import queue
import struct
import time
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from af16rig import AF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from meters import decode_frame,read_frame,meter_db,Ballistics
from test_controls import FakeUSB,Fn
from mixer_view import Console

class MeterUSB(FakeUSB):
    def __init__(self):
        super().__init__();original=self.libusb_control_transfer
        self.meter_calls=[];self.result=236
        def transfer(handle,kind,request,value,index,data,length,timeout):
            if request!=0xc0:return original(handle,kind,request,value,index,data,length,timeout)
            self.meter_calls.append((kind,request,value,index,length,timeout))
            frame=struct.pack('<118H',*range(118))
            for i,b in enumerate(frame):data[i]=b
            return self.result
        self.libusb_control_transfer=Fn(transfer)

class MeterTests(unittest.TestCase):
    def test_channel_offsets(self):
        f=decode_frame(struct.pack('<118H',*range(118)))
        for name,start,count in [('inputs',0,32),('outputs',32,8),('speakers',40,2),('phones',42,2),('adat_outputs',44,16),('main',60,2),('aux',62,4),('cue',66,2),('usb',68,32),('loopback',100,2),('immersive',102,16)]:
            self.assertEqual(f[name],[v/32767 for v in range(start,start+count)])
    def test_native_unsigned_range_is_preserved(self):
        f=decode_frame(struct.pack('<118H',*([65535]*118)))
        self.assertGreater(f['main'][0],1)
        self.assertEqual(meter_db(f['main'][0]),0)
    def test_reject_short_and_long_frames(self):
        for n in (0,204,234,238):
            with self.assertRaises(DeviceError):decode_frame(bytes(n))
    def test_usb_is_single_read_bounded_timeout(self):
        usb=MeterUSB();device=AF16Rig(usb);device.open()
        self.addCleanup(device.close);read_frame(device)
        self.assertEqual(usb.meter_calls,[(0xc0,0xc0,0,0,236,20)])
        self.assertFalse(any(c[0]==0x40 for c in usb.calls))
    def test_errors_and_disconnect(self):
        usb=MeterUSB();device=AF16Rig(usb);device.open();self.addCleanup(device.close)
        for rc,kind in [(-7,DeviceError),(200,DeviceError),(-4,DeviceDisconnected)]:
            usb.result=rc
            with self.assertRaises(kind):read_frame(device)
    def test_unsupported_version_no_usb(self):
        usb=MeterUSB();d=AF16Rig(usb);d.open();d.version=19;self.addCleanup(d.close)
        with self.assertRaises(DeviceError):read_frame(d)
        self.assertEqual(usb.meter_calls,[])
    def test_db_silence_half_and_full_scale(self):
        self.assertEqual(meter_db(0),-60);self.assertEqual(meter_db(1),0)
        self.assertAlmostEqual(meter_db(.5),-6.020599913)
    def test_fast_attack_release_peak_and_stale(self):
        b=Ballistics();b.feed([1],0)
        self.assertEqual(b.tick(0),([0],[0]))
        self.assertEqual(b.tick(.25),([-6],[0]))
        self.assertIsNone(b.tick(.51))
    def test_new_pair_resets_channel_count(self):
        b=Ballistics();b.feed([1],0);b.feed([.5,.25],.1)
        self.assertEqual(len(b.levels),2);self.assertAlmostEqual(b.levels[1],-12.041199826)
    def test_worker_failure_stops_only_meters_and_reconnect_retries(self):
        usb=MeterUSB();usb.result=-7;events=queue.Queue()
        w=Worker(events,factory=lambda:AF16Rig(usb));w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        w.commands.put(('meters_enable',True));w.commands.put(('connect',None))
        def until(kind):
            end=time.monotonic()+3
            while time.monotonic()<end:
                e=events.get(timeout=max(.01,end-time.monotonic()))
                if e['kind']==kind:return e
            self.fail(kind)
        error=until('meter_error');serial=error['connection_serial']
        until('snapshot');self.assertEqual(len(usb.meter_calls),1)
        usb.result=236;w.commands.put(('connect',None))
        frame=until('meter_frame')
        self.assertGreater(frame['connection_serial'],serial)
        self.assertEqual(frame['state']['raw'],list(range(118)))
    def test_meter_event_changes_no_fader_or_knob(self):
        strips={i:SimpleNamespace(meter=Mock(),c=SimpleNamespace(state={'stereo_members':[1,2]} if i==1 else {})) for i in (1,2)}
        v=SimpleNamespace(meter_serial=5,strips=strips,master_view=SimpleNamespace(meter=Mock(),aux_meters={}),bus='main',meter_status=Mock(),app=SimpleNamespace(demo=False))
        f=decode_frame(struct.pack('<118H',*range(118)))
        Console.handle(v,dict(kind='meter_frame',state=f,connection_serial=4))
        strips[1].meter.feed.assert_not_called()
        Console.handle(v,dict(kind='meter_frame',state=f,connection_serial=5))
        self.assertEqual(strips[1].meter.feed.call_args.args[0],f['inputs'][:2])
        self.assertEqual(v.master_view.meter.feed.call_args.args[0],f['main'])

if __name__=='__main__':unittest.main()
