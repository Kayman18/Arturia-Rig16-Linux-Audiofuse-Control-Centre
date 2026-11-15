import math
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from meters import decode_frame
from meter_bridge import BANKS,KEYS,MeterSession,label
from meters_window import MetersWindow

def frame(value=0):return decode_frame(struct.pack('<118H',*([value]*118)))

class MeterBridgeTests(unittest.TestCase):
    def test_all_118_taps_appear_exactly_once(self):
        self.assertEqual(len(KEYS),118);self.assertEqual(len(set(KEYS)),118)
        f=decode_frame(struct.pack('<118H',*range(118)))
        self.assertEqual(sorted(f[g][i] for g,i in KEYS),[i/32767 for i in range(118)])
    def test_bank_sizes_fit_two_rows(self):
        self.assertEqual([len(v) for v in BANKS.values()],[32,32,30,24])
    def test_input_and_adat_output_labels_use_hardware_names(self):
        names={1:'Synth',17:'ADAT synth',77:'FX send',65:'Not guessed'}
        self.assertEqual(label(('inputs',0),names),'Synth')
        self.assertEqual(label(('inputs',16),names),'ADAT synth')
        self.assertEqual(label(('adat_outputs',0),names),'FX send')
        self.assertEqual(label(('outputs',0),names),'Line Out 1')
    def test_default_labels_are_distinct_and_complete(self):
        self.assertEqual(len({label(k,{}) for k in KEYS}),118)
    def test_stale_generation_cannot_change_peaks(self):
        s=MeterSession(2)
        self.assertFalse(s.feed(1,frame(32767),1));self.assertFalse(s.feed(None,frame(),1))
        self.assertEqual(s.peaks,{});self.assertIsNone(s.frame)
    def test_peaks_latch_and_do_not_decay_with_live_levels(self):
        s=MeterSession(1);s.feed(1,frame(32767),1);s.feed(1,frame(100),2)
        self.assertEqual(s.peaks[('main',0)],1);self.assertEqual(len(s.full_scale),118)
        self.assertLess(s.frame[('main',0)],.01)
    def test_full_scale_threshold_is_one_not_near_zero_db(self):
        s=MeterSession(1);s.feed(1,frame(32766),1);self.assertEqual(s.full_scale,set())
        f=frame();f['main'][1]=1;s.feed(1,f,2)
        self.assertEqual(s.full_scale,{('main',1)})
    def test_numeric_peak_preserves_above_scale_values(self):
        s=MeterSession(1);s.feed(1,frame(65535),0)
        self.assertEqual(s.peak_text(('main',0)),'Peak 6.0')
    def test_stale_data_does_not_erase_historical_peak(self):
        s=MeterSession(1);s.feed(1,frame(16384),0)
        self.assertTrue(s.fresh(.5));self.assertFalse(s.fresh(.501))
        self.assertEqual(s.peak_text(('main',0)),'Peak -6.0')
    def test_single_reset_leaves_other_channel_history(self):
        s=MeterSession(1);s.feed(1,frame(32767),0);s.reset_peaks(('main',0))
        self.assertEqual(s.peak_text(('main',0)),'Peak —')
        self.assertNotIn(('main',0),s.full_scale);self.assertIn(('main',1),s.full_scale)
        self.assertEqual(s.frame[('main',0)],1)
    def test_reset_all_then_next_frame_rearms(self):
        s=MeterSession(1);s.feed(1,frame(32767),0);s.reset_peaks()
        self.assertEqual(s.peaks,{});self.assertEqual(s.full_scale,set())
        s.feed(1,frame(32767),1);self.assertEqual(len(s.full_scale),118)
    def test_new_connection_clears_all_state(self):
        s=MeterSession(1);s.feed(1,frame(32767),0);s.reset(2)
        self.assertIsNone(s.frame);self.assertFalse(s.fresh(0));self.assertEqual(s.peaks,{})
    def test_invalid_frame_does_not_partially_update(self):
        s=MeterSession(1);s.feed(1,frame(1),0);original=s.frame.copy()
        for bad in (math.nan,math.inf,-1):
            f=frame(32767);f['immersive'][-1]=bad
            with self.assertRaises(ValueError):s.feed(1,f,1)
            self.assertEqual(s.frame,original);self.assertEqual(s.time,0)
    def test_silence_and_no_samples_are_distinguished(self):
        s=MeterSession(1);self.assertEqual(s.peak_text(('main',0)),'Peak —')
        s.feed(1,frame(),0);self.assertEqual(s.peak_text(('main',0)),'Peak ≤−60')

class BridgeWindowTests(unittest.TestCase):
    def window(self):
        w=MetersWindow.__new__(MetersWindow);w.session=MeterSession(4)
        w.tiles={('main',0):(Mock(),Mock(),Mock())};return w
    def test_frame_only_feeds_displayed_meters_no_commands(self):
        w=self.window();w.app=Mock()
        w.accept(4,frame(32767),1)
        w.tiles['main',0][1].feed.assert_called_once_with([1],1)
        w.app.worker.commands.put.assert_not_called();self.assertEqual(len(w.session.peaks),118)
    def test_old_frame_does_not_touch_widgets(self):
        w=self.window();w.accept(3,frame(),1);w.tiles['main',0][1].feed.assert_not_called()
    def test_disconnect_and_preset_load_clear_peak_history(self):
        for kind in ('error','disconnected','preset_state_reset','connected'):
            w=self.window();w.accept(4,frame(32767),1)
            w.handle_meter_event(dict(kind=kind,connection_serial=5))
            self.assertEqual(w.session.peaks,{});w.tiles['main',0][1].clear.assert_called_once()
    def test_old_meter_error_does_not_erase_current_session(self):
        w=self.window();w.accept(4,frame(32767),1)
        w.handle_meter_event(dict(kind='meter_error',connection_serial=3))
        self.assertEqual(len(w.session.peaks),118)
    def test_current_meter_error_blanks_meters(self):
        w=self.window();w.accept(4,frame(32767),1)
        w.handle_meter_event(dict(kind='meter_error',connection_serial=4))
        self.assertIsNone(w.session.frame);w.tiles['main',0][1].clear.assert_called_once()
    def test_close_cancels_draw_job_and_never_writes_device(self):
        w=self.window();w.app=Mock();w.window=Mock();w.job='timer'
        w.close();self.assertTrue(w.closed);w.app.root.after_cancel.assert_called_once_with('timer')
        w.app.worker.commands.put.assert_called_once_with(('input_select',None))

    def test_construct_switch_banks_names_reset_and_close_headlessly(self):
        class Widget:
            def __init__(self,parent=None,**opts):
                self.opts=opts;self.children=[];self.parent=parent
                if isinstance(parent,Widget):parent.children.append(self)
            def pack(self,**kw):pass
            def grid(self,**kw):pass
            def columnconfigure(self,*a,**kw):pass
            def rowconfigure(self,*a,**kw):pass
            def configure(self,**opts):self.opts.update(opts)
            config=configure
            def cget(self,key):return self.opts.get(key)
            def winfo_children(self):return list(self.children)
            def destroy(self):
                if isinstance(self.parent,Widget):self.parent.children.remove(self)
            def title(self,text):pass
        panel=Widget()
        app=SimpleNamespace(dashboard=SimpleNamespace(meter_serial=4,latest_meters=None),
                            make_panel=lambda:panel,name_cache=SimpleNamespace(names={1:'Synth'}),
                            worker=Mock(),root=Mock(),demo=True,input_window=None)
        with patch('meters_window.tk.Frame',Widget),patch('meters_window.tk.Label',Widget),patch('meters_window.tk.Button',Widget),patch('meters_window.tk.StringVar',Mock),patch('meters_window.Meter',lambda *a,**kw:Mock()),patch('mixer_view.button',lambda parent,text,cmd:Widget(parent,text=text,command=cmd)),patch('mixer_view.lab',lambda parent,text,**kw:Widget(parent,text=text,**kw)):
            w=MetersWindow(app);app.input_window=w
            self.assertEqual(len(w.tiles),32);self.assertEqual(w.tiles['inputs',0][0].cget('text'),'Synth')
            w.accept(4,frame(32767),1)
            for bank in ('Outputs','USB','Buses','Inputs'):
                w.show_bank(bank);self.assertEqual(len(w.tiles),len(BANKS[bank]))
                self.assertEqual(len(w.body.winfo_children()),len(BANKS[bank]))
            self.assertEqual(len(w.session.peaks),118)
            app.name_cache.names={1:'New synth'};w.refresh_names()
            self.assertEqual(w.tiles['inputs',0][0].cget('text'),'New synth')
            w.reset_peaks();self.assertEqual(w.session.peaks,{})
            w.close();self.assertIsNone(app.input_window);app.root.after_cancel.assert_called_once()

if __name__=='__main__':unittest.main()
