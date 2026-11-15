import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from phones_level import decode_level
from output_strips import OutputStrip


class PhonesReadbackTests(unittest.TestCase):
    def test_signed_q8_examples(self):
        for raw, db, text in ((63324,-8.640625,'-8.64 dB'),
                              (62464,-12.0,'-12.00 dB'),
                              (65535,-1/256,'-0.00 dB'),
                              (0,0.0,'0.00 dB'),
                              (256,1.0,'1.00 dB')):
            self.assertEqual(decode_level(raw),(db,text))

    def test_invalid_values_do_not_become_zero_db(self):
        for raw in (None,True,False,'63324',-1,65536,1.5):
            self.assertEqual(decode_level(raw),(None,'—'))

    def test_infinity_and_full_signed_domain(self):
        self.assertEqual(decode_level(32768),(-128.0,'−∞ dB'))
        for raw in range(65536):
            value,_=decode_level(raw)
            self.assertEqual(value,(raw if raw<32768 else raw-65536)/256)

    def test_live_update_then_disconnect_clears_readback(self):
        p=OutputStrip.__new__(OutputStrip)
        p.app=SimpleNamespace(connected=False);p.phones_request=None
        p.kind='phones';p.level=Mock();p.raw=Mock();p.fader=Mock();p.meter=Mock()
        p.phones_state({'knob_raw':62464})
        p.fader.update_value.assert_called_with(-12.0,False,readout='-12.00 dB',valid=True)
        p.clear()
        p.level.config.assert_called_with(text='—')
        p.fader.update_value.assert_called_with(None,False,readout='—',valid=False)
        p.meter.clear.assert_called_once()

    def test_repeated_readback_does_not_reconfigure_text(self):
        p=OutputStrip.__new__(OutputStrip)
        p.app=SimpleNamespace(connected=False);p.phones_request=None
        p.level=Mock();p.raw=Mock();p.fader=Mock()
        for widget in (p.level,p.raw):
            state={}
            widget.cget.side_effect=state.get
            widget.config.side_effect=state.update
        for _ in range(20):p.phones_state({'knob_raw':62464})
        self.assertEqual(p.level.config.call_count,1)
        self.assertEqual(p.raw.config.call_count,1)


if __name__=='__main__':unittest.main()
