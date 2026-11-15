import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from preamp_view import PreampControls
from mixer_view import Field,MasterController
from af16rig import DemoAF16Rig

class HoverButtonTests(unittest.TestCase):
    def controls(self,state):
        v=PreampControls.__new__(PreampControls)
        dash=SimpleNamespace(preamp_states={1:{'kind':'line','pair':[1,2],'forced_rear':0}},preamp_pending=set())
        v.app=SimpleNamespace(dashboard=dash,worker=SimpleNamespace(commands=queue.Queue()))
        v.c=SimpleNamespace(source=Field(1),state={'raw':{'show':3,'stereo':0}})
        v.link=Field();v.link.config(state=state)
        v.source_button=Field();v.source_button.config(state=state)
        v.source_target=True;v.refresh=Mock()
        return v
    def test_hover_link_dispatches_stereo_conversion(self):
        v=self.controls('active');v.toggle_link()
        self.assertEqual(v.app.worker.commands.get_nowait(),('stereo_pair',('main',1,'line',True,3,0)))
    def test_hover_source_dispatches_pair_change(self):
        v=self.controls('active');v.toggle_source()
        self.assertEqual(v.app.worker.commands.get_nowait(),('preamp_source',True))
    def test_disabled_buttons_still_do_nothing(self):
        v=self.controls('disabled');v.toggle_link();v.toggle_source()
        self.assertTrue(v.app.worker.commands.empty())
    def test_hover_does_not_bypass_pending_guard(self):
        for method in ('toggle_link','toggle_source'):
            v=self.controls('active');v.dashboard.preamp_pending.add(1)
            getattr(v,method)();self.assertTrue(v.app.worker.commands.empty())
    def test_link_hover_and_normal_have_same_action(self):
        results=[]
        for state in ('normal','active'):
            v=self.controls(state);v.toggle_link();results.append(v.app.worker.commands.get_nowait())
        self.assertEqual(*results)
    def test_aux_master_hover_is_enabled(self):
        q=queue.Queue();app=SimpleNamespace(connected=True,message=Field(),worker=SimpleNamespace(commands=q))
        c=MasterController(app);c.handle({'kind':'input_snapshot','state':DemoAF16Rig().mixer_masters_snapshot()})
        c.mute_buttons['aux1'].config(state='active');c.toggle_mute('aux1')
        self.assertEqual(q.get_nowait(),('aux_mute',('aux1',True)))

if __name__=='__main__':unittest.main()
