import unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError
import test_output_target as native
from test_controls import Fn
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import mixer_scene as scene
import mixer_scene_outputs as outputs

class OutputLinkSceneTests(unittest.TestCase):
    def native(self,mirror=False):
        fixture=native.OutputTargetTests();d,u=fixture.device();self.addCleanup(fixture.doCleanups)
        original=u.libusb_control_transfer
        def transfer(handle,bm,req,param,index,data,length,timeout):
            if bm==0x40 and req==0x11 and param==32:
                u.calls.append((bm,req,param,index,bytes(data),length,timeout))
                if not u.ignore_writes:
                    value=int.from_bytes(data,'little');mask=u.values[1,32]
                    u.values[1,32]=mask|(1<<index) if value else mask&~(1<<index)
                result=u.write_result
            else:result=original(handle,bm,req,param,index,data,length,timeout)
            if mirror and not u.ignore_writes and bm==0x40 and req==0x11:
                left=index//2*2
                if param==32 and int.from_bytes(data,'little')==1:
                    u.outputs[left+1]=u.outputs[left]
                if param==33 and u.values[1,32]&(3<<left):
                    u.outputs[index^1]=u.outputs[index]
            return result
        u.libusb_control_transfer=Fn(transfer)
        return d,u

    @patch('af16rig.time.sleep')
    def test_all_pairs_link_states_and_levels_with_native_mirroring(self,sleep):
        d,u=self.native(mirror=True)
        # 4 pairs x 4 starting bit combinations x 2 target modes x 3 levels.
        for source in (3,5,7,9):
            offset=source-3
            for bits in range(4):
                for linked in (0,1):
                    for levels in ([0,0],[-513,-513],[-15360,-15360] if linked else [-513,-1025]):
                        u.outputs={i:0 for i in range(8)}
                        u.values[1,32]=(255&~(3<<offset))|(bits<<offset)
                        before=outputs.pair_snapshot(d,source)
                        target=dict(level=list(levels),link=[linked]*2);u.calls.clear()
                        outputs.apply_pair(d,source,target,before)
                        self.assertEqual(outputs.pair_snapshot(d,source),target)
                        self.assertEqual(u.values[1,32]&~(3<<offset),255&~(3<<offset))
                        self.assertTrue(all(v==0 for i,v in u.outputs.items() if i not in (offset,offset+1)))
                        outs=[c for c in u.calls if c[0]==0x40]
                        self.assertLessEqual(len(outs),6)
                        self.assertTrue(all(c[2] in (32,33) and c[3] in (offset,offset+1) for c in outs))
                        link_on=[i for i,c in enumerate(outs) if c[2]==32 and c[4]==b'\x01\x00']
                        gains=[i for i,c in enumerate(outs) if c[2]==33]
                        if link_on and gains:self.assertLess(max(gains),min(link_on))

    def test_invalid_target_stale_state_and_version_no_writes(self):
        d=DemoAF16Rig();before=outputs.pair_snapshot(d,3)
        with patch.object(d,'write_output_link') as link,patch('mixer_scene_outputs.set_raw') as gain:
            for target in (dict(level=[0,0],link=[1,0]),dict(level=[0,-256],link=[1,1]),dict(level=[True,0],link=[0,0])):
                with self.assertRaises(ValueError):outputs.apply_pair(d,3,target,before)
            d.output_level_3=-256
            with self.assertRaises(DeviceError):outputs.apply_pair(d,3,before,before)
            d.version=19
            with self.assertRaises(DeviceError):outputs.apply_pair(d,3,before,before)
            link.assert_not_called();gain.assert_not_called()

    @patch('af16rig.time.sleep')
    def test_second_link_bit_failure_stops_without_gain_or_retry(self,sleep):
        d,u=self.native();u.values[1,32]=3;original=u.libusb_control_transfer
        def transfer(handle,bm,req,param,index,data,length,timeout):
            if bm==0x40 and req==0x11 and param==32 and index==1:u.ignore_writes=True
            return original(handle,bm,req,param,index,data,length,timeout)
        u.libusb_control_transfer=Fn(transfer);u.calls.clear()
        with self.assertRaises(DeviceError):outputs.apply_pair(d,3,dict(level=[-256,-512],link=[0,0]),dict(level=[0,0],link=[1,1]))
        outs=[c for c in u.calls if c[0]==0x40]
        self.assertEqual([(c[2],c[3]) for c in outs],[(32,0),(32,1)])
        self.assertEqual(u.values[1,32],2)

    def test_unexpected_gain_change_on_unlink_stops(self):
        d=DemoAF16Rig();d.output_link_mask=3;original=d.write_output_link
        def link(*args):
            result=original(*args);d.output_level_4=-256;return result
        with patch.object(d,'write_output_link',side_effect=link),patch('mixer_scene_outputs.set_raw') as gain:
            with self.assertRaises(DeviceError):outputs.apply_pair(d,3,dict(level=[-512,-512],link=[1,1]),dict(level=[0,0],link=[1,1]))
            gain.assert_not_called()

    def test_layout_change_during_pair_stops(self):
        d=DemoAF16Rig();saved=capture(d)
        target=next(e for e in saved['entries'] if e['bus']=='outputs');target['values']['level']=[-256,-512]
        change=scene.plan(saved,capture(d))[0];original=outputs.set_raw
        def gain(*args):
            result=original(*args);d.main_show=65534;return result
        with patch('mixer_scene_outputs.set_raw',side_effect=gain) as setter:
            with self.assertRaisesRegex(DeviceError,'layout'):scene.apply_entry(d,saved['layout'],change)
            self.assertEqual(setter.call_count,1)

    def test_new_scene_restores_all_four_pairs_in_controller(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();saved=capture(d);sets=[]
        for e in saved['entries']:
            if e['bus']=='outputs':e['values']=dict(level=[-513,-513],link=[1,1])
        p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),4);self.assertEqual(d.output_link_mask,255)
        self.assertEqual(scene.plan(saved,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])

    def test_old_scene_level_recall_updates_existing_configuration_row(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();saved=capture(d);sets=[]
        saved['format']=scene.CLOCK_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        next(e for e in saved['entries'] if e['bus']=='outputs')['values']['level']=[-513,-1025]
        p.refresh(saved);helper.drain(p,d,sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(scene.plan(saved,capture(d)),[])
        self.assertTrue(any(call.args[:2]==('outputs:3:configuration','current') for call in p.table.set.call_args_list))

    def test_noop_keeps_unequal_linked_snapshot_readable(self):
        d=DemoAF16Rig();d.output_link_mask=3;d.output_level_4=-256
        saved=capture(d);self.assertEqual(scene.plan(saved,capture(d)),[])
        d.output_level_3=-512
        with self.assertRaisesRegex(ValueError,'levels differ'):scene.plan(saved,capture(d))
