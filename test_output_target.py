import unittest
import math
import queue
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError
from output_target import set_level
from test_controls import FakeUSB,Fn
from af16rig_gui import OutputWindow,Worker

class OutputTargetTests(unittest.TestCase):
    def device(self):
        usb=FakeUSB();usb.outputs={i:0 for i in range(8)};usb.values[1,32]=0
        original=usb.libusb_control_transfer
        def transfer(handle,bm,req,param,index,data,length,timeout):
            if (req,param) not in ((0x91,33),(0x11,33)):return original(handle,bm,req,param,index,data,length,timeout)
            usb.calls.append((bm,req,param,index,bytes(data),length,timeout))
            if bm==0xc0:data[:2]=usb.outputs[index].to_bytes(2,'little')
            elif not usb.ignore_writes:usb.outputs[index]=int.from_bytes(data,'little')
            return 2
        usb.libusb_control_transfer=Fn(transfer)
        d=AF16Rig(usb);d.open();self.addCleanup(d.close);return d,usb
    def test_exact_fractional_output_write_and_other_channels_unchanged(self):
        d,u=self.device();before=dict(u.values)
        self.assertEqual(set_level(d,3,-12.25,0),-3136)
        self.assertEqual(d.read('output_gain',0),(-3136)&65535)
        for ch in range(1,8):self.assertEqual(d.read('output_gain',ch),0)
        self.assertEqual(d.read('speaker_level'),before[(3,0)])
    def test_all_eight_output_indices(self):
        d,u=self.device()
        for ch in range(3,11):
            set_level(d,ch,-2.5,0);self.assertEqual(d.read('output_gain',ch-3),(-640)&65535)
    def test_stale_expected_value_prevents_write(self):
        d,u=self.device();d._write_and_confirm('output_gain',(-256)&65535,0);u.calls.clear()
        with self.assertRaises(DeviceError):set_level(d,3,-5,0)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))
    def test_identical_target_sends_no_out(self):
        d,u=self.device();u.calls.clear();self.assertEqual(set_level(d,3,0,0),0)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))
    def test_invalid_target_or_channel_never_writes(self):
        d,u=self.device();u.calls.clear()
        for ch,value in ((2,-3),(11,-3),(True,-3),(3,math.nan),(3,1),(3,-61)):
            with self.assertRaises(ValueError):set_level(d,ch,value,0)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))
    def test_unsupported_state_version(self):
        d,u=self.device();d.version=19;u.calls.clear()
        with self.assertRaises(DeviceError):set_level(d,3,-3,0)
        self.assertEqual(u.calls,[])
    def test_demo_uses_separate_state(self):
        d=DemoAF16Rig();set_level(d,7,-9.5,0)
        self.assertEqual(d.output_snapshot(7)['level_db'],-9.5);self.assertEqual(d.output_snapshot(8)['level_db'],0)
    def test_unconfirmed_target_is_not_repeated(self):
        d,u=self.device();u.ignore_writes=True;u.calls.clear()
        with patch('af16rig.time.sleep'),self.assertRaises(DeviceError):set_level(d,3,-9,0)
        self.assertEqual(sum(c[0]==0x40 for c in u.calls),1)
    def test_worker_rejects_old_connection_then_accepts_current_target(self):
        events=queue.Queue();d=DemoAF16Rig();w=Worker(events,factory=lambda:d);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        def until(kind):
            for _ in range(100):
                e=events.get(timeout=3)
                if e['kind']==kind:return e
            self.fail('Missing '+kind)
        w.commands.put(('connect',None));serial=until('connected')['connection_serial']
        w.commands.put(('output_target',(3,-8,0,serial-1)))
        self.assertEqual(until('input_error')['name'],'level');self.assertEqual(d.output_snapshot(3)['level_db'],0)
        w.commands.put(('output_target',(3,-8.25,0,serial)))
        self.assertEqual(until('input_written')['actual'],-2112)

class OutputEntryTests(unittest.TestCase):
    def window(self):
        w=OutputWindow.__new__(OutputWindow);w.pending=False;w.state={'writes_available':True,'level_signed':0,'level_db':0}
        w.app=SimpleNamespace(connected=True,name_cache=SimpleNamespace(serial=4),worker=SimpleNamespace(commands=Mock()))
        w.window=Mock();w.output=Mock();w.output.get.return_value=3;w.refresh=Mock();w.message=Mock();return w
    def test_numeric_entry_queues_generation_and_expected_readback(self):
        w=self.window()
        with patch('tkinter.simpledialog.askfloat',return_value=-8.3):w.set_level()
        w.app.worker.commands.put.assert_called_once_with(('output_target',(3,-8.25,0,4)))
        self.assertTrue(w.pending);self.assertEqual(w.state['level_db'],0)
    def test_cancel_or_unchanged_entry_sends_nothing(self):
        for v in (None,0):
            w=self.window()
            with patch('tkinter.simpledialog.askfloat',return_value=v):w.set_level()
            w.app.worker.commands.put.assert_not_called()
    def test_reconnection_during_dialog_cancels_entry(self):
        w=self.window()
        def dialog(*a,**kw):w.app.name_cache.serial=5;return -6
        with patch('tkinter.simpledialog.askfloat',side_effect=dialog):w.set_level()
        w.app.worker.commands.put.assert_not_called()
    def test_nan_is_rejected_without_write(self):
        w=self.window()
        with patch('tkinter.simpledialog.askfloat',return_value=math.nan),patch('tkinter.messagebox.showerror') as error:
            w.set_level();error.assert_called_once()
        w.app.worker.commands.put.assert_not_called()

if __name__=='__main__':unittest.main()
