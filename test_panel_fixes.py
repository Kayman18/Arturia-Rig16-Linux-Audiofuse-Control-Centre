import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from af16rig_gui import InputWindow
from mixer_view import Field,Console
from mixer_layout import fixed_geometry

class PanelFixTests(unittest.TestCase):
    def panel(self):
        p=InputWindow.__new__(InputWindow);p.channel=Field(1);p.state={'link':0,'control_available':{'link':True}}
        p.controls={'link':(Field(),Field())};p.pending=True;p.loading=False;p.message=Field();p.refresh=Mock()
        p.app=SimpleNamespace(root=Mock());p.last_error=None
        return p
    def test_link_error_survives_repeated_live_polls(self):
        p=self.panel();error='Firmware rejected link: front/rear source mismatch'
        p.handle({'kind':'input_error','channel':1,'name':'link','message':error})
        for _ in range(20):p.handle({'kind':'input_snapshot','state':{'channel':1,'link':0,'errors':{}}})
        self.assertEqual(p.message.cget('text'),error);self.assertEqual(p.message.cget('fg'),'#efba76')
        self.assertFalse(p.pending)
    def test_copy_error_preserves_exact_details(self):
        p=self.panel();p.last_error='Pair 1/2\nUSB timeout (-7)'
        p.copy_error();p.app.root.clipboard_append.assert_called_once_with(p.last_error)
    def test_dismiss_allows_live_status_again(self):
        p=self.panel();p.last_error='Failed';p.dismiss_error()
        p.handle({'kind':'input_snapshot','state':{'channel':1,'errors':{}}})
        self.assertIsNone(p.last_error);self.assertEqual(p.message.cget('text'),'Live readback')
    def test_narrow_viewport_uses_fixed_scroll_extent(self):
        canvas=Mock();canvas.winfo_width.return_value=1000;canvas.winfo_height.return_value=560
        view=SimpleNamespace(canvas=canvas,visible=list(range(16)),bank_id=1,strips={},master_view=SimpleNamespace(dials={}))
        Console.resize(view)
        canvas.itemconfigure.assert_called_with(1,width=fixed_geometry(16)[1],height=850)
        canvas.configure.assert_called_with(scrollregion=(0,0,fixed_geometry(16)[1],850))
    def test_unlink_recalculates_width_with_unchanged_viewport(self):
        canvas=Mock();canvas.winfo_width.return_value=1200;canvas.winfo_height.return_value=700
        view=SimpleNamespace(canvas=canvas,visible=list(range(16)),bank_id=1,bank_size=(1200,700),bank_visible_count=8,strips={},master_view=SimpleNamespace(dials={}))
        Console.resize(view)
        self.assertEqual(view.bank_visible_count,16);canvas.itemconfigure.assert_called_once()

if __name__=='__main__':unittest.main()
