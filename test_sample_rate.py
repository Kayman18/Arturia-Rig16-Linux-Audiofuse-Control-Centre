import ctypes as C
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig,DeviceError
from clock_controls import DEMO_RAW,RATES
from sample_rate import AlsaRate,idle_card,set_rate

def status():
    return dict(cards=[dict(card='card4',id='AF16Rig')],streams=[dict(card='card4',pcm='pcm0p',state='Closed'),dict(card='card4',pcm='pcm0c',state='Closed')],errors=[])

class RateTests(unittest.TestCase):
    def test_all_demo_transitions(self):
        for old in range(1,7):
            for rate in RATES[1:]:
                d=DemoAF16Rig();d.clock_raw={**DEMO_RAW,'internal_frequency':old}
                self.assertEqual(set_rate(d,rate,d.clock_raw.copy()),rate)
                self.assertEqual(d.clock_raw['internal_frequency'],RATES.index(rate))
    def test_card_requires_idle_unambiguous_streams(self):
        self.assertEqual(idle_card(status()),'card4')
        for key,value in [('cards',[]),('cards',status()['cards']*2),('streams',[]),('errors',['unreadable'])]:
            s=status();s[key]=value
            with self.assertRaises(DeviceError):idle_card(s)
        for state in ('RUNNING','PREPARED','Configured','Unavailable'):
            s=status();s['streams'][1]['state']=state
            with self.assertRaises(DeviceError):idle_card(s)
    def test_bad_rates_and_external_clock(self):
        d=DemoAF16Rig()
        for rate in (True,48000.0,32000,0):
            with self.assertRaises(ValueError):set_rate(d,rate,DEMO_RAW)
        for field in ('selected_source','preferred_source'):
            d.clock_raw={**DEMO_RAW,field:1}
            with self.assertRaises(DeviceError):set_rate(d,96000,d.clock_raw.copy())
    def native(self):return SimpleNamespace(version=18,last_write=None),DEMO_RAW.copy(),Mock()
    @patch('sample_rate.time.sleep')
    def test_confirmed_native_rate_and_no_vendor_out(self,sleep):
        d,raw,backend=self.native()
        def apply(card,rate,guard):guard();raw['internal_frequency']=RATES.index(rate)
        backend.apply.side_effect=apply
        with patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',side_effect=lambda root:status()):
            self.assertEqual(set_rate(d,96000,raw.copy(),backend=backend),96000)
        backend.apply.assert_called_once();self.assertTrue(d.last_write['confirmed']);self.assertEqual(d.last_write['apply_attempts'],1)
    @patch('sample_rate.time.sleep')
    def test_no_confirmation_never_reapplies(self,sleep):
        d,raw,backend=self.native();backend.apply.side_effect=lambda card,rate,guard:guard()
        with patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',return_value=status()):
            with self.assertRaisesRegex(DeviceError,'not confirmed'):set_rate(d,96000,raw.copy(),backend=backend)
        backend.apply.assert_called_once();self.assertFalse(d.last_write['confirmed'])
    def test_busy_card_never_opens_backend(self):
        d,raw,backend=self.native();s=status();s['streams'][0]['state']='RUNNING'
        with patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',return_value=s):
            with self.assertRaises(DeviceError):set_rate(d,96000,raw.copy(),backend=backend)
        backend.apply.assert_not_called()
    def test_clock_change_before_apply_blocks(self):
        d,raw,backend=self.native()
        def apply(card,rate,guard):raw['selected_source']=1;guard()
        backend.apply.side_effect=apply
        with patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',return_value=status()):
            with self.assertRaises(DeviceError):set_rate(d,96000,raw.copy(),backend=backend)
        self.assertEqual(d.last_write['apply_attempts'],0)
    def test_stream_race_blocks(self):
        d,raw,backend=self.native();s=status();s['streams'][1]['state']='RUNNING'
        backend.apply.side_effect=lambda card,rate,guard:guard()
        with patch('sample_rate.read_register',side_effect=lambda d,k:raw[k]),patch('sample_rate.alsa_streams',side_effect=[status(),s]):
            with self.assertRaises(DeviceError):set_rate(d,96000,raw.copy(),backend=backend)
        self.assertEqual(d.last_write['apply_attempts'],0)

class AlsaTests(unittest.TestCase):
    def lib(self):
        lib=Mock();lib.snd_strerror.return_value=b'ALSA error'
        def setptr(ptr,value):C.cast(ptr,C.POINTER(C.c_void_p))[0]=value;return 0
        lib.snd_pcm_open.side_effect=lambda p,*args:setptr(p,1)
        lib.snd_pcm_hw_params_malloc.side_effect=lambda p:setptr(p,2)
        for name in ('any','set_access','set_format','set_rate','set_channels'):
            getattr(lib,'snd_pcm_hw_params_'+name).return_value=0
        lib.snd_pcm_hw_params.return_value=0;lib.snd_pcm_format_value.return_value=10
        def channels(params,p):C.cast(p,C.POINTER(C.c_uint))[0]=32;return 0
        def rate(params,p,d):C.cast(p,C.POINTER(C.c_uint))[0]=96000;C.cast(d,C.POINTER(C.c_int))[0]=0;return 0
        lib.snd_pcm_hw_params_get_channels_min.side_effect=channels
        lib.snd_pcm_hw_params_get_rate.side_effect=rate
        return lib
    def test_exact_rate_no_playback_and_cleanup(self):
        lib=self.lib();guard=Mock();AlsaRate(lib).apply('card4',96000,guard)
        self.assertEqual(lib.snd_pcm_open.call_args.args[1:],(b'hw:4,0',0,1))
        self.assertEqual(lib.snd_pcm_hw_params_set_rate.call_args.args[2:],(96000,0))
        guard.assert_called_once();lib.snd_pcm_hw_params.assert_called_once()
        lib.snd_pcm_close.assert_called_once();lib.snd_pcm_hw_params_free.assert_called_once()
        lib.snd_pcm_start.assert_not_called();lib.snd_pcm_writei.assert_not_called()
    def test_every_setup_failure_frees_resources_without_apply(self):
        for name in ('snd_pcm_hw_params_any','snd_pcm_hw_params_set_access','snd_pcm_hw_params_set_format','snd_pcm_hw_params_set_rate','snd_pcm_hw_params_set_channels'):
            lib=self.lib();getattr(lib,name).return_value=-16
            with self.assertRaises(DeviceError):AlsaRate(lib).apply('card4',96000,Mock())
            lib.snd_pcm_close.assert_called_once();lib.snd_pcm_hw_params_free.assert_called_once();lib.snd_pcm_hw_params.assert_not_called()
    def test_failed_open_does_not_close_invalid_handle(self):
        lib=self.lib();lib.snd_pcm_open.side_effect=None;lib.snd_pcm_open.return_value=-16
        with self.assertRaises(DeviceError):AlsaRate(lib).apply('card4',96000,Mock())
        lib.snd_pcm_close.assert_not_called()
    def test_guard_failure_closes_handle(self):
        lib=self.lib()
        with self.assertRaises(DeviceError):AlsaRate(lib).apply('card4',96000,Mock(side_effect=DeviceError('changed')))
        lib.snd_pcm_hw_params.assert_not_called();lib.snd_pcm_close.assert_called_once()
    def test_apply_failure_not_retried(self):
        lib=self.lib();lib.snd_pcm_hw_params.return_value=-5
        with self.assertRaises(DeviceError):AlsaRate(lib).apply('card4',96000,Mock())
        lib.snd_pcm_hw_params.assert_called_once();lib.snd_pcm_close.assert_called_once()

if __name__=='__main__':unittest.main()

class RateWindowTests(unittest.TestCase):
    def window(self):
        import queue,time
        from clock_window import ClockWindow
        w=ClockWindow.__new__(ClockWindow);w.pending=None;w.last_read=time.monotonic()
        w.app=SimpleNamespace(connected=True,name_cache=SimpleNamespace(serial=3),worker=SimpleNamespace(commands=queue.Queue()))
        w.state=dict(raw=DEMO_RAW.copy(),alsa=status(),stable=True,connection_serial=3)
        w.choices={};w.apply_buttons={};w.rate_choice=Mock();w.rate_choice.current.return_value=3;w.rate_choice.get.return_value='96,000 Hz'
        w.rate_choice.cget.return_value='disabled';w.rate_button=Mock();w.rate_button.cget.return_value='normal';w.write_status=Mock()
        return w
    def test_rate_command_and_single_flight(self):
        w=self.window();w.apply_rate();w.apply_rate()
        cmd,data=w.app.worker.commands.get_nowait()
        self.assertEqual((cmd,data['field'],data['target']),('clock_set','sample_rate',96000))
        self.assertTrue(w.app.worker.commands.empty())
        self.assertEqual(w.state['raw']['internal_frequency'],2)
    def test_old_connection_and_stale_snapshot_do_not_write(self):
        for stale in ('connection','age'):
            w=self.window()
            if stale=='connection':w.app.name_cache.serial=4
            else:w.last_read=0
            w.apply_rate();self.assertTrue(w.app.worker.commands.empty())
    def test_busy_audio_disables_rate_only(self):
        w=self.window();w.state['alsa']['streams'][0]['state']='RUNNING';w.rate_button.cget.return_value='normal'
        w.sync_controls();w.rate_button.config.assert_called_with(state='disabled')
