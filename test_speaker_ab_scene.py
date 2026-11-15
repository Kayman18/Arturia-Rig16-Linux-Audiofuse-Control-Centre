import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,PARAMETERS
from test_controls import FakeUSB
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import mixer_scene as m
import speaker_ab_scene as ab

class SpeakerABSceneTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_all_256_native_configuration_transitions(self,sleep):
        u=FakeUSB();d=AF16Rig(u);d.open();self.addCleanup(d.close)
        for before in range(16):
            for target in range(16):
                state=ab.unpack(before)
                for name,key in [('enabled','ab_enabled'),('selected','ab_selected'),('destination','ab_destination')]:u.values[PARAMETERS[key]]=state[name]
                u.calls.clear();ab.apply(d,target,before)
                self.assertEqual(ab.read(d),target)
                outs=[c for c in u.calls if c[0]==0x40]
                expected=[]
                for field,value in ab.steps(before,target):
                    key={'enabled':'ab_enabled','selected':'ab_selected','destination':'ab_destination'}[field]
                    group,param=PARAMETERS[key];expected.append((0x10+group,param,0,value.to_bytes(2,'little')))
                self.assertEqual([c[1:5] for c in outs],expected)
                self.assertLessEqual(len(outs),5)
    def test_sequence_reassigns_b_only_after_selecting_a(self):
        self.assertEqual(ab.steps(3,7),[('selected',0),('destination',1),('selected',1)])
        self.assertEqual(ab.steps(0,2),[('enabled',1),('selected',1),('enabled',0)])
    def test_stale_and_invalid_configuration_no_writes(self):
        d=DemoAF16Rig()
        with patch.object(d,'write_ab_enabled') as write:
            with self.assertRaises(DeviceError):ab.apply(d,15,0)
            write.assert_not_called()
        for value in (-1,16,True,None):
            with self.assertRaises(ValueError):ab.apply(d,value,4)
    @patch('af16rig.time.sleep')
    def test_failed_native_write_stops_without_retry(self,sleep):
        u=FakeUSB();d=AF16Rig(u);d.open();self.addCleanup(d.close);u.ignore_writes=True
        with self.assertRaises(DeviceError):ab.apply(d,7,4)
        self.assertEqual(sum(c[0]==0x40 for c in u.calls),1)
    def test_old_v10_does_not_change_ab(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.INSTRUMENT_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        d.ab_enabled=1;d.ab_selected=1;d.ab_destination=3
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_incremental_scene_preview_and_final_readback(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();saved=capture(d);sets=[]
        next(e for e in saved['entries'] if e['bus']=='speaker_ab')['values']['ab_config']=[15]
        p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertEqual(ab.read(d),15)
        self.assertEqual(m.plan(saved,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
    def test_unexpected_side_effect_stops_next_step(self):
        d=DemoAF16Rig();original=d.write_ab_enabled
        def write(value):
            result=original(value);d.ab_destination=3;return result
        with patch.object(d,'write_ab_enabled',side_effect=write),patch.object(d,'write_ab_selected') as select:
            with self.assertRaisesRegex(DeviceError,'not confirmed'):ab.apply(d,7,4)
            select.assert_not_called()
