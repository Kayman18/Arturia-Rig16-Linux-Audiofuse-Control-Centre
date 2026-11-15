import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import DeviceError,DeviceDisconnected,DemoAF16Rig
from af16rig_gui import Worker
from midi_config import FIELDS,read_entry,remap,editable
from midi_window import MidiWindow
from reconnect import READ_COMMANDS
import test_midi_config as base

class RemapTests(unittest.TestCase):
    def device(self,initial=0x4207,accept=True,out_rc=2):
        words={key:initial for key in FIELDS};calls=[]
        def transfer(handle,bm,req,p,i,data,length,timeout):
            calls.append((bm,req,p,i,bytes(data)))
            if bm==0xc0:data[:]=words[p,i].to_bytes(2,'little');return 2
            if accept:words[p,i]=int.from_bytes(data,'little')
            return out_rc
        d=SimpleNamespace(version=18,lock=threading.RLock(),handle=1,lib=SimpleNamespace(libusb_control_transfer=transfer))
        return d,words,calls
    @patch('midi_config.time.sleep')
    def test_all_71_assignment_indices_write_exactly_once(self,sleep):
        for p,i in FIELDS[2:]:
            d,words,calls=self.device();r=remap(d,p,i,16,127,0x4207)
            self.assertEqual(r['raw'],0x4f7f);self.assertTrue(r['stable'])
            outs=[c for c in calls if c[0]==0x40]
            self.assertEqual(outs,[(0x40,0x13,p,i,b'\x7f\x4f')]);self.assertTrue(d.last_write['confirmed'])
            self.assertEqual(sum(v!=0x4207 for v in words.values()),1)
    @patch('midi_config.time.sleep')
    def test_supported_type_bits_preserved(self,sleep):
        for kind in range(3):
            initial=kind<<14|0x807;d,words,calls=self.device(initial)
            r=remap(d,20,0,1,0,initial);self.assertEqual(r['raw'],kind<<14)
    def test_noop_and_stale_preflight_send_no_out(self):
        d,words,calls=self.device();r=remap(d,20,0,3,7,0x4207)
        self.assertEqual(r['raw'],0x4207);self.assertFalse(any(c[0]==0x40 for c in calls))
        with self.assertRaises(DeviceError):remap(d,20,0,3,8,0x4208)
        self.assertFalse(any(c[0]==0x40 for c in calls))
    def test_unstable_preflight_stops_before_out(self):
        d,words,calls=self.device();unstable=dict(read_entry(DemoAF16Rig(),20,0),raw=0x4207,stable=False)
        with patch('midi_config.read_entry',return_value=unstable),self.assertRaises(DeviceError):
            remap(d,20,0,1,8,0x4207)
        self.assertEqual(calls,[])
    def test_invalid_fields_and_future_encodings_do_not_read_or_write(self):
        d,words,calls=self.device()
        for p,i,ch,n,expected in ((18,0,1,0,8),(19,0,1,0,0),(20,8,1,0,0x4000),(20,0,0,1,0x4000),(20,0,17,1,0x4000),(20,0,True,1,0x4000),(20,0,1,128,0x4000),(20,0,1,-1,0x4000),(20,0,1,True,0x4000),(20,0,1,2,0xffff),(20,0,1,2,0x5000),(20,0,1,2,0x4080)):
            with self.assertRaises(ValueError):remap(d,p,i,ch,n,expected)
        self.assertEqual(calls,[])
    def test_unsupported_version_does_not_read_or_write(self):
        d,words,calls=self.device();d.version=19
        with self.assertRaises(DeviceError):remap(d,20,0,2,8,0x4207)
        self.assertEqual(calls,[])
    @patch('midi_config.time.sleep')
    def test_failed_confirmation_never_repeats_out(self,sleep):
        d,words,calls=self.device(accept=False)
        with self.assertRaises(DeviceError):remap(d,20,0,1,8,0x4207)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1);self.assertFalse(d.last_write['confirmed'])
        self.assertEqual(len(d.last_write['readback_attempts']),4)
    @patch('midi_config.time.sleep')
    def test_uncertain_out_may_confirm_only_by_reads(self,sleep):
        d,words,calls=self.device(out_rc=-7)
        self.assertEqual(remap(d,20,0,1,8,0x4207)['raw'],0x4008)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    def test_disconnect_out_propagates_without_retry(self):
        d,words,calls=self.device(accept=False,out_rc=-4)
        with self.assertRaises(DeviceDisconnected):remap(d,20,0,1,8,0x4207)
        self.assertEqual(len(calls),3)
    def test_demo_edit_is_local_and_readable(self):
        d=DemoAF16Rig();old=read_entry(d,20,0)['raw']
        self.assertEqual(remap(d,20,0,16,74,old)['raw'],0x4f4a)
        self.assertEqual(read_entry(d,20,0)['number_code'],74)
        self.assertIsNone(d.last_write)
    def test_worker_rejects_stale_generation_and_does_not_classify_edit_as_read(self):
        self.assertNotIn('midi_remap',READ_COMMANDS)
        events=queue.Queue();d=DemoAF16Rig();w=Worker(events,factory=lambda:d);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        def until(kind):
            for _ in range(200):
                e=events.get(timeout=3)
                if e['kind']==kind:return e
            self.fail('Missing '+kind)
        w.commands.put(('connect',None));serial=until('connected')['connection_serial']
        data=dict(parameter=20,index=0,channel=16,number=74,expected=0x4000,request_id='edit',connection_serial=serial-1)
        w.commands.put(('midi_remap',data));until('midi_error');self.assertEqual(read_entry(d,20,0)['raw'],0x4000)
        w.commands.put(('midi_remap',dict(data,connection_serial=serial)))
        self.assertEqual(until('midi_written')['record']['raw'],0x4f4a)

class EditPageTests(unittest.TestCase):
    def window(self):
        w=base.MidiPageTests().window();w.records=[read_entry(DemoAF16Rig(),20,0)];w.pending_edit=None
        w.table.selection.return_value=('0',)
        for name in ('apply_button','channel_entry','number_entry','edit_label','edit_channel','edit_number'):setattr(w,name,Mock())
        w.edit_channel.get.return_value='16';w.edit_number.get.return_value='74';return w
    def test_apply_sends_one_guarded_target_no_optimistic_state(self):
        w=self.window();before=dict(w.records[0]);w.apply_edit();w.apply_edit()
        cmd,data=w.app.worker.commands.get_nowait();self.assertEqual(cmd,'midi_remap')
        self.assertEqual((data['channel'],data['number'],data['expected'],data['connection_serial']),(16,74,0x4000,7))
        self.assertEqual(w.records[0],before);self.assertTrue(w.app.worker.commands.empty())
    def test_success_replaces_only_confirmed_row(self):
        w=self.window();w.apply_edit();request=w.pending_edit['request_id']
        d=DemoAF16Rig();record=remap(d,20,0,16,74,0x4000)
        w.handle(dict(kind='midi_written',request_id=request,connection_serial=7,record=record))
        self.assertIsNone(w.pending_edit);self.assertEqual(w.records[0]['raw'],0x4f4a)
        w.apply_button.config.assert_called_with(state='normal')
    def test_error_blocks_that_assignment_until_refresh(self):
        w=self.window();w.apply_edit();request=w.pending_edit['request_id']
        w.handle(dict(kind='midi_error',request_id=request,connection_serial=7,message='not confirmed'))
        self.assertFalse(w.records[0]['stable']);self.assertIsNone(w.pending_edit)
        w.apply_button.config.assert_called_with(state='disabled')
    def test_invalid_unchanged_and_pending_capture_do_not_send(self):
        for channel,number in (('0','7'),('17','7'),('x','1'),('1','128'),('1','0')):
            w=self.window();w.edit_channel.get.return_value=channel;w.edit_number.get.return_value=number
            w.apply_edit();self.assertTrue(w.app.worker.commands.empty())
        w=self.window();w.request='capture';w.apply_edit();self.assertTrue(w.app.worker.commands.empty())
    def test_refresh_while_edit_pending_is_ignored_and_reconnect_cancels_it(self):
        w=self.window();w.apply_edit();request=w.pending_edit['request_id'];before=list(w.records)
        w.refresh();self.assertEqual(w.records,before)
        w.app.name_cache.serial=8;w.connection_changed();self.assertIsNone(w.pending_edit);self.assertEqual(w.records,[])
        w.handle(dict(kind='midi_written',request_id=request,connection_serial=7,record=read_entry(DemoAF16Rig(),20,0)))
        self.assertEqual(w.records,[])
    def test_pending_write_blocks_export(self):
        w=self.window();w.apply_edit()
        with patch('midi_window.filedialog.asksaveasfilename') as picker:
            w.save();picker.assert_not_called()
        w.save_button.config.assert_called_with(state='disabled')
    def test_closed_page_cannot_apply(self):
        w=self.window();w.closed=True;w.apply_edit();self.assertTrue(w.app.worker.commands.empty())

if __name__=='__main__':unittest.main()
