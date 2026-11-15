import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DemoAF16Rig,PARAMETERS,DeviceError
from af16rig_gui import Worker
from preamp import snapshot,change
from preamp_view import PreampControls
from mixer_view import Console,MasterController,Field
from test_controls import FakeUSB

class PreampTests(unittest.TestCase):
    def device(self,detected=0,forced=0):
        usb=FakeUSB()
        for key in ('rear_pad','front_line_pad','front_mic_pad','rear_gain','front_line_gain','front_mic_gain','front_mini_gain','rear_link','front_line_link','front_mic_link'):usb.values[PARAMETERS[key]]=0
        usb.values[PARAMETERS['detect_status']]=detected;usb.values[PARAMETERS['force_rear']]=forced
        d=AF16Rig(usb);d.open();self.addCleanup(d.close);return d,usb
    def test_active_rear_gain_absolute_and_readback(self):
        d,u=self.device();s=change(d,5,'rear','gain',7)
        self.assertEqual(s['value'],7)
        out=[c for c in u.calls if c[0]==0x40]
        self.assertEqual((out[0][1],out[0][2],out[0][3]),(0x11,20,4))
        self.assertEqual(int.from_bytes(out[0][4],'little'),7*256)
    def test_active_front_line_gain_uses_native_units(self):
        d,u=self.device(0x21);s=change(d,1,'line','gain',30)
        self.assertEqual(s['value'],30);self.assertEqual(s['units'],1)
        self.assertEqual(u.values[PARAMETERS['front_line_gain']],30)
    def test_active_mic_gain(self):
        d,u=self.device(0x42);s=change(d,2,'mic','gain',45)
        self.assertEqual(s['value'],45);self.assertEqual(s['kind'],'mic')
    def test_active_mini_gain_and_link_unavailable(self):
        d,u=self.device(0x10);s=change(d,3,'mini','gain',9)
        self.assertEqual(s['value'],9);self.assertFalse(s['link_available'])
    def test_stale_source_prevents_write(self):
        d,u=self.device(0x21)
        with self.assertRaises(DeviceError):change(d,1,'rear','gain',5)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))
    def test_mixed_front_modes_disable_pair_link(self):
        d,u=self.device(0x41)
        self.assertFalse(snapshot(d,1)['link_available'])
        with self.assertRaises(DeviceError):change(d,1,'line','link',True)
    def test_gain_range_and_version_guards(self):
        d,u=self.device()
        for val in (-1,13,1.5,True):
            with self.assertRaises(DeviceError):change(d,5,'rear','gain',val)
        d.version=19
        with self.assertRaises(DeviceError):change(d,5,'rear','gain',5)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))
    def test_demo_front_rear_gain_and_link(self):
        d=DemoAF16Rig()
        self.assertEqual(change(d,5,'rear','gain',6)['value'],6)
        self.assertEqual(change(d,5,'rear','link',True)['link'],1)
        d.force_rear=0
        self.assertEqual(change(d,1,'line','gain',40)['value'],40)
        self.assertEqual(change(d,3,'mini','gain',8)['value'],8)
    def test_front_detection_without_plug_can_be_switched_back(self):
        d,u=self.device(0,0)
        state=snapshot(d,1)
        self.assertEqual(state['kind'],'rear');self.assertEqual(state['forced_rear'],0)
        obj=PreampControls.__new__(PreampControls)
        obj.app=SimpleNamespace(dashboard=SimpleNamespace(preamp_states={1:state},preamp_pending=set()),worker=SimpleNamespace(commands=queue.Queue()))
        obj.source_button=Mock();obj.source_button.cget.return_value='normal';obj.refresh=Mock()
        obj.toggle_source()
        self.assertEqual(obj.app.worker.commands.get_nowait(),('preamp_source',True))
    def test_front_source_button_switches_pair_not_one_channel(self):
        d=DemoAF16Rig();d.set_rear_pair_source(1,True)
        self.assertEqual(snapshot(d,1)['forced_rear'],3)
        d.set_rear_pair_source(1,False)
        self.assertEqual(snapshot(d,2)['forced_rear'],0)
    def test_master_has_independent_poll_schedule(self):
        q=queue.Queue();v=SimpleNamespace(active=True,app=SimpleNamespace(connected=True,worker=SimpleNamespace(commands=q),root=Mock()),master_inflight=False,next_master_read=0,inflight=('main',8),next_read=0,tick=Mock())
        Console.tick(v)
        self.assertEqual(q.get_nowait(),('masters_read',None));self.assertTrue(q.empty())
        Console.tick(v);self.assertTrue(q.empty())
    def test_master_drag_handle_moves_before_readback(self):
        from test_drag import GestureTests
        w=GestureTests().widget();w.preview_drag=True;w.draw=Mock()
        w.drag(SimpleNamespace(y=100,state=0))
        self.assertEqual(w.visual_target,0);self.assertEqual(w.value,-30)
        w.draw.assert_called_once()
    def test_master_live_snapshot_updates_fader_model(self):
        app=SimpleNamespace(connected=True,message=Field(),worker=SimpleNamespace(commands=queue.Queue()))
        c=MasterController(app);d=DemoAF16Rig();d.set_console_value('main',0,'master',-7*256)
        v=SimpleNamespace(master=c,master_inflight=True,next_master_read=0)
        Console.handle(v,dict(kind='masters_snapshot',state=d.mixer_masters_snapshot()))
        self.assertEqual(c.state['levels']['main']['db'],-7);self.assertFalse(v.master_inflight)
    def test_worker_front_rear_and_preamp_write_readback(self):
        events=queue.Queue();w=Worker(events,demo=True);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        w.commands.put(('connect',None));w.commands.put(('preamp_source',False))
        while True:
            e=events.get(timeout=3)
            if e['kind']=='preamp_state':break
        self.assertEqual([s['forced_rear'] for s in e['states']],[0,0])
        w.commands.put(('preamp_set',(1,'line','gain',25)))
        while True:
            e=events.get(timeout=3)
            if e['kind']=='preamp_state':break
        self.assertEqual(e['states'][0]['value'],25)

if __name__=='__main__':unittest.main()
