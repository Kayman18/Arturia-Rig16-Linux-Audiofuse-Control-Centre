import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from window_state import bounded_size,restore,save
from mixer_view import Console
from mixer_layout import fixed_geometry

class WindowTests(unittest.TestCase):
    def test_bounds_on_smaller_display(self):
        self.assertEqual(bounded_size(1920,1080,1366,768),(1342,688))
    def test_remember_custom_size_and_maximized(self):
        with tempfile.TemporaryDirectory() as tmp,patch('window_state.config_path',return_value=Path(tmp)/'window.json'):
            root=Mock();root.winfo_width.return_value=1500;root.winfo_height.return_value=900;root.attributes.return_value=False
            save(root);root.winfo_screenwidth.return_value=1920;root.winfo_screenheight.return_value=1080
            restore(root);root.geometry.assert_called_with('1500x900+0+0');root.after_idle.assert_not_called()
    def test_first_open_uses_screen_and_maximizes(self):
        with tempfile.TemporaryDirectory() as tmp,patch('window_state.config_path',return_value=Path(tmp)/'window.json'):
            root=Mock();root.winfo_screenwidth.return_value=1920;root.winfo_screenheight.return_value=1080
            restore(root);root.geometry.assert_called_with('1896x1000+0+0')
            root.after_idle.call_args.args[0]();root.attributes.assert_called_with('-zoomed',True)
    def test_corrupt_config_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'window.json';p.write_text('{invalid')
            with patch('window_state.config_path',return_value=p):
                root=Mock();root.winfo_screenwidth.return_value=1366;root.winfo_screenheight.return_value=768
                restore(root);root.geometry.assert_called_with('1342x688+0+0')
    def test_mixer_height_and_width_are_fixed(self):
        canvas=Mock();canvas.winfo_width.return_value=1200;canvas.winfo_height.return_value=680
        view=SimpleNamespace(canvas=canvas,visible=list(range(12)),bank_id=1,strips={},master_view=SimpleNamespace(dials={}))
        Console.resize(view)
        canvas.itemconfigure.assert_called_with(1,width=fixed_geometry(12)[1],height=850)
    def test_full_16_strips_have_scrollable_extent(self):
        canvas=Mock();canvas.winfo_width.return_value=1650;canvas.winfo_height.return_value=800
        view=SimpleNamespace(canvas=canvas,visible=list(range(16)),bank_id=1,strips={},master_view=SimpleNamespace(dials={}))
        Console.resize(view)
        canvas.configure.assert_called_with(scrollregion=(0,0,fixed_geometry(16)[1],850))

if __name__=='__main__':unittest.main()
