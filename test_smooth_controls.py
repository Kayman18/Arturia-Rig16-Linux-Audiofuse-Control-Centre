import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import test_drag as gestures
from mixer_view import ValueControl

class SmoothControlsTests(unittest.TestCase):
    def control(self,kind):
        w=gestures.GestureTests().widget(kind)
        w.preview_drag=True;w.draw=Mock();w.readout=None
        w.cget=Mock(return_value='hand2');w.configure=Mock()
        return w
    def test_every_new_control_enables_preview(self):
        for kind in ('dial','fader'):
            with patch('mixer_view.tk.Canvas.__init__',return_value=None),patch.object(ValueControl,'bind'):
                w=ValueControl(Mock(),Mock(),kind=kind)
                self.assertTrue(w.preview_drag)
    def test_knobs_and_faders_follow_pointer_while_busy(self):
        for kind in ('dial','fader'):
            w=self.control(kind);w.ready=False
            w.drag(SimpleNamespace(y=150,state=0));first=w.visual_target
            w.drag(SimpleNamespace(y=100,state=0))
            self.assertGreater(w.visual_target,first)
            self.assertEqual(w.value,-30)
            self.assertEqual(w.draw.call_count,2)
            w.flush_target();w.target_callback.assert_not_called()
            w.ready=True;wanted=w.desired;w.flush_target()
            w.target_callback.assert_called_once_with(wanted)
    def test_older_readback_does_not_pull_handle_back(self):
        for kind in ('dial','fader'):
            w=self.control(kind);w.drag(SimpleNamespace(y=150,state=0));target=w.visual_target
            w.update_value(-29,False)
            self.assertEqual(w.visual_target,target)
            w.update_value(target,True)
            self.assertIsNone(w.visual_target)
    def test_invalid_readback_clears_preview_and_unsent_target(self):
        w=self.control('dial');w.drag(SimpleNamespace(y=150,state=0))
        w.update_value(None,False,valid=False)
        self.assertIsNone(w.visual_target);self.assertIsNone(w.desired)
        w.flush_target();w.target_callback.assert_not_called()
    def test_release_keeps_final_target_until_confirmed(self):
        w=self.control('fader');w.release(SimpleNamespace(y=100,state=0))
        self.assertEqual(w.visual_target,0);self.assertIsNone(w.drag_origin)
        w.flush_target();w.target_callback.assert_called_once_with(0)
        w.update_value(0,True);self.assertIsNone(w.visual_target)

if __name__=='__main__':unittest.main()
