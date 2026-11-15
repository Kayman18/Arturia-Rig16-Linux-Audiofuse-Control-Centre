import copy,unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError,PARAMETERS
from test_controls import Fn
from test_mixer_scene import capture
import test_preamp as native
import test_mixer_scene_window as windows
import mixer_scene as m
import mixer_scene_inputs as inputs

class SceneInputFilterTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_native_switch_packets_and_preservation_of_unrelated_bits(self,sleep):
        fixture=native.PreampTests()
        cases=[(0,ch,'rear') for ch in range(1,17)]+[(0x21,ch,'line') for ch in (1,2)]+[(0x42,ch,'mic') for ch in (1,2)]+[(0x10,ch,'mini') for ch in (3,4)]
        for detected,ch,kind in cases:
            d,u=fixture.device(detected);self.addCleanup(d.close)
            for field in ('phase','hpf'):
                if kind=='mini' and field=='hpf':continue
                name=('rear_' if kind=='rear' else 'front_'+('line' if kind=='mini' else kind)+'_')+field
                key=PARAMETERS[name];u.values[key]=0x8000 if ch!=16 else 1
                before=u.values[key];original=u.libusb_control_transfer
                def transfer(h,bm,req,param,index,data,length,timeout):
                    old=u.values.get(key,0);result=original(h,bm,req,param,index,data,length,timeout)
                    if bm==0x40 and (req-0x10,param)==key:
                        value=int.from_bytes(data,'little');u.values[key]=old|(1<<index) if value else old&~(1<<index)
                    return result
                u.libusb_control_transfer=Fn(transfer);u.calls.clear()
                inputs.write(d,ch,kind,field,1)
                outs=[c for c in u.calls if c[0]==0x40]
                self.assertEqual(len(outs),1)
                self.assertEqual(outs[0][1:5],(0x10+key[0],key[1],ch-1,b'\x01\x00'))
                self.assertEqual(u.values[key],before|(1<<(ch-1)))
                self.assertEqual(inputs.read(d,ch,field),1)
                u.libusb_control_transfer=original
    def test_v8_leaves_phase_and_hpf_alone(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.INPUT_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        for e in saved['entries']:
            if e['bus']=='inputs':
                e['values'].pop('phase');e['values'].pop('hpf');e['values'].pop('instrument')
        d.inputs[5]['phase']=1;d.inputs[5]['hpf']=1
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_mini_hpf_is_unavailable_and_cannot_be_fabricated(self):
        d=DemoAF16Rig();d.force_rear=0;saved=capture(d)
        entry=next(e for e in saved['entries'] if e['bus']=='inputs' and e['source']==3)
        self.assertEqual(entry['values']['hpf'],[None,None])
        entry['values']['hpf']=[1,1]
        with self.assertRaises(ValueError):m.validate(saved)
        with self.assertRaises(ValueError):inputs.write(d,3,'mini','hpf',1)
    def test_incremental_front_and_rear_batches(self):
        for front in (False,True):
            helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();d.force_rear=0 if front else 3;target=capture(d);sets=[]
            for e in target['entries']:
                if e['bus']=='inputs':
                    e['values']['phase']=[1,1]
                    e['values']['hpf']=[None if k=='mini' else 1 for k in e['values']['kind']]
            p.refresh(target);helper.drain(p,d,sets);self.assertFalse(sets)
            p.start_apply();helper.drain(p,d,sets)
            self.assertEqual(len(sets),15) # Demo inputs 3/4 use mini in both modes.
            self.assertEqual(m.plan(target,capture(d)),[])
            self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
    def test_changed_source_stops_switch_write(self):
        d=DemoAF16Rig();saved=capture(d);target=copy.deepcopy(saved)
        next(e for e in target['entries'] if e['bus']=='inputs')['values']['phase']=[1,1]
        change=m.plan(target,saved)[0];d.force_rear=0
        with patch('mixer_scene_inputs.write') as write:
            with self.assertRaises(DeviceError):m.apply_entry(d,saved['layout'],change)
            write.assert_not_called()
