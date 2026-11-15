import unittest
from routing_labels import SOURCE_LABELS, DESTINATION_LABELS, describe_route, decoded_routes


class RoutingLabels(unittest.TestCase):
    def test_recovered_ranges_and_endpoints(self):
        self.assertEqual(len(SOURCE_LABELS), 70)
        self.assertEqual(len(DESTINATION_LABELS), 60)
        for code, label in [(64, 'Analog 1'), (79, 'Analog 16'), (80, 'ADAT 1'),
                            (95, 'ADAT 16'), (128, 'USB 1'), (154, 'USB 27'),
                            (159, 'USB 32'), (192, 'Main Mix L'), (197, 'Aux 4')]:
            self.assertEqual(SOURCE_LABELS[code], label)

    def test_unknown_codes_are_explicit(self):
        self.assertIn('Unmapped code 240', describe_route('output_source', 4, 240))
        self.assertIn('Unmapped slot 60', describe_route('output_source', 60, 160))
        self.assertEqual(describe_route('cue_destination', 0, 0), '')

    def test_user_capture_pattern_decodes_without_guessing(self):
        routes = decoded_routes({'output_source[0]': 192, 'output_source[28]': 64,
                                 'output_source[59]': 95, 'output_source[60]': 160})
        self.assertEqual(routes[0]['source_name'], 'Main Mix L')
        self.assertEqual(routes[1]['destination_native_name'], 'USB1')
        self.assertEqual(routes[1]['source_name'], 'Analog 1')
        self.assertEqual(routes[2]['source_name'], 'ADAT 16')
        self.assertIsNone(routes[3]['destination_native_name'])
        self.assertIsNone(routes[3]['source_name'])
