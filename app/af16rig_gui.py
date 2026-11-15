#!/usr/bin/env python3
from digital_mixer import mixer_device
from reconnect import ReconnectPolicy,CONTROL_COMMANDS,READ_COMMANDS
"""AF16Rig Linux Control BETA RC — native monitor control prototype."""
import argparse
import datetime
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog
from af16rig import CHANNEL_MAX_DB, CHANNEL_MAX_RAW, MIXER_BUSES, AF16Rig, DemoAF16Rig, DeviceError, DeviceDisconnected, VOLUME_UNITS_PER_DB, VOLUME_MIN_RAW, VOLUME_MAX_RAW

BG, PANEL, TEXT, MUTED, ACCENT = '#202225', '#2b2e32', '#e6e8ea', '#969ca2', '#62cbd5'

def compare_pan_scans(previous, current):
    shared = sorted(previous.keys() & current.keys())
    changes = {key: [previous[key], current[key]] for key in shared if previous[key] != current[key]}
    return {'compared': len(shared), 'changes': changes}


class Worker(threading.Thread):
    def __init__(self, output, demo=False, factory=None):
        super().__init__(daemon=True)
        self.output, self.commands = output, queue.Queue()
        self.stop_event = threading.Event()
        self.factory = factory or (DemoAF16Rig if demo else AF16Rig)
        self.device, self.next_poll = None, 0
        self.poll_failures = 0
        self.connection_serial = 0
        self.reconnect = ReconnectPolicy()
        self.names_scan = None
        self.names_paused = False
        self.preamp_enabled = False
        self.meters_enabled = False
        self.meters_failed = False
        self.next_meter = 0
        self.input_channel, self.input_next_poll = None, 0

    def emit(self, kind, **data):
        self.output.put({'kind': kind, **data})

    def disconnect(self):
        self.names_scan = None
        if self.device:
            self.device.close()
            self.device = None

    def discard_pending_writes(self):
        keep=[];discarded=0
        while True:
            try:item=self.commands.get_nowait()
            except queue.Empty:break
            if item[0] in CONTROL_COMMANDS or item[0] in READ_COMMANDS:keep.append(item)
            else:discarded+=1
        for item in keep:self.commands.put(item)
        if discarded:self.emit('commands_discarded',count=discarded)

    def schedule_reconnect(self,message):
        delay=self.reconnect.failed(time.monotonic())
        if delay is not None:self.emit('reconnect_wait',delay=delay,attempt=self.reconnect.failures,message=message)

    def poll(self,state=None):
        self.emit('snapshot', state=self.device.snapshot() if state is None else state)
        self.names_paused = False
        self.poll_failures = 0
        self.next_poll = time.monotonic() + 0.5

    def poll_input(self):
        try:
            from clock_status import snapshot as clock_snapshot
            from mixer_membership import snapshot as membership_snapshot
            state = (membership_snapshot(self.device,*self.input_channel[1:]) if isinstance(self.input_channel,tuple) and self.input_channel[0]=='mixer_sources'
                     else self.device.output_snapshot(self.input_channel[1]) if isinstance(self.input_channel,tuple) and self.input_channel[0]=='output'
                     else mixer_device(self.device, self.input_channel[2]).mix_channel_snapshot(*self.input_channel[1:]) if isinstance(self.input_channel,tuple) and self.input_channel[0]=='mix_channel'
                     else clock_snapshot(self.device) if self.input_channel=='clock'
                     else self.device.monitor_settings_snapshot() if self.input_channel=='monitor_settings'
                     else self.device.aux_links_snapshot() if self.input_channel=='aux_links'
                     else self.device.mixer_masters_snapshot() if self.input_channel=='masters'
                     else self.device.headphones_snapshot() if self.input_channel=='phones'
                     else self.device.mini_snapshot() if self.input_channel=='mini'
                     else self.device.front_snapshot() if self.input_channel == 'front'
                     else self.device.input_snapshot(self.input_channel))
            if state.get('channel') in ('mixer_sources','clock'):state['connection_serial']=self.connection_serial
            self.emit('input_snapshot', state=state)
        except DeviceDisconnected:
            raise
        except (DeviceError, ValueError) as e:
            if isinstance(self.input_channel,tuple) and self.input_channel[0]=='mixer_sources':
                self.emit('input_error',channel='mixer_sources',bus=self.input_channel[1],source=self.input_channel[2],message=str(e))
            elif isinstance(self.input_channel,tuple) and self.input_channel[0]=='mix_channel':
                self.emit('input_error',channel='mix_channel',bus=self.input_channel[1],source=self.input_channel[2],message=str(e))
            else:
                self.emit('input_error', channel='output' if isinstance(self.input_channel,tuple) else self.input_channel, output=self.input_channel[1] if isinstance(self.input_channel,tuple) else None, message=str(e))
        finally:
            self.input_next_poll = time.monotonic() + 1.0

    def poll_meter_if_due(self):
        # Meter reads must not depend on the command queue becoming empty.
        if (not self.device or not self.meters_enabled or self.meters_failed
                or self.names_paused or self.stop_event.is_set()
                or time.monotonic()<self.next_meter):return
        from meters import read_frame,demo_frame
        try:
            frame=demo_frame() if isinstance(self.device,DemoAF16Rig) else read_frame(self.device)
            self.emit('meter_frame',state=frame,connection_serial=self.connection_serial)
        except DeviceDisconnected:raise
        except (DeviceError,ValueError) as error:
            self.meters_failed=True
            self.emit('meter_error',message=str(error),connection_serial=self.connection_serial)
        self.next_meter=time.monotonic()+.05

    def read_name_slice(self):
        # Amortize the idle queue wait without monopolizing the USB worker.
        deadline=time.monotonic()+.008
        for _ in range(8):
            now=time.monotonic()
            if (self.stop_event.is_set() or not self.commands.empty() or self.names_paused
                    or self.names_scan is None or self.names_scan.done):break
            if now>=self.next_poll or (self.input_channel is not None and now>=self.input_next_poll):break
            if self.meters_enabled and not self.meters_failed and now>=self.next_meter:break
            record=self.names_scan.step()
            if record is not None:self.emit('auto_name',connection_serial=self.connection_serial,state=record)
            if time.monotonic()>=deadline:break

    def run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    cmd, data = self.commands.get(timeout=0.01 if self.meters_enabled and not self.meters_failed else 0.01 if self.names_scan is not None and not self.names_scan.done and not self.names_paused else 0.05)
                except queue.Empty:
                    cmd, data = None, None
                if self.stop_event.is_set():
                    break
                automatic=False
                if cmd is None and self.device is None and self.reconnect.due(time.monotonic()):
                    cmd='connect';automatic=True
                if self.device is None and cmd is not None and cmd not in CONTROL_COMMANDS:
                    if cmd not in READ_COMMANDS:self.emit('commands_discarded',count=1)
                    continue
                try:
                    if cmd not in ('connect','disconnect'):
                        self.poll_meter_if_due()
                    if cmd == 'auto_reconnect':
                        self.reconnect.set_enabled(data)
                        if self.device is None and self.reconnect.enabled and self.reconnect.wanted:
                            self.schedule_reconnect('Waiting for AF16Rig')
                        elif not self.reconnect.enabled:self.emit('reconnect_disabled')
                    elif cmd == 'preamp_enable':
                        self.preamp_enabled=bool(data)
                    elif cmd == 'masters_read':
                        if not self.device:raise DeviceError('Device is disconnected')
                        self.emit('masters_snapshot',state=self.device.mixer_masters_snapshot())
                    elif cmd == 'stereo_pair':
                        if not self.device:raise DeviceError('Device is disconnected')
                        from stereo_pair import convert
                        from preamp import snapshot
                        bus,source,kind,value,mono,pairs=data
                        states=convert(self.device,bus,source,kind,value,mono,pairs)
                        left=((source-1)//2)*2+1
                        self.emit('pair_state',bus=bus,source=left,states=states)
                        self.emit('preamp_state',source=left,operation=True,states=[snapshot(self.device,i) for i in (left,left+1)])
                    elif cmd == 'preamp_pad':
                        if not self.device:raise DeviceError('Device is disconnected')
                        from preamp import change_pad
                        states=change_pad(self.device,*data)
                        self.emit('preamp_state',source=data[0],operation=True,states=states)
                    elif cmd == 'preamp_pair_gain':
                        if not self.device:raise DeviceError('Device is disconnected')
                        from preamp import change_pair_gain
                        states=change_pair_gain(self.device,*data)
                        self.emit('preamp_state',source=data[0],operation=True,states=states)
                    elif cmd == 'preamp_set':
                        if not self.device:raise DeviceError('Device is disconnected')
                        from preamp import change,snapshot
                        channel,kind,control,value=data
                        change(self.device,channel,kind,control,value)
                        left=((channel-1)//2)*2+1
                        self.emit('preamp_state',source=channel,operation=True,states=[snapshot(self.device,i) for i in (left,left+1)])
                    elif cmd == 'preamp_source':
                        if not self.device:raise DeviceError('Device is disconnected')
                        self.device.set_rear_pair_source(1,bool(data))
                        from preamp import snapshot
                        self.emit('preamp_state',source=1,operation=True,states=[snapshot(self.device,i) for i in (1,2)])
                    elif cmd == 'meters_enable':
                        self.meters_enabled=bool(data)
                    elif cmd == 'connect':
                        if not automatic:self.reconnect.start()
                        if self.connection_serial:self.discard_pending_writes()
                        self.disconnect()
                        self.device = self.factory()
                        self.device.open()
                        self.connection_serial += 1
                        self.meters_failed=False
                        self.next_meter=0
                        info = {name: self.device.read(name) for name in
                                ('state_version', 'firmware_raw', 'hardware_raw', 'audio_firmware_raw')}
                        from name_sync import NameScan
                        self.names_scan=NameScan(self.device,demo=isinstance(self.device,DemoAF16Rig))
                        initial_state=self.device.snapshot()
                        self.reconnect.success()
                        self.input_next_poll=0
                        self.poll_failures=0
                        self.emit('connected', info=info,connection_serial=self.connection_serial)
                        self.poll(initial_state)
                    elif cmd in ('midi_ports_read','midi_ports_set'):
                        self.device.last_write=None
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; reopen MIDI ports')
                        from midi_ports import snapshot,set_option
                        records=(snapshot(self.device) if cmd=='midi_ports_read' else set_option(self.device,data['field'],data['target'],data['expected']))
                        self.emit('midi_ports_snapshot' if cmd=='midi_ports_read' else 'midi_ports_written',records=records,request_id=data['request_id'],connection_serial=self.connection_serial)
                    elif cmd == 'midi_bank_size':
                        self.device.last_write=None
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; refresh MIDI assignments')
                        from midi_config import set_bank_size
                        record=set_bank_size(self.device,data['target'],data['expected'])
                        self.emit('midi_written',record=record,request_id=data['request_id'],connection_serial=self.connection_serial,diagnostic=getattr(self.device,'last_write',None))
                    elif cmd == 'midi_remap':
                        self.device.last_write=None
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; refresh MIDI assignments')
                        from midi_config import remap
                        record=remap(self.device,data['parameter'],data['index'],data['channel'],data['number'],data['expected'],data.get('message_type'))
                        self.emit('midi_written',record=record,request_id=data['request_id'],connection_serial=self.connection_serial,diagnostic=getattr(self.device,'last_write',None))
                    elif cmd == 'midi_read':
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; refresh MIDI assignments')
                        from midi_config import read_entry
                        record=read_entry(self.device,data['parameter'],data['index'])
                        self.emit('midi_snapshot',record=record,request_id=data['request_id'],connection_serial=self.connection_serial)
                    elif cmd == 'clock_set':
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed. Refresh clock settings.')
                        from clock_controls import set_option
                        if data['field']=='sample_rate':
                            from sample_rate import set_rate
                            actual=set_rate(self.device,data['target'],data['expected'])
                        else:actual=set_option(self.device,data['field'],data['target'],data['expected'])
                        self.emit('clock_written',channel='clock',actual=actual,request_id=data['request_id'],
                            connection_serial=self.connection_serial,diagnostic=getattr(self.device,'last_write',None))
                        self.device.clock_status_failure=None;self.input_next_poll=0
                    elif cmd == 'clock_refresh':
                        if self.device and self.input_channel=='clock':
                            self.device.clock_status_failure=None
                            self.input_next_poll=0
                    elif cmd == 'stereo_pan':
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed. Refresh stereo pan.')
                        from stereo_pan import set_position
                        actual=set_position(self.device,data['bus'],data['source'],data['target'],data['expected'])
                        self.emit('input_written',channel='mix_channel',bus=data['bus'],source=data['source'],
                                  name='stereo_pan',actual=actual,diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'console_set':
                        if not self.device: raise DeviceError('Device is disconnected')
                        bus, source, control, target, stereo = data
                        actual = mixer_device(self.device, source).set_console_value(bus, source, control, target, stereo)
                        name = bus if source == 0 else 'pan' if control == 'pan' else ('stereo_level' if stereo else 'level') if control == 'level' else ('pair_send_level' if stereo else 'aux'+control[-1]+'_send_level')
                        self.emit('input_written', channel='masters' if source == 0 else 'mix_channel', bus=bus, source=source,
                                  name=name, actual=actual, aux=int(control[-1]) if control.startswith('send') else None,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll = 0
                    elif cmd == 'console_read':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        bus, source = data
                        state = self.device.mixer_masters_snapshot() if source == 0 else mixer_device(self.device, source).mix_channel_snapshot(bus, source)
                        if state.get('stereo_members') and source%2==1:
                            from stereo_pan import read_pair
                            try:state['stereo_pan']=read_pair(self.device,bus,source)
                            except DeviceDisconnected:raise
                            except DeviceError as error:state['errors']['stereo_pan']=str(error)
                        self.emit('console_snapshot', bus=bus, source=source, state=state)
                        if self.preamp_enabled and 1 <= source <= 16:
                            from preamp import snapshot
                            try:
                                members=[source,source+1] if state.get('stereo_members') else [source]
                                states=[]
                                for i in members:
                                    self.poll_meter_if_due()
                                    states.append(snapshot(self.device,i))
                                self.emit('preamp_state',source=source,states=states)
                            except DeviceDisconnected:raise
                            except (DeviceError,ValueError) as error:self.emit('preamp_error',source=source,message=str(error))
                    elif cmd in ('scene_read','scene_set'):
                        if not self.device:raise DeviceError('Device disconnected')
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; read faders again')
                        if data.get('scope')=='mixer':
                            from mixer_scene import topology,read_entry,apply_entry
                        else:
                            from fader_scene import topology,read_entry,apply_entry
                        if cmd=='scene_set':
                            record=apply_entry(self.device,data['layout'],data['change'])
                            if data.get('scope')=='mixer' and record.get('field')=='name':
                                from name_edit import read_name
                                self.emit('auto_name',state=read_name(self.device,record['source']),connection_serial=self.connection_serial)
                            self.emit('scene_written',record=record,request_id=data['request_id'],connection_serial=self.connection_serial)
                        elif data['part'] in ('layout','layout_end'):
                            self.emit('scene_snapshot',part=data['part'],layout=topology(self.device),request_id=data['request_id'],connection_serial=self.connection_serial)
                        else:
                            record=read_entry(self.device,data['layout'],data['address'])
                            self.emit('scene_snapshot',part='entry',record=record,request_id=data['request_id'],connection_serial=self.connection_serial)
                    elif cmd in ('preset_read','preset_status','preset_action','preset_rename','preset_copy'):
                        if not self.device:raise DeviceError('Device is disconnected')
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; read presets again')
                        from device_presets import read_status,read_slot,operate
                        if cmd in ('preset_action','preset_copy'):
                            def invalidate_preset_state():
                                if cmd=='preset_copy' or data['action']=='load':
                                    from name_sync import NameScan
                                    self.names_scan=NameScan(self.device,demo=isinstance(self.device,DemoAF16Rig))
                                    self.names_paused=False
                                    self.next_poll=0;self.input_next_poll=0
                                    self.emit('preset_state_reset',connection_serial=self.connection_serial)
                            if cmd=='preset_copy':
                                from preset_copy import copy_slot
                                def before_copy_save():
                                    if self.stop_event.is_set():raise DeviceError('Application is closing; destination save cancelled')
                                    self.poll_meter_if_due()
                                result=copy_slot(self.device,data['source'],data['destination'],data['source_name'],
                                    data['destination_name'],data['expected_status'],invalidate_preset_state,before_copy_save)
                            else:
                                result=operate(self.device,data['action'],data['slot'],data['expected_name'],data['expected_status'],invalidate_preset_state)
                            self.emit('preset_done',request_id=data['request_id'],result=result,connection_serial=self.connection_serial)
                        elif cmd=='preset_rename':
                            self.device.last_preset_rename=None
                            from device_presets import rename_preset
                            result=rename_preset(self.device,data['slot'],data['name'],data['expected_name'])
                            self.emit('preset_renamed',request_id=data['request_id'],result=result,status=read_status(self.device),connection_serial=self.connection_serial,rename_report=getattr(self.device,'last_preset_rename',None))
                        elif cmd=='preset_read':
                            record=read_slot(self.device,data['slot'])
                            self.emit('preset_snapshot',request_id=data['request_id'],record=record,status=read_status(self.device),connection_serial=self.connection_serial)
                        else:
                            self.emit('preset_status',request_id=data['request_id'],status=read_status(self.device),connection_serial=self.connection_serial)
                    elif cmd == 'name_set':
                        if not self.device:raise DeviceError('Device is disconnected')
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; refresh names before saving')
                        from name_edit import rename
                        record=rename(self.device,data['source'],data['name'],data['expected'])
                        self.emit('name_written',request_id=data['request_id'],state=record,connection_serial=self.connection_serial)
                    elif cmd == 'name_read':
                        if not self.device:raise DeviceError('Device is disconnected')
                        from name_edit import read_name
                        request_id,source=data
                        state=read_name(self.device,source)
                        self.emit('name_snapshot',request_id=request_id,state=state,connection_serial=self.connection_serial)
                    elif cmd == 'digital_pair':
                        if not self.device:raise DeviceError('Device is disconnected')
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; refresh mixer before linking')
                        from digital_pair import convert
                        states=convert(self.device,data['bus'],data['source'],data['linked'],data['mono'],data['pairs'])
                        self.emit('digital_pair_state',request_id=data['request_id'],bus=data['bus'],source=data['source'],states=states,connection_serial=self.connection_serial)
                    elif cmd == 'membership_set':
                        if not self.device:raise DeviceError('Device is disconnected')
                        if data['connection_serial']!=self.connection_serial:raise DeviceError('Connection changed; refresh mixer sources')
                        from mixer_membership import change
                        state=change(self.device,data['bus'],data['source'],data['stereo'],data['value'],data['mono'],data['pairs'])
                        state['connection_serial']=self.connection_serial
                        self.emit('input_snapshot',state=state)
                        self.input_next_poll=0
                    elif cmd == 'mixer_inclusion':
                        if not self.device:raise DeviceError('Device is disconnected')
                        bus,source,stereo,value,mono_mask,stereo_mask=data
                        actual=self.device.write_mixer_inclusion(bus,source,stereo,value,expected_mono=mono_mask,expected_stereo=stereo_mask)
                        self.emit('input_written',channel='mix_channel',bus=bus,source=source,name='inclusion',actual=actual)
                        self.input_next_poll=0
                    elif cmd == 'routing_preflight':
                        if not self.device: raise DeviceError('Device is disconnected')
                        if data['connection_serial'] != self.connection_serial:
                            raise DeviceError('Connection changed. Read routing again.')
                        from routing_presets import preflight
                        preflight(self.device, data['changes'])
                        self.emit('routing_ready', request_id=data['request_id'])
                    elif cmd == 'routing_set':
                        if not self.device: raise DeviceError('Device is disconnected')
                        if data['connection_serial'] != self.connection_serial:
                            raise DeviceError('Connection changed. Read routing again.')
                        actual = self.device.write_output_route(data['destination'], data['source_code'], expected_source=data['expected_source'])
                        self.emit('routing_written', request_id=data['request_id'], destination=data['destination'],
                                  previous=data['expected_source'], actual=actual, undo=data.get('undo',False))
                    elif cmd == 'routing_capture':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        from routing_capture import read_routing
                        state = read_routing(self.device)
                        state['demo'] = isinstance(self.device, DemoAF16Rig)
                        state['connection_serial'] = self.connection_serial
                        self.emit('routing_snapshot', request_id=data, state=state)
                    elif cmd == 'set':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        name, value = data
                        actual = self.device.write_bool(name, value)
                        self.emit('written', name=name, actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.poll()
                    elif cmd == 'monitor_target':
                        if not self.device:raise DeviceError('Device is disconnected')
                        from monitor_level import set_level
                        actual=set_level(self.device,data)
                        self.emit('volume_written',actual=actual,diagnostic=getattr(self.device,'last_write',None))
                        self.poll()
                    elif cmd == 'phones_target':
                        if data['connection_serial']!=self.connection_serial:
                            raise DeviceError('Connection changed. Read Phones level again.')
                        from phones_level import set_level
                        actual=set_level(self.device,data['db'],data['expected_raw'])
                        self.emit('phones_written',actual=actual,request_id=data['request_id'],
                                  connection_serial=self.connection_serial,
                                  diagnostic=getattr(self.device,'last_write',None))
                    elif cmd == 'phones_read':
                        self.emit('phones_snapshot',state=self.device.headphones_snapshot(),connection_serial=self.connection_serial)
                    elif cmd == 'volume':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        actual = self.device.step_volume(data)
                        self.emit('volume_written', actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.poll()
                    elif cmd == 'input_select':
                        self.input_channel = data
                        if data is not None and self.device:
                            self.poll_input()
                    elif cmd == 'input_set':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        channel, name, value = data
                        actual = self.device.write_input_bool(channel, name, value)
                        self.emit('input_written', channel=channel, name=name, actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'input_gain':
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, direction = data
                        actual = self.device.step_input_gain(channel, direction)
                        self.emit('input_gain_written', channel=channel, actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd in ('monitor_ab_destination','monitor_ab_trim'):
                        if not self.device:raise DeviceError('Device is disconnected')
                        name=cmd.removeprefix('monitor_')
                        actual=self.device.write_ab_destination(data) if name=='ab_destination' else self.device.step_ab_trim(data)
                        self.emit('input_written',channel='monitor_settings',name=name,actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd in ('monitor_ab_enabled','monitor_ab_selected'):
                        if not self.device:raise DeviceError('Device is disconnected')
                        name=cmd.removeprefix('monitor_')
                        actual=getattr(self.device,'write_'+name)(data)
                        self.emit('input_written',channel='monitor_settings',name=name,actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'monitor_dim_depth':
                        if not self.device:raise DeviceError('Device is disconnected')
                        actual=self.device.write_dim_depth(data)
                        self.emit('input_written',channel='monitor_settings',name='dim_depth',actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'output_link':
                        if not self.device:raise DeviceError('Device is disconnected')
                        channel,value=data
                        actual=self.device.write_output_link(channel,value)
                        self.emit('input_written',channel='output',output=channel,name='link',actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'output_target':
                        from output_target import set_level
                        channel,value,expected,serial=data
                        if serial!=self.connection_serial:raise DeviceError('Connection changed; output target discarded')
                        actual=set_level(self.device,channel,value,expected)
                        self.emit('input_written',channel='output',output=channel,name='level',actual=actual)
                        self.input_next_poll=0
                    elif cmd == 'output_gain':
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, direction = data
                        actual = self.device.step_output_gain(channel,direction)
                        self.emit('input_written', channel='output', output=channel, name='level', actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'mix_channel_level':
                        if not self.device:raise DeviceError('Device is disconnected')
                        bus,source,direction=data
                        actual=mixer_device(self.device, source).step_mix_channel_level(bus,source,direction)
                        self.emit('input_written',channel='mix_channel',bus=bus,source=source,name='level',actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'stereo_level':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        bus, source, direction = data
                        actual = mixer_device(self.device, source).step_stereo_channel_level(bus, source, direction)
                        self.emit('input_written', channel='mix_channel', bus=bus, source=source,
                                  name='stereo_level', actual=actual, diagnostic=self.device.last_write)
                        self.input_next_poll = 0
                    elif cmd in ('pair_send_level','pair_send_mute'):
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        bus, source, aux, value = data
                        if cmd == 'pair_send_level':
                            actual = mixer_device(self.device, source).step_stereo_send_level(bus,source,aux,value)
                        else:
                            actual = mixer_device(self.device, source).write_stereo_send_mute(bus,source,aux,value)
                        self.emit('input_written',channel='mix_channel',bus=bus,source=source,
                                  name=cmd,aux=aux,actual=actual,diagnostic=self.device.last_write)
                        self.input_next_poll=0
                    elif cmd in ('send_mute','send_level'):
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        bus, source, aux, value = data
                        if cmd == 'send_level':
                            actual = mixer_device(self.device, source).step_send_level(bus, source, aux, value)
                            name = f'aux{aux}_send_level'
                        else:
                            actual = mixer_device(self.device, source).write_send_mute(bus, source, aux, value)
                            name = f'send{aux}'
                        self.emit('input_written', channel='mix_channel', bus=bus, source=source,
                                  name=name, actual=actual, diagnostic=self.device.last_write)
                        self.input_next_poll = 0
                    elif cmd == 'adjust_pan':
                        if not self.device:
                            raise DeviceError('Device disconnected')
                        bus, source, action = data
                        actual = mixer_device(self.device, source).adjust_channel_pan(bus,source,action)
                        self.emit('input_written',channel='mix_channel',bus=bus,source=source,
                                  name='pan',actual=actual,diagnostic=self.device.last_write)
                        self.input_next_poll = 0
                    elif cmd == 'record_pan':
                        if not self.device:
                            raise DeviceError('Device disconnected')
                        bus, source, label = data
                        if label not in ('Left','Centre','Right'):
                            raise ValueError('Unknown pan position')
                        state = mixer_device(self.device, source).mix_channel_snapshot(bus,source)
                        raw = state['raw'].get('pan')
                        if raw is None or state['mono_selected'] != 1 or state['stereo_selected'] != 0:
                            raise DeviceError('Choose an included mono channel with a valid pan reading')
                        scan = self.device.scan_pan_positions()
                        raw = scan['values'].get(f'{bus} {source}', raw)
                        self.emit('pan_recorded', scan=scan, channel='mix_channel', bus=bus, source=source,
                                  label=label, raw=raw, sampled_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    elif cmd == 'mix_channel_pair':
                        if not self.device:
                            raise DeviceError('Device is disconnected')
                        bus, source, control, value = data
                        actual = mixer_device(self.device, source).write_stereo_channel_switch(bus, source, control, value)
                        self.emit('input_written', channel='mix_channel', bus=bus, source=source,
                                  name=control, actual=actual, pair=True, diagnostic=self.device.last_write)
                        self.input_next_poll = 0
                    elif cmd in ('mix_channel_mute','mix_channel_solo'):
                        if not self.device:raise DeviceError('Device is disconnected')
                        bus,source,value=data
                        control = cmd.removeprefix('mix_channel_')
                        method = getattr(mixer_device(self.device, source), 'write_mix_channel_' + control)
                        actual = method(bus, source, value)
                        self.emit('input_written',channel='mix_channel',bus=bus,source=source,name=control,actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'cue_enable':
                        if not self.device:raise DeviceError('Device is disconnected')
                        actual=self.device.write_cue_enabled(data)
                        self.emit('input_written',channel='masters',name='cue_enable',actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'aux_link':
                        if not self.device:raise DeviceError('Device is disconnected')
                        pair,value=data
                        actual=self.device.write_aux_link(pair,value)
                        self.emit('input_written',channel='aux_links',name='link'+str(pair)+str(pair+1),actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd in ('aux_mute','aux_pre'):
                        if not self.device:raise DeviceError('Device is disconnected')
                        bus,value=data
                        actual=getattr(self.device,'write_'+cmd)(bus,value)
                        self.emit('input_written',channel='masters',name=bus+'_'+cmd.removeprefix('aux_'),actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'master_step':
                        if not self.device:raise DeviceError('Device is disconnected')
                        bus,direction=data
                        actual=self.device.step_mixer_master(bus,direction)
                        self.emit('input_written',channel='masters',name=bus,actual=actual,
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'phones_record':
                        if not self.device:raise DeviceError('Device is disconnected')
                        if type(data) is not str or not data.strip() or len(data.strip())>80:raise ValueError('Enter a preset label of 1–80 characters')
                        data=data.strip()
                        state=self.device.headphones_snapshot()
                        if state.get('preset_raw') is None:raise DeviceError('Headphone preset read failed; refresh before recording')
                        self.emit('headphone_recorded',label=data,state=state,
                                  sampled_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
                        self.input_next_poll=0
                    elif cmd in ('mini_gain','mini_set','mini_source'):
                        if not self.device:raise DeviceError('Device is disconnected')
                        if cmd=='mini_source':
                            self.device.set_rear_pair_source(3,False)
                            self.emit('input_source_written',channel='mini',actual=0,diagnostic=getattr(self.device,'last_write',None))
                        else:
                            channel=data[0]
                            actual=self.device.step_mini_gain(channel,data[1]) if cmd=='mini_gain' else self.device.write_mini_switch(channel,data[1],data[2])
                            name=('gain' if cmd=='mini_gain' else data[1])+str(channel)
                            self.emit('input_written',channel='mini',name=name,actual=actual,diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=0
                    elif cmd == 'front_gain':
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, kind, direction = data
                        actual = self.device.step_front_gain(channel, kind, direction)
                        self.emit('input_written', channel='front', name='gain'+str(channel), actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'front_instrument':
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, value = data
                        actual = self.device.write_front_instrument(channel, value)
                        self.emit('input_written', channel='front', name='instrument'+str(channel), actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd in ('front_phase', 'front_hpf', 'front_pad'):
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, kind, value = data
                        control = cmd.removeprefix('front_')
                        method = getattr(self.device, 'write_front_'+control)
                        actual = method(channel, kind, value)
                        self.emit('input_written', channel='front', name=control+str(channel), actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'front_source':
                        if not self.device: raise DeviceError('Device is disconnected')
                        self.device.set_rear_pair_source(1, False)
                        self.emit('input_source_written', channel='front', actual=0,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'front_link':
                        if not self.device: raise DeviceError('Device is disconnected')
                        kind, value = data
                        actual = self.device.write_front_link(kind, value)
                        self.emit('input_written', channel='front', name=kind, actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'input_source':
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, force = data
                        actual = self.device.set_rear_pair_source(channel, force)
                        self.emit('input_source_written', channel=channel, actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'input_link':
                        if not self.device: raise DeviceError('Device is disconnected')
                        channel, value = data
                        actual = self.device.write_input_link(channel, value)
                        self.emit('input_link_written', channel=channel, actual=actual,
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = 0
                    elif cmd == 'disconnect':
                        self.reconnect.stop()
                        self.discard_pending_writes()
                        self.disconnect()
                        self.emit('disconnected')
                    elif self.device and time.monotonic() >= self.next_poll:
                        self.poll()
                    elif self.device and self.input_channel is not None and time.monotonic() >= self.input_next_poll:
                        self.poll_input()
                    elif self.device and self.meters_enabled and not self.meters_failed and not self.names_paused and time.monotonic()>=self.next_meter:
                        self.poll_meter_if_due()
                    elif self.device and self.names_scan is not None and not self.names_scan.done and not self.names_paused:
                        self.read_name_slice()
                except (DeviceError, OSError, ValueError, AttributeError) as e:
                    if isinstance(e, DeviceDisconnected) or cmd == 'connect' or not self.device:
                        self.emit('error', message=str(e))
                        self.disconnect()
                        self.discard_pending_writes()
                        self.schedule_reconnect(str(e))
                    elif cmd in ('scene_read','scene_set'):
                        self.emit('scene_error',request_id=data['request_id'],message=str(e),connection_serial=self.connection_serial)
                    elif cmd in ('midi_read','midi_remap','midi_bank_size','midi_ports_read','midi_ports_set'):
                        self.emit('midi_error',request_id=data['request_id'],message=str(e),connection_serial=self.connection_serial,diagnostic=getattr(self.device,'last_write',None) if cmd in ('midi_remap','midi_bank_size') else None)
                    elif cmd == 'stereo_pair':
                        self.emit('pair_error',bus=data[0],source=data[1],message=str(e))
                    elif cmd == 'masters_read':
                        self.emit('masters_error',message=str(e))
                    elif cmd in ('preamp_set','preamp_source','preamp_pair_gain','preamp_pad'):
                        self.emit('preamp_error',source=data[0] if cmd!='preamp_source' else 1,operation=True,message=str(e))
                    elif cmd == 'stereo_pan':
                        self.emit('input_error',channel='mix_channel',bus=data['bus'],source=data['source'],
                                  name='stereo_pan',message=str(e),diagnostic=getattr(self.device,'last_write',None))
                    elif cmd == 'console_set':
                        self.emit('input_error', channel='masters' if data[1] == 0 else 'mix_channel', bus=data[0], source=data[1],
                                  name=data[0] if data[1] == 0 else data[2], operation='master_step', message=str(e))
                    elif cmd == 'console_read':
                        self.emit('console_error', bus=data[0], source=data[1], message=str(e))
                    elif cmd in ('preset_read','preset_status','preset_action','preset_rename','preset_copy'):
                        self.emit('preset_error',request_id=data['request_id'],message=str(e),connection_serial=self.connection_serial,rename_report=getattr(self.device,'last_preset_rename',None) if cmd=='preset_rename' else None)
                    elif cmd == 'digital_pair':
                        self.emit('digital_pair_error',request_id=data['request_id'],bus=data['bus'],source=data['source'],message=str(e),connection_serial=self.connection_serial)
                    elif cmd == 'membership_set':
                        self.emit('input_error',channel='mixer_sources',bus=data['bus'],source=data['source'],message=str(e))
                    elif cmd == 'name_set':
                        self.emit('name_write_error',request_id=data['request_id'],message=str(e))
                    elif cmd == 'name_read':
                        self.emit('name_error',request_id=data[0],message=str(e))
                    elif cmd in ('routing_set','routing_preflight'):
                        self.emit('routing_error',request_id=data['request_id'],message=str(e))
                    elif cmd == 'routing_capture':
                        self.emit('routing_error', request_id=data, message=str(e))
                    elif cmd in ('monitor_dim_depth','monitor_ab_enabled','monitor_ab_selected','monitor_ab_destination','monitor_ab_trim'):
                        self.emit('input_error',channel='monitor_settings',name=cmd.removeprefix('monitor_'),message=str(e),
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd in ('output_gain','output_link','output_target'):
                        self.emit('input_error', channel='output', output=data[0], name='link' if cmd=='output_link' else 'level', message=str(e),
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = time.monotonic()+0.25
                    elif cmd == 'aux_link':
                        self.emit('input_error',channel='aux_links',pair=data[0],message=str(e),diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd in ('mixer_inclusion','adjust_pan','record_pan','mix_channel_mute','mix_channel_solo','mix_channel_level','mix_channel_pair','stereo_level','send_mute','send_level','pair_send_mute','pair_send_level'):
                        self.emit('input_error',channel='mix_channel',bus=data[0],source=data[1],message=str(e),diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd == 'cue_enable':
                        self.emit('input_error',channel='masters',name='cue',operation=cmd,message=str(e),diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd in ('master_step','aux_mute','aux_pre'):
                        self.emit('input_error',channel='masters',name=data[0],operation=cmd,message=str(e),
                                  diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd == 'clock_set':
                        self.emit('clock_write_error',channel='clock',message=str(e),request_id=data['request_id'],
                            connection_serial=self.connection_serial,diagnostic=getattr(self.device,'last_write',None))
                        self.device.clock_status_failure=None;self.input_next_poll=0
                    elif cmd == 'phones_target':
                        self.emit('phones_write_error',message=str(e),request_id=data['request_id'],
                                  connection_serial=self.connection_serial,
                                  diagnostic=getattr(self.device,'last_write',None))
                    elif cmd == 'phones_read':
                        self.emit('phones_error',message=str(e),connection_serial=self.connection_serial)
                    elif cmd == 'phones_record':
                        self.emit('input_error',channel='phones',name='record',message=str(e))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd in ('mini_gain','mini_set','mini_source'):
                        name='source' if cmd=='mini_source' else ('gain' if cmd=='mini_gain' else data[1])+str(data[0])
                        self.emit('input_error',channel='mini',name=name,message=str(e),diagnostic=getattr(self.device,'last_write',None))
                        self.input_next_poll=time.monotonic()+0.25
                    elif cmd in ('front_link', 'front_source', 'front_phase', 'front_hpf', 'front_pad', 'front_gain', 'front_instrument'):
                        self.emit('input_error', channel='front', name=((cmd.removeprefix('front_'))+str(data[0]) if cmd in ('front_phase', 'front_hpf', 'front_pad', 'front_gain', 'front_instrument') else data[0] if data else 'source'), message=str(e),
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = time.monotonic() + 0.25
                    elif cmd in ('input_link', 'input_source'):
                        self.emit('input_error', channel=data[0], name='link', message=str(e),
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = time.monotonic() + 0.25
                    elif cmd == 'input_gain':
                        self.emit('input_error', channel=data[0], name='gain', message=str(e),
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = time.monotonic() + 0.25
                    elif cmd == 'input_set':
                        self.emit('input_error', channel=data[0], name=data[1], message=str(e),
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.input_next_poll = time.monotonic() + 0.25
                    elif cmd in ('set', 'volume', 'monitor_target'):
                        self.names_paused = True
                        self.emit('command_error', message=str(e),
                                  diagnostic=getattr(self.device, 'last_write', None))
                        self.next_poll = time.monotonic() + 0.25
                    else:
                        self.names_paused = True
                        self.poll_failures += 1
                        if self.poll_failures >= 3:
                            self.emit('error', message=str(e))
                            self.disconnect()
                            self.discard_pending_writes()
                            self.schedule_reconnect(str(e))
                        else:
                            self.emit('recovering', message=str(e))
                            self.next_poll = time.monotonic() + 0.5
        finally:
            self.disconnect()

class App:
    def __init__(self, root, demo=False, capture_path=None):
        self.root, self.demo = root, demo
        from name_sync import NameCache
        self.name_cache = NameCache()
        self.state, self.info, self.history = {}, {}, []
        from event_log import EventLog
        self.event_log=EventLog();self.event_log_window=None
        self.input_window = None
        self.last_input_state = {}
        self.last_front_state = {}
        self.last_mini_state = {}
        self.last_mix_channel_state = {}
        self.last_aux_links_state = {}
        self.last_master_state = {}
        self.last_headphone_state = {}
        self.pan_samples = []
        self.previous_pan_scans = {}
        self.headphone_samples = []
        self.last_routing = {}
        self.last_output_state = {}
        self.last_monitor_settings_state = {}
        self.pending, self.connected = False, False
        self.stale = False
        self.events = queue.Queue()
        root.title('AF16Rig Linux Control — BETA RC' + (' — DEMO' if demo else ''))
        from window_state import restore
        restore(root)
        root.configure(bg=BG)
        root.option_add('*Font', ('DejaVu Sans', 10))
        self.worker = Worker(self.events, demo)
        self.worker.start()
        self.worker.commands.put(('meters_enable',True))
        self.worker.commands.put(('preamp_enable',True))
        self.build()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.drain)
        root.after(150, self.connect)
        if capture_path:
            root.after(1500, lambda: self.capture(capture_path))

    def label(self, parent, text='', **kwargs):
        kwargs.setdefault('fg', TEXT)
        from mixer_view import QuietLabel
        return QuietLabel(parent, text=text, bg=parent.cget('bg'), **kwargs)

    def build(self):
        from mixer_view import build_console
        build_console(self)

    def make_panel(self):
        from mixer_view import EmbeddedPanel
        self.dashboard.cancel_drags()
        self.dashboard.active = False
        self.dashboard.frame.pack_forget()
        return EmbeddedPanel(self)

    def show_mixer(self):
        panel=self.input_window
        self.input_window=None
        try:
            if panel: panel.close()
        finally:
            # Navigation visibility is independent of control refresh/readback.
            self.worker.commands.put(('input_select',None))
            self.dashboard.active=True
            from mixer_view import show_page
            show_page(self,self.dashboard.frame)
            self.dashboard.next_source=getattr(self.dashboard,'bank_start',1)
            self.dashboard.next_read=0
            self.page_title.config(text='MIXER')

    def connect(self):
        if self.pending:
            return
        self.pending = True
        self.connected = False
        self.name_cache.reset(None)
        for strip in self.dashboard.strips.values():strip.refresh_title()
        self.update_controls()
        self.connect_button.config(state='disabled')
        self.message.config(text='Connecting to AF16Rig…', fg=MUTED)
        self.worker.commands.put(('connect', None))

    def toggle(self, name):
        if self.pending or self.stale or not self.connected or not self.state.get('writes_available'):
            return
        current = self.state.get(name)
        if current not in (0, 1):
            return
        self.pending = True
        self.update_controls()
        self.message.config(text=f'Updating {name}…', fg=MUTED)
        self.worker.commands.put(('set', (name, not bool(current))))

    @staticmethod
    def format_level(raw):
        return '−∞ dB' if raw == -32768 else f'{raw / VOLUME_UNITS_PER_DB:.2f} dB'

    def step_volume(self, direction):
        if self.pending or self.stale or not self.connected or not self.state.get('writes_available'):
            return
        self.pending = True
        self.update_controls()
        self.message.config(text='Updating speaker level…', fg=MUTED)
        self.worker.commands.put(('volume', direction))

    def target_volume(self,value):
        if self.pending or self.stale or not self.connected or not self.state.get('writes_available'):return False
        if not isinstance(value,(int,float)) or not VOLUME_MIN_RAW<=round(value*VOLUME_UNITS_PER_DB)<=VOLUME_MAX_RAW:return False
        self.pending=True;self.update_controls()
        self.message.config(text='Updating monitor level…',fg=MUTED)
        self.worker.commands.put(('monitor_target',value));return True

    def update_controls(self):
        from mixer_view import configure_changed
        level = self.state.get('speaker_level_signed')
        volume_ready = (self.connected and not self.pending and not self.stale
                        and self.state.get('writes_available') and isinstance(level, int) and VOLUME_MIN_RAW <= level <= VOLUME_MAX_RAW)
        for direction, button in self.volume_buttons.items():
            enabled = volume_ready and ((direction < 0 and level > VOLUME_MIN_RAW) or (direction > 0 and level < VOLUME_MAX_RAW))
            configure_changed(button,state='normal' if enabled else 'disabled')
        for name, (label, button) in self.controls.items():
            value = self.state.get(name) if self.connected else None
            configure_changed(label,text=('On' if value == 1 else 'Off') if value in (0, 1) else '—',
                         fg=ACCENT if value == 1 else TEXT)
            configure_changed(button,text=name.upper(), bg=ACCENT if value == 1 else '#383c41', fg=BG if value == 1 else TEXT,
                          state='normal' if self.connected and not self.pending and not self.stale and self.state.get('writes_available') else 'disabled')

    def drain(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.history.append({'time_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), **event})
            self.history = self.history[-300:]
            log=getattr(self,'event_log',None)
            if log is not None and log.capture(event,getattr(self.worker,'connection_serial',None)):
                self.log_button.config(text=f'Log ({len(log.records)})')
                if self.event_log_window:self.event_log_window.refresh()
            kind = event['kind']
            from quick_names import finish_rename
            finish_rename(self,event)
            self.dashboard.handle(event)
            if kind in ('clock_written','clock_write_error') and self.input_window and hasattr(self.input_window,'clock_result'):
                self.input_window.clock_result(event)
            if self.input_window and hasattr(self.input_window,'handle_meter_event'):
                self.input_window.handle_meter_event(event)
            if kind=='reconnect_wait':
                self.connection.config(text=f'Reconnecting in {event["delay"]}s · attempt {event["attempt"]}',fg=MUTED)
                self.message.config(text=event['message']+' · automatic reconnect pending',fg=MUTED)
                continue
            if kind=='reconnect_disabled':
                if not self.connected:self.connection.config(text='Disconnected · auto reconnect off',fg=MUTED)
                continue
            if kind in ('meter_frame','meter_error','masters_snapshot','masters_error','preamp_state','preamp_error','pair_state','pair_error'):continue
            if kind == 'preset_state_reset':
                self.name_cache.reset(event.get('connection_serial'))
                self.state={};self.stale=True
                for name in ('last_routing','last_front_state','last_mini_state','last_mix_channel_state','last_aux_links_state','last_master_state','last_headphone_state','last_output_state','last_monitor_settings_state','last_input_state'):
                    setattr(self,name,{})
                for strip in self.dashboard.strips.values():strip.refresh_title()
                if self.input_window and hasattr(self.input_window,'connection_changed'):self.input_window.connection_changed()
                self.update_controls()
                continue
            if kind in ('scene_snapshot','scene_written','scene_error','midi_snapshot','midi_written','midi_error','midi_ports_snapshot','midi_ports_written','preset_snapshot','preset_status','preset_done','preset_renamed','preset_error'):
                if self.input_window:self.input_window.handle(event)
                continue
            if kind == 'auto_name':
                self.accept_name(event)
                continue
            if kind in ('name_snapshot','name_error','name_written','name_write_error'):
                if kind in ('name_snapshot','name_written'):self.accept_name(event)
                if self.input_window:self.input_window.handle(event)
                continue
            if kind in ('routing_snapshot', 'routing_error', 'routing_written', 'routing_ready'):
                if kind == 'routing_snapshot':
                    self.last_routing = event['state']
                if self.input_window:
                    self.input_window.handle(event)
                continue
            if kind=='pan_recorded':
                key = (event['bus'], event['source'])
                current = event['scan']['values']
                previous = self.previous_pan_scans.get(key)
                if previous is not None:
                    event['comparison'] = compare_pan_scans(previous, current)
                self.previous_pan_scans[key] = current
                self.pan_samples.append(dict(event))
                if self.input_window:
                    self.input_window.handle(event)
                continue
            if kind=='headphone_recorded':
                self.headphone_samples.append({'label':event['label'],'sampled_at':event['sampled_at'],'state':event['state']})
                self.last_headphone_state=event['state']
                if self.input_window:self.input_window.handle(event)
                continue
            if kind in ('input_snapshot', 'input_written', 'input_gain_written', 'input_link_written', 'input_source_written', 'input_error'):
                if kind == 'input_snapshot':
                    if event['state'].get('channel') == 'front': self.last_front_state = event['state']
                    elif event['state'].get('channel') == 'mini': self.last_mini_state = event['state']
                    elif event['state'].get('channel') == 'mix_channel': self.last_mix_channel_state = event['state']
                    elif event['state'].get('channel') == 'aux_links': self.last_aux_links_state = event['state']
                    elif event['state'].get('channel') == 'masters': self.last_master_state = event['state']
                    elif event['state'].get('channel') == 'phones': self.last_headphone_state = event['state']
                    elif event['state'].get('channel') == 'output': self.last_output_state = event['state']
                    elif event['state'].get('channel') == 'monitor_settings': self.last_monitor_settings_state = event['state']
                    else: self.last_input_state = event['state']
                if self.input_window:
                    self.input_window.handle(event)
                continue
            if kind == 'connected':
                self.previous_pan_scans.clear()
                self.name_cache.reset(event.get('connection_serial'))
                self.connected, self.pending, self.info = True, False, event['info']
                for name in ('last_routing','last_front_state','last_mini_state','last_mix_channel_state','last_aux_links_state','last_master_state','last_headphone_state','last_output_state','last_monitor_settings_state','last_input_state'):
                    setattr(self,name,{})
                if self.input_window and hasattr(self.input_window,'connection_changed'):self.input_window.connection_changed()
                self.connection.config(text='Demo connected' if self.demo else 'Connected · AF16Rig MIDI', fg=ACCENT)
                self.connect_button.config(text='Reconnect', state='normal')
                self.details.config(text='DEMO · no hardware' if self.demo else 'Native USB')
                self.message.config(text='Connected · live device readback', fg=MUTED)
            elif kind == 'snapshot':
                was_stale, self.stale = self.stale, False
                self.state = event['state']
                if was_stale and not self.pending:
                    self.message.config(text='Live readback restored.', fg=ACCENT)
                self.level.config(text=self.format_level(self.state['speaker_level_signed']))
                if not self.state.get('writes_available'):
                    self.message.config(text='Readback active. Controls disabled for unexpected state version or boolean values.', fg='#efba76')
            elif kind == 'written':
                self.pending = False
                self.state[event['name']] = event['actual']
                self.message.config(text=f'{event["name"].capitalize()} {"on" if event["actual"] else "off"} · readback confirmed', fg=ACCENT)
            elif kind == 'volume_written':
                self.pending = False
                self.state['speaker_level_signed'] = event['actual']
                self.state['speaker_level'] = event['actual'] & 0xffff
                self.level.config(text=self.format_level(event['actual']))
                self.state['speaker_level_db'] = event['actual'] / VOLUME_UNITS_PER_DB
                self.message.config(text=f'Speaker level {self.format_level(event["actual"])} · readback confirmed', fg=ACCENT)
            elif kind in ('command_error', 'recovering'):
                self.stale = True
                if kind == 'command_error':
                    self.pending = False
                self.message.config(text=event['message'], fg='#efba76')
            elif kind in ('error', 'disconnected'):
                self.connected, self.pending, self.state = False, False, {}
                self.name_cache.reset(None)
                for strip in self.dashboard.strips.values():strip.refresh_title()
                self.level.config(text='—')
                if self.input_window:
                    self.input_window.handle({'kind': 'input_error', 'channel': self.input_window.channel.get(), 'message': 'Device disconnected'})
                self.connection.config(text='Disconnected', fg=MUTED)
                self.connect_button.config(text='Connect', state='normal')
                self.message.config(text=event.get('message', 'Disconnected'), fg='#efba76')
            self.update_controls()
            if hasattr(self.dashboard,'monitor_strip'):self.dashboard.monitor_strip.refresh()
            if hasattr(self.dashboard,'phones_strip'):self.dashboard.phones_strip.refresh()
        self.root.after(20, self.drain)

    def open_ab_configuration(self):
        if self.input_window and not isinstance(self.input_window,ABConfigurationWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=ABConfigurationWindow(self)

    def open_monitor_settings(self):
        if self.input_window and not isinstance(self.input_window,MonitorSettingsWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MonitorSettingsWindow(self)

    def open_outputs(self):
        if self.input_window and not isinstance(self.input_window, OutputWindow):
            self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=OutputWindow(self)

    def open_aux_links(self):
        if self.input_window and not isinstance(self.input_window,AuxLinksWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=AuxLinksWindow(self)

    def accept_name(self,event):
        if not self.connected:return
        record=event['state']
        changed=self.name_cache.accept(event.get('connection_serial'),record,demo=self.demo)
        if event.get('connection_serial')!=self.name_cache.serial:return
        if changed:
            source=record['source']
            for index in {source,source-1 if source%2==0 else source}:
                strip=self.dashboard.strips.get(index)
                if strip:strip.refresh_title()
        if self.input_window and hasattr(self.input_window,'refresh_names'):
            self.input_window.refresh_names()
        count=len(self.name_cache.records)
        self.details.config(text=('DEMO' if self.demo else 'Native USB')+f' · Names {count}/60'+(' · read failed' if record['status']=='read_error' else ''))

    def open_event_log(self):
        from event_log_window import EventLogWindow
        if self.event_log_window:self.event_log_window.window.lift()
        else:self.event_log_window=EventLogWindow(self)

    def open_meters(self):
        from meters_window import MetersWindow
        if self.input_window and not isinstance(self.input_window,MetersWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MetersWindow(self)

    def open_mixer_scenes(self):
        from mixer_scene_window import MixerSceneWindow
        if self.input_window and not isinstance(self.input_window,MixerSceneWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MixerSceneWindow(self)

    def open_fader_scenes(self):
        from fader_scene_window import FaderSceneWindow
        if self.input_window and not isinstance(self.input_window,FaderSceneWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=FaderSceneWindow(self)

    def open_midi_config(self):
        from midi_window import MidiWindow
        if self.input_window and not isinstance(self.input_window,MidiWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MidiWindow(self)

    def open_clock_status(self):
        from clock_window import ClockWindow
        if self.input_window and not isinstance(self.input_window,ClockWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=ClockWindow(self)

    def open_device_presets(self):
        from presets_window import PresetsWindow
        if self.input_window and not isinstance(self.input_window,PresetsWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=PresetsWindow(self)

    def open_channel_names(self):
        from names_window import NamesWindow
        if self.input_window and not isinstance(self.input_window,NamesWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=NamesWindow(self)

    def open_mixer_sources(self):
        from mixer_sources import MixerSourcesWindow
        if self.input_window and not isinstance(self.input_window,MixerSourcesWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MixerSourcesWindow(self)

    def open_mix_channel(self):
        if self.input_window and not isinstance(self.input_window,MixChannelWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MixChannelWindow(self)

    def open_mixer_masters(self):
        if self.input_window and not isinstance(self.input_window,MixerMastersWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MixerMastersWindow(self)

    def open_headphones(self):
        if self.input_window and not isinstance(self.input_window,HeadphoneWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=HeadphoneWindow(self)

    def open_mini_inputs(self):
        if self.input_window and not isinstance(self.input_window,MiniInputWindow):self.input_window.close()
        if self.input_window:self.input_window.window.lift()
        else:self.input_window=MiniInputWindow(self)

    def open_front_gain(self):
        if self.input_window and not isinstance(self.input_window, FrontGainWindow):
            self.input_window.close()
        if self.input_window: self.input_window.window.lift()
        else: self.input_window = FrontGainWindow(self)

    def open_front_inputs(self):
        if self.input_window and not isinstance(self.input_window, FrontLinkWindow):
            self.input_window.close()
        if self.input_window: self.input_window.window.lift()
        else: self.input_window = FrontLinkWindow(self)

    def open_inputs(self):
        if self.input_window and not isinstance(self.input_window, InputWindow): self.input_window.close()
        if self.input_window:
            self.input_window.window.lift()
        else:
            self.input_window = InputWindow(self)

    def open_routing(self):
        from patchbay_window import PatchBayWindow as RoutingWindow
        if self.input_window and not isinstance(self.input_window, RoutingWindow):
            self.input_window.close()
        if self.input_window:
            self.input_window.window.lift()
        else:
            self.input_window = RoutingWindow(self)

    def save_report(self):
        path = filedialog.asksaveasfilename(title='Save AF16Rig test report',
            initialfile='AF16Rig-Linux-BETA RC-report.json', defaultextension='.json',
            filetypes=[('JSON report', '*.json')])
        if not path:
            return
        try:
            Path(path).write_text(json.dumps({'app': 'AF16Rig Linux Control BETA RC', 'demo': self.demo,
                'info': self.info, 'last_state': self.state, 'last_rear_input': self.last_input_state, 'last_front_input': self.last_front_state, 'last_front_minijack': self.last_mini_state, 'last_mixer_channel': self.last_mix_channel_state, 'last_aux_stereo_links': self.last_aux_links_state, 'last_mixer_masters': self.last_master_state, 'last_headphones': self.last_headphone_state, 'headphone_samples': self.headphone_samples, 'pan_samples': self.pan_samples, 'last_routing': self.last_routing, 'last_output': self.last_output_state, 'last_monitor_settings': self.last_monitor_settings_state, 'events': self.history, 'event_log': self.event_log.report(self.demo)}, indent=2) + '\n')
        except OSError as e:
            self.message.config(text=f'Could not save report: {e}', fg='#efba76')
        else:
            self.message.config(text='Report saved.', fg=ACCENT)

    def capture(self, path):
        # Optional local QA capture; Pillow is not required for normal use.
        from PIL import ImageGrab
        self.root.update_idletasks()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x+self.root.winfo_width(), y+self.root.winfo_height())).save(path)
        self.close()

    def close(self):
        from window_state import save
        save(self.root)
        self.closing = True
        self.worker.stop_event.set()
        self.worker.join(timeout=4)
        self.root.destroy()

class InputWindow:
    def __init__(self, app):
        self.app, self.state, self.pending = app, {}, False
        self.last_error = None
        self.loading = True
        self.window = app.make_panel()
        self.window.title('AF16Rig — Rear inputs — BETA RC')
        self.window.configure(bg=BG)
        self.window.geometry('760x760')
        self.window.minsize(740, 720)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        shell = tk.Frame(self.window, bg=BG, padx=24, pady=22)
        shell.pack(fill='both', expand=True)
        app.label(shell, 'REAR LINE INPUTS', font=('DejaVu Sans', 17, 'bold')).pack(anchor='w')
        app.label(shell, 'Edits the rear-panel path, including when a front input is active.', fg=MUTED,
                  wraplength=480, justify='left').pack(anchor='w', pady=(6, 18))
        selector = tk.Frame(shell, bg=BG)
        selector.pack(fill='x')
        app.label(selector, 'Input').pack(side='left', padx=(0, 12))
        self.channel = tk.IntVar(value=1)
        self.menu = tk.OptionMenu(selector, self.channel, *range(1, 17), command=self.select)
        self.menu.config(bg=PANEL, fg=TEXT, highlightthickness=0, width=6)
        self.menu.pack(side='left')
        gain_frame = tk.Frame(shell, bg=PANEL, padx=14, pady=12)
        gain_frame.pack(fill='x', pady=(18, 0))
        app.label(gain_frame, 'REAR INPUT GAIN', fg=MUTED, font=('DejaVu Sans', 9, 'bold')).pack(anchor='w')
        self.gain_label = app.label(gain_frame, '—', font=('DejaVu Sans', 22, 'bold'))
        self.gain_label.pack(anchor='w', pady=(4, 8))
        gain_row = tk.Frame(gain_frame, bg=PANEL)
        gain_row.pack(fill='x')
        self.gain_buttons = {}
        for direction, title in ((-1, 'Gain −1 dB'), (1, 'Gain +1 dB')):
            button = tk.Button(gain_row, text=title, command=lambda d=direction: self.step_gain(d),
                bg='#383c41', fg=TEXT, relief='flat', padx=14, pady=7, state='disabled', disabledforeground=MUTED)
            button.pack(side='left', padx=(0, 12))
            self.gain_buttons[direction] = button
        self.gain_detail = app.label(gain_frame, 'Initial control range: 0–12 dB', fg=MUTED, wraplength=500, justify='left', font=('DejaVu Sans', 9))
        self.gain_detail.pack(anchor='w', pady=(8, 0))
        row = tk.Frame(shell, bg=BG)
        row.pack(fill='x', pady=18)
        self.controls = {}
        self.field_status = {}
        for col, (name, title) in enumerate((('phase', 'POLARITY INVERT'), ('hpf', 'HIGH-PASS FILTER'), ('pad', 'PAD'), ('link', 'STEREO LINK'))):
            row.columnconfigure(col, weight=1, uniform='input')
            frame = tk.Frame(row, bg=PANEL, padx=14, pady=14)
            frame.grid(row=0, column=col, sticky='nsew', padx=(0, 8) if col == 0 else (8, 0))
            app.label(frame, title, fg=MUTED, font=('DejaVu Sans', 9, 'bold')).pack(anchor='w')
            label = app.label(frame, '—', font=('DejaVu Sans', 20, 'bold'))
            label.pack(anchor='w', pady=8)
            button = tk.Button(frame, text='Waiting…', command=lambda n=name: self.toggle(n),
                bg='#383c41', fg=TEXT, relief='flat', padx=12, pady=8, state='disabled', disabledforeground=MUTED)
            button.pack(fill='x')
            self.controls[name] = label, button
            detail = app.label(frame, '', fg=MUTED, wraplength=132, justify='left', font=('DejaVu Sans', 9))
            detail.pack(anchor='w', pady=(8, 0))
            self.field_status[name] = detail
        actions = tk.Frame(shell, bg=BG)
        actions.pack(fill='x', pady=(0, 12))
        tk.Button(actions, text='Refresh', command=self.select, bg=PANEL, fg=TEXT, relief='flat', padx=14, pady=7).pack(side='left')
        tk.Button(actions,text='Copy error',command=self.copy_error,bg=PANEL,fg=TEXT,relief='flat',padx=14,pady=7).pack(side='left',padx=8)
        tk.Button(actions,text='Dismiss error',command=self.dismiss_error,bg=PANEL,fg=TEXT,relief='flat',padx=14,pady=7).pack(side='left')
        self.message = app.label(shell, 'Reading input…', fg=MUTED, wraplength=780, justify='left')
        self.message.pack(anchor='w')
        self.source_detail = app.label(shell, '', fg=MUTED, wraplength=620, justify='left', font=('DejaVu Sans', 9))
        self.source_detail.pack(anchor='w', pady=(10, 0))
        self.source_button = tk.Button(shell, text='Use rear pair', command=self.set_source, bg=PANEL, fg=TEXT, relief='flat', padx=14, pady=7)
        self.source_button.pack(anchor='w', pady=(8, 0))
        self.select()

    def copy_error(self):
        if getattr(self,'last_error',None):
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(self.last_error)

    def dismiss_error(self):
        self.last_error=None
        self.message.config(text='Live readback',fg=MUTED)

    def select(self, unused=None):
        if self.pending: return
        self.loading = True
        self.state = {}
        self.refresh()
        self.last_error=None
        self.message.config(text='Reading input…', fg=MUTED)
        self.app.worker.commands.put(('input_select', self.channel.get()))

    def refresh(self):
        context = self.state.get('link_context', {})
        raw = context.get('raw', {})
        if raw:
            text = 'Source status unavailable.'
            if self.channel.get() <= 4:
                text += '\nUse rear pair switches both inputs to the rear sockets. Automatic pair restores front detection.'
        else:
            text = 'Source status unavailable' if context.get('errors') else ''
        left = ((self.channel.get()-1)//2)*2
        forced = raw.get('force_rear')
        self.source_forced = forced is not None and ((forced >> left) & 3) == 3
        self.source_button.config(text='Automatic pair' if self.source_forced else 'Use rear pair',
            state='normal' if self.channel.get() <= 4 and forced is not None and self.app.connected and not self.pending else 'disabled')
        self.source_detail.config(text=text)
        gain = self.state.get('gain_db')
        self.gain_label.config(text=f'{gain:.2f} dB' if gain is not None else ('—' if self.loading else 'Unavailable'))
        self.gain_detail.config(text=self.state.get('errors', {}).get('gain', 'Initial control range: 0–12 dB'))
        gain_ready = self.app.connected and not self.pending and self.state.get('control_available', {}).get('gain', False)
        for direction, button in self.gain_buttons.items():
            enabled = gain_ready and gain is not None and ((direction < 0 and gain > 0) or (direction > 0 and gain < 12))
            button.config(state='normal' if enabled else 'disabled')
        for name, (label, button) in self.controls.items():
            value = self.state.get(name)
            label.config(text=('On' if value == 1 else 'Off') if value in (0, 1) else ('—' if self.loading else 'Unavailable'), fg=ACCENT if value == 1 else TEXT)
            ready = (self.app.connected and not self.pending and
                     self.state.get('control_available', {}).get(name, False))
            button.config(text=('Turn off' if value == 1 else 'Turn on') if value in (0, 1) else ('Waiting…' if self.loading else 'Unavailable'),
                          state='normal' if ready and value in (0, 1) else 'disabled')
            detail = self.state.get('errors', {}).get(name, '')
            if name == 'link':
                pair = self.state.get('pair', [((self.channel.get()-1)//2)*2+1, ((self.channel.get()-1)//2)*2+2])
                bank=self.state.get('link_bank','rear')
                bank_label={'rear':'Rear','line':'Front line / instrument','mic':'Front microphone'}.get(bank,bank)
                detail = detail or f'Pair {pair[0]}–{pair[1]} · {bank_label} link · linked settings may sync'
                if self.state.get('link_mixed'):
                    label.config(text='Mixed', fg='#efba76')
                    button.config(text='Link pair', state='normal' if ready else 'disabled')
            self.field_status[name].config(text=detail)
        self.menu.config(state='disabled' if self.pending else 'normal')

    def toggle(self, name):
        if self.pending or not self.app.connected or not self.state.get('control_available', {}).get(name, False):
            return
        value = self.state.get(name)
        if name == 'link' and self.state.get('link_mixed'):
            value = 0  # The button is explicitly labelled Link pair.
        if value not in (0, 1): return
        self.last_error=None
        self.pending = True
        self.refresh()
        self.message.config(text='Updating input…', fg=MUTED)
        if name == 'link':
            self.app.worker.commands.put(('input_link', (self.channel.get(), not bool(value))))
        else:
            self.app.worker.commands.put(('input_set', (self.channel.get(), name, not bool(value))))

    def set_source(self):
        if self.pending or not self.app.connected or self.channel.get() > 4: return
        self.last_error=None
        self.pending = True
        force = not self.source_forced
        self.refresh()
        self.message.config(text='Selecting rear sockets…' if force else 'Restoring automatic source selection…', fg=MUTED)
        self.app.worker.commands.put(('input_source', (self.channel.get(), force)))

    def step_gain(self, direction):
        if self.pending or not self.app.connected or not self.state.get('control_available', {}).get('gain', False): return
        self.last_error=None
        self.pending = True
        self.refresh()
        self.message.config(text='Updating input gain…', fg=MUTED)
        self.app.worker.commands.put(('input_gain', (self.channel.get(), direction)))

    def handle(self, event):
        channel = event.get('channel', event.get('state', {}).get('channel'))
        if channel != self.channel.get(): return
        self.loading = False
        if event['kind'] == 'input_snapshot':
            self.state = event['state']
            errors = self.state.get('errors', {})
            if not getattr(self,'last_error',None):
                self.message.config(text=('One or more controls are unavailable; waiting for device readback.' if errors else 'Live readback'), fg=MUTED)
        elif event['kind'] == 'input_source_written':
            self.pending = False
            self.message.config(text='Source selection confirmed. Retry stereo link.', fg=ACCENT)
        elif event['kind'] == 'input_link_written':
            self.pending = False
            self.state.update(link=event['actual'], link_bits=[event['actual']]*2, link_mixed=False)
            self.message.config(text='Stereo link confirmed for both channels.', fg=ACCENT)
        elif event['kind'] == 'input_gain_written':
            self.pending = False
            self.state.update(gain_raw=event['actual'], gain_signed=event['actual'], gain_db=event['actual']/256)
            self.message.config(text='Gain confirmed by device readback.', fg=ACCENT)
        elif event['kind'] == 'input_written':
            self.pending = False
            self.state[event['name']] = event['actual']
            self.message.config(text='Change confirmed by device readback.', fg=ACCENT)
        else:
            self.pending = False
            name = event.get('name')
            if name == 'gain' and self.state:
                self.state.update(gain_raw=None, gain_signed=None, gain_db=None)
                self.state.setdefault('control_available', {})['gain'] = False
                self.state.setdefault('errors', {})['gain'] = event['message']
            elif name in self.controls and self.state:
                self.state[name] = None
                self.state.setdefault('control_available', {})[name] = False
                self.state.setdefault('errors', {})[name] = event['message']
            else:
                self.state = {}
            self.last_error=event['message']
            self.message.config(text=self.last_error, fg='#efba76')
        self.refresh()

    def close(self):
        self.app.worker.commands.put(('input_select', None))
        self.app.input_window = None
        self.window.destroy()


class FrontLinkWindow:
    def __init__(self, app):
        self.app, self.state, self.pending = app, {}, False
        self.channel = tk.StringVar(value='front')
        self.window = app.make_panel()
        self.window.title('AF16Rig — Front 1–2 — BETA RC')
        self.window.configure(bg=BG)
        self.window.geometry('720x760')
        self.window.minsize(700, 740)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        shell = tk.Frame(self.window, bg=BG, padx=24, pady=22)
        shell.pack(fill='both', expand=True)
        app.label(shell, 'FRONT INPUTS 1–2', font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell, 'Use the link matching the connected front inputs.\nBoth inputs must use compatible modes.',
                  fg=MUTED, justify='left').pack(anchor='w', pady=(8,16))
        self.source_label = app.label(shell, 'Reading source selection…', fg=MUTED, justify='left', wraplength=640)
        self.source_label.pack(anchor='w', pady=(0,8))
        self.source_button = tk.Button(shell,text='Enable front detection for 1–2',command=self.enable_front,
            bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=8,state='disabled')
        self.source_button.pack(anchor='w',pady=(0,6))
        app.label(shell,'Releases the rear override. Connected front sockets take priority;\nwithout a detected front connection, the rear input remains active.',
                  fg=MUTED,justify='left',font=('DejaVu Sans',9)).pack(anchor='w',pady=(0,14))
        self.controls = {}
        self.reasons = {}
        for kind, title in (('line','FRONT LINE / INSTRUMENT LINK'),('mic','FRONT MICROPHONE LINK')):
            frame = tk.Frame(shell,bg=PANEL,padx=14,pady=8)
            frame.pack(fill='x',pady=(0,12))
            app.label(frame,title,fg=MUTED,font=('DejaVu Sans',10,'bold')).pack(anchor='w')
            row = tk.Frame(frame,bg=PANEL);row.pack(fill='x',pady=(8,0))
            label = app.label(row,'—',font=('DejaVu Sans',20,'bold'));label.pack(side='left')
            button = tk.Button(row,text='Waiting…',command=lambda k=kind:self.toggle(k),
                               bg='#383c41',fg=TEXT,relief='flat',padx=16,pady=8,state='disabled')
            button.pack(side='right');self.controls[kind] = label,button
            reason=app.label(frame,'',fg=MUTED,wraplength=610,justify='left',font=('DejaVu Sans',9))
            reason.pack(anchor='w',pady=(6,0));self.reasons[kind]=reason
        phase_frame=tk.Frame(shell,bg=PANEL,padx=14,pady=10)
        phase_frame.pack(fill='x',pady=(0,12))
        self.phase_buttons, self.hpf_buttons = {}, {}
        for col,(title,control,buttons) in enumerate((('POLARITY INVERT','phase',self.phase_buttons),('HIGH-PASS FILTER','hpf',self.hpf_buttons))):
            phase_frame.columnconfigure(col,weight=1,uniform='frontswitch')
            app.label(phase_frame,title,fg=MUTED,font=('DejaVu Sans',10,'bold')).grid(row=0,column=col,sticky='w',pady=(0,6))
            for channel in (1,2):
                button=tk.Button(phase_frame,text='Input '+str(channel)+' · waiting',command=lambda c=channel,n=control:self.toggle_switch(c,n),
                    bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=6,state='disabled')
                button.grid(row=channel,column=col,sticky='ew',padx=(0,12) if col==0 else (12,0),pady=(0,6))
                buttons[channel]=button
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        tk.Button(actions,text='Gain and pad…',command=app.open_front_gain,bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=7).pack(side='right')
        tk.Button(actions,text='Refresh',command=self.select,bg=PANEL,fg=TEXT,relief='flat',padx=14,pady=7).pack(side='left')
        self.message=app.label(shell,'Reading front links…',fg=MUTED,wraplength=590,justify='left')
        self.message.pack(anchor='w',pady=(12,0));self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','front'))
    def enable_front(self):
        if self.pending or not self.app.connected or not self.state.get('writes_available'): return
        self.pending=True;self.refresh()
        self.message.config(text='Enabling automatic front detection for both inputs…',fg=MUTED)
        self.app.worker.commands.put(('front_source',None))
    def toggle_phase(self,channel):
        self.toggle_switch(channel,'phase')
    def toggle_hpf(self,channel):
        self.toggle_switch(channel,'hpf')
    def toggle_switch(self,channel,control):
        if control not in ('phase','hpf'):return
        value=self.state.get(control+str(channel))
        sources=self.state.get('source_status',{}).get('sources')
        if self.pending or not self.app.connected or not self.state.get('writes_available') or value not in (0,1) or not sources or sources[channel-1] not in ('line','mic'):return
        self.pending=True;self.refresh()
        self.message.config(text='Updating front input '+str(channel)+(' polarity…' if control=='phase' else ' high-pass filter…'),fg=MUTED)
        self.app.worker.commands.put(('front_'+control,(channel,sources[channel-1],not bool(value))))
    def refresh(self):
        source=self.state.get('source_status',{})
        sources=source.get('sources')
        labels={'rear':'Rear','line':'Front line / instrument','mic':'Front microphone'}
        self.source_label.config(text=('Input 1: '+labels[sources[0]]+'    |    Input 2: '+labels[sources[1]]) if sources else 'Source status unavailable')
        forced=self.state.get('link_context',{}).get('raw',{}).get('force_rear')
        source_ready=self.app.connected and not self.pending and self.state.get('writes_available') and forced is not None and bool(forced & 3)
        self.source_button.config(state='normal' if source_ready else 'disabled')
        for control,buttons in (('phase',self.phase_buttons),('hpf',self.hpf_buttons)):
            for channel,button in buttons.items():
                value=self.state.get(control+str(channel))
                ready=self.app.connected and not self.pending and self.state.get('writes_available') and value in (0,1)
                word=('Inverted' if value==1 else 'Normal') if control=='phase' else ('On' if value==1 else 'Off')
                button.config(text='Input '+str(channel)+' · '+(word if value in (0,1) else 'Unavailable'),state='normal' if ready else 'disabled')
        for kind,(label,button) in self.controls.items():
            value=self.state.get(kind)
            label.config(text=('On' if value else 'Off') if value in (0,1) else 'Unavailable',fg=ACCENT if value==1 else TEXT)
            ready=self.app.connected and not self.pending and self.state.get('writes_available') and value in (0,1) and source.get('available',{}).get(kind,False)
            self.reasons[kind].config(text=self.state.get('errors',{}).get(kind) or source.get('reason',{}).get(kind,'Reading source…'))
            button.config(text='Turn off' if value==1 else 'Turn on',state='normal' if ready else 'disabled')
    def toggle(self,kind):
        value=self.state.get(kind)
        if self.pending or not self.app.connected or not self.state.get('writes_available') or value not in (0,1) or not self.state.get('source_status',{}).get('available',{}).get(kind,False):return
        self.pending=True;self.refresh();self.message.config(text='Updating front link…',fg=MUTED)
        self.app.worker.commands.put(('front_link',(kind,not bool(value))))
    def handle(self,event):
        channel=event.get('channel',event.get('state',{}).get('channel'))
        if channel!='front':return
        if event['kind']=='input_snapshot':
            self.state=event['state']
            if not self.pending:self.message.config(text='; '.join(dict.fromkeys(self.state.get('errors',{}).values())) or 'Front link readback · source selection is unchanged',fg=MUTED)
        elif event['kind']=='input_source_written':
            self.pending=False;self.state={}
            self.message.config(text='Rear override released for both inputs; checking front detection…',fg=ACCENT)
        elif event['kind']=='input_written':
            self.pending=False;self.state[event['name']]=event['actual']
            description=('Input '+event['name'][-1]+' front polarity' if event['name'].startswith('phase') else 'Input '+event['name'][-1]+' front high-pass filter' if event['name'].startswith('hpf') else 'Front '+event['name']+' link')
            self.message.config(text=description+' confirmed by device readback.',fg=ACCENT)
        else:
            self.pending=False;self.message.config(text=event.get('message','Read failed'),fg='#efba76')
            if not self.app.connected:self.state={}
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None))
        self.app.input_window=None;self.window.destroy()


class FrontGainWindow:
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},False
        self.channel=tk.StringVar(value='front')
        self.window=app.make_panel()
        self.window.title('AF16Rig — Front gain, pad and mode 1–2 — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('700x540');self.window.minsize(660,520)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'FRONT GAIN, PAD AND MODE',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell,'Native gain steps 0–55 · active front inputs only',fg=MUTED).pack(anchor='w',pady=(6,14))
        self.gain_labels,self.mode_labels,self.buttons,self.pad_buttons={},{},{},{}
        self.instrument_buttons={}
        for channel in (1,2):
            frame=tk.Frame(shell,bg=PANEL,padx=14,pady=12);frame.pack(fill='x',pady=(0,12))
            header=tk.Frame(frame,bg=PANEL);header.pack(fill='x')
            self.mode_labels[channel]=app.label(header,'Input '+str(channel)+' · reading source',fg=MUTED)
            self.mode_labels[channel].pack(side='left')
            self.instrument_buttons[channel]=tk.Button(header,text='Mode · waiting',command=lambda c=channel:self.toggle_instrument(c),bg='#383c41',fg=TEXT,relief='flat',padx=12,pady=5,state='disabled')
            self.instrument_buttons[channel].pack(side='right')
            row=tk.Frame(frame,bg=PANEL);row.pack(fill='x',pady=(8,0))
            label=app.label(row,'—',font=('DejaVu Sans',22,'bold'));label.pack(side='left');self.gain_labels[channel]=label
            self.pad_buttons[channel]=tk.Button(row,text='Pad · waiting',command=lambda c=channel:self.toggle_pad(c),bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=7,state='disabled')
            self.pad_buttons[channel].pack(side='left',padx=(24,0))
            self.buttons[channel]={}
            for direction,title in ((1,'+1 step'),(-1,'−1 step')):
                button=tk.Button(row,text=title,command=lambda c=channel,d=direction:self.step(c,d),bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=7,state='disabled')
                button.pack(side='right',padx=(12,0));self.buttons[channel][direction]=button
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Filters and link…',app.open_front_inputs),('Refresh',self.select)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=12,pady=7).pack(side='left',padx=(0,10))
        self.message=app.label(shell,'Reading front gain and pad…',fg=MUTED,wraplength=600,justify='left');self.message.pack(anchor='w',pady=(14,0))
        self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','front'))
    def toggle_pad(self,channel):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        sources=self.state.get('source_status',{}).get('sources')
        value=self.state.get('pad'+str(channel))
        if not sources or sources[channel-1] not in ('line','mic') or value not in (0,1):return
        self.pending=True;self.refresh();self.message.config(text='Updating input '+str(channel)+' front pad…',fg=MUTED)
        self.app.worker.commands.put(('front_pad',(channel,sources[channel-1],not bool(value))))
    def toggle_instrument(self,channel):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        sources=self.state.get('source_status',{}).get('sources')
        value=self.state.get('instrument'+str(channel))
        if not sources or sources[channel-1]!='line' or value not in (0,1):return
        self.pending=True;self.refresh()
        self.message.config(text='Switching input '+str(channel)+' to '+('Line' if value else 'Instrument')+' mode…',fg=MUTED)
        self.app.worker.commands.put(('front_instrument',(channel,not bool(value))))
    def refresh(self):
        sources=self.state.get('source_status',{}).get('sources')
        labels={'line':'Front line / instrument','mic':'Front microphone','rear':'Rear active · use front detection in Filters and link'}
        for channel in (1,2):
            mode=sources[channel-1] if sources else None
            self.mode_labels[channel].config(text='Input '+str(channel)+' · '+labels.get(mode,'Source unavailable'))
            instrument=self.state.get('instrument'+str(channel))
            instrument_ready=self.app.connected and not self.pending and self.state.get('writes_available') and mode=='line' and instrument in (0,1)
            word=('Instrument' if instrument==1 else 'Line') if instrument in (0,1) else 'Unavailable'
            self.instrument_buttons[channel].config(text='Mode · '+word,state='normal' if instrument_ready else 'disabled')
            pad=self.state.get('pad'+str(channel))
            pad_ready=self.app.connected and not self.pending and self.state.get('writes_available') and pad in (0,1) and mode in ('line','mic')
            self.pad_buttons[channel].config(text='Pad · '+('On' if pad==1 else 'Off' if pad==0 else 'Unavailable'),state='normal' if pad_ready else 'disabled')
            value=self.state.get('gain'+str(channel))
            supported=type(value) is int and 0<=value<=55
            self.gain_labels[channel].config(text=str(value) if supported else 'Unavailable')
            ready=self.app.connected and not self.pending and self.state.get('writes_available') and supported and mode in ('line','mic')
            for direction,button in self.buttons[channel].items():
                enabled=ready and ((direction<0 and value>0) or (direction>0 and value<55))
                button.config(state='normal' if enabled else 'disabled')
    def step(self,channel,direction):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        sources=self.state.get('source_status',{}).get('sources')
        value=self.state.get('gain'+str(channel))
        if not sources or sources[channel-1] not in ('line','mic') or type(value) is not int or not 0<=value<=55:return
        self.pending=True;self.refresh();self.message.config(text='Updating input '+str(channel)+' front gain…',fg=MUTED)
        self.app.worker.commands.put(('front_gain',(channel,sources[channel-1],direction)))
    def handle(self,event):
        if event.get('channel',event.get('state',{}).get('channel'))!='front':return
        if event['kind']=='input_snapshot':
            self.state=event['state']
            if not self.pending:
                errors=[v for k,v in self.state.get('errors',{}).items() if k.startswith(('gain','pad','instrument'))]
                self.message.config(text='; '.join(dict.fromkeys(errors)) or 'Live gain readback · compare one step with the device gain display',fg=MUTED)
        elif event['kind']=='input_written':
            self.pending=False;self.state[event['name']]=event['actual']
            self.message.config(text='Input '+event['name'][-1]+' front '+('instrument mode' if event['name'].startswith('instrument') else 'pad' if event['name'].startswith('pad') else 'gain')+' confirmed by device readback.',fg=ACCENT)
        else:
            self.pending=False;self.message.config(text=event.get('message','Read failed'),fg='#efba76')
            if not self.app.connected:self.state={}
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class OutputWindow:
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},False
        self.channel=tk.StringVar(value='output')
        self.output=tk.IntVar(value=3)
        self.window=app.make_panel()
        self.window.title('AF16Rig — Analog outputs — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('640x660');self.window.minsize(600,640)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'ANALOG OUTPUT LEVEL',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell,'Outputs 3–10 · −60 to 0 dB',fg=MUTED).pack(anchor='w',pady=(6,18))
        selector=tk.Frame(shell,bg=BG);selector.pack(fill='x')
        app.label(selector,'Output').pack(side='left',padx=(0,12))
        self.menu=tk.OptionMenu(selector,self.output,*range(3,11),command=self.select)
        self.menu.config(bg=PANEL,fg=TEXT,highlightthickness=0,width=6);self.menu.pack(side='left')
        frame=tk.Frame(shell,bg=PANEL,padx=16,pady=16);frame.pack(fill='x',pady=18)
        self.level=app.label(frame,'—',font=('DejaVu Sans',28,'bold'));self.level.pack(anchor='w',pady=(0,12))
        row=tk.Frame(frame,bg=PANEL);row.pack(fill='x');self.buttons={}
        for direction,title in ((-1,'−1 dB'),(1,'+1 dB')):
            button=tk.Button(row,text=title,command=lambda d=direction:self.step(d),bg='#383c41',fg=TEXT,relief='flat',padx=20,pady=9,state='disabled')
            button.pack(side='left',padx=(0,16));self.buttons[direction]=button
        link_frame=tk.Frame(shell,bg=PANEL,padx=16,pady=12);link_frame.pack(fill='x',pady=(0,12))
        self.set_level_button=tk.Button(row,text='Set level…',command=self.set_level,bg='#383c41',fg=TEXT,relief='flat',padx=20,pady=9,state='disabled')
        self.set_level_button.pack(side='left')
        self.pair_label=app.label(link_frame,'STEREO LINK',fg=MUTED,font=('DejaVu Sans',10,'bold'));self.pair_label.pack(anchor='w')
        link_row=tk.Frame(link_frame,bg=PANEL);link_row.pack(fill='x',pady=(6,0))
        self.link_label=app.label(link_row,'—',font=('DejaVu Sans',20,'bold'));self.link_label.pack(side='left')
        self.link_button=tk.Button(link_row,text='Waiting…',command=self.toggle_link,bg='#383c41',fg=TEXT,relief='flat',padx=18,pady=8,state='disabled');self.link_button.pack(side='right')
        app.label(shell,'Linking may synchronize paired output levels through the device firmware.',fg=MUTED,wraplength=580,justify='left',font=('DejaVu Sans',9)).pack(anchor='w',pady=(0,12))
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Refresh',self.select),):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=14,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading output…',fg=MUTED,wraplength=580,justify='left');self.message.pack(anchor='w',pady=(12,0))
        self.select()
    def select(self,unused=None):
        if self.pending:return
        self.state={};self.refresh()
        self.message.config(text='Reading output '+str(self.output.get())+'…',fg=MUTED)
        self.app.worker.commands.put(('input_select',('output',self.output.get())))
    def toggle_link(self):
        if self.pending or not self.app.connected or not self.state.get('link_writes_available'):return
        value=0 if self.state.get('link_mixed') else self.state.get('link')
        if value not in (0,1):return
        self.pending=True;self.refresh();self.message.config(text='Updating output pair link…',fg=MUTED)
        self.app.worker.commands.put(('output_link',(self.output.get(),not bool(value))))
    def refresh(self):
        value=self.state.get('level_db')
        self.level.config(text=f'{value:.2f} dB' if value is not None else 'Unavailable')
        ready=self.app.connected and not self.pending and self.state.get('writes_available') and value is not None
        if hasattr(self,'set_level_button'):self.set_level_button.config(state='normal' if ready else 'disabled')
        for direction,button in self.buttons.items():
            enabled=ready and ((direction<0 and value>-60) or (direction>0 and value<0))
            button.config(state='normal' if enabled else 'disabled')
        pair=self.state.get('pair',[((self.output.get()-3)//2)*2+3,((self.output.get()-3)//2)*2+4])
        self.pair_label.config(text='STEREO LINK · OUTPUTS '+str(pair[0])+'–'+str(pair[1]))
        link=self.state.get('link');mixed=self.state.get('link_mixed',False)
        self.link_label.config(text='Mixed' if mixed else ('On' if link==1 else 'Off') if link in (0,1) else 'Unavailable')
        link_ready=self.app.connected and not self.pending and self.state.get('link_writes_available') and (mixed or link in (0,1))
        self.link_button.config(text='Link pair' if mixed else 'Unlink pair' if link==1 else 'Link pair',state='normal' if link_ready else 'disabled')
        self.menu.config(state='disabled' if self.pending else 'normal')
    def set_level(self):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        from tkinter import simpledialog,messagebox
        from value_entry import numeric_target
        output=self.output.get();serial=self.app.name_cache.serial
        expected=self.state.get('level_signed');value=self.state.get('level_db')
        if expected is None or value is None:return
        try:
            entered=simpledialog.askfloat(f'Output {output} level','Level in dB (−60 to 0) · 0.25 dB steps',parent=self.window,
                                         initialvalue=value,minvalue=-60,maxvalue=0)
            if entered is None:return
            target=numeric_target(entered,-60,0)
            if not self.window.winfo_exists() or self.pending or not self.app.connected or serial!=self.app.name_cache.serial or output!=self.output.get():return
            if round(target*256)==expected:return
            self.pending=True;self.refresh()
            self.message.config(text=f'Setting output {output} to {target:.2f} dB…',fg=MUTED)
            self.app.worker.commands.put(('output_target',(output,target,expected,serial)))
        except ValueError as error:messagebox.showerror('Invalid output level',str(error),parent=self.window)
        except tk.TclError:pass

    def step(self,direction):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        self.pending=True;self.refresh()
        self.message.config(text='Updating output '+str(self.output.get())+' level…',fg=MUTED)
        self.app.worker.commands.put(('output_gain',(self.output.get(),direction)))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='output':return
        if event.get('output',state.get('output',self.output.get()))!=self.output.get():return
        if event['kind']=='input_snapshot':
            self.state=state
            if not self.pending:self.message.config(text=state.get('error') or 'Live output level readback',fg=MUTED)
        elif event['kind']=='input_written':
            self.pending=False
            if event.get('name')=='link':
                self.state.update(link=event['actual'],link_bits=[event['actual']]*2,link_mixed=False)
                self.message.config(text='Output pair link confirmed by device readback.',fg=ACCENT)
            else:
                self.state.update(level_signed=event['actual'],level_raw=event['actual'] & 0xffff,level_db=event['actual']/256)
                self.message.config(text='Output '+str(self.output.get())+' level confirmed by device readback.',fg=ACCENT)
        else:
            self.pending=False
            name=event.get('name')
            if name=='link' and self.state:self.state.update(link=None,link_mixed=False,link_writes_available=False)
            elif name=='level' and self.state:self.state.update(level_db=None,writes_available=False)
            else:self.state={}
            self.message.config(text=event.get('message','Read failed'),fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class MonitorSettingsWindow:
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},False
        self.channel=tk.StringVar(value='monitor_settings')
        self.window=app.make_panel()
        self.window.title('AF16Rig — Monitor settings — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('720x700');self.window.minsize(680,680)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'MONITOR SETTINGS',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        frame=tk.Frame(shell,bg=PANEL,padx=16,pady=16);frame.pack(fill='x',pady=(18,12))
        app.label(frame,'SPEAKER DIM DEPTH',fg=MUTED,font=('DejaVu Sans',10,'bold')).pack(anchor='w')
        self.depth=app.label(frame,'—',font=('DejaVu Sans',28,'bold'));self.depth.pack(anchor='w',pady=(6,12))
        row=tk.Frame(frame,bg=PANEL);row.pack(fill='x');self.buttons={}
        for db in (-10,-20):
            button=tk.Button(row,text=str(db)+' dB',command=lambda d=db:self.choose(d),bg='#383c41',fg=TEXT,relief='flat',padx=20,pady=9,state='disabled')
            button.pack(side='left',padx=(0,16));self.buttons[db]=button
        app.label(shell,'Sets the reduction used by DIM. Use the existing DIM button\non the main window or device to engage it.',fg=MUTED,justify='left',wraplength=560).pack(anchor='w',pady=(0,12))
        ab=tk.Frame(shell,bg=PANEL,padx=16,pady=14);ab.pack(fill='x',pady=(0,12))
        app.label(ab,'A/B SPEAKER MONITORING',fg=MUTED,font=('DejaVu Sans',10,'bold')).pack(anchor='w')
        self.ab_status=app.label(ab,'Reading…',font=('DejaVu Sans',19,'bold'));self.ab_status.pack(anchor='w',pady=(6,4))
        self.ab_details=app.label(ab,'',fg=MUTED,wraplength=630,justify='left');self.ab_details.pack(anchor='w',pady=(0,10))
        ab_row=tk.Frame(ab,bg=PANEL);ab_row.pack(fill='x')
        self.ab_enable_button=tk.Button(ab_row,text='Enable A/B',command=self.toggle_ab,bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=8,state='disabled');self.ab_enable_button.pack(side='left',padx=(0,14))
        self.ab_buttons={}
        for speaker in ('A','B'):
            button=tk.Button(ab_row,text='Speaker '+speaker,command=lambda x=speaker:self.select_speaker(x),bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=8,state='disabled')
            button.pack(side='left',padx=(0,14));self.ab_buttons[speaker]=button
        tk.Button(ab_row,text='Configure B…',command=app.open_ab_configuration,bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=8).pack(side='left')
        app.label(ab,'A uses the main monitor outputs. B uses the existing pair shown above.',fg=MUTED,wraplength=630,justify='left',font=('DejaVu Sans',9)).pack(anchor='w',pady=(10,0))
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Refresh',self.select),('Mix masters…',app.open_mixer_masters)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=14,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading dim depth…',fg=MUTED,justify='left',wraplength=560);self.message.pack(anchor='w',pady=(12,0))
        self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','monitor_settings'))
    def toggle_ab(self):
        enabled=self.state.get('ab_enabled')
        if self.pending or not self.app.connected or not self.state.get('ab_writes_available') or enabled not in (0,1):return
        self.pending=True;self.refresh();self.message.config(text='Updating A/B feature…',fg=MUTED)
        self.app.worker.commands.put(('monitor_ab_enabled',not bool(enabled)))
    def select_speaker(self,speaker):
        if self.pending or not self.app.connected or not self.state.get('ab_writes_available') or self.state.get('ab_enabled')!=1:return
        self.pending=True;self.refresh();self.message.config(text='Selecting Speaker '+speaker+'…',fg=MUTED)
        self.app.worker.commands.put(('monitor_ab_selected',speaker))
    def refresh(self):
        value=self.state.get('dim_depth_db')
        self.depth.config(text=str(value)+' dB' if value in (-10,-20) else 'Unavailable')
        ready=self.app.connected and not self.pending and self.state.get('writes_available')
        for db,button in self.buttons.items():
            button.config(state='normal' if ready else 'disabled',bg=ACCENT if value==db else '#383c41',fg=BG if value==db else TEXT)
        enabled,selected=self.state.get('ab_enabled'),self.state.get('ab_selected')
        pair,trim=self.state.get('ab_pair'),self.state.get('ab_trim_db')
        ready=self.app.connected and not self.pending and self.state.get('ab_writes_available')
        b_known=pair is not None and trim is not None and selected in (0,1)
        self.ab_status.config(text=('Speaker B selected' if selected==1 else 'Speaker A selected' if selected==0 else 'Selection unavailable') if enabled==1 else 'A/B disabled' if enabled==0 else 'A/B state unavailable')
        self.ab_details.config(text=('B outputs: '+str(pair[0])+'–'+str(pair[1]) if pair else 'B outputs: unavailable')+' · trim '+(f'{trim:+.2f} dB' if trim is not None else 'unavailable')+(' · stored Speaker '+('A' if selected==0 else 'B') if enabled==0 and selected in (0,1) else ''))
        self.ab_enable_button.config(text='Disable A/B' if enabled==1 else 'Enable A/B',state='normal' if ready and enabled in (0,1) and (enabled==1 or b_known) else 'disabled')
        for speaker,button in self.ab_buttons.items():
            index=0 if speaker=='A' else 1
            available=ready and enabled==1 and selected in (0,1) and (speaker=='A' or b_known)
            active=enabled==1 and selected==index
            button.config(state='normal' if available else 'disabled',bg=ACCENT if active else '#383c41',fg=BG if active else TEXT)
    def choose(self,db):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        self.pending=True;self.refresh();self.message.config(text='Setting speaker dim depth…',fg=MUTED)
        self.app.worker.commands.put(('monitor_dim_depth',db))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='monitor_settings':return
        if event['kind']=='input_snapshot':
            self.state=state
            if not self.pending:self.message.config(text=state.get('error') or 'Live dim-depth readback',fg=MUTED)
        elif event['kind']=='input_written':
            self.pending=False
            name=event.get('name')
            if name=='dim_depth':
                self.state.update(dim_depth_db=event['actual'],dim_depth_raw=0 if event['actual']==-10 else 1)
                text='Speaker dim depth confirmed by device readback.'
            elif name=='ab_destination':
                self.state.update(ab_destination_raw=(event['actual']-3)//2,ab_pair=[event['actual'],event['actual']+1])
                text='B output assignment confirmed by device readback.'
            elif name=='ab_trim':
                self.state.update(ab_trim_raw=event['actual'] & 65535,ab_trim_db=event['actual']/256)
                text='B trim confirmed by device readback.'
            else:
                self.state[name]=event['actual']
                text='A/B setting confirmed by device readback.'
            self.message.config(text=text,fg=ACCENT)
        else:
            self.pending=False
            name=event.get('name')
            if name in ('ab_enabled','ab_selected'):self.state[name]=None
            elif name=='dim_depth':self.state.update(dim_depth_db=None,writes_available=False)
            else:self.state={}
            self.message.config(text=event.get('message','Read failed'),fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class ABConfigurationWindow:
    PAIRS={'3–4':3,'5–6':5,'7–8':7,'9–10':9}
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},False
        self.channel=tk.StringVar(value='monitor_settings')
        self.destination=tk.StringVar(value='5–6');self.destination_dirty=False
        self.window=app.make_panel()
        self.window.title('AF16Rig — Configure Speaker B — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('680x590');self.window.minsize(640,570)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'CONFIGURE SPEAKER B',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        self.status=app.label(shell,'Reading A/B state…',fg=MUTED,wraplength=620,justify='left');self.status.pack(anchor='w',pady=(8,14))
        dest=tk.Frame(shell,bg=PANEL,padx=16,pady=14);dest.pack(fill='x',pady=(0,14))
        self.current_pair=app.label(dest,'Current B outputs: —',font=('DejaVu Sans',14,'bold'));self.current_pair.pack(anchor='w',pady=(0,10))
        row=tk.Frame(dest,bg=PANEL);row.pack(fill='x')
        self.menu=tk.OptionMenu(row,self.destination,*self.PAIRS,command=self.changed)
        self.menu.config(bg='#383c41',fg=TEXT,highlightthickness=0,width=9);self.menu.pack(side='left')
        self.apply_button=tk.Button(row,text='Apply pair',command=self.apply,bg='#383c41',fg=TEXT,relief='flat',padx=16,pady=8,state='disabled');self.apply_button.pack(side='left',padx=16)
        app.label(dest,'Select Speaker A or disable A/B before changing this pair.',fg=MUTED,wraplength=600,justify='left',font=('DejaVu Sans',9)).pack(anchor='w',pady=(10,0))
        trim=tk.Frame(shell,bg=PANEL,padx=16,pady=14);trim.pack(fill='x',pady=(0,14))
        app.label(trim,'B SPEAKER TRIM · ±12 dB',fg=MUTED,font=('DejaVu Sans',10,'bold')).pack(anchor='w')
        self.trim_label=app.label(trim,'—',font=('DejaVu Sans',26,'bold'));self.trim_label.pack(anchor='w',pady=(4,10))
        row=tk.Frame(trim,bg=PANEL);row.pack(fill='x');self.trim_buttons={}
        for direction,title in ((-1,'−1 dB'),(1,'+1 dB')):
            button=tk.Button(row,text=title,command=lambda d=direction:self.trim(d),bg='#383c41',fg=TEXT,relief='flat',padx=20,pady=8,state='disabled')
            button.pack(side='left',padx=(0,16));self.trim_buttons[direction]=button
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Monitor controls…',app.open_monitor_settings),('Refresh',self.select)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=12,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading B configuration…',fg=MUTED,wraplength=620,justify='left');self.message.pack(anchor='w',pady=(12,0))
        self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','monitor_settings'))
    def changed(self,unused=None):
        self.destination_dirty=True;self.refresh()
    def refresh(self):
        enabled,selected=self.state.get('ab_enabled'),self.state.get('ab_selected')
        pair=self.state.get('ab_pair');trim=self.state.get('ab_trim_db')
        active_b=enabled==1 and selected==1
        self.status.config(text='Speaker B is active · trim is adjustable; select A to change its pair.' if active_b else 'Speaker A selected' if enabled==1 and selected==0 else 'A/B disabled' if enabled==0 else 'A/B state unavailable')
        self.current_pair.config(text='Current B outputs: '+(str(pair[0])+'–'+str(pair[1]) if pair else 'Unavailable'))
        if pair and not self.destination_dirty:self.destination.set(str(pair[0])+'–'+str(pair[1]))
        ready=self.app.connected and not self.pending and self.state.get('ab_writes_available')
        dest_ready=ready and pair is not None and enabled in (0,1) and selected in (0,1) and not active_b
        self.menu.config(state='normal' if dest_ready else 'disabled')
        self.apply_button.config(state='normal' if dest_ready and self.destination.get() in self.PAIRS else 'disabled')
        self.trim_label.config(text=f'{trim:+.2f} dB' if trim is not None else 'Unavailable')
        for direction,button in self.trim_buttons.items():
            available=ready and trim is not None and ((direction<0 and trim>-12) or (direction>0 and trim<12))
            button.config(state='normal' if available else 'disabled')
    def apply(self):
        if self.pending or not self.app.connected or not self.state.get('ab_writes_available'):return
        first=self.PAIRS.get(self.destination.get())
        if first is None:return
        self.pending=True;self.refresh();self.message.config(text='Applying B output pair…',fg=MUTED)
        self.app.worker.commands.put(('monitor_ab_destination',first))
    def trim(self,direction):
        if self.pending or not self.app.connected or not self.state.get('ab_writes_available') or self.state.get('ab_trim_db') is None:return
        self.pending=True;self.refresh();self.message.config(text='Updating B trim…',fg=MUTED)
        self.app.worker.commands.put(('monitor_ab_trim',direction))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='monitor_settings':return
        if event['kind']=='input_snapshot':
            self.state=state
            if not self.pending:
                errors=[v for k,v in state.get('errors',{}).items() if k.startswith('ab_')]
                self.message.config(text='; '.join(dict.fromkeys(errors)) or 'Live B configuration readback',fg=MUTED)
        elif event['kind']=='input_written':
            self.pending=False;name=event.get('name')
            if name=='ab_destination':
                self.destination_dirty=False
                self.state.update(ab_destination_raw=(event['actual']-3)//2,ab_pair=[event['actual'],event['actual']+1])
            elif name=='ab_trim':self.state.update(ab_trim_raw=event['actual'] & 65535,ab_trim_db=event['actual']/256)
            else:self.state[name]=event['actual']
            self.message.config(text='B configuration confirmed by device readback.',fg=ACCENT)
        else:
            self.pending=False;name=event.get('name')
            if name=='ab_destination':self.state['ab_pair']=None
            elif name=='ab_trim':self.state['ab_trim_db']=None
            else:self.state={}
            self.message.config(text=event.get('message','Read failed'),fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class MiniInputWindow:
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},False
        self.channel=tk.StringVar(value='mini')
        self.window=app.make_panel();self.window.title('AF16Rig — Front minijack 3–4 — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('740x640');self.window.minsize(700,620)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'FRONT STEREO MINI JACK · 3–4',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        self.source_label=app.label(shell,'Reading sources…',fg=MUTED,wraplength=680,justify='left');self.source_label.pack(anchor='w',pady=(8,10))
        self.source_button=tk.Button(shell,text='Enable front detection for 3–4',command=self.enable_front,bg='#383c41',fg=TEXT,relief='flat',padx=14,pady=8,state='disabled');self.source_button.pack(anchor='w',pady=(0,8))
        app.label(shell,'Releases rear overrides for inputs 3–4. A connected minijack then takes priority.',fg=MUTED,wraplength=680,justify='left',font=('DejaVu Sans',9)).pack(anchor='w',pady=(0,14))
        self.gain_labels,self.gain_buttons,self.switch_buttons={},{},{}
        for channel in (3,4):
            frame=tk.Frame(shell,bg=PANEL,padx=14,pady=12);frame.pack(fill='x',pady=(0,12))
            app.label(frame,'INPUT '+str(channel)+' · FRONT GAIN 0–12 dB',fg=MUTED,font=('DejaVu Sans',10,'bold')).pack(anchor='w')
            row=tk.Frame(frame,bg=PANEL);row.pack(fill='x',pady=(6,8))
            self.gain_labels[channel]=app.label(row,'—',font=('DejaVu Sans',22,'bold'));self.gain_labels[channel].pack(side='left')
            self.gain_buttons[channel]={}
            for direction,title in ((1,'+1 dB'),(-1,'−1 dB')):
                button=tk.Button(row,text=title,command=lambda c=channel,d=direction:self.step(c,d),bg='#383c41',fg=TEXT,relief='flat',padx=18,pady=7,state='disabled')
                button.pack(side='right',padx=(12,0));self.gain_buttons[channel][direction]=button
            row=tk.Frame(frame,bg=PANEL);row.pack(fill='x');self.switch_buttons[channel]={}
            for name in ('phase','pad'):
                button=tk.Button(row,text='Waiting…',command=lambda c=channel,n=name:self.toggle(c,n),bg='#383c41',fg=TEXT,relief='flat',padx=16,pady=7,state='disabled')
                button.pack(side='left',padx=(0,16));self.switch_buttons[channel][name]=button
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Refresh',self.select),):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=14,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading minijack inputs…',fg=MUTED,wraplength=680,justify='left');self.message.pack(anchor='w',pady=(12,0));self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','mini'))
    def enable_front(self):
        if self.pending or not self.app.connected or not self.state.get('writes_available'):return
        self.pending=True;self.refresh();self.message.config(text='Enabling front minijack detection…',fg=MUTED)
        self.app.worker.commands.put(('mini_source',None))
    def refresh(self):
        sources=self.state.get('source_status',{}).get('sources')
        self.source_label.config(text='Input 3: '+('Front minijack' if sources[0]=='line' else 'Rear')+' · Input 4: '+('Front minijack' if sources[1]=='line' else 'Rear') if sources else 'Source status unavailable')
        raw=self.state.get('link_context',{}).get('raw',{})
        forced=raw.get('force_rear');detected=raw.get('detect_status')
        ready=self.app.connected and not self.pending and self.state.get('writes_available')
        self.source_button.config(state='normal' if ready and forced is not None and bool(forced & 12) else 'disabled')
        if sources and sources==['rear','rear'] and forced is not None and not forced&12 and detected is not None and not detected&16:
            self.source_label.config(text='No front minijack connection detected; both rear inputs remain active.')
        available=self.state.get('control_available',{})
        for channel in (3,4):
            value=self.state.get('gain'+str(channel)+'_db')
            self.gain_labels[channel].config(text=f'{value:.2f} dB' if value is not None else 'Unavailable')
            for direction,button in self.gain_buttons[channel].items():
                enabled=ready and available.get('gain'+str(channel)) and value is not None and ((direction<0 and value>0) or (direction>0 and value<12))
                button.config(state='normal' if enabled else 'disabled')
            for name,button in self.switch_buttons[channel].items():
                value=self.state.get(name+str(channel))
                word=('Inverted' if value==1 else 'Normal') if name=='phase' else ('On' if value==1 else 'Off')
                button.config(text=('Polarity · ' if name=='phase' else 'Pad · ')+(word if value in (0,1) else 'Unavailable'),state='normal' if ready and available.get(name+str(channel)) and value in (0,1) else 'disabled')
    def step(self,channel,direction):
        if self.pending or not self.app.connected or not self.state.get('control_available',{}).get('gain'+str(channel)):return
        self.pending=True;self.refresh();self.message.config(text='Updating input '+str(channel)+' minijack gain…',fg=MUTED)
        self.app.worker.commands.put(('mini_gain',(channel,direction)))
    def toggle(self,channel,name):
        if self.pending or not self.app.connected or not self.state.get('control_available',{}).get(name+str(channel)):return
        value=self.state.get(name+str(channel))
        if value not in (0,1):return
        self.pending=True;self.refresh();self.message.config(text='Updating front minijack switch…',fg=MUTED)
        self.app.worker.commands.put(('mini_set',(channel,name,not bool(value))))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='mini':return
        if event['kind']=='input_snapshot':
            self.state=state
            if not self.pending:self.message.config(text='; '.join(dict.fromkeys(state.get('errors',{}).values())) or 'Live front minijack readback',fg=MUTED)
        elif event['kind']=='input_source_written':
            self.pending=False;self.state={};self.message.config(text='Rear overrides released; checking minijack connection…',fg=ACCENT)
        elif event['kind']=='input_written':
            self.pending=False;name=event['name']
            if name.startswith('gain'):self.state.update({name+'_raw':event['actual'] & 65535,name+'_db':event['actual']/256})
            else:self.state[name]=event['actual']
            self.message.config(text='Front minijack change confirmed by device readback.',fg=ACCENT)
        else:
            self.pending=False;name=event.get('name')
            if name in self.state.get('control_available',{}):self.state['control_available'][name]=False
            else:self.state={}
            self.message.config(text=event.get('message','Read failed'),fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class HeadphoneWindow:
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},False
        self.channel=tk.StringVar(value='phones')
        self.window=app.make_panel();self.window.title('AF16Rig — Headphones preset capture — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('720x620');self.window.minsize(680,600)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'HEADPHONES · PRESET CAPTURE',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell,'Read-only device readings · volume stays on the physical PHONES knob',fg=MUTED,wraplength=660,justify='left').pack(anchor='w',pady=(8,16))
        frame=tk.Frame(shell,bg=PANEL,padx=16,pady=14);frame.pack(fill='x',pady=(0,14))
        app.label(frame,'DEVICE PRESET CODE',fg=MUTED,font=('DejaVu Sans',10,'bold')).pack(anchor='w')
        self.preset=app.label(frame,'—',font=('DejaVu Sans',28,'bold'));self.preset.pack(anchor='w',pady=(4,8))
        self.knob=app.label(frame,'Hardware knob reading: —',fg=MUTED);self.knob.pack(anchor='w')
        app.label(shell,'Select a headphone preset on the device, enter its exact displayed label,\nthen Record current. Repeat for every preset and save the report.\nRecord captures a reading; change presets on the device itself.',fg=TEXT,justify='left',wraplength=660).pack(anchor='w',pady=(0,12))
        app.label(shell,'Preset label shown on device',fg=MUTED).pack(anchor='w')
        row=tk.Frame(shell,bg=BG);row.pack(fill='x',pady=(6,0))
        self.preset_name=tk.StringVar(value='')
        self.name_entry=tk.Entry(row,textvariable=self.preset_name,bg=PANEL,fg=TEXT,insertbackground=TEXT,relief='flat',width=36)
        self.name_entry.pack(side='left',fill='x',expand=True,ipady=7,padx=(0,14))
        self.record_button=tk.Button(row,text='Record current',command=self.record,bg='#383c41',fg=TEXT,relief='flat',padx=16,pady=8,state='disabled');self.record_button.pack(side='left')
        self.summary=app.label(shell,'No labels recorded yet',fg=MUTED,wraplength=660,justify='left');self.summary.pack(anchor='w',pady=(12,14))
        self.name_trace=self.preset_name.trace_add('write',lambda *args:self.refresh())
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Monitor controls…',app.open_monitor_settings),('Refresh',self.select)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=12,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading headphones…',fg=MUTED,wraplength=660,justify='left');self.message.pack(anchor='w',pady=(12,0));self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','phones'))
    def refresh(self):
        preset,knob=self.state.get('preset_raw'),self.state.get('knob_raw')
        self.preset.config(text=str(preset) if preset is not None else 'Unavailable')
        self.knob.config(text='Hardware knob reading: '+(str(knob) if knob is not None else 'Unavailable'))
        ready=self.app.connected and not self.pending and preset is not None and 1<=len(self.preset_name.get().strip())<=80
        self.record_button.config(state='normal' if ready else 'disabled')
        self.name_entry.config(state='disabled' if self.pending else 'normal')
        latest={sample['label']:sample['state'].get('preset_raw') for sample in self.app.headphone_samples}
        self.summary.config(text='Captured '+str(len(self.app.headphone_samples))+' readings · '+' · '.join(label[:32]+': '+str(value) for label,value in list(latest.items())[-3:]) if latest else 'No labels recorded yet')
    def record(self):
        label=self.preset_name.get().strip()
        if not 1<=len(label)<=80:return
        if self.pending or not self.app.connected or self.state.get('preset_raw') is None:return
        self.pending=True;self.refresh();self.message.config(text='Reading and recording '+label+' preset…',fg=MUTED)
        self.app.worker.commands.put(('phones_record',label))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='phones':return
        if event['kind']=='input_snapshot':
            self.state=state
            if not self.pending:self.message.config(text='; '.join(state.get('errors',{}).values()) or 'Live read-only headphone readings',fg=MUTED)
        elif event['kind']=='headphone_recorded':
            self.pending=False;self.state=state
            self.message.config(text=event['label']+' labelled reading recorded. Save report after all presets.',fg=ACCENT)
        else:
            self.pending=False;self.state={};self.message.config(text=event.get('message','Read failed'),fg='#efba76')
        self.refresh()
    def close(self):
        self.preset_name.trace_remove('write',self.name_trace)
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class MixerMastersWindow:
    def __init__(self,app):
        self.app,self.state,self.pending=app,{},set()
        self.unavailable=set()
        self.pre_buttons={}
        self.channel=tk.StringVar(value='masters')
        self.window=app.make_panel();self.window.title('AF16Rig — Mixer masters — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('920x700');self.window.minsize(880,680)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'MIXER MASTER LEVELS',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell,'Main, Cue and Aux internal mix levels · each click adjusts 1 dB',fg=MUTED,wraplength=640,justify='left').pack(anchor='w',pady=(8,16))
        self.levels,self.buttons,self.mute_buttons,self.mute_labels={},{},{},{}
        grid=tk.Frame(shell,bg=BG);grid.pack(fill='x',pady=(0,12))
        grid.columnconfigure(0,weight=1,uniform='master');grid.columnconfigure(1,weight=1,uniform='master')
        for index,bus in enumerate(MIXER_BUSES):
            title={'main':'Main mix','cue':'Cue mix'}.get(bus,bus.upper().replace('AUX','Aux '))
            frame=tk.Frame(grid,bg=PANEL,padx=14,pady=12)
            frame.grid(row=index//2,column=index%2,sticky='nsew',padx=(0,6) if index%2==0 else (6,0),pady=(0,12))
            title_row=tk.Frame(frame,bg=PANEL);title_row.pack(fill='x')
            app.label(title_row,title,font=('DejaVu Sans',12,'bold')).pack(side='left')
            if bus=='cue':
                self.cue_button=tk.Button(title_row,text='Cue · reading',command=self.toggle_cue,bg='#383c41',fg=TEXT,relief='flat',padx=12,pady=5,width=16,state='disabled')
                self.cue_button.pack(side='right')
            if bus in MIXER_BUSES[2:]:
                button=tk.Button(title_row,text='Waiting…',command=lambda b=bus:self.toggle_mute(b),bg='#383c41',fg=TEXT,relief='flat',padx=10,pady=5,width=7,state='disabled')
                button.pack(side='right');self.mute_buttons[bus]=button
                label=app.label(title_row,'—',fg=MUTED,width=8,anchor='e');label.pack(side='right',padx=8);self.mute_labels[bus]=label
                pre=tk.Button(title_row,text='Reading…',command=lambda b=bus:self.toggle_pre(b),bg='#383c41',fg=TEXT,relief='flat',padx=10,pady=5,width=10,state='disabled')
                pre.pack(side='right',padx=(8,0));self.pre_buttons[bus]=pre
            row=tk.Frame(frame,bg=PANEL);row.pack(fill='x',pady=(8,0))
            self.levels[bus]=app.label(row,'—',font=('DejaVu Sans',22,'bold'),width=10,anchor='w');self.levels[bus].pack(side='left',expand=True,anchor='w')
            for direction,text in ((-1,'−1 dB'),(1,'+1 dB')):
                button=tk.Button(row,text=text,command=lambda b=bus,d=direction:self.step(b,d),bg='#383c41',fg=TEXT,relief='flat',padx=12,pady=10,state='disabled')
                button.pack(side='left',padx=(8,0));self.buttons[bus,direction]=button
        app.label(shell,'Adjustment range in this build: −60 to 0 dB.\nAudible changes depend on your existing mixer routing.',fg=MUTED,justify='left',wraplength=640).pack(anchor='w',pady=(0,16))
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Monitor controls…',app.open_monitor_settings),('Aux stereo…',app.open_aux_links),('Channels…',app.open_mix_channel),('Refresh',self.select)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=12,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading mix levels…',fg=MUTED,wraplength=640,justify='left');self.message.pack(anchor='w',pady=(12,0));self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','masters'))
    @staticmethod
    def update_widget(widget,**options):
        changed={key:value for key,value in options.items() if str(widget.cget(key))!=str(value)}
        if changed:widget.config(**changed)
    def refresh(self):
        for bus,label in self.levels.items():
            state=self.state.get('levels',{}).get(bus,{})
            db=state.get('db');raw=state.get('signed')
            self.update_widget(label,text='Unavailable' if db is None else f'{db:.2f} dB')
            ready=self.app.connected and (bus,'level') not in self.pending|self.unavailable and state.get('writes_available',False)
            for direction in (-1,1):
                enabled=ready and (raw>-60*256 if direction<0 else raw<0)
                self.update_widget(self.buttons[bus,direction],state='normal' if enabled else 'disabled')
        for bus,button in self.mute_buttons.items():
            value=self.state.get('aux_mutes',{}).get(bus)
            self.update_widget(self.mute_labels[bus],text='Muted' if value==1 else 'Unmuted' if value==0 else 'Unavailable',fg=ACCENT if value==1 else MUTED)
            ready=self.app.connected and (bus,'mute') not in self.pending|self.unavailable and self.state.get('aux_mute_writes_available',False) and value in (0,1)
            self.update_widget(button,text='Unmute' if value==1 else 'Mute' if value==0 else 'Waiting…',state='normal' if ready else 'disabled')
        for bus,button in self.pre_buttons.items():
            value=self.state.get('aux_pre',{}).get(bus)
            ready=self.app.connected and (bus,'pre') not in self.pending|self.unavailable and self.state.get('aux_pre_writes_available',False) and value in (0,1)
            self.update_widget(button,text='Pre-fader' if value==1 else 'Post-fader' if value==0 else 'Unavailable',state='normal' if ready else 'disabled',fg=ACCENT if value==1 else TEXT)
        cue=self.state.get('cue_enabled')
        ready=self.app.connected and ('cue','enable') not in self.pending|self.unavailable and self.state.get('cue_writes_available',False) and cue in (0,1)
        self.update_widget(self.cue_button,text='Cue · On' if cue==1 else 'Cue · Off' if cue==0 else 'Cue · unavailable',state='normal' if ready else 'disabled',fg=ACCENT if cue==1 else TEXT)
    def toggle_cue(self):
        if self.cue_button.cget('state') not in ('normal','active'):return
        target=not bool(self.state['cue_enabled'])
        self.pending.add(('cue','enable'));self.refresh();self.message.config(text='Changing Cue mix enable…',fg=MUTED)
        self.app.worker.commands.put(('cue_enable',target))
    def toggle_pre(self,bus):
        if self.pre_buttons[bus].cget('state') not in ('normal','active'):return
        target=not bool(self.state['aux_pre'][bus])
        self.pending.add((bus,'pre'));self.refresh();self.message.config(text='Changing '+bus+' send point…',fg=MUTED)
        self.app.worker.commands.put(('aux_pre',(bus,target)))
    def toggle_mute(self,bus):
        if self.mute_buttons[bus].cget('state') not in ('normal','active'):return
        target=not bool(self.state['aux_mutes'][bus])
        self.pending.add((bus,'mute'));self.refresh();self.message.config(text='Changing '+bus+' mute…',fg=MUTED)
        self.app.worker.commands.put(('aux_mute',(bus,target)))
    def step(self,bus,direction):
        if self.buttons[bus,direction].cget('state') not in ('normal','active'):return
        self.pending.add((bus,'level'));self.refresh();self.message.config(text='Changing '+bus+' master…',fg=MUTED)
        self.app.worker.commands.put(('master_step',(bus,direction)))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='masters':return
        if event['kind']=='input_snapshot':
            self.state=state;self.unavailable.clear()
            if not self.pending:self.message.config(text='; '.join(state.get('errors',{}).values()) or getattr(self,'live_status','Live mixer master readback'),fg=MUTED)
        elif event['kind']=='input_written':
            # Apply only the value already confirmed by native readback.
            # Preserve all other displayed readings while the next poll runs.
            name=event['name'];kind='mute' if name.endswith('_mute') else 'pre' if name.endswith('_pre') else 'enable' if name=='cue_enable' else 'level'
            bus=name.removesuffix('_mute').removesuffix('_pre').removesuffix('_enable');key=(bus,kind)
            self.pending.discard(key);self.unavailable.discard(key)
            if kind=='enable':
                self.state['cue_enabled']=event['actual']
            elif kind in ('mute','pre'):
                field='aux_mutes' if kind=='mute' else 'aux_pre'
                mask_field='aux_mute_mask' if kind=='mute' else 'aux_pre_mask'
                value=event['actual'];self.state.setdefault(field,{})[bus]=value
                mask=self.state.get(mask_field)
                if type(mask) is int:
                    bit=1<<MIXER_BUSES[2:].index(bus)
                    self.state[mask_field]=mask|bit if value else mask&~bit
            else:
                signed=event['actual']
                self.state.setdefault('levels',{})[bus]={'raw':signed&65535,'signed':signed,'db':signed/256,'writes_available':True}
            self.message.config(text=name.replace('_',' ').title()+' confirmed by device readback.',fg=ACCENT)
        else:
            if not self.app.connected:
                self.pending.clear();self.unavailable.clear();self.state={}
            elif event.get('name') in MIXER_BUSES:
                key=(event['name'],'mute' if event.get('operation')=='aux_mute' else 'pre' if event.get('operation')=='aux_pre' else 'enable' if event.get('operation')=='cue_enable' else 'level')
                self.pending.discard(key);self.unavailable.add(key)
            else:
                self.unavailable.update((bus,kind) for bus in MIXER_BUSES for kind in ('level','mute','pre','enable'))
            self.message.config(text=event.get('message','Read failed')+' · awaiting fresh readback',fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class AuxLinksWindow:
    def __init__(self,app):
        self.app,self.state,self.pending,self.unavailable=app,{},set(),set()
        self.channel=tk.StringVar(value='aux_links')
        self.window=app.make_panel();self.window.title('AF16Rig — Aux stereo pairs — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('740x520');self.window.minsize(700,500)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'AUX STEREO PAIRS',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell,'Link adjacent Aux buses into a stereo pair',fg=MUTED,wraplength=650).pack(anchor='w',pady=(8,18))
        self.status,self.buttons={},{}
        for pair in (1,3):
            card=tk.Frame(shell,bg=PANEL,padx=16,pady=14);card.pack(fill='x',pady=(0,14))
            app.label(card,'Aux '+str(pair)+'–'+str(pair+1),font=('DejaVu Sans',12,'bold')).pack(anchor='w')
            row=tk.Frame(card,bg=PANEL);row.pack(fill='x',pady=(8,0))
            label=app.label(row,'Reading…',font=('DejaVu Sans',18,'bold'),width=20,anchor='w');label.pack(side='left');self.status[pair]=label
            button=tk.Button(row,text='Reading…',command=lambda p=pair:self.toggle(p),bg='#383c41',fg=TEXT,relief='flat',padx=16,pady=9,width=12,state='disabled')
            button.pack(side='right');self.buttons[pair]=button
        app.label(shell,'Linked pairs share stereo operation. Check the device indicators after each change.',fg=MUTED,wraplength=650,justify='left').pack(anchor='w',pady=(0,16))
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Mix masters…',app.open_mixer_masters),('Refresh',self.select)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=12,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading Aux link flags…',fg=MUTED,wraplength=650,justify='left');self.message.pack(anchor='w',pady=(12,0));self.select()
    def select(self):
        if not self.pending:self.app.worker.commands.put(('input_select','aux_links'))
    def refresh(self):
        for pair,button in self.buttons.items():
            value=self.state.get('link'+str(pair)+str(pair+1))
            ready=self.app.connected and pair not in self.pending|self.unavailable and self.state.get('writes_available',False) and value in (0,1)
            MixerMastersWindow.update_widget(self.status[pair],text='Stereo linked' if value==1 else 'Independent' if value==0 else 'Unavailable',fg=ACCENT if value==1 else TEXT)
            MixerMastersWindow.update_widget(button,text='Unlink pair' if value==1 else 'Link pair' if value==0 else 'Reading…',state='normal' if ready else 'disabled')
    def toggle(self,pair):
        if self.buttons[pair].cget('state') not in ('normal','active'):return
        target=not bool(self.state['link'+str(pair)+str(pair+1)])
        self.pending.add(pair);self.refresh();self.message.config(text='Changing Aux '+str(pair)+'–'+str(pair+1)+' link…',fg=MUTED)
        self.app.worker.commands.put(('aux_link',(pair,target)))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='aux_links':return
        if event['kind']=='input_snapshot':
            self.state=state;self.unavailable.clear()
            if not self.pending:self.message.config(text='; '.join(state.get('errors',{}).values()) or 'Live Aux stereo link readback',fg=MUTED)
        elif event['kind']=='input_written':
            pair=int(event['name'][4]);value=event['actual'];self.pending.discard(pair);self.unavailable.discard(pair)
            self.state[event['name']]=value;mask=self.state.get('mask')
            if type(mask) is int:self.state['mask']=mask|(1<<pair) if value else mask&~(1<<pair)
            self.message.config(text='Aux '+str(pair)+'–'+str(pair+1)+' link confirmed by device readback.',fg=ACCENT)
        else:
            if not self.app.connected:self.state={};self.pending.clear();self.unavailable.clear()
            elif event.get('pair') in (1,3):self.pending.discard(event['pair']);self.unavailable.add(event['pair'])
            else:self.unavailable.update((1,3))
            self.message.config(text=event.get('message','Read failed')+' · awaiting fresh readback',fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


class MixChannelWindow:
    def __init__(self,app):
        self.app,self.state,self.pending,self.stale=app,{},False,False
        self.channel=tk.StringVar(value='mix_channel');self.bus=tk.StringVar(value='main');self.source=tk.IntVar(value=1)
        self.window=app.make_panel();self.window.title('AF16Rig — Mono mixer channels — BETA RC')
        self.window.configure(bg=BG);self.window.geometry('780x610');self.window.minsize(760,600)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=22);shell.pack(fill='both',expand=True)
        app.label(shell,'MIXER CHANNELS',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        app.label(shell,'Initial coverage: analog sources1–16 · Main and Cue internal mixers',fg=MUTED,wraplength=680).pack(anchor='w',pady=(8,16))
        selectors=tk.Frame(shell,bg=BG);selectors.pack(fill='x',pady=(0,16))
        app.label(selectors,'Mix').pack(side='left',padx=(0,10))
        self.bus_menu=tk.OptionMenu(selectors,self.bus,'main','cue',command=lambda _:self.select());self.bus_menu.config(bg=PANEL,fg=TEXT,highlightthickness=0);self.bus_menu.pack(side='left')
        app.label(selectors,'Analog source').pack(side='left',padx=(22,10))
        self.source_spin=tk.Spinbox(selectors,from_=1,to=16,textvariable=self.source,width=4,state='readonly',command=self.select,bg=PANEL,fg=TEXT,readonlybackground=PANEL)
        self.source_spin.pack(side='left')
        card=tk.Frame(shell,bg=PANEL,padx=18,pady=16);card.pack(fill='x',pady=(0,14))
        self.selection=app.label(card,'Reading channel selection…',fg=MUTED,wraplength=640,justify='left');self.selection.pack(anchor='w')
        self.level=app.label(card,'Level: —',font=('DejaVu Sans',18,'bold'),width=24,anchor='w');self.level.pack(anchor='w',pady=(12,10))
        pan_row = tk.Frame(card,bg=PANEL)
        pan_row.pack(fill='x',pady=(0,8))
        self.pan_reading = app.label(pan_row,'Pan reading —',width=18,anchor='w')
        self.pan_reading.pack(side='left')
        self.pan_buttons = {}
        for label in ():
            button = tk.Button(pan_row,text='Record '+label,command=lambda pos=label:self.record_pan(pos),
                               bg=BG,fg=TEXT,relief='flat',state='disabled')
            button.pack(side='left',padx=3)
            self.pan_buttons[label] = button
        adjust = tk.Frame(card,bg=PANEL)
        adjust.pack(fill='x',pady=(0,6))
        app.label(adjust,'Set pan').pack(side='left',padx=(0,8))
        self.pan_edit = {}
        for action in ('Left','L step','Centre','R step','Right'):
            button = tk.Button(adjust,text=action,command=lambda a=action:self.adjust_pan(a),bg=BG,fg=TEXT,relief='flat',state='disabled')
            button.pack(side='left',padx=3)
            self.pan_edit[action] = button
        self.pan_summary = app.label(card, 'Set pan on the device before recording each position.',fg=MUTED,wraplength=650)
        # Pan capture is available only in the legacy diagnostic code.
        controls=tk.Frame(card,bg=PANEL);controls.pack(fill='x')
        self.level_buttons={}
        for direction,title in ((-1,'−1 dB'),(1,'+1 dB')):
            button=tk.Button(controls,text=title,command=lambda d=direction:self.step(d),bg='#383c41',fg=TEXT,relief='flat',padx=16,pady=10,state='disabled')
            button.pack(side='left',padx=(0,12));self.level_buttons[direction]=button
        self.mute_button=tk.Button(controls,text='Reading…',command=self.toggle,bg='#383c41',fg=TEXT,relief='flat',padx=18,pady=10,width=14,state='disabled');self.mute_button.pack(side='right')
        self.solo_button = tk.Button(controls, text='Reading…', command=lambda: self.toggle('solo'),
                                     bg='#383c41', fg=TEXT, relief='flat', padx=12, pady=10, width=12, state='disabled')
        self.solo_button.pack(side='right', padx=8)
        sends = tk.Frame(card, bg=PANEL)
        sends.pack(fill='x', pady=(12,0))
        app.label(sends, 'Aux sends').pack(side='left', padx=(0,8))
        self.send_buttons = {}
        self.send_level_labels = {}
        self.send_steps = {}
        for aux in range(1,5):
            column = tk.Frame(sends,bg=PANEL)
            column.pack(side='left',padx=3)
            self.send_level_labels[aux] = app.label(column,'—',width=13)
            self.send_level_labels[aux].pack()
            steps = tk.Frame(column,bg=PANEL)
            steps.pack()
            for direction,title in ((-1,'−1 dB'),(1,'+1 dB')):
                step = tk.Button(steps,text=title,command=lambda n=aux,d=direction:self.step_send(n,d),
                                 bg=BG,fg=TEXT,relief='flat',state='disabled')
                step.pack(side='left')
                self.send_steps[aux,direction] = step
            button = tk.Button(column, width=12, command=lambda n=aux: self.toggle_send(n),
                               bg=BG, fg=TEXT, relief='flat', state='disabled')
            button.pack(side='left', padx=3)
            self.send_buttons[aux] = button
        app.label(shell,'Level steps −60 to +6 dB. Stereo level steps move both faders together.\nChannel inclusion and stereo pairs are changed on the device.',fg=MUTED,wraplength=680,justify='left').pack(anchor='w',pady=(0,16))
        actions=tk.Frame(shell,bg=BG);actions.pack(fill='x')
        for title,callback in (('Mix masters…',app.open_mixer_masters),('Refresh',self.select)):
            tk.Button(actions,text=title,command=callback,bg=PANEL,fg=TEXT,relief='flat',padx=12,pady=7).pack(side='left',padx=(0,12))
        self.message=app.label(shell,'Reading mixer channel…',fg=MUTED,wraplength=680,justify='left');self.message.pack(anchor='w',pady=(12,0));self.select()
    def select(self):
        if self.pending:return
        self.state={};self.stale=False;self.refresh()
        self.app.worker.commands.put(('input_select',('mix_channel',self.bus.get(),self.source.get())))
    def refresh(self):
        raw_pan = self.state.get('raw',{}).get('pan')
        MixerMastersWindow.update_widget(self.pan_reading,text='Pan reading '+('—' if raw_pan is None else str(raw_pan)))
        ready = (self.app.connected and not self.pending and not self.stale and raw_pan is not None
                 and self.state.get('mono_selected') == 1 and self.state.get('stereo_selected') == 0)
        for button in self.pan_buttons.values():
            MixerMastersWindow.update_widget(button,state='normal' if ready else 'disabled')
        editable = ready and self.bus.get() in ('main','cue') and self.app.info.get('state_version') == 18 and 0 <= raw_pan <= 254
        for action, button in self.pan_edit.items():
            enabled = editable and not (raw_pan == 0 and action in ('Left','L step') or
                                        raw_pan == 254 and action in ('Right','R step') or
                                        raw_pan == 127 and action == 'Centre')
            MixerMastersWindow.update_widget(button,state='normal' if enabled else 'disabled')
        mono,stereo=self.state.get('mono_selected'),self.state.get('stereo_selected')
        description='Stereo pair selected · individual-channel editing is read-only' if stereo==1 else 'Mono source included' if mono==1 and stereo==0 else 'Source not included as mono' if mono==0 and stereo==0 else 'Selection unavailable'
        members = self.state.get('stereo_members', [])
        if members:
            lines = []
            for side, member in zip(('L', 'R'), members):
                level = member['level_db']
                level_text = 'Level unavailable' if level is None else f'{level:.2f} dB'
                mute = {0:'Unmuted', 1:'Muted'}.get(member['mute'], 'Mute unavailable')
                solo = {0:'Solo off', 1:'Solo on'}.get(member['solo'], 'Solo unavailable')
                lines.append(f"{side} · Input {member['source']}    {level_text}    {mute}    {solo}")
            description = 'Stereo pair' + chr(10) + chr(10).join(lines)
        MixerMastersWindow.update_widget(self.selection,text=description)
        db=self.state.get('level_db');MixerMastersWindow.update_widget(self.level,text='Level: unavailable' if db is None else f'Level: {db:.2f} dB')
        value=self.state.get('mute');ready=self.app.connected and not self.pending and not self.stale and self.state.get('writes_available',False) and value in (0,1)
        MixerMastersWindow.update_widget(self.mute_button,text='Unmute channel' if value==1 else 'Mute channel' if value==0 else 'Unavailable',state='normal' if ready else 'disabled')
        solo = self.state.get('solo')
        solo_ready = self.app.connected and not self.pending and not self.stale and self.state.get('solo_writes_available', False)
        MixerMastersWindow.update_widget(self.solo_button, text={0:'Solo', 1:'Clear solo'}.get(solo,'Unavailable'),
                                         state='normal' if solo_ready and solo in (0,1) else 'disabled')
        if members:
            editable = self.app.connected and not self.pending and not self.stale and self.state.get('pair_editable')
            for control, button, on, off in (
                ('mute', self.mute_button, 'Mute both', 'Unmute both'),
                ('solo', self.solo_button, 'Solo both', 'Clear both solos'),
            ):
                known = all(member[control] in (0, 1) for member in members)
                active = all(member[control] == 1 for member in members)
                MixerMastersWindow.update_widget(button, text=off if active else on,
                                                 state='normal' if editable and known else 'disabled')
        signed=self.state.get('level_signed')
        level_ready=self.app.connected and not self.pending and not self.stale and self.state.get('level_writes_available',False)
        for direction,button in self.level_buttons.items():
            enabled=level_ready and (signed>-60*256 if direction<0 else signed<CHANNEL_MAX_RAW)
            if members:
                levels = [member['level_db'] for member in members]
                valid = all(value is not None and -60 <= value <= CHANNEL_MAX_DB for value in levels)
                enabled = editable and valid and (min(levels) > -60 if direction < 0 else max(levels) < CHANNEL_MAX_DB)
            title = ('−1 dB' if direction < 0 else '+1 dB') + (' both' if members else '')
            MixerMastersWindow.update_widget(button,text=title,state='normal' if enabled else 'disabled')
        for aux, button in self.send_buttons.items():
            if str(aux) in self.state.get("stereo_sends", {}):continue
            value = self.state.get(f'send{aux}')
            enabled = (self.app.connected and not self.pending and not self.stale
                       and self.state.get('send_writes_available') and value in (0,1))
            action = {0:'Mute', 1:'Unmute'}.get(value, '—')
            MixerMastersWindow.update_widget(button, text=f'{action} Aux {aux}', state='normal' if enabled else 'disabled')
        for aux, label in self.send_level_labels.items():
            if str(aux) in self.state.get("stereo_sends", {}):continue
            signed = self.state.get(f'aux{aux}_send_level')
            MixerMastersWindow.update_widget(label,text='—' if signed is None else f'{signed/256:.2f} dB')
            ready = (self.app.connected and not self.pending and not self.stale and
                     self.state.get('send_writes_available') and signed is not None and -60*256 <= signed <= CHANNEL_MAX_RAW)
            for direction in (-1,1):
                enabled = ready and (signed > -60*256 if direction < 0 else signed < CHANNEL_MAX_RAW)
                MixerMastersWindow.update_widget(self.send_steps[aux,direction],state='normal' if enabled else 'disabled')
        for key, send in self.state.get('stereo_sends', {}).items():
            aux = int(key)
            levels = send['levels']
            mutes = send['mutes']
            editable = self.app.connected and not self.pending and not self.stale and self.state.get('pair_editable')
            lines = []
            for i, value in enumerate(levels):
                side = ('L','R')[i]
                reading = '—' if value is None else f'{value/256:.2f} dB'
                marker = ' M' if len(mutes)==2 and mutes[i] else ''
                lines.append(f'{side} {reading}{marker}')
            MixerMastersWindow.update_widget(self.send_level_labels[aux],text=chr(10).join(lines))
            known = len(levels)==2 and all(v is not None and -60*256<=v<=CHANNEL_MAX_RAW for v in levels)
            for direction in (-1,1):
                enabled = editable and known and (min(levels)>-60*256 if direction<0 else max(levels)<CHANNEL_MAX_RAW)
                MixerMastersWindow.update_widget(self.send_steps[aux,direction],state='normal' if enabled else 'disabled')
            action = 'Unmute' if mutes==[1,1] else 'Mute'
            MixerMastersWindow.update_widget(self.send_buttons[aux],text=f'{action} Aux {aux}',state='normal' if editable and len(mutes)==2 else 'disabled')
        self.bus_menu.config(state='disabled' if self.pending else 'normal');self.source_spin.config(state='disabled' if self.pending else 'readonly')
    def adjust_pan(self, action):
        if self.pan_edit[action].cget('state') not in ('normal','active'):
            return
        self.pending = True
        self.refresh()
        self.message.config(text=f'Changing {self.bus.get().title()} channel pan…',fg=MUTED)
        self.app.worker.commands.put(('adjust_pan',(self.bus.get(),self.source.get(),action)))

    def record_pan(self, label):
        if self.pan_buttons[label].cget('state') not in ('normal','active'):
            return
        self.pending = True
        self.refresh()
        self.app.worker.commands.put(('record_pan',(self.bus.get(),self.source.get(),label)))

    def step_send(self, aux, direction):
        if self.send_steps[aux,direction].cget('state') not in ('normal','active'):
            return
        self.pending = True
        self.refresh()
        self.message.config(text=f'Updating Aux {aux} send level…',fg=MUTED)
        command = 'pair_send_level' if self.state.get('stereo_sends') else 'send_level'
        self.app.worker.commands.put((command,(self.bus.get(),self.source.get(),aux,direction)))

    def toggle_send(self, aux):
        if self.send_buttons[aux].cget('state') not in ('normal','active'):
            return
        pair = self.state.get('stereo_sends', {}).get(str(aux))
        target = pair['mutes'] != [1,1] if pair else not bool(self.state[f'send{aux}'])
        self.pending = True
        self.refresh()
        self.message.config(text=f'Updating Aux {aux} send mute…', fg=MUTED)
        self.app.worker.commands.put(('pair_send_mute' if pair else 'send_mute', (self.bus.get(), self.source.get(), aux, target)))

    def step(self,direction):
        if self.level_buttons[direction].cget('state') not in ('normal','active'):return
        self.pending=True;self.refresh();self.message.config(text='Changing channel level…',fg=MUTED)
        command = 'stereo_level' if self.state.get('stereo_members') else 'mix_channel_level'
        self.app.worker.commands.put((command,(self.bus.get(),self.source.get(),direction)))
    def toggle(self, control='mute'):
        button = self.solo_button if control == 'solo' else self.mute_button
        if button.cget('state') not in ('normal','active'):return
        members = self.state.get('stereo_members')
        if members:
            target = not all(member[control] == 1 for member in members)
            command = ('mix_channel_pair', (self.bus.get(), self.source.get(), control, target))
        else:
            target = not bool(self.state[control])
            command = ('mix_channel_' + control, (self.bus.get(), self.source.get(), target))
        self.pending=True;self.refresh()
        self.message.config(text=f'Changing channel {control}…',fg=MUTED)
        self.app.worker.commands.put(command)
    def handle(self,event):
        state=event.get('state',{});channel=event.get('channel',state.get('channel'))
        if channel!='mix_channel':return
        bus,source=event.get('bus',state.get('bus')),event.get('source',state.get('source'))
        if bus is not None and (bus!=self.bus.get() or source!=self.source.get()):return
        if event['kind']=='input_snapshot':
            self.state=state;self.stale=False
            if not self.pending:self.message.config(text='; '.join(state.get('errors',{}).values()) or getattr(self,'live_status','Live mixer channel readback'),fg=MUTED)
        elif event['kind']=='pan_recorded':
            self.pending = False
            self.state.setdefault('raw',{})['pan'] = event['raw']
            comparison = event.get('comparison')
            if comparison is None:
                summary = 'First scan recorded'
            else:
                changed = comparison['changes']
                summary = f"{len(changed)} of {comparison['compared']} readings changed"
                if changed:
                    summary += ' · ' + ', '.join(f'{k} {a} → {b}' for k, (a,b) in list(changed.items())[:3])
            self.pan_summary.config(text=summary)
            self.message.config(text=f"Recorded {event['label']} at {event['raw']}.",fg=ACCENT)
        elif event['kind']=='input_written':
            self.pending=False
            if event['name'] == 'stereo_pan':
                self.state['stereo_pan']=event['actual']
            elif event['name'] == 'pan':
                self.state.setdefault('raw',{})['pan'] = event['actual']
            elif event['name'] in ('pair_send_level','pair_send_mute'):
                send = self.state.get('stereo_sends', {}).get(str(event['aux']))
                if send is not None:
                    if event['name'] == 'pair_send_level':
                        send['levels'] = event['actual']
                    else:
                        send['mutes'] = [event['actual']] * 2
            elif event['name'] == 'stereo_level':
                levels = event['actual']
                for member, signed in zip(self.state.get('stereo_members', []), levels):
                    member['level_db'] = signed / 256
                selected = levels[(self.source.get() - 1) % 2]
                self.state.update(level_signed=selected, level_db=selected / 256)
                self.state.setdefault('raw', {})['level'] = selected & 65535
            elif event.get('pair'):
                control = event['name']
                mask = event['diagnostic']['actual_mask']
                self.state.setdefault('raw', {})[control] = mask
                self.state[control] = (mask >> (self.source.get() - 1)) & 1
                for member in self.state.get('stereo_members', []):
                    member[control] = (mask >> (member['source'] - 1)) & 1
            elif event['name'].endswith('_send_level'):
                self.state[event['name']] = event['actual']
                self.state.setdefault('raw',{})[event['name']] = event['actual'] & 65535
            elif event['name']=='level':
                signed=event['actual'];self.state.update(level_signed=signed,level_db=signed/256)
                self.state.setdefault('raw',{})['level']=signed&65535
            else:
                control = event['name']
                self.state[control] = event['actual']
                if control in self.state.get('raw', {}):
                    bit = 1 << (self.source.get() - 1)
                    mask = self.state['raw'][control]
                    self.state['raw'][control] = mask | bit if event['actual'] else mask & ~bit
            self.message.config(text='Channel '+event['name']+' confirmed by device readback.',fg=ACCENT)
        else:
            self.pending=False;self.stale=True
            if not self.app.connected:self.state={}
            self.message.config(text=event.get('message','Read failed')+' · awaiting fresh readback',fg='#efba76')
        self.refresh()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Offline UI preview; no hardware access')
    parser.add_argument('--capture', help=argparse.SUPPRESS)
    args = parser.parse_args()
    from app_icon import APP_CLASS,install_window_icon
    root = tk.Tk(className=APP_CLASS)
    install_window_icon(root)
    App(root, demo=args.demo, capture_path=args.capture)
    root.mainloop()

if __name__ == '__main__':
    main()
