import copy,unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError,PARAMETERS
from test_controls import Fn
from test_mixer_scene import capture
import test_preamp as native
import test_mixer_scene_window as windows
import mixer_scene as scene
import mixer_scene_inputs as inputs

class FrontLinkSceneTests(unittest.TestCase):
    def demo(self,kind):
        d=DemoAF16Rig();d.force_rear=0;d.detect_status=0x21 if kind=='line' else 0x42
        return d

    @patch('af16rig.time.sleep')
    def test_native_line_and_mic_link_unlink_packets_and_preservation(self,sleep):
        for kind,param in (('line',22),('mic',23)):
            fixture=native.PreampTests();d,u=fixture.device(0x21 if kind=='line' else 0x42);self.addCleanup(fixture.doCleanups)
            for field in ('front_line_phase','front_line_hpf','front_mic_phase','front_mic_hpf','front_line_instrument'):u.values[PARAMETERS[field]]=0
            original=u.libusb_control_transfer
            def transfer(handle,bm,req,parameter,index,data,length,timeout):
                if bm==0x40 and req==0x11 and parameter in (22,23):
                    u.calls.append((bm,req,parameter,index,bytes(data),length,timeout))
                    if not u.ignore_writes:
                        value=int.from_bytes(data,'little');mask=u.values[1,parameter]
                        u.values[1,parameter]=mask|(1<<index) if value else mask&~(1<<index)
                    return 2
                return original(handle,bm,req,parameter,index,data,length,timeout)
            u.libusb_control_transfer=Fn(transfer)
            u.values[1,param]=128;u.values[1,24]=0x5555
            for value in (1,0):
                expected={f:[inputs.read(d,1+i,f) for i in range(2)] for f in ('kind','input_link','gain','pad','phase','hpf','instrument')}
                u.calls.clear();inputs.apply_link(d,1,[value]*2,expected)
                self.assertEqual([c for c in u.calls if c[0]==0x40],[(0x40,0x11,param,0,value.to_bytes(2,'little'),2,1000)])
                self.assertEqual(u.values[1,param],128|value);self.assertEqual(u.values[1,24],0x5555)
            expected={f:[inputs.read(d,1+i,f) for i in range(2)] for f in expected}
            u.ignore_writes=True;u.calls.clear()
            with self.assertRaises(DeviceError):inputs.apply_link(d,1,[1,1],expected)
            self.assertEqual(sum(c[0]==0x40 for c in u.calls),1)

    def test_full_line_mic_recall_both_directions(self):
        for kind in ('line','mic'):
            for link in (1,0):
                d=self.demo(kind);d.write_front_link(kind,not bool(link));saved=capture(d)
                e=next(e for e in saved['entries'] if e['bus']=='inputs' and e['source']==1)
                e['values'].update(input_link=[link]*2,gain=[5*256,(5 if link else 9)*256],pad=[1,1],phase=[1,1],hpf=[1,1])
                if kind=='line':e['values']['instrument']=[1,1 if link else 0]
                helper=windows.MixerPageTests();p=helper.page();sets=[]
                p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
                p.start_apply();helper.drain(p,d,sets)
                self.assertEqual(scene.plan(saved,capture(d)),[])
                self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
                self.assertEqual(sets[-1 if link else 0]['field'],'input_link')

    def test_instrument_mismatch_blocks_link_preview(self):
        d=self.demo('line');saved=capture(d);target=copy.deepcopy(saved)
        e=next(e for e in target['entries'] if e['bus']=='inputs' and e['source']==1)
        e['values'].update(input_link=[1,1],instrument=[1,0])
        with self.assertRaisesRegex(ValueError,'settings differ'):scene.plan(target,saved)

    def test_mixed_front_modes_and_mini_cannot_link(self):
        for detected,source in ((0x41,1),(0x10,3)):
            d=DemoAF16Rig();d.force_rear=0;d.detect_status=detected;saved=capture(d);target=copy.deepcopy(saved)
            e=next(e for e in target['entries'] if e['bus']=='inputs' and e['source']==source);e['values']['input_link']=[1,1]
            with self.assertRaisesRegex(ValueError,'matching'):scene.plan(target,saved)

    def test_source_or_instrument_changed_after_preview_no_link_write(self):
        for change_source in (True,False):
            d=self.demo('line');saved=capture(d);target=copy.deepcopy(saved)
            next(e for e in target['entries'] if e['bus']=='inputs')['values']['input_link']=[1,1]
            c=scene.plan(target,saved)[0]
            if change_source:d.force_rear=3
            else:d.front_instrument_1=1
            with patch.object(d,'write_front_link') as setter:
                with self.assertRaises(DeviceError):scene.apply_entry(d,saved['layout'],c)
                setter.assert_not_called()

    def test_front_link_side_effect_stops_without_retry(self):
        d=self.demo('mic');saved=capture(d);target=copy.deepcopy(saved)
        next(e for e in target['entries'] if e['bus']=='inputs')['values']['input_link']=[1,1]
        c=scene.plan(target,saved)[0];original=d.write_front_link
        def write(*args):
            result=original(*args);d.front_gain_mic_1=2;return result
        with patch.object(d,'write_front_link',side_effect=write) as setter:
            with self.assertRaisesRegex(DeviceError,'not confirmed'):scene.apply_entry(d,saved['layout'],c)
            self.assertEqual(setter.call_count,1)

    def test_v14_keeps_rear_and_output_link_recall(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=scene.REAR_LINK_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        next(e for e in saved['entries'] if e['bus']=='inputs' and e['source']==5)['values']['input_link']=[1,1]
        next(e for e in saved['entries'] if e['bus']=='outputs')['values']['link']=[1,1]
        changes=scene.plan(saved,capture(d));self.assertEqual(len(changes),2)
        for c in changes:scene.apply_entry(d,saved['layout'],c)
        self.assertEqual(scene.plan(saved,capture(d)),[])
