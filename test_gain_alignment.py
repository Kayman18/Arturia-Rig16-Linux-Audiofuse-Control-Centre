import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from mixer_view import align_gain_rows,Field

class Spacer(Field):
    def __init__(self):super().__init__();self.managed=False;self.packs=0
    def winfo_manager(self):return 'pack' if self.managed else ''
    def pack(self,**kw):self.managed=True;self.packs+=1;self.before=kw['before']
    def pack_forget(self):self.managed=False

class AlignmentTests(unittest.TestCase):
    def strips(self,height=52,heading=17,label=15):
        dial=Field();dial.config(height=height)
        analog=SimpleNamespace(heading=Mock(),labels={1:Mock()},gains={1:dial})
        analog.heading.winfo_reqheight.return_value=heading
        analog.labels[1].winfo_reqheight.return_value=label
        digital=SimpleNamespace(gain_spacer=Spacer(),link=object())
        return {1:SimpleNamespace(preamp=analog),33:SimpleNamespace(preamp=digital)}
    def test_mixed_bank_reserves_complete_gain_block_before_link(self):
        strips=self.strips();align_gain_rows(strips,[1,33]);p=strips[33].preamp
        self.assertEqual(p.gain_spacer.cget('height'),84);self.assertIs(p.gain_spacer.before,p.link)
    def test_height_tracks_compact_normal_and_tall_dials(self):
        for height in (40,52,63):
            strips=self.strips(height);align_gain_rows(strips,[1,33])
            self.assertEqual(strips[33].preamp.gain_spacer.cget('height'),height+32)
    def test_font_scaling_uses_actual_label_metrics(self):
        strips=self.strips(63,25,23);align_gain_rows(strips,[1,33])
        self.assertEqual(strips[33].preamp.gain_spacer.cget('height'),111)
    def test_digital_only_bank_removes_reserved_gain_space(self):
        strips=self.strips();align_gain_rows(strips,[1,33]);align_gain_rows(strips,[33])
        self.assertFalse(strips[33].preamp.gain_spacer.managed)
        align_gain_rows(strips,[1,33]);self.assertTrue(strips[33].preamp.gain_spacer.managed)
    def test_repeated_refresh_does_not_repack_spacer(self):
        strips=self.strips()
        for _ in range(20):align_gain_rows(strips,[1,33])
        self.assertEqual(strips[33].preamp.gain_spacer.packs,1)

if __name__=='__main__':unittest.main()
