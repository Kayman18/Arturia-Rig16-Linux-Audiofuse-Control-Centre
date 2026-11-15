import copy,unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError,PARAMETERS
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import test_preamp as native
import mixer_scene as m
import mixer_scene_inputs as inputs

class SceneInputTests(unittest.TestCase):
    def test_all_inputs_gain_and_pad_front_and_rear_roundtrip(self):
        for front in (False,True):
            d=DemoAF16Rig();d.force_rear=0 if front else 3;saved=capture(d)
            for e in saved['entries']:
                if e['bus']=='inputs':e['values'].update(gain=[256,512],pad=[1,1])
            for c in m.plan(saved,capture(d)):m.apply_entry(d,saved['layout'],c)
            self.assertEqual(m.plan(saved,capture(d)),[])
    @patch('af16rig.time.sleep')
    def test_native_gain_packets_all_active_modes(self,sleep):
        fixture=native.PreampTests()
        for detected,source,kind,raw in [(0,5,'rear',513),(0x21,1,'line',22),(0x42,2,'mic',33),(0x10,3,'mini',513)]:
            d,u=fixture.device(detected);self.addCleanup(d.close)
            units=1 if kind in ('line','mic') else 256
            inputs.write(d,source,kind,'gain',raw*256//units)
            parameter,index,_,_=inputs.preamp.spec(source,kind);group,param=PARAMETERS[parameter]
            outs=[c for c in u.calls if c[0]==0x40]
            self.assertEqual(len(outs),1)
            self.assertEqual(outs[0][1:5],(0x10+group,param,index,raw.to_bytes(2,'little')))
    def test_legacy_v7_leaves_input_settings_untouched(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.OUTPUT_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        saved['entries']=[e for e in saved['entries'] if e['bus']!='inputs']
        d.inputs[5]['gain_raw']=513;d.inputs[5]['pad']=1;d.force_rear=0
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_context_mismatch_blocks_preview_and_stale_write(self):
        d=DemoAF16Rig();saved=capture(d);target=copy.deepcopy(saved)
        e=next(e for e in target['entries'] if e['bus']=='inputs');e['values']['gain']=[256,256]
        change=m.plan(target,saved)[0];d.force_rear=0
        with self.assertRaisesRegex(ValueError,'active input'):m.plan(target,capture(d))
        with patch('mixer_scene_inputs.write') as write:
            with self.assertRaisesRegex(DeviceError,'Input source'):m.apply_entry(d,saved['layout'],change)
            write.assert_not_called()
    def test_invalid_gain_member_blocks_entire_pair(self):
        d=DemoAF16Rig();layout=m.topology(d);ctx=inputs.context(d,5)
        c=dict(bus='inputs',source=5,stereo=True,field='gain',expected=[0,0],values=[256,13*256],input_context=ctx)
        with patch('mixer_scene_inputs.write') as write:
            with self.assertRaises(ValueError):m.apply_entry(d,layout,c)
            write.assert_not_called()
    def test_incremental_gui_batch_and_final_capture(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d);sets=[]
        for e in target['entries']:
            if e['bus']=='inputs':e['values'].update(gain=[256,512],pad=[1,1])
        p.refresh(target);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),16);self.assertEqual(m.plan(target,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
