import queue
import unittest
from unittest.mock import patch
from af16rig import AF16Rig, DemoAF16Rig, DeviceError, PARAMETERS
from af16rig_gui import Worker
from test_controls import FakeUSB

class RouteWriteTests(unittest.TestCase):
    def setUp(self):
        self.sleep=patch('af16rig.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
        self.usb=FakeUSB();self.routes={i:128+i%32 for i in range(62)}
        orig=self.usb.libusb_control_transfer.func
        def indexed(h,bm,req,param,index,data,length,timeout):
            if param==64 and req in (0x91,0x11):
                self.usb.calls.append((bm,req,param,index,bytes(data),length,timeout))
                if bm==0x40:
                    if not self.usb.ignore_writes:self.routes[index]=int.from_bytes(data,'little')
                else:data[0],data[1]=self.routes[index]&255,self.routes[index]>>8
                return 2
            return orig(h,bm,req,param,index,data,length,timeout)
        self.usb.libusb_control_transfer.func=indexed
        self.device=AF16Rig(self.usb);self.device.open();self.addCleanup(self.device.close)
    def writes(self):return [c for c in self.usb.calls if c[0]==0x40]
    def test_single_slot_only(self):
        before=dict(self.routes)
        self.assertEqual(self.device.write_output_route(15,192,expected_source=143),192)
        before[15]=192;self.assertEqual(self.routes,before)
        self.assertEqual(len(self.writes()),1)
        self.assertEqual(self.writes()[0][1:5],(0x11,64,15,b'\xc0\x00'))
        self.assertEqual(self.device.last_write['readback_attempts'],[{'actual':192}])
    def test_undo_exact_original(self):
        self.device.write_output_route(12,64,expected_source=140)
        self.device.write_output_route(12,140,expected_source=64)
        self.assertEqual(self.routes[12],140)
    def test_external_change_blocks_apply(self):
        self.routes[12]=64
        with self.assertRaises(DeviceError):self.device.write_output_route(12,192,expected_source=140)
        self.assertFalse(self.writes())
    def test_external_change_blocks_undo(self):
        self.device.write_output_route(12,64,expected_source=140)
        self.routes[12]=65;self.usb.calls.clear()
        with self.assertRaises(DeviceError):self.device.write_output_route(12,140,expected_source=64)
        self.assertFalse(self.writes())
    def test_unknown_values_and_destinations_blocked(self):
        for index,source,old in [(60,64,128),(61,64,128),(-1,64,128),(0,240,128),(0,160,128),(0,64,240),(True,64,128)]:
            with self.assertRaises(ValueError):self.device.write_output_route(index,source,expected_source=old)
        self.assertFalse(self.writes())
    def test_wrong_version_blocked(self):
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_output_route(0,64,expected_source=128)
        self.assertFalse(self.writes())
    def test_noop_does_not_write(self):
        self.assertEqual(self.device.write_output_route(0,128,expected_source=128),128)
        self.assertFalse(self.writes())
    def test_readback_mismatch_never_repeats_out(self):
        self.usb.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_output_route(17,64,expected_source=145)
        self.assertEqual(len(self.writes()),1)
        self.assertFalse(self.device.last_write['confirmed'])
    def test_demo_persists_route(self):
        d=DemoAF16Rig();d.write_output_route(12,192,expected_source=140)
        self.assertEqual(d.read('output_source',12),192)
        self.assertEqual(d.read('output_source',13),141)
    def test_worker_rejects_previous_connection(self):
        events=queue.Queue();worker=Worker(events,factory=lambda:self.device);worker.start()
        try:
            worker.commands.put(('connect',None))
            while events.get(timeout=3)['kind']!='connected':pass
            worker.commands.put(('routing_set',dict(connection_serial=0,request_id=77,destination=0,source_code=64,expected_source=128)))
            while True:
                event=events.get(timeout=3)
                if event['kind']=='routing_error':break
            self.assertEqual(event['request_id'],77);self.assertFalse(self.writes())
        finally:worker.stop_event.set();worker.join(2)
    def test_worker_emits_verified_route(self):
        events=queue.Queue();worker=Worker(events,factory=lambda:self.device);worker.start()
        try:
            worker.commands.put(('connect',None))
            while events.get(timeout=3)['kind']!='connected':pass
            worker.commands.put(('routing_set',dict(connection_serial=1,request_id=78,destination=0,source_code=64,expected_source=128)))
            while True:
                event=events.get(timeout=3)
                if event['kind'].startswith('routing_'):break
            self.assertEqual(event['kind'],'routing_written');self.assertEqual(event['actual'],64)
            self.assertEqual(event['previous'],128)
        finally:worker.stop_event.set();worker.join(2)

if __name__=='__main__':unittest.main()
