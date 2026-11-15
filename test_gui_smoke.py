import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from gui_smoke import DemoGuard, Runner
from wrap_bar import wrap_rows, WrapBar

class GuiSmokeTests(unittest.TestCase):
    def test_wrap_exact_fit(self):
        self.assertEqual(wrap_rows(212,[100,100]),[[0,1]])
        self.assertEqual(wrap_rows(211,[100,100]),[[0],[1]])

    def test_wrap_narrow_and_empty(self):
        self.assertEqual(wrap_rows(0,[100,20]),[[0],[1]])
        self.assertEqual(wrap_rows(100,[]),[])

    def test_wrap_preserves_order_at_all_widths(self):
        widths=[55,120,83,42,190,15]
        for width in range(1,700):
            rows=wrap_rows(width,widths)
            self.assertEqual([i for row in rows for i in row],list(range(len(widths))))
            for row in rows:
                self.assertTrue(len(row)==1 or sum(widths[i]+6 for i in row)<=width)

    def test_unchanged_layout_does_not_repack(self):
        item=Mock();item.winfo_reqwidth.return_value=50
        bar=Mock(items=[item],layout_key=((0,),),rows=[])
        bar.winfo_width.return_value=200;bar.winfo_pixels.return_value=0
        WrapBar.reflow(bar)
        item.pack_forget.assert_not_called()

    def test_demo_guard_blocks_native_and_restores(self):
        import af16rig
        import window_state
        original=af16rig.AF16Rig.__init__;save=window_state.save
        with DemoGuard():
            with self.assertRaisesRegex(AssertionError,'Physical USB'):af16rig.AF16Rig()
            window_state.save(object())
        self.assertIs(af16rig.AF16Rig.__init__,original)
        self.assertIs(window_state.save,save)

    def runner(self):
        return Runner(Mock(),Mock(),dict(checks=[],callback_errors=[],layouts=[]),'.')

    def test_failed_action_continues_and_reports_failure(self):
        r=self.runner()
        r.add('bad',Mock(side_effect=ValueError('broken')))
        r.tick()
        self.assertEqual(r.report['checks'][0]['status'],'failed')
        r.tick()
        self.assertEqual(r.report['status'],'failed')
        r.app.close.assert_called_once()

    def test_timeout_is_not_pass(self):
        r=self.runner();r.add('wait',lambda:None,ready=lambda:False,timeout=1)
        r.tick();r.step_started-=2;r.tick();r.tick()
        self.assertEqual(r.report['status'],'failed')
        self.assertIn('Timed out',r.report['checks'][0]['detail'])

    def test_callback_error_fails_otherwise_successful_run(self):
        r=self.runner();r.callback_error(ValueError,ValueError('callback'),None);r.finish()
        self.assertEqual(r.report['status'],'failed')
        self.assertEqual(r.report['callback_error_count'],1)

    def test_success_and_idempotent_finish(self):
        r=self.runner();r.add('ok',lambda:None,settle=0);r.tick();r.tick();r.finish()
        self.assertEqual(r.report['status'],'passed')
        r.app.close.assert_called_once()

    def test_plan_includes_current_scene_and_phones_controls(self):
        r=self.runner();r.plan();names=[s['name'] for s in r.steps]
        for name in ('Mixer scene capture','Mixer scene save','Mixer scene rate preview','Mixer scene rate matching','Mixer scene setting recall','Phones target','Phones restore'):
            self.assertIn(name,names)
        self.assertNotIn('Phones readback is not a writable level',names)

    def test_phones_check_requires_writable_level_and_stereo_meters(self):
        r=self.runner();p=SimpleNamespace(fader=SimpleNamespace(ready=True,target_callback=lambda:None),meter=SimpleNamespace(model=SimpleNamespace(levels=[0,0])))
        r.app.dashboard.phones_strip=p;r.phones_check()
        p.fader.ready=False
        with self.assertRaises(AssertionError):r.phones_check()

if __name__=='__main__':unittest.main()
