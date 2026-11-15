import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from af16rig import AF16Rig,DeviceError
from device_presets import rename_preset
from test_preset_name_tail import InPlaceNamesUSB
from test_preset_rename import RenameUSB
import test_presets_window as page_fixture

class RenameReportTests(unittest.TestCase):
    def test_capture_stays_inside_preset_field(self):
        usb=InPlaceNamesUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close)
        with patch('device_presets.time.sleep'):rename_preset(d,3,'MergedFronts','abcdefghijkl')
        report=d.last_preset_rename
        self.assertEqual(report['requested_name'],'MergedFronts')
        self.assertEqual(report['payload_bytes'],12);self.assertEqual(report['write_requests'],1)
        self.assertEqual(len(bytes.fromhex(report['storage_after']['passes'][0]['hex'])),12)
        self.assertTrue(report['confirmed']);self.assertTrue(report['storage_after']['stable'])
        self.assertNotIn(b'et3',bytes.fromhex(report['storage_after']['passes'][0]['hex']))
    def test_failed_rename_retains_requested_and_actual_names(self):
        usb=RenameUSB();usb.ignore_rename=True;d=AF16Rig(usb);d.open();self.addCleanup(d.close)
        with patch('device_presets.time.sleep'):
            with self.assertRaisesRegex(DeviceError,"requested 'New', received 'Preset 3'"):
                rename_preset(d,3,'New','Preset 3')
        self.assertFalse(d.last_preset_rename['confirmed'])
        self.assertEqual(len(usb.rename_out),1)
    def test_failed_report_can_be_exported_with_current_display(self):
        p=page_fixture.PresetPageTests().page()
        report={'requested_name':'MergedFronts','out_result':16,'write_requests':1}
        p.handle(dict(kind='preset_error',request_id=100,connection_serial=4,message='not confirmed',rename_report=report))
        self.assertEqual(p.app.last_preset_rename_report,report)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            with patch('presets_window.filedialog.asksaveasfilename',return_value=str(path)):p.save_rename_report()
            saved=json.loads(path.read_text());self.assertEqual(saved['requested_name'],'MergedFronts')
            self.assertIn('current_records',saved)

if __name__=='__main__':unittest.main()
