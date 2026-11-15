import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,PARAMETERS,DeviceError
from test_controls import FakeUSB

class ActiveLinkTests(unittest.TestCase):
    def device(self,detected):
        u=FakeUSB()
        for key in PARAMETERS.values():u.values.setdefault(key,0)
        u.values[PARAMETERS['detect_status']]=detected
        d=AF16Rig(u);d.open();self.addCleanup(d.close)
        sleeper=patch('af16rig.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
        return d,u
    def test_front_line_uses_parameter22_never_rear24(self):
        d,u=self.device(0x21)
        self.assertEqual(d.write_input_link(1,True),1)
        out=[c for c in u.calls if c[0]==0x40]
        self.assertEqual([(c[2],c[3]) for c in out],[(22,0)])
        state=d.input_snapshot(2)
        self.assertEqual(state['link'],1);self.assertEqual(state['link_bank'],'line')
        self.assertEqual(u.values[PARAMETERS['rear_link']],0)
    def test_front_mics_use_parameter23_from_either_channel(self):
        d,u=self.device(0x42)
        d.write_input_link(2,True);d.write_input_link(1,False)
        self.assertEqual([c[2] for c in u.calls if c[0]==0x40],[23,23])
        self.assertEqual(d.input_snapshot(1)['link_bank'],'mic')
    def test_front_snapshot_does_not_show_stored_rear_link(self):
        d,u=self.device(0x21);u.values[PARAMETERS['rear_link']]=3
        self.assertEqual(d.input_snapshot(1)['link'],0)
    def test_front_source_change_is_rechecked_on_write(self):
        d,u=self.device(0x21);self.assertEqual(d.input_snapshot(1)['link_bank'],'line')
        u.values[PARAMETERS['detect_status']]=0x42
        d.write_input_link(1,True)
        self.assertEqual([c[2] for c in u.calls if c[0]==0x40],[23])
    def test_mixed_sources_reject_before_any_out(self):
        d,u=self.device(0x41)
        with self.assertRaisesRegex(DeviceError,'mixed source modes'):d.write_input_link(1,True)
        self.assertFalse(d.input_snapshot(1)['control_available']['link'])
        self.assertFalse(any(c[0]==0x40 for c in u.calls))
    def test_demo_front_link_matches_active_readback(self):
        d=DemoAF16Rig();d.force_rear=0
        d.write_input_link(1,True)
        self.assertEqual(d.input_snapshot(2)['link'],1)
        self.assertEqual(d.input_snapshot(2)['link_bank'],'line')
        self.assertEqual(d.inputs[1]['link'],0)

if __name__=='__main__':unittest.main()
