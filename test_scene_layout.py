import copy,unittest
from unittest.mock import patch,Mock
from af16rig import DemoAF16Rig,AF16Rig,DeviceError
from test_digital_mixer import DigitalUSB
from test_mixer_scene import capture
import test_mixer_scene_window as windows
from fader_scene import topology,validate_layout
import scene_layout as layouts
import mixer_scene as scene

class SceneLayoutTests(unittest.TestCase):
    def layout(self,bus,pair,state):
        result={'main':[0,0],'cue':[0,0]}
        result[bus]=[(state if state<4 else 0)<<(pair*2),(1<<pair) if state==4 else 0]
        return result

    @patch('mixer_membership.time.sleep')
    def test_all_1600_pair_transitions_native_packets(self,sleep):
        u=DigitalUSB();d=AF16Rig(u);d.open();self.addCleanup(d.close)
        for bus in ('main','cue'):
            for pair in range(32):
                for old in range(5):
                    for new in range(5):
                        before=self.layout(bus,pair,old);target=self.layout(bus,pair,new)
                        for b,params in [('main',(34,35)),('cue',(48,49))]:
                            for parameter,value in zip(params,before[b]):u.packed[parameter]=value
                        u.out.clear();steps=layouts.plan(target,before)
                        for step in steps:
                            validate_layout(step['target_layout'])
                            layouts.apply_step(d,step['expected_layout'],step)
                        self.assertEqual(topology(d),target)
                        expected=[(0x40,0x11,(35 if s['stereo'] else 34) if bus=='main' else (49 if s['stereo'] else 48),
                                   (s['source']-1)//2 if s['stereo'] else s['source']-1,s['values'][0]) for s in steps]
                        self.assertEqual(u.out,expected)
                        self.assertLessEqual(len(steps),3)

    def target(self,d):
        d.main_show=0;d.main_stereo=1;d.cue_show=0;d.cue_stereo=0
        d.digital_selection={'main':(0,1<<16),'cue':(1<<63,0)}
        saved=capture(d)
        d.main_show=65535;d.main_stereo=0;d.cue_show=65535;d.digital_selection={}
        return saved

    def test_controller_layout_then_fresh_preview_no_setting_recall(self):
        d=DemoAF16Rig();saved=self.target(d)
        saved['entries'][0]['values']['level']=[-256,-256]
        helper=windows.MixerPageTests();p=helper.page();p.layout_button=Mock();sets=[]
        p.refresh(saved);helper.drain(p,d,sets)
        self.assertTrue(p.layout_match_needed());self.assertFalse(p.changes)
        p.match_layout();helper.drain(p,d,sets)
        self.assertEqual(topology(d),saved['layout']);self.assertFalse(p.layout_match_needed())
        self.assertTrue(p.changes);self.assertTrue(all(c['bus']=='mixer_layout' for c in sets))
        self.assertEqual(getattr(d,'mix_levels',{}),{})
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(scene.plan(saved,capture(d)),[])

    def test_stop_between_bits_prevents_remaining_writes(self):
        d=DemoAF16Rig();saved=self.target(d);helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets);p.match_layout()
        cmd,data=p.app.worker.commands.get_nowait()
        record=scene.apply_entry(d,data['layout'],data['change'])
        p.handle(dict(kind='scene_written',record=record,request_id=data['request_id'],connection_serial=1))
        p.stop();helper.drain(p,d,sets)
        self.assertFalse(sets);self.assertNotEqual(topology(d),saved['layout']);self.assertFalse(p.busy)

    def test_stale_state_blocks_next_bit(self):
        d=DemoAF16Rig();before=topology(d);target={'main':[0,1],'cue':[0,0]}
        step=layouts.plan(target,before)[0];d.cue_show=0
        with patch('scene_layout.change') as write:
            with self.assertRaises(DeviceError):layouts.apply_step(d,before,step)
            write.assert_not_called()

    def test_invalid_and_multibit_commands_do_not_write(self):
        d=DemoAF16Rig();before=topology(d);step=layouts.plan({'main':[0,1],'cue':[0,0]},before)[0]
        bad=copy.deepcopy(step);bad['target_layout']['cue']=[0,0]
        with patch('scene_layout.change') as write:
            with self.assertRaises(ValueError):layouts.apply_step(d,before,bad)
            bad=copy.deepcopy(step);bad['values']=[True]
            with self.assertRaises(ValueError):layouts.apply_step(d,before,bad)
            write.assert_not_called()

    def test_unexpected_side_effect_stops_without_retry(self):
        d=DemoAF16Rig();before=topology(d);step=layouts.plan({'main':[0,1],'cue':[0,0]},before)[0]
        import mixer_membership
        original=mixer_membership.change
        def write(*args):
            result=original(*args);d.cue_show=0;return result
        with patch('scene_layout.change',side_effect=write) as setter:
            with self.assertRaises(DeviceError):layouts.apply_step(d,before,step)
            self.assertEqual(setter.call_count,1)

    def test_hardware_scene_cannot_match_demo_layout(self):
        d=DemoAF16Rig();saved=self.target(d);saved['demo']=False
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(p.layout_match_needed())
        p.match_layout();self.assertTrue(p.app.worker.commands.empty())

    def test_matching_layout_no_writes(self):
        d=DemoAF16Rig();self.assertEqual(layouts.plan(topology(d),topology(d)),[])

    @patch('mixer_membership.time.sleep')
    def test_native_rejection_is_not_retried(self,sleep):
        u=DigitalUSB();d=AF16Rig(u);d.open();self.addCleanup(d.close)
        before=topology(d);step=layouts.plan({'main':[1,0],'cue':[0,0]},before)[0]
        u.ignore=True
        with self.assertRaises(DeviceError):layouts.apply_step(d,before,step)
        self.assertEqual(len(u.out),1);self.assertEqual(topology(d),before)

    def test_preview_uses_bank_relative_channel_numbers(self):
        self.assertEqual(layouts.pair_label([3<<32,0],32),'Mono 1, 2')
        self.assertEqual(layouts.pair_label([1<<63,0],62),'Mono 32')
