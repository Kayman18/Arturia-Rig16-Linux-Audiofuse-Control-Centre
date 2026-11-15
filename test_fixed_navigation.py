import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from navigation_bar import NavigationBar
from mixer_view import Console,Field

class FixedNavigationTests(unittest.TestCase):
    def test_add_packs_once_without_reparenting_or_reflow(self):
        bar=SimpleNamespace(items=[],reveal=Mock());button=Mock()
        NavigationBar.add(bar,button)
        button.pack.assert_called_once_with(side='left',padx=3)
        button.pack_forget.assert_not_called()
        self.assertEqual(bar.items,[button])
    def test_measure_only_sets_content_extent(self):
        bar=SimpleNamespace(content=Mock(),canvas=Mock())
        bar.content.winfo_reqwidth.return_value=1400;bar.content.winfo_reqheight.return_value=36
        bar.canvas.winfo_reqheight.return_value=36
        NavigationBar.measure(bar)
        bar.canvas.configure.assert_called_once_with(scrollregion=(0,0,1400,36))
    def test_keyboard_focus_scrolls_to_hidden_tab(self):
        bar=SimpleNamespace(content=Mock(),canvas=Mock());b=Mock()
        bar.content.winfo_reqwidth.return_value=1400;bar.canvas.winfo_width.return_value=1000
        bar.canvas.canvasx.return_value=0;b.winfo_x.return_value=1300;b.winfo_width.return_value=100
        NavigationBar.reveal(bar,b);bar.canvas.xview_moveto.assert_called_once_with(400/1400)
    def test_window_resize_does_not_resize_controls_or_canvas_content(self):
        canvas=Mock();canvas.winfo_width.return_value=1000;canvas.winfo_height.return_value=600
        strip=SimpleNamespace(frame=Field(),title=Field(),pan=Field(),dials={},preamp=SimpleNamespace(gains={}))
        v=SimpleNamespace(canvas=canvas,visible=[1],strips={1:strip},bank_id=1,
            master_view=SimpleNamespace(frame=Field(),minimum_width=170,dials={}))
        Console.resize(v);initial=v.bank_size
        canvas.itemconfigure.reset_mock();canvas.configure.reset_mock()
        canvas.winfo_width.return_value=2048;canvas.winfo_height.return_value=1200
        Console.resize(v)
        canvas.itemconfigure.assert_not_called();canvas.configure.assert_not_called()
        self.assertEqual(v.bank_size,initial);self.assertEqual(strip.frame.cget('width'),170)
        self.assertEqual(strip.pan.cget('height'),52)

if __name__=='__main__':unittest.main()
