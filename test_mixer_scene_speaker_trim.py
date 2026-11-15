import copy,unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,PARAMETERS
from test_controls import FakeUSB
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import mixer_scene as m
import speaker_trim

class SceneSpeakerTrimTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_native_exact_fractional_trim_packets(self,sleep):
        usb=FakeUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close);layout=m.topology(d)
        a=dict(bus='speaker_b',source=0,stereo=False)
        for target in (-3072,-513,-1,0,129,3072):
            old=m.read_entry(d,layout,a)['values']['trim'];usb.calls.clear()
            m.apply_entry(d,layout,dict(a,field='trim',expected=old,values=[target]))
            outs=[c for c in usb.calls if c[0]==0x40]
            self.assertEqual(len(outs),1)
            self.assertEqual(outs[0][1:5],(0x11,75,0,(target&65535).to_bytes(2,'little')))
            self.assertEqual(speaker_trim.read(d),target)
            self.assertEqual(usb.values[PARAMETERS['ab_destination']],1)
            self.assertEqual(usb.values[PARAMETERS['ab_selected']],0)
    def test_v5_leaves_b_trim_alone(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.MONITOR_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_b','outputs','inputs')]
        d.ab_trim=123
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_stale_invalid_and_unsupported_version_do_not_write(self):
        d=DemoAF16Rig()
        for value in (True,-3073,3073,1.5):
            with self.assertRaises(ValueError):speaker_trim.set_raw(d,value,0)
        d.ab_trim=10
        with self.assertRaises(DeviceError):speaker_trim.set_raw(d,20,0)
        self.assertEqual(d.ab_trim,10)
        d.version=19
        with self.assertRaises(DeviceError):speaker_trim.set_raw(d,20,10)
    @patch('af16rig.time.sleep')
    def test_rejected_write_never_retried(self,sleep):
        usb=FakeUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close);usb.ignore_writes=True
        with self.assertRaises(DeviceError):speaker_trim.set_raw(d,256,0)
        self.assertEqual(len([c for c in usb.calls if c[0]==0x40]),1)
    def test_incremental_preview_and_verified_recall(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();saved=capture(d);sets=[]
        next(e for e in saved['entries'] if e['bus']=='speaker_b')['values']['trim']=[-513]
        p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertEqual(d.ab_trim,-513)
        self.assertEqual(m.plan(saved,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
    def test_invalid_saved_trim_rejected(self):
        saved=capture(DemoAF16Rig())
        for value in (True,-3073,3073,None):
            bad=copy.deepcopy(saved);next(e for e in bad['entries'] if e['bus']=='speaker_b')['values']['trim']=[value]
            with self.assertRaises(ValueError):m.validate(bad)
