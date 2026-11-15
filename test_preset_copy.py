import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from device_presets import read_status
from preset_copy import copy_slot
from presets_window import PresetsWindow
from test_controls import Fn
import test_device_presets as fixtures

class ContentUSB(fixtures.PresetUSB):
    def __init__(self):
        super().__init__()
        self.slots={s:('saved-settings',s) for s in range(9)};self.active=('unsaved-settings',)
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            result=original(h,bm,req,param,index,data,length,timeout)
            if req==0x48 and not self.ignore:
                if param==0:self.active=self.slots[index]
                else:self.slots[index]=self.active
            return result
        self.libusb_control_transfer=Fn(transfer)

class CopyTests(unittest.TestCase):
    worker_event=fixtures.PresetTests.worker_event
    def setUp(self):
        self.usb=ContentUSB();self.device=AF16Rig(self.usb);self.device.open();self.addCleanup(self.device.close)
        sleeper=patch('device_presets.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def run_copy(self,**kw):
        return copy_slot(self.device,3,8,'Preset 3','Preset 8',dict(current=2,changed=1),**kw)
    def test_exact_two_packets_and_contents(self):
        before=dict(self.usb.slots);names=dict(self.usb.names)
        result=self.run_copy()
        self.assertEqual(self.usb.out,[(0x40,0x48,0,3,b'\0',1,1000),(0x40,0x48,1,8,b'\0',1,1000)])
        self.assertEqual(self.usb.slots[8],before[3]);self.assertEqual(self.usb.active,before[3])
        self.assertEqual({s:v for s,v in self.usb.slots.items() if s!=8},{s:v for s,v in before.items() if s!=8})
        self.assertEqual(self.usb.names,names);self.assertEqual(result['status'],dict(current=8,changed=0))
    def test_factory_source(self):
        copy_slot(self.device,0,8,'Factory','Preset 8',dict(current=2,changed=1))
        self.assertEqual(self.usb.slots[8],self.usb.slots[0])
    def test_invalid_destinations_zero_writes(self):
        for source,dest in [(3,3),(3,0),(3,9),(True,8),(3,True)]:
            with self.assertRaises(ValueError):copy_slot(self.device,source,dest,'Preset 3','Preset 8',{})
        self.assertFalse(self.usb.out)
    def test_stale_destination_blocks_load(self):
        self.usb.names[8]='Changed'
        with self.assertRaisesRegex(DeviceError,'preflight'):self.run_copy()
        self.assertFalse(self.usb.out)
    def test_stale_source_or_status_zero_writes(self):
        self.usb.names[3]='Changed'
        with self.assertRaises(DeviceError):self.run_copy()
        self.usb.names[3]='Preset 3';self.usb.changed=0
        with self.assertRaises(DeviceError):self.run_copy()
        self.assertFalse(self.usb.out)
    def test_unconfirmed_load_never_saves_or_retries(self):
        self.usb.ignore=True
        with self.assertRaisesRegex(DeviceError,'load source'):self.run_copy()
        self.assertEqual(len(self.usb.out),1)
    def test_uncertain_load_does_not_save_even_if_state_matches(self):
        self.usb.result=-7
        with self.assertRaises(DeviceError):self.run_copy()
        self.assertEqual(len(self.usb.out),1)
    def test_destination_changed_after_load_no_save(self):
        with self.assertRaisesRegex(DeviceError,'Source load was confirmed'):
            self.run_copy(between=lambda:self.usb.names.update({8:'Changed'}))
        self.assertEqual(len(self.usb.out),1)
    def test_live_edit_between_stages_blocks_save(self):
        with self.assertRaisesRegex(DeviceError,'save destination'):
            self.run_copy(between=lambda:setattr(self.usb,'changed',1))
        self.assertEqual(len(self.usb.out),1)
    def test_cancel_between_stages_never_saves(self):
        def stop():raise DeviceError('Application is closing')
        with self.assertRaisesRegex(DeviceError,'Source load was confirmed'):self.run_copy(between=stop)
        self.assertEqual(len(self.usb.out),1)
    def test_save_failure_no_rollback_or_retry(self):
        with self.assertRaisesRegex(DeviceError,'Source load was confirmed'):
            self.run_copy(between=lambda:setattr(self.usb,'ignore',True))
        self.assertEqual(len(self.usb.out),2);self.assertEqual(self.usb.current,3)
    def test_disconnect_remains_disconnect(self):
        self.usb.result=-4
        with self.assertRaises(DeviceDisconnected):self.run_copy()
        self.assertEqual(len(self.usb.out),1)
    def test_callback_before_load_only(self):
        observed=[];self.run_copy(on_load=lambda:observed.append(len(self.usb.out)))
        self.assertEqual(observed,[0])
    def test_demo_no_usb(self):
        d=DemoAF16Rig();r=copy_slot(d,1,8,'Demo preset 1','Demo preset 8',read_status(d))
        self.assertTrue(r['demo']);self.assertEqual(r['write_requests'],0);self.assertEqual(d.preset_current,8)
    def test_worker_result_and_cache_invalidation(self):
        events=self.worker_event(('preset_copy',dict(connection_serial=1,request_id=31,source=3,destination=8,
            source_name='Preset 3',destination_name='Preset 8',expected_status=dict(current=2,changed=1))),'preset_done')
        self.assertEqual(events[-1]['result']['action'],'copy')
        self.assertEqual(sum(e['kind']=='preset_state_reset' for e in events),1)
    def test_worker_stale_connection(self):
        self.worker_event(('preset_copy',dict(connection_serial=0,request_id=32)),'preset_error')
        self.assertFalse(self.usb.out)

class CopyUITests(unittest.TestCase):
    def page(self):
        p=object.__new__(PresetsWindow)
        p.closed=False;p.busy=False;p.serial=1;p.status=dict(current=2,changed=1)
        p.records={i:dict(slot=i,name=f'Preset {i}') for i in range(9)}
        p.app=SimpleNamespace(connected=True,name_cache=SimpleNamespace(serial=1),worker=SimpleNamespace(commands=queue.Queue()))
        p.table=Mock();p.table.selection.return_value=('3',);p.window=Mock();p.message=Mock();p.update_buttons=Mock()
        return p
    def test_confirmed_queues_one_command(self):
        p=self.page()
        with patch('presets_window.simpledialog.askinteger',return_value=8),patch('presets_window.messagebox.askyesno',return_value=True) as confirm:
            p.copy_selected()
            self.assertIn('unsaved changes',confirm.call_args.args[1])
        cmd,data=p.app.worker.commands.get_nowait();self.assertEqual(cmd,'preset_copy')
        self.assertEqual((data['source'],data['destination']),(3,8));self.assertTrue(p.app.worker.commands.empty())
    def test_cancel_both_steps_no_command(self):
        for destination,confirmed in [(None,True),(8,False),(3,True)]:
            p=self.page()
            with patch('presets_window.simpledialog.askinteger',return_value=destination),patch('presets_window.messagebox.askyesno',return_value=confirmed):p.copy_selected()
            self.assertTrue(p.app.worker.commands.empty());self.assertFalse(p.busy)
    def test_connection_change_in_confirmation_blocks(self):
        p=self.page()
        def confirm(*a,**k):p.app.name_cache.serial=2;return True
        with patch('presets_window.simpledialog.askinteger',return_value=8),patch('presets_window.messagebox.askyesno',side_effect=confirm):p.copy_selected()
        self.assertTrue(p.app.worker.commands.empty())
    def test_busy_blocks_duplicate(self):
        p=self.page();p.busy=True
        with patch('presets_window.simpledialog.askinteger') as dialog:p.copy_selected();dialog.assert_not_called()
