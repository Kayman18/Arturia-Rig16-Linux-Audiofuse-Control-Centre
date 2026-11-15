import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from device_presets import rename_preset,read_slot
from test_controls import Fn
from test_device_presets import PresetUSB
import test_device_presets as fixtures


class RenameUSB(PresetUSB):
    def __init__(self):
        super().__init__();self.rename_out=[];self.rename_rc=None;self.ignore_rename=False
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            if req==0x1b:
                self.rename_out.append((bm,req,param,index,bytes(data),length))
                if not self.ignore_rename:self.names[param-9]=bytes(data).rstrip(b'\0').decode('utf-8')
                return length if self.rename_rc is None else self.rename_rc
            return original(h,bm,req,param,index,data,length,timeout)
        self.libusb_control_transfer=Fn(transfer)


class PresetRenameTests(unittest.TestCase):
    worker_event=fixtures.PresetTests.worker_event

    def setUp(self):
        self.usb=RenameUSB();self.device=AF16Rig(self.usb);self.device.open();self.addCleanup(self.device.close)
        sleeper=patch('device_presets.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)

    def test_all_eight_slots_exact_packets_and_no_content_operations(self):
        for slot in range(1,9):
            result=rename_preset(self.device,slot,f'Set {slot}',f'Preset {slot}')
            self.assertEqual(result['record']['name'],f'Set {slot}')
            self.assertEqual(self.usb.rename_out[-1],(0x40,0x1b,slot+9,0,(f'Set {slot}'.encode()+b'\0').ljust(12,b'\0'),12))
        self.assertFalse(self.usb.out)
        self.assertEqual((self.usb.current,self.usb.changed),(2,1))

    def test_factory_invalid_slots_and_unknown_version_rejected(self):
        for slot in (0,-1,9,True):
            with self.assertRaises(ValueError):rename_preset(self.device,slot,'New','Old')
        self.device.version=19
        with self.assertRaises(DeviceError):rename_preset(self.device,1,'New','Preset 1')
        self.assertFalse(self.usb.rename_out)

    def test_stale_name_prevents_overwrite(self):
        with self.assertRaisesRegex(DeviceError,'name changed'):rename_preset(self.device,2,'New','Old')
        self.assertFalse(self.usb.rename_out)

    def test_identical_name_no_write(self):
        self.assertEqual(rename_preset(self.device,1,'Preset 1','Preset 1')['write_requests'],0)
        self.assertFalse(self.usb.rename_out)

    def test_utf8_and_blank_names_roundtrip(self):
        rename_preset(self.device,1,'Synthé','Preset 1')
        self.assertEqual(read_slot(self.device,1)['name'],'Synthé')
        rename_preset(self.device,1,'','Synthé')
        self.assertEqual(read_slot(self.device,1)['name'],'')

    def test_oversize_and_control_characters_rejected(self):
        for value in ('x'*16,'é'*8,'Bad\nname','Bad\0name'):
            with self.assertRaises(ValueError):rename_preset(self.device,1,value,'Preset 1')
        self.assertFalse(self.usb.rename_out)

    def test_unconfirmed_write_never_retried(self):
        self.usb.ignore_rename=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):rename_preset(self.device,1,'New','Preset 1')
        self.assertEqual(len(self.usb.rename_out),1)

    def test_uncertain_out_with_matching_name_is_confirmed_by_readback(self):
        self.usb.rename_rc=-7
        self.assertEqual(rename_preset(self.device,1,'New','Preset 1')['record']['name'],'New')
        self.assertEqual(len(self.usb.rename_out),1)

    def test_disconnect_never_retries(self):
        self.usb.rename_rc=-4
        with self.assertRaises(DeviceDisconnected):rename_preset(self.device,1,'New','Preset 1')
        self.assertEqual(len(self.usb.rename_out),1)

    def test_demo_persists_name_in_session_only(self):
        d=DemoAF16Rig();rename_preset(d,8,'Studio','Demo preset 8')
        self.assertEqual(read_slot(d,8)['name'],'Studio')
        self.assertEqual(read_slot(DemoAF16Rig(),8)['name'],'Demo preset 8')

    def test_worker_old_connection_rejected(self):
        events=self.worker_event(('preset_rename',dict(connection_serial=0,request_id=20)),'preset_error')
        self.assertEqual(events[-1]['request_id'],20);self.assertFalse(self.usb.rename_out)

    def test_worker_returns_readback_and_leaves_active_state_alone(self):
        events=self.worker_event(('preset_rename',dict(connection_serial=1,request_id=21,slot=2,name='Studio',expected_name='Preset 2')),'preset_renamed')
        self.assertEqual(events[-1]['result']['record']['name'],'Studio')
        self.assertNotIn('preset_state_reset',[e['kind'] for e in events])


if __name__=='__main__':unittest.main()
