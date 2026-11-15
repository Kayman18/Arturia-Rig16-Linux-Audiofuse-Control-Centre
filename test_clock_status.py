import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from clock_status import alsa_streams,snapshot,read_register,FIELDS
from clock_window import ClockWindow
from af16rig_gui import Worker
from test_controls import FakeUSB,Fn

class ClockUSB(FakeUSB):
    def __init__(self):
        super().__init__();self.clock_reads=[];self.result=2;self.changing=False
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,n,t):
            if (req-0x90,param) in FIELDS.values():
                self.clock_reads.append((bm,req,param,index,n))
                word=param+100 if req==0x90 else param
                if self.changing and len(self.clock_reads)>len(FIELDS):word+=1
                data[:2]=word.to_bytes(2,'little');return self.result
            return original(h,bm,req,param,index,data,n,t)
        self.libusb_control_transfer=Fn(transfer)

class ClockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def card(self,name='card4',identity='AF16Rig'):
        card=self.root/name;card.mkdir();(card/'id').write_text(identity);return card
    def stream(self,card,pcm,params,status='state: RUNNING\n'):
        sub=card/pcm/'sub0';sub.mkdir(parents=True);(sub/'hw_params').write_text(params);(sub/'status').write_text(status)
    def device(self):
        usb=ClockUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close);usb.clock_reads=[];return d,usb
    def test_only_af16rig_audio_card_matches(self):
        self.card('card0','NVidia');self.card('card7','MIDI');self.card('card6','AF16Rig MIDI');self.card()
        self.assertEqual(alsa_streams(self.root)['cards'],[dict(card='card4',id='AF16Rig')])
    def test_rates_come_from_each_stream_not_capability_lists(self):
        card=self.card();self.stream(card,'pcm0p','format: S32_LE\nchannels: 32\nrate: 96000 (96000/1)\n')
        self.stream(card,'pcm0c','format: S24_3LE\nchannels: 16\nrate: 48000 (48000/1)\n','state: PREPARED\n')
        (card/'stream0').write_text('Rates: 44100, 48000, 96000, 192000\n')
        streams=alsa_streams(self.root)['streams']
        self.assertEqual([(s['direction'],s['rate_hz'],s['state']) for s in streams],[('Capture',48000,'PREPARED'),('Playback',96000,'RUNNING')])
    def test_closed_stream_has_no_claimed_rate(self):
        card=self.card();self.stream(card,'pcm0p','closed\n')
        s=alsa_streams(self.root)['streams'][0];self.assertEqual(s['state'],'Closed');self.assertIsNone(s['rate_hz'])
    def test_missing_files_are_reported_without_exception(self):
        card=self.card();(card/'pcm0p'/'sub0').mkdir(parents=True)
        result=alsa_streams(self.root);self.assertTrue(result['errors']);self.assertEqual(result['streams'][0]['state'],'Unavailable')
    def test_no_card_and_no_proc_directory(self):
        self.assertTrue(alsa_streams(self.root)['errors']);self.assertTrue(alsa_streams(self.root/'missing')['errors'])
    def test_multiple_af16rig_cards_retained_separately(self):
        for card in (self.card(),self.card('card5','AF16Rig_1')):self.stream(card,'pcm0p','closed')
        self.assertEqual(len(alsa_streams(self.root)['cards']),2)
    def test_exact_register_reads_twice_no_out_or_decoding(self):
        d,u=self.device();r=snapshot(d,self.root)
        expected=[(0xc0,0x90+group,param,0,2) for group,param in FIELDS.values()]*2
        self.assertEqual(u.clock_reads,expected);self.assertTrue(r['stable']);self.assertTrue(r['clock_enums_verified']);self.assertEqual(r['write_requests'],0)
        self.assertEqual(r['raw']['internal_frequency'],110)
    def test_short_read_stops_and_pauses_until_retry(self):
        d,u=self.device();u.result=1;r=snapshot(d,self.root)
        self.assertIn('native',r['errors']);self.assertEqual(len(u.clock_reads),1)
        u.result=2;snapshot(d,self.root);self.assertEqual(len(u.clock_reads),1)
        d.clock_status_failure=None;self.assertTrue(snapshot(d,self.root)['stable'])
        self.assertEqual(len(u.clock_reads),19)
    def test_failed_native_read_does_not_hide_alsa_state(self):
        self.stream(self.card(),'pcm0p','rate: 48000\nchannels: 32\nformat: S32_LE\n')
        d,u=self.device();u.result=-9;r=snapshot(d,self.root)
        self.assertEqual(r['alsa']['streams'][0]['rate_hz'],48000);self.assertFalse(r['stable'])
    def test_changing_capture_marked_unstable(self):
        d,u=self.device();u.changing=True;r=snapshot(d,self.root)
        self.assertFalse(r['stable']);self.assertIn('changing',r['errors']);self.assertEqual(len(r['passes']),2)
    def test_disconnect_propagates(self):
        d,u=self.device();u.result=-4
        with self.assertRaises(DeviceDisconnected):snapshot(d,self.root)
        self.assertEqual(len(u.clock_reads),1)
    def test_unknown_version_no_native_usb(self):
        d,u=self.device();d.version=19;r=snapshot(d,self.root)
        self.assertEqual(u.clock_reads,[]);self.assertIn('native',r['errors'])
    def test_invalid_field_no_usb(self):
        d,u=self.device()
        with self.assertRaises(ValueError):read_register(d,'speaker_level')
        self.assertEqual(u.clock_reads,[])
    def test_demo_not_misrepresented_as_physical(self):
        r=snapshot(DemoAF16Rig(),self.root)
        self.assertTrue(r['demo']);self.assertEqual(r['raw']['internal_frequency'],2);self.assertEqual(r['alsa']['streams'][0]['state'],'DEMO')
    def test_unchanged_table_rows_not_rebuilt(self):
        table=Mock();table.get_children.return_value=['one'];table.exists.return_value=True;table.item.return_value=('A','48000')
        ClockWindow.update_rows(table,[('one',('A',48000))]);table.insert.assert_not_called();table.delete.assert_not_called()
        table.item.assert_called_once_with('one','values')
    def test_old_connection_page_reply_ignored(self):
        window=ClockWindow.__new__(ClockWindow);window.app=SimpleNamespace(name_cache=SimpleNamespace(serial=2));window.state=None
        window.handle(dict(kind='input_snapshot',state=dict(channel='clock',connection_serial=1)))
        self.assertIsNone(window.state)
    def test_disconnect_clears_visible_old_values(self):
        window=ClockWindow.__new__(ClockWindow);window.state={'old':True};window.save_button=Mock();window.summary=Mock();window.message=Mock();window.streams=Mock();window.registers=Mock();window.update_rows=Mock()
        window.handle(dict(kind='input_error',channel='clock',message='Disconnected'))
        self.assertIsNone(window.state);self.assertEqual(window.update_rows.call_count,2);window.save_button.config.assert_called_with(state='disabled')
    def test_worker_clock_poll_is_tagged_and_remains_read_only(self):
        import queue
        events=queue.Queue();w=Worker(events);w.device=DemoAF16Rig();w.input_channel='clock';w.connection_serial=4
        w.poll_input();event=events.get_nowait()
        self.assertEqual(event['state']['connection_serial'],4);self.assertEqual(event['state']['write_requests'],0)
