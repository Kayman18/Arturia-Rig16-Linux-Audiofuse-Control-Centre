import unittest
from unittest.mock import patch
from af16rig import DeviceError, DemoAF16Rig
from midi_ports import set_option, snapshot, OPTIONS
import test_midi_ports as base

class PreferredModeTests(unittest.TestCase):
    @patch('midi_ports.time.sleep')
    def test_both_modes_preserve_all_other_words(self, sleep):
        self.assertEqual(OPTIONS['preferred_mode'], ('Standalone', 'Hosted'))
        for old in (0,1):
            d,words,calls=base.PortTests().device(old)
            before=words.copy()
            actual=set_option(d,'preferred_mode',1-old,old)
            self.assertEqual(actual['preferred_mode']['raw'],1-old)
            self.assertEqual([c for c in calls if c[0]==0x40],[(0x40,0x11,5,0,(1-old).to_bytes(2,'little'))])
            before[(5,0)]=1-old
            self.assertEqual(words,before)
    def test_unknown_and_stale_mode_cannot_write(self):
        d,words,calls=base.PortTests().device()
        words[(5,0)]=65535
        self.assertEqual(snapshot(d)['preferred_mode']['raw'],65535)
        with self.assertRaises(DeviceError):set_option(d,'preferred_mode',1,0)
        for value in (-1,2,True):
            with self.assertRaises(ValueError):set_option(d,'preferred_mode',value,0)
        self.assertFalse(any(c[0]==0x40 for c in calls))
    @patch('midi_ports.time.sleep')
    def test_rejection_not_retried(self,sleep):
        d,words,calls=base.PortTests().device(accept=False)
        with self.assertRaises(DeviceError):set_option(d,'preferred_mode',1,0)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
        self.assertFalse(d.last_write['confirmed'])
    def test_demo_and_ui_confirmed_readback(self):
        w=base.PortPageTests().window();w.apply('preferred_mode')
        cmd,data=w.app.worker.commands.get_nowait()
        self.assertEqual((cmd,data['field'],data['target']),('midi_ports_set','preferred_mode',1))
        self.assertEqual(w.records['preferred_mode']['raw'],0)
        records=set_option(DemoAF16Rig(),'preferred_mode',1,0)
        self.assertTrue(w.handle(dict(kind='midi_ports_written',request_id=w.request,connection_serial=7,records=records)))
        self.assertEqual(w.records['preferred_mode']['raw'],1)

if __name__=='__main__':unittest.main()
