import copy,unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError
import test_output_target as native
import test_mixer_scene_window as windows
from test_mixer_scene import capture
import mixer_scene as m

class SceneOutputTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_all_eight_native_indices_exact_fractional_values(self,sleep):
        fixture=native.OutputTargetTests();d,u=fixture.device();self.addCleanup(fixture.doCleanups);layout=m.topology(d)
        for left in (3,5,7,9):
            a=dict(bus='outputs',source=left,stereo=True)
            self.assertEqual(m.read_entry(d,layout,a)['values'],{'level':[0,0],'link':[0,0]})
            u.calls.clear();m.apply_entry(d,layout,dict(a,field='level',expected=[0,0],values=[-513,-1025],output_links=[0,0]))
            outs=[c for c in u.calls if c[0]==0x40]
            self.assertEqual([c[1:5] for c in outs],[(0x11,33,left-3,(-513&65535).to_bytes(2,'little')),(0x11,33,left-2,(-1025&65535).to_bytes(2,'little'))])
            self.assertEqual(m.read_entry(d,layout,a)['values']['level'],[-513,-1025])
    def test_legacy_v6_leaves_outputs_unchanged(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.TRIM_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('outputs','inputs')]
        d.output_level_3=-256;d.output_link_mask=3
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_link_mismatch_prevents_plan_and_changed_link_blocks_write(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.CLOCK_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate'];d.output_link_mask=3
        with self.assertRaisesRegex(ValueError,'stereo links'):m.plan(saved,capture(d))
        c=dict(bus='outputs',source=3,stereo=True,field='level',expected=[0,0],values=[-256,-256],output_links=[0,0])
        with patch('mixer_scene_outputs.set_raw') as write:
            with self.assertRaisesRegex(DeviceError,'stereo links'):m.apply_entry(d,saved['layout'],c)
            write.assert_not_called()
    def test_linked_pair_side_effect_target_skips_redundant_write(self):
        d=DemoAF16Rig();d.output_link_mask=3;layout=m.topology(d)
        c=dict(bus='outputs',source=3,stereo=True,field='level',expected=[0,0],values=[-513,-513],output_links=[1,1])
        def write(device,source,target,expected):
            device.output_level_3=target;device.output_level_4=target
        with patch('mixer_scene_outputs.set_raw',side_effect=write) as call:
            m.apply_entry(d,layout,c);self.assertEqual(call.call_count,1)
    def test_unexpected_linked_pair_side_effect_stops(self):
        d=DemoAF16Rig();d.output_link_mask=3;layout=m.topology(d)
        c=dict(bus='outputs',source=3,stereo=True,field='level',expected=[0,0],values=[-513,-1025],output_links=[1,1])
        def write(device,source,target,expected):
            device.output_level_3=target;device.output_level_4=target
        with patch('mixer_scene_outputs.set_raw',side_effect=write) as call:
            with self.assertRaisesRegex(DeviceError,'during recall'):m.apply_entry(d,layout,c)
            self.assertEqual(call.call_count,1)
    def test_bad_range_and_shape(self):
        d=DemoAF16Rig();saved=capture(d)
        for values in ([1,0],[-15361,0],[True,0],[0],None):
            bad=copy.deepcopy(saved);next(e for e in bad['entries'] if e['bus']=='outputs')['values']['level']=values
            with self.assertRaises(ValueError):m.validate(bad)
            c=dict(bus='outputs',source=9,stereo=True,field='level',expected=[0,0],values=values,output_links=[0,0])
            with self.assertRaises(ValueError):m.apply_entry(d,saved['layout'],c)
    def test_incremental_full_recall(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();saved=capture(d);sets=[]
        for e in saved['entries']:
            if e['bus']=='outputs':e['values']['level']=[-513,-1025]
        p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),4);self.assertEqual(m.plan(saved,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
