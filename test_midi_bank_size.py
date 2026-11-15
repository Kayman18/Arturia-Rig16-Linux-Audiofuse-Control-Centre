import unittest,queue
from unittest.mock import patch,Mock
import test_midi_remap as base
from midi_config import FIELDS,read_entry,set_bank_size
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from reconnect import READ_COMMANDS

class BankSizeTests(unittest.TestCase):
    @patch('midi_config.time.sleep')
    def test_all_64_transitions_exact_packet_and_no_other_writes(self,sleep):
        for old in range(1,9):
            for new in range(1,9):
                d,words,calls=base.RemapTests().device(old)
                r=set_bank_size(d,new,old)
                self.assertEqual(r['raw'],new);self.assertTrue(r['stable'])
                outs=[c for c in calls if c[0]==0x40]
                self.assertEqual(outs,[] if old==new else [(0x40,0x13,18,0,new.to_bytes(2,'little'))])
                self.assertTrue(all(v==old for k,v in words.items() if k!=(18,0)))
    def test_invalid_values_and_version_do_not_touch_usb(self):
        d,words,calls=base.RemapTests().device(8)
        for bad in (True,0,9,-1,1.5,'4',None):
            for target,expected in ((bad,8),(4,bad)):
                with self.assertRaises(ValueError):set_bank_size(d,target,expected)
        d.version=19
        with self.assertRaises(DeviceError):set_bank_size(d,4,8)
        self.assertEqual(calls,[])
    def test_stale_and_unstable_preflight_never_write(self):
        d,words,calls=base.RemapTests().device(8)
        with self.assertRaises(DeviceError):set_bank_size(d,4,7)
        with patch('midi_config.read_entry',return_value=dict(raw=8,stable=False)),self.assertRaises(DeviceError):set_bank_size(d,4,8)
        self.assertFalse(any(c[0]==0x40 for c in calls))
    @patch('midi_config.time.sleep')
    def test_failed_or_disconnected_out_not_retried(self,sleep):
        for rc,error in ((2,DeviceError),(-4,DeviceDisconnected)):
            d,words,calls=base.RemapTests().device(8,accept=False,out_rc=rc)
            with self.assertRaises(error):set_bank_size(d,4,8)
            self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    @patch('midi_config.time.sleep')
    def test_uncertain_out_can_confirm_by_readback(self,sleep):
        d,words,calls=base.RemapTests().device(8,out_rc=-7)
        self.assertEqual(set_bank_size(d,4,8)['raw'],4)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    def test_worker_connection_guard_and_demo_roundtrip(self):
        self.assertNotIn('midi_bank_size',READ_COMMANDS)
        events=queue.Queue();d=DemoAF16Rig();w=Worker(events,factory=lambda:d);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        def until(kind):
            for _ in range(200):
                e=events.get(timeout=3)
                if e['kind']==kind:return e
            self.fail('Missing '+kind)
        w.commands.put(('connect',None));serial=until('connected')['connection_serial']
        data=dict(target=4,expected=8,request_id='bank',connection_serial=serial-1)
        w.commands.put(('midi_bank_size',data));until('midi_error')
        self.assertEqual(read_entry(d,18,0)['raw'],8)
        w.commands.put(('midi_bank_size',dict(data,connection_serial=serial)))
        self.assertEqual(until('midi_written')['record']['raw'],4)
    def window(self):
        w=base.EditPageTests().window();d=DemoAF16Rig()
        w.records=[read_entry(d,p,i) for p,i in FIELDS]
        w.bank_size=Mock();w.bank_size.get.return_value='4';w.bank_apply=Mock()
        return w
    def test_ui_sends_once_and_does_not_guess_state(self):
        w=self.window();w.apply_bank_size();w.apply_bank_size()
        cmd,data=w.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'midi_bank_size');self.assertEqual((data['target'],data['expected'],data['connection_serial']),(4,8,7))
        self.assertTrue(w.app.worker.commands.empty());self.assertEqual(w.records[0]['raw'],8)
    def test_ui_reloads_after_confirmation(self):
        w=self.window();w.apply_bank_size();req=w.pending_edit['request_id'];w.refresh=Mock()
        record=read_entry(DemoAF16Rig(),18,0);record['raw']=4
        w.handle(dict(kind='midi_written',record=record,request_id=req,connection_serial=7))
        w.refresh.assert_called_once();self.assertIsNone(w.pending_edit)
    def test_ui_error_blocks_retry_until_refresh(self):
        w=self.window();w.apply_bank_size();req=w.pending_edit['request_id']
        w.handle(dict(kind='midi_error',message='Rejected',request_id=req,connection_serial=7))
        self.assertFalse(w.bank_ready());self.assertFalse(w.records[0]['stable'])
    def test_ui_guards_incomplete_capture_and_reconnect(self):
        for attr,value in (('closed',True),('request','capture'),('serial',6)):
            w=self.window();setattr(w,attr,value);w.apply_bank_size();self.assertTrue(w.app.worker.commands.empty())
        w=self.window();w.records.pop();w.apply_bank_size();self.assertTrue(w.app.worker.commands.empty())
        w=self.window();w.bank_size.get.return_value='8';w.apply_bank_size();self.assertTrue(w.app.worker.commands.empty())

if __name__=='__main__':unittest.main()
