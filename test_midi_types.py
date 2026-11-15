import unittest
from unittest.mock import patch,Mock
import test_midi_remap as base
from midi_config import FIELDS,MESSAGE_TYPES,remap,decode
from midi_window import MidiWindow
from af16rig import DeviceError

class MidiTypeTests(unittest.TestCase):
    def test_type_only_edit_sends_selected_type_including_off(self):
        for code in (0,2):
            w=base.EditPageTests().window()
            w.edit_channel.get.return_value='1';w.edit_number.get.return_value='0'
            w.type_entry=Mock();w.type_entry.current.return_value=code
            w.apply_edit()
            cmd,data=w.app.worker.commands.get_nowait()
            self.assertEqual(cmd,'midi_remap')
            self.assertEqual((data['message_type'],data['expected']),(code,0x4000))
            self.assertEqual(w.records[0]['raw'],0x4000)
    def test_unchanged_type_and_number_send_nothing(self):
        w=base.EditPageTests().window()
        w.edit_channel.get.return_value='1';w.edit_number.get.return_value='0'
        w.type_entry=Mock();w.type_entry.current.return_value=1
        w.apply_edit();self.assertTrue(w.app.worker.commands.empty())
    @patch('midi_config.time.sleep')
    def test_every_type_transition_on_all_71_assignments(self,sleep):
        for p,i in FIELDS[2:]:
            for old in range(3):
                for new in range(3):
                    initial=old<<14|0x070b
                    d,words,calls=base.RemapTests().device(initial)
                    r=remap(d,p,i,8,11,initial,message_type=new)
                    self.assertEqual((r['channel_code'],r['number_code'],r['type_code']),(7,11,new))
                    outs=[c for c in calls if c[0]==0x40]
                    self.assertEqual(len(outs),int(old!=new))
                    if outs:self.assertEqual(outs[0],(0x40,0x13,p,i,(new<<14|0x070b).to_bytes(2,'little')))
    def test_invalid_type_rejected_without_usb(self):
        for value in (True,-1,3,'CC',1.5):
            d,words,calls=base.RemapTests().device()
            with self.assertRaises(ValueError):remap(d,20,0,3,7,0x4207,message_type=value)
            self.assertEqual(calls,[])
    @patch('midi_config.time.sleep')
    def test_failed_type_write_not_retried(self,sleep):
        d,words,calls=base.RemapTests().device(accept=False)
        with self.assertRaises(DeviceError):remap(d,20,0,3,7,0x4207,message_type=2)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    def test_table_labels_all_types_and_unknown(self):
        for code,label in enumerate((*MESSAGE_TYPES,'Unknown')):
            r=decode(20,0,code<<14);r['stable']=True
            self.assertEqual(MidiWindow.row_values(r)[3],label)
        r=decode(18,0,8);r['stable']=True
        self.assertEqual(MidiWindow.row_values(r)[3],'—')

if __name__=='__main__':unittest.main()
