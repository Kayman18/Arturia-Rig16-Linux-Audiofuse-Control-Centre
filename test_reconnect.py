import queue,time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from reconnect import ReconnectPolicy
from af16rig_gui import Worker,App
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected

class PolicyTests(unittest.TestCase):
    def test_backoff_and_cap(self):
        p=ReconnectPolicy();p.start();self.assertEqual([p.failed(0) for _ in range(7)],[1,2,5,10,30,30,30])
        self.assertFalse(p.due(29));self.assertTrue(p.due(30))
    def test_success_resets_backoff(self):
        p=ReconnectPolicy();p.start();p.failed(0);p.failed(0);p.success()
        self.assertIsNone(p.deadline);self.assertEqual(p.failed(100),1)
    def test_no_initial_unsolicited_connection(self):
        p=ReconnectPolicy();self.assertIsNone(p.failed(0));self.assertFalse(p.due(999))
    def test_disable_cancels_pending_retry(self):
        p=ReconnectPolicy();p.start();p.failed(0);p.set_enabled(False)
        self.assertFalse(p.due(999));self.assertIsNone(p.failed(999))
    def test_explicit_disconnect_stops_intent(self):
        p=ReconnectPolicy();p.start();p.failed(0);p.stop();p.set_enabled(True)
        self.assertFalse(p.due(999));self.assertIsNone(p.failed(999))
    def test_manual_connect_restarts_attempt_count(self):
        p=ReconnectPolicy();p.start();p.failed(0);p.failed(0);p.start();self.assertEqual(p.failed(10),1)

class Device(DemoAF16Rig):
    def __init__(self,fail_open=False,fail_snapshot=False,fail_write=False):
        super().__init__();self.fail_open=fail_open;self.fail_snapshot=fail_snapshot;self.fail_write=fail_write;self.writes=[];self.closed=0
    def open(self):
        if self.fail_open:raise DeviceError('Not attached')
    def close(self):self.closed+=1
    def snapshot(self):
        if self.fail_snapshot:raise DeviceDisconnected('Unplugged')
        return super().snapshot()
    def write_bool(self,name,value):
        self.writes.append((name,value))
        if self.fail_write:raise DeviceDisconnected('Disconnected after OUT')
        return super().write_bool(name,value)

class WorkerReconnectTests(unittest.TestCase):
    def worker(self,factory):
        out=queue.Queue();w=Worker(out,factory=factory);w.reconnect.DELAYS=(.02,.04,.06);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)));return w,out
    def wait(self,out,kind):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            e=out.get(timeout=3)
            if e['kind']==kind:return e
        self.fail('Missing '+kind)
    def test_failed_open_retries_and_rebuilds_connection_state(self):
        devices=[Device(fail_open=True),Device()];factory=Mock(side_effect=devices)
        w,out=self.worker(factory);w.commands.put(('connect',None))
        self.wait(out,'reconnect_wait');event=self.wait(out,'connected')
        self.assertEqual(factory.call_count,2);self.assertEqual(event['connection_serial'],1)
        self.assertIsNotNone(w.names_scan);self.assertEqual(w.reconnect.failures,0);self.assertEqual(devices[1].writes,[])
    def test_recovery_gets_new_generation_and_fresh_snapshot(self):
        first,second=Device(),Device();factory=Mock(side_effect=[first,second]);w,out=self.worker(factory)
        w.commands.put(('connect',None));one=self.wait(out,'connected');self.wait(out,'snapshot')
        first.fail_snapshot=True;w.next_poll=0
        self.wait(out,'error');two=self.wait(out,'connected');self.wait(out,'snapshot')
        self.assertGreater(two['connection_serial'],one['connection_serial']);self.assertEqual(second.writes,[])
    def test_interrupted_and_queued_writes_never_replayed(self):
        first,second=Device(fail_write=True),Device();w,out=self.worker(Mock(side_effect=[first,second]))
        w.commands.put(('connect',None));self.wait(out,'connected')
        w.commands.put(('set',('mute',True)));w.commands.put(('set',('dim',True)))
        self.wait(out,'error');self.wait(out,'connected');self.wait(out,'snapshot')
        self.assertEqual(first.writes,[('mute',True)]);self.assertEqual(second.writes,[])
    def test_auto_off_stops_attempts_but_manual_connect_still_works(self):
        first,second=Device(fail_open=True),Device();factory=Mock(side_effect=[first,second]);w,out=self.worker(factory)
        w.commands.put(('auto_reconnect',False));w.commands.put(('connect',None));self.wait(out,'error')
        # A control acknowledgement proves the worker remains responsive while offline.
        w.commands.put(('auto_reconnect',False));self.wait(out,'reconnect_disabled');self.assertEqual(factory.call_count,1)
        w.commands.put(('connect',None));self.wait(out,'connected');self.assertEqual(factory.call_count,2)
    def test_explicit_disconnect_does_not_reconnect(self):
        factory=Mock(return_value=Device());w,out=self.worker(factory);w.commands.put(('connect',None));self.wait(out,'connected')
        w.commands.put(('disconnect',None));self.wait(out,'disconnected')
        self.assertFalse(w.reconnect.wanted);self.assertIsNone(w.reconnect.deadline)
        w.commands.put(('auto_reconnect',False));self.wait(out,'reconnect_disabled');self.assertEqual(factory.call_count,1)
    def test_open_without_initial_snapshot_does_not_emit_connected(self):
        first,second=Device(fail_snapshot=True),Device();w,out=self.worker(Mock(side_effect=[first,second]))
        w.commands.put(('connect',None));events=[]
        while True:
            e=out.get(timeout=3);events.append(e)
            if e['kind']=='connected':break
        self.assertTrue(any(e['kind']=='reconnect_wait' for e in events));self.assertEqual(sum(e['kind']=='connected' for e in events),1)
    def test_discard_retains_settings_and_reads_only(self):
        w=Worker(queue.Queue());commands=[('set',('mute',True)),('meters_enable',True),('name_set',{}),('console_read',('main',1)),('input_select','clock'),('auto_reconnect',False),('future_unknown_write',{})]
        for cmd in commands:w.commands.put(cmd)
        w.discard_pending_writes();kept=[]
        while not w.commands.empty():kept.append(w.commands.get_nowait()[0])
        self.assertEqual(kept,['meters_enable','console_read','input_select','auto_reconnect'])
        self.assertEqual(w.output.get_nowait()['count'],3)
    def test_rejected_write_does_not_trigger_reconnect(self):
        d=Device();d.write_bool=Mock(side_effect=DeviceError('Rejected'))
        factory=Mock(return_value=d);w,out=self.worker(factory);w.commands.put(('connect',None));self.wait(out,'connected')
        w.commands.put(('set',('mute',True)));self.wait(out,'command_error')
        self.assertIs(w.device,d);self.assertIsNone(w.reconnect.deadline);self.assertEqual(factory.call_count,1)
    def test_offline_write_is_discarded_before_later_connection(self):
        d=Device();w,out=self.worker(lambda:d)
        w.commands.put(('set',('mute',True)));self.wait(out,'commands_discarded')
        w.commands.put(('connect',None));self.wait(out,'connected');self.assertEqual(d.writes,[])
    def test_shutdown_cancels_retry(self):
        factory=Mock(return_value=Device(fail_open=True));w,out=self.worker(factory)
        w.commands.put(('connect',None));self.wait(out,'reconnect_wait');w.stop_event.set();w.join(2)
        self.assertFalse(w.is_alive());self.assertEqual(factory.call_count,1)

class NavigationTests(unittest.TestCase):
    def test_return_to_mixer_restarts_selected_digital_bank(self):
        app=SimpleNamespace(input_window=None,worker=SimpleNamespace(commands=queue.Queue()),dashboard=SimpleNamespace(active=False,bank_start=49,frame=Mock(),next_source=0,next_read=99),page_title=Mock())
        with patch('mixer_view.show_page'):App.show_mixer(app)
        self.assertEqual(app.dashboard.next_source,49);self.assertTrue(app.dashboard.active)
