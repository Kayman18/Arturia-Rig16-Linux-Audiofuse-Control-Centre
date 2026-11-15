import copy,unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError
import mixer_scene as m
from test_mixer_scene import capture
import test_routing_write as routes
import test_mixer_scene_window as windows
from mixer_scene_window import MixerSceneWindow

class SceneRoutesTests(unittest.TestCase):
    def test_all_native_destinations_exact_packets_and_reserved_untouched(self):
        fixture=routes.RouteWriteTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        d=fixture.device;layout=m.topology(d)
        for destination in range(60):
            a=dict(bus='routing',source=destination,stereo=False)
            old=m.read_entry(d,layout,a)['values']['route']
            fixture.usb.calls.clear()
            m.apply_entry(d,layout,dict(a,field='route',expected=old,values=[64]))
            self.assertEqual(len(fixture.writes()),1)
            self.assertEqual(fixture.writes()[0][1:5],(0x11,64,destination,b'\x40\x00'))
            self.assertEqual(m.read_entry(d,layout,a)['values'],{'route':[64]})
        self.assertEqual((fixture.routes[60],fixture.routes[61]),(156,157))
    def test_v1_v2_do_not_restore_routes(self):
        for fmt in (m.LEGACY_FORMAT,m.MASTER_FORMAT):
            d=DemoAF16Rig();saved=capture(d);saved['format']=fmt;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
            saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
            saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('routing','names','monitor','phones','speaker_b','outputs','inputs')]
            if fmt==m.LEGACY_FORMAT:
                for e in saved['entries']:
                    if e['source']==0:e['values']={'level':e['values']['level']}
            d.output_routes={0:64}
            self.assertEqual(m.plan(saved,capture(d)),[])
    def test_unknown_and_invalid_routes_rejected(self):
        original=capture(DemoAF16Rig())
        for value in (0,63,96,127,160,191,198,True,64.0):
            bad=copy.deepcopy(original);next(e for e in bad['entries'] if e['bus']=='routing')['values']['route']=[value]
            with self.assertRaises(ValueError):m.validate(bad)
        for destination in (60,61,True,-1):
            bad=copy.deepcopy(original);next(e for e in bad['entries'] if e['bus']=='routing')['source']=destination
            with self.assertRaises(ValueError):m.validate(bad)
    def test_stale_route_prevents_write(self):
        d=DemoAF16Rig();layout=m.topology(d);d.output_routes={0:65}
        c=dict(bus='routing',source=0,stereo=False,field='route',expected=[128],values=[64])
        with patch.object(d,'write_output_route') as write:
            with self.assertRaises(DeviceError):m.apply_entry(d,layout,c)
            write.assert_not_called()
    def test_incremental_ui_preview_recall_and_route_labels(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d)
        for e in target['entries']:
            if e['bus']=='routing':e['values']['route']=[64]
        target['entries'][0]['values']['mute']=[1]
        sets=[];p.refresh(target);helper.drain(p,d,sets)
        self.assertEqual(len(p.changes),61);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),61);self.assertEqual(sets[0]['field'],'mute')
        self.assertEqual(m.plan(target,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
        e=dict(bus='routing',source=0,stereo=False,field='route',values=[64])
        self.assertEqual(MixerSceneWindow.label(e),'ROUTE · Speakers L')
        self.assertEqual(MixerSceneWindow.db(e),'Analog 1')
    def test_final_readback_detects_route_side_effect(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d)
        next(e for e in target['entries'] if e['bus']=='routing' and e['source']==59)['values']['route']=[64]
        original=d.write_output_route
        def write(*a,**kw):
            result=original(*a,**kw);d.output_routes[0]=65;return result
        sets=[];p.refresh(target);helper.drain(p,d,sets)
        with patch.object(d,'write_output_route',side_effect=write):
            p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1)
        self.assertIn('differ on final readback',p.message.config.call_args.kwargs['text'])
