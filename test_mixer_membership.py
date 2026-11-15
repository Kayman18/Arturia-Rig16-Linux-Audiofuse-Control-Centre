import queue
import unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from mixer_membership import source_id,masks,snapshot,change
from mixer_sources import inclusion_options
from test_controls import FakeUSB,Fn


class MembershipUSB(FakeUSB):
    def __init__(self):
        super().__init__();self.masks={34:0,35:0,48:0,49:0};self.out=[];self.reads=[];self.rc=2;self.ignore=False;self.extra=False;self.read_rc=2
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            if req==0x91 and param in self.masks:
                self.reads.append((param,index));word=(self.masks[param]>>(index*16))&65535
                data[0:2]=word.to_bytes(2,'little');return self.read_rc
            if req==0x11 and param in self.masks:
                self.out.append((bm,req,param,index,bytes(data),length))
                if not self.ignore:
                    if data[0]:self.masks[param]|=1<<index
                    else:self.masks[param]&=~(1<<index)
                    if self.extra:self.masks[param]^=1<<7
                return self.rc
            return original(h,bm,req,param,index,data,length,timeout)
        self.libusb_control_transfer=Fn(transfer)


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.usb=MembershipUSB();self.d=AF16Rig(self.usb);self.d.open();self.addCleanup(self.d.close)
        sleeper=patch('mixer_membership.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def apply(self,bus,source,stereo,value):
        return change(self.d,bus,source,stereo,value,*masks(self.d,bus))
    def test_bank_boundaries(self):
        self.assertEqual([source_id(b,n) for b,n in [('Analog',16),('ADAT',1),('ADAT',16),('USB',1),('USB',32)]],[16,17,32,33,64])
        for b,n in [('USB',33),('ADAT',17),('Analog',True)]:
            with self.assertRaises(ValueError):source_id(b,n)
    def test_exact_read_word_indices(self):
        self.usb.reads=[];snapshot(self.d,'main',64)
        self.assertEqual(self.usb.reads,[(34,0),(34,1),(34,2),(34,3),(35,0),(35,1)]*2)
    def test_all_64_mono_flags_both_buses(self):
        for bus,param in [('main',34),('cue',48)]:
            for source in range(1,65):
                result=self.apply(bus,source,False,True)
                self.assertEqual(result['raw']['show'],1<<(source-1))
                self.assertEqual(self.usb.out[-1],(0x40,0x11,param,source-1,b'\1\0',2))
                self.apply(bus,source,False,False)
        self.assertEqual(set(self.usb.masks.values()),{0})
    def test_all_32_stereo_pairs_both_member_addresses(self):
        for bus,param in [('main',35),('cue',49)]:
            for source in range(1,65):
                result=self.apply(bus,source,True,True)
                self.assertEqual(result['raw']['stereo'],1<<((source-1)//2))
                self.assertEqual(self.usb.out[-1][2:4],(param,(source-1)//2))
                self.apply(bus,source,True,False)
    def test_other_words_and_other_bus_preserved(self):
        self.usb.masks={34:1<<63,35:1<<15,48:1<<49,49:1<<20};before=dict(self.usb.masks)
        self.apply('main',17,False,True);before[34]|=1<<16
        self.assertEqual(self.usb.masks,before)
    def test_stale_full_mask_rejected(self):
        self.usb.masks[34]=1<<63
        with self.assertRaisesRegex(DeviceError,'changed externally'):change(self.d,'main',17,False,True,0,0)
        self.assertFalse(self.usb.out)
    def test_both_mode_conflicts_prevent_writes(self):
        self.usb.masks[34]=1<<32
        with self.assertRaises(DeviceError):self.apply('main',34,True,True)
        self.usb.masks[34]=0;self.usb.masks[35]=1<<31
        with self.assertRaises(DeviceError):self.apply('main',64,False,True)
        self.assertFalse(self.usb.out)
    def test_noop_sends_no_out(self):
        self.apply('main',64,False,False);self.assertFalse(self.usb.out)
    def test_ignored_and_side_effect_writes_not_confirmed_or_retried(self):
        self.usb.ignore=True
        with self.assertRaises(DeviceError):self.apply('main',17,False,True)
        self.assertEqual(len(self.usb.out),1)
        self.usb.ignore=False;self.usb.extra=True
        with self.assertRaises(DeviceError):self.apply('main',17,False,True)
        self.assertEqual(len(self.usb.out),2)
    def test_uncertain_completion_resolved_by_exact_readback(self):
        self.usb.rc=-7
        self.assertEqual(self.apply('cue',64,False,True)['raw']['show'],1<<63)
        self.assertEqual(len(self.usb.out),1)
    def test_disconnect_does_not_retry(self):
        self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):self.apply('main',17,False,True)
        self.assertEqual(len(self.usb.out),1)
    def test_short_read_and_unknown_version_prevent_out(self):
        self.usb.read_rc=1
        with self.assertRaises(DeviceError):self.apply('main',17,False,True)
        self.usb.read_rc=2;self.d.version=19
        with self.assertRaises(DeviceError):self.apply('main',17,False,True)
        self.assertFalse(self.usb.out)
    def test_demo_digital_and_analog_selection_preserve_each_other(self):
        d=DemoAF16Rig();change(d,'main',64,False,True,*masks(d,'main'))
        d.main_show=0
        self.assertEqual(masks(d,'main')[0],1<<63)
        change(d,'main',1,False,True,*masks(d,'main'))
        self.assertEqual(masks(d,'main')[0],(1<<63)|1)
    def test_high_input_ui_options(self):
        state={'raw':{'show':1<<63,'stereo':0}}
        self.assertTrue(inclusion_options(state,64)['mono_remove'])
        self.assertFalse(inclusion_options(state,63)['stereo_add'])
    def test_changed_during_read_rejected(self):
        with patch('mixer_membership.masks',side_effect=[(0,0),(1<<63,0)]):
            with self.assertRaises(DeviceError):snapshot(self.d,'main',17)
    def test_old_connection_worker_guard(self):
        events=queue.Queue();w=Worker(events,factory=lambda:AF16Rig(self.usb));w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        w.commands.put(('connect',None));w.commands.put(('membership_set',dict(connection_serial=0,bus='main',source=17)))
        while True:
            event=events.get(timeout=3)
            if event['kind']=='input_error':break
        self.assertEqual(event['channel'],'mixer_sources');self.assertFalse(self.usb.out)

    def test_worker_selected_usb_snapshot_has_global_source_and_generation(self):
        events=queue.Queue();w=Worker(events,factory=lambda:AF16Rig(self.usb));w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        w.commands.put(('connect',None));w.commands.put(('input_select',('mixer_sources','cue',64)))
        while True:
            event=events.get(timeout=3)
            if event['kind']=='input_snapshot':break
        self.assertEqual(event['state']['source'],64);self.assertEqual(event['state']['connection_serial'],1)
    def test_source_page_queues_usb32_global_bit64_target(self):
        from types import SimpleNamespace
        from mixer_view import Field
        from mixer_sources import MixerSourcesWindow
        p=MixerSourcesWindow.__new__(MixerSourcesWindow)
        p.app=SimpleNamespace(connected=True,info={'state_version':18},worker=SimpleNamespace(commands=queue.Queue()))
        p.source=Field(32);p.bank=Field('USB');p.bus=Field('main');p.pending=False;p.stale=False
        p.state=dict(raw={'show':0,'stereo':0},connection_serial=7)
        p.buttons={key:Field() for key in ('mono_add','mono_remove','stereo_add','stereo_remove')}
        for name in ('summary','bus_menu','bank_menu','source_menu','refresh_button','message'):setattr(p,name,Field())
        p.update();self.assertIn('USB 31/32',p.summary.cget('text'))
        p.apply('mono_add');cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'membership_set');self.assertEqual(data['source'],64);self.assertEqual(data['connection_serial'],7)

if __name__=='__main__':unittest.main()
