import unittest,queue
from unittest.mock import Mock,patch
from types import SimpleNamespace
import test_midi_remap as base
from midi_ports import OPTIONS,SCALAR_OPTIONS,PARAMETERS,snapshot,set_option,read_word
from midi_ports_window import MidiPortsWindow
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from reconnect import READ_COMMANDS

class PortTests(unittest.TestCase):
    def device(self,old=0,accept=True,rc=2):
        d,words,calls=base.RemapTests().device(old,accept,rc)
        words.update({(5,0):old,(6,0):old,(7,0):old,(16,0):old});words.update({(p,i):0 for p in (12,13) for i in (4,5,6,7)});return d,words,calls
    @patch('midi_ports.time.sleep')
    def test_all_supported_transitions_exact_packets(self,sleep):
        for field,options in SCALAR_OPTIONS.items():
            for old in range(len(options)):
                for new in range(len(options)):
                    d,words,calls=self.device(old)
                    result=set_option(d,field,new,old)
                    self.assertEqual(result[field]['raw'],new);self.assertTrue(result[field]['stable'])
                    outs=[c for c in calls if c[0]==0x40]
                    self.assertEqual(outs,[] if old==new else [(0x40,0x11,PARAMETERS[field],0,new.to_bytes(2,'little'))])
                    self.assertTrue(all(c[1]==0x91 for c in calls if c[0]==0xc0))
    def test_invalid_and_stale_targets_do_not_write(self):
        d,words,calls=self.device()
        for field,target,expected in [('other',0,0),('host_cable',16,0),('din_clock',4,0),('din_clock',True,0),('din_clock',1,-1)]:
            with self.assertRaises(ValueError):set_option(d,field,target,expected)
        self.assertEqual(calls,[])
        with self.assertRaises(DeviceError):set_option(d,'din_clock',2,1)
        self.assertFalse(any(c[0]==0x40 for c in calls))
    def test_unstable_or_future_version_blocks_writes(self):
        d,words,calls=self.device()
        with patch('midi_ports.read_word',side_effect=[0,1]),self.assertRaises(DeviceError):set_option(d,'din_clock',2,0)
        d.version=19
        with self.assertRaises(DeviceError):set_option(d,'din_clock',2,0)
        self.assertEqual(calls,[])
    @patch('midi_ports.time.sleep')
    def test_rejected_write_is_never_retried(self,sleep):
        d,words,calls=self.device(accept=False)
        with self.assertRaises(DeviceError):set_option(d,'din_clock',2,0)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    @patch('midi_ports.time.sleep')
    def test_uncertain_out_and_disconnect(self,sleep):
        d,words,calls=self.device(rc=-7)
        self.assertEqual(set_option(d,'host_cable',15,0)['host_cable']['raw'],15)
        d,words,calls=self.device(accept=False,rc=-4)
        with self.assertRaises(DeviceDisconnected):set_option(d,'host_cable',15,0)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    def test_short_read_and_unknown_values(self):
        d,words,calls=self.device(65535)
        self.assertEqual(snapshot(d)['host_cable']['raw'],65535)
        d.lib.libusb_control_transfer=Mock(return_value=1)
        with self.assertRaises(DeviceError):snapshot(d)
    def test_worker_guards_and_roundtrip(self):
        self.assertNotIn('midi_ports_set',READ_COMMANDS)
        events=queue.Queue();d=DemoAF16Rig();w=Worker(events,factory=lambda:d);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        def until(kind):
            for _ in range(200):
                e=events.get(timeout=3)
                if e['kind']==kind:return e
            self.fail(kind)
        w.commands.put(('connect',None));serial=until('connected')['connection_serial']
        data=dict(request_id='p',connection_serial=serial,field='host_cable',target=15,expected=0)
        w.commands.put(('midi_ports_set',dict(data,connection_serial=serial-1)));until('midi_error');self.assertEqual(read_word(d,'host_cable'),0)
        w.commands.put(('midi_ports_set',data));self.assertEqual(until('midi_ports_written')['records']['host_cable']['raw'],15)
        w.commands.put(('midi_ports_read',data));self.assertEqual(until('midi_ports_snapshot')['records']['host_cable']['raw'],15)

class PortPageTests(unittest.TestCase):
    def window(self):
        parent=base.EditPageTests().window();w=MidiPortsWindow.__new__(MidiPortsWindow)
        w.parent=parent;w.app=parent.app;w.serial=7;w.closed=False;w.request=None;w.records=snapshot(DemoAF16Rig())
        w.selectors={f:Mock() for f in OPTIONS};w.buttons={f:Mock() for f in OPTIONS};w.values={f:Mock() for f in OPTIONS}
        for f in OPTIONS:w.selectors[f].current.return_value=1
        w.message=Mock();w.refresh_button=Mock();w.window=Mock();return w
    def test_edit_single_flight_and_no_optimistic_update(self):
        w=self.window();w.apply('din_clock');w.apply('host_cable')
        cmd,data=w.app.worker.commands.get_nowait();self.assertEqual(cmd,'midi_ports_set');self.assertEqual(data['expected'],0)
        self.assertTrue(w.app.worker.commands.empty());self.assertEqual(w.records['din_clock']['raw'],0)
    def test_result_updates_readback_and_errors_disable_until_refresh(self):
        w=self.window();w.apply('din_clock');req=w.request
        actual=set_option(DemoAF16Rig(),'din_clock',1,0)
        self.assertTrue(w.handle(dict(kind='midi_ports_written',request_id=req,connection_serial=7,records=actual)))
        self.assertEqual(w.records['din_clock']['raw'],1)
        w.apply('host_cable');req=w.request;w.handle(dict(kind='midi_error',request_id=req,connection_serial=7,message='failed'))
        self.assertEqual(w.records,{});w.buttons['host_cable'].config.assert_called_with(state='disabled')
    def test_unknown_reconnect_and_close_block_writes(self):
        w=self.window();w.records['host_cable']['raw']=65535;w.apply('host_cable');self.assertTrue(w.app.worker.commands.empty())
        w=self.window();w.app.name_cache.serial=8;w.apply('din_clock');self.assertTrue(w.app.worker.commands.empty())
        w=self.window();w.close();w.apply('din_clock');self.assertTrue(w.app.worker.commands.empty())
    def test_stale_request_does_not_update(self):
        w=self.window();w.apply('din_clock');req=w.request
        self.assertFalse(w.handle(dict(kind='midi_error',request_id='old',message='old')));self.assertEqual(w.request,req)

if __name__=='__main__':unittest.main()
