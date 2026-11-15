import unittest
from unittest.mock import Mock
from af16rig import DemoAF16Rig,DeviceError
from preamp import change_pair_gain

class PairGainTests(unittest.TestCase):
    def device(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1;return d
    def test_one_target_changes_both_gains(self):
        d=self.device();result=change_pair_gain(d,1,'rear',7)
        self.assertEqual([s['value'] for s in result],[7,7])
    def test_front_native_steps_change_both(self):
        d=self.device();d.force_rear=0
        self.assertEqual([s['value'] for s in change_pair_gain(d,1,'line',30)],[30,30])
    def test_unlinked_pair_rejected_without_changing_gain(self):
        d=self.device();d.main_stereo=0;d.main_show=65535
        with self.assertRaises(DeviceError):change_pair_gain(d,1,'rear',7)
        self.assertEqual(d.inputs[1]['gain_raw'],0)
    def test_source_mismatch_rejected_before_changes(self):
        d=self.device();d.force_rear=0
        with self.assertRaises(DeviceError):change_pair_gain(d,1,'rear',7)
        self.assertEqual(d.inputs[1]['gain_raw'],0)
    def test_out_of_range_rejected_before_changes(self):
        d=self.device()
        with self.assertRaises(DeviceError):change_pair_gain(d,1,'rear',13)
        self.assertEqual(d.inputs[1]['gain_raw'],0)
    def test_already_matching_pair_skips_writes(self):
        d=self.device();d.inputs[1]['gain_raw']=d.inputs[2]['gain_raw']=5*256
        from unittest.mock import patch
        with patch('preamp.change') as change:
            change_pair_gain(d,1,'rear',5);change.assert_not_called()

if __name__=='__main__':unittest.main()
