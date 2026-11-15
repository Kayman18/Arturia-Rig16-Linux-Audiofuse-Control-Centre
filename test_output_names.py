import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from channel_names import name_parameter,NAME_SOURCES,NAME_SOURCE_COUNT,source_label,read_word
from name_edit import rename,read_name
from name_sync import NameCache,NameScan
from names_window import NamesWindow
from routing_names import named_label
from patchbay_window import PatchBayWindow
from test_name_edit import NameUSB
from test_channel_names import packed

class OutputNameTests(unittest.TestCase):
    def setUp(self):
        self.usb=NameUSB();self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        sleeper=patch('name_edit.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def test_catalog_is_complete_and_does_not_alias_usb_inputs(self):
        self.assertEqual(NAME_SOURCE_COUNT,60)
        self.assertEqual(set(map(name_parameter,NAME_SOURCES)),set(range(60)))
        self.assertEqual(len(set(NAME_SOURCES)),60)
        self.assertTrue(set(range(33,65)).isdisjoint(NAME_SOURCES))
    def test_every_output_rename_exact_packet_and_input_preservation(self):
        before={i:self.usb.names[i] for i in list(range(16))+list(range(28,44))}
        for source in range(65,93):
            expected='ANALOG OUT' if source<=76 else 'ADAT OUT';name=f'Output {source-64}'
            record=rename(self.d,source,name,expected)
            parameter=source-49 if source<=76 else source-33
            self.assertEqual(record['parameter'],parameter)
            self.assertEqual(self.usb.out[-1],(0x40,0x1a,parameter,0,name.encode()+b'\0',len(name)+1))
        self.assertEqual({i:self.usb.names[i] for i in before},before)
    def test_stale_output_name_blocks_write(self):
        with self.assertRaises(DeviceError):rename(self.d,77,'Synth','Old name')
        self.assertEqual(self.usb.out,[])
    def test_ignored_output_write_sent_once(self):
        self.usb.ignore=True
        with self.assertRaises(DeviceError):rename(self.d,92,'Synth','ADAT OUT')
        self.assertEqual(len(self.usb.out),1)
    def test_disconnect_during_output_rename_stops(self):
        self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):rename(self.d,65,'Synth','ANALOG OUT')
        self.assertEqual(len(self.usb.out),1)
    def test_all_60_names_auto_read_without_writes(self):
        scan=NameScan(self.d);records=[]
        while not scan.done:
            record=scan.step()
            if record:records.append(record)
        self.assertEqual([r['source'] for r in records],list(NAME_SOURCES))
        self.assertEqual(records[-1]['parameter'],59);self.assertEqual(self.usb.out,[])
    def test_cache_blank_and_generic_output_names_fall_back(self):
        cache=NameCache();cache.reset(1)
        for source,text in ((65,'ANALOG OUT'),(77,'ADAT OUT'),(92,'')):
            words=packed(text);cache.accept(1,dict(source=source,status='candidate',passes=[words,words]))
            self.assertEqual(cache.title(source),source_label(source))
            self.assertNotIn(source,cache.names)
    def test_demo_output_names_separate_from_input_names(self):
        d=DemoAF16Rig();rename(d,65,'Monitor','Demo out 1');rename(d,77,'Processor','Demo out 13')
        self.assertEqual(read_name(d,1)['candidate'],'Demo input 1')
        self.assertEqual(read_name(d,65)['candidate'],'Monitor')
        self.assertEqual(read_name(d,77)['candidate'],'Processor')
    def test_manual_refresh_skips_usb_name_id_gap(self):
        w=NamesWindow.__new__(NamesWindow);w.records=[{}]*32;w.request_id=7;w.message=Mock();w.app=SimpleNamespace(worker=SimpleNamespace(commands=Mock()))
        w.next_read();w.app.worker.commands.put.assert_called_once_with(('name_read',(7,65)))
    def test_manual_refresh_completes_at_final_output(self):
        w=NamesWindow.__new__(NamesWindow);w.records=[{}]*59;w.request_id=7;w.pending=True;w.table=Mock();w.finish=Mock();w.next_read=Mock();w.app=SimpleNamespace(demo=False)
        w.handle(dict(kind='name_snapshot',request_id=7,state=dict(source=92,status='candidate',candidate='Processor')))
        w.finish.assert_called_once();w.next_read.assert_not_called()
        self.assertEqual(w.table.insert.call_args.kwargs['values'][0],'ADAT OUT 16')
    def test_patch_labels_keep_verified_native_port_identity(self):
        cache=SimpleNamespace(names={1:'Synth',17:'Digital synth',77:'Processor',92:'Recorder'})
        self.assertEqual(named_label(cache,'source',64),'Analog 1 · Synth')
        self.assertEqual(named_label(cache,'source',80),'ADAT 1 · Digital synth')
        self.assertEqual(named_label(cache,'dest',12),'ADAT1 · Processor')
        self.assertEqual(named_label(cache,'dest',27),'ADAT16 · Recorder')
        self.assertEqual(named_label(cache,'source',128),'USB 1')
    def test_unverified_analog_output_order_not_assumed(self):
        cache=SimpleNamespace(names={s:f'Output {s}' for s in range(65,77)})
        self.assertEqual(named_label(cache,'dest',0),'Speakers L')
        self.assertEqual(named_label(cache,'dest',2),'Analog1')
        self.assertEqual(named_label(cache,'dest',10),'Phones L')
    def test_name_refresh_updates_only_text_without_interrupting_drag(self):
        w=PatchBayWindow.__new__(PatchBayWindow);w.app=SimpleNamespace(name_cache=SimpleNamespace(names={1:'Synth',77:'Processor'}))
        w.source_points={64:(10,10)};w.destination_points={12:(20,20)};w.state={'reads':{'second':{'values':{'output_source[12]':64}}}}
        w.canvas=Mock();w.canvas.itemcget.return_value='Old';w.route_label=Mock();w.selected_destination=12;w.armed_source=64;w.drag_source=64;w.drag_destination=None;w.draw=Mock()
        w.refresh_names()
        self.assertEqual(w.canvas.itemconfigure.call_count,2);w.canvas.delete.assert_not_called();w.draw.assert_not_called()
        self.assertEqual(w.drag_source,64);self.assertEqual(w.armed_source,64)
        self.assertEqual(w.routes(),{12:64})
        w.canvas.itemcget.side_effect=lambda tag,key: 'Analog 1 · Synth' if tag=='name_source_64' else 'ADAT1 · Processor'
        w.canvas.itemconfigure.reset_mock();w.refresh_names();w.canvas.itemconfigure.assert_not_called()
    def test_stale_connection_cannot_insert_output_label(self):
        cache=NameCache();cache.reset(2);words=packed('Old output')
        self.assertFalse(cache.accept(1,dict(source=77,passes=[words,words])))
        self.assertEqual(named_label(cache,'dest',12),'ADAT1')
