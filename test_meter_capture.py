import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from meter_bridge import MeterSession,KEYS
from meter_capture import capture
from meters_window import MetersWindow
from test_meter_bridge import frame

class CaptureTests(unittest.TestCase):
    def session(self):
        s=MeterSession(7);s.feed(7,frame(16384),10);return s
    def test_all_banks_with_stable_indices_and_names(self):
        s=self.session();d=capture(s,{1:'Synth'},10)
        self.assertEqual(len(d['readings']),118)
        self.assertEqual([(r['group'],r['index']) for r in d['readings']],list(KEYS))
        self.assertEqual(d['readings'][0]['label'],'Synth')
        self.assertAlmostEqual(d['readings'][0]['last_dbfs'],-6.0203,places=3)
    def test_stale_and_unavailable_are_explicit(self):
        d=capture(self.session(),{},11)
        self.assertFalse(d['fresh_at_capture']);self.assertEqual(d['frame_age_seconds'],1)
        self.assertIsNotNone(d['readings'][0]['last_linear'])
        d=capture(MeterSession(),{},11)
        self.assertIsNone(d['readings'][0]['last_linear']);self.assertIsNone(d['frame_age_seconds'])
    def test_silence_is_json_safe_and_distinct_from_missing(self):
        s=MeterSession(7);s.feed(7,frame(),0)
        d=capture(s,{},0);r=d['readings'][0]
        self.assertEqual(r['last_linear'],0);self.assertIsNone(r['last_dbfs'])
        json.dumps(d,allow_nan=False)
    def test_peaks_and_demo_are_preserved(self):
        s=self.session();s.feed(7,frame(32767),11);s.feed(7,frame(),12)
        d=capture(s,{},12,demo=True,held=True)
        self.assertTrue(d['demo']);self.assertTrue(d['held'])
        r=d['readings'][0];self.assertEqual(r['peak_dbfs'],0);self.assertTrue(r['observed_full_scale'])
    def window(self):
        w=MetersWindow.__new__(MetersWindow);w.session=self.session();w.held=None
        w.app=Mock();w.app.demo=False;w.app.name_cache.names={1:'Synth'}
        w.tiles={('inputs',0):(Mock(),Mock(),Mock())};w.hold_button=Mock();w.window=Mock()
        return w
    def test_hold_freezes_all_banks_but_keeps_live_peaks(self):
        w=self.window()
        with patch('meters_window.time.monotonic',return_value=10):w.toggle_hold()
        w.accept(7,frame(32767),11)
        self.assertLess(w.held.peaks['inputs',0],1);self.assertEqual(w.session.peaks['inputs',0],1)
        self.assertEqual(len(w.held.frame),118)
        w.app.worker.commands.put.assert_not_called()
        w.toggle_hold();self.assertIsNone(w.held)
        w.tiles['inputs',0][1].feed.assert_called_with([1],11)
    def test_hold_refuses_stale_and_disconnect_clears_it(self):
        w=self.window()
        with patch('meters_window.time.monotonic',return_value=20):w.toggle_hold()
        self.assertIsNone(w.held)
        with patch('meters_window.time.monotonic',return_value=10):w.toggle_hold()
        w.handle_meter_event(dict(kind='disconnected',connection_serial=7))
        self.assertIsNone(w.held);self.assertIsNone(w.session.frame)
    def test_export_captures_before_dialog_changes_device(self):
        w=self.window()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'meters.json'
            def dialog(**kw):
                w.session.reset(8);w.app.name_cache.names={};return str(path)
            with patch('meters_window.filedialog.asksaveasfilename',side_effect=dialog),patch('meters_window.time.monotonic',return_value=10):
                w.save_snapshot()
            d=json.loads(path.read_text());self.assertEqual(d['connection_serial'],7)
            self.assertEqual(d['readings'][0]['label'],'Synth')
            self.assertIsNotNone(d['readings'][0]['last_linear'])
    def test_cancel_and_write_failure_are_handled(self):
        w=self.window()
        with patch('meters_window.filedialog.asksaveasfilename',return_value=''),patch('meters_window.Path.write_text') as write:
            w.save_snapshot();write.assert_not_called()
        with patch('meters_window.filedialog.asksaveasfilename',return_value='/x'),patch('meters_window.Path.write_text',side_effect=OSError('disk full')),patch('meters_window.messagebox.showerror') as error:
            w.save_snapshot();error.assert_called_once()
    def test_reset_held_peaks_also_resets_background(self):
        w=self.window()
        with patch('meters_window.time.monotonic',return_value=10):w.toggle_hold()
        w.reset_peaks(('inputs',0))
        self.assertNotIn(('inputs',0),w.held.peaks);self.assertNotIn(('inputs',0),w.session.peaks)
        self.assertEqual(len(w.held.peaks),117)

if __name__=='__main__':unittest.main()
