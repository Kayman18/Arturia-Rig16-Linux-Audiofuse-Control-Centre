import queue
import unittest
from unittest.mock import patch
from af16rig import AF16Rig, DemoAF16Rig, DeviceError, DeviceDisconnected
from af16rig_gui import Worker
from device_presets import read_status, read_slot, operate
from test_controls import FakeUSB, Fn


class PresetUSB(FakeUSB):
    def __init__(self):
        super().__init__()
        self.current = 2; self.changed = 1; self.out = []; self.result = 1
        self.ignore = False; self.read_size = 2; self.names = {s: f'Preset {s}' for s in range(1, 9)}
        original = self.libusb_control_transfer
        def transfer(h, bm, req, param, index, data, length, timeout):
            if req == 0x93 and 8 <= param <= 17:
                if param < 10:
                    value = self.current if param == 8 else self.changed
                    data[0:2] = value.to_bytes(2, 'little')
                else:
                    raw = (self.names[param-9].encode() + b'\0').ljust(32, b'\0')
                    data[0:2] = raw[2*index:2*index+2]
                return self.read_size
            if req == 0x48:
                self.out.append((bm, req, param, index, bytes(data), length, timeout))
                if not self.ignore: self.current = index; self.changed = 0
                return self.result
            return original(h, bm, req, param, index, data, length, timeout)
        self.libusb_control_transfer = Fn(transfer)


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.usb = PresetUSB(); self.device = AF16Rig(self.usb); self.device.open()
        self.addCleanup(self.device.close)
        sleeper = patch('device_presets.time.sleep'); sleeper.start(); self.addCleanup(sleeper.stop)

    def action(self, action='load', slot=3, **kw):
        return operate(self.device, action, slot, 'Factory' if slot == 0 else self.usb.names[slot],
                       dict(current=2, changed=1), **kw)

    def test_read_all_slots_never_writes(self):
        self.assertEqual(read_status(self.device), dict(current=2, changed=1))
        self.assertEqual([read_slot(self.device, s)['name'] for s in range(9)], ['Factory']+[f'Preset {s}' for s in range(1, 9)])
        self.assertFalse(self.usb.out)

    def test_native_load_wire_packet(self):
        result = self.action()
        self.assertEqual(self.usb.out, [(0x40, 0x48, 0, 3, b'\0', 1, 1000)])
        self.assertEqual(result['status'], dict(current=3, changed=0))

    def test_native_save_wire_packet(self):
        self.action('save', 8)
        self.assertEqual(self.usb.out, [(0x40, 0x48, 1, 8, b'\0', 1, 1000)])

    def test_factory_load_allowed(self):
        self.action('load', 0); self.assertEqual(self.usb.out[0][2:4], (0, 0))

    def test_factory_save_and_invalid_slots_blocked(self):
        for action, slot in [('save', 0), ('load', -1), ('load', 9), ('save', True), ('erase', 1)]:
            with self.assertRaises(ValueError): operate(self.device, action, slot, '', {})
        self.assertFalse(self.usb.out)

    def test_stale_status_or_name_never_writes(self):
        with self.assertRaisesRegex(DeviceError, 'state changed'):
            operate(self.device, 'save', 3, 'Preset 3', dict(current=1, changed=0))
        with self.assertRaisesRegex(DeviceError, 'name changed'):
            operate(self.device, 'save', 3, 'Old name', dict(current=2, changed=1))
        self.assertFalse(self.usb.out)

    def test_invalid_status_blocks_action(self):
        for current, changed in [(9, 0), (65535, 0), (1, 2)]:
            self.usb.current = current; self.usb.changed = changed
            with self.assertRaises(DeviceError): self.action()
        self.assertFalse(self.usb.out)

    def test_short_read_blocks_write(self):
        self.usb.read_size = 1
        with self.assertRaises(DeviceError): self.action('save')
        self.assertFalse(self.usb.out)

    def test_unknown_version_blocks_write(self):
        self.device.version = 19
        with self.assertRaises(DeviceError): self.action('save')
        self.assertFalse(self.usb.out)

    def test_ignored_operation_not_confirmed_or_retried(self):
        self.usb.ignore = True
        with self.assertRaisesRegex(DeviceError, 'not confirmed'): self.action()
        self.assertEqual(len(self.usb.out), 1)

    def test_uncertain_out_never_claims_success_even_matching_status(self):
        for result in (-7, -9, 0):
            self.usb.result = result; self.usb.current = 2; self.usb.changed = 1
            with self.assertRaisesRegex(DeviceError, 'not confirmed'): self.action()
        self.assertEqual(len(self.usb.out), 3)

    def test_disconnect_not_retried(self):
        self.usb.result = -4
        with self.assertRaises(DeviceDisconnected): self.action()
        self.assertEqual(len(self.usb.out), 1)

    def test_invalidation_only_after_preflight(self):
        attempts = []
        self.usb.ignore = True
        with self.assertRaises(DeviceError): self.action(on_attempt=lambda: attempts.append(1))
        self.assertEqual(attempts, [1])
        self.usb.current = 7
        with self.assertRaises(DeviceError): self.action(on_attempt=lambda: attempts.append(1))
        self.assertEqual(attempts, [1])

    def test_blank_and_utf8_names(self):
        for value in ('', 'Synthé'):
            self.usb.names[3] = value
            self.assertEqual(read_slot(self.device, 3)['name'], value)

    def test_unterminated_name_rejected(self):
        self.usb.names[3] = 'x'*32
        with self.assertRaises(DeviceError): self.action()
        self.assertFalse(self.usb.out)

    def test_demo_uses_no_usb(self):
        d = DemoAF16Rig()
        result = operate(d, 'save', 8, 'Demo preset 8', read_status(d))
        self.assertTrue(result['demo']); self.assertEqual(result['write_requests'], 0)

    def worker_event(self, command, wanted):
        events = queue.Queue(); w = Worker(events, factory=lambda: AF16Rig(self.usb)); w.start()
        self.addCleanup(lambda: (w.stop_event.set(), w.join(2)))
        w.commands.put(('connect', None)); w.commands.put(command)
        seen = []
        while True:
            event = events.get(timeout=3); seen.append(event)
            if event['kind'] == wanted: return seen

    def test_worker_old_connection_rejected(self):
        events = self.worker_event(('preset_action', dict(connection_serial=0, request_id=12)), 'preset_error')
        self.assertEqual(events[-1]['request_id'], 12); self.assertFalse(self.usb.out)

    def test_worker_load_invalidates_caches_before_completion(self):
        events = self.worker_event(('preset_action', dict(connection_serial=1, request_id=14, action='load', slot=3,
                                 expected_name='Preset 3', expected_status=dict(current=2, changed=1))), 'preset_done')
        self.assertIn('preset_state_reset', [e['kind'] for e in events])
        self.assertEqual(events[-1]['result']['slot'], 3)

    def test_worker_save_does_not_reset_live_state(self):
        events = self.worker_event(('preset_action', dict(connection_serial=1, request_id=15, action='save', slot=3,
                                 expected_name='Preset 3', expected_status=dict(current=2, changed=1))), 'preset_done')
        self.assertNotIn('preset_state_reset', [e['kind'] for e in events])


if __name__ == '__main__': unittest.main()
