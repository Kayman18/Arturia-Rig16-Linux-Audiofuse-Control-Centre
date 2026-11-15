import queue
import unittest
from unittest.mock import Mock
from af16rig import AF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from name_sync import NameScan,NameCache
from test_controls import FakeUSB
from test_channel_names import packed

class SyncTests(unittest.TestCase):
    def test_one_word_per_step_and_all_sources(self):
        reads=[]
        def read(d,p,i):reads.append((p,i));return packed(f'Input {p+1}')[i]
        scan=NameScan(None,reader=read);records=[]
        while not scan.done:
            before=len(reads);record=scan.step();self.assertEqual(len(reads)-before,1)
            if record:records.append(record)
        self.assertEqual([r['source'] for r in records],list(range(1,33))+list(range(65,93)))
        self.assertTrue(all(r['status']=='candidate' for r in records))
        self.assertIsNone(scan.step())
    def test_failure_stops_scan(self):
        read=Mock(side_effect=DeviceError('stall'));scan=NameScan(None,reader=read)
        self.assertEqual(scan.step()['status'],'read_error');self.assertTrue(scan.done)
        scan.step();read.assert_called_once()
    def test_disconnection_is_not_suppressed(self):
        scan=NameScan(None,reader=Mock(side_effect=DeviceDisconnected('gone')))
        with self.assertRaises(DeviceDisconnected):scan.step()
    def test_new_connection_clears_old_labels(self):
        cache=NameCache();cache.reset(1);cache.accept(1,self.record(1,'Synth'))
        cache.reset(2);self.assertEqual(cache.names,{})
        self.assertFalse(cache.accept(1,self.record(1,'Old synth')))
        self.assertEqual(cache.title(1),'ANALOG 1')
    @staticmethod
    def record(source,name):return dict(source=source,status='candidate',candidate='DO NOT TRUST THIS FIELD',passes=[packed(name),packed(name)])
    def test_raw_verified_bytes_supply_label(self):
        cache=NameCache();cache.reset(1);cache.accept(1,self.record(1,'TD-3'))
        self.assertEqual(cache.title(1),'TD-3')
    def test_default_name_falls_back_to_number(self):
        cache=NameCache();cache.reset(1);cache.accept(1,self.record(2,'ANALOG IN'))
        self.assertEqual(cache.title(2),'ANALOG 2')
    def test_stereo_left_name_with_default_right(self):
        cache=NameCache();cache.reset(1);cache.accept(1,self.record(3,'Computer'));cache.accept(1,self.record(4,'ANALOG IN'))
        self.assertEqual(cache.title(3,True),'Computer')
    def test_different_stereo_names_both_preserved(self):
        cache=NameCache();cache.reset(1)
        cache.accept(1,self.record(13,'Deepmind'));cache.accept(1,self.record(14,'MIcrofreak'))
        self.assertEqual(cache.title(13,True),'Deepmind / MIcrofreak')
    def test_equal_pair_names_not_duplicated(self):
        cache=NameCache();cache.reset(1)
        for n in (1,2):cache.accept(1,self.record(n,'Keys'))
        self.assertEqual(cache.title(1,True),'Keys')
    def test_unchanged_name_does_not_trigger_render(self):
        cache=NameCache();cache.reset(1)
        self.assertTrue(cache.accept(1,self.record(1,'Synth')))
        self.assertFalse(cache.accept(1,self.record(1,'Synth')))
    def test_unstable_record_not_used(self):
        cache=NameCache();cache.reset(1);r=self.record(1,'Synth');r['passes'][1]=packed('Other')
        cache.accept(1,r);self.assertEqual(cache.title(1),'ANALOG 1')
    def test_demo_never_used_as_hardware_label(self):
        cache=NameCache();cache.reset(1)
        record=dict(source=1,status='demo',candidate='Example')
        cache.accept(1,record);self.assertEqual(cache.title(1),'ANALOG 1')
        cache.accept(1,record,demo=True);self.assertEqual(cache.title(1),'Example')
    def test_worker_auto_reads_and_restarts_on_reconnect_without_out(self):
        usb=FakeUSB();original=usb.libusb_control_transfer.func
        def transfer(h,bm,req,param,index,data,length,timeout):
            if req==0x92:
                usb.calls.append((bm,req,param,index,bytes(data),length,timeout))
                word=packed(f'Unit {param+1}')[index];data[0]=word&255;data[1]=word>>8;return 2
            return original(h,bm,req,param,index,data,length,timeout)
        usb.libusb_control_transfer.func=transfer
        events=queue.Queue();worker=Worker(events,factory=lambda:AF16Rig(usb));worker.start()
        try:
            for serial in (1,2):
                worker.commands.put(('connect',None));records=[];polls=0
                # Name loading can now finish before the next 500 ms live poll.
                while len(records)<16 or polls<2:
                    event=events.get(timeout=5)
                    if event['kind']=='snapshot':polls+=1
                    if event['kind']=='auto_name' and event['connection_serial']==serial:records.append(event['state'])
                    self.assertNotIn(event['kind'],('error','recovering'))
                self.assertEqual(records[0]['candidate'],'Unit 1');self.assertEqual(records[15]['source'],16)
                self.assertGreaterEqual(polls,2)
            self.assertFalse(any(c[0]==0x40 for c in usb.calls))
        finally:worker.stop_event.set();worker.join(2)

if __name__=='__main__':unittest.main()
