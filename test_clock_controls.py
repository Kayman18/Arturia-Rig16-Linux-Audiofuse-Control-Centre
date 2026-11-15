import unittest
import queue
from unittest.mock import patch,Mock
from types import SimpleNamespace
from af16rig import AF16Rig,DeviceError,DeviceDisconnected,DemoAF16Rig
from test_controls import FakeUSB
from clock_status import FIELDS,snapshot
from clock_controls import OPTIONS,RATES,DEMO_RAW,decoded,set_option
from clock_window import ClockWindow
from af16rig_gui import Worker

class ClockControlsTests(unittest.TestCase):
    def setUp(self):
        p=patch('clock_controls.time.sleep');p.start();self.addCleanup(p.stop)
        self.u=FakeUSB()
        for k,v in DEMO_RAW.items():self.u.values[FIELDS[k]]=v
        self.d=AF16Rig(self.u);self.d.open();self.addCleanup(self.d.close);self.u.calls.clear()
    def outs(self):return [c for c in self.u.calls if c[0]==0x40]
    def test_all_xml_frequency_codes(self):
        for field in ('internal_frequency','adat_frequency','wordclock_frequency'):
            for code,hz in enumerate(RATES):
                self.assertEqual(decoded({field:code})[field],'Invalid' if code==0 else f'{hz:,} Hz')
    def test_enums_and_unknown_values(self):
        self.assertEqual(decoded(dict(selected_source=0,preferred_source=2,wordclock_impedance=0,wordclock_thru=1,double_smux=1)),
            dict(selected_source='Internal',preferred_source='Word clock',wordclock_impedance='75 Ω',wordclock_thru='Pass through',double_smux='Force SMUX'))
        self.assertEqual(decoded({'selected_source':7})['selected_source'],'Unknown (7)')
        self.assertEqual(decoded({'internal_frequency':65535})['internal_frequency'],'Unknown (65535)')
    def test_all_four_packets_and_confirmation(self):
        expected=DEMO_RAW.copy()
        for field in OPTIONS:
            self.u.calls.clear();self.assertEqual(set_option(self.d,field,1,expected),1)
            self.assertEqual(self.outs(),[(0x40,0x11,FIELDS[field][1],0,b'\x01\x00',2,1000)])
            self.assertTrue(self.d.last_write['confirmed']);expected[field]=1
    def test_noop(self):
        set_option(self.d,'selected_source',0,DEMO_RAW);self.assertEqual(self.outs(),[])
    def test_unknown_fields_and_enums_blocked(self):
        for field,value in [('preferred_source',1),('internal_frequency',2),('validity',0),('selected_source',3),('double_smux',2),('wordclock_thru',True)]:
            with self.assertRaises(ValueError):set_option(self.d,field,value,DEMO_RAW)
        self.assertEqual(self.outs(),[])
    def test_changed_configuration_blocks_write(self):
        self.u.values[FIELDS['preferred_source']]=2
        with self.assertRaisesRegex(DeviceError,'changed'):set_option(self.d,'selected_source',1,DEMO_RAW)
        self.assertEqual(self.outs(),[])
    def test_missing_external_frequency_blocks_switch(self):
        self.u.values[FIELDS['adat_frequency']]=0
        with self.assertRaisesRegex(DeviceError,'frequency'):set_option(self.d,'selected_source',1,DEMO_RAW)
        self.assertEqual(self.outs(),[])
    def test_unknown_version_blocks(self):
        self.d.version=19
        with self.assertRaises(DeviceError):set_option(self.d,'selected_source',1,DEMO_RAW)
        self.assertEqual(self.u.calls,[])
    def test_read_failure_blocks(self):
        self.u.read_result=1
        with self.assertRaises(DeviceError):set_option(self.d,'selected_source',1,DEMO_RAW)
        self.assertEqual(self.outs(),[])
    def test_rejection_never_retries_out(self):
        self.u.ignore_writes=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):set_option(self.d,'double_smux',1,DEMO_RAW)
        self.assertEqual(len(self.outs()),1);self.assertFalse(self.d.last_write['confirmed'])
    def test_disconnection_propagates(self):
        self.u.write_result=-4
        with self.assertRaises(DeviceDisconnected):set_option(self.d,'double_smux',1,DEMO_RAW)
        self.assertEqual(len(self.outs()),1)
    def test_uncertain_out_with_confirmed_readback(self):
        self.u.write_result=-7
        self.assertEqual(set_option(self.d,'double_smux',1,DEMO_RAW),1)
        self.assertEqual(len(self.outs()),1)
    def test_demo_status_tracks_options(self):
        d=DemoAF16Rig();s=snapshot(d)
        set_option(d,'selected_source',2,s['raw'])
        self.assertEqual(snapshot(d)['decoded']['selected_source'],'Word clock')
    def test_worker_tags_success_and_stale_connection_error(self):
        q=queue.Queue();w=Worker(q,demo=True);w.start()
        def until(kind):
            while True:
                e=q.get(timeout=3)
                if e['kind']==kind:return e
        try:
            w.commands.put(('connect',None));serial=until('connected')['connection_serial']
            data=dict(field='selected_source',target=1,expected=DEMO_RAW.copy(),connection_serial=serial,request_id='one')
            w.commands.put(('clock_set',data));self.assertEqual(until('clock_written')['actual'],1)
            w.commands.put(('clock_set',dict(data,connection_serial=serial-1,request_id='old')))
            self.assertEqual(until('clock_write_error')['request_id'],'old')
        finally:w.stop_event.set();w.join(3)
    def test_page_ignores_old_reply_and_clears_on_failure(self):
        p=ClockWindow.__new__(ClockWindow);p.pending='new';p.state={};p.app=SimpleNamespace(name_cache=SimpleNamespace(serial=2))
        p.write_status=Mock();p.refresh=Mock();p.sync_controls=Mock()
        p.clock_result(dict(kind='clock_written',connection_serial=1,request_id='new'))
        self.assertEqual(p.pending,'new')
        p.clock_result(dict(kind='clock_write_error',connection_serial=2,request_id='new',message='Rejected'))
        self.assertIsNone(p.pending);self.assertIsNone(p.state)
        p.write_status.config.assert_called_once_with(text='Rejected')

if __name__=='__main__':unittest.main()
