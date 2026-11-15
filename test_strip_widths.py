import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from mixer_view import Console,Field
from mixer_layout import fixed_geometry


class StripWidthTests(unittest.TestCase):
    def resize(self,count,total):
        canvas=Mock();canvas.winfo_width.return_value=total;canvas.winfo_height.return_value=800
        strips={i:SimpleNamespace(frame=Field(),title=Field(),pan=Field(),dials={},preamp=SimpleNamespace(gains={})) for i in range(count)}
        body=Mock();body.winfo_width.return_value=total
        master=SimpleNamespace(frame=Field(),dials={})
        view=SimpleNamespace(body=body,canvas=canvas,visible=list(strips),strips=strips,bank_id=1,master_view=master)
        Console.resize(view)
        widths=[s.frame.cget('width') for s in strips.values()]
        all_widths=widths+[master.frame.cget('width')]
        self.assertLessEqual(max(widths)-min(widths),1)
        self.assertGreaterEqual(master.frame.cget('width'),164)
        self.assertEqual(sum(widths)+3*count+master.frame.cget('width')+5,fixed_geometry(count)[1])
        canvas.configure.assert_called_with(scrollregion=(0,0,fixed_geometry(count)[1],850))
        return widths[0]

    def test_stereo_bank_uses_main_master_width(self):
        self.assertEqual(self.resize(8,2000),164)

    def test_mono_bank_preserves_fixed_channel_width(self):
        self.assertEqual(self.resize(16,1920),164)

    def test_small_window_preserves_width_with_scroll_extent(self):
        self.assertEqual(self.resize(8,1000),164)

    def test_fixed_width_across_screen_sizes_and_channel_counts(self):
        for count in (8,9,12,15,16):
            for total in (800,1024,1280,1366,1536,1920,2048,2560,3440,3840):
                with self.subTest(channels=count,width=total):self.resize(count,total)

    def test_master_packs_immediately_after_channels_when_linking_changes(self):
        order=[]
        def frame(name):
            f=Mock();f.pack.side_effect=lambda **kw:order.append((name,kw));return f
        controllers={i:SimpleNamespace(state={}) for i in range(1,17)}
        strips={i:SimpleNamespace(frame=frame(i),preamp=SimpleNamespace(source_button=None,source_slot=Field())) for i in controllers}
        view=SimpleNamespace(controllers=controllers,strips=strips,visible=[],master_view=SimpleNamespace(frame=frame('master')),bus_buttons={},resize=Mock())
        for stereo in (False,True,False):
            order.clear()
            for i,c in controllers.items():c.state={'stereo_members':[1,2]} if stereo and i%2 else {}
            Console.layout(view)
            self.assertEqual([name for name,kw in order],list(range(1,17,2 if stereo else 1))+['master'])
            self.assertTrue(all(kw['side']=='left' and kw['expand'] is False for name,kw in order))


if __name__=='__main__':unittest.main()
