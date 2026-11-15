import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from mixer_layout import expanded_geometry
from mixer_view import Console,Field

class ExpandedStripTests(unittest.TestCase):
    def test_twelve_strips_fill_available_width_and_height(self):
        for width in (2006,2048,2160,2560):
            for height in (850,920,1000):
                widths,total,h,dial=expanded_geometry(width,height,11)
                self.assertEqual(total,width)
                self.assertEqual(sum(widths)+3*11+5,width)
                self.assertLessEqual(max(widths)-min(widths),1)
                self.assertEqual((h,dial),(height,52))
    def test_main_bank_fits_all_columns_without_paging(self):
        for width in (1280,1440,1600,1920,2048,2560):
            for count in (11,20):
                widths,total,h,dial=expanded_geometry(width,930,count,fit=True)
                self.assertEqual(sum(widths)+3*count+5,width)
                self.assertEqual(total,width)
                self.assertEqual(dial,52)
                self.assertLessEqual(max(widths)-min(widths),1)
    def test_small_window_does_not_shrink_controls(self):
        widths,total,height,dial=expanded_geometry(1000,500,11)
        self.assertEqual(widths,[164]*12)
        self.assertEqual((total,height,dial),(2006,850,52))
    def test_resize_applies_spare_space_and_does_not_touch_header_sizes(self):
        strips={i:SimpleNamespace(frame=Field(),title=Field(),pan=Field(),dials={},preamp=SimpleNamespace(gains={})) for i in range(9)}
        outputs=[SimpleNamespace(frame=Field(),header=Mock()),SimpleNamespace(frame=Field(),header=Mock())]
        canvas=Mock();canvas.winfo_width.return_value=2048;canvas.winfo_height.return_value=930
        v=SimpleNamespace(canvas=canvas,visible=list(strips),strips=strips,bank_id=1,output_strips=outputs,page_slots=9,
            master_view=SimpleNamespace(frame=Field(),minimum_width=164,dials={}))
        with patch('mixer_view.align_gain_rows'):
            Console.resize(v)
            actual=[s.frame.cget('width') for s in strips.values()]+[o.frame.cget('width') for o in outputs]+[v.master_view.frame.cget('width')]
            self.assertEqual(sum(actual)+38,2048)
            self.assertEqual(v.bank_size,(2048,930))
            self.assertTrue(all(s.pan.cget('height')==52 for s in strips.values()))
            for o in outputs:o.header.configure.assert_not_called()
            canvas.itemconfigure.reset_mock();Console.resize(v)
            canvas.itemconfigure.assert_not_called()
            canvas.winfo_height.return_value=970;Console.resize(v)
            canvas.itemconfigure.assert_called_once_with(1,width=2048,height=970)

if __name__=='__main__':unittest.main()
