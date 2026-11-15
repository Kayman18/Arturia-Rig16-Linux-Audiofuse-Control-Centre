import unittest
from unittest.mock import patch
import test_midi_ports as base
from midi_routes import OPTIONS,DESTINATIONS,read_route,set_route
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from midi_ports import snapshot

class RouteTests(unittest.TestCase):
    def device(self,field,old,accept=True):
        d,words,calls=base.PortTests().device(accept=accept)
        i=DESTINATIONS[field];words[13,i]=old&1;words[12,i]=old>>1
        return d,words,calls
    @patch('midi_routes.time.sleep')
    def test_all_45_supported_transitions_and_other_routes_preserved(self,sleep):
        for field,opts in OPTIONS.items():
            for old in range(len(opts)):
                for new in range(len(opts)):
                    d,words,calls=self.device(field,old);before=words.copy();i=DESTINATIONS[field]
                    result=set_route(d,field,new,old)
                    self.assertEqual(result[field]['raw'],new)
                    expected=[]
                    if (old&1)!=(new&1):expected.append((0x40,0x11,13,i,(new&1).to_bytes(2,'little')))
                    if old>>1!=new>>1:expected.append((0x40,0x11,12,i,(new>>1).to_bytes(2,'little')))
                    self.assertEqual([c for c in calls if c[0]==0x40],expected)
                    self.assertTrue(all(v==before[k] for k,v in words.items() if k not in ((12,i),(13,i))))
    def test_demo_roundtrip_all_routes(self):
        d=DemoAF16Rig()
        for field,opts in OPTIONS.items():
            self.assertEqual(set_route(d,field,len(opts)-1,0)[field]['raw'],len(opts)-1)
    def test_invalid_targets_and_unsupported_existing_combination(self):
        for field,opts in OPTIONS.items():
            d,words,calls=self.device(field,0)
            for bad in (-1,True,len(opts),65535):
                with self.assertRaises(ValueError):set_route(d,field,bad,0)
                with self.assertRaises(ValueError):set_route(d,field,0,bad)
            self.assertEqual(calls,[])
    def test_stale_or_unstable_preflight_sends_nothing(self):
        d,words,calls=self.device('din1_source',0)
        with self.assertRaises(DeviceError):set_route(d,'din1_source',3,1)
        with patch('midi_routes.read_route',return_value=dict(raw=0,bits=[0,0],stable=False)),self.assertRaises(DeviceError):set_route(d,'din1_source',3,0)
        self.assertFalse(any(c[0]==0x40 for c in calls))
    @patch('midi_routes.time.sleep')
    def test_first_failed_component_stops_without_second_out(self,sleep):
        d,words,calls=self.device('din1_source',0,False)
        with self.assertRaisesRegex(DeviceError,'0 route component'):set_route(d,'din1_source',3,0)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    @patch('midi_routes.time.sleep')
    def test_partial_failure_keeps_confirmed_first_component_no_retry(self,sleep):
        d,words,calls=self.device('din1_source',0);transfer=d.lib.libusb_control_transfer
        def fail_second(h,b,r,p,i,data,n,t):
            if b==0x40 and p==12:calls.append((b,r,p,i,bytes(data)));return 2
            return transfer(h,b,r,p,i,data,n,t)
        d.lib.libusb_control_transfer=fail_second
        with self.assertRaisesRegex(DeviceError,'1 route component'):set_route(d,'din1_source',3,0)
        self.assertEqual((words[13,5],words[12,5]),(1,0));self.assertEqual(sum(c[0]==0x40 for c in calls),2)
    def test_external_change_between_components_blocks_second_write(self):
        d,words,calls=self.device('din1_source',0)
        original=read_route;counter=[0]
        def change(device,field):
            counter[0]+=1
            if counter[0]==4:words[12,5]=1
            return original(device,field)
        with patch('midi_routes.read_route',side_effect=change),self.assertRaisesRegex(DeviceError,'changed during apply'):set_route(d,'din1_source',3,0)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    def test_unknown_raw_and_short_read_do_not_become_valid_route(self):
        d,words,calls=self.device('din1_source',0);words[13,5]=8
        self.assertEqual(read_route(d,'din1_source')['raw'],65535)
        d.lib.libusb_control_transfer=lambda *args:1
        with self.assertRaises(DeviceError):read_route(d,'din1_source')
    def test_disconnect_is_not_retried(self):
        d,words,calls=self.device('din1_source',0);transfer=d.lib.libusb_control_transfer
        def disconnect(h,b,r,p,i,data,n,t):
            if b==0x40:calls.append((b,r,p,i,bytes(data)));return -4
            return transfer(h,b,r,p,i,data,n,t)
        d.lib.libusb_control_transfer=disconnect
        with self.assertRaises(DeviceDisconnected):set_route(d,'din1_source',3,0)
        self.assertEqual(sum(c[0]==0x40 for c in calls),1)
    def test_popup_routes_through_existing_guarded_worker_command(self):
        w=base.PortPageTests().window();w.selectors['din2_source'].current.return_value=3;w.apply('din2_source')
        cmd,data=w.app.worker.commands.get_nowait();self.assertEqual((cmd,data['field'],data['target']),('midi_ports_set','din2_source',3))
        result=set_route(DemoAF16Rig(),'din2_source',3,0)
        w.handle(dict(kind='midi_ports_written',request_id=data['request_id'],connection_serial=7,records=result))
        w.values['din2_source'].config.assert_called_with(text='USB Host + DIN')

if __name__=='__main__':unittest.main()
