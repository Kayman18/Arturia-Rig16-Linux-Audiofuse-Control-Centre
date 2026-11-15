import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig,DeviceError,VOLUME_MIN_RAW,VOLUME_MAX_RAW,VOLUME_UNITS_PER_DB
from af16rig_gui import Worker,App
from monitor_level import set_level
from mixer_view import Console,Field
from output_strips import OutputStrip

class OutputStripTests(unittest.TestCase):
    def test_demo_monitor_absolute_target_and_boundaries(self):
        d=DemoAF16Rig()
        for raw in (VOLUME_MIN_RAW,VOLUME_MAX_RAW,-2189):
            self.assertEqual(set_level(d,raw/VOLUME_UNITS_PER_DB),raw)
            self.assertEqual(d.snapshot()['speaker_level_signed'],raw)
    def test_monitor_rejects_invalid_target_without_changes(self):
        d=DemoAF16Rig();before=d.values.copy()
        for value in (True,float('nan'),float('inf'),-10000,10000,'0'):
            with self.assertRaises(ValueError):set_level(d,value)
        self.assertEqual(d.values,before)
    def test_monitor_rejects_unknown_firmware_and_invalid_readback(self):
        d=DemoAF16Rig();d.version=19
        with self.assertRaises(DeviceError):set_level(d,-20)
        d.version=18;d.values['speaker_level']=32768
        with self.assertRaises(DeviceError):set_level(d,-20)
    def test_native_target_uses_existing_confirmed_writer_once(self):
        d=Mock(version=18);d.lock=__import__('threading').RLock()
        d.snapshot.return_value={'speaker_level_signed':-3072}
        self.assertEqual(set_level(d,-8.5),-2176)
        d._write_and_confirm.assert_called_once_with('speaker_level',(-2176)&65535)
    def test_native_unchanged_target_does_not_write(self):
        d=Mock(version=18);d.lock=__import__('threading').RLock()
        d.snapshot.return_value={'speaker_level_signed':-3072}
        set_level(d,-12);d._write_and_confirm.assert_not_called()
    def test_monitor_ui_enqueues_only_when_ready(self):
        a=SimpleNamespace(pending=False,stale=False,connected=True,state={'writes_available':True},update_controls=Mock(),message=Mock(),worker=SimpleNamespace(commands=queue.Queue()))
        self.assertTrue(App.target_volume(a,-10))
        self.assertEqual(a.worker.commands.get_nowait(),('monitor_target',-10))
        self.assertFalse(App.target_volume(a,-5));self.assertTrue(a.worker.commands.empty())
    def test_worker_handles_monitor_target_and_phone_reads(self):
        events=queue.Queue();w=Worker(events,demo=True);w.start()
        try:
            w.commands.put(('connect',None))
            while events.get(timeout=3)['kind']!='connected':pass
            w.commands.put(('monitor_target',-8.5));w.commands.put(('phones_read',None))
            found={}
            while len(found)<2:
                e=events.get(timeout=3)
                self.assertNotIn(e['kind'],('error','command_error','phones_error'))
                if e['kind'] in ('volume_written','phones_snapshot'):found[e['kind']]=e
            self.assertEqual(found['volume_written']['actual'],-2176)
            self.assertTrue(found['phones_snapshot']['state']['read_only'])
        finally:w.stop_event.set();w.join(3)
    def test_phones_strip_decodes_but_disconnected_fader_disabled(self):
        p=OutputStrip.__new__(OutputStrip);p.kind='phones';p.raw=Mock();p.level=Mock();p.fader=Mock()
        p.app=SimpleNamespace(connected=False);p.phones_request=None
        p.phones_state({'knob_raw':63324})
        p.level.config.assert_called_once_with(text='-8.64 dB')
        p.fader.update_value.assert_called_once_with(-8.640625,False,readout='-8.64 dB',valid=True)
    def test_output_strips_stay_before_master_on_all_channel_pages(self):
        order=[]
        def frame(name):
            f=Mock();f.pack.side_effect=lambda **kw:order.append(name);return f
        controllers={i:SimpleNamespace(state={}) for i in range(1,35)}
        strips={i:SimpleNamespace(frame=frame(i),preamp=SimpleNamespace(source_button=None,source_slot=Field())) for i in controllers}
        v=SimpleNamespace(controllers=controllers,strips=strips,visible=[],all_visible=[],channel_page=0,page_slots=9,
            bus='main',bank_start=1,bus_buttons={},resize=Mock(),previous_page=Field(),next_page=Field(),
            output_strips=[SimpleNamespace(frame=frame('phones')),SimpleNamespace(frame=frame('monitor'))],
            master_view=SimpleNamespace(frame=frame('master')))
        v.layout=lambda:Console.layout(v)
        v.layout();self.assertEqual(order,list(range(1,17))+[33,34,'phones','monitor','master'])
        self.assertEqual(v.next_page.cget('state'),'disabled')
        order.clear();Console.change_channel_page(v,1)
        self.assertEqual(order,[])
        self.assertEqual(v.channel_page,0)

if __name__=='__main__':unittest.main()
