import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from af16rig import AF16Rig, DemoAF16Rig, DeviceError, DeviceDisconnected
from channel_names import name_parameter,read_word,read_one,source_label
from name_edit import rename,read_name
from name_sync import NameCache,NameScan
from names_window import NamesWindow
from mixer_view import Strip,Field
from test_name_edit import NameUSB
from test_channel_names import packed


class AdatNamesTests(unittest.TestCase):
    def setUp(self):
        self.usb=NameUSB();self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        sleeper=patch('name_edit.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def test_all_native_adat_parameter_ids(self):
        self.assertEqual([name_parameter(i) for i in range(17,33)],list(range(28,44)))
        self.assertEqual([name_parameter(i) for i in range(1,17)],list(range(16)))
    def test_unmapped_and_usb_names_not_addressable(self):
        for parameter in (60,76,-1,True):
            with self.assertRaises(ValueError):read_word(self.d,parameter,0)
        for source in (0,33,64,True):
            with self.assertRaises(ValueError):rename(self.d,source,'New','Old')
        self.assertEqual(self.usb.out,[])
    def test_rename_every_adat_input_exact_packet(self):
        before={i:self.usb.names[i] for i in range(16)}
        for source in range(17,33):
            name=f'Synth {source-16}'
            record=rename(self.d,source,name,'ADAT IN')
            self.assertEqual(record['source'],source)
            self.assertEqual(record['parameter'],source+11)
            self.assertEqual(record['candidate'],name)
            self.assertEqual(self.usb.out[-1],(0x40,0x1a,source+11,0,name.encode()+b'\0',len(name)+1))
        self.assertEqual({i:self.usb.names[i] for i in range(16)},before)
    def test_automatic_scan_reads_all_inputs_without_output_or_writes(self):
        reads=[]
        def reader(device,parameter,index):
            reads.append((parameter,index));return read_word(device,parameter,index)
        scan=NameScan(self.d,reader=reader);records=[]
        while not scan.done:
            previous=len(reads);record=scan.step()
            self.assertEqual(len(reads),previous+1)
            if record:records.append(record)
        self.assertEqual(len(records),60)
        self.assertEqual({p for p,_ in reads},set(range(60)))
        self.assertEqual(records[31]['candidate'],'ADAT IN');self.assertEqual(self.usb.out,[])
    def test_stale_adat_name_stops_write(self):
        self.usb.names[28]='External edit'
        with self.assertRaisesRegex(DeviceError,'changed'):rename(self.d,17,'New','ADAT IN')
        self.assertEqual(self.usb.out,[])
    def test_ignored_adat_rename_not_retried(self):
        self.usb.ignore=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):rename(self.d,32,'New','ADAT IN')
        self.assertEqual(len(self.usb.out),1)
    def test_adat_disconnect_not_retried(self):
        self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):rename(self.d,17,'New','ADAT IN')
        self.assertEqual(len(self.usb.out),1)
    def test_adat_timeout_with_readback_is_success(self):
        self.usb.rc=-7
        self.assertTrue(rename(self.d,32,'New','ADAT IN')['rename_confirmed'])
        self.assertEqual(len(self.usb.out),1)
    def test_generic_and_blank_adat_names_fall_back(self):
        cache=NameCache();cache.reset(1)
        for text in ('ADAT IN',''):
            words=packed(text)
            cache.accept(1,dict(source=17,passes=[words,words],status='candidate'))
            self.assertEqual(cache.title(17),'ADAT 1')
            self.assertEqual(cache.title(17,True),'ADAT 1/2')
    def test_stereo_adat_names_combine_and_analog_stays_separate(self):
        cache=NameCache();cache.reset(1)
        for source,text in ((1,'Analog synth'),(17,'Digital L'),(18,'Digital R')):
            words=packed(text);cache.accept(1,dict(source=source,passes=[words,words],status='candidate'))
        self.assertEqual(cache.title(17,True),'Digital L / Digital R')
        self.assertEqual(cache.title(1),'Analog synth')
        view=SimpleNamespace(c=SimpleNamespace(source=Field(17),state={'stereo_members':[1,2]},app=SimpleNamespace(name_cache=cache)),title=Field(),mode=Field())
        Strip.refresh_title(view)
        self.assertEqual(view.title.cget('text'),'Digital L / Digital R')
        self.assertEqual(view.mode.cget('text'),'ADAT 1/2\nSTEREO')
    def test_old_connection_cannot_restore_adat_names(self):
        cache=NameCache();cache.reset(2);words=packed('Old synth')
        self.assertFalse(cache.accept(1,dict(source=32,passes=[words,words])))
        self.assertEqual(cache.title(32),'ADAT 16')
    def test_demo_names_use_same_bank_mapping(self):
        d=DemoAF16Rig();rename(d,17,'ADAT synth','Demo ADAT 1')
        scan=NameScan(d,demo=True);records=[]
        while not scan.done:records.append(scan.step())
        self.assertEqual(records[16]['candidate'],'ADAT synth')
        self.assertEqual(records[16]['parameter'],28)
        self.assertEqual(records[0]['candidate'],'Demo input 1')
    def test_manual_refresh_continues_after_analog_bank(self):
        w=NamesWindow.__new__(NamesWindow);w.request_id=10;w.pending=True;w.records=[{}]*15;w.table=Mock();w.next_read=Mock();w.finish=Mock()
        w.handle(dict(kind='name_snapshot',request_id=10,state=dict(source=16,status='candidate',candidate='Last analog')))
        w.next_read.assert_called_once();w.finish.assert_not_called()
    def test_manual_refresh_continues_to_output_banks(self):
        w=NamesWindow.__new__(NamesWindow);w.request_id=10;w.pending=True;w.records=[{}]*31;w.table=Mock();w.next_read=Mock();w.finish=Mock();w.app=SimpleNamespace(demo=False)
        w.handle(dict(kind='name_snapshot',request_id=10,state=dict(source=32,status='candidate',candidate='Last ADAT')))
        w.next_read.assert_called_once();w.finish.assert_not_called()
        self.assertEqual(w.table.insert.call_args.kwargs['values'][0],'ADAT 16')
