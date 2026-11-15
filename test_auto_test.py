import unittest
from unittest.mock import patch

from af16rig import AF16Rig, DeviceError, PARAMETERS
from auto_test import hardware_suite, pan_case
from test_controls import FakeUSB


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.usb = FakeUSB()
        self.device = AF16Rig(self.usb)
        sleeper = patch('af16rig.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.addCleanup(self.device.close)

    def run_pan(self):
        self.device.open()
        record = {}
        pan_case(self.device, 'cue', record, lambda: None)
        return record

    def test_both_buses_exact_restore_including_right_edge(self):
        self.usb.values[PARAMETERS['cue_channel_pan']] = 254
        report = {'cases': []}
        hardware_suite(self.device, report, lambda: None)
        self.assertEqual([(c['observed'], c['final']) for c in report['cases'] if c['status'] == 'passed'],
                         [(1, 0), (253, 254)])
        self.assertTrue(self.usb.closed)
        self.assertEqual(len([c for c in self.usb.calls if c[0] == 0x40]), 4)

    def test_stereo_only_skip(self):
        self.usb.values[PARAMETERS['cue_channel_stereo']] = 255
        self.assertEqual(self.run_pan()['status'], 'skipped')
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_ignored_write_fails_and_stops_next_case(self):
        self.usb.ignore_writes = True
        report = {'cases': []}
        with self.assertRaises(DeviceError):
            hardware_suite(self.device, report, lambda: None)
        self.assertEqual(len(report['cases']), 1)
        self.assertEqual(report['cases'][0]['restoration'], 'verified')
        self.assertTrue(self.usb.closed)

    def test_external_move_to_target_before_write_preserved(self):
        self.device.open()
        def move():
            self.usb.values[PARAMETERS['cue_channel_pan']] = 1
        with self.assertRaises(DeviceError):
            pan_case(self.device, 'cue', {}, move)
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_disconnected_before_restore_reports_unverified(self):
        self.device.open()
        original = self.device.adjust_channel_pan
        def disconnect(*args, **kwargs):
            value = original(*args, **kwargs)
            self.device.close()
            return value
        record = {}
        with patch.object(self.device, 'adjust_channel_pan', disconnect):
            with self.assertRaises(DeviceError):
                pan_case(self.device, 'cue', record, lambda: None)
        self.assertEqual(record['restoration'], 'unverified')
        self.assertEqual(record['start'], 0)

    def test_read_only_stereo_pair_and_empty_cue(self):
        from auto_test import inspect_mixer
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_show']] = 1
        self.usb.values[PARAMETERS['main_channel_stereo']] = 2
        self.usb.values[PARAMETERS['main_channel_solo']] = 4
        self.usb.values[PARAMETERS['cue_channel_show']] = 0
        report = {}
        inspect_mixer(self.device, report)
        strips = report['strips']['main']
        self.assertEqual([(s['source'], s['mode'], s['solo_bit']) for s in strips],
                         [(1, 'mono', 0), (3, 'stereo', 1), (4, 'stereo', 0)])
        self.assertEqual(strips[1]['level_db'], -12)
        self.assertEqual(report['strips']['cue'], [])
        self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))

    def test_current_routing_and_all_skipped_distinguished(self):
        from auto_test import batch_status
        self.usb.values[PARAMETERS['cue_channel_show']] = 0
        for mask, status in [(1, 'passed_with_skips'), (0, 'read_only_passed')]:
            self.usb.values[PARAMETERS['main_channel_show']] = mask
            report = {'cases': []}
            hardware_suite(self.device, report, lambda: None)
            self.assertEqual(batch_status(report['cases']), status)
            self.assertEqual(report['mixer_readback'], 'passed')

    def test_read_failure_aborts_before_any_out_request(self):
        original = self.device.read
        def read(name, index=0):
            if name == 'aux2_master':
                raise DeviceError('simulated read error')
            return original(name, index)
        with patch.object(self.device, 'read', read):
            with self.assertRaisesRegex(DeviceError, 'aux2 master'):
                hardware_suite(self.device, {'cases': []}, lambda: None)
        self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))

    def test_level_check_preserves_fractional_fader_on_muted_mono_source(self):
        self.usb.values[PARAMETERS['main_channel_mute']] = 2
        self.usb.values[PARAMETERS['main_channel_level']] = (-1152) & 65535
        report = {'cases': []}
        hardware_suite(self.device, report, lambda: None)
        result = next(c for c in report['cases'] if c['name'] == 'main muted mono level')
        self.assertEqual((result['source'], result['start_db'], result['target_db']), (2, -4.5, -5.5))
        self.assertEqual(result['observed'], (-1408) & 65535)
        self.assertEqual(result['final'], result['start'])
        self.assertEqual(result['restoration'], 'verified')

    def test_level_skips_floor_and_stereo(self):
        from auto_test import level_case
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_mute']] = 15
        self.usb.values[PARAMETERS['main_channel_stereo']] = 1
        self.usb.values[PARAMETERS['main_channel_level']] = (-60 * 256) & 65535
        record = {}
        level_case(self.device, 'main', record, lambda: None)
        self.assertEqual(record['status'], 'skipped')
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_level_rechecks_mute_before_writing(self):
        from auto_test import level_case
        self.device.open()
        mute = PARAMETERS['main_channel_mute']
        self.usb.values[mute] = 1
        def unmute():
            self.usb.values[mute] = 0
        with self.assertRaisesRegex(DeviceError, 'no longer muted'):
            level_case(self.device, 'main', {}, unmute)
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_all_four_muted_sends_restore_fractional_raw_levels(self):
        for aux in range(1, 5):
            self.usb.values[PARAMETERS[f'main_channel_send{aux}']] = 1
            self.usb.values[PARAMETERS[f'aux{aux}_send_level']] = (-7219) & 65535
        report = {'cases': []}
        hardware_suite(self.device, report, lambda: None)
        results = [c for c in report['cases'] if 'Aux' in c['name']]
        self.assertEqual(len(results), 4)
        for result in results:
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['observed'], (-7475) & 65535)
            self.assertEqual(result['final'], (-7219) & 65535)
            self.assertEqual(result['restoration'], 'verified')

    def test_strip_mute_does_not_qualify_unmuted_send(self):
        from auto_test import level_case
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_mute']] = 65535
        result = {}
        level_case(self.device, 'main', result, lambda: None, aux=1)
        self.assertEqual(result['status'], 'skipped')
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_send_unmuted_during_checkpoint_refuses_write(self):
        from auto_test import level_case
        self.device.open()
        field = PARAMETERS['main_channel_send2']
        self.usb.values[field] = 1
        def unmute():
            self.usb.values[field] = 0
        with self.assertRaisesRegex(DeviceError, 'no longer muted'):
            level_case(self.device, 'main', {}, unmute, aux=2)
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_large_button_batch_restores_every_register(self):
        from auto_test import button_suite
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_show']] = 3
        self.usb.values[PARAMETERS['cue_channel_show']] = 0
        self.usb.values[PARAMETERS['main_channel_mute']] = 1
        before = dict(self.usb.values)
        report = {'cases': []}
        button_suite(self.device, report, lambda: None)
        self.assertEqual(report['button_checks_planned'], 24)
        self.assertEqual(len(report['cases']), 24)
        self.assertTrue(all(c['status'] == 'passed' and c['restoration'] == 'verified'
                            for c in report['cases']))
        self.assertEqual(self.usb.values, before)

    def test_button_write_ignored_stops_batch_and_restores(self):
        from auto_test import button_suite
        self.device.open()
        self.usb.ignore_writes = True
        report = {'cases': []}
        with self.assertRaises(DeviceError):
            button_suite(self.device, report, lambda: None)
        self.assertEqual(len(report['cases']), 1)
        self.assertEqual(report['cases'][0]['status'], 'failed')
        self.assertEqual(report['cases'][0]['restoration'], 'verified')

    def test_button_checkpoint_external_change_not_overwritten(self):
        from auto_test import button_case
        self.device.open()
        def change():
            self.usb.values[PARAMETERS['mute']] = 1
        with self.assertRaises(DeviceError):
            button_case(self.device, 'mute', None,
                        lambda value: self.device.write_bool('mute', value), {}, change)
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_full_current_routing_runs_66_buttons_and_restores(self):
        from auto_test import button_suite
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_show']] = 3
        self.usb.values[PARAMETERS['main_channel_stereo']] = 254
        self.usb.values[PARAMETERS['cue_channel_show']] = 0
        self.usb.values[PARAMETERS['main_channel_mute']] = 1 | (3 << 2) | (3 << 6)
        before = dict(self.usb.values)
        report = {'cases': []}
        button_suite(self.device, report, lambda: None)
        self.assertEqual(report['button_checks_planned'], 66)
        self.assertEqual(len(report['cases']), 66)
        self.assertTrue(all(c['status'] == 'passed' for c in report['cases']))
        self.assertEqual(self.usb.values, before)

    def test_stereo_mixed_initial_buttons_skip_without_writes(self):
        from auto_test import button_case
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_mute']] = 4
        record = {}
        button_case(self.device, 'main_channel_mute', (2, 3),
                    lambda v: self.device.write_stereo_channel_switch('main', 3, 'mute', v),
                    record, lambda: None)
        self.assertEqual(record['status'], 'skipped')
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_stereo_second_member_failure_restores_first_member(self):
        from auto_test import button_case
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_show']] = 0
        self.usb.values[PARAMETERS['main_channel_stereo']] = 2
        original = self.device._write_and_confirm
        def fail_second(name, value, index=0):
            if index == 3 and value == 1:
                raise DeviceError('second member failed')
            return original(name, value, index)
        record = {}
        with patch.object(self.device, '_write_and_confirm', fail_second):
            with self.assertRaisesRegex(DeviceError, 'second member'):
                button_case(self.device, 'main_channel_mute', (2, 3),
                            lambda v: self.device.write_stereo_channel_switch('main', 3, 'mute', v),
                            record, lambda: None)
        self.assertEqual(record['restoration'], 'verified')
        self.assertEqual(record['restore_from'], 1)
        self.assertEqual(self.usb.values[PARAMETERS['main_channel_mute']], 0)

    def test_stereo_topology_change_stops_without_writes(self):
        from auto_test import button_case
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_show']] = 0
        self.usb.values[PARAMETERS['main_channel_stereo']] = 2
        def unlink():
            self.usb.values[PARAMETERS['main_channel_stereo']] = 0
        record = {}
        with self.assertRaisesRegex(DeviceError, 'Pair selection changed'):
            button_case(self.device, 'main_channel_mute', (2, 3),
                        lambda v: self.device.write_stereo_channel_switch('main', 3, 'mute', v),
                        record, unlink)
        self.assertEqual(record['restoration'], 'verified')
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_linked_hardware_changes_both_sides_on_first_write(self):
        from auto_test import button_case
        self.device.open()
        self.usb.values[PARAMETERS['main_channel_show']] = 0
        self.usb.values[PARAMETERS['main_channel_stereo']] = 2
        field = 'main_channel_mute'
        self.usb.values[PARAMETERS[field]] = 12
        original = self.usb.libusb_control_transfer.func
        def linked(handle, bm, req, param, index, data, length, timeout):
            result = original(handle, bm, req, param, index, data, length, timeout)
            if bm == 0x40 and req == 0x11 and param == PARAMETERS[field][1]:
                value = int.from_bytes(bytes(data), 'little')
                self.usb.values[PARAMETERS[field]] = 12 if value else 0
            return result
        self.usb.libusb_control_transfer.func = linked
        record = {}
        button_case(self.device, field, (2, 3),
                    lambda v: self.device.write_stereo_channel_switch('main', 3, 'mute', v),
                    record, lambda: None)
        self.assertEqual(record['status'], 'passed')
        self.assertEqual(record['observed'], 0)
        self.assertEqual(record['final'], 3)
        self.assertEqual(len(record['write_diagnostic']['transactions']), 1)
        self.assertEqual(record['restoration'], 'verified')
        self.assertEqual(self.usb.values[PARAMETERS[field]], 12)

    def prepare_input_registers(self):
        for name in ('rear_link', 'front_line_link', 'front_mic_link', 'rear_phase',
                     'rear_hpf', 'rear_pad', 'front_line_phase', 'front_line_hpf',
                     'front_line_pad', 'front_mic_phase', 'front_mic_hpf', 'front_mic_pad', 'front_line_instrument'):
            self.usb.values[PARAMETERS[name]] = 0
        self.usb.values[PARAMETERS['force_rear']] = 15
        original = self.usb.libusb_control_transfer.func
        fields = {PARAMETERS[name] for name in ('rear_phase', 'rear_hpf', 'rear_pad',
                  'front_line_phase', 'front_line_hpf', 'front_line_pad',
                  'front_mic_phase', 'front_mic_hpf', 'front_mic_pad', 'front_line_instrument')}
        def packed(handle, bm, req, param, index, data, length, timeout):
            key = (req - 0x10, param)
            before = self.usb.values.get(key, 0)
            result = original(handle, bm, req, param, index, data, length, timeout)
            if bm == 0x40 and key in fields:
                value = int.from_bytes(bytes(data), 'little')
                self.usb.values[key] = before | (1 << index) if value else before & ~(1 << index)
            return result
        self.usb.libusb_control_transfer.func = packed

    def test_input_batch_tests_48_controls_and_restores_active_low_pad(self):
        from input_checks import input_button_checks
        from auto_test import button_case
        self.prepare_input_registers()
        self.device.open()
        before = dict(self.usb.values)
        checks = input_button_checks(self.device)
        self.assertEqual(len(checks), 48)
        for name, field, bit, writer in checks:
            if writer is None:
                continue
            record = {}
            button_case(self.device, field, bit, writer, record, lambda: None)
            self.assertEqual(record['status'], 'passed', name)
            self.assertEqual(record['observed'], 1, name)
        self.assertEqual(self.usb.values, before)

    def test_front_source_and_linked_rear_planning(self):
        from input_checks import input_button_checks
        self.prepare_input_registers()
        self.device.open()
        self.usb.values[PARAMETERS['force_rear']] = 0
        self.usb.values[PARAMETERS['detect_status']] = 1 | 64 | 16
        self.usb.values[PARAMETERS['rear_link']] = 3 << 4
        checks = input_button_checks(self.device)
        self.assertEqual(len(checks), 45)
        fields = [field for _, field, _, _ in checks]
        self.assertIn('front_mic_pad', fields)
        self.assertIn('front_line_hpf', fields)
        self.assertIn((4, 5), [bit for _, _, bit, _ in checks])
        from auto_test import button_case
        before = dict(self.usb.values)
        for name, field, bit, writer in checks:
            if writer is None:
                continue
            record = {}
            button_case(self.device, field, bit, writer, record, lambda: None)
            self.assertEqual(record['status'], 'passed', name)
        self.assertEqual(self.usb.values, before)

    def test_input_source_change_refuses_write(self):
        from input_checks import input_button_checks
        from auto_test import button_case
        self.prepare_input_registers()
        self.device.open()
        _, field, bit, writer = input_button_checks(self.device)[0]
        def move_source():
            self.usb.values[PARAMETERS['force_rear']] = 0
            self.usb.values[PARAMETERS['detect_status']] = 1
        with self.assertRaisesRegex(DeviceError, 'selection changed'):
            button_case(self.device, field, bit, writer, {}, move_source)
        self.assertFalse(any(c[0] == 0x40 for c in self.usb.calls))

    def test_restored_input_failure_collects_remaining_cases_and_stays_failed(self):
        from auto_test import button_suite, batch_status
        self.prepare_input_registers()
        self.device.open()
        original = self.device.write_input_bool
        def reject_first(channel, name, value):
            if channel == 1 and name == 'phase' and value:
                raise DeviceError('simulated unavailable phase')
            return original(channel, name, value)
        report = {'cases': []}
        with patch.object(self.device, 'write_input_bool', reject_first):
            button_suite(self.device, report, lambda: None, inputs=True)
        inputs = [c for c in report['cases'] if ' input ' in c['name']]
        self.assertEqual(len(inputs), 48)
        self.assertEqual(inputs[0]['status'], 'failed')
        self.assertEqual(inputs[0]['restoration'], 'verified')
        self.assertTrue(inputs[0]['continued_after_verified_restore'])
        self.assertTrue(all(c['status'] == 'passed' for c in inputs[1:]))
        self.assertEqual(batch_status(report['cases']), 'failed')

    def test_reported_setup_runs_95_buttons_and_labels_seven_unresolved(self):
        from auto_test import button_suite
        self.prepare_input_registers()
        self.device.open()
        self.usb.values[PARAMETERS['force_rear']] = 0
        self.usb.values[PARAMETERS['detect_status']] = 33
        self.usb.values[PARAMETERS['rear_link']] = 65532
        self.usb.values[PARAMETERS['main_channel_show']] = 3
        self.usb.values[PARAMETERS['main_channel_stereo']] = 254
        self.usb.values[PARAMETERS['cue_channel_show']] = 0
        before = dict(self.usb.values)
        report = {'cases': []}
        button_suite(self.device, report, lambda: None, inputs=True)
        self.assertEqual(report['button_checks_planned'], 102)
        self.assertEqual(sum(c['status'] == 'passed' for c in report['cases']), 95)
        skipped = [c for c in report['cases'] if c['status'] == 'skipped']
        self.assertEqual(len(skipped), 7)
        self.assertTrue(all('linked right' in c['name'] for c in skipped))
        self.assertEqual(self.usb.values, before)

    def test_focused_hardware_check_runs_only_named_case(self):
        report = {'cases': []}
        hardware_suite(self.device, report, lambda: None, buttons=True,
                       only=['MAIN 1 SOLO'])
        self.assertEqual([c['name'] for c in report['cases']], ['main 1 solo'])
        writes = [call for call in self.usb.calls if call[0] == 0x40]
        self.assertEqual(len(writes), 2)
        self.assertTrue(all(call[2] == PARAMETERS['main_channel_solo'][1] for call in writes))
        self.assertEqual(report['cases'][0]['restoration'], 'verified')

    def test_unmatched_selector_does_not_pass_or_write(self):
        from auto_test import batch_status
        report = {'cases': []}
        hardware_suite(self.device, report, lambda: None, buttons=True, only=['no such control'])
        self.assertEqual(report['cases'], [])
        self.assertEqual(batch_status(report['cases']), 'no_matching_checks')
        self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))

    def test_repeated_selectors_choose_union(self):
        from check_selection import case_selected
        self.assertTrue(case_selected('Main 3/4 Aux 2 send mute', ['main 3/4', 'speaker level']))
        self.assertTrue(case_selected('Speaker level', ['main 3/4', 'speaker level']))
        self.assertFalse(case_selected('Cue enable', ['main 3/4', 'speaker level']))
