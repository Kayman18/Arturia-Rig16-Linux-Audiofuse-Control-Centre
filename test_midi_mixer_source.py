import unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig,DeviceError
from midi_ports import OPTIONS,PARAMETERS,set_option,snapshot
import test_midi_ports as base

class MixerSourceTests(unittest.TestCase):
    def test_verified_mapping_and_demo_all_options(self):
        self.assertEqual(OPTIONS['mixer_source'],('Disabled','DIN','USB Host','USB Device'))
        self.assertEqual(PARAMETERS['mixer_source'],16)
        d=DemoAF16Rig();current=0
        for target in (1,2,3,0):
            r=set_option(d,'mixer_source',target,current);current=target
            self.assertEqual(r['mixer_source']['raw'],target)
            self.assertEqual((r['host_cable']['raw'],r['din_clock']['raw']),(0,0))
    @patch('midi_ports.time.sleep')
    def test_source_change_does_not_touch_assignments_or_port_settings(self,sleep):
        d,words,calls=base.PortTests().device()
        words[6,0]=15;words[7,0]=3;before=words.copy()
        set_option(d,'mixer_source',2,0)
        self.assertEqual([k for k in words if words[k]!=before[k]],[(16,0)])
        self.assertEqual([c for c in calls if c[0]==0x40],[(0x40,0x11,16,0,b'\x02\x00')])
    def test_reserved_source_codes_block_edit(self):
        d,words,calls=base.PortTests().device()
        for value in (4,65535,True,-1):
            with self.assertRaises(ValueError):set_option(d,'mixer_source',value,0)
            with self.assertRaises(ValueError):set_option(d,'mixer_source',0,value)
        self.assertEqual(calls,[])
    def test_popup_source_confirmation_and_disable(self):
        w=base.PortPageTests().window();w.selectors['mixer_source'].current.return_value=3
        w.apply('mixer_source');cmd,data=w.app.worker.commands.get_nowait()
        self.assertEqual((cmd,data['field'],data['target'],data['expected']),('midi_ports_set','mixer_source',3,0))
        actual=set_option(DemoAF16Rig(),'mixer_source',3,0)
        w.handle(dict(kind='midi_ports_written',records=actual,request_id=data['request_id'],connection_serial=7))
        w.values['mixer_source'].config.assert_called_with(text='USB Device')
        w.selectors['mixer_source'].current.return_value=0;w.apply('mixer_source')
        _,data=w.app.worker.commands.get_nowait();self.assertEqual((data['target'],data['expected']),(0,3))
    def test_unknown_current_source_is_displayed_but_disabled(self):
        w=base.PortPageTests().window();w.refresh();_,data=w.app.worker.commands.get_nowait()
        actual=snapshot(DemoAF16Rig());actual['mixer_source']['raw']=8
        w.handle(dict(kind='midi_ports_snapshot',records=actual,request_id=data['request_id'],connection_serial=7))
        w.values['mixer_source'].config.assert_called_with(text='Unknown (8)')
        w.buttons['mixer_source'].config.assert_called_with(state='disabled')
        w.apply('mixer_source');self.assertTrue(w.app.worker.commands.empty())

if __name__=='__main__':unittest.main()
