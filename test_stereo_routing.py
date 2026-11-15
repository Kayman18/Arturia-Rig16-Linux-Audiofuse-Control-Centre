import unittest
from unittest.mock import Mock
from mixer_view import Field
from stereo_routing import source_pair,destination_pair,plan,reverse
import test_patchbay as fixtures


class StereoRoutingTests(unittest.TestCase):
    def panel(self):
        p=fixtures.PatchBayTests().panel();p.stereo_mode=Field(True);p.stereo_job=None;p.stereo_undo=None
        return p
    def test_pair_boundaries_and_right_jack_normalisation(self):
        for code,expected in ((64,(64,65)),(79,(78,79)),(80,(80,81)),(95,(94,95)),(128,(128,129)),(159,(158,159)),(193,(192,193))):
            self.assertEqual(source_pair(code),expected)
        for i in range(60):self.assertEqual(destination_pair(i),(i//2*2,i//2*2+1))
    def test_aux_and_unknown_codes_rejected(self):
        for code in (194,195,196,197,63,160,True):
            with self.assertRaises(ValueError):source_pair(code)
    def test_both_members_required_even_if_one_already_matches(self):
        with self.assertRaises(ValueError):plan(192,0,{0:192})
        with self.assertRaises(ValueError):plan(192,0,{0:192,1:999})
        self.assertEqual(len(plan(192,0,{0:192,1:64})),2)
    def test_reverse_plan_preserves_both_original_sources(self):
        forward=plan(128,1,{0:192,1:193})
        self.assertEqual(reverse(forward),[dict(destination=0,source_code=192,expected_source=128),dict(destination=1,source_code=193,expected_source=129)])
    def test_drop_preflights_both_before_any_write(self):
        p=self.panel();p.patch(129,1)
        cmd,data=p.app.worker.commands.get_nowait();self.assertEqual(cmd,'routing_preflight')
        self.assertEqual([r['source_code'] for r in data['changes']],[128,129]);self.assertTrue(p.app.worker.commands.empty())
    def test_pair_completion_then_single_undo_plan(self):
        p=self.panel();p.patch(128,0);p.app.worker.commands.get_nowait()
        p.handle(dict(kind='routing_ready',request_id=p.request_id))
        cmd,left=p.app.worker.commands.get_nowait();self.assertEqual(cmd,'routing_set');self.assertEqual(left['destination'],0)
        p.handle(dict(kind='routing_written',request_id=p.request_id,destination=0,previous=192,actual=128,undo=False))
        cmd,right=p.app.worker.commands.get_nowait();self.assertEqual(right['destination'],1)
        p.handle(dict(kind='routing_written',request_id=p.request_id,destination=1,previous=193,actual=129,undo=False))
        self.assertEqual(p.app.worker.commands.get_nowait()[0],'routing_capture')
        self.assertEqual(len(p.stereo_undo),2);self.assertIn('both L/R routes confirmed',p.notice)
        p.pending=False;p.editable=True;p.update_editor();p.undo_route()
        cmd,data=p.app.worker.commands.get_nowait();self.assertEqual(cmd,'routing_preflight')
        self.assertEqual([r['source_code'] for r in data['changes']],[192,193])
    def test_first_failure_stops_without_sending_second_member(self):
        p=self.panel();p.patch(128,0);p.app.worker.commands.get_nowait()
        p.handle(dict(kind='routing_ready',request_id=p.request_id));p.app.worker.commands.get_nowait()
        p.handle(dict(kind='routing_error',request_id=p.request_id,message='Rejected'))
        self.assertTrue(p.app.worker.commands.empty());self.assertFalse(p.editable)
        self.assertIsNone(p.stereo_undo);self.assertIn('0 routes confirmed',p.message.cget('text'))
    def test_second_failure_reports_partial_completion(self):
        p=self.panel();p.patch(128,0);p.app.worker.commands.get_nowait()
        p.handle(dict(kind='routing_ready',request_id=p.request_id));p.app.worker.commands.get_nowait()
        p.handle(dict(kind='routing_written',request_id=p.request_id,destination=0,previous=192,actual=128,undo=False));p.app.worker.commands.get_nowait()
        p.handle(dict(kind='routing_error',request_id=p.request_id,message='Timeout'))
        self.assertIn('1 routes confirmed',p.message.cget('text'));self.assertTrue(p.app.worker.commands.empty())
    def test_unchanged_pair_recolours_both_without_writes(self):
        p=self.panel();p.remember_color=Mock();p.patch(193,1)
        self.assertEqual(p.remember_color.call_count,2);self.assertTrue(p.app.worker.commands.empty())
    def test_aux_in_stereo_mode_does_not_write(self):
        p=self.panel();p.patch(194,0);self.assertTrue(p.app.worker.commands.empty())
        self.assertIn('Aux buses remain mono',p.message.cget('text'))
    def test_mono_mode_uses_one_existing_command(self):
        p=self.panel();p.stereo_mode.set(False);p.patch(129,1)
        cmd,data=p.app.worker.commands.get_nowait();self.assertEqual(cmd,'routing_set');self.assertEqual(data['source_code'],129)
    def test_new_file_batch_clears_previous_pair_undo(self):
        p=self.panel();p.stereo_undo=[dict(destination=0,source_code=192,expected_source=128)]
        p.start_batch([dict(destination=0,source_code=128,expected_source=192)],3)
        self.assertIsNone(p.stereo_undo)

    def test_unrelated_error_cannot_interrupt_pair(self):
        p=self.panel();p.patch(128,0);job=p.stereo_job
        p.handle(dict(kind='input_error',channel='masters',message='Unrelated'))
        self.assertIs(p.stereo_job,job);self.assertTrue(p.pending)
    def test_old_snapshot_cannot_clear_pair_undo(self):
        p=self.panel();p.request_id=100;p.stereo_undo=[dict(destination=0,source_code=192,expected_source=128)]
        p.handle(dict(kind='routing_snapshot',request_id=99,state={'connection_serial':2}))
        self.assertIsNotNone(p.stereo_undo)

if __name__=='__main__':unittest.main()
