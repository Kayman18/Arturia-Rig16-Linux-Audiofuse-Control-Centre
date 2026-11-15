import copy
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from af16rig import DemoAF16Rig
from routing_capture import read_routing
from routing_presets import make_preset,validate_preset,preview,preflight
from routing_window import RoutingWindow

class PresetTests(unittest.TestCase):
    def setUp(self):
        self.device=DemoAF16Rig();self.device.open()
        self.capture=read_routing(self.device);self.capture.update(demo=True,connection_serial=1)
        self.preset=make_preset(self.capture)
    def test_round_trip_all_known_routes(self):
        self.assertEqual(len(self.preset['routes']),60)
        self.assertEqual(preview(self.preset,self.capture),[])
    def test_preview_only_differences(self):
        self.preset['routes'][3]['source_code']=192
        self.assertEqual(preview(self.preset,self.capture),[dict(destination=3,source_code=192,expected_source=131)])
    def test_unknown_routes_omitted_on_save(self):
        self.capture['reads']['second']['values']['output_source[2]']=240
        preset=make_preset(self.capture)
        self.assertEqual(len(preset['routes']),59)
        self.assertNotIn(2,[r['destination'] for r in preset['routes']])
    def test_unknown_current_blocks_import(self):
        self.capture['reads']['second']['values']['output_source[2]']=240
        with self.assertRaises(ValueError):preview(self.preset,self.capture)
    def test_duplicate_destination_rejected(self):
        self.preset['routes'][1]=self.preset['routes'][0]
        with self.assertRaises(ValueError):validate_preset(self.preset)
    def test_invalid_schema_cases(self):
        for update in ({'format':'other'},{'state_version':19},{'demo':'false'},{'routes':[]},{'routes':[{'destination':True,'source_code':128}]},{'routes':[{'destination':60,'source_code':128}]},{'routes':[{'destination':0,'source_code':240}]}):
            p=copy.deepcopy(self.preset);p.update(update)
            with self.assertRaises(ValueError):validate_preset(p)
    def test_demo_hardware_mismatch(self):
        self.preset['demo']=False
        with self.assertRaises(ValueError):preview(self.preset,self.capture)
    def test_partial_capture_rejected(self):
        self.capture['status']='partial'
        with self.assertRaises(ValueError):make_preset(self.capture)
        with self.assertRaises(ValueError):preview(self.preset,self.capture)
    def test_preflight_all_routes_before_any_write(self):
        changes=[dict(destination=0,source_code=64,expected_source=128),dict(destination=1,source_code=65,expected_source=129)]
        device=SimpleNamespace(version=18,read=Mock(side_effect=[128,130]),write_output_route=Mock())
        with self.assertRaises(ValueError):preflight(device,changes)
        device.write_output_route.assert_not_called()
    def test_preflight_success_read_only(self):
        device=SimpleNamespace(version=18,read=Mock(return_value=128),write_output_route=Mock())
        preflight(device,[dict(destination=0,source_code=64,expected_source=128)])
        device.read.assert_called_once_with('output_source',0);device.write_output_route.assert_not_called()
    def test_preflight_validates_entire_plan_before_reading(self):
        device=SimpleNamespace(version=18,read=Mock())
        with self.assertRaises(ValueError):preflight(device,[dict(destination=0,source_code=64,expected_source=128),dict(destination=0,source_code=65,expected_source=128)])
        device.read.assert_not_called()

class BatchTests(unittest.TestCase):
    def window(self):
        w=RoutingWindow.__new__(RoutingWindow)
        w.app=SimpleNamespace(connected=True,worker=SimpleNamespace(commands=queue.Queue()),message=Mock())
        w.pending=False;w.editable=True;w.state={'connection_serial':1};w.batch=None;w.batch_done=0;w.notice=''
        w.update_editor=Mock();w.refresh_button=Mock();w.save_button=Mock();w.message=Mock();w.refresh=Mock()
        return w
    def changes(self):return [dict(destination=i,source_code=64+i,expected_source=128+i) for i in (0,1)]
    def test_start_only_sends_preflight(self):
        w=self.window();w.start_batch(self.changes(),1)
        cmd,data=w.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'routing_preflight');self.assertEqual(data['changes'],self.changes())
        self.assertTrue(w.app.worker.commands.empty())
    def test_sequential_confirmation_before_next_write(self):
        w=self.window();w.start_batch(self.changes(),1);w.app.worker.commands.get_nowait()
        w.handle(dict(kind='routing_ready',request_id=w.request_id))
        cmd,data=w.app.worker.commands.get_nowait();self.assertEqual(cmd,'routing_set');self.assertEqual(data['destination'],0)
        self.assertTrue(w.app.worker.commands.empty())
        w.handle(dict(kind='routing_written',request_id=w.request_id,destination=0,previous=128,actual=64,undo=False))
        cmd,data=w.app.worker.commands.get_nowait();self.assertEqual(data['destination'],1);self.assertEqual(w.batch_done,1)
        w.handle(dict(kind='routing_written',request_id=w.request_id,destination=1,previous=129,actual=65,undo=False))
        self.assertEqual(w.batch_done,2);self.assertIsNone(w.batch);w.refresh.assert_called_once()
    def test_failure_stops_remaining_changes(self):
        w=self.window();w.start_batch(self.changes(),1);w.app.worker.commands.get_nowait()
        w.handle(dict(kind='routing_ready',request_id=w.request_id));w.app.worker.commands.get_nowait()
        w.handle(dict(kind='routing_error',request_id=w.request_id,message='Readback failed'))
        self.assertIsNone(w.batch);self.assertFalse(w.editable);self.assertTrue(w.app.worker.commands.empty())
        self.assertIn('Remaining routes were not sent',w.notice)
    def test_stale_response_ignored(self):
        w=self.window();w.start_batch(self.changes(),1);w.app.worker.commands.get_nowait()
        w.handle(dict(kind='routing_ready',request_id=-1));self.assertTrue(w.app.worker.commands.empty())

if __name__=='__main__':unittest.main()
