import copy,unittest
from unittest.mock import patch,Mock
from af16rig import DemoAF16Rig,AF16Rig,DeviceError
from test_controls import FakeUSB,Fn
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import scene_sources as sources
import mixer_scene as scene

class SceneSourceTests(unittest.TestCase):
    def test_planner_all_1536_source_mask_combinations(self):
        for detected in (0,0x21,0x42,0x41,0x31,0x52):
            for current_mask in range(16):
                state=dict(force_rear=0xa0|current_mask,detect_status=detected)
                for target_mask in range(16):
                    target=sources.kinds(dict(state,force_rear=0xa0|target_mask))
                    reachable=True
                    for left in (0,2):
                        if sources.kinds(state)[left:left+2]==target[left:left+2]:continue
                        mask=3<<left
                        if not any(sources.kinds(dict(state,force_rear=(state['force_rear']&~mask)|force))[left:left+2]==target[left:left+2] for force in (0,mask)):reachable=False
                    if not reachable:
                        with self.assertRaises(DeviceError):sources.operations(state,target)
                        continue
                    steps=sources.operations(state,target)
                    final=steps[-1][2] if steps else state
                    self.assertEqual(sources.kinds(final),target)
                    self.assertEqual(final['force_rear']&~15,0xa0)
                    self.assertLessEqual(len(steps),2)

    @patch('af16rig.time.sleep')
    def test_native_packets_both_pairs_and_directions(self,sleep):
        u=FakeUSB();d=AF16Rig(u);d.open();self.addCleanup(d.close)
        original=u.libusb_control_transfer
        def transfer(handle,bm,req,param,index,data,length,timeout):
            if bm==0x40 and req==0x11 and param==72:
                u.calls.append((bm,req,param,index,bytes(data),length,timeout))
                if not u.ignore_writes:
                    value=int.from_bytes(data,'little');mask=u.values[1,72]
                    u.values[1,72]=mask|(1<<index) if value else mask&~(1<<index)
                return 2
            return original(handle,bm,req,param,index,data,length,timeout)
        u.libusb_control_transfer=Fn(transfer);u.values[0,1]=0x31
        for start,end in ((0xaf,0xa0),(0xa0,0xaf)):
            u.values[1,72]=start;expected=sources.kinds(sources.raw(d));target=sources.kinds(dict(force_rear=end,detect_status=0x31));u.calls.clear()
            sources.apply(d,target,expected)
            self.assertEqual(u.values[1,72],end)
            self.assertEqual([c for c in u.calls if c[0]==0x40],[(0x40,0x11,72,i,bytes([int(end==0xaf),0]),2,1000) for i in range(4)])
        u.ignore_writes=True;u.calls.clear()
        with self.assertRaises(DeviceError):sources.apply(d,['line','line','mini','mini']+['rear']*12,['rear']*16)
        self.assertEqual(sum(c[0]==0x40 for c in u.calls),1)

    def test_unreachable_second_pair_blocks_first_pair(self):
        d=DemoAF16Rig();d.force_rear=15;d.detect_status=0x21
        with patch.object(d,'set_rear_pair_source') as setter:
            with self.assertRaises(DeviceError):sources.apply(d,['line','line','mini','mini']+['rear']*12,['rear']*16)
            setter.assert_not_called()

    def test_connection_changes_between_pairs_stop_remaining_write(self):
        d=DemoAF16Rig();d.force_rear=15;original=d.set_rear_pair_source
        def write(*args):
            result=original(*args);d.detect_status=0;return result
        with patch.object(d,'set_rear_pair_source',side_effect=write) as setter:
            with self.assertRaises(DeviceError):sources.apply(d,['line','line','mini','mini']+['rear']*12,['rear']*16)
            self.assertEqual(setter.call_count,1)

    def test_stale_state_invalid_target_and_version_do_not_write(self):
        d=DemoAF16Rig();d.force_rear=15
        with patch.object(d,'set_rear_pair_source') as setter:
            with self.assertRaises(DeviceError):sources.apply(d,['rear']*16,['line','line','mini','mini']+['rear']*12)
            for target in ([],['mic']*16,None):
                with self.assertRaises(ValueError):sources.apply(d,target,['rear']*16)
            d.version=19
            with self.assertRaises(DeviceError):sources.apply(d,['rear']*16,['rear']*16)
            setter.assert_not_called()

    def test_controller_matches_then_requires_fresh_recall(self):
        d=DemoAF16Rig();d.force_rear=0;saved=capture(d)
        first=next(e for e in saved['entries'] if e['bus']=='inputs');first['values']['gain']=[256,256]
        d.force_rear=15
        helper=windows.MixerPageTests();p=helper.page();p.source_button=Mock();sets=[]
        p.refresh(saved);helper.drain(p,d,sets)
        self.assertTrue(p.source_match_needed());self.assertFalse(p.changes)
        p.start_apply();self.assertTrue(p.app.worker.commands.empty())
        p.match_sources();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertEqual(sets[0]['bus'],'input_sources')
        self.assertFalse(p.source_match_needed());self.assertTrue(p.changes)
        self.assertEqual(inputs_gain(d),[0,0])
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(scene.plan(saved,capture(d)),[])

    def test_stop_after_source_matching_does_not_start_capture_or_recall(self):
        d=DemoAF16Rig();d.force_rear=0;saved=capture(d);d.force_rear=15
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets);p.match_sources();p.stop();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertIsNone(p.scene);self.assertFalse(p.busy)
        self.assertIn('stopped',p.message.config.call_args.kwargs['text'])

    def test_old_scene_without_inputs_has_no_matching_action(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=scene.OUTPUT_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('inputs','speaker_ab','clock')]
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets)
        self.assertFalse(p.source_match_needed());p.match_sources();self.assertFalse(sets)

    def test_hardware_scene_cannot_match_sources_in_demo(self):
        d=DemoAF16Rig();d.force_rear=0;saved=capture(d);saved['demo']=False;d.force_rear=15
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets)
        self.assertFalse(p.source_match_needed());p.match_sources()
        self.assertTrue(p.app.worker.commands.empty());self.assertFalse(sets)
        self.assertIn('cannot be mixed',p.message.config.call_args.kwargs['text'])

def inputs_gain(d):
    import mixer_scene_inputs as inputs
    return [inputs.read(d,i,'gain') for i in (1,2)]
