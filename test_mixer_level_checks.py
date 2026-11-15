import unittest
from unittest.mock import patch

from af16rig import AF16Rig, DeviceError, PARAMETERS
from mixer_level_checks import mixer_level_suite
from test_controls import FakeUSB


class MixerLevels(unittest.TestCase):
    def setUp(self):
        self.usb = FakeUSB()
        self.device = AF16Rig(self.usb)
        self.device.open()
        self.addCleanup(self.device.close)
        sleep = patch('af16rig.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)
        self.usb.values[PARAMETERS['main_channel_show']] = 3
        self.usb.values[PARAMETERS['main_channel_stereo']] = 254
        self.usb.values[PARAMETERS['cue_channel_show']] = 0
        self.levels = {}
        for name in ('main_channel_level', 'cue_channel_level',
                     'aux1_send_level', 'aux2_send_level', 'aux3_send_level', 'aux4_send_level'):
            for i in range(16):
                self.levels[PARAMETERS[name], i] = (-7219) & 65535
        original = self.usb.libusb_control_transfer.func
        def indexed(handle, bm, req, param, index, data, length, timeout):
            key = ((req - (0x90 if bm == 0xc0 else 0x10), param), index)
            if key in self.levels:
                if bm == 0x40:
                    self.levels[key] = int.from_bytes(bytes(data), 'little')
                else:
                    value = self.levels[key]
                    data[0], data[1] = value & 255, value >> 8
                return 2
            return original(handle, bm, req, param, index, data, length, timeout)
        self.usb.libusb_control_transfer.func = indexed

    def test_current_routing_exercises_45_checks_and_restores_all_members(self):
        start = dict(self.levels)
        report = {'cases': []}
        mixer_level_suite(self.device, report, lambda: None)
        self.assertEqual(report['mixer_level_checks_planned'], 45)
        self.assertEqual(len(report['cases']), 45)
        self.assertTrue(all(c['status'] == 'passed' for c in report['cases']))
        self.assertEqual(self.levels, start)

    def test_partial_stereo_write_restores_only_changed_member(self):
        original = self.device._write_and_confirm
        def fail_right(field, word, index=0):
            if field == 'main_channel_level' and index == 3 and word == ((-7475) & 65535):
                raise DeviceError('simulated right write failure')
            return original(field, word, index)
        before = dict(self.levels)
        report = {'cases': []}
        with patch.object(self.device, '_write_and_confirm', fail_right):
            mixer_level_suite(self.device, report, lambda: None)
        failed = [c for c in report['cases'] if c['status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['restoration'], 'verified')
        self.assertEqual(self.levels, before)
        self.assertEqual(len(report['cases']), 45)

    def test_out_of_range_and_unequal_members_skip(self):
        self.levels[PARAMETERS['main_channel_level'], 2] = (-61 * 256) & 65535
        self.levels[PARAMETERS['aux1_send_level'], 2] = (-10 * 256) & 65535
        report = {'cases': []}
        mixer_level_suite(self.device, report, lambda: None)
        skipped = [c for c in report['cases'] if c['status'] == 'skipped']
        self.assertEqual(len(skipped), 2)

    def test_all_minimum_send_levels_run_and_restore(self):
        for (field, index) in self.levels:
            if field != PARAMETERS['main_channel_level']:
                self.levels[field, index] = (-60 * 256) & 65535
        before = dict(self.levels)
        report = {'cases': []}
        mixer_level_suite(self.device, report, lambda: None)
        self.assertEqual(len(report['cases']), 45)
        sends = [c for c in report['cases'] if 'send level' in c['name']]
        self.assertEqual(len(sends), 36)
        self.assertTrue(all(c['status'] == 'passed' and c['step_db'] == 1 for c in sends))
        self.assertTrue(all(c['observed'] == [(-59 * 256) & 65535] * len(c['controls'])
                            for c in sends))
        self.assertEqual(self.levels, before)

    def test_minimum_stereo_partial_failure_restores_exact_start(self):
        for key in self.levels:
            self.levels[key] = (-60 * 256) & 65535
        before = dict(self.levels)
        original = self.device._write_and_confirm
        def reject_right(field, value, index=0):
            if field == 'aux1_send_level' and index == 3 and value == ((-59 * 256) & 65535):
                raise DeviceError('simulated upward right failure')
            return original(field, value, index)
        report = {'cases': []}
        with patch.object(self.device, '_write_and_confirm', reject_right):
            mixer_level_suite(self.device, report, lambda: None)
        failed = [c for c in report['cases'] if c['status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['restoration'], 'verified')
        self.assertEqual(self.levels, before)
