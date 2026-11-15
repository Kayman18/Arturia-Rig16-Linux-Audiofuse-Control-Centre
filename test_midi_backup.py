import copy
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig
from midi_config import FIELDS,read_entry,remap
from midi_backup import make_backup,validate,restore_plan,load_backup,MAX_FILE_BYTES,LEGACY_FORMAT
from midi_restore_window import MidiRestoreWindow
import test_midi_config as base

def records():return [read_entry(DemoAF16Rig(),p,i) for p,i in FIELDS]
def backup():return make_backup(records(),True)
def changes(count=2):
    data=backup()
    for e in data['assignments'][:count]:e['raw']=(e['raw']&0xc000)|0x0f7f
    return restore_plan(data,records(),True)

class MidiBackupTests(unittest.TestCase):
    def test_roundtrip_all_71_and_unchanged_plan(self):
        data=backup();self.assertEqual(len(validate(data)),71)
        self.assertEqual(restore_plan(data,records(),True),[])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'backup.json';p.write_text(json.dumps(data))
            self.assertEqual(load_backup(p),data)
    def test_plan_contains_exact_expected_values_and_only_changed_assignments(self):
        plan=changes(71);self.assertEqual(len(plan),71)
        self.assertEqual([(c['parameter'],c['index']) for c in plan],list(FIELDS[2:]))
        for c in plan:self.assertEqual((c['channel'],c['number']),(16,127))
    def test_backup_requires_complete_stable_native_reads(self):
        for bad in (records()[:-1],records()+[records()[2]]):
            with self.assertRaises(ValueError):make_backup(bad)
        for change in ({'stable':False},{'reads':[0,1]},{'reads':[True,True]}):
            bad=records();bad[2].update(change)
            with self.assertRaises(ValueError):make_backup(bad)
    def test_demo_cannot_restore_to_real_hardware(self):
        with self.assertRaisesRegex(ValueError,'Demo'):restore_plan(backup(),records(),False)
    def test_any_type_mismatch_rejects_whole_plan(self):
        data=backup();data['format']=LEGACY_FORMAT;data['assignments'][0]['raw']=0x4001
        data['assignments'][-1]['raw']=0x8001
        with self.assertRaisesRegex(ValueError,'message type differs'):restore_plan(data,records(),True)
    def test_future_encoding_can_be_saved_but_cannot_be_changed(self):
        current=records();current[2].update(raw=0xffff,reads=[0xffff,0xffff])
        data=make_backup(current,True);self.assertEqual(restore_plan(data,current,True),[])
        data['assignments'][0]['raw']=0xfffe
        with self.assertRaisesRegex(ValueError,'unsupported'):restore_plan(data,current,True)
    def test_unknown_reserved_bits_and_bad_number_block_plan(self):
        for raw in (0x5000,0x4080):
            data=backup();data['assignments'][0]['raw']=raw
            with self.assertRaises(ValueError):restore_plan(data,records(),True)
    def test_malformed_or_incomplete_backups_rejected(self):
        for key,value in (('format','other'),('device','other'),('state_version',19),('state_version',True),('demo',0),('assignments',[])):
            data=backup();data[key]=value
            with self.assertRaises(ValueError):validate(data)
        for change in ({'parameter':18},{'index':8},{'raw':65536},{'raw':True},{'parameter':True}):
            data=backup();data['assignments'][0].update(change)
            with self.assertRaises(ValueError):validate(data)
        data=backup();data['assignments'][1]=data['assignments'][0]
        with self.assertRaisesRegex(ValueError,'duplicate'):validate(data)
    def test_file_limits_duplicate_keys_and_excessive_nesting(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.json'
            for content in (b'x'*(MAX_FILE_BYTES+1),b'{"format":"x","format":"y"}',b'['*2000+b']'*2000,b'\xff'):
                p.write_bytes(content)
                with self.assertRaises(ValueError):load_backup(p)

class MidiRestoreTests(unittest.TestCase):
    def dialog(self,count=2):
        parent=base.MidiPageTests().window();parent.records=records();parent.refresh=Mock()
        d=MidiRestoreWindow.__new__(MidiRestoreWindow)
        d.parent=parent;d.app=parent.app;d.changes=changes(count);d.serial=7;d.position=0;d.request=None
        d.busy=False;d.stopped=False;d.closed=False;d.timer=None
        for name in ('window','table','apply','stop','message'):setattr(d,name,Mock())
        d.window.after.return_value='timer';parent.restore_dialog=d
        return d
    def confirmed(self,d,device):
        command,data=d.app.worker.commands.get_nowait();self.assertEqual(command,'midi_remap')
        result=remap(device,data['parameter'],data['index'],data['channel'],data['number'],data['expected'])
        return dict(kind='midi_written',request_id=data['request_id'],connection_serial=7,record=result)
    def test_all_71_restore_one_at_a_time_and_update_confirmed_rows(self):
        d=self.dialog(71);device=DemoAF16Rig();d.start();d.start()
        for i in range(71):
            e=self.confirmed(d,device);self.assertTrue(d.app.worker.commands.empty())
            self.assertTrue(d.handle(e));self.assertEqual(d.position,i+1)
            self.assertTrue(d.app.worker.commands.empty())
            if i<70:d.queue_next()
        self.assertFalse(d.busy);self.assertTrue(d.stopped)
        for r in d.parent.records[2:]:self.assertEqual(r['raw'],0x4f7f)
    def test_failure_stops_after_partial_success_and_invalidates_failed_row(self):
        d=self.dialog();d.start();d.handle(self.confirmed(d,DemoAF16Rig()));d.queue_next()
        _,data=d.app.worker.commands.get_nowait()
        d.handle(dict(kind='midi_error',request_id=data['request_id'],connection_serial=7,message='not confirmed'))
        self.assertEqual(d.position,1);self.assertFalse(d.busy);self.assertFalse(d.parent.records[3]['stable'])
        self.assertTrue(d.app.worker.commands.empty());d.queue_next();self.assertTrue(d.app.worker.commands.empty())
    def test_stop_waits_for_already_sent_assignment_and_never_sends_next(self):
        d=self.dialog();d.start();d.request_stop();self.assertTrue(d.busy)
        d.handle(self.confirmed(d,DemoAF16Rig()));self.assertEqual(d.position,1)
        self.assertFalse(d.busy);self.assertTrue(d.app.worker.commands.empty())
    def test_stop_between_entries_cancels_timer(self):
        d=self.dialog();d.start();d.handle(self.confirmed(d,DemoAF16Rig()));d.request_stop()
        d.window.after_cancel.assert_called_with('timer');d.queue_next();self.assertTrue(d.app.worker.commands.empty())
    def test_reconnect_and_old_reply_cannot_advance_batch(self):
        d=self.dialog();d.start();event=self.confirmed(d,DemoAF16Rig())
        d.app.name_cache.serial=8;d.handle(event)
        self.assertEqual(d.position,0);self.assertFalse(d.busy);self.assertTrue(d.app.worker.commands.empty())
    def test_wrong_request_and_wrong_confirmation_never_advance(self):
        d=self.dialog();d.start();event=self.confirmed(d,DemoAF16Rig())
        self.assertFalse(d.handle(dict(event,request_id='old')));self.assertEqual(d.position,0)
        event['record']=dict(event['record'],raw=0)
        d.handle(event);self.assertEqual(d.position,0);self.assertFalse(d.busy)
    def test_close_cancels_remaining_and_rereads_parent(self):
        d=self.dialog();d.start();event=self.confirmed(d,DemoAF16Rig());d.close()
        self.assertFalse(d.handle(event));self.assertIsNone(d.parent.restore_dialog)
        d.parent.refresh.assert_called_once();d.window.destroy.assert_called_once()
    def test_connection_change_before_start_sends_nothing(self):
        d=self.dialog();d.app.name_cache.serial=8;d.start()
        self.assertFalse(d.busy);self.assertTrue(d.app.worker.commands.empty())
    def test_preview_constructs_without_device_writes(self):
        parent=base.MidiPageTests().window();parent.app.root=Mock()
        with patch('midi_restore_window.tk.Toplevel'),patch('midi_restore_window.ttk.Frame'),patch('midi_restore_window.ttk.Label'),patch('midi_restore_window.ttk.Button'),patch('midi_restore_window.ttk.Treeview'),patch('midi_restore_window.ttk.Scrollbar'):
            d=MidiRestoreWindow(parent,changes())
        self.assertTrue(parent.app.worker.commands.empty());self.assertFalse(d.busy)

class BackupPageTests(unittest.TestCase):
    def window(self):
        w=base.MidiPageTests().window();w.records=records();w.restore_dialog=None;w.pending_edit=None
        return w
    def test_backup_readiness_blocks_missing_changing_pending_or_disconnected(self):
        w=self.window();self.assertTrue(w.backup_ready())
        for field,value in (('pending_edit',{}),('request','busy'),('restore_dialog',Mock())):
            setattr(w,field,value or {'pending':True});self.assertFalse(w.backup_ready());setattr(w,field,None)
        w.records[2]['stable']=False;self.assertFalse(w.backup_ready())
    def test_open_restore_requires_review_not_immediate_write(self):
        w=self.window();data=backup();data['assignments'][0]['raw']=0x4001
        with patch('midi_window.filedialog.askopenfilename',return_value='backup.json'),patch('midi_backup.load_backup',return_value=data),patch('midi_restore_window.MidiRestoreWindow') as preview:
            w.open_restore();preview.assert_called_once()
        self.assertTrue(w.app.worker.commands.empty())
    def test_reconnect_during_picker_does_not_open_preview(self):
        w=self.window()
        def picker(**kw):w.app.name_cache.serial=8;return 'backup.json'
        with patch('midi_window.filedialog.askopenfilename',side_effect=picker),patch('midi_restore_window.MidiRestoreWindow') as preview:
            w.open_restore();preview.assert_not_called()
    def test_save_backup_freezes_before_picker_and_reports_disk_error(self):
        w=self.window()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'backup.json'
            def picker(**kw):w.records=[];return str(p)
            with patch('midi_window.filedialog.asksaveasfilename',side_effect=picker):w.save_backup()
            self.assertEqual(len(validate(load_backup(p))),71)
        w=self.window()
        with patch('midi_window.filedialog.asksaveasfilename',return_value='/x'),patch('midi_window.Path.write_text',side_effect=OSError('disk full')):
            w.save_backup();w.message.config.assert_called_with(text='disk full')
    def test_connection_reset_closes_preview_without_starting_it(self):
        w=self.window();w.restore_dialog=Mock();dialog=w.restore_dialog
        w.connection_changed();dialog.close.assert_called_once_with(refresh=False)

if __name__=='__main__':unittest.main()
