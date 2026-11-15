import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected,PARAMETERS
from fader_scene import topology,addresses,read_entry,make_scene,validate,plan,apply_entry,load_scene
from test_digital_mixer import DigitalUSB

def capture(d):
    layout=topology(d)
    return make_scene(layout,[read_entry(d,layout,a) for a in addresses(layout)],isinstance(d,DemoAF16Rig))

class SceneModelTests(unittest.TestCase):
    def test_demo_capture_is_detached_and_complete(self):
        d=DemoAF16Rig();scene=capture(d)
        self.assertEqual(len(scene['entries']),34)
        self.assertEqual(plan(scene,capture(d)),[])
        d.mix_levels={('main',1):-256};self.assertEqual(scene['entries'][0]['levels'],[-3072])
    def test_recall_demo_channels_masters_and_repeat_noop(self):
        d=DemoAF16Rig();saved=capture(d);d.mix_levels={('main',1):-256,('cue',4):-2*256};d.main_master=-5*256
        current=capture(d);changes=plan(saved,current);self.assertEqual(len(changes),3)
        for c in changes:apply_entry(d,current['layout'],c)
        self.assertEqual(plan(saved,capture(d)),[])
    def test_demo_analog_stereo_offset_preserved(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1;d.mix_levels={('main',1):-3072,('main',2):-3840}
        scene=capture(d);d.mix_levels.update({('main',1):-2560,('main',2):-3328})
        changes=plan(scene,capture(d));self.assertEqual(len(changes),1)
        apply_entry(d,scene['layout'],changes[0]);self.assertEqual(plan(scene,capture(d)),[])
    def test_stereo_offset_mismatch_blocks_entire_plan(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1;saved=capture(d)
        d.mix_levels={('main',2):-2560}
        with self.assertRaisesRegex(ValueError,'offset'):plan(saved,capture(d))
    def test_layout_change_and_demo_file_rejected(self):
        d=DemoAF16Rig();scene=capture(d);other=copy.deepcopy(scene);other['demo']=False
        with self.assertRaisesRegex(ValueError,'Demo'):plan(scene,other)
        d.main_show=65534
        with self.assertRaisesRegex(ValueError,'layout'):plan(scene,capture(d))
    def test_bad_values_missing_duplicate_addresses(self):
        scene=capture(DemoAF16Rig())
        edits=[lambda s:s['entries'].pop(),lambda s:s['entries'].__setitem__(1,s['entries'][0]),
            lambda s:s['entries'][0].update(levels=[True]),lambda s:s['entries'][0].update(levels=[1537]),
            lambda s:s['entries'][0].update(source=True),lambda s:s['entries'][0].update(stereo=0),
            lambda s:s.update(state_version=True),lambda s:s['layout']['main'].__setitem__(0,1<<64),
            lambda s:s['entries'][0].update(levels=[-15361]),lambda s:s['entries'][0].update(levels=[0,0])]
        for edit in edits:
            bad=copy.deepcopy(scene);edit(bad)
            with self.assertRaises(ValueError):validate(bad)
    def test_ambiguous_layout_rejected(self):
        d=DemoAF16Rig();d.main_stereo=1
        with self.assertRaisesRegex(ValueError,'Ambiguous'):topology(d)
    def test_file_limit_duplicate_keys_and_roundtrip(self):
        scene=capture(DemoAF16Rig())
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'scene.json';p.write_text(json.dumps(scene));self.assertEqual(load_scene(p),scene)
            for text in (' '*65537,'{"format":1,"format":2}', '['*10000):
                p.write_text(text)
                with self.assertRaises(ValueError):load_scene(p)
    def test_changed_expected_no_apply(self):
        d=DemoAF16Rig();saved=capture(d);d.mix_levels={('main',1):-256};current=capture(d);change=plan(saved,current)[0]
        d.mix_levels['main',1]=-512
        with self.assertRaisesRegex(DeviceError,'changed'):apply_entry(d,current['layout'],change)
        self.assertEqual(d.mix_levels['main',1],-512)
    def test_unknown_version_rejected(self):
        d=DemoAF16Rig();d.version=19
        with self.assertRaises(DeviceError):topology(d)

class SceneNativeTests(unittest.TestCase):
    def setUp(self):
        self.usb=DigitalUSB();self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        for mod in ('af16rig','digital_mixer'):
            p=patch(mod+'.time.sleep');p.start();self.addCleanup(p.stop)
    def select(self,source,stereo=False,bus='main'):
        self.usb.packed[34 if bus=='main' else 48]=0 if stereo else 1<<(source-1)
        self.usb.packed[35 if bus=='main' else 49]=1<<((source-1)//2) if stereo else 0
    def test_capture_no_out_all_64_sources_both_buses(self):
        self.usb.packed[34]=self.usb.packed[48]=(1<<64)-1
        scene=capture(self.d);self.assertEqual(len(scene['entries']),130)
        self.assertFalse(self.usb.out);self.assertFalse([c for c in self.usb.calls if c[0]==0x40])
    def test_analog_and_digital_writes_use_existing_indexed_path(self):
        for source in (1,16,17,32,33,64):
            for bus in ('main','cue'):
                self.select(source,bus=bus);current=capture(self.d);saved=copy.deepcopy(current)
                e=next(e for e in saved['entries'] if e['bus']==bus and e['source']==source);e['levels']=[-256]
                change=plan(saved,current)[0];apply_entry(self.d,current['layout'],change)
                self.assertEqual(self.usb.out[-1],(0x40,0x11,36 if bus=='main' else 50,source-1,65536-256))
                self.assertEqual(plan(saved,capture(self.d)),[])
    def test_stereo_pair_offset_exact_targets_two_writes(self):
        self.select(33,True);self.usb.words[36,32]=(-3072)&65535;self.usb.words[36,33]=(-3840)&65535
        current=capture(self.d);saved=copy.deepcopy(current);saved['entries'][0]['levels']=[-2560,-3328]
        apply_entry(self.d,current['layout'],plan(saved,current)[0])
        self.assertEqual(self.usb.out,[(0x40,0x11,36,32,(-2560)&65535),(0x40,0x11,36,33,(-3328)&65535)])
    def test_master_uses_existing_master_command(self):
        current=capture(self.d);saved=copy.deepcopy(current);saved['entries'][0]['levels']=[-256]
        apply_entry(self.d,current['layout'],plan(saved,current)[0])
        self.assertEqual(self.usb.values[PARAMETERS['main_master']],65536-256)
    def test_topology_changed_no_out(self):
        self.select(33);current=capture(self.d);saved=copy.deepcopy(current);saved['entries'][0]['levels']=[0]
        change=plan(saved,current)[0];self.usb.packed[34]=0
        with self.assertRaisesRegex(DeviceError,'layout'):apply_entry(self.d,current['layout'],change)
        self.assertFalse(self.usb.out)
    def test_ignored_write_not_retried(self):
        self.select(33);current=capture(self.d);saved=copy.deepcopy(current);saved['entries'][0]['levels']=[0]
        self.usb.ignore=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):apply_entry(self.d,current['layout'],plan(saved,current)[0])
        self.assertEqual(len(self.usb.out),1)
    def test_disconnect_is_propagated(self):
        self.select(33);current=capture(self.d);saved=copy.deepcopy(current);saved['entries'][0]['levels']=[0]
        self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):apply_entry(self.d,current['layout'],plan(saved,current)[0])
        self.assertEqual(len(self.usb.out),1)
    def test_short_read_never_becomes_scene(self):
        self.usb.read_rc=1
        with self.assertRaises(DeviceError):capture(self.d)
        self.assertFalse(self.usb.out)

import test_device_presets as worker_fixtures
class SceneWorkerTests(unittest.TestCase):
    worker_event=worker_fixtures.PresetTests.worker_event
    def setUp(self):
        self.usb=DigitalUSB()
        for mod in ('af16rig','digital_mixer'):
            p=patch(mod+'.time.sleep');p.start();self.addCleanup(p.stop)
    def test_worker_read_layout_no_writes(self):
        events=self.worker_event(('scene_read',dict(connection_serial=1,request_id=55,part='layout')),'scene_snapshot')
        self.assertEqual(events[-1]['layout'],{'main':[0,0],'cue':[0,0]});self.assertFalse(self.usb.out)
    def test_worker_old_serial_never_applies(self):
        events=self.worker_event(('scene_set',dict(connection_serial=0,request_id=56)),'scene_error')
        self.assertIn('Connection changed',events[-1]['message']);self.assertFalse(self.usb.out)
    def test_worker_write_channel_confirmed(self):
        self.usb.packed[34]=1<<32
        change=dict(bus='main',source=33,stereo=False,levels=[-256],expected=[-3072])
        events=self.worker_event(('scene_set',dict(connection_serial=1,request_id=57,layout={'main':[1<<32,0],'cue':[0,0]},change=change)),'scene_written')
        self.assertEqual(events[-1]['record']['levels'],[-256]);self.assertEqual(len(self.usb.out),1)
