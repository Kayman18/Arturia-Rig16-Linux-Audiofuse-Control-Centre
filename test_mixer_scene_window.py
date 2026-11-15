import copy,unittest
from af16rig import DemoAF16Rig,DeviceError
import test_fader_scene_window as old
from test_mixer_scene import capture
from mixer_scene_window import MixerSceneWindow
import mixer_scene as m

class MixerPageTests(unittest.TestCase):
    def page(self):
        p=MixerSceneWindow.__new__(MixerSceneWindow);p.__dict__.update(old.ScenePageTests().page().__dict__);return p
    def drain(self,p,d,sets):
        for _ in range(2000):
            if p.app.worker.commands.empty():
                if p.timer is None:return
                p.queue_next();continue
            cmd,data=p.app.worker.commands.get_nowait();self.assertEqual(data['scope'],'mixer')
            event=dict(request_id=data['request_id'],connection_serial=1)
            try:
                if cmd=='scene_set':sets.append(data['change']);event.update(kind='scene_written',record=m.apply_entry(d,data['layout'],data['change']))
                elif data['part'].startswith('layout'):event.update(kind='scene_snapshot',part=data['part'],layout=m.topology(d))
                else:event.update(kind='scene_snapshot',part='entry',record=m.read_entry(d,data['layout'],data['address']))
            except (DeviceError,ValueError) as error:event.update(kind='scene_error',message=str(error))
            p.handle(event)
        self.fail('Capture did not complete')
    def target(self,d):
        target=capture(d);target['entries'][0]['values'].update(level=[-256],pan=[25],mute=[1],solo=[1],send1_level=[-512],send1_mute=[1]);return target
    def test_preview_preflight_restore_all_control_types(self):
        p=self.page();d=DemoAF16Rig();target=self.target(d);sets=[]
        p.refresh(target);self.drain(p,d,sets);self.assertEqual(len(p.changes),6);self.assertFalse(sets)
        p.start_apply();self.drain(p,d,sets);self.assertEqual(len(sets),6);self.assertFalse(p.busy)
        self.assertEqual(m.plan(target,capture(d)),[])
    def test_change_after_preview_rejects_whole_recall(self):
        p=self.page();d=DemoAF16Rig();sets=[];p.refresh(self.target(d));self.drain(p,d,sets)
        d.pan_positions={('cue',16):20};p.start_apply();self.drain(p,d,sets)
        self.assertFalse(sets);self.assertFalse(p.busy);self.assertIn('changed after preview',p.message.config.call_args.kwargs['text'])
    def test_stop_capture_and_reconnect(self):
        p=self.page();d=DemoAF16Rig();sets=[];p.refresh();p.stop();self.drain(p,d,sets)
        self.assertIsNone(p.scene);self.assertFalse(sets)
        p=self.page();p.refresh();p.app.name_cache.serial=2;self.drain(p,d,sets)
        self.assertIsNone(p.scene);self.assertFalse(sets)
    def test_scene_rows_have_unique_field_keys_and_units(self):
        rows=MixerSceneWindow.flatten(capture(DemoAF16Rig()))
        self.assertEqual(len(rows),len({MixerSceneWindow.key(r) for r in rows}))
        self.assertEqual(MixerSceneWindow.db(dict(field='pan',values=[0,127,254])),'L 127 / Centre / R 127')
        self.assertEqual(MixerSceneWindow.db(dict(field='mute',values=[1,0])),'On / Off')

if __name__=='__main__':unittest.main()
