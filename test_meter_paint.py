import unittest
from unittest.mock import Mock
from meter_view import Meter
from meters import Ballistics

class MeterPaintTests(unittest.TestCase):
    def meter(self,caption='IN',width=26,height=120):
        m=Meter.__new__(Meter);m.caption=caption;m.model=Ballistics()
        m.signature=object();m.items=[];m.size=None;m.paint_cache={}
        m.winfo_width=lambda:width;m.winfo_height=lambda:height
        ids=iter(range(100))
        for name in ('create_rectangle','create_line','create_text'):setattr(m,name,Mock(side_effect=lambda *a,**k:next(ids)))
        m.delete=Mock();m.coords=Mock();m.itemconfigure=Mock()
        return m
    def test_stereo_labels_never_repaint_during_levels_or_stale_transition(self):
        m=self.meter();m.feed([.1,.2],1);m.draw(1)
        m.itemconfigure.reset_mock();m.delete.reset_mock()
        for t in (1.05,1.1,1.2,2):m.draw(t)
        self.assertFalse(any(c.args[0]==m.label for c in m.itemconfigure.call_args_list))
        m.delete.assert_not_called()
        self.assertEqual(m.create_text.call_args.kwargs['text'],'L R')
    def test_unchanged_pixels_and_colours_do_not_repaint(self):
        m=self.meter();m.feed([.1],1);m.draw(1)
        m.coords.reset_mock();m.itemconfigure.reset_mock()
        m.draw(1.00001)
        m.coords.assert_not_called();m.itemconfigure.assert_not_called()
    def test_aux_uses_available_height_and_actual_width(self):
        m=self.meter('',16,40);m.feed([1],1);m.draw(1)
        bar=m.items[0][0];coords=m.paint_cache[bar,'coords']
        self.assertEqual(coords,(3,12,10,37))
        self.assertEqual(m.create_text.call_args.kwargs['text'],'')
    def test_stale_hides_peaks_and_recovery_restores_them(self):
        m=self.meter();m.feed([.5],1);m.draw(1);peak=m.items[0][1]
        m.draw(2);self.assertEqual(m.paint_cache[peak,'state'],'hidden')
        m.feed([.5],3);m.draw(3);self.assertEqual(m.paint_cache[peak,'state'],'normal')
    def test_initial_empty_meter_has_no_peak(self):
        m=self.meter();m.draw(1)
        self.assertEqual(m.paint_cache[m.items[0][1],'state'],'hidden')

if __name__=='__main__':unittest.main()
