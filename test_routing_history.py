import unittest
from copy import deepcopy
from unittest.mock import Mock
from mixer_view import Field
from routing_history import RoutingHistory
import test_patchbay as fixtures
from stereo_routing import plan


def change(d=0,old=192,new=128):return dict(destination=d,expected_source=old,source_code=new)

class HistoryModelTests(unittest.TestCase):
    def test_multiple_steps_undo_redo_order(self):
        h=RoutingHistory();h.record([change()],'First');h.record([change(1,193,129)],'Second')
        self.assertEqual(h.prepare('undo'),[change(1,129,193)]);h.complete('undo')
        self.assertEqual(h.prepare('undo'),[change(0,128,192)]);h.complete('undo')
        self.assertEqual(h.prepare('redo'),[change()]);h.complete('redo')
        self.assertEqual(h.prepare('redo'),[change(1,193,129)]);h.complete('redo')
        self.assertEqual(len(h.undo),2);self.assertFalse(h.redo)
    def test_prepare_does_not_move_history(self):
        h=RoutingHistory();h.record([change()],'Patch');h.prepare('undo')
        self.assertEqual(len(h.undo),1);self.assertFalse(h.redo)
    def test_new_confirmed_edit_discards_redo(self):
        h=RoutingHistory();h.record([change()],'Patch');h.complete('undo');h.record([change(2,64,65)],'New')
        self.assertFalse(h.redo);self.assertEqual(len(h.undo),1)
    def test_noop_does_not_remove_redo(self):
        h=RoutingHistory();h.record([change()],'Patch');h.complete('undo');h.record([change(2,64,64)],'Same')
        self.assertEqual(len(h.redo),1);self.assertFalse(h.undo)
    def test_bound_discards_oldest_whole_operation(self):
        h=RoutingHistory(limit=2)
        for i in range(3):h.record([change(i,64,128)],str(i))
        self.assertEqual([r['label'] for r in h.undo],['1','2'])
    def test_connection_change_clears_both_stacks(self):
        h=RoutingHistory();h.bind(3);h.record([change()],'Patch');h.complete('undo');h.bind(3)
        self.assertEqual(len(h.redo),1);h.bind(4);self.assertFalse(h.redo);self.assertFalse(h.undo)
    def test_pair_and_preset_changes_preserve_all_preconditions(self):
        h=RoutingHistory();h.record([change(0,192,192),change(1,193,129)],'Stereo')
        self.assertEqual(h.prepare('undo'),[change(0,192,192),change(1,129,193)])
    def test_invalid_unknown_duplicate_and_boolean_addresses_rejected(self):
        for changes in ([],[change(60)],[change(new=999)],[change(d=True)],[change(),change()]):
            with self.assertRaises(ValueError):RoutingHistory().record(changes,'Bad')
    def test_entry_and_returned_plan_are_independent_copies(self):
        h=RoutingHistory();data=[change()];h.record(data,'Patch');data[0]['source_code']=64
        result=h.prepare('undo');result[0]['source_code']=65
        self.assertEqual(h.prepare('undo'),[change(0,128,192)])

class HistoryPanelTests(unittest.TestCase):
    def panel(self):
        p=fixtures.PatchBayTests().panel();p.history=RoutingHistory();p.history_job=None;p.history_done=None
        p.stereo_job=None;p.stereo_undo=None;p.stereo_mode=Field(False);p.redo_button=Field();p.window=Mock()
        return p
    def command(self,p):return p.app.worker.commands.get_nowait()
    def confirm(self,p,data):
        p.handle(dict(kind='routing_written',request_id=data['request_id'],destination=data['destination'],previous=data['expected_source'],actual=data['source_code'],undo=data.get('undo',False)))
    def ready_after_capture(self,p):
        self.assertEqual(self.command(p)[0],'routing_capture')
        p.pending=False;p.editable=True;p.update_editor()
    def patch(self,p,source,dest):
        p.patch(source,dest);cmd,data=self.command(p);self.assertEqual(cmd,'routing_set');self.confirm(p,data)
        p.state['reads']['second']['values'][f'output_source[{dest}]']=source
        self.ready_after_capture(p)
    def run_batch(self,p):
        cmd,data=self.command(p);self.assertEqual(cmd,'routing_preflight')
        p.handle(dict(kind='routing_ready',request_id=data['request_id']))
        for expected in data['changes']:
            cmd,write=self.command(p);self.assertEqual(cmd,'routing_set')
            self.assertEqual(write['source_code'],expected['source_code']);self.confirm(p,write)
            p.state['reads']['second']['values'][f"output_source[{write['destination']}]"]=write['source_code']
        self.ready_after_capture(p)
        return data
    def test_two_mono_edits_can_undo_twice_and_redo_twice(self):
        p=self.panel();self.patch(p,128,0);self.patch(p,129,1)
        self.assertEqual(p.undo_button.cget('text'),'Undo (2)')
        for expected in (193,192):
            p.undo_route();data=self.run_batch(p);self.assertEqual(data['changes'][0]['source_code'],expected)
        self.assertFalse(p.history.undo);self.assertEqual(len(p.history.redo),2)
        for expected in (128,129):
            p.redo_route();data=self.run_batch(p);self.assertEqual(data['changes'][0]['source_code'],expected)
        self.assertEqual(len(p.history.undo),2);self.assertFalse(p.history.redo)
    def test_stereo_group_remains_one_step(self):
        p=self.panel();p.stereo_mode.set(True);p.patch(128,0);self.run_batch(p)
        self.assertEqual(len(p.history.undo),1);self.assertEqual(len(p.history.undo[0]['changes']),2)
        p.undo_route();data=self.run_batch(p);self.assertEqual([c['source_code'] for c in data['changes']],[192,193])
        p.redo_route();data=self.run_batch(p);self.assertEqual([c['source_code'] for c in data['changes']],[128,129])
    def test_preset_is_one_undo_step(self):
        p=self.panel();changes=[change(),change(1,193,129),change(2,64,80)]
        p.start_batch(changes,3);self.run_batch(p)
        self.assertEqual(len(p.history.undo),1);self.assertEqual(p.history.undo[0]['label'],'Routing preset')
        p.undo_route();data=self.run_batch(p);self.assertEqual([c['source_code'] for c in data['changes']],[192,193,64])
    def test_stack_waits_for_all_group_members(self):
        p=self.panel();p.stereo_mode.set(True);p.patch(128,0);_,data=self.command(p)
        p.handle(dict(kind='routing_ready',request_id=data['request_id']));_,write=self.command(p);self.confirm(p,write)
        self.assertFalse(p.history.undo);self.assertEqual(len(p.history_job['confirmed']),1)
    def test_partial_failure_clears_history_and_stops(self):
        p=self.panel();self.patch(p,80,2);p.stereo_mode.set(True);p.patch(128,0);_,data=self.command(p)
        p.handle(dict(kind='routing_ready',request_id=data['request_id']));_,write=self.command(p);self.confirm(p,write)
        _,write=self.command(p);p.handle(dict(kind='routing_error',request_id=write['request_id'],message='Uncertain write'))
        self.assertFalse(p.history.undo);self.assertFalse(p.history.redo);self.assertIsNone(p.history_job)
        self.assertTrue(p.app.worker.commands.empty());self.assertIn('1 routes confirmed',p.message.cget('text'))
    def test_undo_preflight_failure_sends_no_route_write(self):
        p=self.panel();self.patch(p,128,0);p.undo_route();_,data=self.command(p)
        p.handle(dict(kind='routing_error',request_id=data['request_id'],message='Route changed externally'))
        self.assertTrue(p.app.worker.commands.empty());self.assertFalse(p.history.undo);self.assertFalse(p.editable)
    def test_unrelated_or_old_error_keeps_history(self):
        p=self.panel();self.patch(p,128,0)
        p.handle(dict(kind='input_error',channel='masters',message='Other'))
        p.handle(dict(kind='routing_error',request_id=-1,message='Old'))
        self.assertEqual(len(p.history.undo),1)
    def test_busy_replay_cannot_queue_duplicate(self):
        p=self.panel();self.patch(p,128,0);p.undo_route();p.undo_route();p.redo_route()
        self.assertEqual(p.app.worker.commands.qsize(),1)
    def test_recolour_is_not_hardware_history(self):
        p=self.panel();self.patch(p,128,0);p.undo_route();self.run_batch(p)
        p.patch(192,0);self.assertEqual(len(p.history.redo),1);self.assertTrue(p.app.worker.commands.empty())
    def test_new_edit_after_undo_discards_redo(self):
        p=self.panel();self.patch(p,128,0);p.undo_route();self.run_batch(p);self.patch(p,80,0)
        self.assertFalse(p.history.redo);self.assertEqual(len(p.history.undo),1)
    def test_unexpected_confirmation_not_added_to_history(self):
        p=self.panel();p.patch(128,0);_,data=self.command(p)
        p.confirm_history(dict(destination=0,previous=192,actual=129))
        self.assertFalse(p.history.undo);self.assertIsNone(p.history_job)
    def test_disconnect_clears_history_and_disables_replay(self):
        p=self.panel();self.patch(p,128,0);p.handle(dict(kind='input_error',channel='routing',message='Disconnected'))
        self.assertFalse(p.history.undo);self.assertEqual(p.undo_button.cget('state'),'disabled');self.assertEqual(p.redo_button.cget('state'),'disabled')
