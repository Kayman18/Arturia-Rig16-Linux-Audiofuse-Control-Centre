import unittest
from unittest.mock import patch

from af16rig import AF16Rig, DeviceError, PARAMETERS
from level_checks import level_suite, level_group
from test_controls import FakeUSB


class LevelChecks(unittest.TestCase):
    def setUp(self):
        self.usb = FakeUSB()
        self.device = AF16Rig(self.usb)
        self.device.open()
        self.addCleanup(self.device.close)
        sleep = patch('af16rig.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)
        self.usb.values[PARAMETERS['output_link']] = 0
        self.outputs = [(-1024 - i * 128) & 65535 for i in range(8)]
        original = self.usb.libusb_control_transfer.func
        def indexed(handle, bm, req, param, index, data, length, timeout):
            if param == PARAMETERS['output_gain'][1] and req in (0x91, 0x11):
                if bm == 0x40:
                    self.outputs[index] = int.from_bytes(bytes(data), 'little')
                else:
                    value = self.outputs[index]
                    data[0], data[1] = value & 255, value >> 8
                return 2
            return original(handle, bm, req, param, index, data, length, timeout)
        self.usb.libusb_control_transfer.func = indexed

    def test_all_15_levels_restore_exact_fractional_values(self):
        before, outputs = dict(self.usb.values), list(self.outputs)
        report = {'cases': []}
        level_suite(self.device, report, lambda: None)
        self.assertEqual(report['level_checks_planned'], 15)
        self.assertTrue(all(c['status'] == 'passed' for c in report['cases']))
        self.assertEqual(self.usb.values, before)
        self.assertEqual(self.outputs, outputs)

    def test_linked_pair_tracks_automatic_partner_change(self):
        self.outputs[:2] = [64512, 64512]
        def step(direction):
            self.outputs[0] += direction * 256
            self.outputs[1] += direction * 256
        result = {}
        level_group(self.device, [('output_gain', 0), ('output_gain', 1)],
                    [step, step], None, None, result, lambda: None)
        self.assertEqual(result['observed'], [64256, 64256])
        self.assertEqual(result['final'], [64512, 64512])

    def test_changed_link_prevents_outgoing_write(self):
        result = {}
        def change():
            self.usb.values[PARAMETERS['output_link']] = 3
        with self.assertRaisesRegex(DeviceError, 'link selection changed'):
            level_group(self.device, [('output_gain', 0)],
                        [lambda d: self.device.step_output_gain(3, d)],
                        'output_link', 0, result, change)
        self.assertEqual(result['restoration'], 'verified')

    def test_floor_and_unequal_pair_skip(self):
        self.outputs[:2] = [(-60 * 256) & 65535, 0]
        result = {}
        level_group(self.device, [('output_gain', 0), ('output_gain', 1)], [],
                    None, None, result, lambda: None)
        self.assertEqual(result['status'], 'skipped')
        self.outputs[:2] = [64512, 64256]
        level_group(self.device, [('output_gain', 0), ('output_gain', 1)], [],
                    None, None, result, lambda: None)
        self.assertEqual(result['status'], 'skipped')

    def test_failure_after_applied_change_restores_original(self):
        initial = self.outputs[0]
        def step(direction):
            self.outputs[0] += direction * 256
            if direction < 0:
                raise DeviceError('simulated lost confirmation')
        record = {}
        with self.assertRaisesRegex(DeviceError, 'lost confirmation'):
            level_group(self.device, [('output_gain', 0)], [step], None, None,
                        record, lambda: None)
        self.assertEqual(self.outputs[0], initial)
        self.assertEqual(record['restoration'], 'verified')

    def test_external_value_is_preserved_and_restore_unverified(self):
        def step(direction):
            self.outputs[0] = 60000
        record = {}
        with self.assertRaisesRegex(DeviceError, 'restoration unverified'):
            level_group(self.device, [('output_gain', 0)], [step], None, None,
                        record, lambda: None)
        self.assertEqual(self.outputs[0], 60000)
        self.assertEqual(record['restoration'], 'unverified')

    def test_minimum_master_and_output_levels_restore(self):
        for name in ('main_master', 'cue_master', 'aux1_master', 'aux2_master',
                     'aux3_master', 'aux4_master', 'speaker_level'):
            self.usb.values[PARAMETERS[name]] = (-60 * 256) & 65535
        self.outputs[:] = [(-60 * 256) & 65535] * 8
        before = dict(self.usb.values)
        outputs = list(self.outputs)
        report = {'cases': []}
        level_suite(self.device, report, lambda: None)
        self.assertTrue(all(c['status'] == 'passed' and c['step_db'] == 1 for c in report['cases']))
        self.assertEqual(self.usb.values, before)
        self.assertEqual(self.outputs, outputs)

    def test_fractional_near_floor_restores(self):
        self.outputs[0] = (-60 * 256 + 128) & 65535
        result = {}
        level_group(self.device, [('output_gain', 0)],
                    [lambda d: self.device.step_output_gain(3, d)],
                    None, None, result, lambda: None)
        self.assertEqual(result['step_db'], 1)
        self.assertEqual(result['observed'], [(-59 * 256 + 128) & 65535])
        self.assertEqual(result['final'], [(-60 * 256 + 128) & 65535])

    def test_delayed_partner_restore_between_prechecks_is_accepted(self):
        self.outputs[:2] = [50176, 50176]
        reads_after_restore = [0]
        restoring = [False]
        original_read = self.device.read
        def read(field, index=0):
            if restoring[0] and field == 'output_gain' and index == 1:
                reads_after_restore[0] += 1
                if reads_after_restore[0] >= 2:
                    self.outputs[1] = 50176
            return original_read(field, index)
        def forward(direction):
            self.outputs[:2] = [50432, 50432]
        def restore_left(value):
            self.outputs[0] = value
            restoring[0] = True
        def restore_right(value):
            self.fail('Partner already restored by linked hardware')
        record = {}
        with patch.object(self.device, 'read', read):
            level_group(self.device, [('output_gain', 0), ('output_gain', 1)],
                        [forward, forward], None, None, record, lambda: None,
                        restore_writers=[restore_left, restore_right], require_all=True)
        self.assertEqual(record['status'], 'passed')
        self.assertEqual(record['final'], [50176, 50176])
        self.assertEqual(record['restoration'], 'verified')
        self.assertTrue(any(r['member'] == 1 and r['actual'] == [50176, 50176]
                            for r in record['pre_write_reads']))
