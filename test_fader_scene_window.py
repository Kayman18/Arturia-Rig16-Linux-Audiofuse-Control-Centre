import copy
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig,DeviceError
from fader_scene import topology,read_entry,apply_entry
from fader_scene_window import FaderSceneWindow
from test_fader_scene import capture

class ScenePageTests(unittest.TestCase):
    def page(self):
        p=object.__new__(FaderSceneWindow)
        p.app=SimpleNamespace(connected=True,demo=True,name_cache=SimpleNamespace(serial=1),worker=SimpleNamespace(commands=queue.Queue()))
        p.closed=False;p.busy=False;p.request=None;p.timer=None;p.serial=None;p.scene=None
        p.target=None;p.changes=[];p.preview_current=None;p.mode='capture';p.stopped=False
        p.window=Mock();p.table=Mock();p.table.get_children.return_value=[];p.message=Mock()
        for name in ('read_button','save_button','load_button','apply_button','stop_button'):setattr(p,name,Mock())
        return p
    def drain(self,p,d,sets=None):
        steps=0
        while not p.app.worker.commands.empty() or p.timer is not None:
            steps+=1;self.assertLess(steps,1000)
            if p.app.worker.commands.empty():p.queue_next();continue
            cmd,data=p.app.worker.commands.get_nowait()
            event=dict(request_id=data['request_id'],connection_serial=data['connection_serial'])
            try:
                if cmd=='scene_set':
                    if sets is not None:sets.append(copy.deepcopy(data))
                    event.update(kind='scene_written',record=apply_entry(d,data['layout'],data['change']))
                elif data['part'].startswith('layout'):event.update(kind='scene_snapshot',part=data['part'],layout=topology(d))
                else:event.update(kind='scene_snapshot',part='entry',record=read_entry(d,data['layout'],data['address']))
            except (DeviceError,ValueError) as error:event.update(kind='scene_error',message=str(error))
            p.handle(event)
    def target(self,d):
        scene=capture(d);scene['entries'][0]['levels']=[-256];scene['entries'][1]['levels']=[-512];return scene
    def test_capture_preview_full_preflight_apply_reread(self):
        p=self.page();d=DemoAF16Rig();sets=[]
        p.refresh(self.target(d));self.drain(p,d,sets)
        self.assertEqual(len(p.changes),2);self.assertFalse(sets)
        p.start_apply();self.drain(p,d,sets)
        self.assertEqual(len(sets),2);self.assertFalse(p.busy);self.assertIsNone(p.preview_current)
        self.assertEqual(d.mix_levels,{('main',1):-256,('main',2):-512})
        p.refresh();self.drain(p,d);self.assertEqual(p.scene['entries'][0]['levels'],[-256])
    def test_preview_current_changed_blocks_all_writes(self):
        p=self.page();d=DemoAF16Rig();p.refresh(self.target(d));self.drain(p,d)
        d.mix_levels={('cue',16):-256};p.start_apply();sets=[];self.drain(p,d,sets)
        self.assertFalse(sets);self.assertFalse(p.busy);self.assertIsNone(p.preview_current)
        self.assertIn('changed after preview',p.message.config.call_args.kwargs['text'])
    def test_stop_during_capture_no_writes(self):
        p=self.page();d=DemoAF16Rig();p.refresh();p.stop();sets=[];self.drain(p,d,sets)
        self.assertFalse(sets);self.assertIsNone(p.scene);self.assertFalse(p.busy)
    def test_stop_between_writes_keeps_first_only(self):
        p=self.page();d=DemoAF16Rig();p.refresh(self.target(d));self.drain(p,d);p.start_apply()
        # Process preflight requests until the first write is queued.
        while True:
            cmd,data=p.app.worker.commands.get_nowait()
            if cmd=='scene_set':break
            result=dict(kind='scene_snapshot',part=data['part'],request_id=data['request_id'],connection_serial=1)
            result.update(layout=topology(d)) if data['part'].startswith('layout') else result.update(record=read_entry(d,data['layout'],data['address']))
            p.handle(result)
        p.stop()
        p.handle(dict(kind='scene_written',request_id=data['request_id'],connection_serial=1,record=apply_entry(d,data['layout'],data['change'])))
        p.queue_next();self.assertEqual(d.mix_levels,{('main',1):-256});self.assertTrue(p.app.worker.commands.empty())
    def test_connection_change_discards_preview_and_old_event(self):
        p=self.page();d=DemoAF16Rig();p.refresh();request=p.request
        p.app.name_cache.serial=2;p.connection_changed()
        p.handle(dict(kind='scene_snapshot',part='layout',layout=topology(d),request_id=request,connection_serial=1))
        self.assertIsNone(p.scene);self.assertFalse(p.busy)
    def test_failed_write_stops_batch_no_retry(self):
        p=self.page();d=DemoAF16Rig();p.refresh(self.target(d));self.drain(p,d)
        with patch('test_fader_scene_window.apply_entry',side_effect=DeviceError('failed')):
            p.start_apply();sets=[];self.drain(p,d,sets)
        self.assertEqual(len(sets),1);self.assertFalse(p.busy);self.assertIsNone(p.scene)
    def test_cancel_open_no_reads_or_writes(self):
        p=self.page();p.serial=1
        with patch('fader_scene_window.filedialog.askopenfilename',return_value=''):p.open_scene()
        self.assertTrue(p.app.worker.commands.empty())
    def test_stale_connection_no_apply(self):
        p=self.page();d=DemoAF16Rig();p.refresh(self.target(d));self.drain(p,d)
        p.app.name_cache.serial=2;p.start_apply();self.assertTrue(p.app.worker.commands.empty())
    def test_close_cancels_timer_and_ignores_result(self):
        p=self.page();p.serial=1;p.timer=4;p.request='old';p.close()
        p.window.after_cancel.assert_called_once_with(4)
        p.handle(dict(kind='scene_error',request_id='old',connection_serial=1,message='error'))
        self.assertTrue(p.closed)
    def test_identical_scene_no_apply(self):
        p=self.page();d=DemoAF16Rig();p.refresh(capture(d));self.drain(p,d)
        self.assertEqual(p.changes,[]);p.start_apply();self.assertTrue(p.app.worker.commands.empty())
