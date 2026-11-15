import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,PARAMETERS
from test_digital_mixer import DigitalUSB
from test_controls import Fn
from stereo_pan import targets,describe,read_pair,set_position
from mixer_view import ChannelController,Field
from af16rig_gui import Worker

class StereoPanTests(unittest.TestCase):
    def setUp(self):
        p=patch('af16rig.time.sleep');p.start();self.addCleanup(p.stop)
        self.u=DigitalUSB();self.d=AF16Rig(self.u);self.d.open();self.addCleanup(self.d.close)
        for bus in ('main','cue'):
            self.u.packed[PARAMETERS[bus+'_channel_show'][1]]=0
            self.u.packed[PARAMETERS[bus+'_channel_stereo'][1]]=(1<<32)-1
            for i in range(64):self.u.words[PARAMETERS[bus+'_channel_pan'][1],i]=254 if i%2 else 0
    def test_curve_and_roundtrip_every_position(self):
        self.assertEqual(targets(0),[0,0]);self.assertEqual(targets(127),[0,254]);self.assertEqual(targets(254),[254,254])
        for position in range(255):
            s=describe(targets(position));self.assertTrue(s['canonical']);self.assertEqual(s['position'],position)
    def test_custom_pans_not_claimed_canonical(self):
        s=describe([70,180]);self.assertFalse(s['canonical']);self.assertEqual(s['values'],[70,180])
        self.assertIsNone(describe([None,254])['position'])
    def test_every_pair_and_bus_targets_native_indexes_only(self):
        for bus in ('main','cue'):
            for source in range(1,64,2):
                self.u.out.clear();before=read_pair(self.d,bus,source)
                state=set_position(self.d,bus,source,64,before)
                self.assertEqual(state['values'],[0,128])
                self.assertEqual(self.u.out,[(0x40,0x11,PARAMETERS[bus+'_channel_pan'][1],source,128)])
    def test_centre_restores_both_native_pans(self):
        self.u.words[37,0]=127;self.u.words[37,1]=127
        set_position(self.d,'main',1,127,read_pair(self.d,'main',1))
        self.assertEqual(self.u.out,[(0x40,0x11,37,0,0),(0x40,0x11,37,1,254)])
    def test_noop_does_not_write(self):
        set_position(self.d,'main',1,127,read_pair(self.d,'main',1));self.assertEqual(self.u.out,[])
    def test_external_pan_change_blocks(self):
        before=read_pair(self.d,'main',1);self.u.words[37,1]=200
        with self.assertRaisesRegex(DeviceError,'changed'):set_position(self.d,'main',1,64,before)
        self.assertEqual(self.u.out,[])
    def test_selection_change_blocks(self):
        before=read_pair(self.d,'main',1);self.u.packed[34]=1
        with self.assertRaises(DeviceError):set_position(self.d,'main',1,64,before)
        self.assertEqual(self.u.out,[])
    def test_bad_positions_and_even_source_blocked(self):
        for v in (-1,255,True,1.5):
            with self.assertRaises(ValueError):targets(v)
        with self.assertRaises(ValueError):read_pair(self.d,'main',2)
        self.assertEqual(self.u.out,[])
    def test_unsupported_version_blocked(self):
        before=read_pair(self.d,'main',1);self.d.version=19
        with self.assertRaises(DeviceError):set_position(self.d,'main',1,64,before)
        self.assertEqual(self.u.out,[])
    def test_rejected_second_write_keeps_partial_state_without_retry(self):
        self.u.words[37,0]=127;self.u.words[37,1]=127
        original=self.u.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,n,t):
            self.u.ignore=bm==0x40 and index==1
            return original(h,bm,req,param,index,data,n,t)
        self.u.libusb_control_transfer=Fn(transfer)
        with self.assertRaises(DeviceError):set_position(self.d,'main',1,127,read_pair(self.d,'main',1))
        self.assertEqual(len(self.u.out),2)
        self.assertEqual(read_pair(self.d,'main',1)['values'],[0,127])
    def test_demo_analog_and_digital(self):
        d=DemoAF16Rig();d.main_show=0;d.main_stereo=1
        self.assertEqual(set_position(d,'main',1,127,read_pair(d,'main',1))['values'],[0,254])
    def test_controller_sends_frozen_pair_readback(self):
        app=SimpleNamespace(connected=True,info={'state_version':18},name_cache=SimpleNamespace(serial=3),worker=SimpleNamespace(commands=queue.Queue()))
        c=ChannelController.__new__(ChannelController);c.app=app;c.pending=False;c.stale=False;c.refresh=Mock()
        c.bus=Field('main');c.source=Field(1);c.state={'stereo_members':[{},{}],'stereo_pan':{'values':[0,254],'masks':[0,1],'position':127}}
        self.assertTrue(c.target('pan',100));self.assertFalse(c.target('pan',101))
        cmd,data=app.worker.commands.get_nowait();self.assertEqual(cmd,'stereo_pan');self.assertEqual(data['target'],100)
        self.assertEqual(data['expected']['values'],[0,254]);self.assertEqual(data['connection_serial'],3)
    def test_worker_demo_read_and_write(self):
        events=queue.Queue();w=Worker(events,demo=True);w.start()
        def until(kind):
            while True:
                e=events.get(timeout=3)
                if e['kind']==kind:return e
        try:
            w.commands.put(('connect',None));serial=until('connected')['connection_serial']
            w.device.main_show=0;w.device.main_stereo=1
            w.commands.put(('console_read',('main',1)));state=until('console_snapshot')['state']
            self.assertIn('stereo_pan',state)
            w.commands.put(('stereo_pan',dict(bus='main',source=1,target=127,expected=state['stereo_pan'],connection_serial=serial)))
            result=until('input_written');self.assertEqual(result['name'],'stereo_pan');self.assertEqual(result['actual']['values'],[0,254])
        finally:w.stop_event.set();w.join(3)

if __name__=='__main__':unittest.main()
