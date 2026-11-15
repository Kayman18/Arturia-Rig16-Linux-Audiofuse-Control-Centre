import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig,DeviceError
from preamp import snapshot
from stereo_pair import convert
from preamp_view import PreampControls
from mixer_view import Console,Field

class PairTests(unittest.TestCase):
    def test_link_collapses_both_members_unlink_restores_mono(self):
        d=DemoAF16Rig();initial=d.mix_channel_snapshot('main',1)['raw']
        result=convert(d,'main',1,'rear',True,initial['show'],initial['stereo'])
        self.assertEqual(len(result[0]['stereo_members']),2)
        self.assertEqual(d.input_snapshot(1)['link'],1)
        raw=result[0]['raw'];self.assertEqual(raw['show']&3,0);self.assertEqual(raw['stereo']&1,1)
        result=convert(d,'main',2,'rear',False,raw['show'],raw['stereo'])
        self.assertFalse(result[0].get('stereo_members'));self.assertEqual(result[0]['raw']['show']&3,3)
    def test_matching_front_pair(self):
        d=DemoAF16Rig();d.force_rear=0
        raw=d.mix_channel_snapshot('main',1)['raw']
        result=convert(d,'main',1,'line',True,raw['show'],raw['stereo'])
        self.assertEqual(len(result[0]['stereo_members']),2);self.assertEqual(d.front_snapshot()['line'],1)
    def test_stale_masks_prevent_input_link(self):
        d=DemoAF16Rig()
        with self.assertRaises(DeviceError):convert(d,'main',1,'rear',True,0,0)
        self.assertEqual(d.input_snapshot(1)['link'],0)
    def test_half_selected_pair_rejected(self):
        d=DemoAF16Rig();d.main_show=1
        with self.assertRaises(DeviceError):convert(d,'main',1,'rear',True,1,0)
    def test_stop_after_failed_selection_reports_partial(self):
        d=DemoAF16Rig();raw=d.mix_channel_snapshot('main',1)['raw'];original=d.write_mixer_inclusion;calls=[]
        def fail(*args,**kw):
            calls.append(args)
            if len(calls)==2:raise DeviceError('Readback failed')
            return original(*args,**kw)
        d.write_mixer_inclusion=fail
        with self.assertRaisesRegex(DeviceError,'Some changes may have applied'):convert(d,'main',1,'rear',True,raw['show'],raw['stereo'])
        self.assertEqual(len(calls),2);self.assertEqual(d.main_stereo if hasattr(d,'main_stereo') else 0,0)
    def test_background_read_does_not_complete_pending_source_command(self):
        view=SimpleNamespace(preamp_pending={1},preamp_states={1:{'kind':'line'}},strips={})
        Console.handle(view,dict(kind='preamp_state',source=1,states=[{'source':1,'kind':'rear'}]))
        self.assertEqual(view.preamp_pending,{1});self.assertEqual(view.preamp_states[1]['kind'],'line')
    def test_both_source_buttons_dispatch_identical_pair_command(self):
        for source in (1,2):
            q=queue.Queue();dash=SimpleNamespace(preamp_pending=set(),preamp_states={1:{'forced_rear':0}})
            view=PreampControls.__new__(PreampControls);view.app=SimpleNamespace(dashboard=dash,worker=SimpleNamespace(commands=q))
            view.c=SimpleNamespace(source=Field(source));view.source_button=Mock();view.source_button.cget.return_value='normal';view.source_target=True;view.refresh=Mock()
            view.toggle_source();view.toggle_source()
            self.assertEqual(q.get_nowait(),('preamp_source',True));self.assertTrue(q.empty())
    def test_levels_and_other_pairs_untouched(self):
        d=DemoAF16Rig();d.set_console_value('main',1,'level',-18*256)
        raw=d.mix_channel_snapshot('main',1)['raw']
        out=convert(d,'main',1,'rear',True,raw['show'],raw['stereo'])
        self.assertEqual(out[0]['stereo_members'][0]['level_db'],-18)
        self.assertEqual(out[0]['raw']['show']&~3,raw['show']&~3)

if __name__=='__main__':unittest.main()
