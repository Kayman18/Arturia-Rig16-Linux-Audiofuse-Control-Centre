import ctypes as C
from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent))
from af16rig import AF16Rig, DemoAF16Rig, DeviceError, DeviceDisconnected, PARAMETERS, front_source_status

class Fn:
    def __init__(self, func): self.func = func
    def __call__(self, *args): return self.func(*args)

class FakeUSB:
    def __init__(self):
        self.values = {PARAMETERS[n]: v for n, v in {
            'main_channel_solo':0,'cue_channel_solo':0,**{f'aux{n}_send_level':(-12*256)&65535 for n in range(1,5)},**{f'main_channel_send{n}':0 for n in range(1,5)},'main_channel_pan':0,'cue_channel_pan':0,'main_channel_show':65535,'cue_channel_show':65535,'main_channel_stereo':0,'cue_channel_stereo':0,'main_channel_mute':0,'cue_channel_mute':0,'main_channel_level':(-12*256)&65535,'cue_channel_level':(-6*256)&65535,'cue_enabled':0,'aux_link':0,'aux_pre':0,'aux_mute':0,'aux1_master':(-8*256)&65535,'aux2_master':(-9*256)&65535,'aux3_master':(-10*256)&65535,'aux4_master':(-11*256)&65535,'main_master':(-12*256)&65535,'cue_master':(-6*256)&65535,'phones_preset':0,'phones_knob':1000, 'ab_enabled':0,'ab_selected':0,'ab_destination':1,'ab_trim':0, 'dim_depth':0, 'force_rear':0, 'detect_status':0, 'front_mic_status':0, 'state_version':18, 'speaker_level':65524, 'mute':0, 'mono':0, 'dim':0,
            'button':1, 'firmware_raw':2, 'hardware_raw':1, 'audio_firmware_raw':513}.items()}
        self.calls, self.closed, self.exited = [], False, False
        self.ignore_writes, self.read_result, self.write_result = False, 2, 2
        self.open_ids = None
        self.libusb_init = Fn(lambda ctx: 0)
        self.libusb_exit = Fn(lambda ctx: setattr(self, 'exited', True))
        def open_device(ctx, vid, pid):
            self.open_ids = (vid, pid)
            return 123
        self.libusb_open_device_with_vid_pid = Fn(open_device)
        self.libusb_close = Fn(lambda handle: setattr(self, 'closed', True))
        self.libusb_error_name = Fn(lambda rc: b'LIBUSB_ERROR_PIPE')
        def transfer(handle, bm, req, param, index, data, length, timeout):
            self.calls.append((bm, req, param, index, bytes(data), length, timeout))
            if bm == 0xc0:
                value = 0 if req==0x92 else self.values[(req-0x90, param)]
                data[0], data[1] = value & 255, value >> 8
                return self.read_result
            if bm == 0x40:
                if not self.ignore_writes:
                    if param in (38,39,44,45,46,47,52,53,54,55,62) and req==0x11:
                        mask=self.values[1,param];value=int.from_bytes(data,'little')
                        self.values[1,param]=mask|(1<<index) if value else mask&~(1<<index)
                    else:self.values[(req-0x10,param)] = int.from_bytes(data, 'little')
                return self.write_result
            raise AssertionError('Unexpected transfer direction/type')
        self.libusb_control_transfer = Fn(transfer)

class Tests(unittest.TestCase):
    def setUp(self):
        sleeper = patch('af16rig.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.fake = FakeUSB()
        self.device = AF16Rig(self.fake)
        self.device.open()
    def tearDown(self): self.device.close()
    def test_uses_confirmed_midi_identity(self):
        self.assertEqual(self.fake.open_ids, (0x1c75, 0xaf21))
    def test_observed_speaker_value_decodes_signed(self):
        state = self.device.snapshot()
        self.assertEqual(state['speaker_level_signed'], -12)
        self.assertTrue(state['writes_available'])
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))
    def test_each_boolean_write_and_readback(self):
        for name, req, param in [('mute',0x10,7),('mono',0x11,26),('dim',0x11,27)]:
            self.assertEqual(self.device.write_bool(name, True), 1)
            self.assertEqual(self.fake.calls[-2], (0x40, req, param, 0, b'\x01\x00', 2, 1000))
            self.assertEqual(self.device.write_bool(name, False), 0)
            self.assertEqual(self.fake.calls[-2][4], b'\x00\x00')
    def test_no_write_if_already_requested_value(self):
        self.device.write_bool('mute', False)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))
    def test_no_volume_or_other_writes(self):
        for name in ('speaker_level', 'state_version', 'unknown'):
            with self.assertRaises(ValueError): self.device.write_bool(name, True)
        with self.assertRaises(ValueError): self.device.write_bool('mute', 1)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))
    def test_version_mismatch_prevents_writes(self):
        self.device.version = 19
        with self.assertRaises(DeviceError): self.device.write_bool('mute', True)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))
    def test_unexpected_bool_prevents_writes(self):
        self.fake.values[PARAMETERS['mute']] = 65535
        with self.assertRaises(DeviceError): self.device.write_bool('mute', True)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))
    def test_readback_mismatch_reports_failure(self):
        self.fake.ignore_writes = True
        with self.assertRaisesRegex(DeviceError, 'not confirmed'): self.device.write_bool('mute', True)
    def test_short_read_is_not_accepted(self):
        self.fake.read_result = 1
        with self.assertRaisesRegex(DeviceError, 'got 1'): self.device.read('mute')
    def test_short_write_is_not_accepted(self):
        self.fake.write_result = 0
        self.fake.ignore_writes = True
        with self.assertRaisesRegex(DeviceError, 'not confirmed'): self.device.write_bool('mute', True)
    def test_failed_write_is_not_accepted(self):
        self.fake.write_result = -9
        self.fake.ignore_writes = True
        with self.assertRaisesRegex(DeviceError, 'LIBUSB_ERROR_PIPE'): self.device.write_bool('mute', True)
    def test_close_releases_resources(self):
        self.device.close()
        self.assertTrue(self.fake.closed and self.fake.exited)
        with self.assertRaises(DeviceError): self.device.read('mute')

    def test_applied_write_with_status_error_is_confirmed_without_resend(self):
        self.fake.write_result = -9
        self.assertEqual(self.device.write_bool('mute', True), 1)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 1)
        self.assertEqual(self.device.last_write['out_result'], -9)
        self.assertTrue(self.device.last_write['confirmed'])

    def test_zero_length_write_with_matching_readback_is_confirmed(self):
        self.fake.write_result = 0
        self.assertEqual(self.device.write_bool('mute', True), 1)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 1)

    def test_delayed_readback_retries_reads_only(self):
        read = self.device.read
        calls = 0
        def delayed(name):
            nonlocal calls
            calls += 1
            if calls == 2:
                return 0  # First read after OUT is stale.
            if calls == 3:
                raise DeviceError('temporary read stall')
            return read(name)
        self.device.read = delayed
        self.assertEqual(self.device.write_bool('mute', True), 1)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 1)
        self.assertEqual(len(self.device.last_write['readback_attempts']), 3)

    def test_volume_step_request_and_signed_payload(self):
        self.assertEqual(self.device.step_volume(-1), -268)
        out = [c for c in self.fake.calls if c[0] == 0x40]
        self.assertEqual(out, [(0x40, 0x13, 0, 0, b'\xf4\xfe', 2, 1000)])
        self.assertEqual(self.device.step_volume(1), -12)

    def test_volume_reads_current_hardware_before_step(self):
        self.fake.values[PARAMETERS['speaker_level']] = (-2803) & 0xffff
        self.assertEqual(self.device.step_volume(1), -2547)

    def test_volume_software_limits_do_not_write(self):
        for level, direction in [(0, 1), (-15360, -1)]:
            self.fake.values[PARAMETERS['speaker_level']] = level & 0xffff
            self.assertEqual(self.device.step_volume(direction), level)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_volume_outside_subset_does_not_write(self):
        for raw in (1, (-15361) & 0xffff, 0x8000):
            self.fake.values[PARAMETERS['speaker_level']] = raw
            with self.assertRaises(DeviceError): self.device.step_volume(-1)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_volume_rejects_large_steps_and_wrong_version(self):
        for direction in (0, 2, -2, True):
            with self.assertRaises(ValueError): self.device.step_volume(direction)
        self.device.version = 19
        with self.assertRaises(DeviceError): self.device.step_volume(-1)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_volume_status_error_is_reconciled_without_rewrite(self):
        self.fake.write_result = -9
        self.assertEqual(self.device.step_volume(-1), -268)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 1)

    def test_reported_minus_2803_value_is_in_control_range(self):
        self.fake.values[PARAMETERS['speaker_level']] = (-2803) & 0xffff
        self.assertAlmostEqual(self.device.snapshot()['speaker_level_db'], -10.94921875)
        self.assertEqual(self.device.step_volume(-1), -3059)
        self.assertEqual(self.device.step_volume(1), -2803)

    def test_volume_step_clamps_near_boundaries(self):
        self.fake.values[PARAMETERS['speaker_level']] = (-100) & 0xffff
        self.assertEqual(self.device.step_volume(1), 0)
        self.fake.values[PARAMETERS['speaker_level']] = (-15300) & 0xffff
        self.assertEqual(self.device.step_volume(-1), -15360)

    def test_db_display_for_reported_values(self):
        from af16rig_gui import App
        self.assertEqual(App.format_level(-2803), '-10.95 dB')
        self.assertEqual(App.format_level(-435), '-1.70 dB')
        self.assertEqual(App.format_level(-32768), '−∞ dB')

class WorkerTests(unittest.TestCase):
    @staticmethod
    def next_event(events):
        # Startup names are independent background notifications.
        import time
        deadline=time.monotonic()+2
        while True:
            event=events.get(timeout=max(0.001,deadline-time.monotonic()))
            if event['kind']!='auto_name':return event

    def test_demo_connect_set_and_shutdown(self):
        from af16rig_gui import Worker
        events = queue.Queue()
        worker = Worker(events, demo=True)
        worker.start()
        try:
            worker.commands.put(('connect', None))
            self.assertEqual(self.next_event(events)['kind'], 'connected')
            self.assertEqual(self.next_event(events)['kind'], 'snapshot')
            worker.commands.put(('set', ('mute', True)))
            self.assertEqual(self.next_event(events)['kind'], 'written')
            event = self.next_event(events)
            self.assertEqual(event['kind'], 'snapshot')
            self.assertEqual(event['state']['mute'], 1)
        finally:
            worker.stop_event.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    def test_command_failure_keeps_handle_and_recovers_state(self):
        from af16rig_gui import Worker
        class Temporary(DemoAF16Rig):
            closed = False
            def write_bool(self, name, value):
                self.values[name] = int(value)
                raise DeviceError('temporary readback failure')
            def close(self): self.closed = True
        device = Temporary()
        events = queue.Queue()
        worker = Worker(events, factory=lambda: device)
        worker.start()
        try:
            worker.commands.put(('connect', None))
            self.assertEqual(self.next_event(events)['kind'], 'connected')
            self.assertEqual(self.next_event(events)['kind'], 'snapshot')
            worker.commands.put(('set', ('mute', True)))
            self.assertEqual(self.next_event(events)['kind'], 'command_error')
            event = self.next_event(events)
            self.assertEqual(event['kind'], 'snapshot')
            self.assertEqual(event['state']['mute'], 1)
            self.assertFalse(device.closed)
            self.assertIs(worker.device, device)
        finally:
            worker.stop_event.set();worker.join(timeout=2)
        self.assertTrue(device.closed)

    def test_one_poll_failure_recovers_without_reconnect(self):
        from af16rig_gui import Worker
        class Temporary(DemoAF16Rig):
            count = 0
            def snapshot(self):
                self.count += 1
                if self.count == 2:
                    raise DeviceError('temporary stall')
                return super().snapshot()
        device = Temporary()
        events = queue.Queue()
        worker = Worker(events, factory=lambda: device)
        worker.start()
        try:
            worker.commands.put(('connect', None))
            self.assertEqual(self.next_event(events)['kind'], 'connected')
            self.assertEqual(self.next_event(events)['kind'], 'snapshot')
            self.assertEqual(self.next_event(events)['kind'], 'recovering')
            self.assertEqual(self.next_event(events)['kind'], 'snapshot')
            self.assertIs(worker.device, device)
        finally:
            worker.stop_event.set();worker.join(timeout=2)

class InputTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch('af16rig.time.sleep'); sleeper.start(); self.addCleanup(sleeper.stop)
        self.fake = FakeUSB()
        self.gain_values = {index: 0 for index in range(16)}
        self.output_values = {index:0 for index in range(8)}
        self.mini_gain_values = {0:0,1:0}
        self.front_gain_values = {(param,index):0 for param in (70,71) for index in (0,1)}
        self.input_values = {(param, index): 0 for param in (19, 97, 24, 72, 22, 23, 17, 18, 95, 96, 66, 67, 68, 69, 32) for index in range(16)}
        original = self.fake.libusb_control_transfer.func
        def transfer(handle, bm, req, param, index, data, length, timeout):
            if param not in (19, 97, 20, 24, 72, 22, 23, 17, 18, 95, 96, 66, 67, 68, 69, 70, 71, 33, 32, 21):
                return original(handle, bm, req, param, index, data, length, timeout)
            self.fake.calls.append((bm, req, param, index, bytes(data), length, timeout))
            if param == 21:
                if bm==0xc0:
                    value=self.mini_gain_values[index];data[0],data[1]=value & 255,value >> 8
                else:self.mini_gain_values[index]=int.from_bytes(data,'little')
                return 2
            if param == 33:
                if bm == 0xc0:
                    value=self.output_values[index]
                    data[0],data[1]=value & 255,value >> 8
                else:self.output_values[index]=int.from_bytes(data,'little')
                return 2
            if param in (70,71):
                if bm == 0xc0:
                    value = self.front_gain_values[param,index]
                    data[0],data[1] = value & 255,value >> 8
                else:
                    self.front_gain_values[param,index] = int.from_bytes(data,'little')
                return 2
            if param == 20:
                if bm == 0xc0:
                    value = self.gain_values[index]
                    data[0], data[1] = value & 255, value >> 8
                else:
                    self.gain_values[index] = int.from_bytes(data, 'little')
                return 2
            if bm == 0xc0:
                if index != 0:
                    raise AssertionError('Input reads must address packed word zero')
                value = sum(self.input_values[param, bit] << bit for bit in range(16))
                data[0], data[1] = value & 255, value >> 8
            else:
                self.input_values[param, index] = int.from_bytes(data, 'little')
            return 2
        self.fake.libusb_control_transfer = Fn(transfer)
        self.device = AF16Rig(self.fake); self.device.open()
        self.addCleanup(self.device.close)

    def test_headphones_snapshot_exact_read_only_fields(self):
        state=self.device.headphones_snapshot()
        self.assertEqual((state['preset_raw'],state['knob_raw']),(0,1000))
        self.assertTrue(state['read_only'])
        self.assertIn((0xc0,0x91,30,0,b'\x00\x00',2,1000),self.fake.calls)
        self.assertTrue(any(c[:4]==(0xc0,0x90,8,0) for c in self.fake.calls))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_headphones_read_failures_are_independent(self):
        original=self.device.read
        for name,field,other in (('phones_preset','preset_raw','knob_raw'),('phones_knob','knob_raw','preset_raw')):
            def read(parameter,index=0):
                if parameter==name:raise DeviceError('Headphones read failed')
                return original(parameter,index)
            self.device.read=read;state=self.device.headphones_snapshot()
            self.assertIsNone(state[field]);self.assertIsNotNone(state[other])
            self.assertIn(field,state['errors'])
        self.assertFalse(self.fake.closed)
    def test_headphones_preserves_unknown_codes_without_gain_conversion(self):
        self.fake.values[PARAMETERS['phones_preset']]=65535
        self.fake.values[PARAMETERS['phones_knob']]=32768
        state=self.device.headphones_snapshot()
        self.assertEqual(state['preset_raw'],65535);self.assertEqual(state['knob_raw'],32768)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_headphones_writes_and_nonzero_indices_are_blocked(self):
        for name in ('phones_preset','phones_knob'):
            with self.assertRaises(ValueError):self.device.read(name,1)
            with self.assertRaises(ValueError):self.device.write_bool(name,True)
            with self.assertRaises(ValueError):self.device._write_and_confirm(name,1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_headphones_record_worker_uses_fresh_read(self):
        from af16rig_gui import Worker
        class Headphones(DemoAF16Rig):
            calls=0
            def headphones_snapshot(self):
                self.calls+=1
                return {'channel':'phones','preset_raw':self.calls,'knob_raw':1000,'errors':{},'read_only':True}
        device=Headphones();events=queue.Queue();worker=Worker(events,factory=lambda:device);worker.start()
        def event(kind):
            while True:
                value=events.get(timeout=2)
                if value['kind']==kind:return value
        try:
            worker.commands.put(('connect',None));event('snapshot')
            worker.commands.put(('input_select','phones'))
            first=event('input_snapshot')['state']['preset_raw']
            worker.commands.put(('phones_record','Low'))
            recorded=event('headphone_recorded')
            self.assertEqual(recorded['label'],'Low')
            self.assertGreater(recorded['state']['preset_raw'],first)
            self.assertIn('sampled_at',recorded)
            self.assertIs(worker.device,device)
        finally:worker.stop_event.set();worker.join(timeout=2)
    def test_headphones_exact_device_labels_and_invalid_labels(self):
        from af16rig_gui import Worker
        device=DemoAF16Rig();events=queue.Queue();worker=Worker(events,factory=lambda:device);worker.start()
        def event(kind):
            while True:
                value=events.get(timeout=2)
                if value['kind']==kind:return value
        try:
            worker.commands.put(('connect',None));event('snapshot')
            worker.commands.put(('phones_record','  32–150 Ω  '))
            self.assertEqual(event('headphone_recorded')['label'],'32–150 Ω')
            for label in ('','   ','x'*81,1):
                worker.commands.put(('phones_record',label))
                self.assertEqual(event('input_error')['channel'],'phones')
            self.assertIs(worker.device,device)
        finally:worker.stop_event.set();worker.join(timeout=2)

    def test_headphones_failed_capture_keeps_worker_connected(self):
        from af16rig_gui import Worker
        class Headphones(DemoAF16Rig):
            def headphones_snapshot(self):return {'channel':'phones','preset_raw':None,'knob_raw':1000,'errors':{'preset_raw':'Failed'}}
        device=Headphones();events=queue.Queue();worker=Worker(events,factory=lambda:device);worker.start()
        def event(kind):
            while True:
                value=events.get(timeout=2)
                if value['kind']==kind:return value
        try:
            worker.commands.put(('connect',None));event('snapshot')
            worker.commands.put(('phones_record','High'))
            error=event('input_error')
            self.assertEqual(error['channel'],'phones')
            self.assertIs(worker.device,device)
        finally:worker.stop_event.set();worker.join(timeout=2)

    def test_mini_detection_and_explicit_rear_override_release(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        for i in range(16):self.input_values[72,i]=1
        state=self.device.mini_snapshot()
        self.assertEqual(state['source_status']['sources'],['rear','rear'])
        self.assertFalse(any(state['control_available'].values()))
        self.device.set_rear_pair_source(3,False)
        self.assertEqual(self.device.read('force_rear'),65523)
        self.assertEqual(self.device.mini_snapshot()['source_status']['sources'],['line','line'])
        self.assertEqual([(c[2],c[3]) for c in self.fake.calls if c[0]==0x40],[(72,2),(72,3)])
    def test_mini_gain_uses_two_element_fixed_point_array(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        self.mini_gain_values[0]=256
        self.assertEqual(self.device.mini_snapshot()['gain3_db'],1)
        self.assertEqual(self.device.step_mini_gain(3,1),512)
        self.assertIn((0x40,0x11,21,0,b'\x00\x02',2,1000),self.fake.calls)
        self.assertEqual(self.device.step_mini_gain(4,1),256)
        self.assertIn((0x40,0x11,21,1,b'\x00\x01',2,1000),self.fake.calls)
        self.assertTrue(all(v==0 for v in self.front_gain_values.values()))
        self.assertTrue(all(v==0 for v in self.gain_values.values()))
    def test_mini_gain_bounds_and_unknown_value(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        self.assertEqual(self.device.step_mini_gain(3,-1),0)
        self.mini_gain_values[0]=3072
        self.assertEqual(self.device.step_mini_gain(3,1),3072)
        self.mini_gain_values[0]=65535
        self.assertFalse(self.device.mini_snapshot()['control_available']['gain3'])
        with self.assertRaises(DeviceError):self.device.step_mini_gain(3,1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_mini_polarity_uses_bit_two_preserves_combo_flags(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        self.input_values[18,0]=self.input_values[18,1]=1
        self.device.write_mini_switch(3,'phase',True)
        self.assertIn((0x40,0x11,18,2,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.read('front_line_phase'),7)
        self.assertEqual(self.device.mini_snapshot()['phase3'],1)
        self.device.write_mini_switch(3,'phase',False)
        self.assertEqual(self.device.read('front_line_phase'),3)
    def test_mini_pad_uses_bit_three_preserves_other_front_pad_flags(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        self.input_values[67,0]=self.input_values[67,1]=1
        self.device.write_mini_switch(4,'pad',True)
        self.assertIn((0x40,0x11,67,3,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.read('front_line_pad'),11)
        self.assertEqual(self.device.mini_snapshot()['pad4'],1)
        self.device.write_mini_switch(4,'pad',False)
        self.assertEqual(self.device.read('front_line_pad'),3)
    def test_mini_source_change_blocks_stale_commands(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        self.device.mini_snapshot();self.input_values[72,3]=1
        with self.assertRaises(DeviceError):self.device.write_mini_switch(4,'pad',True)
        with self.assertRaises(DeviceError):self.device.step_mini_gain(4,1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_mini_split_sources_allow_only_active_channel(self):
        self.fake.values[PARAMETERS['detect_status']]=16;self.input_values[72,2]=1
        state=self.device.mini_snapshot()
        self.assertFalse(state['control_available']['gain3']);self.assertTrue(state['control_available']['gain4'])
        self.assertEqual(self.device.step_mini_gain(4,1),256)
        with self.assertRaises(DeviceError):self.device.step_mini_gain(3,1)
    def test_mini_field_read_failure_is_independent(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        original=self.device.read
        def read(name,index=0):
            if name=='front_mini_gain' and index==0:raise DeviceError('Mini gain read failed')
            return original(name,index)
        self.device.read=read;state=self.device.mini_snapshot()
        self.assertFalse(state['control_available']['gain3']);self.assertTrue(state['control_available']['gain4'])
        self.assertTrue(state['control_available']['phase3']);self.assertTrue(state['control_available']['pad3'])
        self.assertFalse(self.fake.closed)
    def test_mini_rejection_no_retry_or_disconnect(self):
        self.fake.values[PARAMETERS['detect_status']]=16
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==67 and args[4]==3:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]));return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.write_mini_switch(4,'pad',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed']);self.assertFalse(self.fake.closed)
    def test_mini_no_connection_arguments_indices_and_version(self):
        self.fake.values[PARAMETERS['detect_status']]=33
        self.assertFalse(any(self.device.mini_snapshot()['control_available'].values()))
        with self.assertRaises(DeviceError):self.device.step_mini_gain(3,1)
        for channel in (1,2,5,True):
            with self.assertRaises(ValueError):self.device.step_mini_gain(channel,1)
        for name,value in (('hpf',True),('phase',1)):
            with self.assertRaises(ValueError):self.device.write_mini_switch(3,name,value)
        with self.assertRaises(ValueError):self.device.read('front_mini_gain',2)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.step_mini_gain(3,1)
        with self.assertRaises(DeviceError):self.device.write_mini_switch(4,'pad',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_ab_destination_all_pairs_use_native_enum(self):
        for first,raw in ((3,0),(5,1),(7,2),(9,3)):
            self.assertEqual(self.device.write_ab_destination(first),first)
            self.assertIn((0x40,0x11,77,0,raw.to_bytes(2,'little'),2,1000),self.fake.calls)
            self.assertEqual(self.device.monitor_settings_snapshot()['ab_pair'],[first,first+1])
        self.assertTrue(all(c[2]==77 for c in self.fake.calls if c[0]==0x40))
    def test_ab_destination_blocks_live_b_and_rechecks_current_state(self):
        self.fake.values[PARAMETERS['ab_enabled']]=1
        self.device.monitor_settings_snapshot()
        self.fake.values[PARAMETERS['ab_selected']]=1
        with self.assertRaisesRegex(DeviceError,'Select Speaker A'):self.device.write_ab_destination(7)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
        self.fake.values[PARAMETERS['ab_enabled']]=0
        self.assertEqual(self.device.write_ab_destination(7),7)
        self.assertEqual(self.fake.values[PARAMETERS['ab_selected']],1)
    def test_ab_destination_noop_while_b_active_and_invalid_context(self):
        self.fake.values[PARAMETERS['ab_enabled']]=self.fake.values[PARAMETERS['ab_selected']]=1
        self.device.write_ab_destination(5)
        self.assertTrue(self.device.last_write['skipped'])
        self.fake.values[PARAMETERS['ab_destination']]=65535
        with self.assertRaises(DeviceError):self.device.write_ab_destination(3)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_ab_destination_and_trim_preserve_other_settings(self):
        names=('ab_enabled','ab_selected','dim_depth','dim','speaker_level')
        before={n:self.device.read(n) for n in names}
        self.device.write_ab_destination(9);self.device.step_ab_trim(-1)
        self.assertEqual({n:self.device.read(n) for n in names},before)
        self.assertTrue(all(v==0 for v in self.output_values.values()))
        self.assertTrue(all(c[2] in (75,77) for c in self.fake.calls if c[0]==0x40))
    def test_ab_trim_signed_db_payloads_and_live_b_adjustment(self):
        self.fake.values[PARAMETERS['ab_enabled']]=self.fake.values[PARAMETERS['ab_selected']]=1
        self.assertEqual(self.device.step_ab_trim(-1),-256)
        self.assertIn((0x40,0x11,75,0,b'\x00\xff',2,1000),self.fake.calls)
        self.assertEqual(self.device.monitor_settings_snapshot()['ab_trim_db'],-1)
        self.assertEqual(self.device.step_ab_trim(1),0)
        self.assertEqual(self.device.step_ab_trim(1),256)
        self.assertIn((0x40,0x11,75,0,b'\x00\x01',2,1000),self.fake.calls)
        self.assertEqual(self.fake.values[PARAMETERS['ab_selected']],1)
    def test_ab_trim_fractional_values_and_limits(self):
        self.fake.values[PARAMETERS['ab_trim']]=128
        self.assertEqual(self.device.step_ab_trim(1),384)
        self.assertEqual(self.device.monitor_settings_snapshot()['ab_trim_db'],1.5)
        count=len([c for c in self.fake.calls if c[0]==0x40])
        for signed,direction in ((-12*256,-1),(12*256,1)):
            self.fake.values[PARAMETERS['ab_trim']]=signed & 65535
            self.assertEqual(self.device.step_ab_trim(direction),signed)
            self.assertTrue(self.device.last_write['skipped'])
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),count)
    def test_ab_trim_unknown_value_not_overwritten(self):
        self.fake.values[PARAMETERS['ab_trim']]=32768
        with self.assertRaises(DeviceError):self.device.step_ab_trim(-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_ab_configuration_arguments_indices_and_version_guards(self):
        for first in (1,4,6,10,True,'5'):
            with self.assertRaises(ValueError):self.device.write_ab_destination(first)
        for direction in (0,2,True,None):
            with self.assertRaises(ValueError):self.device.step_ab_trim(direction)
        with self.assertRaises(ValueError):self.device.read('ab_trim',1)
        with self.assertRaises(ValueError):self.device.read('ab_destination',1)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_ab_destination(3)
        with self.assertRaises(DeviceError):self.device.step_ab_trim(1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_ab_configuration_rejection_no_resend_or_disconnect(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_ab_destination(7)
        self.assertEqual(self.device.last_write['requested_pair'],[7,8])
        with self.assertRaises(DeviceError):self.device.step_ab_trim(1)
        self.assertEqual(self.device.last_write['requested_db'],1)
        self.assertFalse(self.fake.closed)
        self.assertEqual([c[2] for c in self.fake.calls if c[0]==0x40],[77,75])

    def test_ab_snapshot_reads_existing_assignment_and_trim(self):
        self.fake.values[PARAMETERS['ab_trim']]=(-2*256)&65535
        state=self.device.monitor_settings_snapshot()
        self.assertEqual(state['ab_pair'],[5,6]);self.assertEqual(state['ab_trim_db'],-2)
        self.assertEqual(state['ab_enabled'],0);self.assertEqual(state['ab_selected'],0)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_ab_feature_enable_disable_exact_scalar_commands(self):
        self.assertEqual(self.device.write_ab_enabled(True),1)
        self.assertIn((0x40,0x11,76,0,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.write_ab_enabled(False),0)
        self.assertIn((0x40,0x11,76,0,b'\x00\x00',2,1000),self.fake.calls)
    def test_ab_selection_requires_enabled_and_uses_own_parameter(self):
        with self.assertRaises(DeviceError):self.device.write_ab_selected('B')
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
        self.device.write_ab_enabled(True)
        self.assertEqual(self.device.write_ab_selected('B'),1)
        self.assertIn((0x40,0x11,31,0,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.write_ab_selected('A'),0)
        self.assertIn((0x40,0x11,31,0,b'\x00\x00',2,1000),self.fake.calls)
    def test_ab_commands_preserve_assignment_trim_dim_and_levels(self):
        before={name:self.device.read(name) for name in ('ab_destination','ab_trim','dim_depth','dim','speaker_level')}
        self.device.write_ab_enabled(True);self.device.write_ab_selected('B');self.device.write_ab_selected('A')
        self.assertEqual({name:self.device.read(name) for name in before},before)
        self.assertTrue(all(v==0 for v in self.output_values.values()))
        self.assertTrue(all(c[2] in (31,76) for c in self.fake.calls if c[0]==0x40))
    def test_ab_unknown_assignment_or_trim_blocks_activation(self):
        for name,raw in (('ab_destination',4),('ab_trim',32768),('ab_selected',65535)):
            original=self.fake.values[PARAMETERS[name]]
            self.fake.values[PARAMETERS[name]]=raw
            with self.assertRaises(DeviceError):self.device.write_ab_enabled(True)
            self.fake.values[PARAMETERS[name]]=original
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_ab_return_to_a_and_disable_remain_possible_without_b_context(self):
        self.fake.values[PARAMETERS['ab_enabled']]=1
        self.fake.values[PARAMETERS['ab_selected']]=1
        self.fake.values[PARAMETERS['ab_destination']]=65535
        self.assertEqual(self.device.write_ab_selected('A'),0)
        self.assertEqual(self.device.write_ab_enabled(False),0)
    def test_ab_noop_version_and_argument_guards(self):
        self.device.write_ab_enabled(False)
        self.assertTrue(self.device.last_write['skipped'])
        for value in (1,None,'yes'):
            with self.assertRaises(ValueError):self.device.write_ab_enabled(value)
        for value in (1,None,'C'):
            with self.assertRaises(ValueError):self.device.write_ab_selected(value)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_ab_enabled(True)
        with self.assertRaises(DeviceError):self.device.write_ab_selected('A')
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_ab_read_failure_does_not_hide_valid_dim_depth(self):
        original=self.device.read
        def read(name,index=0):
            if name=='ab_enabled':raise DeviceError('A/B read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.monitor_settings_snapshot()
        self.assertIsNone(state['ab_enabled']);self.assertTrue(state['writes_available'])
        self.assertEqual(self.device.write_dim_depth(-20),-20)
        self.assertFalse(self.fake.closed)
    def test_ab_rejected_command_sent_once_and_keeps_handle(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_ab_enabled(True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertIn('ab_context_before',self.device.last_write)
        self.assertFalse(self.fake.closed)

    def test_monitor_dim_depth_enum_readback_is_not_db_scaling(self):
        self.assertEqual(self.device.monitor_settings_snapshot()['dim_depth_db'],-10)
        self.fake.values[PARAMETERS['dim_depth']]=1
        state=self.device.monitor_settings_snapshot()
        self.assertEqual(state['dim_depth_db'],-20);self.assertEqual(state['dim_depth_raw'],1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_monitor_dim_depth_exact_write_payloads(self):
        self.assertEqual(self.device.write_dim_depth(-20),-20)
        self.assertIn((0x40,0x11,28,0,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.last_write['requested_db'],-20)
        self.assertEqual(self.device.write_dim_depth(-10),-10)
        self.assertIn((0x40,0x11,28,0,b'\x00\x00',2,1000),self.fake.calls)
    def test_monitor_dim_depth_does_not_enable_dim_or_change_levels(self):
        before=self.device.read('speaker_level')
        self.device.write_dim_depth(-20)
        self.assertEqual(self.device.read('dim'),0)
        self.assertEqual(self.device.read('speaker_level'),before)
        self.assertTrue(all(v==0 for v in self.output_values.values()))
        self.assertTrue(all(c[2]==28 for c in self.fake.calls if c[0]==0x40))
    def test_monitor_dim_depth_noop_has_no_out(self):
        self.device.write_dim_depth(-10)
        self.assertTrue(self.device.last_write['confirmed'])
        self.assertTrue(self.device.last_write['skipped'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_monitor_dim_depth_unknown_values_preserved_not_written(self):
        for raw in (2,65535,(-20*256)&65535):
            self.fake.values[PARAMETERS['dim_depth']]=raw
            state=self.device.monitor_settings_snapshot()
            self.assertEqual(state['dim_depth_raw'],raw)
            self.assertIsNone(state['dim_depth_db']);self.assertFalse(state['writes_available'])
            with self.assertRaises(DeviceError):self.device.write_dim_depth(-10)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_monitor_dim_depth_argument_and_version_guards(self):
        for db in (0,-5,-30,True,'-10'):
            with self.assertRaises(ValueError):self.device.write_dim_depth(db)
        self.device.version=19
        self.assertFalse(self.device.monitor_settings_snapshot()['writes_available'])
        with self.assertRaises(DeviceError):self.device.write_dim_depth(-20)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_monitor_dim_depth_rejection_not_retried_keeps_handle(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_dim_depth(-20)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertEqual(self.device.last_write['requested_db'],-20)
        self.assertFalse(self.fake.closed)
    def test_monitor_dim_depth_read_failure_does_not_hide_monitor(self):
        original=self.device.read
        def read(name,index=0):
            if name=='dim_depth':raise DeviceError('Dim depth read failed')
            return original(name,index)
        self.device.read=read
        self.assertFalse(self.device.monitor_settings_snapshot()['writes_available'])
        self.assertTrue(self.device.snapshot()['writes_available'])
        self.assertFalse(self.fake.closed)

    def test_output_link_first_pair_and_other_member_selection(self):
        self.assertEqual(self.device.write_output_link(3,True),1)
        for index in (0,1):self.assertIn((0x40,0x11,32,index,b'\x01\x00',2,1000),self.fake.calls)
        state=self.device.output_snapshot(4)
        self.assertEqual(state['pair'],[3,4]);self.assertEqual(state['link'],1)
        self.assertEqual(state['link_bits'],[1,1])
        self.assertEqual(self.device.write_output_link(4,False),0)
        self.assertEqual(self.device.output_snapshot(3)['link'],0)
    def test_output_link_last_pair_preserves_other_pair_and_gain(self):
        self.input_values[32,0]=self.input_values[32,1]=1
        self.device.write_output_link(10,True)
        self.assertEqual(self.device.read('output_link'),0xc3)
        self.assertEqual(self.device.output_snapshot(9)['pair'],[9,10])
        self.device.write_output_link(9,False)
        self.assertEqual(self.device.read('output_link'),3)
        self.assertTrue(all(v==0 for v in self.output_values.values()))
        self.assertTrue(all(c[2]==32 for c in self.fake.calls if c[0]==0x40))
    def test_output_link_all_ones_and_mixed_flags(self):
        for index in range(16):self.input_values[32,index]=1
        self.assertEqual(self.device.output_snapshot(10)['link_mask'],65535)
        self.device.write_output_link(10,False)
        self.assertEqual(self.device.read('output_link'),0xff3f)
        self.input_values[32,1]=0
        state=self.device.output_snapshot(3)
        self.assertTrue(state['link_mixed']);self.assertIsNone(state['link'])
        self.device.write_output_link(3,True)
        self.assertEqual(self.device.output_snapshot(4)['link'],1)
    def test_output_link_noop_skips_out(self):
        self.device.write_output_link(3,False)
        self.assertTrue(self.device.last_write['confirmed'])
        self.assertEqual(self.device.last_write['transactions'],[])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_output_link_native_propagation_skips_second_write(self):
        original=self.fake.libusb_control_transfer.func
        def propagated(*args):
            result=original(*args)
            if args[1]==0x40 and args[3]==32:self.input_values[32,args[4]^1]=int.from_bytes(args[5],'little')
            return result
        self.fake.libusb_control_transfer=Fn(propagated)
        self.device.write_output_link(7,True)
        self.assertEqual(self.device.output_snapshot(8)['link'],1)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
    def test_output_link_partial_failure_no_rollback_or_repeat(self):
        original=self.fake.libusb_control_transfer.func
        def partial(*args):
            if args[1]==0x40 and args[3]==32 and args[4]==1:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]));return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(partial)
        with self.assertRaises(DeviceError):self.device.write_output_link(3,True)
        self.assertEqual(self.device.output_snapshot(3)['link_bits'],[1,0])
        self.assertTrue(self.device.output_snapshot(3)['link_mixed'])
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertEqual(len(self.device.last_write['transactions']),2)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),2)
        self.assertFalse(self.fake.closed)
    def test_output_link_and_gain_read_errors_are_independent(self):
        original=self.device.read
        for failed in ('output_gain','output_link'):
            def read(name,index=0):
                if name==failed:raise DeviceError('Read stalled')
                return original(name,index)
            self.device.read=read
            state=self.device.output_snapshot(3)
            self.assertEqual(state['writes_available'],failed!='output_gain')
            self.assertEqual(state['link_writes_available'],failed!='output_link')
        self.assertFalse(self.fake.closed)
    def test_output_link_rejects_invalid_channels_indices_and_version(self):
        for channel,value in ((2,True),(11,True),(True,True),(3,1)):
            with self.assertRaises(ValueError):self.device.write_output_link(channel,value)
        with self.assertRaises(ValueError):self.device.read_input_bit('output_link',8)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_output_link(3,True)
        state=self.device.output_snapshot(3)
        self.assertFalse(state['writes_available']);self.assertFalse(state['link_writes_available'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_output_first_last_channel_array_mapping_and_signed_scaling(self):
        for channel,index in ((3,0),(10,7)):
            self.output_values[index]=(-4*256)&65535
            self.assertEqual(self.device.output_snapshot(channel)['level_db'],-4)
            self.assertEqual(self.device.step_output_gain(channel,-1),-5*256)
            self.assertIn((0x40,0x11,33,index,b'\x00\xfb',2,1000),self.fake.calls)
            self.assertEqual(self.device.output_snapshot(channel)['level_db'],-5)
            self.assertEqual(self.device.step_output_gain(channel,1),-4*256)
    def test_output_gain_keeps_other_channels_and_speaker_level(self):
        before=self.device.read('speaker_level')
        self.device.step_output_gain(5,-1)
        self.assertEqual(self.output_values[2],(-256)&65535)
        self.assertTrue(all(v==0 for i,v in self.output_values.items() if i!=2))
        self.assertEqual(self.device.read('speaker_level'),before)
        self.assertTrue(all(v==0 for v in self.gain_values.values()))
        self.assertTrue(all(c[2]==33 for c in self.fake.calls if c[0]==0x40))
    def test_output_gain_boundaries_skip_writes(self):
        self.assertEqual(self.device.step_output_gain(3,1),0)
        self.output_values[0]=(-60*256)&65535
        self.assertEqual(self.device.step_output_gain(3,-1),-60*256)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_output_gain_fractional_readback_is_signed_not_integer_steps(self):
        self.output_values[0]=(-4*256-128)&65535
        self.assertEqual(self.device.output_snapshot(3)['level_db'],-4.5)
        self.device.step_output_gain(3,-1)
        self.assertEqual(self.device.output_snapshot(3)['level_db'],-5.5)
    def test_output_gain_invalid_values_not_clamped_or_written(self):
        for raw in (1,32768,(-61*256)&65535):
            self.output_values[0]=raw
            state=self.device.output_snapshot(3)
            self.assertEqual(state['level_raw'],raw)
            self.assertIsNone(state['level_db'])
            self.assertFalse(state['writes_available'])
            with self.assertRaises(DeviceError):self.device.step_output_gain(3,-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_output_snapshot_never_writes(self):
        self.assertEqual(self.device.output_snapshot(10)['output'],10)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_output_gain_argument_index_and_version_guards(self):
        for channel in (0,2,11,True):
            with self.assertRaises(ValueError):self.device.output_snapshot(channel)
            with self.assertRaises(ValueError):self.device.step_output_gain(channel,-1)
        for direction in (0,True,2):
            with self.assertRaises(ValueError):self.device.step_output_gain(3,direction)
        with self.assertRaises(ValueError):self.device.read('output_gain',8)
        self.device.version=19
        self.assertFalse(self.device.output_snapshot(3)['writes_available'])
        with self.assertRaises(DeviceError):self.device.step_output_gain(3,-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_output_gain_rejection_not_retried_keeps_monitor_connected(self):
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==33:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.step_output_gain(10,-1)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertFalse(self.fake.closed)
        self.assertEqual(self.device.snapshot()['mute'],0)

    def test_front_instrument_exact_channel_commands_and_readback(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        for channel,index in ((1,0),(2,1)):
            self.assertEqual(self.device.write_front_instrument(channel,True),1)
            self.assertIn((0x40,0x11,69,index,b'\x01\x00',2,1000),self.fake.calls)
            self.assertEqual(self.device.front_snapshot()['instrument'+str(channel)],1)
            self.assertEqual(self.device.write_front_instrument(channel,False),0)
            self.assertIn((0x40,0x11,69,index,b'\x00\x00',2,1000),self.fake.calls)
    def test_front_instrument_preserves_other_modes_pads_and_gains(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.input_values[69,1]=1
        self.input_values[67,0]=self.input_values[68,0]=1
        self.front_gain_values[71,0]=23
        self.device.write_front_instrument(1,True)
        self.assertEqual(self.device.read('front_line_instrument'),3)
        self.device.write_front_instrument(1,False)
        self.assertEqual(self.device.read('front_line_instrument'),2)
        self.assertEqual(self.front_gain_values[71,0],23)
        self.assertEqual(self.input_values[67,0],1)
        self.assertEqual(self.input_values[68,0],1)
        self.assertTrue(all(c[2]==69 for c in self.fake.calls if c[0]==0x40))
    def test_front_instrument_blocks_mic_and_rear_sources(self):
        for detection in (0,0x42):
            self.fake.values[PARAMETERS['detect_status']]=detection
            self.assertIsNone(self.device.front_snapshot()['instrument1'])
            with self.assertRaises(DeviceError):self.device.write_front_instrument(1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_instrument_rechecks_source_after_snapshot(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertEqual(self.device.front_snapshot()['instrument1'],0)
        self.input_values[72,0]=1
        with self.assertRaises(DeviceError):self.device.write_front_instrument(1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_instrument_noop_and_guards(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.device.write_front_instrument(1,False)
        self.assertTrue(self.device.last_write['confirmed'])
        for channel,value in ((0,True),(3,True),(True,True),(1,1)):
            with self.assertRaises(ValueError):self.device.write_front_instrument(channel,value)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_front_instrument(1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_instrument_read_error_leaves_gain_and_pad_available(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.device.read
        def read(name,index=0):
            if name=='front_line_instrument':raise DeviceError('Mode read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.front_snapshot()
        self.assertIsNone(state['instrument1'])
        self.assertEqual(state['gain1'],0)
        self.assertEqual(state['pad1'],0)
        self.assertIn('instrument1',state['errors'])
    def test_front_instrument_rejection_sent_once_keeps_handle(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==69:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.write_front_instrument(1,True)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.fake.closed)
    def test_front_instrument_needs_only_selected_input_to_be_jack(self):
        self.fake.values[PARAMETERS['detect_status']]=0x41
        self.device.write_front_instrument(1,True)
        with self.assertRaises(DeviceError):self.device.write_front_instrument(2,True)
        self.assertEqual(self.device.read('front_line_instrument'),1)

    def test_front_gain_line_second_input_uses_array_index(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.front_gain_values[71,1]=12
        self.assertEqual(self.device.front_snapshot()['gain2'],12)
        self.assertEqual(self.device.step_front_gain(2,'line',1),13)
        self.assertIn((0x40,0x11,71,1,b'\x0d\x00',2,1000),self.fake.calls)
        self.assertEqual(self.front_gain_values[71,0],0)
        self.assertEqual(self.front_gain_values[70,1],0)
        self.assertEqual(self.gain_values[1],0)
        self.assertEqual(self.device.front_snapshot()['gain2'],13)
    def test_front_gain_mic_uses_integer_step_not_fixed_point(self):
        self.fake.values[PARAMETERS['detect_status']]=0x42
        self.front_gain_values[70,0]=30
        self.assertEqual(self.device.step_front_gain(1,'mic',-1),29)
        self.assertIn((0x40,0x11,70,0,b'\x1d\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.front_snapshot()['gain1'],29)
    def test_front_gain_boundaries_noop(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertEqual(self.device.step_front_gain(1,'line',-1),0)
        self.front_gain_values[71,0]=55
        self.assertEqual(self.device.step_front_gain(1,'line',1),55)
        self.assertTrue(self.device.last_write['confirmed'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_gain_invalid_current_value_retained_and_not_written(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.front_gain_values[71,0]=65535
        state=self.device.front_snapshot()
        self.assertEqual(state['gain1'],65535)
        self.assertIn('gain1',state['errors'])
        self.assertEqual(state['gain2'],0)
        with self.assertRaises(DeviceError):self.device.step_front_gain(1,'line',1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_gain_source_change_blocks_wrong_path(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertEqual(self.device.front_snapshot()['gain1'],0)
        self.fake.values[PARAMETERS['detect_status']]=0x42
        with self.assertRaisesRegex(DeviceError,'source changed'):
            self.device.step_front_gain(1,'line',1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_gain_failure_does_not_hide_other_front_controls(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.device.read
        def read(name,index=0):
            if name=='front_line_gain' and index==0:raise DeviceError('Gain read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.front_snapshot()
        self.assertIsNone(state['gain1'])
        self.assertEqual(state['gain2'],0)
        self.assertEqual(state['hpf1'],0)
        self.assertEqual(state['phase1'],0)
        self.assertEqual(state['line'],0)
    def test_front_gain_version_and_argument_guards(self):
        for channel,kind,direction in ((0,'line',1),(3,'line',1),(1,'rear',1),(1,'mic',0),(1,'mic',True)):
            with self.assertRaises(ValueError):self.device.step_front_gain(channel,kind,direction)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.step_front_gain(1,'line',1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_gain_indices_are_limited_to_two_elements(self):
        with self.assertRaises(ValueError):self.device.read('front_line_gain',2)
        self.assertFalse(any(c[2]==71 for c in self.fake.calls))
    def test_front_gain_rejected_write_not_retried_or_disconnected(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==71:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.step_front_gain(1,'line',1)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertFalse(self.fake.closed)

    def test_front_line_polarity_uses_selected_bit_and_preserves_other_paths(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.input_values[18,7]=1
        self.input_values[19,1]=1
        self.device.write_front_phase(2,'line',True)
        self.assertEqual(self.device.read('front_line_phase'),130)
        self.assertEqual(self.device.read('rear_phase'),2)
        self.assertEqual(self.device.read('front_mic_phase'),0)
        self.assertIn((0x40,0x11,18,1,b'\x01\x00',2,1000),self.fake.calls)
        state=self.device.front_snapshot()
        self.assertEqual((state['phase1'],state['phase2']),(0,1))
        self.device.write_front_phase(2,'line',False)
        self.assertEqual(self.device.read('front_line_phase'),128)
    def test_front_mic_polarity_uses_mic_parameter(self):
        self.fake.values[PARAMETERS['detect_status']]=0x42
        self.device.write_front_phase(1,'mic',True)
        self.assertIn((0x40,0x11,17,0,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.front_snapshot()['phase1'],1)
    def test_front_phase_source_change_blocks_stale_mode(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertEqual(self.device.front_snapshot()['phase1'],0)
        self.fake.values[PARAMETERS['detect_status']]=0x42
        with self.assertRaisesRegex(DeviceError,'source changed'):
            self.device.write_front_phase(1,'line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_phase_read_error_does_not_hide_link(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.device.read
        def read(name,index=0):
            if name=='front_line_phase':raise DeviceError('Phase read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.front_snapshot()
        self.assertEqual(state['line'],0)
        self.assertIsNone(state['phase1'])
        self.assertIn('phase1',state['errors'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_phase_noop_and_version_guard(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.device.write_front_phase(1,'line',False)
        self.assertTrue(self.device.last_write['confirmed'])
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_front_phase(1,'line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_phase_rejection_no_retry_no_disconnect(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==18:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.write_front_phase(1,'line',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertFalse(self.fake.closed)
    def test_front_phase_invalid_inputs_rejected_without_write(self):
        for channel,kind,value in ((0,'line',True),(3,'line',True),(1,'rear',True),(1,'mic',1)):
            with self.assertRaises(ValueError):self.device.write_front_phase(channel,kind,value)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_front_line_hpf_uses_selected_bit_and_preserves_other_paths(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.input_values[96,7]=1
        self.input_values[97,1]=1
        self.device.write_front_hpf(2,'line',True)
        self.assertEqual(self.device.read('front_line_hpf'),130)
        self.assertEqual(self.device.read('rear_hpf'),2)
        self.assertEqual(self.device.read('front_mic_hpf'),0)
        self.assertIn((0x40,0x11,96,1,b'\x01\x00',2,1000),self.fake.calls)
        state=self.device.front_snapshot()
        self.assertEqual((state['hpf1'],state['hpf2']),(0,1))
        self.device.write_front_hpf(2,'line',False)
        self.assertEqual(self.device.read('front_line_hpf'),128)
    def test_front_mic_hpf_uses_mic_parameter(self):
        self.fake.values[PARAMETERS['detect_status']]=0x42
        self.device.write_front_hpf(1,'mic',True)
        self.assertIn((0x40,0x11,95,0,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.front_snapshot()['hpf1'],1)
    def test_front_hpf_source_change_blocks_stale_mode(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertEqual(self.device.front_snapshot()['hpf1'],0)
        self.fake.values[PARAMETERS['detect_status']]=0x42
        with self.assertRaisesRegex(DeviceError,'source changed'):
            self.device.write_front_hpf(1,'line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_hpf_read_error_does_not_hide_link(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.device.read
        def read(name,index=0):
            if name=='front_line_hpf':raise DeviceError('Phase read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.front_snapshot()
        self.assertEqual(state['line'],0)
        self.assertIsNone(state['hpf1'])
        self.assertIn('hpf1',state['errors'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_hpf_noop_and_version_guard(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.device.write_front_hpf(1,'line',False)
        self.assertTrue(self.device.last_write['confirmed'])
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_front_hpf(1,'line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_hpf_rejection_no_retry_no_disconnect(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==96:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.write_front_hpf(1,'line',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertFalse(self.fake.closed)
    def test_front_hpf_invalid_inputs_rejected_without_write(self):
        for channel,kind,value in ((0,'line',True),(3,'line',True),(1,'rear',True),(1,'mic',1)):
            with self.assertRaises(ValueError):self.device.write_front_hpf(channel,kind,value)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_front_line_pad_uses_selected_bit_and_preserves_other_paths(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.input_values[67,7]=1
        self.input_values[68,1]=1
        self.device.write_front_pad(2,'line',True)
        self.assertEqual(self.device.read('front_line_pad'),130)
        self.assertEqual(sum(self.input_values[68,i] << i for i in range(16)),2)
        self.assertEqual(self.device.read('front_mic_pad'),0)
        self.assertIn((0x40,0x11,67,1,b'\x01\x00',2,1000),self.fake.calls)
        state=self.device.front_snapshot()
        self.assertEqual((state['pad1'],state['pad2']),(0,1))
        self.device.write_front_pad(2,'line',False)
        self.assertEqual(self.device.read('front_line_pad'),128)
    def test_front_mic_pad_uses_mic_parameter(self):
        self.fake.values[PARAMETERS['detect_status']]=0x42
        self.device.write_front_pad(1,'mic',True)
        self.assertIn((0x40,0x11,66,0,b'\x01\x00',2,1000),self.fake.calls)
        self.assertEqual(self.device.front_snapshot()['pad1'],1)
    def test_front_pad_source_change_blocks_stale_mode(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertEqual(self.device.front_snapshot()['pad1'],0)
        self.fake.values[PARAMETERS['detect_status']]=0x42
        with self.assertRaisesRegex(DeviceError,'source changed'):
            self.device.write_front_pad(1,'line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_pad_read_error_does_not_hide_link(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.device.read
        def read(name,index=0):
            if name=='front_line_pad':raise DeviceError('Phase read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.front_snapshot()
        self.assertEqual(state['line'],0)
        self.assertIsNone(state['pad1'])
        self.assertIn('pad1',state['errors'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_pad_noop_and_version_guard(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.device.write_front_pad(1,'line',False)
        self.assertTrue(self.device.last_write['confirmed'])
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_front_pad(1,'line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_pad_rejection_no_retry_no_disconnect(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==67:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.write_front_pad(1,'line',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertFalse(self.fake.closed)
    def test_front_pad_invalid_inputs_rejected_without_write(self):
        for channel,kind,value in ((0,'line',True),(3,'line',True),(1,'rear',True),(1,'mic',1)):
            with self.assertRaises(ValueError):self.device.write_front_pad(channel,kind,value)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_reported_rear_override_blocks_front_without_out(self):
        for i in range(16): self.input_values[72,i]=1
        self.fake.values[PARAMETERS['detect_status']]=49
        state=self.device.front_snapshot()
        self.assertEqual(state['source_status']['sources'],['rear','rear'])
        self.assertFalse(any(state['source_status']['available'].values()))
        with self.assertRaisesRegex(DeviceError,'Rear override'):
            self.device.write_front_link('line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_enable_front_detection_then_link_preserves_other_source_bits(self):
        for i in range(16): self.input_values[72,i]=1
        self.fake.values[PARAMETERS['detect_status']]=49
        self.device.set_rear_pair_source(1,False)
        self.assertEqual(self.device.read('force_rear'),65532)
        self.assertEqual(self.device.front_snapshot()['source_status']['sources'],['line','line'])
        self.device.write_front_link('line',True)
        self.assertEqual([(c[2],c[3]) for c in self.fake.calls if c[0]==0x40],[(72,0),(72,1),(22,0)])
    def test_source_decoder_partial_override_matches_report(self):
        state=front_source_status({'raw':{'force_rear':65533,'detect_status':49}})
        self.assertEqual(state['sources'],['rear','line'])
        self.assertFalse(any(state['available'].values()))
    def test_source_decoder_front_mics(self):
        state=front_source_status({'raw':{'force_rear':0,'detect_status':0x42}})
        self.assertEqual(state['sources'],['mic','mic'])
        self.assertTrue(state['available']['mic'])
        self.assertFalse(state['available']['line'])
    def test_source_decoder_no_front_connection_keeps_rear(self):
        state=front_source_status({'raw':{'force_rear':0,'detect_status':0}})
        self.assertEqual(state['sources'],['rear','rear'])
        self.assertIn('No compatible',state['reason']['line'])
    def test_source_decoder_mixed_front_types_blocks_both(self):
        state=front_source_status({'raw':{'force_rear':0,'detect_status':0x41}})
        self.assertEqual(state['sources'],['line','mic'])
        self.assertFalse(any(state['available'].values()))
    def test_source_decoder_missing_status_is_not_assumed_front(self):
        state=front_source_status({'raw':{'force_rear':0},'errors':{'detect_status':'failed'}})
        self.assertIsNone(state['sources'])
        self.assertFalse(any(state['available'].values()))
    def test_source_change_after_snapshot_is_rechecked_before_link(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.assertTrue(self.device.front_snapshot()['source_status']['available']['line'])
        self.input_values[72,1]=1
        with self.assertRaises(DeviceError): self.device.write_front_link('line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_front_links_use_native_index_zero_and_distinct_parameters(self):
        for kind, param in (('line',22),('mic',23)):
            self.fake.values[PARAMETERS['detect_status']] = 0x21 if kind == 'line' else 0x42
            self.assertEqual(self.device.write_front_link(kind,True),1)
            writes=[c for c in self.fake.calls if c[0]==0x40]
            self.assertEqual(writes[-1],(0x40,0x11,param,0,b'\x01\x00',2,1000))
            self.assertEqual(self.device.front_snapshot()[kind],1)
            self.device.write_front_link(kind,False)
            self.assertEqual(self.device.front_snapshot()[kind],0)
        self.assertTrue(all(c[2] in (22,23) for c in self.fake.calls if c[0]==0x40))
    def test_front_link_preserves_rear_and_other_front_bits(self):
        self.fake.values[PARAMETERS['detect_status']] = 0x21
        self.input_values[22,7]=1
        self.input_values[23,0]=1
        self.input_values[24,0]=1
        self.device.write_front_link('line',True)
        self.assertEqual(self.device.read('front_line_link'),129)
        self.assertEqual(self.device.read('front_mic_link'),1)
        self.assertEqual(self.device.read('rear_link'),1)
    def test_front_snapshot_reads_only_and_reports_fields_independently(self):
        original=self.device.read
        def read(name,index=0):
            if name=='front_mic_link':raise DeviceError('mic read failed')
            return original(name,index)
        self.device.read=read
        state=self.device.front_snapshot()
        self.assertEqual(state['line'],0)
        self.assertIsNone(state['mic'])
        self.assertIn('mic',state['errors'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_noop_and_version_guard(self):
        self.fake.values[PARAMETERS['detect_status']] = 0x21
        self.device.write_front_link('line',False)
        self.assertTrue(self.device.last_write['confirmed'])
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_front_link('line',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_front_rejection_is_reported_without_retry_or_disconnect(self):
        self.fake.values[PARAMETERS['detect_status']] = 0x21
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==22:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaisesRegex(DeviceError,'compatible modes'):
            self.device.write_front_link('line',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertIn('context_before',self.device.last_write)
        self.assertFalse(self.fake.closed)
    def test_front_invalid_kind_and_non_bool_rejected(self):
        for kind,value in (('rear',True),('line',1),('mic',None)):
            with self.assertRaises(ValueError):self.device.write_front_link(kind,value)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_rear_pad_first_and_last_inputs_use_exact_bit_requests(self):
        for channel,index in ((1,0),(16,15)):
            self.input_values[68,index]=1
            self.assertEqual(self.device.write_input_bool(channel,'pad',True),1)
            self.assertIn((0x40,0x11,68,index,b'\x00\x00',2,1000),self.fake.calls)
            self.assertEqual(self.device.last_write['logical_requested'],1)
            self.assertEqual(self.device.last_write['requested'],0)
            self.assertEqual(self.device.input_snapshot(channel)['pad'],1)
            self.assertEqual(self.device.write_input_bool(channel,'pad',False),0)
            self.assertIn((0x40,0x11,68,index,b'\x01\x00',2,1000),self.fake.calls)
            self.assertEqual(self.device.input_snapshot(channel)['pad'],0)
            self.assertEqual(self.device.last_write['logical_requested'],0)
            self.assertEqual(self.device.last_write['requested'],1)
        self.assertTrue(all(c[2]==68 for c in self.fake.calls if c[0]==0x40))
        self.assertTrue(all(v==0 for (param,index),v in self.input_values.items() if param!=68))
    def test_rear_pad_preserves_other_input_flags_and_front_pad(self):
        self.input_values[68,4]=1
        self.input_values[68,15]=1
        self.input_values[67,0]=1
        self.input_values[66,1]=1
        self.device.write_input_bool(16,'pad',True)
        self.assertEqual(self.device.input_snapshot(1)['packed_words']['pad'],0x10)
        self.device.write_input_bool(16,'pad',False)
        self.assertEqual(self.device.input_snapshot(1)['packed_words']['pad'],0x8010)
        self.assertEqual(self.input_values[67,0],1)
        self.assertEqual(self.input_values[66,1],1)
        self.assertEqual(self.device.input_snapshot(5)['pad'],0)
    def test_rear_pad_all_ones_is_valid(self):
        for index in range(16):self.input_values[68,index]=1
        state=self.device.input_snapshot(10)
        self.assertEqual(state['packed_words']['pad'],65535)
        self.assertEqual(state['pad'],0)
        self.assertTrue(state['control_available']['pad'])
        self.device.write_input_bool(10,'pad',True)
        self.assertEqual(self.input_values[68,8],1)
        self.assertEqual(self.input_values[68,9],0)
        self.assertEqual(self.input_values[68,10],1)
    def test_rear_pad_noop_has_no_out(self):
        self.assertEqual(self.device.write_input_bool(5,'pad',True),1)
        self.input_values[68,4]=1
        self.assertEqual(self.device.write_input_bool(5,'pad',False),0)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_reported_rear_pad_led_mapping_is_active_low_for_all_inputs(self):
        for channel in range(1,17):
            index=channel-1
            self.input_values[68,index]=0
            state=self.device.input_snapshot(channel)
            self.assertEqual(state['pad'],1)
            self.assertEqual(state['raw_switches']['pad'],0)
            self.input_values[68,index]=1
            state=self.device.input_snapshot(channel)
            self.assertEqual(state['pad'],0)
            self.assertEqual(state['raw_switches']['pad'],1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_rear_pad_inversion_does_not_invert_front_pad_or_phase_hpf(self):
        self.fake.values[PARAMETERS['detect_status']]=49
        self.input_values[68,0]=1
        self.input_values[67,0]=1
        self.input_values[19,0]=1
        self.input_values[97,0]=1
        rear=self.device.input_snapshot(1)
        front=self.device.front_snapshot()
        self.assertEqual(rear['pad'],0)
        self.assertEqual(front['pad1'],1)
        self.assertEqual((rear['phase'],rear['hpf']),(1,1))

    def test_rear_pad_read_error_is_isolated(self):
        original=self.device.read
        def read(name,index=0):
            if name=='rear_pad':raise DeviceError('Pad read stalled')
            return original(name,index)
        self.device.read=read
        state=self.device.input_snapshot(8)
        self.assertIsNone(state['pad'])
        self.assertFalse(state['control_available']['pad'])
        self.assertTrue(state['control_available']['phase'])
        self.assertTrue(state['control_available']['hpf'])
        self.assertTrue(state['control_available']['gain'])
        self.assertTrue(state['control_available']['link'])
        self.assertEqual(self.device.write_input_bool(8,'phase',True),1)
        self.assertFalse(self.fake.closed)
    def test_rear_pad_rejection_not_retried_or_disconnected(self):
        self.input_values[68,15]=1
        original=self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1]==0x40 and args[3]==68:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer=Fn(refused)
        with self.assertRaises(DeviceError):self.device.write_input_bool(16,'pad',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertFalse(self.fake.closed)
    def test_rear_pad_argument_and_version_guards(self):
        for channel,value in ((0,True),(17,True),(True,True),(1,1)):
            with self.assertRaises(ValueError):self.device.write_input_bool(channel,'pad',value)
        self.device.version=19
        with self.assertRaises(DeviceError):self.device.write_input_bool(1,'pad',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_input_1_polarity_maps_to_element_0(self):
        self.assertEqual(self.device.write_input_bool(1, 'phase', True), 1)
        self.assertIn((0x40, 0x11, 19, 0, b'\x01\x00', 2, 1000), self.fake.calls)

    def test_input_16_hpf_maps_to_element_15(self):
        self.assertEqual(self.device.write_input_bool(16, 'hpf', True), 1)
        self.assertIn((0x40, 0x11, 97, 15, b'\x01\x00', 2, 1000), self.fake.calls)
        self.assertEqual(self.input_values[97, 0], 0)
        self.assertEqual(self.input_values[19, 15], 0)

    def test_snapshot_is_read_only_for_selected_input(self):
        self.input_values[19, 7] = 1
        state = self.device.input_snapshot(8)
        self.assertEqual((state['channel'], state['phase'], state['hpf']), (8, 1, 0))
        self.assertTrue(state['writes_available'])
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_out_of_range_and_invalid_controls_rejected(self):
        for channel in (0, 17, -1, True):
            with self.assertRaises(ValueError): self.device.input_snapshot(channel)
            with self.assertRaises(ValueError): self.device.write_input_bool(channel, 'phase', True)
        for name, value in [('gain', True), ('phase', 1)]:
            with self.assertRaises(ValueError): self.device.write_input_bool(1, name, value)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_scalar_index_cannot_target_another_element(self):
        with self.assertRaises(ValueError): self.device.read('mute', 1)
        with self.assertRaises(ValueError): self.device.read('rear_phase', 16)
        with self.assertRaises(ValueError): self.device.read('rear_hpf', -1)
        with self.assertRaises(ValueError): self.device.read('rear_phase', 1)

    def test_all_ones_is_valid_packed_word(self):
        for bit in range(16): self.input_values[97, bit] = 1
        state = self.device.input_snapshot(4)
        self.assertTrue(state['control_available']['hpf'])
        self.assertEqual(state['hpf'], 1)
        self.assertEqual(state['packed_words']['hpf'], 65535)
        self.assertEqual(self.device.write_input_bool(4, 'hpf', False), 0)
        self.assertEqual(self.input_values[97, 2], 1)
        self.assertEqual(self.input_values[97, 3], 0)
        self.assertEqual(self.input_values[97, 4], 1)

    def test_version_mismatch_prevents_input_write(self):
        self.device.version = 19
        with self.assertRaises(DeviceError): self.device.write_input_bool(16, 'hpf', True)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_same_state_does_not_write(self):
        self.assertEqual(self.device.write_input_bool(16, 'hpf', False), 0)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_input_read_failure_does_not_close_monitor_connection(self):
        from af16rig_gui import Worker
        class FailingInput(DemoAF16Rig):
            def input_snapshot(self, channel): raise DeviceError('input read stall')
        device = FailingInput(); events = queue.Queue()
        worker = Worker(events, factory=lambda: device); worker.start()
        try:
            worker.commands.put(('connect', None))
            self.assertEqual(events.get(timeout=2)['kind'], 'connected')
            self.assertEqual(events.get(timeout=2)['kind'], 'snapshot')
            worker.commands.put(('input_select', 16))
            self.assertEqual(events.get(timeout=2)['kind'], 'input_error')
            worker.commands.put(('set', ('mute', True)))
            self.assertEqual(events.get(timeout=2)['kind'], 'written')
            self.assertEqual(events.get(timeout=2)['kind'], 'snapshot')
            self.assertIs(worker.device, device)
        finally:
            worker.stop_event.set(); worker.join(timeout=2)

    def test_hpf_read_error_preserves_valid_polarity(self):
        original = self.device.read
        def one_failure(name, index=0):
            if name == 'rear_hpf': raise DeviceError('HPF read stalled')
            return original(name, index)
        self.device.read = one_failure
        state = self.device.input_snapshot(4)
        self.assertEqual(state['phase'], 0)
        self.assertTrue(state['control_available']['phase'])
        self.assertIsNone(state['hpf'])
        self.assertFalse(state['control_available']['hpf'])
        self.assertIn('stalled', state['errors']['hpf'])
        self.assertEqual(self.device.write_input_bool(4, 'phase', True), 1)

    def test_both_input_read_errors_return_diagnostic_snapshot(self):
        def failure(name, index=0): raise DeviceError('read error')
        self.device.read = failure
        state = self.device.input_snapshot(16)
        self.assertFalse(state['writes_available'])
        self.assertEqual(set(state['errors']), {'phase', 'hpf', 'pad', 'gain', 'link'})

    def test_removed_device_is_not_hidden_by_partial_read_handler(self):
        def removed(name, index=0): raise DeviceDisconnected('removed')
        self.device.read = removed
        with self.assertRaises(DeviceDisconnected): self.device.input_snapshot(1)

    def test_exact_report_mask_16_selects_input_5_not_1(self):
        self.input_values[19, 4] = 1
        self.assertEqual(self.device.input_snapshot(1)['phase'], 0)
        self.assertEqual(self.device.input_snapshot(2)['phase'], 0)
        state = self.device.input_snapshot(5)
        self.assertEqual(state['phase'], 1)
        self.assertEqual(state['packed_words']['phase'], 16)

    def test_set_and_clear_input_16_preserves_input_5(self):
        self.input_values[19, 4] = 1
        self.assertEqual(self.device.write_input_bool(16, 'phase', True), 1)
        self.assertEqual(self.device.input_snapshot(1)['packed_words']['phase'], 0x8010)
        self.assertEqual(self.device.write_input_bool(16, 'phase', False), 0)
        self.assertEqual(self.device.input_snapshot(1)['packed_words']['phase'], 0x0010)
        self.assertEqual(self.input_values[19, 4], 1)

    def test_gain_input_16_uses_word_index_15(self):
        self.assertEqual(self.device.step_input_gain(16, 1), 256)
        self.assertIn((0x40, 0x11, 20, 15, b'\x00\x01', 2, 1000), self.fake.calls)
        self.assertEqual(self.gain_values[0], 0)
        self.assertEqual(self.device.input_snapshot(16)['gain_db'], 1.0)
        self.assertEqual(self.device.step_input_gain(16, -1), 0)

    def test_gain_clamps_to_initial_software_range(self):
        self.gain_values[3] = 3000
        self.assertEqual(self.device.step_input_gain(4, 1), 3072)
        count = len([c for c in self.fake.calls if c[0] == 0x40])
        self.assertEqual(self.device.step_input_gain(4, 1), 3072)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), count)

    def test_gain_outside_range_does_not_block_switches(self):
        self.gain_values[4] = 0xffff
        state = self.device.input_snapshot(5)
        self.assertEqual(state['gain_db'], -1/256)
        self.assertFalse(state['control_available']['gain'])
        self.assertTrue(state['control_available']['phase'])
        with self.assertRaises(DeviceError): self.device.step_input_gain(5, 1)
        self.assertEqual(self.device.write_input_bool(5, 'phase', True), 1)

    def test_gain_reads_current_channel_value_before_increment(self):
        self.gain_values[7] = 768
        self.assertEqual(self.device.step_input_gain(8, 1), 1024)
        self.assertEqual(self.gain_values[8], 0)

    def test_gain_invalid_indices_steps_and_version_do_not_write(self):
        for channel, direction in [(0,1), (17,1), (True,1), (1,2), (1,True)]:
            with self.assertRaises(ValueError): self.device.step_input_gain(channel,direction)
        self.device.version = 19
        with self.assertRaises(DeviceError): self.device.step_input_gain(1,1)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_source_gated_link_recovers_after_explicit_rear_selection(self):
        original = self.fake.libusb_control_transfer.func
        def gated(*args):
            if args[1] == 0x40 and args[3] == 24 and not all(self.input_values[(72,i)] for i in (0,1)):
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2
            return original(*args)
        self.fake.libusb_control_transfer = Fn(gated)
        with self.assertRaises(DeviceError): self.device.write_input_link(1, True)
        self.assertEqual(self.device.read('force_rear'), 0)
        self.device.set_rear_pair_source(1, True)
        self.assertEqual(self.device.write_input_link(1, True), 1)
        self.assertTrue(self.device.input_snapshot(1)['link'])
        self.assertFalse(self.fake.closed)

    def test_explicit_rear_source_pair_preserves_other_pair(self):
        self.input_values[(72,2)] = self.input_values[(72,3)] = 1
        self.device.set_rear_pair_source(1, True)
        self.assertEqual(self.device.read('force_rear'), 15)
        self.device.set_rear_pair_source(2, False)
        self.assertEqual(self.device.read('force_rear'), 12)
        writes = [c for c in self.fake.calls if c[0] == 0x40]
        self.assertEqual([(c[1],c[2],c[3]) for c in writes], [(0x11,72,0),(0x11,72,1)]*2)
    def test_invalid_rear_source_selection_is_rejected(self):
        for channel, force in ((0,True),(5,True),(1,1)):
            with self.assertRaises(ValueError): self.device.set_rear_pair_source(channel,force)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_link_context_records_source_reads_without_writes(self):
        self.input_values[(72,0)] = self.input_values[(72,1)] = 1
        self.fake.values[PARAMETERS['detect_status']] = 0x42
        self.fake.values[PARAMETERS['front_mic_status']] = 5
        state = self.device.input_snapshot(1)
        self.assertEqual(state['link_context']['raw'],
                         {'force_rear': 3, 'detect_status': 0x42, 'front_mic_status': 5})
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

    def test_source_read_failure_preserves_input_controls(self):
        original = self.device.read
        def failed(name, index=0):
            if name == 'detect_status': raise DeviceError('detection unavailable')
            return original(name, index)
        self.device.read = failed
        state = self.device.input_snapshot(1)
        self.assertTrue(state['control_available']['gain'])
        self.assertTrue(state['control_available']['phase'])
        self.assertFalse(state['control_available']['link'])
        self.assertIn('detect_status', state['link_context']['errors'])
        self.assertEqual(state['link_context']['raw']['force_rear'], 0)

    def test_reported_link_rejection_collects_context_and_keeps_handle(self):
        original = self.fake.libusb_control_transfer.func
        def refused(*args):
            if args[1] == 0x40 and args[3] == 24:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return 2  # TEST11: accepted USB transfer, unchanged packed flags.
            return original(*args)
        self.fake.libusb_control_transfer = Fn(refused)
        with self.assertRaisesRegex(DeviceError, 'selected link bank: REAR'):
            self.device.write_input_link(1, True)
        result = self.device.last_write
        self.assertFalse(result['confirmed'])
        self.assertIn('context_before', result)
        self.assertIn('context_after', result)
        self.assertFalse(self.fake.closed)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 1)
        self.assertEqual(self.device.write_bool('mute', True), 1)

    def test_link_first_pair_updates_two_flags_and_verifies(self):
        self.assertEqual(self.device.write_input_link(1, True), 1)
        out = [c for c in self.fake.calls if c[0] == 0x40]
        self.assertEqual([(c[1],c[2],c[3],c[4]) for c in out], [(0x11,24,0,b'\x01\x00'),(0x11,24,1,b'\x01\x00')])
        state = self.device.input_snapshot(2)
        self.assertEqual(state['pair'], [1,2])
        self.assertEqual(state['link_bits'], [1,1])
        self.assertEqual(state['link'], 1)

    def test_link_last_pair_preserves_other_pair(self):
        self.input_values[24,4] = self.input_values[24,5] = 1
        self.device.write_input_link(16, True)
        self.assertEqual(self.device.input_snapshot(15)['pair'], [15,16])
        self.assertEqual(self.device.input_snapshot(15)['link'], 1)
        self.assertEqual(self.device.input_snapshot(5)['link'], 1)
        self.device.write_input_link(15, False)
        self.assertEqual(self.input_values[24,4], 1)
        self.assertEqual(self.input_values[24,5], 1)
        self.assertEqual(self.input_values[24,14], 0)
        self.assertEqual(self.input_values[24,15], 0)

    def test_mixed_link_flags_are_explicit(self):
        self.input_values[24,0] = 1
        state = self.device.input_snapshot(1)
        self.assertTrue(state['link_mixed'])
        self.assertIsNone(state['link'])
        self.assertEqual(state['link_bits'], [1,0])

    def test_link_already_set_does_not_write(self):
        self.device.write_input_link(2, False)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))
        self.assertTrue(self.device.last_write['confirmed'])

    def test_native_pair_propagation_skips_redundant_second_write(self):
        original = self.fake.libusb_control_transfer.func
        def propagated(*args):
            result = original(*args)
            if args[1] == 0x40 and args[3] == 24:
                self.input_values[24,args[4]^1] = int.from_bytes(args[5], 'little')
            return result
        self.fake.libusb_control_transfer = Fn(propagated)
        self.device.write_input_link(1, True)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 1)

    def test_partial_link_failure_is_reported_without_rollback_or_retry(self):
        original = self.fake.libusb_control_transfer.func
        def fail_second(*args):
            if args[1] == 0x40 and args[3] == 24 and args[4] == 1:
                self.fake.calls.append((args[1],args[2],args[3],args[4],bytes(args[5]),args[6],args[7]))
                return -9
            return original(*args)
        self.fake.libusb_control_transfer = Fn(fail_second)
        with self.assertRaises(DeviceError): self.device.write_input_link(1, True)
        self.assertFalse(self.device.last_write['confirmed'])
        self.assertEqual(len(self.device.last_write['transactions']), 2)
        self.assertTrue(self.device.input_snapshot(1)['link_mixed'])
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 0x40]), 2)

    def test_link_rejects_invalid_channels_values_and_version(self):
        for channel, value in [(0,True),(17,True),(True,True),(1,1)]:
            with self.assertRaises(ValueError): self.device.write_input_link(channel,value)
        self.device.version = 19
        with self.assertRaises(DeviceError): self.device.write_input_link(1,True)
        self.assertFalse(any(c[0] == 0x40 for c in self.fake.calls))

class MixerMasterTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    # Use the common native USB fixture without inheriting its unrelated cases.
    def test_snapshot_exact_reads_and_signed_levels(self):
        state=self.device.mixer_masters_snapshot()
        self.assertEqual(state['levels']['main']['db'],-12)
        self.assertEqual(state['levels']['cue']['db'],-6)
        calls=[(c[0],c[1],c[2],c[3]) for c in self.fake.calls[-9:]]
        self.assertEqual(calls,[(0xc0,0x91,n,0) for n in list(range(56,63))+[55,63]])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_exact_write_only_selected_bus(self):
        for bus,param in (('main',56),('cue',57)):
            self.fake.calls.clear();other='cue' if bus=='main' else 'main'
            untouched=self.fake.values[PARAMETERS[other+'_master']]
            value=self.device.step_mixer_master(bus,-1)
            out=[c for c in self.fake.calls if c[0]==0x40]
            self.assertEqual(len(out),1)
            self.assertEqual(out[0][1:5],(0x11,param,0,(value&65535).to_bytes(2,'little')))
            self.assertEqual(self.fake.values[PARAMETERS[other+'_master']],untouched)
            self.assertTrue(self.device.last_write['confirmed'])
    def test_step_uses_fresh_value(self):
        self.device.mixer_masters_snapshot()
        self.fake.values[PARAMETERS['main_master']]=(-21*256)&65535
        self.assertEqual(self.device.step_mixer_master('main',1),-20*256)
    def test_boundaries_no_out_and_fractional_clamp(self):
        for raw,direction in ((0,1),(-60*256,-1)):
            self.fake.values[PARAMETERS['main_master']]=raw&65535;self.fake.calls.clear()
            self.assertEqual(self.device.step_mixer_master('main',direction),raw)
            self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
        self.fake.values[PARAMETERS['main_master']]=(-60*256+128)&65535
        self.assertEqual(self.device.step_mixer_master('main',-1),-60*256)
    def test_unknown_values_and_version_block_writes(self):
        for raw in (-32768,-61*256,256):
            self.fake.values[PARAMETERS['main_master']]=raw&65535
            state=self.device.mixer_masters_snapshot()
            self.assertFalse(state['levels']['main']['writes_available'])
            self.assertEqual(state['levels']['main']['signed'],raw)
            with self.assertRaises(DeviceError):self.device.step_mixer_master('main',1)
        self.fake.values[PARAMETERS['main_master']]=0;self.device.version=19
        self.assertFalse(self.device.mixer_masters_snapshot()['levels']['main']['writes_available'])
        with self.assertRaises(DeviceError):self.device.step_mixer_master('main',-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_invalid_requests_no_usb(self):
        before=len(self.fake.calls)
        for bus,direction in (('aux',1),('main',True),('main',0),('cue',2),(None,1)):
            with self.assertRaises(ValueError):self.device.step_mixer_master(bus,direction)
        self.assertEqual(len(self.fake.calls),before)
    def test_independent_read_failure(self):
        original=self.fake.libusb_control_transfer.func
        def fail(*args):
            return -9 if args[1]==0xc0 and args[3]==56 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail)
        state=self.device.mixer_masters_snapshot()
        self.assertIsNone(state['levels']['main']['db'])
        self.assertEqual(state['levels']['cue']['db'],-6)
        self.assertTrue(state['levels']['cue']['writes_available'])
    def test_removed_device_propagates(self):
        self.fake.read_result=-4
        with self.assertRaises(DeviceDisconnected):self.device.mixer_masters_snapshot()
    def test_readback_failure_never_resends(self):
        self.fake.ignore_writes=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):self.device.step_mixer_master('cue',-1)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertEqual(len(self.device.last_write['readback_attempts']),4)

class AuxMasterTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    def test_each_aux_write_is_scalar_and_isolated(self):
        for i in range(1,5):
            bus='aux'+str(i);before=dict(self.fake.values);self.fake.calls.clear()
            original=self.device.mixer_masters_snapshot()['levels'][bus]['signed']
            self.assertEqual(self.device.step_mixer_master(bus,-1),original-256)
            calls=[c for c in self.fake.calls if c[0]==0x40]
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1:5],(0x11,57+i,0,((original-256)&65535).to_bytes(2,'little')))
            for field,value in before.items():
                if field!=PARAMETERS[bus+'_master']:self.assertEqual(self.fake.values[field],value)
    def test_aux_fresh_reads_and_limits(self):
        for bus in ('aux1','aux2','aux3','aux4'):
            self.fake.values[PARAMETERS[bus+'_master']]=0
            self.device.mixer_masters_snapshot()
            self.fake.values[PARAMETERS[bus+'_master']]=(-18*256)&65535
            self.assertEqual(self.device.step_mixer_master(bus,1),-17*256)
            for raw,direction in ((0,1),(-60*256,-1)):
                self.fake.values[PARAMETERS[bus+'_master']]=raw&65535;self.fake.calls.clear()
                self.assertEqual(self.device.step_mixer_master(bus,direction),raw)
                self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_aux_failure_does_not_hide_other_masters(self):
        original=self.fake.libusb_control_transfer.func
        def fail(*args):return -9 if args[1]==0xc0 and args[3]==59 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail)
        state=self.device.mixer_masters_snapshot()
        self.assertEqual(list(state['errors']),['aux2'])
        for bus in ('main','cue','aux1','aux3','aux4'):self.assertTrue(state['levels'][bus]['writes_available'])
        self.assertIsNone(state['levels']['aux2']['db'])
    def test_aux_unsupported_levels_and_version_no_out(self):
        for bus in ('aux1','aux2','aux3','aux4'):
            for raw in (32768,256,(-61*256)&65535):
                self.fake.values[PARAMETERS[bus+'_master']]=raw
                self.assertFalse(self.device.mixer_masters_snapshot()['levels'][bus]['writes_available'])
                with self.assertRaises(DeviceError):self.device.step_mixer_master(bus,1)
        self.device.version=19
        for bus in ('aux1','aux2','aux3','aux4'):
            with self.assertRaises(DeviceError):self.device.step_mixer_master(bus,-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_aux_readback_mismatch_sends_once(self):
        self.fake.ignore_writes=True
        for bus in ('aux1','aux2','aux3','aux4'):
            self.fake.calls.clear()
            with self.assertRaises(DeviceError):self.device.step_mixer_master(bus,1)
            self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
    def test_aux_demo_separation(self):
        demo=DemoAF16Rig();before=demo.mixer_masters_snapshot()['levels']
        demo.step_mixer_master('aux4',-1)
        after=demo.mixer_masters_snapshot()['levels']
        self.assertEqual(after['aux4']['signed'],before['aux4']['signed']-256)
        for bus in ('main','cue','aux1','aux2','aux3'):self.assertEqual(before[bus],after[bus])

class AuxMuteTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    def test_packed_read_all_bits_and_no_out(self):
        for mask in (0,5,10,65535):
            self.fake.values[1,62]=mask
            state=self.device.mixer_masters_snapshot()
            self.assertEqual(state['aux_mute_mask'],mask)
            self.assertEqual(state['aux_mutes'],{'aux'+str(i+1):(mask>>i)&1 for i in range(4)})
            self.assertEqual(self.fake.calls[-3][1:4],(0x91,62,0))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_each_bit_exact_payload_and_preserves_others(self):
        for index in range(4):
            self.fake.values[1,62]=0xfff0
            self.fake.calls.clear()
            bus='aux'+str(index+1)
            self.assertEqual(self.device.write_aux_mute(bus,True),1)
            self.assertEqual(self.fake.values[1,62],0xfff0|(1<<index))
            out=[c for c in self.fake.calls if c[0]==0x40]
            self.assertEqual(len(out),1)
            self.assertEqual(out[0][1:5],(0x11,62,index,b'\x01\x00'))
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,62,0))
            self.assertEqual(self.device.write_aux_mute(bus,False),0)
            self.assertEqual(self.fake.values[1,62],0xfff0)
    def test_already_requested_state_no_out(self):
        self.fake.values[1,62]=10
        for bus,value in (('aux1',False),('aux2',True),('aux3',False),('aux4',True)):
            self.assertEqual(self.device.write_aux_mute(bus,value),int(value))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_level_and_mute_are_independent(self):
        self.device.write_aux_mute('aux3',True)
        before={name:self.fake.values[PARAMETERS[name+'_master']] for name in ('main','cue','aux1','aux2','aux3','aux4')}
        self.device.step_mixer_master('aux1',-1)
        self.assertEqual(self.fake.values[1,62],4)
        for name in ('main','cue','aux2','aux3','aux4'):self.assertEqual(self.fake.values[PARAMETERS[name+'_master']],before[name])
    def test_invalid_bus_value_and_bit_index_no_out(self):
        for bus,value in (('main',True),('cue',True),('aux0',True),('aux5',True),('aux1',1),('aux1',None)):
            with self.assertRaises(ValueError):self.device.write_aux_mute(bus,value)
        for index in (-1,4,15,True):
            with self.assertRaises(ValueError):self.device._write_and_confirm('aux_mute',1,index)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_unsupported_version_blocks(self):
        self.device.version=19
        self.assertFalse(self.device.mixer_masters_snapshot()['aux_mute_writes_available'])
        with self.assertRaises(DeviceError):self.device.write_aux_mute('aux1',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_failed_mute_read_keeps_levels(self):
        original=self.fake.libusb_control_transfer.func
        def fail(*args):return -9 if args[1]==0xc0 and args[3]==62 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail)
        state=self.device.mixer_masters_snapshot()
        self.assertFalse(state['aux_mute_writes_available'])
        self.assertEqual(state['aux_mutes'],{})
        self.assertTrue(all(v['writes_available'] for v in state['levels'].values()))
        with self.assertRaises(DeviceError):self.device.write_aux_mute('aux2',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_readback_mismatch_no_resend(self):
        self.fake.ignore_writes=True
        with self.assertRaisesRegex(DeviceError,'not confirmed'):self.device.write_aux_mute('aux4',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertEqual(len(self.device.last_write['readback_attempts']),4)
    def test_mute_available_with_out_of_range_gain(self):
        self.fake.values[PARAMETERS['aux2_master']]=32768
        state=self.device.mixer_masters_snapshot()
        self.assertFalse(state['levels']['aux2']['writes_available'])
        self.assertTrue(state['aux_mute_writes_available'])
        self.assertEqual(self.device.write_aux_mute('aux2',True),1)
    def test_demo_preserves_peer_mutes(self):
        d=DemoAF16Rig()
        for bus in ('aux1','aux2','aux3','aux4'):d.write_aux_mute(bus,True)
        d.write_aux_mute('aux3',False)
        self.assertEqual(d.mixer_masters_snapshot()['aux_mute_mask'],11)

class MixerResponsivenessTests(unittest.TestCase):
    def make_window(self):
        from types import SimpleNamespace
        from af16rig_gui import MixerMastersWindow
        class Widget:
            def __init__(self):self.options={};self.changes=[]
            def cget(self,key):return self.options.get(key,'')
            def config(self,**kw):self.changes.append(kw);self.options.update(kw)
        w=MixerMastersWindow.__new__(MixerMastersWindow)
        w.app=SimpleNamespace(connected=True,worker=SimpleNamespace(commands=queue.Queue()))
        w.state=DemoAF16Rig().mixer_masters_snapshot();w.pending=set();w.unavailable=set()
        w.levels={bus:Widget() for bus in w.state['levels']}
        w.buttons={(bus,d):Widget() for bus in w.levels for d in (-1,1)}
        w.mute_buttons={bus:Widget() for bus in ('aux1','aux2','aux3','aux4')}
        w.mute_labels={bus:Widget() for bus in w.mute_buttons};w.pre_buttons={bus:Widget() for bus in w.mute_buttons};w.message=Widget();w.cue_button=Widget();w.refresh()
        return w
    def test_click_locks_only_selected_control_and_keeps_values(self):
        w=self.make_window();before={b:v.cget('text') for b,v in w.levels.items()}
        w.toggle_mute('aux1')
        self.assertEqual(w.mute_buttons['aux1'].cget('state'),'disabled')
        self.assertTrue(all(w.mute_buttons[b].cget('state')=='normal' for b in ('aux2','aux3','aux4')))
        self.assertTrue(all(b.cget('state')=='normal' for b in w.buttons.values()))
        self.assertEqual({b:v.cget('text') for b,v in w.levels.items()},before)
    def test_verified_mute_never_clears_other_readings(self):
        w=self.make_window();w.toggle_mute('aux2');before=dict(w.state['levels'])
        w.handle({'kind':'input_written','channel':'masters','name':'aux2_mute','actual':1})
        self.assertEqual(w.state['levels'],before)
        self.assertEqual(w.state['aux_mutes']['aux2'],1)
        self.assertEqual(w.state['aux_mute_mask'],2)
        self.assertEqual(w.mute_buttons['aux2'].cget('text'),'Unmute')
        self.assertEqual(w.mute_buttons['aux2'].cget('state'),'normal')
        self.assertFalse(w.pending)
    def test_verified_level_never_clears_peer_readings(self):
        w=self.make_window();w.step('main',-1)
        self.assertEqual(w.buttons['main',1].cget('state'),'disabled')
        self.assertEqual(w.buttons['cue',1].cget('state'),'normal')
        w.handle({'kind':'input_written','channel':'masters','name':'main','actual':-13*256})
        self.assertEqual(w.levels['main'].cget('text'),'-13.00 dB')
        self.assertEqual(w.levels['cue'].cget('text'),'-12.00 dB')
        self.assertEqual(w.mute_buttons['aux1'].cget('text'),'Mute')
    def test_multiple_controls_queue_without_losing_pending_state(self):
        w=self.make_window();w.toggle_mute('aux1');w.toggle_mute('aux2');w.step('cue',-1)
        self.assertEqual(w.pending,{('aux1','mute'),('aux2','mute'),('cue','level')})
        self.assertEqual(w.app.worker.commands.qsize(),3)
        w.toggle_mute('aux1');self.assertEqual(w.app.worker.commands.qsize(),3)
        w.handle({'kind':'input_written','channel':'masters','name':'aux1_mute','actual':1})
        self.assertEqual(w.pending,{('aux2','mute'),('cue','level')})
    def test_unchanged_refresh_makes_no_widget_changes(self):
        w=self.make_window()
        widgets=list(w.levels.values())+list(w.buttons.values())+list(w.mute_buttons.values())+list(w.mute_labels.values())
        before=sum(len(x.changes) for x in widgets)
        w.refresh();w.refresh()
        self.assertEqual(sum(len(x.changes) for x in widgets),before)
    def test_failure_preserves_values_and_locks_only_failed_control(self):
        w=self.make_window();w.toggle_mute('aux3')
        w.handle({'kind':'input_error','channel':'masters','name':'aux3','operation':'aux_mute','message':'not confirmed'})
        self.assertEqual(w.levels['main'].cget('text'),'-12.00 dB')
        self.assertEqual(w.mute_buttons['aux3'].cget('text'),'Mute')
        self.assertEqual(w.mute_buttons['aux3'].cget('state'),'disabled')
        self.assertEqual(w.mute_buttons['aux4'].cget('state'),'normal')
        self.assertFalse(w.pending)
        w.handle({'kind':'input_snapshot','state':DemoAF16Rig().mixer_masters_snapshot()})
        self.assertEqual(w.mute_buttons['aux3'].cget('state'),'normal')
    def test_physical_change_is_read_while_other_control_is_pending(self):
        w=self.make_window();w.toggle_mute('aux1')
        d=DemoAF16Rig();d.write_aux_mute('aux4',True)
        w.handle({'kind':'input_snapshot','state':d.mixer_masters_snapshot()})
        self.assertEqual(w.mute_buttons['aux4'].cget('text'),'Unmute')
        self.assertEqual(w.mute_buttons['aux1'].cget('state'),'disabled')
    def test_disconnect_disables_and_clears_pending(self):
        w=self.make_window();w.toggle_mute('aux1');w.app.connected=False
        w.handle({'kind':'input_error','channel':'masters','message':'Device disconnected'})
        self.assertFalse(w.pending)
        self.assertTrue(all(b.cget('state')=='disabled' for b in w.buttons.values()))
        self.assertTrue(all(b.cget('state')=='disabled' for b in w.mute_buttons.values()))

class AuxPreTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    def test_live_packed_states_and_no_writes(self):
        for mask in (0,5,10,65535):
            self.fake.values[1,55]=mask
            state=self.device.mixer_masters_snapshot()
            self.assertEqual(state['aux_pre_mask'],mask)
            self.assertEqual(state['aux_pre'],{'aux'+str(i+1):(mask>>i)&1 for i in range(4)})
            self.assertEqual(self.fake.calls[-2][1:4],(0x91,55,0))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_each_aux_exact_pre_and_post_payload_preserves_peers(self):
        for index in range(4):
            self.fake.values[1,55]=0xfff0;self.fake.calls.clear();before=dict(self.fake.values)
            bus='aux'+str(index+1)
            self.assertEqual(self.device.write_aux_pre(bus,True),1)
            self.assertEqual(self.fake.values[1,55],0xfff0|(1<<index))
            self.assertEqual(self.fake.calls[-2][1:5],(0x11,55,index,b'\x01\x00'))
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,55,0))
            for field,value in before.items():
                if field!=(1,55):self.assertEqual(self.fake.values[field],value)
            self.assertEqual(self.device.write_aux_pre(bus,False),0)
            self.assertEqual(self.fake.values[1,55],0xfff0)
            self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),2)
    def test_no_op_and_invalid_requests_never_write(self):
        self.fake.values[1,55]=10
        for bus,value in (('aux1',False),('aux2',True),('aux3',False),('aux4',True)):self.device.write_aux_pre(bus,value)
        for bus,value in (('main',True),('cue',True),('aux0',True),('aux5',True),('aux1',1)):
            with self.assertRaises(ValueError):self.device.write_aux_pre(bus,value)
        for index in (-1,4,15,True):
            with self.assertRaises(ValueError):self.device._write_and_confirm('aux_pre',1,index)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_pre_read_failure_keeps_mutes_and_levels(self):
        original=self.fake.libusb_control_transfer.func
        def fail(*args):return -9 if args[1]==0xc0 and args[3]==55 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail)
        state=self.device.mixer_masters_snapshot()
        self.assertFalse(state['aux_pre_writes_available'])
        self.assertEqual(state['aux_pre'],{})
        self.assertTrue(state['aux_mute_writes_available'])
        self.assertTrue(all(v['writes_available'] for v in state['levels'].values()))
        with self.assertRaises(DeviceError):self.device.write_aux_pre('aux1',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_version_mismatch_and_removed_device(self):
        self.device.version=19
        self.assertFalse(self.device.mixer_masters_snapshot()['aux_pre_writes_available'])
        with self.assertRaises(DeviceError):self.device.write_aux_pre('aux1',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
        self.device.version=18;self.fake.read_result=-4
        with self.assertRaises(DeviceDisconnected):self.device.write_aux_pre('aux4',True)
    def test_uncertain_write_readback_retries_only(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_aux_pre('aux4',True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertEqual(len(self.device.last_write['readback_attempts']),4)
    def test_demo_pre_preserves_mute(self):
        d=DemoAF16Rig();d.write_aux_mute('aux2',True)
        d.write_aux_pre('aux1',True);d.write_aux_pre('aux4',True)
        state=d.mixer_masters_snapshot()
        self.assertEqual(state['aux_pre_mask'],9)
        self.assertEqual(state['aux_mute_mask'],2)

class AuxPreResponsivenessTests(unittest.TestCase):
    make_window=MixerResponsivenessTests.make_window
    def test_pre_is_independent_and_applies_only_confirmed_value(self):
        w=self.make_window();w.toggle_pre('aux2')
        self.assertEqual(w.pre_buttons['aux2'].cget('state'),'disabled')
        self.assertEqual(w.pre_buttons['aux2'].cget('text'),'Post-fader')
        self.assertEqual(w.pre_buttons['aux1'].cget('state'),'normal')
        self.assertEqual(w.mute_buttons['aux2'].cget('state'),'normal')
        self.assertTrue(all(b.cget('state')=='normal' for b in w.buttons.values()))
        w.handle({'kind':'input_written','channel':'masters','name':'aux2_pre','actual':1})
        self.assertEqual(w.pre_buttons['aux2'].cget('text'),'Pre-fader')
        self.assertEqual(w.state['aux_pre_mask'],2)
        self.assertFalse(w.pending)
        self.assertEqual(w.state['aux_mute_mask'],0)
    def test_error_invalidates_pre_only_and_recovers(self):
        w=self.make_window();w.toggle_pre('aux4')
        w.handle({'kind':'input_error','channel':'masters','name':'aux4','operation':'aux_pre','message':'not confirmed'})
        self.assertFalse(w.pending)
        self.assertEqual(w.pre_buttons['aux4'].cget('state'),'disabled')
        self.assertEqual(w.pre_buttons['aux3'].cget('state'),'normal')
        self.assertEqual(w.mute_buttons['aux4'].cget('state'),'normal')
        w.handle({'kind':'input_snapshot','state':DemoAF16Rig().mixer_masters_snapshot()})
        self.assertEqual(w.pre_buttons['aux4'].cget('state'),'normal')
    def test_pre_and_mute_queue_independently_on_same_bus(self):
        w=self.make_window();w.toggle_pre('aux1');w.toggle_mute('aux1');w.step('aux1',-1)
        self.assertEqual(w.pending,{('aux1','pre'),('aux1','mute'),('aux1','level')})
        self.assertEqual(w.app.worker.commands.qsize(),3)

class AuxLinkTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    def test_snapshot_uses_odd_pair_flags_only(self):
        for mask,expected in ((0,(0,0)),(5,(0,0)),(2,(1,0)),(8,(0,1)),(10,(1,1)),(65535,(1,1))):
            self.fake.values[1,54]=mask
            state=self.device.aux_links_snapshot()
            self.assertEqual((state['link12'],state['link34']),expected)
            self.assertEqual(state['mask'],mask)
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,54,0))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_single_flag_per_pair_preserves_other_flags_and_fields(self):
        for pair in (1,3):
            self.fake.values[1,54]=0xfff5;before=dict(self.fake.values);self.fake.calls.clear()
            self.assertEqual(self.device.write_aux_link(pair,True),1)
            out=[c for c in self.fake.calls if c[0]==0x40]
            self.assertEqual(len(out),1)
            self.assertEqual(out[0][1:5],(0x11,54,pair,b'\x01\x00'))
            self.assertEqual(self.fake.values[1,54],0xfff5|(1<<pair))
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,54,0))
            for field,value in before.items():
                if field!=(1,54):self.assertEqual(self.fake.values[field],value)
            self.assertEqual(self.device.write_aux_link(pair,False),0)
            self.assertEqual(self.fake.values[1,54],0xfff5)
            self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),2)
    def test_invalid_pair_flags_and_arguments_never_write(self):
        for pair,value in ((0,True),(2,True),(4,True),(True,True),(1,1),(3,None)):
            with self.assertRaises(ValueError):self.device.write_aux_link(pair,value)
        for index in (0,2,4,True):
            with self.assertRaises(ValueError):self.device._write_and_confirm('aux_link',1,index)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_noop_uses_actual_device_bit(self):
        self.fake.values[1,54]=2
        self.assertEqual(self.device.write_aux_link(1,True),1)
        self.assertEqual(self.device.write_aux_link(3,False),0)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_version_guard_and_removed_device(self):
        self.device.version=19
        self.assertFalse(self.device.aux_links_snapshot()['writes_available'])
        with self.assertRaises(DeviceError):self.device.write_aux_link(1,True)
        self.device.version=18;self.fake.read_result=-4
        with self.assertRaises(DeviceDisconnected):self.device.aux_links_snapshot()
        with self.assertRaises(DeviceDisconnected):self.device.write_aux_link(3,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_failed_reads_disable_links_without_write(self):
        self.fake.read_result=-9
        state=self.device.aux_links_snapshot()
        self.assertIsNone(state['mask']);self.assertIsNone(state['link12'])
        self.assertFalse(state['writes_available']);self.assertIn('link',state['errors'])
        with self.assertRaises(DeviceError):self.device.write_aux_link(1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_uncertain_write_is_not_resent_or_rolled_back(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_aux_link(3,True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertEqual(len(self.device.last_write['readback_attempts']),4)
        self.assertEqual(self.device.aux_links_snapshot()['link34'],0)
    def test_demo_pair_flag_separation(self):
        d=DemoAF16Rig();d.write_aux_link(1,True)
        self.assertEqual(d.aux_links_snapshot()['mask'],2)
        d.write_aux_link(3,True);d.write_aux_link(1,False)
        self.assertEqual(d.aux_links_snapshot()['mask'],8)

class CueEnableTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    def test_current_scalar_state_read_without_writing(self):
        for value in (0,1):
            self.fake.values[1,63]=value
            state=self.device.mixer_masters_snapshot()
            self.assertEqual(state['cue_enabled'],value)
            self.assertTrue(state['cue_writes_available'])
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,63,0))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_on_off_exact_payload_preserves_all_other_fields(self):
        before=dict(self.fake.values)
        for value in (True,False):
            self.fake.calls.clear()
            self.assertEqual(self.device.write_cue_enabled(value),int(value))
            out=[c for c in self.fake.calls if c[0]==0x40]
            self.assertEqual(len(out),1)
            self.assertEqual(out[0][1:5],(0x11,63,0,int(value).to_bytes(2,'little')))
            for field,original in before.items():
                if field!=(1,63):self.assertEqual(self.fake.values[field],original)
            self.assertTrue(self.device.last_write['confirmed'])
    def test_noop_and_invalid_values_no_out(self):
        self.assertEqual(self.device.write_cue_enabled(False),0)
        for value in (0,1,None,'on'):
            with self.assertRaises(ValueError):self.device.write_cue_enabled(value)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_unknown_state_and_version_guard(self):
        for value in (2,65535):
            self.fake.values[1,63]=value
            state=self.device.mixer_masters_snapshot()
            self.assertEqual(state['cue_enabled'],value)
            self.assertFalse(state['cue_writes_available'])
            with self.assertRaises(DeviceError):self.device.write_cue_enabled(True)
        self.fake.values[1,63]=0;self.device.version=19
        self.assertFalse(self.device.mixer_masters_snapshot()['cue_writes_available'])
        with self.assertRaises(DeviceError):self.device.write_cue_enabled(True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_failed_cue_read_keeps_levels_and_aux_controls(self):
        original=self.fake.libusb_control_transfer.func
        def fail(*args):return -9 if args[1]==0xc0 and args[3]==63 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail)
        state=self.device.mixer_masters_snapshot()
        self.assertIsNone(state['cue_enabled']);self.assertFalse(state['cue_writes_available'])
        self.assertTrue(state['aux_mute_writes_available']);self.assertTrue(state['aux_pre_writes_available'])
        self.assertTrue(all(s['writes_available'] for s in state['levels'].values()))
    def test_uncertain_write_not_resent(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_cue_enabled(True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertEqual(len(self.device.last_write['readback_attempts']),4)
    def test_removed_device_and_demo(self):
        self.fake.read_result=-4
        with self.assertRaises(DeviceDisconnected):self.device.write_cue_enabled(True)
        d=DemoAF16Rig();self.assertEqual(d.write_cue_enabled(True),1)
        self.assertEqual(d.mixer_masters_snapshot()['cue_enabled'],1)

class CueEnableResponsivenessTests(unittest.TestCase):
    make_window=MixerResponsivenessTests.make_window
    def test_only_cue_enable_locks_and_updates_on_confirmation(self):
        w=self.make_window();w.toggle_cue()
        self.assertEqual(w.cue_button.cget('state'),'disabled')
        self.assertEqual(w.cue_button.cget('text'),'Cue · Off')
        self.assertTrue(all(b.cget('state')=='normal' for b in w.buttons.values()))
        self.assertTrue(all(b.cget('state')=='normal' for b in w.mute_buttons.values()))
        w.handle({'kind':'input_written','channel':'masters','name':'cue_enable','actual':1})
        self.assertFalse(w.pending);self.assertEqual(w.cue_button.cget('text'),'Cue · On')
        self.assertEqual(w.cue_button.cget('state'),'normal')
        self.assertEqual(w.levels['cue'].cget('text'),'-12.00 dB')
    def test_failure_preserves_known_display_and_peer_controls(self):
        w=self.make_window();w.toggle_cue()
        w.handle({'kind':'input_error','channel':'masters','name':'cue','operation':'cue_enable','message':'not confirmed'})
        self.assertFalse(w.pending)
        self.assertEqual(w.cue_button.cget('text'),'Cue · Off')
        self.assertEqual(w.cue_button.cget('state'),'disabled')
        self.assertEqual(w.buttons['cue',1].cget('state'),'normal')
        w.handle({'kind':'input_snapshot','state':DemoAF16Rig().mixer_masters_snapshot()})
        self.assertEqual(w.cue_button.cget('state'),'normal')

class MixChannelTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    def test_snapshot_exact_fields_and_level_indices(self):
        for bus,ids in (('main',(34,35,38,39,36,37,44,40,45,41,46,42,47,43)),('cue',(48,49,52,53,50,51))):
            self.fake.calls.clear()
            state=self.device.mix_channel_snapshot(bus,16)
            self.assertTrue(state['writes_available']);self.assertEqual(state['mono_selected'],1)
            self.assertEqual(state['stereo_selected'],0);self.assertEqual(state['mute'],0)
            self.assertEqual([(c[1],c[2],c[3]) for c in self.fake.calls],[(0x91,p,15 if p in (36,37,40,41,42,43,50,51) else 0) for p in ids])
            self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_each_bus_channel1_and16_exact_write_isolated(self):
        for bus,param in (('main',38),('cue',52)):
            for source in (1,16):
                self.fake.values[1,param]=0;before=dict(self.fake.values);self.fake.calls.clear()
                self.assertEqual(self.device.write_mix_channel_mute(bus,source,True),1)
                self.assertEqual(self.fake.values[1,param],1<<(source-1))
                out=[c for c in self.fake.calls if c[0]==0x40];self.assertEqual(len(out),1)
                self.assertEqual(out[0][1:5],(0x11,param,source-1,b'\x01\x00'))
                self.assertEqual(self.fake.calls[-1][1:4],(0x91,param,0))
                for field,value in before.items():
                    if field!=(1,param):self.assertEqual(self.fake.values[field],value)
    def test_absent_or_stereo_sources_never_written(self):
        for show,stereo in ((0,0),(65535,1),(0,1)):
            self.fake.values[1,34]=show;self.fake.values[1,35]=stereo
            self.assertFalse(self.device.mix_channel_snapshot('main',1)['writes_available'])
            with self.assertRaises(DeviceError):self.device.write_mix_channel_mute('main',1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_stereo_guard_is_rechecked_after_old_snapshot(self):
        self.assertTrue(self.device.mix_channel_snapshot('main',2)['writes_available'])
        self.fake.values[1,35]=1
        with self.assertRaises(DeviceError):self.device.write_mix_channel_mute('main',2,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_last_stereo_pair_mapping_blocks15_and16_only(self):
        self.fake.values[1,35]=1<<7
        self.assertFalse(self.device.mix_channel_snapshot('main',15)['writes_available'])
        self.assertFalse(self.device.mix_channel_snapshot('main',16)['writes_available'])
        self.assertTrue(self.device.mix_channel_snapshot('main',14)['writes_available'])
    def test_noop_and_invalid_requests_no_writes(self):
        self.device.write_mix_channel_mute('main',1,False)
        for bus,source,value in (('aux1',1,True),('main',0,True),('cue',17,True),('main',True,True),('main',1,1)):
            with self.assertRaises(ValueError):self.device.write_mix_channel_mute(bus,source,value)
        # Direct inclusion writes are blocked; use the checked selection API.
        for field in ('main_channel_show','main_channel_stereo','cue_channel_show'):
            with self.assertRaises(ValueError):self.device._write_and_confirm(field,1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_read_error_is_independent_and_selection_failure_blocks(self):
        original=self.fake.libusb_control_transfer.func
        def fail_level(*args):return -9 if args[1]==0xc0 and args[3]==36 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail_level)
        state=self.device.mix_channel_snapshot('main',1)
        self.assertIsNone(state['level_db']);self.assertTrue(state['writes_available'])
        def fail_selection(*args):return -9 if args[1]==0xc0 and args[3]==34 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail_selection)
        self.assertFalse(self.device.mix_channel_snapshot('main',1)['writes_available'])
        with self.assertRaises(DeviceError):self.device.write_mix_channel_mute('main',1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_version_and_removal_guards(self):
        self.device.version=19
        self.assertFalse(self.device.mix_channel_snapshot('main',1)['writes_available'])
        with self.assertRaises(DeviceError):self.device.write_mix_channel_mute('main',1,True)
        self.device.version=18;self.fake.read_result=-4
        with self.assertRaises(DeviceDisconnected):self.device.mix_channel_snapshot('main',1)
    def test_uncertain_write_is_never_resent(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.write_mix_channel_mute('cue',16,True)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
    def test_worker_poll_routes_tuple_to_channel_snapshot(self):
        from af16rig_gui import Worker
        q=queue.Queue();w=Worker(q);w.device=self.device;w.input_channel=('mix_channel','cue',16)
        w.poll_input();event=q.get_nowait()
        self.assertEqual(event['state']['channel'],'mix_channel')
        self.assertEqual(event['state']['bus'],'cue');self.assertEqual(event['state']['source'],16)
    def test_demo_mixer_separation(self):
        d=DemoAF16Rig();d.write_mix_channel_mute('main',16,True)
        self.assertEqual(d.mix_channel_snapshot('main',16)['mute'],1)
        self.assertEqual(d.mix_channel_snapshot('main',1)['mute'],0)
        self.assertEqual(d.mix_channel_snapshot('cue',16)['mute'],0)

class MixChannelLevelTests(unittest.TestCase):
    def setUp(self):
        Tests.setUp(self)
        self.levels={(param,index):(-12*256)&65535 for param in (36,40,41,42,43,50) for index in range(16)}
        original=self.fake.libusb_control_transfer.func
        def transfer(handle,bm,req,param,index,data,length,timeout):
            if param not in (36,40,41,42,43,50):return original(handle,bm,req,param,index,data,length,timeout)
            self.fake.calls.append((bm,req,param,index,bytes(data),length,timeout))
            if bm==0xc0:
                raw=self.levels[param,index];data[0],data[1]=raw&255,raw>>8
                return self.fake.read_result
            if not self.fake.ignore_writes:self.levels[param,index]=int.from_bytes(data,'little')
            return self.fake.write_result
        self.fake.libusb_control_transfer=Fn(transfer)
    tearDown=Tests.tearDown
    def test_exact_array_write_and_main_cue_channel_isolation(self):
        for bus,param in (('main',36),('cue',50)):
            for source in (1,16):
                before=dict(self.levels);self.fake.calls.clear()
                self.assertEqual(self.device.step_mix_channel_level(bus,source,-1),-13*256)
                out=[c for c in self.fake.calls if c[0]==0x40]
                self.assertEqual(len(out),1)
                self.assertEqual(out[0][1:5],(0x11,param,source-1,((-13*256)&65535).to_bytes(2,'little')))
                self.assertEqual(self.fake.calls[-1][1:4],(0x91,param,source-1))
                for field,value in before.items():
                    if field!=(param,source-1):self.assertEqual(self.levels[field],value)
    def test_fresh_hardware_value_not_cached_snapshot(self):
        self.device.mix_channel_snapshot('main',1)
        self.levels[36,0]=(-7*256)&65535
        self.assertEqual(self.device.step_mix_channel_level('main',1,1),-6*256)
    def test_bounds_no_out_and_fractional_clamping(self):
        for raw,direction in ((6*256,1),(-60*256,-1)):
            self.levels[36,0]=raw&65535;self.fake.calls.clear()
            self.assertEqual(self.device.step_mix_channel_level('main',1,direction),raw)
            self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
        self.levels[36,0]=(-60*256+128)&65535
        self.assertEqual(self.device.step_mix_channel_level('main',1,-1),-60*256)
    def test_absent_stereo_and_changed_selection_no_out(self):
        self.assertTrue(self.device.mix_channel_snapshot('main',1)['level_writes_available'])
        for show,stereo in ((0,0),(65535,1)):
            self.fake.values[1,34]=show;self.fake.values[1,35]=stereo
            self.assertFalse(self.device.mix_channel_snapshot('main',1)['level_writes_available'])
            with self.assertRaises(DeviceError):self.device.step_mix_channel_level('main',1,1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_out_of_range_and_invalid_arguments_no_out(self):
        for raw in (32768,7*256,(-61*256)&65535):
            self.levels[36,0]=raw
            self.assertFalse(self.device.mix_channel_snapshot('main',1)['level_writes_available'])
            with self.assertRaises(DeviceError):self.device.step_mix_channel_level('main',1,1)
        for bus,source,direction in (('main',1,True),('main',1,0),('main',1,2),('aux1',1,1),('cue',17,1)):
            with self.assertRaises(ValueError):self.device.step_mix_channel_level(bus,source,direction)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_version_and_removal_guard(self):
        self.device.version=19
        self.assertFalse(self.device.mix_channel_snapshot('main',1)['level_writes_available'])
        with self.assertRaises(DeviceError):self.device.step_mix_channel_level('main',1,1)
        self.device.version=18;self.fake.read_result=-4
        with self.assertRaises(DeviceDisconnected):self.device.step_mix_channel_level('main',1,1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_uncertain_write_read_retries_only(self):
        self.fake.ignore_writes=True
        with self.assertRaises(DeviceError):self.device.step_mix_channel_level('cue',16,1)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),1)
        self.assertEqual(len(self.device.last_write['readback_attempts']),4)
    def test_mute_and_other_parameters_preserved(self):
        before=dict(self.fake.values)
        self.device.step_mix_channel_level('main',2,1)
        self.assertEqual(self.fake.values,before)
    def test_read_failure_disables_level_keeps_mute(self):
        original=self.fake.libusb_control_transfer.func
        def fail(*args):return -9 if args[1]==0xc0 and args[3]==36 else original(*args)
        self.fake.libusb_control_transfer=Fn(fail)
        state=self.device.mix_channel_snapshot('main',1)
        self.assertFalse(state['level_writes_available']);self.assertTrue(state['writes_available'])
        with self.assertRaises(DeviceError):self.device.step_mix_channel_level('main',1,-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))
    def test_demo_per_source_and_bus_levels(self):
        d=DemoAF16Rig();d.step_mix_channel_level('main',16,-1)
        self.assertEqual(d.mix_channel_snapshot('main',16)['level_db'],-13)
        self.assertEqual(d.mix_channel_snapshot('main',1)['level_db'],-12)
        self.assertEqual(d.mix_channel_snapshot('cue',16)['level_db'],-12)

class MixChannelLevelUITests(unittest.TestCase):
    def make_window(self):
        from types import SimpleNamespace
        from af16rig_gui import MixChannelWindow
        class Var:
            def __init__(self,value):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value
        class Widget:
            def __init__(self):self.options={}
            def cget(self,key):return self.options.get(key,'')
            def config(self,**kw):self.options.update(kw)
        w=MixChannelWindow.__new__(MixChannelWindow)
        w.app=SimpleNamespace(connected=True,worker=SimpleNamespace(commands=queue.Queue()))
        w.bus=Var('main');w.source=Var(1);w.channel=Var('mix_channel')
        w.pending=False;w.stale=False;w.state=DemoAF16Rig().mix_channel_snapshot('main',1)
        for name in ('selection','level','mute_button','solo_button','bus_menu','source_spin','message'):setattr(w,name,Widget())
        w.app.info={"state_version":18};w.pan_edit={a:Widget() for a in ("Left","L step","Centre","R step","Right")};w.pan_summary=Widget();w.pan_reading=Widget();w.pan_buttons={label:Widget() for label in ('Left','Centre','Right')}
        w.send_level_labels={n:Widget() for n in range(1,5)};w.send_steps={(n,d):Widget() for n in range(1,5) for d in (-1,1)}
        w.send_buttons={n:Widget() for n in range(1,5)};w.level_buttons={-1:Widget(),1:Widget()};w.refresh();return w
    def test_step_keeps_display_until_verified_readback(self):
        w=self.make_window();w.step(-1)
        self.assertTrue(w.pending)
        self.assertEqual(w.level.cget('text'),'Level: -12.00 dB')
        self.assertTrue(all(b.cget('state')=='disabled' for b in w.level_buttons.values()))
        self.assertEqual(w.app.worker.commands.get_nowait(),('mix_channel_level',('main',1,-1)))
        w.handle({'kind':'input_written','channel':'mix_channel','bus':'main','source':1,'name':'level','actual':-13*256})
        self.assertFalse(w.pending);self.assertEqual(w.level.cget('text'),'Level: -13.00 dB')
        self.assertEqual(w.state['mute'],0)
        self.assertEqual(w.level_buttons[1].cget('state'),'normal')
    def test_stereo_and_missing_level_disable_only_relevant_controls(self):
        w=self.make_window();w.state.update(stereo_selected=1,writes_available=False,level_writes_available=False);w.refresh()
        self.assertTrue(all(b.cget('state')=='disabled' for b in w.level_buttons.values()))
        w.state=DemoAF16Rig().mix_channel_snapshot('main',1)
        w.state.update(level_db=None,level_signed=None,level_writes_available=False);w.refresh()
        self.assertEqual(w.mute_button.cget('state'),'normal')
        self.assertTrue(all(b.cget('state')=='disabled' for b in w.level_buttons.values()))
    def test_error_keeps_level_then_fresh_state_recovers(self):
        w=self.make_window();w.step(1)
        w.handle({'kind':'input_error','channel':'mix_channel','bus':'main','source':1,'message':'not confirmed'})
        self.assertFalse(w.pending);self.assertTrue(w.stale)
        self.assertEqual(w.level.cget('text'),'Level: -12.00 dB')
        self.assertEqual(w.level_buttons[1].cget('state'),'disabled')
        w.handle({'kind':'input_snapshot','state':DemoAF16Rig().mix_channel_snapshot('main',1)})
        self.assertFalse(w.stale);self.assertEqual(w.level_buttons[1].cget('state'),'normal')
    def test_late_other_source_event_does_not_change_display(self):
        w=self.make_window()
        w.handle({'kind':'input_written','channel':'mix_channel','bus':'cue','source':16,'name':'level','actual':-30*256})
        self.assertEqual(w.level.cget('text'),'Level: -12.00 dB')
    def test_boundary_buttons_disable_outward_steps(self):
        w=self.make_window()
        for signed,direction in ((6*256,1),(-60*256,-1)):
            w.state.update(level_signed=signed,level_db=signed/256);w.refresh()
            self.assertEqual(w.level_buttons[direction].cget('state'),'disabled')
            self.assertEqual(w.level_buttons[-direction].cget('state'),'normal')

class ChannelSoloTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_solo_preserves_peer_bits_mute_and_other_mix(self):
        for bus, parameter in [('main', 39), ('cue', 53)]:
            self.fake.values[1, parameter] = 2
            previous = self.fake.values.copy()
            self.device.write_mix_channel_solo(bus, 16, True)
            self.assertEqual(self.fake.values[1, parameter], 0x8002)
            self.assertEqual(self.fake.calls[-2][1:4], (0x11, parameter, 15))
            self.assertEqual(self.fake.calls[-1][1:4], (0x91, parameter, 0))
            self.assertEqual(self.device.mix_channel_snapshot(bus,16)['solo'], 1)
            self.device.write_mix_channel_solo(bus, 16, False)
            self.assertEqual(self.fake.values, previous)

    def test_solo_rechecks_mono_selection_before_write(self):
        self.assertTrue(self.device.mix_channel_snapshot('main',1)['solo_writes_available'])
        self.fake.values[1,35] = 1
        with self.assertRaises(DeviceError):
            self.device.write_mix_channel_solo('main',1,True)
        self.assertFalse(any(call[0] == 0x40 for call in self.fake.calls))

    def test_solo_readback_failure_sends_once(self):
        self.fake.ignore_writes = True
        with self.assertRaises(DeviceError):
            self.device.write_mix_channel_solo('cue',1,True)
        self.assertEqual(sum(call[0] == 0x40 for call in self.fake.calls), 1)

    def test_gui_solo_waits_for_readback(self):
        window = MixChannelLevelUITests().make_window()
        window.toggle('solo')
        self.assertEqual(window.app.worker.commands.get_nowait(), ('mix_channel_solo', ('main',1,True)))
        self.assertEqual(window.solo_button.cget('text'), 'Solo')
        window.handle(dict(kind='input_written',channel='mix_channel',bus='main',source=1,name='solo',actual=1))
        self.assertEqual(window.solo_button.cget('text'), 'Clear solo')
        self.assertEqual(window.state['mute'], 0)

class StereoMemberReadTests(unittest.TestCase):
    setUp = MixChannelLevelTests.setUp
    tearDown = Tests.tearDown

    def test_either_selector_returns_same_pair_and_distinct_flags(self):
        for bus, stereo, level, mute, solo in [('main',35,36,38,39),('cue',49,50,52,53)]:
            self.fake.values[1,stereo] = 128
            self.fake.values[1,mute] = 1 << 14
            self.fake.values[1,solo] = 1 << 15
            self.levels[level,14] = (-9 * 256) & 65535
            self.levels[level,15] = (-4 * 256) & 65535
            for source in (15,16):
                state = self.device.mix_channel_snapshot(bus,source)
                self.assertEqual(state['stereo_members'], [
                    dict(source=15,level_db=-9,mute=1,solo=0),
                    dict(source=16,level_db=-4,mute=0,solo=1)])
                self.assertFalse(state['level_writes_available'])
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_partner_read_failure_preserves_selected_readings(self):
        self.fake.values[1,35] = 2
        original = self.fake.libusb_control_transfer.func
        def fail(*args):
            if args[1:5] == (0xc0,0x91,36,3): return -9
            return original(*args)
        self.fake.libusb_control_transfer = Fn(fail)
        state = self.device.mix_channel_snapshot('main',3)
        self.assertIn('partner_level',state['errors'])
        self.assertEqual(state['stereo_members'][0]['level_db'],-12)
        self.assertIsNone(state['stereo_members'][1]['level_db'])

class StereoSwitchTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_either_member_targets_only_pair_in_selected_mix(self):
        for bus, show, stereo, mute, solo in [('main',34,35,38,39), ('cue',48,49,52,53)]:
            self.fake.values[1,show] = 3
            self.fake.values[1,stereo] = 2
            for control, field in [('mute',mute), ('solo',solo)]:
                self.fake.values[1,field] = 5
                self.fake.calls.clear()
                self.device.write_stereo_channel_switch(bus,4,control,True)
                self.assertEqual(self.fake.values[1,field],13)
                self.assertEqual([c[3] for c in self.fake.calls if c[0]==0x40],[3])
                self.device.write_stereo_channel_switch(bus,3,control,False)
                self.assertEqual(self.fake.values[1,field],1)

    def test_partial_failure_records_first_member_and_stops(self):
        self.fake.values[1,34] = 3
        self.fake.values[1,35] = 2
        original = self.fake.libusb_control_transfer.func
        def transfer(*args):
            if args[1:5] == (0x40,0x11,38,3):
                self.fake.ignore_writes = True
            return original(*args)
        self.fake.libusb_control_transfer = Fn(transfer)
        with self.assertRaises(DeviceError):
            self.device.write_stereo_channel_switch('main',3,'mute',True)
        self.assertEqual(self.fake.values[1,38],4)
        self.assertEqual([c[3] for c in self.fake.calls if c[0]==0x40],[2,3])
        self.assertFalse(self.device.last_write['confirmed'])

    def test_no_writes_after_selection_changes(self):
        self.fake.values[1,34] = 3
        self.fake.values[1,35] = 2
        self.assertTrue(self.device.mix_channel_snapshot('main',3)['pair_editable'])
        self.fake.values[1,35] = 0
        with self.assertRaises(DeviceError):
            self.device.write_stereo_channel_switch('main',3,'solo',True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

class StereoLevelTests(unittest.TestCase):
    setUp = MixChannelLevelTests.setUp
    tearDown = Tests.tearDown

    def test_relative_levels_from_either_member_and_mix(self):
        for bus, show, stereo, field in [('main',34,35,36),('cue',48,49,50)]:
            self.fake.values[1,show] = 3
            self.fake.values[1,stereo] = 2
            self.levels[field,2] = (-7*256)&65535
            self.levels[field,3] = (-14*256)&65535
            before = dict(self.levels)
            self.assertEqual(self.device.step_stereo_channel_level(bus,4,-1),[-8*256,-15*256])
            self.device.step_stereo_channel_level(bus,3,1)
            self.assertEqual(self.levels,before)

    def test_reported_main34_at_plus_four_steps_in_both_directions(self):
        self.fake.values[1,34] = 3
        self.fake.values[1,35] = 254
        self.levels[36,2] = self.levels[36,3] = 1024
        window = MixChannelLevelUITests().make_window()
        for source, direction in [(3,1),(4,-1)]:
            window.source.set(source)
            window.state = self.device.mix_channel_snapshot('main',source)
            window.refresh()
            self.assertTrue(all(b.cget('state')=='normal' for b in window.level_buttons.values()))
            target = self.device.step_stereo_channel_level('main',source,direction)
            self.assertEqual(target, [1280,1280] if direction==1 else [1024,1024])

    def test_shared_boundary_respects_offset(self):
        self.fake.values[1,34] = 0
        self.fake.values[1,35] = 1
        self.levels[36,0] = 6*256-128
        self.levels[36,1] = 6*256-384
        self.assertEqual(self.device.step_stereo_channel_level('main',1,1),[6*256,5*256])
        count = len([c for c in self.fake.calls if c[0]==0x40])
        self.device.step_stereo_channel_level('main',2,1)
        self.assertEqual(len([c for c in self.fake.calls if c[0]==0x40]),count)

    def test_mono_selection_rejected_without_out(self):
        with self.assertRaises(DeviceError):
            self.device.step_stereo_channel_level('cue',1,-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_second_member_failure_recorded_without_resend(self):
        self.fake.values[1,34] = 0
        self.fake.values[1,35] = 1
        original = self.fake.libusb_control_transfer.func
        def transfer(*args):
            if args[1:5] == (0x40,0x11,36,1):
                self.fake.ignore_writes = True
            return original(*args)
        self.fake.libusb_control_transfer = Fn(transfer)
        with self.assertRaises(DeviceError):
            self.device.step_stereo_channel_level('main',1,-1)
        self.assertEqual([c[3] for c in self.fake.calls if c[0]==0x40],[0,1])
        self.assertFalse(self.device.last_write['confirmed'])

class StereoLevelPanelTests(unittest.TestCase):
    def test_right_member_commands_pair_and_displays_verified_values(self):
        window = MixChannelLevelUITests().make_window()
        window.source.set(4)
        window.state.update(source=4, mono_selected=0, stereo_selected=1,
                            pair_editable=True, writes_available=False, level_writes_available=False,
                            stereo_members=[dict(source=3,level_db=-7,mute=0,solo=0),
                                            dict(source=4,level_db=-14,mute=0,solo=0)])
        window.refresh()
        window.step(-1)
        self.assertEqual(window.app.worker.commands.get_nowait(), ('stereo_level',('main',4,-1)))
        window.handle(dict(kind='input_written', channel='mix_channel', bus='main', source=4,
                           name='stereo_level', actual=[-2048,-3840]))
        self.assertEqual(window.level.cget('text'),'Level: -15.00 dB')
        self.assertEqual([m['level_db'] for m in window.state['stereo_members']],[-8,-15])
        self.assertFalse(window.pending)

class ChannelSendTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_four_send_addresses_and_source_isolation(self):
        for aux in range(1,5):
            self.fake.values[1,43+aux] = 2
            before = dict(self.fake.values)
            self.device.write_send_mute('main',16,aux,True)
            self.assertEqual(self.fake.calls[-2][1:4], (0x11,43+aux,15))
            self.assertEqual(self.fake.values[1,43+aux],32770)
            self.assertEqual(self.device.mix_channel_snapshot('main',16)[f'send{aux}'],1)
            self.device.write_send_mute('main',16,aux,False)
            self.assertEqual(self.fake.values,before)

    def test_cue_and_stereo_rejection(self):
        with self.assertRaises(ValueError):
            self.device.write_send_mute('cue',1,1,True)
        self.fake.values[1,35] = 1
        with self.assertRaises(DeviceError):
            self.device.write_send_mute('main',1,1,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_panel_confirms_selected_send(self):
        window = MixChannelLevelUITests().make_window()
        window.toggle_send(3)
        self.assertEqual(window.app.worker.commands.get_nowait(),('send_mute',('main',1,3,True)))
        window.handle(dict(kind='input_written',channel='mix_channel',bus='main',source=1,name='send3',actual=1))
        self.assertEqual(window.send_buttons[3].cget('text'),'Unmute Aux 3')
        self.assertEqual(window.state['mute'],0)

class ChannelSendLevelTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_exact_send_element_and_other_fields(self):
        for aux in range(1,5):
            before = dict(self.fake.values)
            actual = self.device.step_send_level('main',16,aux,-1)
            self.assertEqual(actual,-13*256)
            self.assertEqual(self.fake.calls[-2][1:4],(0x11,39+aux,15))
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,39+aux,15))
            self.device.step_send_level('main',16,aux,1)
            self.assertEqual(before,self.fake.values)

    def test_stereo_or_cue_send_step_blocked(self):
        self.fake.values[1,35] = 1
        with self.assertRaises(DeviceError):
            self.device.step_send_level('main',1,1,-1)
        with self.assertRaises(ValueError):
            self.device.step_send_level('cue',1,1,-1)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_panel_updates_only_confirmed_send(self):
        w = MixChannelLevelUITests().make_window()
        w.step_send(2,-1)
        self.assertEqual(w.app.worker.commands.get_nowait(),('send_level',('main',1,2,-1)))
        w.handle(dict(kind='input_written',channel='mix_channel',bus='main',source=1,name='aux2_send_level',actual=-13*256))
        self.assertEqual(w.send_level_labels[2].cget('text'),'-13.00 dB')
        self.assertEqual(w.state['send2'],0)
        self.assertEqual(w.state['level_db'],-12)

class StereoAuxSendTests(unittest.TestCase):
    setUp = MixChannelLevelTests.setUp
    tearDown = Tests.tearDown

    def test_all_sends_preserve_offset_and_other_inputs(self):
        self.fake.values[1,34] = 3
        self.fake.values[1,35] = 2
        for aux in range(1,5):
            field = 39 + aux
            self.levels[field,2] = (-14*256)&65535
            self.levels[field,3] = (-8*256)&65535
            before = dict(self.levels)
            self.assertEqual(self.device.step_stereo_send_level('main',4,aux,-1),[-15*256,-9*256])
            self.device.step_stereo_send_level('main',3,aux,1)
            self.assertEqual(self.levels,before)
            self.fake.values[1,43+aux] = 5
            self.device.write_stereo_send_mute('main',4,aux,True)
            self.assertEqual(self.fake.values[1,43+aux],13)
            self.device.write_stereo_send_mute('main',3,aux,False)
            self.assertEqual(self.fake.values[1,43+aux],1)

    def test_wrong_mix_or_changed_selection_skips_writes(self):
        with self.assertRaises(ValueError):
            self.device.step_stereo_send_level('cue',1,1,1)
        with self.assertRaises(DeviceError):
            self.device.write_stereo_send_mute('main',1,2,True)
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_right_side_gui_drives_selected_stereo_send(self):
        self.fake.values[1,34] = 3
        self.fake.values[1,35] = 2
        window = MixChannelLevelUITests().make_window()
        window.source.set(4)
        window.handle(dict(kind='input_snapshot',state=self.device.mix_channel_snapshot('main',4)))
        window.step_send(2,-1)
        self.assertEqual(window.app.worker.commands.get_nowait(),('pair_send_level',('main',4,2,-1)))
        window.handle(dict(kind='input_written',channel='mix_channel',bus='main',source=4,name='pair_send_level',aux=2,actual=[-3328,-3328]))
        self.assertIn('R -13.00 dB',window.send_level_labels[2].cget('text'))

class PanReadTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_pan_snapshot_only_reads_each_bus(self):
        for bus, field in [('main',37),('cue',51)]:
            self.fake.values[1,field] = 65535
            self.assertEqual(self.device.mix_channel_snapshot(bus,16)['raw']['pan'],65535)
            self.assertTrue(any(c[1:4]==(0x91,field,15) for c in self.fake.calls))
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_record_uses_fresh_sample_in_panel(self):
        w=MixChannelLevelUITests().make_window()
        w.record_pan('Centre')
        self.assertEqual(w.app.worker.commands.get_nowait(),('record_pan',('main',1,'Centre')))
        w.handle(dict(kind='pan_recorded',channel='mix_channel',bus='main',source=1,label='Centre',raw=128))
        self.assertEqual(w.pan_reading.cget('text'),'Pan reading 128')
        self.assertFalse(w.pending)

class PanScanTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_native_scan_reads_each_main_cue_index_without_writes(self):
        self.fake.calls.clear()
        scan = self.device.scan_pan_positions()
        self.assertEqual(len(scan['values']), 32)
        self.assertEqual([(c[0],c[1],c[2],c[3]) for c in self.fake.calls],
                         [(0xc0,0x91,param,index) for param in (37,51) for index in range(16)])

    def test_changed_slot_and_incomplete_reads(self):
        from af16rig_gui import compare_pan_scans
        result = compare_pan_scans({'main 1':127,'cue 2':0,'main 4':10},
                                   {'main 1':127,'cue 2':254,'cue 3':0})
        self.assertEqual(result,{'compared':2,'changes':{'cue 2':[0,254]}})

class CalibratedPanTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_positions_and_fresh_relative_steps(self):
        for action,target in [('Right',254),('L step',253),('Left',0),('Centre',127),('R step',128)]:
            self.assertEqual(self.device.adjust_main_pan('main',16,action),target)
            self.assertEqual(self.fake.calls[-2][1:5],(0x11,37,15,target.to_bytes(2,'little')))
            self.assertEqual(self.fake.calls[-1][1:4],(0x91,37,15))

    def test_stereo_and_invalid_readings_block_writes(self):
        self.fake.values[1,35] = 1
        with self.assertRaises(DeviceError):self.device.adjust_main_pan('main',1,'Left')
        self.fake.values[1,35] = 0
        self.fake.values[1,37] = 65535
        with self.assertRaises(DeviceError):self.device.adjust_main_pan('main',1,'Centre')
        with self.assertRaises(ValueError):self.device.adjust_main_pan('cue',1,'Right')
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_panel_waits_for_confirmed_position(self):
        w=MixChannelLevelUITests().make_window()
        w.adjust_pan('Right')
        self.assertEqual(w.app.worker.commands.get_nowait(),('adjust_pan',('main',1,'Right')))
        self.assertEqual(w.state['raw']['pan'],127)
        w.handle(dict(kind='input_written',channel='mix_channel',bus='main',source=1,name='pan',actual=254))
        self.assertEqual(w.pan_reading.cget('text'),'Pan reading 254')

class CueChannelPanTests(unittest.TestCase):
    setUp = Tests.setUp
    tearDown = Tests.tearDown

    def test_cue_uses_its_own_selection_and_array(self):
        self.fake.values[1,34] = 0
        self.fake.values[1,37] = 12
        self.fake.values[1,51] = 127
        self.assertEqual(self.device.adjust_channel_pan('cue',16,'L step'),126)
        self.assertEqual(self.fake.calls[-2][1:5],(0x11,51,15,bytes([126,0])))
        self.assertEqual(self.fake.calls[-1][1:4],(0x91,51,15))
        self.assertEqual(self.fake.values[1,37],12)

    def test_stereo_or_absent_cue_is_read_only(self):
        for mono, stereo in [(0,0),(65535,1)]:
            self.fake.values[1,48] = mono
            self.fake.values[1,49] = stereo
            with self.assertRaises(DeviceError):
                self.device.adjust_channel_pan('cue',1,'Centre')
        self.assertFalse(any(c[0]==0x40 for c in self.fake.calls))

    def test_cue_button_dispatch_and_confirmed_display(self):
        w = MixChannelLevelUITests().make_window()
        w.bus.set('cue')
        w.state = DemoAF16Rig().mix_channel_snapshot('cue',1)
        w.refresh()
        w.adjust_pan('R step')
        self.assertEqual(w.app.worker.commands.get_nowait(),('adjust_pan',('cue',1,'R step')))
        self.assertEqual(w.state['raw']['pan'],127)
        w.handle(dict(kind='input_written',channel='mix_channel',bus='cue',source=1,name='pan',actual=128))
        self.assertEqual(w.state['raw']['pan'],128)

if __name__ == '__main__': unittest.main()
