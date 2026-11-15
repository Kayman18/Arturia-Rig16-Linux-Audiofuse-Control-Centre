import unittest,copy
from unittest.mock import patch
from af16rig import DemoAF16Rig,PARAMETERS,DeviceError
from test_controls import Fn
from test_mixer_scene import capture
import test_preamp as native
import test_mixer_scene_window as windows
import mixer_scene as m
import mixer_scene_inputs as inputs

class InstrumentSceneTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_native_both_front_jacks_preserve_other_bits(self,sleep):
        fixture=native.PreampTests();d,u=fixture.device(0x21);self.addCleanup(d.close)
        key=PARAMETERS['front_line_instrument'];u.values[key]=0x8000;original=u.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            old=u.values[key];rc=original(h,bm,req,param,index,data,length,timeout)
            if bm==0x40 and (req-0x10,param)==key:
                u.values[key]=old|(1<<index) if int.from_bytes(data,'little') else old&~(1<<index)
            return rc
        u.libusb_control_transfer=Fn(transfer)
        for target in (1,0):
            for source in (1,2):
                u.calls.clear();inputs.write(d,source,'line','instrument',target)
                outs=[c for c in u.calls if c[0]==0x40]
                self.assertEqual(len(outs),1)
                self.assertEqual(outs[0][1:5],(0x11,69,source-1,target.to_bytes(2,'little')))
                self.assertEqual(inputs.read(d,source,'instrument'),target)
                self.assertTrue(u.values[key]&0x8000)
    def test_v9_compatibility_preserves_instrument_mode(self):
        d=DemoAF16Rig();d.force_rear=0;saved=capture(d);saved['format']=m.FILTER_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        for e in saved['entries']:
            if e['bus']=='inputs':e['values'].pop('instrument')
        d.front_instrument_1=1;d.front_instrument_2=1
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_inactive_mode_cannot_be_recalled(self):
        d=DemoAF16Rig();saved=capture(d)
        e=next(e for e in saved['entries'] if e['bus']=='inputs');self.assertEqual(e['values']['instrument'],[None,None])
        e['values']['instrument']=[1,1]
        with self.assertRaises(ValueError):m.validate(saved)
        with self.assertRaises(ValueError):inputs.write(d,1,'rear','instrument',1)
    def test_front_line_values_required_and_boolean_only(self):
        d=DemoAF16Rig();d.force_rear=0;original=capture(d)
        for value in (None,True,2,-1):
            bad=copy.deepcopy(original);e=next(e for e in bad['entries'] if e['bus']=='inputs');e['values']['instrument']=[value,0]
            with self.assertRaises(ValueError):m.validate(bad)
    def test_batch_preview_recall_and_stale_source(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();d.force_rear=0;target=capture(d);sets=[]
        next(e for e in target['entries'] if e['bus']=='inputs')['values']['instrument']=[1,1]
        p.refresh(target);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertEqual(m.plan(target,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
        d.front_instrument_1=0;d.front_instrument_2=0
        c=m.plan(target,capture(d))[0];d.force_rear=3
        with patch('mixer_scene_inputs.write') as write:
            with self.assertRaises(DeviceError):m.apply_entry(d,target['layout'],c)
            write.assert_not_called()
