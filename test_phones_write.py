import queue
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected,PARAMETERS
from af16rig_gui import Worker
from test_controls import FakeUSB
from phones_level import set_level
from output_strips import OutputStrip

class PhonesWriteTests(unittest.TestCase):
    def setUp(self):
        self.sleep=patch('af16rig.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
        self.usb=FakeUSB();self.usb.values[PARAMETERS['phones_knob']]=62464
        self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        self.usb.calls.clear()
    def writes(self):return [c for c in self.usb.calls if c[0]==0x40]
    def test_native_packet_and_readback(self):
        self.assertEqual(set_level(self.d,-13,62464),-3328)
        self.assertEqual(self.writes(),[(0x40,0x10,8,0,b'\x00\xf3',2,1000)])
        self.assertTrue(self.d.last_write['confirmed'])
        self.assertEqual(self.usb.calls[-1][:4],(0xc0,0x90,8,0))
    def test_noop_has_no_out(self):
        set_level(self.d,-12,62464);self.assertEqual(self.writes(),[])
    def test_invalid_targets_never_write(self):
        for db in (True,'-12',None,float('nan'),float('inf'),-60.001,0.001):
            with self.assertRaises(ValueError):set_level(self.d,db,62464)
        self.assertEqual(self.writes(),[])
    def test_invalid_expected_value_never_writes(self):
        for raw in (True,-1,65536,None,1.5):
            with self.assertRaises(ValueError):set_level(self.d,-13,raw)
        self.assertEqual(self.writes(),[])
    def test_external_knob_change_blocks_write(self):
        with self.assertRaisesRegex(DeviceError,'changed on device'):set_level(self.d,-13,60000)
        self.assertEqual(self.writes(),[])
    def test_unknown_version_blocks_write(self):
        self.d.version=19
        with self.assertRaises(DeviceError):set_level(self.d,-13,62464)
        self.assertEqual(self.usb.calls,[])
    def test_out_of_range_and_infinity_readback_block_write(self):
        for raw in (32768,1000,(-70*256)&65535):
            self.usb.values[PARAMETERS['phones_knob']]=raw
            with self.assertRaises(DeviceError):set_level(self.d,-13,raw)
        self.assertEqual(self.writes(),[])
    def test_rejected_write_is_not_repeated(self):
        self.usb.ignore_writes=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):set_level(self.d,-13,62464)
        self.assertEqual(len(self.writes()),1)
        self.assertFalse(self.d.last_write['confirmed'])
    def test_uncertain_out_but_confirmed_read_is_not_repeated(self):
        self.usb.write_result=-7
        self.assertEqual(set_level(self.d,-13,62464),-3328)
        self.assertEqual(len(self.writes()),1)
    def test_disconnected_write_propagates(self):
        self.usb.write_result=-4
        with self.assertRaises(DeviceDisconnected):set_level(self.d,-13,62464)
        self.assertEqual(len(self.writes()),1)
    def test_raw_bypass_stays_blocked(self):
        with self.assertRaises(ValueError):self.d._write_and_confirm('phones_knob',1)
        with self.assertRaises(ValueError):self.d._write_and_confirm('phones_preset',1)
        self.assertEqual(self.writes(),[])
    def test_limits_and_demo_match_native(self):
        demo=DemoAF16Rig()
        for db in (-60,-8.640625,0):
            expected=demo.headphones_snapshot()['knob_raw']
            self.usb.values[PARAMETERS['phones_knob']]=expected
            self.assertEqual(set_level(demo,db,expected),set_level(self.d,db,expected))

def strip():
    p=OutputStrip.__new__(OutputStrip)
    p.kind='phones';p.phones_raw=62464;p.phones_request=None;p.phones_read_at=time.monotonic()
    p.app=SimpleNamespace(connected=True,stale=False,state={'writes_available':True},
        name_cache=SimpleNamespace(serial=3),worker=SimpleNamespace(commands=queue.Queue()),message=Mock())
    p.raw=Mock();p.level=Mock();p.fader=Mock();p.meter=Mock();p.phone_status=Mock()
    return p

class PhonesControlTests(unittest.TestCase):
    def test_target_is_single_pending_command(self):
        p=strip();self.assertTrue(p.target_phones(-13));self.assertFalse(p.target_phones(-14))
        cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual((cmd,data['expected_raw'],data['db'],data['connection_serial']),('phones_target',62464,-13,3))
        self.assertTrue(p.app.worker.commands.empty())
        p.fader.update_value.assert_called_with(-12,False,readout='-12.00 dB',valid=True)
    def test_stale_reads_disable_control(self):
        p=strip();p.phones_read_at-=3
        self.assertFalse(p.target_phones(-13));self.assertTrue(p.app.worker.commands.empty())
    def test_confirmed_result_enables_with_new_level(self):
        p=strip();p.target_phones(-13)
        p.phones_result(dict(kind='phones_written',request_id=p.phones_request,actual=-3328))
        self.assertEqual(p.phones_raw,62208);self.assertTrue(p.phones_ready())
    def test_old_result_ignored_after_disconnect(self):
        p=strip();p.target_phones(-13);request=p.phones_request;p.clear()
        p.phones_result(dict(kind='phones_written',request_id=request,actual=-3328))
        self.assertIsNone(p.phones_raw);self.assertFalse(p.phones_ready())
    def test_failure_clears_level_until_fresh_read(self):
        p=strip();p.target_phones(-13)
        p.phones_result(dict(kind='phones_write_error',request_id=p.phones_request,message='not confirmed'))
        self.assertIsNone(p.phones_raw);self.assertFalse(p.phones_ready())
        p.app.message.config.assert_called_once_with(text='not confirmed',fg='#efba76')
    def test_worker_success_and_stale_connection(self):
        events=queue.Queue();w=Worker(events,demo=True);w.start()
        def until(kind):
            while True:
                event=events.get(timeout=3)
                if event['kind']==kind:return event
        try:
            w.commands.put(('connect',None));connected=until('connected')
            serial=connected['connection_serial']
            w.commands.put(('phones_target',dict(db=-13,expected_raw=62464,connection_serial=serial,request_id='ok')))
            event=until('phones_written');self.assertEqual(event['actual'],-3328)
            w.commands.put(('phones_target',dict(db=-14,expected_raw=62208,connection_serial=serial-1,request_id='old')))
            event=until('phones_write_error');self.assertEqual(event['request_id'],'old')
            self.assertEqual(w.device.phones_knob,62208)
        finally:w.stop_event.set();w.join(3)

if __name__=='__main__':unittest.main()
