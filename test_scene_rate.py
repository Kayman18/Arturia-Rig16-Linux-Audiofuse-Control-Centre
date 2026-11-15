import copy,unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
from af16rig import DemoAF16Rig,DeviceError
from clock_controls import DEMO_RAW,RATES
from test_mixer_scene import capture
from test_sample_rate import status
import test_mixer_scene_window as windows
import mixer_scene as scene
import scene_rate as rate

class SceneRateTests(unittest.TestCase):
    def test_all_36_supported_demo_rate_transitions(self):
        for old in RATES[1:]:
            for target in RATES[1:]:
                d=DemoAF16Rig();d.clock_raw={**DEMO_RAW,'internal_frequency':RATES.index(old)}
                self.assertEqual(rate.read(d),old)
                self.assertEqual(rate.apply(d,target,old),target)
                self.assertEqual(rate.read(d),target)

    def test_stale_external_and_invalid_rates_never_apply(self):
        d=DemoAF16Rig()
        with patch('scene_rate.set_rate') as setter:
            with self.assertRaises(DeviceError):rate.apply(d,96000,44100)
            for target in (None,True,32000,48000.0):
                with self.assertRaises(ValueError):rate.apply(d,target,48000)
            d.clock_raw={**DEMO_RAW,'selected_source':1}
            self.assertIsNone(rate.read(d))
            with self.assertRaisesRegex(DeviceError,'Select Internal'):rate.apply(d,96000,None)
            setter.assert_not_called()

    @patch('sample_rate.time.sleep')
    def test_native_scene_matching_uses_one_alsa_apply_and_readback(self,sleep):
        d=SimpleNamespace(version=18,last_write=None);raw=DEMO_RAW.copy();backend=Mock()
        def apply(card,target,guard):guard();raw['internal_frequency']=RATES.index(target)
        backend.apply.side_effect=apply
        with patch('scene_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',return_value=status()),patch('sample_rate.AlsaRate',return_value=backend):
            self.assertEqual(rate.apply(d,96000,48000),96000)
        backend.apply.assert_called_once();self.assertTrue(d.last_write['confirmed'])

    def test_busy_native_stream_blocks_before_backend(self):
        d=SimpleNamespace(version=18,last_write=None);raw=DEMO_RAW.copy();busy=status();busy['streams'][0]['state']='RUNNING'
        with patch('scene_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',return_value=busy),patch('sample_rate.AlsaRate') as backend:
            with self.assertRaisesRegex(DeviceError,'in use'):rate.apply(d,96000,48000)
            backend.assert_not_called()

    def test_controller_match_rate_then_separate_setting_recall(self):
        d=DemoAF16Rig();saved=capture(d)
        next(e for e in saved['entries'] if e['bus']=='sample_rate')['values']['rate']=[96000]
        saved['entries'][0]['values']['level']=[-256]
        helper=windows.MixerPageTests();p=helper.page();p.rate_button=Mock();sets=[]
        p.refresh(saved);helper.drain(p,d,sets);self.assertTrue(p.rate_match_needed());self.assertFalse(p.changes)
        p.start_apply();self.assertTrue(p.app.worker.commands.empty())
        p.match_rate();helper.drain(p,d,sets)
        self.assertEqual(rate.read(d),96000);self.assertEqual(len(sets),1);self.assertEqual(sets[0]['bus'],'sample_rate')
        self.assertTrue(p.changes);self.assertEqual(getattr(d,'mix_levels',{}),{})
        p.start_apply();helper.drain(p,d,sets);self.assertEqual(scene.plan(saved,capture(d)),[])

    def test_legacy_v15_does_not_require_matching_rate(self):
        d=DemoAF16Rig();saved=capture(d);saved['format']=scene.FRONT_LINK_FORMAT
        saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
        d.clock_raw['internal_frequency']=3
        self.assertEqual(scene.plan(saved,capture(d)),[])

    def test_external_scene_does_not_request_internal_rate(self):
        d=DemoAF16Rig();d.clock_raw={**DEMO_RAW,'selected_source':1};saved=capture(d)
        self.assertIsNone(rate.saved_rate(saved))
        d.clock_raw['internal_frequency']=3
        self.assertEqual(scene.plan(saved,capture(d)),[])

    def test_stop_after_rate_apply_no_capture_or_setting_recall(self):
        d=DemoAF16Rig();saved=capture(d)
        next(e for e in saved['entries'] if e['bus']=='sample_rate')['values']['rate']=[96000]
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        p.refresh(saved);helper.drain(p,d,sets);p.match_rate();p.stop();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertFalse(p.busy);self.assertIsNone(p.scene)

    def test_bad_saved_rates_rejected(self):
        saved=capture(DemoAF16Rig())
        for value in (32000,True,'48000',48000.0):
            bad=copy.deepcopy(saved);bad['entries'][-1]['values']['rate']=[value]
            with self.assertRaises(ValueError):scene.validate(bad)
