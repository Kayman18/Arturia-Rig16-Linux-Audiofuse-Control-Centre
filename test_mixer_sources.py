import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,PARAMETERS,DeviceError,validate_index
from mixer_sources import inclusion_options
from test_controls import FakeUSB

class SourceTests(unittest.TestCase):
    def setUp(self):
        sleeper=patch('af16rig.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
        self.usb=FakeUSB();original=self.usb.libusb_control_transfer.func
        def transfer(h,bm,req,param,index,data,length,timeout):
            if bm==0x40 and req==0x11 and param in (34,35,48,49):
                self.usb.calls.append((bm,req,param,index,bytes(data),length,timeout))
                if not self.usb.ignore_writes:
                    before=self.usb.values[1,param];value=int.from_bytes(data,'little')
                    self.usb.values[1,param]=before|(1<<index) if value else before&~(1<<index)
                return 2
            return original(h,bm,req,param,index,data,length,timeout)
        self.usb.libusb_control_transfer.func=transfer
        self.device=AF16Rig(self.usb);self.device.open();self.addCleanup(self.device.close)
        for bus in ('main','cue'):
            self.usb.values[PARAMETERS[bus+'_channel_show']]=0
            self.usb.values[PARAMETERS[bus+'_channel_stereo']]=0
    def apply(self,bus,source,stereo,value):
        return self.device.write_mixer_inclusion(bus,source,stereo,value,
            expected_mono=self.usb.values[PARAMETERS[bus+'_channel_show']],
            expected_stereo=self.usb.values[PARAMETERS[bus+'_channel_stereo']])
    def writes(self):return [c for c in self.usb.calls if c[0]==0x40]
    def test_all_analog_mono_flags_main_and_cue(self):
        baseline=dict(self.usb.values)
        for bus in ('main','cue'):
            for source in range(1,17):
                self.apply(bus,source,False,True)
                self.assertEqual(self.usb.values[PARAMETERS[bus+'_channel_show']],1<<(source-1))
                self.apply(bus,source,False,False)
        self.assertEqual(self.usb.values,baseline)
        self.assertTrue(all(c[2] in (34,48) for c in self.writes()))
    def test_all_stereo_pairs_both_member_addresses(self):
        for bus in ('main','cue'):
            for source in range(1,17):
                self.apply(bus,source,True,True)
                self.assertEqual(self.usb.values[PARAMETERS[bus+'_channel_stereo']],1<<((source-1)//2))
                self.apply(bus,source,True,False)
        self.assertTrue(all(c[2] in (35,49) and c[3]<8 for c in self.writes()))
    def test_other_flags_and_values_preserved(self):
        self.apply('main',16,False,True);before=dict(self.usb.values)
        self.apply('main',1,False,True);before[PARAMETERS['main_channel_show']]|=1
        self.assertEqual(self.usb.values,before)
    def test_stale_selection_blocks_write(self):
        with self.assertRaises(DeviceError):self.device.write_mixer_inclusion('main',1,False,True,expected_mono=1,expected_stereo=0)
        self.assertFalse(self.writes())
    def test_stereo_cannot_replace_mono_implicitly(self):
        self.apply('main',2,False,True);self.usb.calls.clear()
        with self.assertRaises(DeviceError):self.apply('main',1,True,True)
        self.assertFalse(self.writes())
    def test_mono_cannot_replace_stereo_implicitly(self):
        self.apply('cue',1,True,True);self.usb.calls.clear()
        with self.assertRaises(DeviceError):self.apply('cue',2,False,True)
        self.assertFalse(self.writes())
    def test_explicit_conversion_preserves_levels(self):
        levels={k:v for k,v in self.usb.values.items() if k[1] in (36,50,40,41,42,43)}
        self.apply('main',1,False,True);self.apply('main',2,False,True)
        self.apply('main',1,False,False);self.apply('main',2,False,False);self.apply('main',1,True,True)
        self.assertEqual({k:self.usb.values[k] for k in levels},levels)
    def test_noop_no_out(self):
        self.apply('main',1,False,False);self.assertFalse(self.writes())
    def test_version_guard(self):
        self.device.version=19
        with self.assertRaises(DeviceError):self.apply('main',1,False,True)
        self.assertFalse(self.writes())
    def test_ignored_write_not_retried(self):
        self.usb.ignore_writes=True
        with self.assertRaises(DeviceError):self.apply('main',1,False,True)
        self.assertEqual(len(self.writes()),1)
    def test_bad_types_and_indices(self):
        for source in (0,17,True):
            with self.assertRaises(ValueError):self.apply('main',source,False,True)
        with self.assertRaises(ValueError):validate_index('main_channel_stereo',8)
        with self.assertRaises(ValueError):validate_index('main_channel_show',16)
        self.assertFalse(self.writes())
    def test_ui_options_reflect_conflicts(self):
        state={'raw':{'show':3,'stereo':0}}
        self.assertEqual(inclusion_options(state,1),dict(mono_add=False,mono_remove=True,stereo_add=False,stereo_remove=False))
        state={'raw':{'show':0,'stereo':1}}
        self.assertEqual(inclusion_options(state,2),dict(mono_add=False,mono_remove=False,stereo_add=False,stereo_remove=True))
        self.assertEqual(inclusion_options({},1),{})
    def test_demo_source_removal_disables_controls(self):
        d=DemoAF16Rig();d.write_mixer_inclusion('cue',1,False,False,expected_mono=65535,expected_stereo=0)
        s=d.mix_channel_snapshot('cue',1)
        self.assertEqual(s['mono_selected'],0);self.assertFalse(s['level_writes_available'])
        self.assertEqual(d.mix_channel_snapshot('main',1)['mono_selected'],1)
    def test_demo_stereo_group_visible(self):
        d=DemoAF16Rig();d.cue_show=0
        d.write_mixer_inclusion('cue',2,True,True,expected_mono=0,expected_stereo=0)
        self.assertEqual([m['source'] for m in d.mix_channel_snapshot('cue',1)['stereo_members']],[1,2])

if __name__=='__main__':unittest.main()
