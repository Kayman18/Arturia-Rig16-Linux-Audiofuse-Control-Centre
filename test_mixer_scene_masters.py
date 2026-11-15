import copy,unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,PARAMETERS
from test_controls import FakeUSB,Fn
from test_mixer_scene import capture
import mixer_scene as m
import mixer_scene_masters as masters
import test_mixer_scene_window as pagebase

class SceneMasterTests(unittest.TestCase):
    def test_all_new_fields_read_and_recall(self):
        d=DemoAF16Rig();saved=capture(d)
        master=next(e for e in saved['entries'] if e['bus']=='main' and e['source']==0)
        self.assertEqual(set(master['values']),{'level',*masters.FIELDS})
        for field in masters.FIELDS:master['values'][field]=[-256 if field.endswith('_level') else 1]
        changes=m.plan(saved,capture(d));self.assertEqual(len(changes),15)
        self.assertEqual([c['field'] for c in changes[-2:]],['aux_link12','aux_link34'])
        for c in changes:m.apply_entry(d,saved['layout'],c)
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_v1_leaves_new_settings_untouched(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=m.LEGACY_FORMAT;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
        saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('routing','names','monitor','phones','speaker_b','outputs','inputs')]
        for e in saved['entries']:
            if e['source']==0:e['values']={'level':e['values']['level']}
        d.aux1_master=-256;d.aux_link_mask=10;d.cue_enabled=1
        saved['entries'][0]['values']['pan']=[10]
        changes=m.plan(saved,capture(d));self.assertEqual(len(changes),1)
        for c in changes:m.apply_entry(d,saved['layout'],c)
        self.assertEqual((d.aux1_master,d.aux_link_mask,d.cue_enabled),(-256,10,1))
    def test_new_file_requires_every_master_field(self):
        scene=capture(DemoAF16Rig());master=next(e for e in scene['entries'] if e['bus']=='main' and e['source']==0)
        for field in masters.FIELDS:
            old=master['values'].pop(field)
            with self.assertRaises(ValueError):m.validate(scene)
            master['values'][field]=old
        for value in (-1,2,True):
            master['values']['cue_enabled']=[value]
            with self.assertRaises(ValueError):m.validate(scene)
    def test_stale_master_rejects_before_write(self):
        d=DemoAF16Rig();scene=capture(d)
        c=dict(bus='main',source=0,stereo=False,field='aux1_mute',expected=[0],values=[1])
        d.aux_mute_mask=1
        with patch('mixer_scene_masters.write') as write:
            with self.assertRaises(DeviceError):m.apply_entry(d,scene['layout'],c)
            write.assert_not_called()
    @patch('af16rig.time.sleep')
    def test_native_packets_and_reserved_mask_bits(self,sleep):
        usb=FakeUSB()
        for field in masters.FIELDS:
            name,index,bit=masters.address(field)
            usb.values[PARAMETERS[name]]=0xa000 if bit else ((-12*256)&65535) if field.endswith('_level') else 0
        original=usb.libusb_control_transfer
        packed={PARAMETERS[n] for n in ('aux_mute','aux_pre','aux_link')}
        def transfer(h,bm,req,param,index,data,length,timeout):
            key=(req-0x10,param)
            old=usb.values.get(key,0)
            result=original(h,bm,req,param,index,data,length,timeout)
            if bm==0x40 and key in packed:
                value=int.from_bytes(data,'little');usb.values[key]=old|(1<<index) if value else old&~(1<<index)
            return result
        usb.libusb_control_transfer=Fn(transfer);d=AF16Rig(usb);d.open();self.addCleanup(d.close)
        for field in masters.FIELDS:
            name,index,bit=masters.address(field);target=-256 if field.endswith('_level') else 1
            usb.calls.clear();masters.write(d,field,target)
            self.assertEqual(masters.read(d,field),target)
            outs=[c for c in usb.calls if c[0]==0x40]
            self.assertEqual([(c[1],c[2],c[3],int.from_bytes(c[4],'little')) for c in outs],[(0x10+PARAMETERS[name][0],PARAMETERS[name][1],index,target&65535)])
            if bit:self.assertEqual(usb.values[PARAMETERS[name]]&0xa000,0xa000)
    def test_final_capture_detects_side_effect_on_earlier_control(self):
        base=pagebase.MixerPageTests();p=base.page();d=DemoAF16Rig();target=base.target(d);sets=[]
        p.refresh(target);base.drain(p,d,sets);original=m.write_value
        def write(device,bus,source,field,value):
            original(device,bus,source,field,value)
            if field=='mute':device.pan_positions[('main',1)]=88
        with patch('mixer_scene.write_value',side_effect=write):p.start_apply();base.drain(p,d,sets)
        self.assertFalse(p.busy);self.assertIsNone(p.scene)
        self.assertIn('final readback',p.message.config.call_args.kwargs['text'])
    def test_final_capture_confirms_complete_scene(self):
        base=pagebase.MixerPageTests();p=base.page();d=DemoAF16Rig();target=base.target(d);sets=[]
        p.refresh(target);base.drain(p,d,sets);p.start_apply();base.drain(p,d,sets)
        self.assertEqual(p.mode,'verify');self.assertIsNotNone(p.scene);self.assertFalse(p.busy)
        self.assertIn('complete scene readback',p.message.config.call_args.kwargs['text'])

if __name__=='__main__':unittest.main()
