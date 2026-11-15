import math
import unittest
from unittest.mock import Mock,patch
from mixer_view import ValueControl
from value_entry import numeric_target,entry_description

class ValueEntryTests(unittest.TestCase):
    def control(self):
        c=ValueControl.__new__(ValueControl)
        c.ready=True;c.valid=True;c.value=-12;c.low=-60;c.high=6;c.quantum=.25
        c.edit_generation=0;c.flush_id=None;c.target_callback=Mock(return_value=True)
        c.winfo_toplevel=Mock();c.winfo_exists=Mock(return_value=True);c.after_cancel=Mock()
        return c
    def test_gain_quantization(self):
        self.assertEqual(numeric_target(-12.13,-60,6),-12.25)
        self.assertEqual(numeric_target(7.7,0,12,1),8)
    def test_pan_percent_maps_native_bounds_and_centre(self):
        self.assertEqual([numeric_target(v,0,254) for v in (-100,0,100)],[0,127,254])
    def test_nonfinite_and_invalid_values_rejected(self):
        for v in (math.nan,math.inf,-math.inf,True,'1'):
            with self.assertRaises(ValueError):numeric_target(v,-60,6)
    def test_out_of_range_not_silently_clamped(self):
        for v in (-61,7):
            with self.assertRaises(ValueError):numeric_target(v,-60,6)
    def test_enter_submits_one_target_via_existing_callback(self):
        c=self.control()
        with patch('mixer_view.simpledialog.askfloat',return_value=-8.13):self.assertEqual(c.edit_value(),'break')
        c.target_callback.assert_called_once_with(-8.25)
        self.assertEqual(c.value,-12)  # still device readback, never optimistic state
    def test_cancel_does_not_write(self):
        c=self.control()
        with patch('mixer_view.simpledialog.askfloat',return_value=None):c.edit_value()
        c.target_callback.assert_not_called()
    def test_identical_target_does_not_write(self):
        c=self.control()
        with patch('mixer_view.simpledialog.askfloat',return_value=-12):c.edit_value()
        c.target_callback.assert_not_called()
    def test_disabled_control_never_opens_dialog(self):
        for attribute,value in (('ready',False),('valid',False),('value',None),('target_callback',None)):
            c=self.control();setattr(c,attribute,value)
            with patch('mixer_view.simpledialog.askfloat') as ask:c.edit_value();ask.assert_not_called()
    def test_disconnect_and_reconnect_during_dialog_invalidates_entry(self):
        c=self.control()
        def dialog(*a,**kw):c.cancel_drag();c.ready=True;c.valid=True;return -5
        with patch('mixer_view.simpledialog.askfloat',side_effect=dialog):c.edit_value()
        c.target_callback.assert_not_called()
    def test_changed_gain_range_invalidates_entry(self):
        c=self.control()
        def dialog(*a,**kw):c.high=12;return -5
        with patch('mixer_view.simpledialog.askfloat',side_effect=dialog):c.edit_value()
        c.target_callback.assert_not_called()
    def test_busy_or_destroyed_control_ignores_completed_dialog(self):
        for mode in ('busy','destroyed'):
            c=self.control()
            def dialog(*a,**kw):
                if mode=='busy':c.ready=False
                else:c.winfo_exists.return_value=False
                return -5
            with patch('mixer_view.simpledialog.askfloat',side_effect=dialog):c.edit_value()
            c.target_callback.assert_not_called()
    def test_nonfinite_dialog_value_shows_error_without_write(self):
        c=self.control()
        with patch('mixer_view.simpledialog.askfloat',return_value=math.nan),patch('mixer_view.messagebox.showerror') as error:
            c.edit_value();error.assert_called_once()
        c.target_callback.assert_not_called()
    def test_pending_drag_timer_is_canceled_before_entry(self):
        c=self.control();c.flush_id='drag';c.desired=-2
        with patch('mixer_view.simpledialog.askfloat',return_value=-8):c.edit_value()
        c.after_cancel.assert_called_once_with('drag');self.assertIsNone(c.desired)
        c.target_callback.assert_called_once_with(-8)
    def test_pan_dialog_explains_left_right_and_uses_percent(self):
        title,prompt,value,low,high=entry_description(127,0,254,.25)
        self.assertEqual((title,value,low,high),('Set pan',0,-100,100));self.assertIn('left',prompt)
    def test_rejected_target_not_queued_or_repeated(self):
        c=self.control();c.target_callback.return_value=False
        with patch('mixer_view.simpledialog.askfloat',return_value=-8):c.edit_value()
        c.target_callback.assert_called_once();self.assertIsNone(c.flush_id)

if __name__=='__main__':unittest.main()
