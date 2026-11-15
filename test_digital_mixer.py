import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from af16rig import AF16Rig, DemoAF16Rig, PARAMETERS, DeviceError, DeviceDisconnected
from af16rig_gui import Worker
from digital_mixer import DigitalMixer, mixer_device, PACKED, INDEXED
from mixer_membership import change, masks
from mixer_view import ChannelController, Console, Field, Strip
from test_controls import FakeUSB, Fn


class DigitalUSB(FakeUSB):
    def __init__(self):
        super().__init__()
        self.packed={PARAMETERS[name][1]:0 for name in PACKED}
        self.words={};self.out=[];self.reads=[];self.ignore=False;self.rc=2;self.read_rc=2
        original=self.libusb_control_transfer
        def transfer(h,bm,req,param,index,data,length,timeout):
            if req==0x91 and 34<=param<=53:
                self.reads.append((param,index))
                word=((self.packed[param]>>(index*16))&65535) if param in self.packed else self.words.get((param,index),127 if param in (37,51) else (-12*256)&65535)
                data[:2]=word.to_bytes(2,'little');return self.read_rc
            if req==0x11 and 34<=param<=53:
                word=int.from_bytes(data,'little');self.out.append((bm,req,param,index,word))
                if not self.ignore:
                    if param in self.packed:
                        self.packed[param]=(self.packed[param]|(1<<index)) if word else (self.packed[param]&~(1<<index))
                    else:self.words[param,index]=word
                return self.rc
            return original(h,bm,req,param,index,data,length,timeout)
        self.libusb_control_transfer=Fn(transfer)


class DigitalTests(unittest.TestCase):
    def setUp(self):
        self.usb=DigitalUSB();self.device=AF16Rig(self.usb);self.device.open();self.addCleanup(self.device.close)
        self.d=DigitalMixer(self.device)
        sleeper=patch('digital_mixer.time.sleep');sleeper.start();self.addCleanup(sleeper.stop)
    def select(self,bus,source,stereo=False):
        self.usb.packed[34 if bus=='main' else 48]=0 if stereo else 1<<(source-1)
        self.usb.packed[35 if bus=='main' else 49]=1<<((source-1)//2) if stereo else 0
    def test_every_digital_mono_channel_both_buses(self):
        for bus in ('main','cue'):
            for source in range(17,65):
                with self.subTest(bus=bus,source=source):
                    self.select(bus,source)
                    self.d.set_console_value(bus,source,'level',-10*256,False)
                    self.assertEqual(self.usb.out[-1],(0x40,0x11,36 if bus=='main' else 50,source-1,(-10*256)&65535))
                    self.d.write_mix_channel_mute(bus,source,True)
                    self.d.write_mix_channel_solo(bus,source,True)
                    self.d.adjust_channel_pan(bus,source,'Right')
                    state=self.d.mix_channel_snapshot(bus,source)
                    self.assertEqual((state['mute'],state['solo'],state['level_db'],state['raw']['pan']),(1,1,-10,254))
    def test_all_digital_stereo_pairs_preserve_relative_level(self):
        for bus in ('main','cue'):
            for source in range(17,65,2):
                self.select(bus,source,True)
                param=36 if bus=='main' else 50
                self.usb.words[param,source-1]=(-12*256)&65535
                self.usb.words[param,source]=(-15*256)&65535
                self.d.set_console_value(bus,source,'level',-8*256,True)
                self.d.write_stereo_channel_switch(bus,source,'mute',True)
                self.d.write_stereo_channel_switch(bus,source,'solo',True)
                state=self.d.mix_channel_snapshot(bus,source)
                self.assertEqual([m['level_db'] for m in state['stereo_members']],[-8,-11])
                self.assertTrue(all(m['mute']==m['solo']==1 for m in state['stereo_members']))
    def test_all_aux_sends_mono_and_stereo(self):
        for source in range(17,65):
            for stereo in (False,True):
                self.select('main',source,stereo)
                for aux in range(1,5):
                    self.d.set_console_value('main',source,'send'+str(aux),-20*256,stereo)
                    if stereo:self.d.write_stereo_send_mute('main',source,aux,True)
                    else:self.d.write_send_mute('main',source,aux,True)
                    self.assertEqual(self.d.read('aux'+str(aux)+'_send_level',source-1),(-20*256)&65535)
                    self.assertEqual(self.d.read_input_bit('main_channel_send'+str(aux),source-1),1)
    def test_read_masks_all_words(self):
        self.usb.packed[38]=(1<<63)|(1<<32)|1
        self.assertEqual(self.d.read('main_channel_mute'),(1<<63)|(1<<32)|1)
        self.assertEqual(self.usb.reads[-4:],[(38,i) for i in range(4)])
    def test_one_bit_write_preserves_other_words(self):
        self.select('main',64);self.usb.packed[38]=(1<<16)|1
        self.d.write_mix_channel_mute('main',64,True)
        self.assertEqual(self.usb.packed[38],(1<<63)|(1<<16)|1)
    def test_missing_or_conflicting_selection_prevents_writes(self):
        for source in (17,32,33,48,49,64):
            with self.assertRaises(DeviceError):self.d.set_console_value('main',source,'level',0,False)
        self.assertEqual(self.usb.out,[])
    def test_ignored_write_sent_once(self):
        self.select('main',64);self.usb.ignore=True
        with self.assertRaises(DeviceError):self.d.write_mix_channel_mute('main',64,True)
        self.assertEqual(len(self.usb.out),1)
    def test_timeout_after_acceptance_confirmed_without_repeat(self):
        self.select('main',64);self.usb.rc=-7
        self.assertEqual(self.d.write_mix_channel_mute('main',64,True),1)
        self.assertEqual(len(self.usb.out),1)
    def test_disconnect_stops_pair(self):
        self.select('main',63,True);self.usb.rc=-4
        with self.assertRaises(DeviceDisconnected):self.d.write_stereo_channel_switch('main',63,'mute',True)
        self.assertEqual(len(self.usb.out),1)
    def test_short_selection_read_prevents_write(self):
        self.select('main',17);self.usb.read_rc=1
        with self.assertRaises(DeviceError):self.d.write_mix_channel_solo('main',17,True)
        self.assertEqual(self.usb.out,[])
    def test_unknown_version_prevents_write(self):
        self.select('main',17);self.d.version=19
        with self.assertRaises(DeviceError):self.d.set_console_value('main',17,'level',0,False)
        self.assertEqual(self.usb.out,[])
    def test_bad_addresses_and_fields_rejected(self):
        for index in (-1,0,15,64,True):
            with self.assertRaises(ValueError):self.d._write_and_confirm('main_channel_level',0,index)
        for name in ('force_rear','main_channel_show','output_source'):
            with self.assertRaises(ValueError):self.d._write_and_confirm(name,1,16)
        self.assertEqual(self.usb.out,[])
    def test_analog_uses_original_driver(self):
        for source in range(17):self.assertIs(mixer_device(self.device,source),self.device)
    def test_demo_selection_and_values(self):
        d=DemoAF16Rig();change(d,'main',64,False,True,*masks(d,'main'))
        proxy=DigitalMixer(d);proxy.set_console_value('main',64,'level',-9*256,False)
        proxy.write_mix_channel_mute('main',64,True)
        state=DigitalMixer(d).mix_channel_snapshot('main',64)
        self.assertEqual((state['level_db'],state['mute']),(-9,1))
        self.assertEqual(d.mix_channel_snapshot('main',1)['level_db'],-12)
    def test_high_source_controller_dispatch(self):
        self.select('main',64)
        app=SimpleNamespace(connected=True,info={'state_version':18},message=Field(),worker=SimpleNamespace(commands=queue.Queue()))
        c=ChannelController(app,'main',64);c.handle(dict(kind='input_snapshot',state=self.d.mix_channel_snapshot('main',64)))
        self.assertTrue(c.target('level',-8))
        self.assertEqual(app.worker.commands.get_nowait(),('console_set',('main',64,'level',-2048,False)))
    def test_digital_titles_do_not_use_analog_names(self):
        for source,title in ((17,'ADAT 1'),(32,'ADAT 16'),(33,'USB 1'),(64,'USB 32')):
            from name_sync import NameCache
            cache=NameCache();view=SimpleNamespace(c=SimpleNamespace(source=Field(source),state={'mono_selected':1},app=SimpleNamespace(name_cache=cache)),title=Field(),mode=Field())
            Strip.refresh_title(view)
            self.assertEqual(view.title.cget('text'),title)
    def test_previous_bank_snapshot_does_not_advance_new_bank(self):
        c=Console.__new__(Console);c.bank_start=49;c.bus='main';c.inflight=('main',1);c.next_source=49
        c.handle(dict(kind='console_snapshot',bus='main',source=1,state={}))
        self.assertEqual(c.next_source,49);self.assertIsNone(c.inflight)
    def test_worker_digital_fader_readback_no_preamp_access(self):
        self.select('main',64);events=queue.Queue();w=Worker(events,factory=lambda:AF16Rig(self.usb));w.preamp_enabled=True;w.start()
        self.addCleanup(lambda:(w.stop_event.set(),w.join(2)))
        def wait(kind):
            for _ in range(100):
                event=events.get(timeout=2)
                if event['kind']==kind:return event
            self.fail('Missing '+kind)
        w.commands.put(('connect',None));wait('connected')
        w.commands.put(('console_set',('main',64,'level',-2560,False)))
        self.assertEqual(wait('input_written')['actual'],-2560)
        w.commands.put(('console_read',('main',64)))
        self.assertEqual(wait('console_snapshot')['state']['level_db'],-10)
        w.commands.put(('console_read',('main',33)))
        wait('console_snapshot')
        remaining=[]
        while not events.empty():remaining.append(events.get_nowait())
        self.assertFalse(any(e['kind']=='preamp_error' for e in remaining))
    def test_digital_meter_mapping_including_last_usb_pair(self):
        from meters import decode_frame
        import struct
        strips={i:SimpleNamespace(meter=Mock(),c=SimpleNamespace(state={'stereo_members':[1,2]} if i==63 else {})) for i in (17,32,33,49,63,64)}
        v=SimpleNamespace(meter_serial=5,strips=strips,master_view=SimpleNamespace(meter=Mock(),aux_meters={}),bus='main',meter_status=Mock(),app=SimpleNamespace(demo=False))
        frame=decode_frame(struct.pack('<118H',*range(118)))
        Console.handle(v,dict(kind='meter_frame',state=frame,connection_serial=5))
        for source,word in ((17,16),(32,31),(33,68),(49,84),(64,99)):
            self.assertEqual(strips[source].meter.feed.call_args.args[0],[word/32767])
        self.assertEqual(strips[63].meter.feed.call_args.args[0],[98/32767,99/32767])
    def test_last_digital_channel_then_master_restarts_same_bank(self):
        c=Console.__new__(Console);c.bank_start=49;c.bus='main';c.inflight=('main',64)
        c.controllers={64:SimpleNamespace(state={},handle=Mock())};c.master=SimpleNamespace(handle=Mock());c.layout=Mock()
        c.handle(dict(kind='console_snapshot',bus='main',source=64,state={}))
        self.assertEqual(c.next_source,0)
        c.handle(dict(kind='console_snapshot',bus='main',source=0,state={}))
        self.assertEqual(c.next_source,49)
    def test_bank_layout_filters_analog_and_collapses_digital_pair(self):
        c=Console.__new__(Console);c.bank_start=49;c.bus='main';c.visible=[];c.bus_buttons={};c.bank_buttons={};c.resize=Mock()
        c.controllers={i:SimpleNamespace(state={'stereo_members':[1,2]} if i==63 else {}) for i in list(range(1,17))+list(range(49,65))}
        c.strips={i:SimpleNamespace(frame=Mock(),preamp=SimpleNamespace(source_button=None,source_slot=Field())) for i in c.controllers}
        c.master_view=SimpleNamespace(frame=Mock());c.layout()
        self.assertEqual(c.visible,list(range(49,64)))
        c.strips[1].frame.pack.assert_not_called();c.strips[64].frame.pack.assert_not_called()
    def test_bank_change_blocked_during_pending_write(self):
        c=Console.__new__(Console);c.bank_start=1;c.preamp_pending=set();c.controllers={1:SimpleNamespace(pending=True)}
        c.change_bank(49);self.assertEqual(c.bank_start,1)
