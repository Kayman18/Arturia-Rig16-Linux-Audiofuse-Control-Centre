import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DeviceError
from device_presets import read_slot,rename_preset
from test_preset_rename import RenameUSB
from test_controls import Fn

class InPlaceNamesUSB(RenameUSB):
    """Word-wise firmware copies, retaining bytes beyond the write length."""
    def __init__(self):
        super().__init__()
        self.buffers={i:bytearray((b'abcdefghijkl'+b'preset3').ljust(32,b'\0')) for i in range(1,9)}
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            if req==0x93 and 10<=param<=17:
                data[:2]=self.buffers[param-9][2*index:2*index+2];return 2
            if req==0x1b:
                self.rename_out.append((bm,req,param,index,bytes(data),length))
                amount=length//2*2
                self.buffers[param-9][:amount]=bytes(data)[:amount]
                return length
            return original(h,bm,req,param,index,data,length,timeout)
        self.libusb_control_transfer=Fn(transfer)

class PresetNameTailTests(unittest.TestCase):
    def setUp(self):
        self.usb=InPlaceNamesUSB();self.device=AF16Rig(self.usb);self.device.open();self.addCleanup(self.device.close)
        p=patch('device_presets.time.sleep');p.start();self.addCleanup(p.stop)
    def test_read_stops_at_field_boundary_despite_adjacent_name(self):
        payload=b'MergedFronts\0'
        self.usb.libusb_control_transfer(None,0x40,0x1b,12,0,payload,len(payload),1000)
        self.assertEqual(read_slot(self.device,3)['name'],'MergedFronts')
    def test_reported_name_replaces_old_tail_with_one_write(self):
        result=rename_preset(self.device,3,'MergedFronts','abcdefghijkl')
        self.assertEqual(result['record']['name'],'MergedFronts')
        self.assertEqual(self.usb.rename_out[-1][4:],(b'MergedFronts',12))
        self.assertEqual(len(self.usb.rename_out),1)
        self.assertEqual(read_slot(self.device,4)['name'],'abcdefghijkl')
        self.assertFalse(self.usb.out)
    def test_existing_correct_hardware_name_needs_no_rewrite(self):
        self.usb.buffers[3][:]=b'MergedFrontspreset3'.ljust(32,b'\0')
        result=rename_preset(self.device,3,'MergedFronts','MergedFronts')
        self.assertEqual(result['record']['name'],'MergedFronts')
        self.assertEqual(result['write_requests'],0)
    def test_every_byte_length_and_utf8_shortens_cleanly(self):
        for name in ['x'*i for i in range(13)]+['Synthé','é'*6]:
            with self.subTest(name=name):
                self.usb.buffers[1][:]=b'abcdefghijklpreset3'.ljust(32,b'\0')
                result=rename_preset(self.device,1,name,'abcdefghijkl')
                self.assertEqual(result['record']['name'],name)
                self.assertEqual(len(self.usb.rename_out[-1][4]),12)
    def test_first_null_byte_ends_read_even_with_nonzero_other_half(self):
        for raw,name in [(b'ABC\0old suffix','ABC'),(b'AB\0Xold suffix','AB'),(b'\0Xold suffix','')]:
            self.usb.buffers[2][:]=raw.ljust(32,b'\0')
            self.assertEqual(read_slot(self.device,2)['name'],name)

if __name__=='__main__':unittest.main()
