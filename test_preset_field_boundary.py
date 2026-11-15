import unittest
from unittest.mock import patch
from af16rig import AF16Rig
from device_presets import read_slot,encode_preset_name
from test_device_presets import PresetUSB

class PresetFieldBoundaryTests(unittest.TestCase):
    def test_actual_report_bytes_decode_without_next_preset(self):
        raw=bytes.fromhex('4d657267656446726f6e74735072657365743300000000005072657365743400')
        d=AF16Rig(PresetUSB());d.open();self.addCleanup(d.close)
        def word(device,parameter,index):return int.from_bytes(raw[2*index:2*index+2],'little')
        with patch('device_presets.read_word',side_effect=word) as reader:
            result=read_slot(d,2)
        self.assertEqual(result['name'],'MergedFronts')
        self.assertEqual([c.args[2] for c in reader.call_args_list],list(range(6))*2)
        self.assertEqual(len(result['words']),6)
    def test_twelve_bytes_supported_without_extra_terminator(self):
        self.assertEqual(encode_preset_name('MergedFronts'),b'MergedFronts')
        self.assertEqual(encode_preset_name('é'*6),('é'*6).encode())
        self.assertEqual(encode_preset_name('Main'),b'Main'+b'\0'*8)
    def test_overlength_not_silently_truncated(self):
        for name in ('x'*13,'é'*7,'MergedFrontsPreset3'):
            with self.assertRaisesRegex(ValueError,'12-byte'):encode_preset_name(name)

if __name__=='__main__':unittest.main()
