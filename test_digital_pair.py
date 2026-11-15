import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
import queue
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from digital_pair import convert
from digital_mixer import DigitalMixer
from mixer_membership import masks
from mixer_view import Console,ChannelController,Field,DigitalControls
from af16rig_gui import Worker
from test_digital_mixer import DigitalUSB

class DigitalPairTests(unittest.TestCase):
    def setUp(self):
        self.usb=DigitalUSB();self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        sleeper=patch('mixer_membership.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def select(self,bus,left,linked=False):
        self.usb.packed[34 if bus=='main' else 48]=0 if linked else 3<<(left-1)
        self.usb.packed[35 if bus=='main' else 49]=1<<((left-1)//2) if linked else 0
    def apply(self,bus,source,linked):return convert(self.d,bus,source,linked,*masks(self.d,bus))
    def test_all_digital_pairs_link_and_unlink_both_buses(self):
        for bus in ('main','cue'):
            show,stereo=(34,35) if bus=='main' else (48,49)
            for left in range(17,65,2):
                self.select(bus,left);self.usb.out=[]
                result=self.apply(bus,left+1,True)
                self.assertEqual(self.usb.out,[(0x40,0x11,show,left-1,0),(0x40,0x11,show,left,0),(0x40,0x11,stereo,(left-1)//2,1)])
                self.assertTrue(all(s['stereo_selected']==1 for s in result))
                self.usb.out=[];result=self.apply(bus,left,False)
                self.assertEqual(self.usb.out,[(0x40,0x11,stereo,(left-1)//2,0),(0x40,0x11,show,left-1,1),(0x40,0x11,show,left,1)])
                self.assertTrue(all(s['mono_selected']==1 for s in result))
    def test_other_sources_bus_and_levels_untouched(self):
        self.select('main',63);self.usb.packed[34]|=1;self.usb.packed[35]|=1<<8
        self.usb.packed[48]=1<<32;self.usb.words[36,62]=(-10*256)&65535;self.usb.words[36,63]=(-15*256)&65535
        self.usb.packed[38]=1<<63;before=dict(self.usb.words)
        self.apply('main',63,True)
        self.assertEqual(self.usb.packed[34],1);self.assertEqual(self.usb.packed[35],(1<<31)|(1<<8))
        self.assertEqual(self.usb.packed[48],1<<32);self.assertEqual(self.usb.packed[38],1<<63)
        self.assertEqual(self.usb.words,before)
    def test_already_requested_mode_sends_nothing(self):
        for linked in (True,False):
            self.select('main',17,linked);self.apply('main',17,linked)
        self.assertEqual(self.usb.out,[])
    def test_absent_half_selected_or_conflicting_pair_rejected(self):
        for mono,pairs in ((0,0),(1<<16,0),(3<<16,1<<8)):
            self.usb.packed[34]=mono;self.usb.packed[35]=pairs
            with self.assertRaises(DeviceError):self.apply('main',17,True)
        self.assertEqual(self.usb.out,[])
    def test_stale_full_mask_rejected(self):
        self.select('main',17)
        with self.assertRaises(DeviceError):convert(self.d,'main',17,True,(3<<16)|1,0)
        self.assertEqual(self.usb.out,[])
    def test_invalid_arguments_and_unknown_version(self):
        for source in (1,16,65,True):
            with self.assertRaises(ValueError):convert(self.d,'main',source,True,0,0)
        self.select('main',17);self.d.version=19
        with self.assertRaises(DeviceError):self.apply('main',17,True)
        self.assertEqual(self.usb.out,[])
    def test_first_failed_write_sent_once(self):
        self.select('main',17);self.usb.ignore=True
        with self.assertRaisesRegex(DeviceError,'Some changes may have applied'):self.apply('main',17,True)
        self.assertEqual(len(self.usb.out),1)
    def test_second_failure_stops_without_rollback(self):
        self.select('main',17)
        original=self.usb.libusb_control_transfer.func
        def transfer(h,bm,req,p,i,data,n,t):
            if req==0x11 and len(self.usb.out)>=1:self.usb.ignore=True
            return original(h,bm,req,p,i,data,n,t)
        self.usb.libusb_control_transfer.func=transfer
        with self.assertRaisesRegex(DeviceError,'Some changes may have applied'):self.apply('main',17,True)
        self.assertEqual(len(self.usb.out),2);self.assertEqual(self.usb.packed[34],1<<17);self.assertEqual(self.usb.packed[35],0)
    def test_disconnect_propagates_and_stops(self):
        self.select('main',17);self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):self.apply('main',17,True)
        self.assertEqual(len(self.usb.out),1)
    def test_demo_pair_conversion(self):
        d=DemoAF16Rig();d.digital_selection={'main':(3<<62,0)}
        result=convert(d,'main',63,True,*masks(d,'main'))
        self.assertTrue(result[0]['stereo_selected']);self.assertEqual(result[0]['stereo_members'][1]['source'],64)
    def make_console(self):
        c=Console.__new__(Console);c.bus='main';c.bank_start=17;c.cancel_drags=Mock();c.layout=Mock()
        c.app=SimpleNamespace(connected=True,info={'state_version':18},message=Field(),name_cache=SimpleNamespace(serial=1),worker=SimpleNamespace(commands=queue.Queue()))
        c.controllers={i:ChannelController(c.app,'main',i) for i in (17,18)}
        for i in (17,18):c.controllers[i].handle(dict(kind='input_snapshot',state=DigitalMixer(self.d).mix_channel_snapshot('main',i)))
        return c
    def test_click_dispatches_one_operation_and_locks_both_members(self):
        self.select('main',17);c=self.make_console();c.link_digital(18);c.link_digital(17)
        cmd,data=c.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'digital_pair');self.assertEqual(data['source'],17);self.assertTrue(data['linked'])
        self.assertEqual(data['connection_serial'],1);self.assertTrue(c.app.worker.commands.empty())
        self.assertTrue(all(m.pending for m in c.controllers.values()))
    def test_failure_unlocks_both_and_forces_refresh(self):
        self.select('main',17);c=self.make_console();c.link_digital(17)
        c.handle(dict(kind='digital_pair_error',request_id=c.digital_pair_request,source=17,bus='main',message='Partial conversion'))
        self.assertTrue(all(not m.pending and m.stale for m in c.controllers.values()))
        self.assertEqual(c.next_source,17);self.assertEqual(c.app.message.cget('text'),'Partial conversion')
    def test_old_operation_reply_ignored(self):
        self.select('main',17);c=self.make_console();c.link_digital(17)
        c.handle(dict(kind='digital_pair_error',request_id=-1,source=17,bus='main',message='Old error'))
        self.assertTrue(all(m.pending for m in c.controllers.values()))
    def test_confirmed_conversion_updates_both_states(self):
        self.select('main',17);c=self.make_console();c.link_digital(17)
        states=self.apply('main',17,True)
        c.handle(dict(kind='digital_pair_state',request_id=c.digital_pair_request,source=17,bus='main',states=states))
        self.assertTrue(all(not m.pending and not m.stale and m.state['stereo_selected']==1 for m in c.controllers.values()))
        c.layout.assert_called_once()
    def test_button_uses_local_usb_pair_number(self):
        control=DigitalControls.__new__(DigitalControls);control.link=Field()
        control.c=SimpleNamespace(source=Field(63),state={'raw':{'show':0,'stereo':1<<31}},pending=False,stale=False,app=SimpleNamespace(connected=True))
        control.refresh();self.assertEqual(control.link.cget('text'),'UNLINK 31/32');self.assertEqual(control.link.cget('state'),'normal')
    def test_worker_rejects_old_connection_before_writes(self):
        events=queue.Queue();w=Worker(events,factory=lambda:AF16Rig(self.usb));w.start();self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        w.commands.put(('connect',None));w.commands.put(('digital_pair',dict(connection_serial=0,request_id=11,bus='main',source=17,linked=True,mono=3<<16,pairs=0)))
        while True:
            e=events.get(timeout=3)
            if e['kind']=='digital_pair_error':break
        self.assertEqual(e['request_id'],11);self.assertEqual(self.usb.out,[])
    def test_external_selection_change_between_steps_stops_next_write(self):
        from mixer_membership import change
        self.select('main',17)
        def changed(*args,**kwargs):
            result=change(*args,**kwargs)
            self.usb.packed[34]|=1
            return result
        with patch('digital_pair.change',side_effect=changed):
            with self.assertRaisesRegex(DeviceError,'changed externally'):self.apply('main',17,True)
        self.assertEqual(len(self.usb.out),1)
        self.assertEqual(self.usb.packed[34],(1<<17)|1)
