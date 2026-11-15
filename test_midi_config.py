import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from midi_config import FIELDS,read_entry,decode
from midi_window import MidiWindow
from af16rig_gui import Worker

class MidiRegisterTests(unittest.TestCase):
    def device(self,values=(0x4207,0x4207),rc=2):
        calls=[];values=iter(values)
        def transfer(handle,bm,req,param,index,data,length,timeout):
            calls.append((bm,req,param,index,length))
            if rc==2:data[:]=next(values).to_bytes(2,'little')
            return rc
        return SimpleNamespace(version=18,lock=threading.RLock(),handle=1,lib=SimpleNamespace(libusb_control_transfer=transfer)),calls
    def test_all_73_entries_only_use_bounded_in_reads(self):
        self.assertEqual(len(FIELDS),73);self.assertEqual(len(set(FIELDS)),73)
        for p,i in FIELDS:
            d,calls=self.device();r=read_entry(d,p,i)
            self.assertTrue(r['stable']);self.assertEqual(calls,[(0xc0,0x93,p,i,2)]*2)
    def test_packing_preserves_all_bits_and_does_not_invent_type_labels(self):
        for raw in (0,0xffff,0x4207,0xb300):
            r=decode(20,7,raw)
            rebuilt=r['number_code']+(r['channel_code']<<8)+(r['type_code']<<14)+r['reserved_bits']
            self.assertEqual(rebuilt,raw);self.assertEqual(r['strip'],8)
            self.assertNotIn('type_name',r)
        self.assertEqual(decode(20,0,0x4207)['channel_code'],2)
        self.assertEqual(decode(20,0,0x4207)['number_code'],7)
    def test_headers_are_not_decoded_as_assignments(self):
        for p in (18,19):
            r=decode(p,0,65535);self.assertEqual(r['value'],65535);self.assertNotIn('type_code',r)
    def test_changes_are_reported_without_retry(self):
        d,calls=self.device((1,2));r=read_entry(d,28,0)
        self.assertFalse(r['stable']);self.assertEqual(r['reads'],[1,2]);self.assertEqual(len(calls),2)
    def test_bad_indices_and_versions_send_nothing(self):
        d,calls=self.device()
        for p,i in ((17,0),(35,0),(18,1),(20,8),(28,1),(20,-1),(True,0),(20,True)):
            with self.assertRaises(ValueError):read_entry(d,p,i)
        self.assertEqual(calls,[]);d.version=17
        with self.assertRaises(DeviceError):read_entry(d,20,0)
        self.assertEqual(calls,[])
    def test_short_read_and_disconnect_stop_immediately(self):
        for rc,error in ((1,DeviceError),(-4,DeviceDisconnected),(-9,DeviceError)):
            d,calls=self.device(rc=rc)
            with self.assertRaises(error):read_entry(d,20,0)
            self.assertEqual(len(calls),1)
    def test_demo_is_marked_synthetic(self):
        d=DemoAF16Rig()
        for p,i in FIELDS:self.assertTrue(read_entry(d,p,i)['demo'])
    def test_worker_generation_guard_and_read_dispatch(self):
        events=queue.Queue();w=Worker(events,factory=DemoAF16Rig);w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        def until(kind):
            for _ in range(200):
                e=events.get(timeout=3)
                if e['kind']==kind:return e
            self.fail('Missing '+kind)
        w.commands.put(('connect',None));serial=until('connected')['connection_serial']
        data=dict(parameter=20,index=0,request_id='one',connection_serial=serial-1)
        w.commands.put(('midi_read',data));self.assertEqual(until('midi_error')['request_id'],'one')
        data=dict(data,connection_serial=serial)
        w.commands.put(('midi_read',data));self.assertEqual(until('midi_snapshot')['record']['parameter'],20)

class MidiPageTests(unittest.TestCase):
    def window(self):
        w=MidiWindow.__new__(MidiWindow);w.closed=False;w.records=[];w.position=0;w.request=None;w.serial=7;w.error=None
        w.app=SimpleNamespace(connected=True,demo=True,name_cache=SimpleNamespace(serial=7),worker=SimpleNamespace(commands=queue.Queue()))
        w.table=Mock();w.table.get_children.return_value=[]
        w.refresh_button=Mock();w.save_button=Mock();w.summary=Mock();w.message=Mock();w.window=Mock()
        w.started_utc='test';return w
    def test_construct_page_queues_only_selection_and_first_read(self):
        app=SimpleNamespace(connected=True,demo=True,name_cache=SimpleNamespace(serial=9),worker=SimpleNamespace(commands=queue.Queue()),make_panel=Mock(return_value=Mock()))
        with patch('midi_window.tk.StringVar'),patch('midi_window.ttk.Frame'),patch('midi_window.ttk.Label'),patch('midi_window.ttk.Button'),patch('midi_window.ttk.Scrollbar'),patch('midi_window.ttk.Treeview') as table:
            table.return_value.get_children.return_value=[]
            w=MidiWindow(app)
        self.assertEqual(app.worker.commands.get_nowait(),('input_select',None))
        command,data=app.worker.commands.get_nowait();self.assertEqual(command,'midi_read')
        self.assertEqual(data['connection_serial'],9);self.assertTrue(app.worker.commands.empty())
    def test_save_cancel_and_disk_failure(self):
        w=self.window();w.records=[read_entry(DemoAF16Rig(),18,0)]
        with patch('midi_window.filedialog.asksaveasfilename',return_value=''),patch('midi_window.Path.write_text') as write:
            w.save();write.assert_not_called()
        with patch('midi_window.filedialog.asksaveasfilename',return_value='/x'),patch('midi_window.Path.write_text',side_effect=OSError('disk full')):
            w.save();w.message.config.assert_called_with(text='disk full')
    def test_whole_capture_advances_one_entry_at_a_time(self):
        w=self.window();w.refresh();d=DemoAF16Rig()
        for p,i in FIELDS:
            command,data=w.app.worker.commands.get_nowait();self.assertEqual(command,'midi_read')
            self.assertTrue(w.app.worker.commands.empty())
            self.assertEqual((data['parameter'],data['index']),(p,i))
            w.handle(dict(kind='midi_snapshot',request_id=data['request_id'],connection_serial=7,record=read_entry(d,p,i)))
        self.assertEqual(len(w.records),73);self.assertIsNone(w.request);self.assertTrue(w.app.worker.commands.empty())
    def test_stale_reply_and_old_request_are_ignored(self):
        w=self.window();w.refresh();request=w.request
        e=dict(kind='midi_snapshot',request_id=request,connection_serial=6,record=read_entry(DemoAF16Rig(),18,0))
        w.handle(e);self.assertEqual(w.records,[])
        w.handle(dict(e,connection_serial=7,request_id='other'));self.assertEqual(w.records,[])
    def test_error_stops_scan_and_preserves_partial_records(self):
        w=self.window();w.refresh();w.app.worker.commands.get_nowait()
        w.handle(dict(kind='midi_error',request_id=w.request,connection_serial=7,message='stalled'))
        self.assertEqual(w.error,'stalled');self.assertTrue(w.app.worker.commands.empty());self.assertIsNone(w.request)
    def test_reconnect_invalidates_previous_scan(self):
        w=self.window();w.refresh();old=w.request;w.records=[{'old':True}]
        w.app.name_cache.serial=8;w.connection_changed()
        self.assertEqual(w.records,[]);self.assertEqual(w.serial,8);self.assertNotEqual(w.request,old)
    def test_disconnect_clears_and_does_not_queue_reads(self):
        w=self.window();w.records=[{'old':True}];w.app.connected=False;w.app.name_cache.serial=None
        w.handle(dict(kind='input_error',channel='midi',message='Device disconnected'))
        self.assertEqual(w.records,[]);self.assertTrue(w.app.worker.commands.empty())
        w.save_button.config.assert_called_with(state='disabled')
    def test_save_freezes_partial_capture_before_dialog(self):
        w=self.window();w.records=[read_entry(DemoAF16Rig(),18,0)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'midi.json'
            def picker(**kwargs):w.records=[];w.serial=8;return str(path)
            with patch('midi_window.filedialog.asksaveasfilename',side_effect=picker):w.save()
            d=json.loads(path.read_text());self.assertEqual(d['connection_serial'],7)
            self.assertEqual(len(d['records']),1);self.assertFalse(d['complete']);self.assertFalse(d['export_writes_device'])
    def test_close_ignores_late_events(self):
        w=self.window();w.refresh();request=w.request;w.close()
        w.handle(dict(kind='midi_snapshot',request_id=request,connection_serial=7,record=read_entry(DemoAF16Rig(),18,0)))
        self.assertEqual(w.records,[]);w.window.destroy.assert_called_once()

if __name__=='__main__':unittest.main()
