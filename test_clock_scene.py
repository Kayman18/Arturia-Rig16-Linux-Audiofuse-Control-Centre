import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError
from test_controls import FakeUSB
from test_mixer_scene import capture
from clock_status import FIELDS
import clock_controls as controls
import clock_scene as clock
import mixer_scene as scene
import test_mixer_scene_window as windows

class ClockSceneTests(unittest.TestCase):
    def native(self):
        usb=FakeUSB()
        for k,v in controls.DEMO_RAW.items():usb.values[FIELDS[k]]=v
        device=AF16Rig(usb);device.open();self.addCleanup(device.close)
        usb.calls.clear()
        return device,usb

    @patch('clock_controls.time.sleep')
    def test_all_576_native_transitions_exact_ordered_packets(self,sleep):
        d,u=self.native()
        for before in range(24):
            for target in range(24):
                for k,v in clock.unpack(before).items():u.values[FIELDS[k]]=v
                u.calls.clear();clock.apply(d,target,before)
                self.assertEqual(clock.read(d),target)
                old,goal=clock.unpack(before),clock.unpack(target)
                expected=[(0x40,0x11,FIELDS[k][1],0,goal[k].to_bytes(2,'little'),2,1000)
                          for k in clock.ORDER if old[k]!=goal[k]]
                self.assertEqual([c for c in u.calls if c[0]==0x40],expected)

    def test_missing_external_clock_blocks_before_first_write(self):
        d,u=self.native();u.values[FIELDS['wordclock_frequency']]=0
        with self.assertRaisesRegex(DeviceError,'frequency'):clock.apply(d,23,0)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))

    def test_stale_unknown_and_invalid_states_do_not_write(self):
        d,u=self.native()
        with self.assertRaisesRegex(DeviceError,'changed'):clock.apply(d,23,1)
        for value in (-1,24,True,None):
            with self.assertRaises(ValueError):clock.apply(d,value,0)
        u.values[FIELDS['preferred_source']]=99
        with self.assertRaisesRegex(DeviceError,'unavailable'):clock.apply(d,23,0)
        self.assertFalse(any(c[0]==0x40 for c in u.calls))

    @patch('clock_controls.time.sleep')
    def test_rejected_write_stops_without_retry(self,sleep):
        d,u=self.native();u.ignore_writes=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):clock.apply(d,23,0)
        self.assertEqual(sum(c[0]==0x40 for c in u.calls),1)

    def test_unexpected_side_effect_stops_next_write(self):
        d=DemoAF16Rig();original=controls.set_option
        def write(*args):
            result=original(*args);d.clock_raw['selected_source']=1;return result
        with patch('clock_controls.set_option',side_effect=write) as setter:
            with self.assertRaisesRegex(DeviceError,'not confirmed'):clock.apply(d,23,0)
            self.assertEqual(setter.call_count,1)

    def test_clock_loss_before_source_switch_stops_with_prior_changes(self):
        d=DemoAF16Rig();original=controls.set_option
        def write(*args):
            result=original(*args);d.clock_raw['adat_frequency']=0;return result
        with patch('clock_controls.set_option',side_effect=write):
            with self.assertRaisesRegex(DeviceError,'frequency'):clock.apply(d,9,0)
        self.assertEqual(clock.read(d),1)

    def test_old_v11_preserves_clock(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=scene.AB_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus']!='clock']
        d.clock_raw['selected_source']=2
        self.assertEqual(scene.plan(saved,capture(d)),[])

    def test_scene_preview_recall_verifies_clock_last(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();saved=capture(d);sets=[]
        next(e for e in saved['entries'] if e['bus']=='clock')['values']['clock_config']=[23]
        next(e for e in saved['entries'] if e['bus']=='monitor')['values']['mute']=[1]
        p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(clock.read(d),23)
        self.assertEqual(scene.plan(saved,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
        self.assertEqual(scene.plan(saved,capture(DemoAF16Rig()))[-1]['bus'],'clock')

    def test_unknown_version_and_corrupt_saved_config(self):
        d=DemoAF16Rig();d.version=19
        with self.assertRaises(DeviceError):clock.apply(d,1,0)
        saved=capture(DemoAF16Rig())
        for value in (24,True,-1,None):
            next(e for e in saved['entries'] if e['bus']=='clock')['values']['clock_config']=[value]
            with self.assertRaises(ValueError):scene.validate(saved)

    def test_sample_rate_and_preferred_source_are_not_scene_writes(self):
        d=DemoAF16Rig();clock.apply(d,23,0)
        self.assertEqual(d.clock_raw['internal_frequency'],2)
        self.assertEqual(d.clock_raw['preferred_source'],0)
        self.assertIn('Word clock',clock.describe(23))
