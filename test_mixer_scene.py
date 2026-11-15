import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,PARAMETERS
from test_digital_mixer import DigitalUSB
import mixer_scene as m

def capture(d):
    layout=m.topology(d)
    return m.make_scene(layout,[m.read_entry(d,layout,a) for a in m.addresses(layout)],isinstance(d,DemoAF16Rig))

class MixerSceneTests(unittest.TestCase):
    def test_roundtrip_complete_fields(self):
        d=DemoAF16Rig();scene=capture(d);self.assertEqual(len(scene['entries']),172)
        self.assertEqual(set(scene['entries'][0]['values']),set(m.BASE+m.SENDS))
        self.assertEqual(m.plan(scene,capture(d)),[])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'scene.json';p.write_text(json.dumps(scene));self.assertEqual(m.load_scene(p),scene)
    def test_all_supported_fields_restore_demo(self):
        d=DemoAF16Rig();saved=capture(d)
        for e in saved['entries']:
            for f,v in e['values'].items():
                if f in ('link','kind','input_link'):continue
                if f=='instrument':
                    e['values'][f]=[1 if k=='line' and e['source']+i in (1,2) else None for i,k in enumerate(e['values']['kind'])];continue
                if f=='hpf':
                    e['values'][f]=[None if k=='mini' else 1 for k in e['values']['kind']];continue
                e['values'][f]=[None if f=='rate' else 23 if f=='clock_config' else 15 if f=='ab_config' else 'Scene label' if f=='name' else 64 if f=='route' else 256 if f=='gain' else 13 if f=='pan' else 1 if m.bounds(f,e['source'])==(0,1) else -256]*len(v)
        changes=m.plan(saved,capture(d));self.assertGreater(len(changes),200)
        for c in changes:m.apply_entry(d,saved['layout'],c)
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_stereo_independent_levels_pan_and_flags_preserved(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1;saved=capture(d)
        e=saved['entries'][0];e['values'].update(level=[-256,-1024],pan=[17,240],mute=[1,0],send1_level=[-512,-768])
        for c in m.plan(saved,capture(d)):m.apply_entry(d,saved['layout'],c)
        self.assertEqual(m.plan(saved,capture(d)),[])
    def test_bad_fields_values_missing_entries_rejected(self):
        scene=capture(DemoAF16Rig())
        for f,v in [('pan',[255]),('mute',[2]),('level',[True]),('level',[-15361]),('send1_level',[1537])]:
            bad=copy.deepcopy(scene);bad['entries'][0]['values'][f]=v
            with self.assertRaises(ValueError):m.validate(bad)
        for modify in (lambda s:s['entries'].pop(),lambda s:s['entries'][0]['values'].pop('pan'),lambda s:s['entries'][0]['values'].update(gain=[1])):
            bad=copy.deepcopy(scene);modify(bad)
            with self.assertRaises(ValueError):m.validate(bad)
    def test_stale_value_and_layout_prevent_write(self):
        d=DemoAF16Rig();scene=capture(d);target=copy.deepcopy(scene);target['entries'][0]['values']['pan']=[20]
        c=m.plan(target,scene)[0];d.pan_positions={('main',1):30}
        with self.assertRaises(DeviceError):m.apply_entry(d,scene['layout'],c)
        self.assertEqual(d.pan_positions[('main',1)],30)
        d.pan_positions={};d.main_show=65534
        with self.assertRaises(DeviceError):m.apply_entry(d,scene['layout'],c)
    def test_partial_pair_failure_is_not_retried(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1;scene=capture(d)
        c=dict(bus='main',source=1,stereo=True,field='pan',values=[0,254],expected=[127,127]);original=m.write_value
        def write(device,bus,source,field,value):
            if source==2:raise DeviceError('rejected')
            original(device,bus,source,field,value)
        with patch('mixer_scene.write_value',side_effect=write) as call:
            with self.assertRaises(DeviceError):m.apply_entry(d,scene['layout'],c)
            self.assertEqual(call.call_count,2)
        self.assertEqual(d.pan_positions,{('main',1):0})
    @patch('af16rig.time.sleep')
    @patch('digital_mixer.time.sleep')
    def test_native_packets_all_channels_and_fields(self,*sleep):
        usb=DigitalUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close)
        for bus in ('main','cue'):
            for source in range(1,65):
                usb.packed[34 if bus=='main' else 48]=1<<(source-1)
                usb.packed[35 if bus=='main' else 49]=0
                layout=m.topology(d);address=dict(bus=bus,source=source,stereo=False)
                entry=m.read_entry(d,layout,address)
                for field,old in entry['values'].items():
                    target=42 if field=='pan' else 1-old[0] if m.bounds(field,source)==(0,1) else -256
                    usb.out.clear();change=dict(address,field=field,values=[target],expected=old)
                    m.apply_entry(d,layout,change)
                    name,_=m.native(bus,source,field)
                    self.assertEqual(usb.out,[(0x40,0x11,PARAMETERS[name][1],source-1,target&65535)])
    def test_file_limits_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'scene.json'
            for text in (' '*(m.MAX_BYTES+1),'{"format":1,"format":2}'):
                p.write_text(text)
                with self.assertRaises(ValueError):m.load_scene(p)

if __name__=='__main__':unittest.main()
