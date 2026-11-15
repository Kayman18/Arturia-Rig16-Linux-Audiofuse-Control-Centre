import copy,unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError,PARAMETERS
import test_preamp as native
from test_controls import Fn
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import mixer_scene as scene
import mixer_scene_inputs as inputs

class RearLinkSceneTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_native_link_unlink_all_eight_pairs_exact_packets(self,sleep):
        fixture=native.PreampTests();d,u=fixture.device();self.addCleanup(fixture.doCleanups)
        for name in ('rear_phase','rear_hpf'):u.values[PARAMETERS[name]]=0
        original=u.libusb_control_transfer
        def transfer(handle,bm,req,param,index,data,length,timeout):
            if bm==0x40 and req==0x11 and param==24:
                u.calls.append((bm,req,param,index,bytes(data),length,timeout))
                value=int.from_bytes(data,'little');mask=u.values[1,24]
                u.values[1,24]=mask|(1<<index) if value else mask&~(1<<index)
                return 2
            return original(handle,bm,req,param,index,data,length,timeout)
        u.libusb_control_transfer=Fn(transfer)
        for source in range(1,17,2):
            for value in (1,0):
                left=source-1;mask=(65535&~(3<<left))|((0 if value else 3)<<left)
                u.values[1,24]=mask
                expected={f:[inputs.read(d,source+i,f) for i in range(2)] for f in ('kind','input_link','gain','pad','phase','hpf','instrument')}
                u.calls.clear();inputs.apply_link(d,source,[value,value],expected)
                outs=[c for c in u.calls if c[0]==0x40]
                self.assertEqual(outs,[(0x40,0x11,24,i,value.to_bytes(2,'little'),2,1000) for i in (left,left+1)])
                self.assertEqual(u.values[1,24]&~(3<<left),mask&~(3<<left))

    def test_all_rear_pairs_link_and_unlink_with_settings_in_controller(self):
        for link in (1,0):
            d=DemoAF16Rig();d.force_rear=15
            if not link:
                for source in range(1,17,2):d.write_input_link(source,True)
            saved=capture(d)
            for e in saved['entries']:
                if e['bus']=='inputs':e['values'].update(input_link=[link,link],gain=[256,256 if link else 512],pad=[1,1],phase=[1,1],hpf=[1,1])
            helper=windows.MixerPageTests();p=helper.page();sets=[]
            p.refresh(saved);helper.drain(p,d,sets);self.assertFalse(sets)
            p.start_apply();helper.drain(p,d,sets)
            self.assertEqual(scene.plan(saved,capture(d)),[])
            self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
            links=[i for i,c in enumerate(sets) if c['field']=='input_link']
            settings=[i for i,c in enumerate(sets) if c['bus']=='inputs' and c['field']!='input_link']
            self.assertEqual(len(links),8)
            if link:self.assertLess(max(settings),min(links))
            else:self.assertLess(max(links),min(settings))

    def test_legacy_v13_requires_matching_input_links(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=scene.OUTPUT_LINK_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        d.write_input_link(5,True)
        with self.assertRaisesRegex(ValueError,'older scenes'):scene.plan(saved,capture(d))

    def test_front_source_and_inconsistent_targets_rejected_at_preview(self):
        d=DemoAF16Rig();saved=capture(d)
        for field,value in [('input_link',[None,None]),('gain',[256,512]),('pad',[0,1]),('phase',[0,1]),('hpf',[0,1])]:
            target=copy.deepcopy(saved);e=next(e for e in target['entries'] if e['bus']=='inputs' and e['source']==5)
            e['values']['input_link']=[1,1];e['values'][field]=value
            with self.assertRaises(ValueError):scene.plan(target,saved)
        d.force_rear=0;saved=capture(d);saved['format']=scene.REAR_LINK_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate'];target=copy.deepcopy(saved)
        e=next(e for e in target['entries'] if e['bus']=='inputs');e['values']['input_link']=[1,1]
        with self.assertRaisesRegex(ValueError,'rear inputs'):scene.plan(target,saved)

    def test_stale_source_or_gain_blocks_link_write(self):
        for field in ('gain','source'):
            d=DemoAF16Rig();saved=capture(d);target=copy.deepcopy(saved)
            e=next(e for e in target['entries'] if e['bus']=='inputs');e['values']['input_link']=[1,1]
            change=scene.plan(target,saved)[0]
            if field=='gain':d.inputs[1]['gain_raw']=256
            else:d.force_rear=0
            with patch('preamp.change') as write:
                with self.assertRaises(DeviceError):scene.apply_entry(d,saved['layout'],change)
                write.assert_not_called()

    def test_unexpected_link_side_effect_stops_without_retry(self):
        d=DemoAF16Rig();saved=capture(d);target=copy.deepcopy(saved)
        e=next(e for e in target['entries'] if e['bus']=='inputs' and e['source']==5);e['values']['input_link']=[1,1]
        change=scene.plan(target,saved)[0];original=d.write_input_link
        def link(*args):
            result=original(*args);d.inputs[5]['gain_raw']=256;return result
        with patch.object(d,'write_input_link',side_effect=link) as setter:
            with self.assertRaisesRegex(DeviceError,'not confirmed'):scene.apply_entry(d,saved['layout'],change)
            self.assertEqual(setter.call_count,1)

    def test_preflight_change_prevents_all_writes(self):
        d=DemoAF16Rig();saved=capture(d)
        next(e for e in saved['entries'] if e['bus']=='inputs' and e['source']==5)['values']['input_link']=[1,1]
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets);d.inputs[5]['gain_raw']=256
        p.start_apply();helper.drain(p,d,sets)
        self.assertFalse(sets);self.assertIn('changed after preview',p.message.config.call_args.kwargs['text'])

    def test_partial_link_failure_stops_remaining_scene(self):
        d=DemoAF16Rig();saved=capture(d)
        for e in saved['entries']:
            if e['bus']=='inputs' and e['source'] in (5,7):e['values']['input_link']=[1,1]
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets)
        def partial(source,value):
            d.inputs[source]['link']=1
            raise DeviceError('second link bit rejected')
        with patch.object(d,'write_input_link',side_effect=partial) as setter:
            p.start_apply();helper.drain(p,d,sets)
            self.assertEqual(setter.call_count,1)
        self.assertEqual(len(sets),1);self.assertEqual(d.inputs[7]['link'],0)
        self.assertIn('second link bit rejected',p.message.config.call_args.kwargs['text'])
