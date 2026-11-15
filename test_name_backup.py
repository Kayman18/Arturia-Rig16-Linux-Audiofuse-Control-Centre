import copy,json,queue,tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DeviceError
from channel_names import NAME_SOURCES,name_parameter
from name_edit import read_name,rename
from name_backup import make_backup,validate,restore_plan,stable_name,load_backup,MAX_FILE_BYTES
from name_restore_window import NameRestoreWindow
from test_name_edit import NameUSB
from test_channel_names import packed

def record(source,name):
    words=packed(name)
    return dict(source=source,parameter=name_parameter(source),candidate='untrusted field',status='candidate',passes=[words,words])

class BackupTests(unittest.TestCase):
    def test_all_60_names_roundtrip(self):
        records=[record(s,f'Name {i}') for i,s in enumerate(NAME_SOURCES)]
        data=make_backup(records);entries=validate(json.loads(json.dumps(data)))
        self.assertEqual(len(entries),60);self.assertEqual([e['source'] for e in entries],list(NAME_SOURCES))
        self.assertEqual(entries[-1]['name'],'Name 59')
    def test_export_uses_actual_readback_bytes(self):
        self.assertEqual(make_backup([record(1,'Synth')])['names'][0]['name'],'Synth')
    def test_blank_and_unicode_roundtrip(self):
        data=make_backup([record(1,''),record(77,'Synthé')]);self.assertEqual([e['name'] for e in validate(data)],['','Synthé'])
    def test_unstable_or_unterminated_reads_not_saved(self):
        r=record(1,'Synth');r['passes'][1]=packed('Other')
        with self.assertRaises(DeviceError):make_backup([r])
        r['passes']=[[1],[1]]
        with self.assertRaises(DeviceError):make_backup([r])
    def test_invalid_source_parameter_duplicates_and_control_text(self):
        original=make_backup([record(1,'Synth')])
        for update in ({'source':33},{'source':True},{'parameter':28},{'name':'bad\nname'},{'name':'x'*32}):
            data=copy.deepcopy(original);data['names'][0].update(update)
            with self.assertRaises(ValueError):validate(data)
        data=copy.deepcopy(original);data['names']*=2
        with self.assertRaises(ValueError):validate(data)
    def test_wrong_device_and_schema_rejected(self):
        original=make_backup([record(1,'Synth')])
        for key,value in [('format','routing'),('device','Other'),('state_version',19),('demo','false'),('names',[])]:
            data=copy.deepcopy(original);data[key]=value
            with self.assertRaises(ValueError):validate(data)
    def test_long_existing_names_can_be_archived_but_changed_restore_is_blocked(self):
        data=make_backup([record(1,'Long equipment label')])
        self.assertEqual(restore_plan(data,{1:record(1,'Long equipment label')}),[])
        with self.assertRaisesRegex(ValueError,'15-byte'):restore_plan(data,{1:record(1,'Other')})
    def test_plan_skips_unchanged_and_only_includes_saved_sources(self):
        data=make_backup([record(1,'Same'),record(77,'New')])
        plan=restore_plan(data,{1:record(1,'Same'),77:record(77,'Old'),92:record(92,'Unrelated')})
        self.assertEqual(plan,[dict(source=77,expected='Old',name='New')])
    def test_missing_current_read_prevents_restore(self):
        with self.assertRaisesRegex(DeviceError,'Refresh names'):restore_plan(make_backup([record(77,'New')]),{})
    def test_demo_backup_cannot_target_hardware(self):
        data=make_backup([dict(source=1,status='demo',candidate='Example')],demo=True)
        with self.assertRaisesRegex(ValueError,'Demo'):restore_plan(data,{1:record(1,'Synth')})
    def test_file_size_and_json_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'backup.json';path.write_bytes(b'x'*(MAX_FILE_BYTES+1))
            with self.assertRaisesRegex(ValueError,'too large'):load_backup(path)
            path.write_text('{bad')
            with self.assertRaises(ValueError):load_backup(path)
            data=make_backup([record(1,'Synth')]);path.write_text(json.dumps(data));self.assertEqual(load_backup(path),data)
    def test_complete_restore_writes_names_only(self):
        usb=NameUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close)
        data=make_backup([record(s,f'Saved {i}') for i,s in enumerate(NAME_SOURCES)])
        records={s:read_name(d,s) for s in NAME_SOURCES};changes=restore_plan(data,records)
        with patch('name_edit.time.sleep'):
            for c in changes:rename(d,c['source'],c['name'],c['expected'])
        self.assertEqual(len(usb.out),60);self.assertTrue(all(call[1]==0x1a for call in usb.out))
        self.assertEqual({call[2] for call in usb.out},set(range(60)))

class RestoreBatchTests(unittest.TestCase):
    def window(self):
        w=NameRestoreWindow.__new__(NameRestoreWindow)
        w.changes=[dict(source=1,name='First',expected='Old1'),dict(source=77,name='Second',expected='Old2')]
        w.position=0;w.request_id=None;w.busy=False;w.stop_requested=False;w.closed=False;w.timer=None;w.serial=3
        w.app=SimpleNamespace(connected=True,name_cache=SimpleNamespace(serial=3),worker=SimpleNamespace(commands=queue.Queue()))
        w.parent=SimpleNamespace(edit_feedback=None,editing=True,read_button=Mock(),refresh_names=Mock(),restore_dialog=w,message=Mock())
        w.window=Mock();w.window.after.return_value='timer';w.table=Mock();w.apply=Mock();w.stop=Mock();w.message=Mock()
        return w
    def test_start_sends_only_one_and_waits_for_confirmation(self):
        w=self.window();w.start();w.start()
        self.assertEqual(w.app.worker.commands.qsize(),1)
        cmd,data=w.app.worker.commands.get_nowait();self.assertEqual(cmd,'name_set');self.assertEqual(data['source'],1)
        self.assertEqual(data['expected'],'Old1');self.assertEqual(data['connection_serial'],3)
        w.handle(dict(kind='name_written',request_id=w.request_id))
        self.assertEqual(w.position,1);self.assertTrue(w.app.worker.commands.empty());w.window.after.assert_called_once_with(120,w.queue_next)
        w.queue_next();self.assertEqual(w.app.worker.commands.get_nowait()[1]['source'],77)
    def test_failed_write_stops_remaining_names(self):
        w=self.window();w.start();w.app.worker.commands.get_nowait()
        w.handle(dict(kind='name_write_error',request_id=w.request_id,message='Changed externally'))
        self.assertTrue(w.app.worker.commands.empty());self.assertFalse(w.busy);self.assertEqual(w.position,0);self.assertTrue(w.stop_requested)
        w.window.after.assert_not_called()
    def test_stop_during_write_waits_for_current_result(self):
        w=self.window();w.start();w.request_stop();self.assertTrue(w.busy)
        w.handle(dict(kind='name_written',request_id=w.request_id));self.assertFalse(w.busy);self.assertEqual(w.position,1)
        self.assertEqual(w.app.worker.commands.qsize(),1);w.window.after.assert_not_called()
    def test_stop_between_names_cancels_timer(self):
        w=self.window();w.start();w.handle(dict(kind='name_written',request_id=w.request_id));w.request_stop()
        w.window.after_cancel.assert_called_once_with('timer');self.assertFalse(w.busy)
    def test_close_prevents_any_next_name(self):
        w=self.window();w.start();w.close();w.queue_next()
        self.assertEqual(w.app.worker.commands.qsize(),1);self.assertIsNone(w.parent.restore_dialog)
        self.assertIn('already-sent',w.parent.edit_feedback)
    def test_connection_change_prevents_next_name(self):
        w=self.window();w.app.name_cache.serial=4;w.start()
        self.assertTrue(w.app.worker.commands.empty());self.assertFalse(w.busy)
    def test_wrong_request_id_does_not_advance(self):
        w=self.window();w.start()
        self.assertFalse(w.handle(dict(kind='name_written',request_id=-1)));self.assertEqual(w.position,0);self.assertTrue(w.busy)
    def test_disconnect_stops_without_claiming_current_write_failed(self):
        w=self.window();w.start();w.handle(dict(kind='input_error',channel='names',message='Disconnected'))
        self.assertFalse(w.busy);self.assertIn('uncertain',w.parent.edit_feedback)
    def test_completion_counts_only_confirmed_names(self):
        w=self.window();w.start();w.handle(dict(kind='name_written',request_id=w.request_id));w.queue_next();w.handle(dict(kind='name_written',request_id=w.request_id))
        self.assertEqual(w.position,2);self.assertFalse(w.busy);self.assertIn('2/2 names confirmed',w.parent.edit_feedback)
    def test_finished_dialog_keeps_parent_editor_locked_until_close(self):
        w=self.window();w.start();w.handle(dict(kind='name_write_error',request_id=w.request_id,message='Stopped'))
        self.assertTrue(w.parent.editing)
        w.close();self.assertFalse(w.parent.editing)
    def test_old_connection_result_not_counted_as_confirmation(self):
        w=self.window();w.start();w.app.name_cache.serial=4
        w.handle(dict(kind='name_written',request_id=w.request_id,connection_serial=3))
        self.assertEqual(w.position,0);self.assertFalse(w.busy);self.assertTrue(w.stop_requested)
