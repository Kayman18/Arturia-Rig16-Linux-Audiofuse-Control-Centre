import queue
import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from name_edit import rename,encode_name,read_name
from test_controls import FakeUSB,Fn

class NameUSB(FakeUSB):
    def __init__(self):
        super().__init__();self.names={**{i:'ANALOG IN' for i in range(16)},**{i:'ADAT IN' for i in range(28,44)},**{i:'ANALOG OUT' for i in range(16,28)},**{i:'ADAT OUT' for i in range(44,60)}};self.ignore=False;self.rc=None;self.out=[]
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            if req==0x92:
                raw=(self.names[param].encode()+b'\0').ljust(32,b'\0')
                data[0:2]=raw[index*2:index*2+2];return 2
            if req==0x1a:
                self.out.append((bm,req,param,index,bytes(data),length))
                if not self.ignore:self.names[param]=bytes(data).rstrip(b'\0').decode()
                return length if self.rc is None else self.rc
            return original(h,bm,req,param,index,data,length,timeout)
        self.libusb_control_transfer=Fn(transfer)

class NameEditTests(unittest.TestCase):
    def setUp(self):
        self.usb=NameUSB();self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        sleeper=patch('name_edit.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def test_exact_native_string_request_and_readback(self):
        r=rename(self.d,3,'Computer','ANALOG IN')
        self.assertEqual(self.usb.out,[(0x40,0x1a,2,0,b'Computer\0',9)])
        self.assertEqual(r['candidate'],'Computer');self.assertTrue(r['rename_confirmed'])
        self.assertEqual(self.usb.names[1],'ANALOG IN')
    def test_stale_name_blocks_out(self):
        with self.assertRaisesRegex(DeviceError,'changed'):rename(self.d,1,'New','Old')
        self.assertEqual(self.usb.out,[])
    def test_unchanged_name_is_noop(self):
        rename(self.d,1,'ANALOG IN','ANALOG IN');self.assertEqual(self.usb.out,[])
    def test_controls_and_limit_are_rejected(self):
        for name in ('bad\nname','bad\0name','x'*16,'é'*8):
            with self.assertRaises(ValueError):rename(self.d,1,name,'ANALOG IN')
        self.assertEqual(self.usb.out,[])
    def test_utf8_byte_limit(self):
        self.assertEqual(encode_name('é'*7),('é'*7).encode()+b'\0')
        self.assertEqual(rename(self.d,1,'Synthé','ANALOG IN')['candidate'],'Synthé')
    def test_blank_name_roundtrip(self):
        r=rename(self.d,1,'','ANALOG IN');self.assertEqual(r['status'],'blank');self.assertEqual(r['candidate'],'')
    def test_failed_readback_never_repeats_out(self):
        self.usb.ignore=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):rename(self.d,1,'New','ANALOG IN')
        self.assertEqual(len(self.usb.out),1)
    def test_timeout_with_confirmed_readback_succeeds(self):
        self.usb.rc=-7
        self.assertTrue(rename(self.d,1,'New','ANALOG IN')['rename_confirmed'])
        self.assertEqual(len(self.usb.out),1)
    def test_disconnect_does_not_retry(self):
        self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):rename(self.d,1,'New','ANALOG IN')
        self.assertEqual(len(self.usb.out),1)
    def test_unknown_version_and_invalid_input_no_out(self):
        with self.assertRaises(ValueError):rename(self.d,33,'New','ANALOG IN')
        self.d.version=19
        with self.assertRaises(DeviceError):rename(self.d,1,'New','ANALOG IN')
        self.assertEqual(self.usb.out,[])
    def test_demo_name_is_reread_without_usb(self):
        d=DemoAF16Rig();rename(d,2,'Synth','Demo input 2')
        self.assertEqual(read_name(d,2)['candidate'],'Synth')
    def test_worker_rejects_previous_connection(self):
        events=queue.Queue();w=Worker(events,factory=lambda:AF16Rig(self.usb));w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        w.commands.put(('connect',None))
        w.commands.put(('name_set',dict(connection_serial=0,source=1,name='New',expected='ANALOG IN',request_id=12)))
        while True:
            e=events.get(timeout=3)
            if e['kind']=='name_write_error':break
        self.assertEqual(e['request_id'],12);self.assertEqual(self.usb.out,[])

if __name__=='__main__':unittest.main()
