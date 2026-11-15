import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from af16rig import AF16Rig, DemoAF16Rig, DeviceError, PARAMETERS
from af16rig_gui import App, Worker
from mixer_view import ValueControl
from test_controls import FakeUSB

class DragTests(unittest.TestCase):
    def setUp(self):
        self.usb=FakeUSB();self.device=AF16Rig(self.usb);self.device.open()
    def tearDown(self):self.device.close()
    def test_large_mono_drag_uses_one_write(self):
        self.assertEqual(self.device.set_console_value('main',1,'level',-4*256),-4*256)
        self.assertEqual(len([c for c in self.usb.calls if c[0]==0x40]),1)
    def test_aux_absolute_target(self):
        self.assertEqual(self.device.set_console_value('main',2,'send3',-7*256),-7*256)
        self.assertEqual(self.usb.values[PARAMETERS['aux3_send_level']],(-7*256)&65535)
    def test_pan_absolute_target(self):
        self.assertEqual(self.device.set_console_value('cue',1,'pan',200),200)
    def test_master_absolute_target(self):
        self.assertEqual(self.device.set_console_value('aux4',0,'master',-3*256),-3*256)
    def test_out_of_range_no_write(self):
        for args in [('main',1,'level',7*256),('main',1,'pan',255),('main',0,'master',256),('main',1,'send2',-61*256)]:
            with self.assertRaises(ValueError):self.device.set_console_value(*args)
        self.assertFalse(any(c[0]==0x40 for c in self.usb.calls))
    def test_changed_selection_rejected(self):
        self.usb.values[PARAMETERS['main_channel_show']]=0
        with self.assertRaises(DeviceError):self.device.set_console_value('main',1,'level',0)
        self.assertFalse(any(c[0]==0x40 for c in self.usb.calls))
    def test_readback_mismatch_rejected(self):
        self.usb.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.set_console_value('main',1,'level',0)
    def test_stereo_preserves_offset_and_clamps_both(self):
        self.usb.values[PARAMETERS['main_channel_show']]=0
        self.usb.values[PARAMETERS['main_channel_stereo']]=1
        levels={0:(-12*256)&65535,1:(-8*256)&65535}
        orig=self.usb.libusb_control_transfer.func
        def transfer(h,bm,req,param,index,data,length,timeout):
            if (req-(0x90 if bm==0xc0 else 0x10),param)==PARAMETERS['main_channel_level']:
                if bm==0x40:levels[index]=int.from_bytes(data,'little')
                else:data[0],data[1]=levels[index]&255,levels[index]>>8
                return 2
            return orig(h,bm,req,param,index,data,length,timeout)
        self.usb.libusb_control_transfer.func=transfer
        self.assertEqual(self.device.set_console_value('main',1,'level',6*256,True),[2*256,6*256])
    def test_demo_master_survives_snapshot(self):
        d=DemoAF16Rig();d.set_console_value('main',0,'master',-256)
        self.assertEqual(d.mixer_masters_snapshot()['levels']['main']['signed'],-256)

class GestureTests(unittest.TestCase):
    def widget(self,kind='fader'):
        w=ValueControl.__new__(ValueControl)
        w.kind=kind;w.high=6;w.low=-60;w.valid=True;w.ready=True;w.value=-30
        w.drag_origin=(200,-30);w.desired=None;w.flush_id=None
        w.winfo_height=lambda:266
        w.after=Mock(return_value='timer');w.after_cancel=Mock()
        w.target_callback=Mock(return_value=True)
        return w
    def test_fader_tracks_pointer_distance(self):
        w=self.widget();w.drag(SimpleNamespace(y=100,state=0))
        self.assertEqual(w.desired,0)
    def test_knob_full_range_in_120_pixels(self):
        w=self.widget('dial');w.drag_origin=(200,-60)
        w.drag(SimpleNamespace(y=80,state=0));self.assertEqual(w.desired,6)
    def test_shift_fine_drag(self):
        w=self.widget();w.drag(SimpleNamespace(y=100,state=1));self.assertEqual(w.desired,-27)
    def test_pending_drag_coalesces_to_latest_position(self):
        w=self.widget();w.ready=False
        w.drag(SimpleNamespace(y=150,state=0));w.drag(SimpleNamespace(y=100,state=0))
        w.flush_target();w.target_callback.assert_not_called()
        w.ready=True;w.flush_target();w.target_callback.assert_called_once_with(0)
        self.assertIsNone(w.desired)
    def test_error_cancels_unsent_drag(self):
        w=self.widget();w.desired=0;w.flush_id='timer';w.cancel_drag()
        w.flush_target();w.target_callback.assert_not_called()
    def test_navigation_restores_mixer_even_if_panel_cleanup_fails(self):
        panel=SimpleNamespace(close=Mock(side_effect=RuntimeError('cleanup')))
        frame=Mock();dashboard=SimpleNamespace(active=False,frame=frame,next_source=12,next_read=10)
        app=SimpleNamespace(page_host=SimpleNamespace(winfo_children=lambda:[frame]),input_window=panel,dashboard=dashboard,worker=SimpleNamespace(commands=queue.Queue()),page_title=Mock())
        with self.assertRaises(RuntimeError):App.show_mixer(app)
        self.assertTrue(dashboard.active);frame.pack.assert_called_once();frame.lift.assert_called_once()
        self.assertIsNone(app.input_window)
    def test_navigation_restores_mixer_normally(self):
        panel=SimpleNamespace(close=Mock());frame=Mock()
        app=SimpleNamespace(page_host=SimpleNamespace(winfo_children=lambda:[frame]),input_window=panel,dashboard=SimpleNamespace(active=False,frame=frame),worker=SimpleNamespace(commands=queue.Queue()),page_title=Mock())
        App.show_mixer(app)
        panel.close.assert_called_once();self.assertTrue(app.dashboard.active)

if __name__=='__main__':unittest.main()
