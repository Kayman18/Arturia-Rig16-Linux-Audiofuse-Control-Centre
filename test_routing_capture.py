import unittest
from unittest.mock import patch

from af16rig import AF16Rig, DeviceError, PARAMETERS, ROUTING_FIELDS
from routing_capture import capture, compare
from test_controls import FakeUSB


class RoutingCaptureTests(unittest.TestCase):
    def setUp(self):
        self.usb = FakeUSB()
        for field in ROUTING_FIELDS:
            self.usb.values[PARAMETERS[field]] = 0
        self.device = AF16Rig(self.usb)

    def test_capture_is_complete_and_read_only(self):
        report = capture(self.device)
        self.assertEqual(report['status'], 'stable')
        self.assertEqual(len(report['reads']['second']['values']), 73)
        self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))
        self.assertTrue(self.usb.closed)
        self.assertTrue(any(call[2:4] == (64, 61) for call in self.usb.calls))
        self.assertTrue(any(call[2:4] == (94, 3) for call in self.usb.calls))

    def test_routing_fields_remain_outside_write_whitelist(self):
        self.device.open()
        try:
            for field in ROUTING_FIELDS:
                with self.assertRaises(ValueError):
                    self.device._write_and_confirm(field, 1)
        finally:
            self.device.close()
        self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))

    def test_field_error_is_partial_and_cannot_compare(self):
        original = self.device.read
        def read(name, index=0):
            if name == 'output_source' and index == 20:
                raise DeviceError('unavailable slot')
            return original(name, index)
        with patch.object(self.device, 'read', read):
            report = capture(self.device)
        self.assertEqual(report['status'], 'partial')
        self.assertIn('output_source[20]', report['reads']['second']['errors'])
        with self.assertRaises(ValueError):
            compare(report, report)

    def test_comparison_identifies_changed_registers_without_guessing_names(self):
        before = capture(self.device)
        self.usb.values[PARAMETERS['cue_destination']] = 7
        after = capture(self.device)
        result = compare(before, after)
        self.assertEqual(result['compared'], 73)
        self.assertEqual(result['changes']['cue_destination[0]'], {'before': 0, 'after': 7})
        self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))

    def test_open_connection_capture_keeps_device_available(self):
        from routing_capture import read_routing
        self.device.open()
        result = read_routing(self.device)
        self.assertEqual(result['status'], 'stable')
        self.assertFalse(self.usb.closed)
        self.assertEqual(self.device.read('mute'), 0)
        self.device.close()

    def test_worker_routes_capture_and_remains_connected(self):
        import queue
        from af16rig_gui import Worker
        events = queue.Queue()
        worker = Worker(events, factory=lambda: self.device)
        worker.start()
        try:
            worker.commands.put(('connect', None))
            while events.get(timeout=3)['kind'] != 'connected':
                pass
            worker.commands.put(('routing_capture', 42))
            while True:
                event = events.get(timeout=3)
                if event['kind'] == 'routing_snapshot':
                    break
                self.assertNotIn(event['kind'], ('error', 'routing_error'))
            self.assertEqual(event['request_id'], 42)
            self.assertEqual(event['state']['status'], 'stable')
            self.assertFalse(self.usb.closed)
            self.assertFalse(any(call[0] == 0x40 for call in self.usb.calls))
        finally:
            worker.stop_event.set()
            worker.join(timeout=3)

    def test_demo_cannot_be_compared_with_hardware(self):
        before = capture(self.device)
        after = dict(before, demo=True)
        with self.assertRaisesRegex(ValueError, 'Demo and hardware'):
            compare(before, after)

    def test_gui_exports_valid_routing_json(self):
        import json
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock
        from routing_window import RoutingWindow
        window = RoutingWindow.__new__(RoutingWindow)
        window.pending = False
        window.state = capture(self.device)
        window.app = SimpleNamespace(demo=False)
        window.message = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'routing.json'
            with patch('routing_window.filedialog.asksaveasfilename', return_value=str(path)):
                window.save()
            report = json.loads(path.read_text())
            self.assertEqual(report['status'], 'stable')
            self.assertFalse(report['demo'])
