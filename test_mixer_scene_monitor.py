import copy,unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,PARAMETERS
from test_controls import FakeUSB
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import mixer_scene as m
from mixer_scene_window import MixerSceneWindow

class SceneMonitorTests(unittest.TestCase):
    @patch('af16rig.time.sleep')
    def test_native_packet_mappings_all_six_settings(self,sleep):
        usb=FakeUSB();usb.values[PARAMETERS['phones_knob']]=(-12*256)&65535
        d=AF16Rig(usb);d.open();self.addCleanup(d.close);layout=m.topology(d)
        for bus,field,param,value in [('monitor','level','speaker_level',-256),('phones','level','phones_knob',-512),('monitor','mute','mute',1),('monitor','mono','mono',1),('monitor','dim','dim',1),('monitor','dim_depth','dim_depth',1)]:
            a=dict(bus=bus,source=0,stereo=False);old=m.read_entry(d,layout,a)['values'][field]
            usb.calls.clear();m.apply_entry(d,layout,dict(a,field=field,expected=old,values=[value]))
            outs=[c for c in usb.calls if c[0]==0x40];group,index=PARAMETERS[param]
            self.assertEqual(len(outs),1)
            self.assertEqual(outs[0][1:5],(0x10+group,index,0,(value&65535).to_bytes(2,'little')))
            self.assertEqual(m.read_entry(d,layout,a)['values'][field],[value])
    def test_all_legacy_formats_leave_monitor_and_phones(self):
        for fmt in (m.LEGACY_FORMAT,m.MASTER_FORMAT,m.ROUTING_FORMAT,m.NAMES_FORMAT):
            d=DemoAF16Rig();saved=capture(d);saved['format']=fmt;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
            saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
            allowed={'main','cue'}
            if fmt in (m.ROUTING_FORMAT,m.NAMES_FORMAT):allowed.add('routing')
            if fmt==m.NAMES_FORMAT:allowed.add('names')
            saved['entries']=[e for e in saved['entries'] if e['bus'] in allowed]
            if fmt==m.LEGACY_FORMAT:
                for e in saved['entries']:
                    if e['source']==0:e['values']={'level':e['values']['level']}
            d.values.update(speaker_level=0,mute=1,mono=1,dim=1);d.phones_knob=0;d.dim_depth=1
            self.assertEqual(m.plan(saved,capture(d)),[])
    def test_invalid_ranges_and_infinity_cannot_be_recalled(self):
        saved=capture(DemoAF16Rig())
        for bus,field,value in [('monitor','level',1),('phones','level',-32768),('monitor','dim_depth',2),('monitor','mono',True)]:
            bad=copy.deepcopy(saved);next(e for e in bad['entries'] if e['bus']==bus)['values'][field]=[value]
            with self.assertRaises(ValueError):m.validate(bad)
        d=DemoAF16Rig();d.phones_knob=32768
        with self.assertRaises(ValueError):capture(d)
    def test_stale_level_rejected_without_write(self):
        d=DemoAF16Rig();layout=m.topology(d)
        for bus in ('monitor','phones'):
            with patch('mixer_scene_monitor.write') as write:
                with self.assertRaises(DeviceError):m.apply_entry(d,layout,dict(bus=bus,source=0,stereo=False,field='level',expected=[0],values=[-256]))
                write.assert_not_called()
    def test_batch_recall_and_control_order(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d);sets=[]
        for e in target['entries']:
            if e['bus'] in ('monitor','phones'):
                for field in e['values']:e['values'][field]=[-256 if field=='level' else 1]
        p.refresh(target);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),6)
        self.assertEqual([c['field'] for c in sets],['level','level','dim_depth','mono','dim','mute'])
        self.assertEqual(m.plan(target,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
        self.assertEqual(MixerSceneWindow.db(dict(field='dim_depth',values=[1])),'−20 dB')
    def test_final_read_detects_side_effect(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d);sets=[]
        next(e for e in target['entries'] if e['bus']=='monitor')['values']['mute']=[1]
        original=d.write_bool
        def write(*args):
            result=original(*args);d.phones_knob=0;return result
        p.refresh(target);helper.drain(p,d,sets)
        with patch.object(d,'write_bool',side_effect=write):
            p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1)
        self.assertIn('differ on final readback',p.message.config.call_args.kwargs['text'])
