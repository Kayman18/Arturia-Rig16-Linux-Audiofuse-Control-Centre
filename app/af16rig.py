"""Experimental native AF16Rig monitor and rear-input backend. Python stdlib + system libusb."""
import ctypes as C
import ctypes.util
import struct
import threading
import time

MIXER_BUSES = ('main','cue','aux1','aux2','aux3','aux4')

VID, PID = 0x1C75, 0xAF21
CHANNEL_MAX_DB = 6
CHANNEL_MAX_RAW = CHANNEL_MAX_DB * 256

SEND_MUTE_FIELDS = {f'main_channel_send{n}': (1, 43+n) for n in range(1,5)}
SEND_LEVEL_FIELDS = {f'aux{n}_send_level': (1, 39+n) for n in range(1,5)}
ROUTING_FIELDS = {'output_source': (64, 62), 'cue_destination': (65, 2),
                  'front_output_mode': (73, 1), 'cue_selection_left': (93, 4),
                  'cue_selection_right': (94, 4)}
PARAMETERS = {
    **{name: (1, spec[0]) for name, spec in ROUTING_FIELDS.items()},
    'main_channel_pan': (1,37), 'cue_channel_pan': (1,51),
    **SEND_LEVEL_FIELDS,
    **SEND_MUTE_FIELDS,
    'main_channel_solo': (1,39), 'cue_channel_solo': (1,53),
    'main_channel_show': (1,34), 'main_channel_stereo': (1,35), 'main_channel_level': (1,36), 'main_channel_mute': (1,38),
    'cue_channel_show': (1,48), 'cue_channel_stereo': (1,49), 'cue_channel_level': (1,50), 'cue_channel_mute': (1,52),
    'cue_enabled': (1, 63),
    'aux_link': (1, 54), 'aux_pre': (1, 55), 'aux_mute': (1, 62),
    'aux1_master': (1, 58), 'aux2_master': (1, 59), 'aux3_master': (1, 60), 'aux4_master': (1, 61),
    'main_master': (1, 56), 'cue_master': (1, 57),
    'phones_preset': (1, 30), 'phones_knob': (0, 8), 'detect_status': (0, 1), 'front_mic_status': (0, 6), 'force_rear': (1, 72),
    'button': (0, 3), 'state_version': (3, 2), 'firmware_raw': (0, 0),
    'hardware_raw': (3, 3), 'audio_firmware_raw': (3, 4),
    'front_line_instrument': (1, 69), 'front_line_pad': (1, 67), 'front_mic_pad': (1, 66),
    'front_mini_gain': (1, 21), 'front_line_gain': (1, 71), 'front_mic_gain': (1, 70),
    'front_line_hpf': (1, 96), 'front_mic_hpf': (1, 95),
    'front_line_phase': (1, 18), 'front_mic_phase': (1, 17),
    'front_line_link': (1, 22), 'front_mic_link': (1, 23),
    'ab_enabled': (1, 76), 'ab_selected': (1, 31), 'ab_destination': (1, 77), 'ab_trim': (1, 75),
    'dim_depth': (1, 28), 'output_link': (1, 32), 'output_gain': (1, 33), 'rear_pad': (1, 68), 'rear_link': (1, 24), 'rear_gain': (1, 20), 'rear_phase': (1, 19), 'rear_hpf': (1, 97),
    'speaker_level': (3, 0), 'mute': (0, 7), 'mono': (1, 26), 'dim': (1, 27),
}
INPUT_CONTROLS = {'phase': 'rear_phase', 'hpf': 'rear_hpf', 'pad': 'rear_pad'}
INVERTED_INPUT_CONTROLS = frozenset(('pad',))  # Rear pad: native zero lights the device PAD indicator.
MIXER_SELECTION_FIELDS = {f'{bus}_channel_{kind}' for bus in ('main','cue') for kind in ('show','stereo')}
PACKED_INPUT_FIELDS = MIXER_SELECTION_FIELDS | frozenset(INPUT_CONTROLS.values()) | set(SEND_MUTE_FIELDS) | {'main_channel_solo', 'cue_channel_solo', 'main_channel_mute', 'cue_channel_mute', 'aux_link', 'aux_pre', 'aux_mute', 'rear_link', 'force_rear', 'front_line_link', 'front_mic_link', 'front_line_phase', 'front_mic_phase', 'front_line_hpf', 'front_mic_hpf', 'front_line_pad', 'front_mic_pad', 'front_line_instrument', 'output_link'}

GAIN_FIELDS = {'main_channel_pan','cue_channel_pan'} | set(SEND_LEVEL_FIELDS) | frozenset(('main_channel_level','cue_channel_level','aux1_master', 'aux2_master', 'aux3_master', 'aux4_master', 'main_master', 'cue_master', 'rear_gain', 'front_line_gain', 'front_mic_gain', 'output_gain', 'ab_trim', 'front_mini_gain'))

def validate_index(name, index):
    if name in MIXER_SELECTION_FIELDS:
        limit=7 if name.endswith('_stereo') else 15
        if type(index) is not int or not 0 <= index <= limit:raise ValueError('Only analog mixer selections are supported')
        return
    if name in ROUTING_FIELDS:
        if type(index) is not int or not 0 <= index < ROUTING_FIELDS[name][1]:
            raise ValueError('Invalid routing read index')
        return
    if type(index) is not int or not 0 <= index <= (3 if name in ('aux_link','aux_mute','aux_pre') else 7 if name in ('output_gain','output_link') else 1 if name in ('front_line_gain','front_mic_gain','front_mini_gain') else 15 if name in SEND_LEVEL_FIELDS or name in PACKED_INPUT_FIELDS or name in ('rear_gain','main_channel_level','cue_channel_level','main_channel_pan','cue_channel_pan') else 0):
        raise ValueError('Invalid parameter element index')

BOOLEAN_CONTROLS = frozenset(('mute', 'mono', 'dim'))
VALIDATED_STATE_VERSION = 18
VOLUME_UNITS_PER_DB = 256
VOLUME_MIN_RAW = -60 * VOLUME_UNITS_PER_DB
VOLUME_MAX_RAW = 0

def front_source_status(context):
    raw = context.get('raw', {})
    if any(name not in raw for name in ('force_rear', 'detect_status')):
        return {'sources': None, 'available': {'line': False, 'mic': False},
                'reason': {'line': 'Source status unavailable; refresh.', 'mic': 'Source status unavailable; refresh.'}}
    forced, detected = raw['force_rear'], raw['detect_status']
    sources = []
    for index, line_bit, mic_bit in ((0,0,1),(1,5,6)):
        if forced & (1 << index): source = 'rear'
        elif detected & (1 << line_bit): source = 'line'
        elif detected & (1 << mic_bit): source = 'mic'
        else: source = 'rear'
        sources.append(source)
    available = {kind: sources == [kind, kind] for kind in ('line', 'mic')}
    reason = {}
    for kind in ('line', 'mic'):
        if available[kind]: reason[kind] = 'Both front inputs use this mode.'
        elif forced & 3: reason[kind] = 'Rear override active. Enable front detection below.'
        elif sources[0] != sources[1]: reason[kind] = 'Inputs 1–2 use different sources; connect matching front input types.'
        elif sources == ['rear', 'rear']: reason[kind] = 'No compatible front pair detected; connect both front inputs.'
        else: reason[kind] = 'The active front pair uses the other input mode.'
    return {'sources': sources, 'available': available, 'reason': reason}

def mini_source_status(context):
    raw=context.get('raw',{})
    if any(name not in raw for name in ('force_rear','detect_status')):return None
    return ['rear' if raw['force_rear'] & (1<<index) or not raw['detect_status'] & 0x10 else 'line' for index in (2,3)]

def input_link_bank(channel, context):
    """Input 1/2 use different link parameters for front mic, front line, rear."""
    if channel not in (1,2):return 'rear'
    sources=front_source_status(context)['sources']
    if not sources:raise DeviceError('Cannot select link bank: input 1/2 source detection unavailable')
    if sources[0]!=sources[1]:
        raise DeviceError('Cannot link inputs 1/2 in mixed source modes: '+str(sources)+'. Use matching front input types or select both rear inputs.')
    return sources[0]

class DeviceError(Exception):
    pass

class DeviceDisconnected(DeviceError):
    pass

class AF16Rig:
    def __init__(self, library=None):
        try:
            self.lib = library if library is not None else C.CDLL(
                ctypes.util.find_library('usb-1.0') or 'libusb-1.0.so.0')
        except OSError as e:
            raise DeviceError('libusb is missing. On CachyOS/Arch: sudo pacman -S libusb') from e
        signatures = {
            'libusb_init': ([C.POINTER(C.c_void_p)], C.c_int),
            'libusb_exit': ([C.c_void_p], None),
            'libusb_open_device_with_vid_pid': ([C.c_void_p, C.c_uint16, C.c_uint16], C.c_void_p),
            'libusb_close': ([C.c_void_p], None),
            'libusb_control_transfer': ([C.c_void_p, C.c_uint8, C.c_uint8, C.c_uint16,
                C.c_uint16, C.POINTER(C.c_ubyte), C.c_uint16, C.c_uint], C.c_int),
            'libusb_error_name': ([C.c_int], C.c_char_p),
        }
        for name, (args, result) in signatures.items():
            f = getattr(self.lib, name)
            f.argtypes, f.restype = args, result
        self.context = C.c_void_p()
        self.handle = None
        self.initialized = False
        self.version = None
        self.lock = threading.RLock()
        self.last_write = None

    def error(self, rc):
        s = self.lib.libusb_error_name(rc)
        return s.decode(errors='replace') if s else str(rc)

    def open(self):
        with self.lock:
            if self.handle:
                return
            rc = self.lib.libusb_init(C.byref(self.context))
            if rc < 0:
                raise DeviceError('USB initialization failed: ' + self.error(rc))
            self.initialized = True
            self.handle = self.lib.libusb_open_device_with_vid_pid(self.context, VID, PID)
            if not self.handle:
                self.close()
                raise DeviceError('Cannot open AF16Rig MIDI (1c75:af21). Check the connection '
                                  'and USB permissions; see README.md.')
            try:
                self.version = self.read('state_version')
            except Exception:
                self.close()
                raise

    def close(self):
        with self.lock:
            if self.handle:
                self.lib.libusb_close(self.handle)
                self.handle = None
            if self.initialized:
                self.lib.libusb_exit(self.context)
                self.initialized = False
            self.version = None

    def read(self, name, index=0):
        with self.lock:
            validate_index(name, index)
            if name in PACKED_INPUT_FIELDS and index != 0:
                raise ValueError('Packed input reads use word index zero')
            if name not in PARAMETERS:
                raise ValueError('Unknown parameter')
            if not self.handle:
                raise DeviceError('Device is disconnected')
            group, parameter = PARAMETERS[name]
            data = (C.c_ubyte * 2)()
            rc = self.lib.libusb_control_transfer(
                self.handle, 0xC0, 0x90 + group, parameter, index, data, 2, 1000)
            if rc == -4:
                raise DeviceDisconnected(f'{name}: {self.error(rc)}')
            if rc < 0:
                raise DeviceError(f'{name}: {self.error(rc)}')
            if rc != 2:
                raise DeviceError(f'{name}: expected 2 bytes, got {rc}')
            return int.from_bytes(data, 'little')

    def write_bool(self, name, value):
        with self.lock:
            if name not in BOOLEAN_CONTROLS:
                raise ValueError('Only mute, mono and dim writes are implemented')
            if type(value) is not bool:
                raise ValueError('Boolean value required')
            if not self.handle:
                raise DeviceError('Device is disconnected')
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError(f'Controls require state version {VALIDATED_STATE_VERSION}; '
                                  f'device returned {self.version}')
            self.last_write = None
            current = self.read(name)
            if current not in (0, 1):
                raise DeviceError(f'{name}: unexpected boolean value {current}; write skipped')
            if current == int(value):
                return current
            return self._write_and_confirm(name, int(value))

    def step_volume(self, direction):
        """One relative 1 dB step in signed 8.8 fixed-point units."""
        with self.lock:
            if type(direction) is not int or direction not in (-1, 1):
                raise ValueError('Direction must be -1 or +1')
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for volume writes')
            self.last_write = None
            raw = self.read('speaker_level')
            current = struct.unpack('<h', struct.pack('<H', raw))[0]
            if not VOLUME_MIN_RAW <= current <= VOLUME_MAX_RAW:
                raise DeviceError('Speaker level is outside the TEST13 volume-control range')
            target = max(VOLUME_MIN_RAW, min(VOLUME_MAX_RAW, current + direction * VOLUME_UNITS_PER_DB))
            if target == current:
                return current
            self._write_and_confirm('speaker_level', target & 0xffff)
            return target

    def write_output_route(self, destination, source_code, *, expected_source):
        from routing_labels import SOURCE_LABELS, DESTINATION_LABELS
        if (type(destination) is not int or destination not in DESTINATION_LABELS or
                type(source_code) is not int or source_code not in SOURCE_LABELS or
                type(expected_source) is not int or expected_source not in SOURCE_LABELS):
            raise ValueError('Only mapped destinations and source codes can be edited')
        with self.lock:
            self.last_write = None
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for output routing')
            current = self.read('output_source', destination)
            if current != expected_source:
                raise DeviceError('Routing changed externally. Read routing again before applying.')
            if current == source_code: return current
            return self._write_and_confirm('output_source', source_code, destination)

    def _write_and_confirm(self, name, word, index=0, *, selection_checked=False, phones_checked=False):
        if name in MIXER_SELECTION_FIELDS and not selection_checked:
            raise ValueError("Use the checked mixer inclusion API")
        if name=='phones_knob' and not phones_checked:
            raise ValueError('Use the checked Phones level API')
        validate_index(name, index)
        if name=='aux_link' and index not in (1,3):raise ValueError('Aux stereo link uses only pair flag indices1 and3')
        if name not in BOOLEAN_CONTROLS and name not in PACKED_INPUT_FIELDS and name not in ('phones_knob','speaker_level','dim_depth','ab_enabled','ab_selected','ab_destination','cue_enabled','output_source') and name not in GAIN_FIELDS:
            raise ValueError('Unsupported write parameter')
        if name == 'output_source':
            from routing_labels import SOURCE_LABELS, DESTINATION_LABELS
            if index not in DESTINATION_LABELS or type(word) is not int or word not in SOURCE_LABELS:
                raise ValueError('Unmapped routing destination or source')
        group, parameter = PARAMETERS[name]
        data = (C.c_ubyte * 2).from_buffer_copy(struct.pack('<H', word))
        # Send exactly once. Some failures can occur after the hardware
        # has already accepted the command; never repeat an uncertain OUT.
        rc = self.lib.libusb_control_transfer(
            self.handle, 0x40, 0x10 + group, parameter, index, data, 2, 1000)
        self.last_write = {'control': name, 'requested': word,
                           'out_result': rc, 'element_index': index, 'read_word_index': index // 16 if name in PACKED_INPUT_FIELDS else index, 'readback_attempts': []}
        if rc == -4:
            raise DeviceDisconnected(f'{name} write: {self.error(rc)}')
        # Allow state propagation before checking. Retry reads only.
        for delay in (0.05, 0.10, 0.20, 0.40):
            time.sleep(delay)
            try:
                actual = (self.read_input_bit(name, index) if name in PACKED_INPUT_FIELDS
                          else self.read(name, index) if name in GAIN_FIELDS or name == 'output_source' else self.read(name))
            except DeviceDisconnected:
                raise
            except DeviceError as e:
                self.last_write['readback_attempts'].append({'error': str(e)})
                continue
            self.last_write['readback_attempts'].append({'actual': actual})
            if actual == word:
                self.last_write['confirmed'] = True
                return actual
        self.last_write['confirmed'] = False
        detail = self.error(rc) if rc < 0 else f'OUT returned {rc} bytes'
        raise DeviceError(f'{name}: change not confirmed ({detail}); refreshing device state')

    def read_input_bit(self, parameter, bit_index):
        if parameter not in PACKED_INPUT_FIELDS:
            raise ValueError('Unsupported packed input field')
        validate_index(parameter, bit_index)
        # Reads address packed words; writes address individual channel bits.
        packed = self.read(parameter, bit_index // 16)
        return (packed >> (bit_index % 16)) & 1

    def link_context(self):
        """Read only: firmware link acceptance depends on source/detection state."""
        result = {'raw': {}, 'errors': {}}
        for name in ('force_rear', 'detect_status', 'front_mic_status'):
            try:
                result['raw'][name] = self.read(name)
            except DeviceDisconnected:
                raise
            except DeviceError as e:
                result['errors'][name] = str(e)
        return result

    @staticmethod
    def validate_mix_channel(bus,source):
        if bus not in ('main','cue') or type(source) is not int or not 1<=source<=16:
            raise ValueError('Main/Cue analog source1–16 required')

    def adjust_main_pan(self, bus, source, action):
        if bus != 'main':
            raise ValueError('Main mix required')
        return self.adjust_channel_pan(bus, source, action)

    def adjust_channel_pan(self, bus, source, action, *, expected_current=None, target_raw=None):
        self.validate_mix_channel(bus, source)
        if action not in ('Left','Centre','Right','L step','R step'):
            raise ValueError('Invalid channel pan command')
        with self.lock:
            self.last_write = None
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for pan')
            index = source - 1
            mono = self.read(bus+'_channel_show')
            stereo = self.read(bus+'_channel_stereo')
            if not mono & (1 << index) or stereo & (1 << (index // 2)):
                raise DeviceError('Pan requires an included mono source')
            current = self.read(bus+'_channel_pan', index)
            if not 0 <= current <= 254:
                raise DeviceError('Pan outside calibrated range')
            if expected_current is not None and current != expected_current:
                raise DeviceError(f'Pan changed externally (expected {expected_current}, read {current})')
            targets = {'Left':0, 'Centre':127, 'Right':254,
                       'L step':max(0,current-1), 'R step':min(254,current+1)}
            target = targets[action] if target_raw is None else target_raw
            if type(target) is not int or not 0 <= target <= 254: raise ValueError('Invalid pan target')
            if target != current:
                self._write_and_confirm(bus+'_channel_pan',target,index)
            return target

    def scan_pan_positions(self):
        values, errors = {}, {}
        with self.lock:
            for bus in ('main', 'cue'):
                for index in range(16):
                    key = f'{bus} {index + 1}'
                    try:
                        values[key] = self.read(bus + '_channel_pan', index)
                    except DeviceDisconnected:
                        raise
                    except DeviceError as error:
                        errors[key] = str(error)
        return {'values': values, 'errors': errors}

    def mix_channel_snapshot(self,bus,source):
        self.validate_mix_channel(bus,source)
        with self.lock:
            state={'channel':'mix_channel','bus':bus,'source':source,'raw':{},'errors':{},'mute':None,
                   'level_db':None,'mono_selected':None,'stereo_selected':None,'writes_available':False}
            index=source-1
            for field in ('show','stereo','mute','solo','level','pan'):
                try:state['raw'][field]=self.read(bus+'_channel_'+field,index if field in ('level','pan') else 0)
                except DeviceDisconnected:raise
                except DeviceError as e:state['errors'][field]=str(e)
            raw=state['raw']
            if 'show' in raw:state['mono_selected']=(raw['show']>>index)&1
            if 'stereo' in raw:state['stereo_selected']=(raw['stereo']>>(index//2))&1
            if 'mute' in raw:state['mute']=(raw['mute']>>index)&1
            state['solo'] = (raw['solo'] >> index) & 1 if 'solo' in raw else None
            state['solo_writes_available'] = (
                self.version == VALIDATED_STATE_VERSION and state['mono_selected'] == 1
                and state['stereo_selected'] == 0 and state['solo'] is not None
            )
            if 'level' in raw:
                signed=struct.unpack('<h',struct.pack('<H',raw['level']))[0]
                state['level_signed']=signed;state['level_db']=signed/256
            state['writes_available']=(self.version==VALIDATED_STATE_VERSION and state['mono_selected']==1
                                       and state['stereo_selected']==0 and state['mute'] in (0,1))
            signed=state.get('level_signed')
            state['level_writes_available']=(self.version==VALIDATED_STATE_VERSION and state['mono_selected']==1
                and state['stereo_selected']==0 and signed is not None and -60*256<=signed<=CHANNEL_MAX_RAW)
            if signed is not None and not -60*256<=signed<=CHANNEL_MAX_RAW:
                state['errors']['level_range']='Level outside this build’s −60 to +6 dB adjustment range'
            if self.version!=VALIDATED_STATE_VERSION:state['errors']['version']='Unsupported state version'
            if state['stereo_selected'] == 1:
                left = index - index % 2
                members = []
                for member in (left, left + 1):
                    level_word = raw.get('level')
                    if member != index:
                        try:
                            level_word = self.read(bus + '_channel_level', member)
                        except DeviceDisconnected:
                            raise
                        except DeviceError as error:
                            level_word = None
                            state['errors']['partner_level'] = str(error)
                    level_db = None
                    if level_word is not None:
                        level_db = int.from_bytes(level_word.to_bytes(2, 'little'), 'little', signed=True) / 256
                    members.append({
                        'source': member + 1, 'level_db': level_db,
                        'mute': (raw['mute'] >> member) & 1 if 'mute' in raw else None,
                        'solo': (raw['solo'] >> member) & 1 if 'solo' in raw else None,
                    })
                state['stereo_members'] = members
                state['pair_editable'] = (
                    self.version == VALIDATED_STATE_VERSION and 'show' in raw
                    and raw['show'] & (3 << left) == 0
                )
            if bus == 'main' and state['stereo_selected'] == 1:
                state['stereo_sends'] = {}
                for aux in range(1, 5):
                    send = {'levels': [], 'mutes': []}
                    state['stereo_sends'][str(aux)] = send
                    try:
                        mask = self.read(f'main_channel_send{aux}')
                        send['mutes'] = [(mask >> member) & 1 for member in (left, left + 1)]
                    except DeviceDisconnected:
                        raise
                    except DeviceError as error:
                        state['errors'][f'aux{aux}_mute'] = str(error)
                    for member in (left, left + 1):
                        try:
                            word = self.read(f'aux{aux}_send_level', member)
                            send['levels'].append(word - 65536 if word >= 32768 else word)
                        except DeviceDisconnected:
                            raise
                        except DeviceError as error:
                            send['levels'].append(None)
                            state['errors'][f'aux{aux}_level_{member+1}'] = str(error)
            if bus == 'main' and state['mono_selected'] == 1 and state['stereo_selected'] == 0:
                state['send_writes_available'] = self.version == VALIDATED_STATE_VERSION
                for aux in range(1, 5):
                    name = f'send{aux}'
                    try:
                        mask = self.read('main_channel_' + name)
                        raw[name] = mask
                        state[name] = (mask >> index) & 1
                    except DeviceDisconnected:
                        raise
                    except DeviceError as error:
                        state['errors'][name] = str(error)
                    level_name = f'aux{aux}_send_level'
                    try:
                        word = self.read(level_name, index)
                        raw[level_name] = word
                        state[level_name] = word - 65536 if word >= 32768 else word
                    except DeviceDisconnected:
                        raise
                    except DeviceError as error:
                        state['errors'][level_name] = str(error)
            return state

    def write_mixer_inclusion(self, bus, source, stereo, value, *, expected_mono, expected_stereo):
        """Change one known analog inclusion flag; never convert a pair implicitly."""
        self.validate_mix_channel(bus,source)
        if type(stereo) is not bool or type(value) is not bool:
            raise ValueError('Inclusion flags must be boolean')
        if any(type(v) is not int or not 0 <= v <= 65535 for v in (expected_mono,expected_stereo)):
            raise ValueError('Invalid expected mixer selection')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported mixer state version')
            mono=self.read(bus+'_channel_show');pairs=self.read(bus+'_channel_stereo')
            if (mono,pairs)!=(expected_mono,expected_stereo):
                raise DeviceError('Mixer source selection changed externally. Refresh before applying.')
            index=source-1;pair=index//2;pair_mask=3 << (pair*2)
            if stereo and mono & pair_mask:
                raise DeviceError('Remove both mono inputs before editing this stereo pair')
            if not stereo and pairs & (1<<pair):
                raise DeviceError('Remove the stereo pair before editing a mono input')
            field=bus+('_channel_stereo' if stereo else '_channel_show')
            bit=pair if stereo else index
            before=pairs if stereo else mono
            if ((before>>bit)&1)==int(value):return int(value)
            actual=self._write_and_confirm(field,int(value),bit,selection_checked=True)
            expected=(before | (1<<bit)) if value else (before & ~(1<<bit))
            after=self.read(field)
            other=self.read(bus+('_channel_show' if stereo else '_channel_stereo'))
            if after!=expected or other!=(mono if stereo else pairs):
                raise DeviceError('Mixer selection readback changed additional flags. Refresh and inspect sources.')
            return actual

    def set_console_value(self, bus, source, control, target, stereo=False):
        """Absolute drag target, retaining selection, range and readback guards."""
        if type(target) is not int or type(stereo) is not bool:
            raise ValueError('Invalid console target')
        if source == 0 and control == 'master':
            return self.step_mixer_master(bus, 1, target_raw=target)
        if control == 'pan' and not stereo:
            return self.adjust_channel_pan(bus, source, 'Centre', target_raw=target)
        if control == 'level':
            field = bus + '_channel_level'
        elif control in ('send1','send2','send3','send4') and bus == 'main':
            field = 'aux' + control[-1] + '_send_level'
        else:
            raise ValueError('Invalid console control')
        if stereo:
            return self._step_stereo_level(bus, source, 1, field, target_raw=target)
        return self._step_mono_level(bus, source, 1, field, target_raw=target)

    def step_mix_channel_level(self, bus, source, direction, *, expected_raw=None, require_muted=False):
        return self._step_mono_level(bus, source, direction, f'{bus}_channel_level',
                                     expected_raw=expected_raw, require_muted=require_muted)

    def step_send_level(self, bus, source, aux, direction, *, expected_raw=None, require_muted=False):
        if bus != 'main' or type(aux) is not int or aux not in range(1,5):
            raise ValueError('Select an Aux send in the Main mix')
        return self._step_mono_level(bus, source, direction, f'aux{aux}_send_level',
                                     expected_raw=expected_raw, require_muted=require_muted)

    def _step_mono_level(self, bus, source, direction, field, *, expected_raw=None, require_muted=False, target_raw=None):
        self.validate_mix_channel(bus,source)
        if type(direction) is not int or direction not in (-1,1):raise ValueError('Level step must be−1 or+1')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for channel level')
            index=source-1
            show=self.read(bus+'_channel_show');stereo=self.read(bus+'_channel_stereo')
            if not (show>>index)&1 or (stereo>>(index//2))&1:
                raise DeviceError('Source must be selected as mono; stereo/absent strips are read-only')
            mute_field = bus + '_channel_mute'
            if field in SEND_LEVEL_FIELDS:
                mute_field = f'main_channel_send{field[3]}'
            if require_muted and not self.read(mute_field) & (1 << index):
                raise DeviceError('Selected strip or send is no longer muted')
            raw=self.read(field,index)
            if expected_raw is not None and raw != expected_raw:
                raise DeviceError(f'Level changed externally (expected {expected_raw}, read {raw})')
            current=struct.unpack('<h',struct.pack('<H',raw))[0]
            if not -60*256<=current<=CHANNEL_MAX_RAW:raise DeviceError('Channel level outside this build’s −60 to +6 dB adjustment range')
            target=max(-60*256,min(CHANNEL_MAX_RAW,current+direction*256)) if target_raw is None else target_raw
            if type(target) is not int or not -60*256 <= target <= CHANNEL_MAX_RAW: raise ValueError("Invalid level target")
            if target!=current:self._write_and_confirm(field,target&65535,index)
            return target

    def step_stereo_channel_level(self, bus, source, direction):
        return self._step_stereo_level(bus, source, direction, f'{bus}_channel_level')

    def step_stereo_send_level(self, bus, source, aux, direction):
        if bus != 'main' or type(aux) is not int or aux not in range(1,5):
            raise ValueError('Select a Main mix Aux send')
        return self._step_stereo_level(bus, source, direction, f'aux{aux}_send_level')

    def _step_stereo_level(self, bus, source, direction, field, *, target_raw=None):
        self.validate_mix_channel(bus, source)
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError('Stereo level step must be -1 or +1')
        left = (source - 1) & ~1
        indices = (left, left + 1)
        diagnostic = dict(control=field, pair=[left + 1, left + 2], direction=direction,
                          transactions=[], confirmed=False)

        def check_pair():
            stereo = self.read(bus + '_channel_stereo')
            mono = self.read(bus + '_channel_show')
            if not stereo & (1 << (left // 2)) or mono & (3 << left):
                raise DeviceError('Stereo selection changed. Refresh the channels.')

        def read_level(index):
            word = self.read(field, index)
            return word - 65536 if word >= 32768 else word

        with self.lock:
            try:
                if self.version != VALIDATED_STATE_VERSION:
                    raise DeviceError('Unsupported state version for stereo levels')
                check_pair()
                start = [read_level(index) for index in indices]
                if any(value < -60*256 or value > CHANNEL_MAX_RAW for value in start):
                    raise DeviceError('Stereo level outside the adjustment range')
                delta = min(256, CHANNEL_MAX_RAW - max(start)) if direction > 0 else -min(256, min(start) + 60*256)
                if target_raw is not None:
                    if type(target_raw) is not int or not -60*256 <= target_raw <= CHANNEL_MAX_RAW:
                        raise ValueError('Invalid stereo level target')
                    delta = max(-60*256-min(start), min(CHANNEL_MAX_RAW-max(start), target_raw-start[(source-1)%2]))
                targets = [value + delta for value in start]
                diagnostic.update(start_signed=start, target_signed=targets)
                for index, previous, target in zip(indices, start, targets):
                    check_pair()
                    current = read_level(index)
                    if current == target:
                        continue
                    if current != previous:
                        raise DeviceError('A fader moved during the step. Check both levels.')
                    self.last_write = None
                    try:
                        self._write_and_confirm(field, target & 65535, index)
                    finally:
                        if self.last_write is not None:
                            diagnostic['transactions'].append(self.last_write)
                actual = [read_level(index) for index in indices]
                diagnostic['actual_signed'] = actual
                if actual != targets:
                    raise DeviceError('Stereo level readback disagreed. Check both levels.')
                diagnostic['confirmed'] = True
                return actual
            except DeviceError as error:
                diagnostic['error'] = str(error)
                raise
            finally:
                self.last_write = diagnostic

    def write_stereo_channel_switch(self, bus, source, control, value):
        self.validate_mix_channel(bus, source)
        if control not in ('mute', 'solo') or type(value) is not bool:
            raise ValueError('Invalid stereo channel switch')
        return self._write_stereo_switch(bus, source, f'{bus}_channel_{control}', value)

    def write_stereo_send_mute(self, bus, source, aux, value):
        self.validate_mix_channel(bus,source)
        if bus != 'main' or type(aux) is not int or aux not in range(1,5) or type(value) is not bool:
            raise ValueError('Invalid stereo Aux send mute')
        return self._write_stereo_switch(bus, source, f'main_channel_send{aux}', value)

    def _write_stereo_switch(self, bus, source, field, value):
        left = (source - 1) & ~1
        pair_mask = 3 << left
        diagnostic = {'control': field, 'pair': [left + 1, left + 2],
                      'requested': int(value), 'transactions': [], 'confirmed': False}
        with self.lock:
            try:
                if self.version != VALIDATED_STATE_VERSION:
                    raise DeviceError('Unsupported state version for stereo editing')
                for member in (left, left + 1):
                    stereo = self.read(bus + '_channel_stereo')
                    mono = self.read(bus + '_channel_show')
                    if not stereo & (1 << (left // 2)) or mono & pair_mask:
                        raise DeviceError('Pair selection changed. Refresh the channel.')
                    if self.read_input_bit(field, member) == int(value):
                        continue
                    self.last_write = None
                    try:
                        self._write_and_confirm(field, int(value), member)
                    finally:
                        if self.last_write is not None:
                            diagnostic['transactions'].append(self.last_write)
                mask = self.read(field)
                diagnostic['actual_mask'] = mask
                if mask & pair_mask != (pair_mask if value else 0):
                    raise DeviceError('Pair readback disagreed. Check both sides.')
                diagnostic['confirmed'] = True
                return int(value)
            except DeviceError as error:
                diagnostic['error'] = str(error)
                raise
            finally:
                self.last_write = diagnostic

    def write_send_mute(self, bus, source, aux, value):
        if bus != 'main' or type(aux) is not int or aux not in range(1, 5):
            raise ValueError('Select a Main mix source and Aux 1–4')
        return self._write_mix_channel_switch(bus, source, value, f'send{aux}')

    def write_mix_channel_mute(self, bus, source, value):
        return self._write_mix_channel_switch(bus, source, value, 'mute')

    def write_mix_channel_solo(self, bus, source, value):
        return self._write_mix_channel_switch(bus, source, value, 'solo')

    def _write_mix_channel_switch(self, bus, source, value, control):
        self.validate_mix_channel(bus,source)
        if type(value) is not bool:raise ValueError('Boolean channel switch value required')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for channel switch')
            index=source-1
            # Recheck inclusion immediately before writing; never auto-add/unlink a strip.
            show=self.read(bus+'_channel_show')
            stereo=self.read(bus+'_channel_stereo')
            if not (show>>index)&1 or (stereo>>(index//2))&1:
                raise DeviceError('Source must be selected as mono; stereo/absent strips are read-only')
            parameter = f'{bus}_channel_{control}'
            current=self.read_input_bit(parameter,index)
            if current==int(value):return current
            return self._write_and_confirm(parameter,int(value),index)

    def aux_links_snapshot(self):
        with self.lock:
            state={'channel':'aux_links','mask':None,'link12':None,'link34':None,'writes_available':False,'errors':{}}
            try:
                mask=self.read('aux_link')
                state.update(mask=mask,link12=(mask>>1)&1,link34=(mask>>3)&1,
                             writes_available=self.version==VALIDATED_STATE_VERSION)
                if self.version!=VALIDATED_STATE_VERSION:state['errors']['version']='Unsupported state version'
            except DeviceDisconnected:raise
            except DeviceError as e:state['errors']['link']=str(e)
            return state

    def write_aux_link(self,pair,value):
        if type(pair) is not int or pair not in (1,3) or type(value) is not bool:
            raise ValueError('Aux pair must be1 or3 with a boolean link state')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for Aux stereo linking')
            # Firmware pair controls use (pair_number*2)+1: only bits1 and3.
            current=self.read_input_bit('aux_link',pair)
            if current==int(value):return current
            return self._write_and_confirm('aux_link',int(value),pair)

    def mixer_masters_snapshot(self):
        with self.lock:
            state={'channel':'masters','levels':{},'errors':{}}
            for bus in MIXER_BUSES:
                field=bus+'_master'
                try:
                    raw=self.read(field)
                    signed=struct.unpack('<h',struct.pack('<H',raw))[0]
                    in_range=-60*256<=signed<=0
                    state['levels'][bus]={'raw':raw,'signed':signed,'db':signed/256,
                        'writes_available':in_range and self.version==VALIDATED_STATE_VERSION}
                    if not in_range:state['errors'][bus]='Level outside this build’s −60 to 0 dB adjustment range'
                except DeviceDisconnected:raise
                except DeviceError as e:
                    state['levels'][bus]={'raw':None,'signed':None,'db':None,'writes_available':False}
                    state['errors'][bus]=str(e)
            try:
                mask=self.read('aux_mute')
                state['aux_mute_mask']=mask
                state['aux_mutes']={'aux'+str(i+1):(mask>>i)&1 for i in range(4)}
                state['aux_mute_writes_available']=self.version==VALIDATED_STATE_VERSION
            except DeviceDisconnected:raise
            except DeviceError as e:
                state.update(aux_mute_mask=None,aux_mutes={},aux_mute_writes_available=False)
                state['errors']['aux_mutes']=str(e)
            try:
                mask=self.read('aux_pre')
                state['aux_pre_mask']=mask
                state['aux_pre']={'aux'+str(i+1):(mask>>i)&1 for i in range(4)}
                state['aux_pre_writes_available']=self.version==VALIDATED_STATE_VERSION
            except DeviceDisconnected:raise
            except DeviceError as e:
                state.update(aux_pre_mask=None,aux_pre={},aux_pre_writes_available=False)
                state['errors']['aux_pre']=str(e)
            try:
                raw=self.read('cue_enabled')
                state['cue_enabled']=raw
                state['cue_writes_available']=raw in (0,1) and self.version==VALIDATED_STATE_VERSION
                if raw not in (0,1):state['errors']['cue_enabled']='Unexpected Cue enable value; save a report'
            except DeviceDisconnected:raise
            except DeviceError as e:
                state.update(cue_enabled=None,cue_writes_available=False);state['errors']['cue_enabled']=str(e)
            if self.version!=VALIDATED_STATE_VERSION:state['errors']['version']='Unsupported state version'
            return state

    def write_cue_enabled(self,value):
        if type(value) is not bool:raise ValueError('Boolean Cue enable value required')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for Cue enable')
            current=self.read('cue_enabled')
            if current not in (0,1):raise DeviceError('Unexpected Cue enable value; write skipped')
            if current==int(value):return current
            return self._write_and_confirm('cue_enabled',int(value))

    def write_aux_mute(self,bus,value):
        if bus not in MIXER_BUSES[2:] or type(value) is not bool:
            raise ValueError('Aux bus and boolean mute value required')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for Aux mute')
            index=MIXER_BUSES[2:].index(bus)
            current=self.read_input_bit('aux_mute',index)
            if current==int(value):return current
            return self._write_and_confirm('aux_mute',int(value),index)

    def write_aux_pre(self,bus,value):
        if bus not in MIXER_BUSES[2:] or type(value) is not bool:
            raise ValueError('Aux bus and boolean pre-fader value required')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for Aux pre/post')
            index=MIXER_BUSES[2:].index(bus)
            current=self.read_input_bit('aux_pre',index)
            if current==int(value):return current
            return self._write_and_confirm('aux_pre',int(value),index)

    def step_mixer_master(self,bus,direction, *, target_raw=None):
        if bus not in MIXER_BUSES or type(direction) is not int or direction not in (-1,1):
            raise ValueError('Invalid mixer master step')
        with self.lock:
            self.last_write=None
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for mixer masters')
            field=bus+'_master'
            raw=self.read(field)
            current=struct.unpack('<h',struct.pack('<H',raw))[0]
            if not -60*256<=current<=0:raise DeviceError('Mixer master outside this build’s −60 to 0 dB adjustment range')
            target=max(-60*256,min(0,current+direction*256)) if target_raw is None else target_raw
            if type(target) is not int or not -60*256 <= target <= 0: raise ValueError("Invalid master target")
            if target!=current:self._write_and_confirm(field,target&65535)
            return target

    def headphones_snapshot(self):
        with self.lock:
            state={'channel':'phones','read_only':True,'errors':{}}
            for field,parameter in (('preset_raw','phones_preset'),('knob_raw','phones_knob')):
                try:state[field]=self.read(parameter)
                except DeviceDisconnected:raise
                except DeviceError as e:state[field]=None;state['errors'][field]=str(e)
            return state

    def monitor_settings_snapshot(self):
        with self.lock:
            raw,errors={},{}
            for name in ('dim_depth','ab_enabled','ab_selected','ab_destination','ab_trim'):
                try:raw[name]=self.read(name)
                except DeviceDisconnected:raise
                except DeviceError as e:raw[name]=None;errors[name]=str(e)
            depth=raw['dim_depth'];depth_ok=depth in (0,1)
            if not depth_ok and 'dim_depth' not in errors:errors['dim_depth']='Unsupported dim-depth value; save a report'
            for name in ('ab_enabled','ab_selected'):
                if raw[name] not in (0,1) and name not in errors:errors[name]='Unsupported A/B state; save a report'
            destination=raw['ab_destination']
            dest_ok=type(destination) is int and 0<=destination<=3
            if not dest_ok and 'ab_destination' not in errors:errors['ab_destination']='B output assignment unavailable'
            trim=raw['ab_trim']
            signed=struct.unpack('<h',struct.pack('<H',trim))[0] if trim is not None else None
            trim_ok=signed is not None and -12*256<=signed<=12*256
            if not trim_ok and 'ab_trim' not in errors:errors['ab_trim']='B trim is outside the recovered range'
            version_ok=self.version==VALIDATED_STATE_VERSION
            if not version_ok:errors['version']='Unsupported state version'
            return {'channel':'monitor_settings','dim_depth_raw':depth,
                    'dim_depth_db':(-10 if depth==0 else -20) if depth_ok else None,
                    'writes_available':depth_ok and version_ok,'ab_writes_available':version_ok,
                    'ab_enabled':raw['ab_enabled'],'ab_selected':raw['ab_selected'],
                    'ab_destination_raw':destination,'ab_pair':[3+2*destination,4+2*destination] if dest_ok else None,
                    'ab_trim_raw':trim,'ab_trim_db':signed/256 if trim_ok else None,
                    'errors':errors,'error':'; '.join(dict.fromkeys(errors.values()))}

    def _write_ab_setting(self, name, target):
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for A/B monitoring')
            self.last_write={'control':name,'requested':target,'confirmed':False}
            context=None
            try:
                context=self.monitor_settings_snapshot()
                current=context[name]
                if current not in (0,1):raise DeviceError('Unsupported A/B state; write skipped')
                if name=='ab_selected' and context['ab_enabled']!=1:
                    raise DeviceError('Enable A/B monitoring before selecting a speaker set')
                if target==1 and (context['ab_pair'] is None or context['ab_trim_db'] is None or context['ab_selected'] not in (0,1)):
                    raise DeviceError('B output assignment or trim is unavailable; write skipped')
                if current!=target:self._write_and_confirm(name,target)
                else:self.last_write.update(confirmed=True,skipped=True)
                return target
            except DeviceError as e:
                self.last_write['error']=str(e)
                raise
            finally:
                if context is not None:self.last_write['ab_context_before']=context

    def write_ab_enabled(self, value):
        if type(value) is not bool:raise ValueError('A/B enable must be boolean')
        return self._write_ab_setting('ab_enabled',int(value))

    def write_ab_selected(self, speaker):
        if speaker not in ('A','B'):raise ValueError('Speaker selection must be A or B')
        return self._write_ab_setting('ab_selected',0 if speaker=='A' else 1)

    def write_ab_destination(self, first_output):
        if type(first_output) is not int or first_output not in (3,5,7,9):
            raise ValueError('B output pair must be 3–4, 5–6, 7–8 or 9–10')
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for B output assignment')
            target=(first_output-3)//2
            self.last_write={'control':'ab_destination','requested':target,'confirmed':False}
            context=None
            try:
                context=self.monitor_settings_snapshot()
                current=context['ab_destination_raw']
                if type(current) is not int or not 0<=current<=3:raise DeviceError('Unknown B output assignment; write skipped')
                if current!=target:
                    if context['ab_enabled'] not in (0,1) or context['ab_selected'] not in (0,1):raise DeviceError('A/B state unavailable; write skipped')
                    if context['ab_enabled']==1 and context['ab_selected']==1:
                        raise DeviceError('Select Speaker A or disable A/B before changing the B output pair')
                    self._write_and_confirm('ab_destination',target)
                else:self.last_write.update(confirmed=True,skipped=True)
                return first_output
            except DeviceError as e:
                self.last_write['error']=str(e)
                raise
            finally:
                self.last_write.update(requested_pair=[first_output,first_output+1],ab_context_before=context)

    def step_ab_trim(self, direction):
        if type(direction) is not int or direction not in (-1,1):raise ValueError('B trim direction must be −1 or +1')
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for B trim')
            self.last_write={'control':'ab_trim','direction':direction,'confirmed':False}
            context=None;target=None
            try:
                context=self.monitor_settings_snapshot()
                raw=context['ab_trim_raw']
                if raw is None or context['ab_trim_db'] is None:raise DeviceError('B trim is outside the recovered ±12 dB range')
                current=struct.unpack('<h',struct.pack('<H',raw))[0]
                target=max(-12*256,min(12*256,current+direction*256))
                if current!=target:self._write_and_confirm('ab_trim',target & 65535)
                else:self.last_write.update(requested=target & 65535,confirmed=True,skipped=True)
                return target
            except DeviceError as e:
                self.last_write['error']=str(e)
                raise
            finally:
                self.last_write['ab_context_before']=context
                if target is not None:self.last_write['requested_db']=target/256

    def write_dim_depth(self, db):
        if type(db) is not int or db not in (-10,-20):raise ValueError('Dim depth must be −10 or −20 dB')
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for dim depth')
            raw=0 if db==-10 else 1
            self.last_write={'control':'dim_depth','requested':raw,'requested_db':db,'confirmed':False}
            try:
                current=self.read('dim_depth')
                if current not in (0,1):raise DeviceError('Unsupported dim-depth value; write skipped')
                if current!=raw:self._write_and_confirm('dim_depth',raw)
                else:self.last_write.update(confirmed=True,skipped=True)
                return db
            except DeviceError as e:
                self.last_write['error']=str(e)
                raise
            finally:self.last_write['requested_db']=db

    def output_snapshot(self, channel):
        if type(channel) is not int or not 3 <= channel <= 10:
            raise ValueError('Analog output must be 3 through 10')
        with self.lock:
            values = {'channel': 'output', 'output': channel, 'errors': {}}
            try:
                raw = self.read('output_gain',channel-3)
                signed = struct.unpack('<h',struct.pack('<H',raw))[0]
                supported = -60*VOLUME_UNITS_PER_DB <= signed <= 0
                values.update(level_raw=raw,level_signed=signed,level_db=signed/256 if supported else None,
                              writes_available=supported and self.version==VALIDATED_STATE_VERSION)
                if not supported: values['errors']['level']='Output level is outside the recovered −60 to 0 dB range'
                elif self.version!=VALIDATED_STATE_VERSION: values['errors']['level']='Unsupported state version'
            except DeviceDisconnected:
                raise
            except DeviceError as e:
                values.update(level_raw=None,level_signed=None,level_db=None,writes_available=False)
                values['errors']['level']=str(e)
            left=((channel-3)//2)*2
            values['pair']=[left+3,left+4]
            try:
                mask=self.read('output_link')
                bits=[(mask>>left)&1,(mask>>(left+1))&1]
                values.update(link_mask=mask,link_bits=bits,link=bits[0] if bits[0]==bits[1] else None,
                              link_mixed=bits[0]!=bits[1],link_writes_available=self.version==VALIDATED_STATE_VERSION)
                if self.version!=VALIDATED_STATE_VERSION:values['errors']['link']='Unsupported state version'
            except DeviceDisconnected:
                raise
            except DeviceError as e:
                values.update(link_mask=None,link_bits=None,link=None,link_mixed=False,link_writes_available=False)
                values['errors']['link']=str(e)
            values['error']='; '.join(dict.fromkeys(values['errors'].values()))
            return values

    def write_output_link(self, channel, value):
        if type(channel) is not int or not 3<=channel<=10 or type(value) is not bool:
            raise ValueError('Invalid output pair link')
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for output link')
            left=((channel-3)//2)*2
            transactions=[]
            result={'control':'output_link_pair','pair':[left+3,left+4],'requested':int(value),
                    'transactions':transactions,'confirmed':False}
            self.last_write=None
            try:
                for index in (left,left+1):
                    if self.read_input_bit('output_link',index)==int(value):continue
                    self._write_and_confirm('output_link',int(value),index)
                    transactions.append(self.last_write)
                actual=[self.read_input_bit('output_link',index) for index in (left,left+1)]
                result['actual_bits']=actual
                if actual!=[int(value)]*2:raise DeviceError('Output link flags disagree; refresh the pair')
                result['confirmed']=True
                return int(value)
            except DeviceError as e:
                if self.last_write is not None and self.last_write not in transactions:transactions.append(self.last_write)
                result['error']=str(e)
                raise
            finally:self.last_write=result

    def step_output_gain(self, channel, direction):
        if type(channel) is not int or not 3 <= channel <= 10 or type(direction) is not int or direction not in (-1,1):
            raise ValueError('Invalid analog output level step')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for output level')
            self.last_write = None
            raw = self.read('output_gain', channel-3)
            current = struct.unpack('<h', struct.pack('<H', raw))[0]
            if not -60*VOLUME_UNITS_PER_DB <= current <= 0:
                raise DeviceError('Output level is outside the recovered −60 to 0 dB range')
            target = max(-60*VOLUME_UNITS_PER_DB,min(0,current+direction*VOLUME_UNITS_PER_DB))
            if target != current:
                self._write_and_confirm('output_gain',target & 0xffff,channel-3)
            return target

    def mini_snapshot(self):
        with self.lock:
            context=self.link_context();sources=mini_source_status(context)
            values={'channel':'mini','source_status':{'sources':sources},'link_context':context,
                    'writes_available':self.version==VALIDATED_STATE_VERSION,'control_available':{},'errors':{},'packed_words':{}}
            for channel in (3,4):
                active=bool(sources and sources[channel-3]=='line')
                field='gain'+str(channel)
                values.update({field+'_raw':None,field+'_db':None})
                values['control_available'][field]=False
                if active:
                    try:
                        raw=self.read('front_mini_gain',channel-3)
                        signed=struct.unpack('<h',struct.pack('<H',raw))[0]
                        supported=0<=signed<=12*256
                        values[field+'_raw']=raw;values[field+'_db']=signed/256 if supported else None
                        values['control_available'][field]=supported and values['writes_available']
                        if not supported:values['errors'][field]='Minijack gain is outside the recovered 0–12 dB range'
                    except DeviceDisconnected:raise
                    except DeviceError as e:values['errors'][field]=str(e)
                for control in ('phase','pad'):
                    field=control+str(channel);values[field]=None;values['control_available'][field]=False
                    if not active:continue
                    try:
                        if control not in values['packed_words']:values['packed_words'][control]=self.read('front_line_'+control)
                        values[field]=(values['packed_words'][control]>>(channel-1))&1
                        values['control_available'][field]=values['writes_available']
                    except DeviceDisconnected:raise
                    except DeviceError as e:values['errors'][field]=str(e)
            if sources is None:values['errors']['source']='Front minijack source status unavailable'
            return values

    def step_mini_gain(self, channel, direction):
        if type(channel) is not int or channel not in (3,4) or type(direction) is not int or direction not in (-1,1):
            raise ValueError('Invalid front minijack gain step')
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for front minijack')
            self.last_write={'control':'front_mini_gain','channel':channel,'confirmed':False}
            context=self.link_context()
            try:
                sources=mini_source_status(context)
                if not sources or sources[channel-3]!='line':raise DeviceError('Front minijack is inactive; check connection and rear override')
                raw=self.read('front_mini_gain',channel-3)
                current=struct.unpack('<h',struct.pack('<H',raw))[0]
                if not 0<=current<=12*256:raise DeviceError('Minijack gain is outside the recovered 0–12 dB range')
                target=max(0,min(12*256,current+direction*256))
                if target!=current:self._write_and_confirm('front_mini_gain',target,channel-3)
                else:self.last_write.update(requested=target,confirmed=True,skipped=True)
                return target
            except DeviceError as e:
                self.last_write['error']=str(e);raise
            finally:self.last_write.update(channel=channel,context_before=context)

    def write_mini_switch(self, channel, name, value):
        if type(channel) is not int or channel not in (3,4) or name not in ('phase','pad') or type(value) is not bool:
            raise ValueError('Invalid front minijack switch')
        with self.lock:
            if self.version!=VALIDATED_STATE_VERSION:raise DeviceError('Unsupported state version for front minijack')
            parameter='front_line_'+name
            self.last_write={'control':parameter,'channel':channel,'requested':int(value),'confirmed':False}
            context=self.link_context()
            try:
                sources=mini_source_status(context)
                if not sources or sources[channel-3]!='line':raise DeviceError('Front minijack is inactive; check connection and rear override')
                if self.read_input_bit(parameter,channel-1)!=int(value):self._write_and_confirm(parameter,int(value),channel-1)
                else:self.last_write.update(confirmed=True,skipped=True)
                return int(value)
            except DeviceError as e:
                self.last_write['error']=str(e);raise
            finally:self.last_write.update(channel=channel,context_before=context)

    def front_snapshot(self):
        with self.lock:
            values, errors, masks = {}, {}, {}
            for kind in ('line', 'mic'):
                try:
                    masks[kind] = self.read('front_'+kind+'_link')
                    values[kind] = masks[kind] & 1
                except DeviceDisconnected:
                    raise
                except DeviceError as e:
                    values[kind], errors[kind] = None, str(e)
            context = self.link_context()
            sources = front_source_status(context)['sources']
            for control in ('phase', 'hpf', 'pad'):
                for index in range(2):
                    field = control+str(index+1)
                    kind = sources[index] if sources else None
                    values[field] = None
                    if kind not in ('line', 'mic'):
                        errors[field] = 'Front input is inactive or source status is unavailable.'
                        continue
                    try:
                        mask_key = control+'_'+kind
                        if mask_key not in masks: masks[mask_key] = self.read('front_'+kind+'_'+control)
                        values[field] = (masks[mask_key] >> index) & 1
                    except DeviceDisconnected:
                        raise
                    except DeviceError as e:
                        errors[field] = str(e)
            for index in range(2):
                field = 'gain'+str(index+1)
                kind = sources[index] if sources else None
                values[field] = None
                if kind not in ('line', 'mic'):
                    errors[field] = 'Front input is inactive or source status is unavailable.'
                    continue
                try:
                    values[field] = self.read('front_'+kind+'_gain', index)
                    if not 0 <= values[field] <= 55:
                        errors[field] = 'Gain is outside the recovered native range 0–55.'
                except DeviceDisconnected:
                    raise
                except DeviceError as e:
                    errors[field] = str(e)
            for index in range(2):
                field = 'instrument'+str(index+1)
                values[field] = None
                if not sources or sources[index] != 'line': continue
                try:
                    if 'instrument' not in masks: masks['instrument'] = self.read('front_line_instrument')
                    values[field] = (masks['instrument'] >> index) & 1
                except DeviceDisconnected:
                    raise
                except DeviceError as e:
                    errors[field] = str(e)
            return {'channel': 'front', **values, 'errors': errors,
                    'source_status': front_source_status(context),
                    'packed_words': masks, 'link_context': context,
                    'writes_available': self.version == VALIDATED_STATE_VERSION}

    def step_front_gain(self, channel, kind, direction):
        if type(channel) is not int or channel not in (1,2) or kind not in ('line','mic') or type(direction) is not int or direction not in (-1,1):
            raise ValueError('Invalid front gain step')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for front gain')
            parameter = 'front_'+kind+'_gain'
            self.last_write = {'control': parameter, 'channel': channel, 'direction': direction, 'confirmed': False}
            context = self.link_context()
            try:
                sources = front_source_status(context)['sources']
                if not sources or sources[channel-1] != kind:
                    raise DeviceError('Front source changed or is inactive; refresh before changing gain')
                current = self.read(parameter, channel-1)
                if not 0 <= current <= 55:
                    raise DeviceError('Gain is outside the recovered native range 0–55')
                target = max(0, min(55, current+direction))
                if target != current:
                    self._write_and_confirm(parameter, target, channel-1)
                else:
                    self.last_write.update(requested=target, confirmed=True)
                return target
            except DeviceError as e:
                self.last_write['error'] = str(e)
                raise
            finally:
                self.last_write['context_before'] = context

    def write_front_phase(self, channel, kind, value):
        return self._write_front_switch(channel, kind, value, 'phase')

    def write_front_hpf(self, channel, kind, value):
        return self._write_front_switch(channel, kind, value, 'hpf')

    def write_front_pad(self, channel, kind, value):
        return self._write_front_switch(channel, kind, value, 'pad')

    def write_front_instrument(self, channel, value):
        return self._write_front_switch(channel, 'line', value, 'instrument')

    def _write_front_switch(self, channel, kind, value, control):
        if control not in ('phase', 'hpf', 'pad', 'instrument'): raise ValueError('Invalid front switch')
        if type(channel) is not int or channel not in (1,2) or kind not in ('line','mic') or type(value) is not bool:
            raise ValueError('Invalid front switch control')
        if control == 'instrument' and kind != 'line': raise ValueError('Instrument mode requires a front jack')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for front switch')
            parameter = 'front_'+kind+'_'+control
            self.last_write = {'control': parameter, 'channel': channel, 'requested': int(value), 'confirmed': False}
            context = self.link_context()
            try:
                sources = front_source_status(context)['sources']
                if not sources or sources[channel-1] != kind:
                    raise DeviceError('Front source changed or is inactive; refresh before changing front switches')
                if self.read_input_bit(parameter, channel-1) != int(value):
                    self._write_and_confirm(parameter, int(value), channel-1)
                else:
                    self.last_write['confirmed'] = True
                return int(value)
            except DeviceError as e:
                self.last_write['error'] = str(e)
                raise
            finally:
                self.last_write['context_before'] = context

    def write_front_link(self, kind, value):
        if kind not in ('line', 'mic') or type(value) is not bool:
            raise ValueError('Invalid front link control')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for front linking')
            parameter = 'front_'+kind+'_link'
            self.last_write = {'control': parameter, 'requested': int(value), 'confirmed': False}
            context = self.link_context()
            try:
                source = front_source_status(context)
                if not source['available'][kind]:
                    raise DeviceError(source['reason'][kind])
                if self.read_input_bit(parameter, 0) != int(value):
                    self._write_and_confirm(parameter, int(value), 0)
                else:
                    self.last_write['confirmed'] = True
                return int(value)
            except DeviceError as e:
                self.last_write['error'] = str(e)
                if isinstance(e, DeviceDisconnected): raise
                raise DeviceError(str(e) + '; both front inputs must use compatible modes. '
                                  'Use Enable front detection in the Front 1–2 panel if rear override is active.') from e
            finally:
                self.last_write['context_before'] = context

    def input_snapshot(self, channel):
        if type(channel) is not int or not 1 <= channel <= 16:
            raise ValueError('Rear input must be 1 through 16')
        with self.lock:
            values, errors, availability, packed_words, raw_switches = {}, {}, {}, {}, {}
            for name, parameter in INPUT_CONTROLS.items():
                try:
                    packed = self.read(parameter, (channel-1)//16)
                    packed_words[name] = packed
                    value = (packed >> ((channel-1) % 16)) & 1
                    raw_switches[name] = value
                    if name in INVERTED_INPUT_CONTROLS: value = 1-value
                    values[name] = value
                    availability[name] = self.version == VALIDATED_STATE_VERSION and value in (0, 1)
                    if value not in (0, 1):
                        errors[name] = f'Unsupported value {value} (0x{value:04x})'
                    elif self.version != VALIDATED_STATE_VERSION:
                        errors[name] = f'Unsupported state version {self.version}'
                except DeviceDisconnected:
                    raise
                except DeviceError as e:
                    values[name], availability[name], errors[name] = None, False, str(e)
            try:
                gain = self.read('rear_gain', channel-1)
                signed = struct.unpack('<h', struct.pack('<H', gain))[0]
                values.update(gain_raw=gain, gain_signed=signed,
                              gain_db=None if signed == -32768 else signed / VOLUME_UNITS_PER_DB)
                availability['gain'] = self.version == VALIDATED_STATE_VERSION and 0 <= signed <= 12*VOLUME_UNITS_PER_DB
                if not availability['gain']:
                    errors['gain'] = 'Gain outside the initial 0–12 dB control range or unsupported state version'
            except DeviceDisconnected:
                raise
            except DeviceError as e:
                values.update(gain_raw=None, gain_signed=None, gain_db=None)
                availability['gain'], errors['gain'] = False, str(e)
            context = self.link_context()
            left = ((channel-1)//2)*2
            values['pair'] = [left+1, left+2]
            try:
                bank=input_link_bank(channel,context)
                values['link_bank']=bank
                mask = self.read('rear_link' if bank=='rear' else 'front_'+bank+'_link', 0)
                packed_words['link'] = mask
                bits = [(mask >> left)&1, (mask >> (left+1))&1] if bank=='rear' else [mask&1]*2
                values.update(link_bits=bits, link=bits[0] if bits[0] == bits[1] else None,
                              link_mixed=bits[0] != bits[1])
                availability['link'] = self.version == VALIDATED_STATE_VERSION
                if not availability['link']: errors['link'] = 'Unsupported state version'
            except DeviceDisconnected:
                raise
            except DeviceError as e:
                values.update(link_bits=None, link=None, link_mixed=False)
                availability['link'], errors['link'] = False, str(e)
            return {'channel': channel, **values, 'control_available': availability,
                    'errors': errors, 'packed_words': packed_words, 'raw_switches': raw_switches, 'link_context': context,
                    'writes_available': any(availability.values())}

    def write_input_bool(self, channel, name, value):
        if type(channel) is not int or not 1 <= channel <= 16 or name not in INPUT_CONTROLS or type(value) is not bool:
            raise ValueError('Invalid rear-input control')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for input writes')
            self.last_write = None
            parameter, index = INPUT_CONTROLS[name], channel-1
            current = self.read_input_bit(parameter, index)
            if current not in (0, 1):
                raise DeviceError('Unexpected input boolean value; write skipped')
            target = 1-int(value) if name in INVERTED_INPUT_CONTROLS else int(value)
            if current == target:
                return int(value)
            try:
                actual = self._write_and_confirm(parameter, target, index)
                return 1-actual if name in INVERTED_INPUT_CONTROLS else actual
            finally:
                if name in INVERTED_INPUT_CONTROLS and self.last_write is not None:
                    self.last_write.update(logical_requested=int(value), encoding='active_low', channel=channel)

    def step_input_gain(self, channel, direction):
        if type(channel) is not int or not 1 <= channel <= 16 or type(direction) is not int or direction not in (-1, 1):
            raise ValueError('Invalid rear gain step')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for input gain')
            self.last_write = None
            raw = self.read('rear_gain', channel-1)
            current = struct.unpack('<h', struct.pack('<H', raw))[0]
            if not 0 <= current <= 12*VOLUME_UNITS_PER_DB:
                raise DeviceError('Gain is outside the initial 0–12 dB control range')
            target = max(0, min(12*VOLUME_UNITS_PER_DB, current+direction*VOLUME_UNITS_PER_DB))
            if target != current:
                self._write_and_confirm('rear_gain', target, channel-1)
            return target

    def set_rear_pair_source(self, channel, force):
        """Explicit source selection; never done automatically by linking."""
        if type(channel) is not int or not 1 <= channel <= 4 or type(force) is not bool:
            raise ValueError('Source selection supports rear pairs 1–2 and 3–4')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for source selection')
            left = ((channel-1)//2)*2
            transactions = []
            result = {'control': 'rear_pair_source', 'pair': [left+1, left+2],
                      'requested': int(force), 'transactions': transactions, 'confirmed': False}
            self.last_write = None
            try:
                for index in (left, left+1):
                    if self.read_input_bit('force_rear', index) != int(force):
                        self._write_and_confirm('force_rear', int(force), index)
                        transactions.append(self.last_write)
                result['actual_bits'] = [self.read_input_bit('force_rear', i) for i in (left,left+1)]
                if result['actual_bits'] != [int(force)]*2:
                    raise DeviceError('Rear source selection not confirmed')
                result['confirmed'] = True
                return int(force)
            except DeviceError as e:
                if self.last_write is not None and self.last_write not in transactions:
                    transactions.append(self.last_write)
                result['error'] = str(e)
                raise
            finally:
                self.last_write = result

    def write_input_link(self, channel, value):
        if type(channel) is not int or not 1 <= channel <= 16 or type(value) is not bool:
            raise ValueError('Invalid stereo pair link')
        with self.lock:
            if self.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version for stereo link')
            context=self.link_context()
            bank=input_link_bank(channel,context)
            if bank!='rear':return self.write_front_link(bank,value)
            left = ((channel-1)//2)*2
            self.last_write = None
            transactions = []
            result = {'control': 'rear_link_pair', 'pair': [left+1, left+2],
                      'requested': int(value), 'transactions': transactions, 'confirmed': False,
                      'context_before': context}
            try:
                for index in (left, left+1):
                    current = self.read_input_bit('rear_link', index)
                    if current == int(value): continue
                    self._write_and_confirm('rear_link', int(value), index)
                    transactions.append(self.last_write)
                actual = [self.read_input_bit('rear_link', index) for index in (left, left+1)]
                result['actual_bits'] = actual
                if actual != [int(value), int(value)]:
                    raise DeviceError('Stereo link flags disagree; refresh the pair state')
                result['confirmed'] = True
                return int(value)
            except DeviceError as e:
                if self.last_write is not None and self.last_write not in transactions:
                    transactions.append(self.last_write)
                result['error'] = str(e)
                if isinstance(e, DeviceDisconnected):
                    raise
                result['context_after'] = self.link_context()
                if left < 4:
                    raise DeviceError(str(e) + '; selected link bank: REAR; source context: '+str(result['context_after']['raw'])) from e
                raise
            finally:
                self.last_write = result

    def snapshot(self):
        with self.lock:
            state = {name: self.read(name) for name in
                     ('speaker_level', 'mute', 'mono', 'dim')}
            state['speaker_level_signed'] = struct.unpack('<h', struct.pack('<H', state['speaker_level']))[0]
            state['speaker_level_db'] = (None if state['speaker_level_signed'] == -32768
                                         else state['speaker_level_signed'] / VOLUME_UNITS_PER_DB)
            state['state_version'] = self.version
            state['writes_available'] = self.version == VALIDATED_STATE_VERSION and all(
                state[name] in (0, 1) for name in BOOLEAN_CONTROLS)
            return state

class DemoAF16Rig:
    """Offline GUI preview; never opens libusb or touches hardware."""
    def __init__(self):
        self.values = {'speaker_level': 62464, 'mute': 0, 'mono': 0, 'dim': 0,
                       'state_version': 18, 'firmware_raw': 2, 'hardware_raw': 1,
                       'audio_firmware_raw': 513}
        self.version = 18
        self.inputs = {n: {'phase': 0, 'hpf': 0, 'pad': 0, 'gain_raw': 0, 'link': 0} for n in range(1, 17)}
    def set_console_value(self, bus, source, control, target, stereo=False):
        if type(target) is not int or stereo:
            raise ValueError('Invalid demo target')
        if source == 0 and control == 'master':
            if bus not in MIXER_BUSES or not -60*256 <= target <= 0: raise ValueError('Invalid master target')
            setattr(self, bus+'_master', target)
            return target
        AF16Rig.validate_mix_channel(bus,source)
        if control == 'pan':
            if not 0 <= target <= 254: raise ValueError('Invalid pan target')
            if not hasattr(self,'pan_positions'): self.pan_positions={}
            self.pan_positions[bus,source]=target
        elif control == 'level':
            if not -60*256 <= target <= CHANNEL_MAX_RAW: raise ValueError('Invalid level target')
            if not hasattr(self,'mix_levels'): self.mix_levels={}
            self.mix_levels[bus,source]=target
        elif control in ('send1','send2','send3','send4') and bus=='main':
            if not -60*256 <= target <= CHANNEL_MAX_RAW: raise ValueError('Invalid send target')
            if not hasattr(self,'send_levels'): self.send_levels={}
            self.send_levels[source,int(control[-1])]=target
        else: raise ValueError('Invalid console control')
        return target

    def adjust_main_pan(self, bus, source, action):
        if bus != 'main':
            raise ValueError('Main mix required')
        return self.adjust_channel_pan(bus, source, action)

    def adjust_channel_pan(self, bus, source, action):
        AF16Rig.validate_mix_channel(bus,source)
        if action not in ('Left','Centre','Right','L step','R step'):
            raise ValueError('Invalid channel pan command')
        if not hasattr(self,'pan_positions'):
            self.pan_positions = {}
        current = self.pan_positions.get((bus,source),127)
        target = {'Left':0,'Centre':127,'Right':254,'L step':max(0,current-1),'R step':min(254,current+1)}[action]
        self.pan_positions[bus,source] = target
        return target

    def scan_pan_positions(self):
        return {'values': {f'{bus} {n}': getattr(self,'pan_positions',{}).get((bus,n),127) for bus in ('main', 'cue') for n in range(1,17)}, 'errors': {}}

    def mix_channel_snapshot(self,bus,source):
        AF16Rig.validate_mix_channel(bus,source)
        mask=getattr(self,bus+'_channel_mute',0)
        solo = getattr(self, bus+'_channel_solo', 0)
        level=getattr(self,'mix_levels',{}).get((bus,source),-12*256)
        state = {'channel':'mix_channel','bus':bus,'source':source,'raw':{'pan':getattr(self,'pan_positions',{}).get((bus,source),127),'show':getattr(self,bus+'_show',65535),'stereo':getattr(self,bus+'_stereo',0),'mute':mask,'solo':solo,'level':level&65535},
                'solo':(solo>>(source-1))&1,'solo_writes_available':True,'mono_selected':1,'stereo_selected':0,'mute':(mask>>(source-1))&1,'level_signed':level,'level_db':level/256,'level_writes_available':-60*256<=level<=CHANNEL_MAX_RAW,'writes_available':True,'errors':{}}
        mono=(state['raw']['show']>>(source-1))&1
        stereo=(state['raw']['stereo']>>((source-1)//2))&1
        state.update(mono_selected=mono,stereo_selected=stereo)
        state['writes_available']=state['solo_writes_available']=state['level_writes_available']=bool(mono and not stereo)
        if stereo:
            left=(source-1)&~1
            state['stereo_members']=[dict(source=i+1,level_db=getattr(self,'mix_levels',{}).get((bus,i+1),-12*256)/256,
                mute=(mask>>i)&1,solo=(solo>>i)&1) for i in (left,left+1)]
            state['pair_editable']=False  # This demo does not simulate stereo control writes.
            state['errors']['demo']='Stereo control writes are not simulated in demo mode'
        if bus == 'main':
            state['send_writes_available'] = bool(mono and not stereo)
            for aux in range(1, 5):
                name = f'send{aux}'
                mask = getattr(self, name, 0)
                state['raw'][name] = mask
                state[name] = (mask >> (source-1)) & 1
                key = f'aux{aux}_send_level'
                state[key] = getattr(self,'send_levels',{}).get((source,aux),-12*256)
                state['raw'][key] = state[key] & 65535
        return state

    def step_send_level(self, bus, source, aux, direction):
        AF16Rig.validate_mix_channel(bus,source)
        if bus != 'main' or type(aux) is not int or aux not in range(1,5) or type(direction) is not int or direction not in (-1,1):
            raise ValueError('Invalid Aux send level step')
        if not hasattr(self,'send_levels'):
            self.send_levels = {}
        current = self.send_levels.get((source,aux),-12*256)
        target = max(-60*256,min(CHANNEL_MAX_RAW,current+direction*256))
        self.send_levels[source,aux] = target
        return target

    def write_send_mute(self, bus, source, aux, value):
        AF16Rig.validate_mix_channel(bus, source)
        if bus != 'main' or type(aux) is not int or aux not in range(1,5) or type(value) is not bool:
            raise ValueError('Invalid Main channel send mute')
        name = f'send{aux}'
        mask = getattr(self, name, 0)
        bit = 1 << (source-1)
        setattr(self, name, mask | bit if value else mask & ~bit)
        return int(value)

    def step_mix_channel_level(self,bus,source,direction):
        AF16Rig.validate_mix_channel(bus,source)
        if type(direction) is not int or direction not in (-1,1):raise ValueError('Invalid channel level step')
        if not hasattr(self,'mix_levels'):self.mix_levels={}
        current=self.mix_levels.get((bus,source),-12*256)
        if not -60*256<=current<=CHANNEL_MAX_RAW:raise DeviceError('Channel level outside adjustment range')
        target=max(-60*256,min(CHANNEL_MAX_RAW,current+direction*256));self.mix_levels[bus,source]=target;return target
    def write_mix_channel_mute(self,bus,source,value):
        AF16Rig.validate_mix_channel(bus,source)
        if type(value) is not bool:raise ValueError('Boolean channel mute value required')
        mask=getattr(self,bus+'_channel_mute',0)
        setattr(self,bus+'_channel_mute',mask|(1<<(source-1)) if value else mask&~(1<<(source-1)))
        return int(value)
    def write_mix_channel_solo(self,bus,source,value):
        AF16Rig.validate_mix_channel(bus,source)
        if type(value) is not bool:raise ValueError('Boolean channel solo value required')
        mask=getattr(self,bus+'_channel_solo',0)
        setattr(self,bus+'_channel_solo',mask|(1<<(source-1)) if value else mask&~(1<<(source-1)))
        return int(value)
    def aux_links_snapshot(self):
        mask=getattr(self,'aux_link_mask',0)
        return {'channel':'aux_links','mask':mask,'link12':(mask>>1)&1,'link34':(mask>>3)&1,'writes_available':True,'errors':{}}
    def write_aux_link(self,pair,value):
        if type(pair) is not int or pair not in (1,3) or type(value) is not bool:raise ValueError('Invalid Aux pair link')
        mask=getattr(self,'aux_link_mask',0)
        self.aux_link_mask=mask|(1<<pair) if value else mask&~(1<<pair)
        return int(value)
    def mixer_masters_snapshot(self):
        levels={}
        for bus in MIXER_BUSES:
            raw=getattr(self,bus+'_master',-12*256)
            levels[bus]={'raw':raw&65535,'signed':raw,'db':raw/256,'writes_available':-60*256<=raw<=0}
        return {'channel':'masters','levels':levels,'errors':{},'aux_mute_mask':getattr(self,'aux_mute_mask',0),
                'aux_mutes':{bus:(getattr(self,'aux_mute_mask',0)>>i)&1 for i,bus in enumerate(MIXER_BUSES[2:])},
                'aux_mute_writes_available':True, 'aux_pre_mask':getattr(self,'aux_pre_mask',0),
                'aux_pre':{bus:(getattr(self,'aux_pre_mask',0)>>i)&1 for i,bus in enumerate(MIXER_BUSES[2:])},
                'aux_pre_writes_available':True, 'cue_enabled':getattr(self,'cue_enabled',0),'cue_writes_available':True}
    def write_cue_enabled(self,value):
        if type(value) is not bool:raise ValueError('Boolean Cue enable value required')
        self.cue_enabled=int(value);return int(value)
    def step_mixer_master(self,bus,direction):
        if bus not in MIXER_BUSES or type(direction) is not int or direction not in (-1,1):raise ValueError('Invalid mixer master step')
        current=getattr(self,bus+'_master',-12*256)
        if not -60*256<=current<=0:raise DeviceError('Mixer master outside adjustment range')
        target=max(-60*256,min(0,current+direction*256));setattr(self,bus+'_master',target)
        return target
    def write_aux_mute(self,bus,value):
        if bus not in MIXER_BUSES[2:] or type(value) is not bool:raise ValueError('Aux bus and boolean mute value required')
        index=MIXER_BUSES[2:].index(bus);mask=getattr(self,'aux_mute_mask',0)
        self.aux_mute_mask=(mask|(1<<index)) if value else (mask&~(1<<index))
        return int(value)
    def write_aux_pre(self,bus,value):
        if bus not in MIXER_BUSES[2:] or type(value) is not bool:raise ValueError('Aux bus and boolean pre-fader value required')
        index=MIXER_BUSES[2:].index(bus);mask=getattr(self,'aux_pre_mask',0)
        self.aux_pre_mask=(mask|(1<<index)) if value else (mask&~(1<<index))
        return int(value)
    def headphones_snapshot(self):
        return {'channel':'phones','read_only':True,'preset_raw':getattr(self,'phones_preset',0),
                'knob_raw':getattr(self,'phones_knob',(-12*256)&65535),'errors':{}}
    def monitor_settings_snapshot(self):
        raw=getattr(self,'dim_depth',0)
        return {'channel':'monitor_settings','dim_depth_raw':raw,'dim_depth_db':-10 if raw==0 else -20,
                'writes_available':True,'error':'','errors':{},'ab_writes_available':True,
                'ab_enabled':getattr(self,'ab_enabled',0),'ab_selected':getattr(self,'ab_selected',0),
                'ab_destination_raw':getattr(self,'ab_destination',1),
                'ab_pair':[3+2*getattr(self,'ab_destination',1),4+2*getattr(self,'ab_destination',1)],
                'ab_trim_raw':getattr(self,'ab_trim',0)&65535,'ab_trim_db':getattr(self,'ab_trim',0)/256}
    def write_ab_enabled(self,value):
        self.ab_enabled=int(value)
        return int(value)
    def write_ab_selected(self,speaker):
        self.ab_selected=0 if speaker=='A' else 1
        return self.ab_selected
    def write_ab_destination(self,first_output):
        self.ab_destination=(first_output-3)//2
        return first_output
    def step_ab_trim(self,direction):
        self.ab_trim=max(-12*256,min(12*256,getattr(self,'ab_trim',0)+direction*256))
        return self.ab_trim
    def write_dim_depth(self,db):
        self.dim_depth=0 if db==-10 else 1
        return db
    def output_snapshot(self, channel):
        value = getattr(self, 'output_level_'+str(channel), 0)
        left=((channel-3)//2)*2
        mask=getattr(self,'output_link_mask',0)
        bits=[(mask>>left)&1,(mask>>(left+1))&1]
        return {'channel': 'output', 'output': channel, 'level_raw': value & 0xffff,
                'level_signed': value, 'level_db': value/256, 'writes_available': True, 'error': '', 'errors': {},
                'pair':[left+3,left+4], 'link_mask':mask,'link_bits':bits,'link_mixed':bits[0]!=bits[1],
                'link':bits[0] if bits[0]==bits[1] else None,'link_writes_available':True}
    def write_output_link(self, channel, value):
        left=((channel-3)//2)*2
        mask=getattr(self,'output_link_mask',0)
        self.output_link_mask=(mask & ~(3<<left)) | ((3 if value else 0)<<left)
        return int(value)
    def step_output_gain(self, channel, direction):
        name = 'output_level_'+str(channel)
        value = max(-60*256,min(0,getattr(self,name,0)+direction*256))
        setattr(self,name,value)
        return value
    def mini_snapshot(self):
        context={'raw':{'force_rear':getattr(self,'force_rear',3),'detect_status':getattr(self,'detect_status',0x31)},'errors':{}}
        sources=mini_source_status(context)
        values={'channel':'mini','source_status':{'sources':sources},'link_context':context,
                'writes_available':True,'control_available':{},'errors':{},'packed_words':{}}
        for channel in (3,4):
            active=sources[channel-3]=='line'
            raw=getattr(self,'mini_gain_'+str(channel),0)
            values['gain'+str(channel)+'_raw']=raw if active else None
            values['gain'+str(channel)+'_db']=raw/256 if active else None
            values['control_available']['gain'+str(channel)]=active
            for name in ('phase','pad'):
                values[name+str(channel)]=getattr(self,'mini_'+name+'_'+str(channel),0) if active else None
                values['control_available'][name+str(channel)]=active
        return values
    def step_mini_gain(self,channel,direction):
        name='mini_gain_'+str(channel)
        target=max(0,min(12*256,getattr(self,name,0)+direction*256));setattr(self,name,target);return target
    def write_mini_switch(self,channel,name,value):
        setattr(self,'mini_'+name+'_'+str(channel),int(value));return int(value)
    def front_snapshot(self):
        context = {'raw': {'force_rear': getattr(self, 'force_rear', 3), 'detect_status': getattr(self, 'detect_status', 0x31)}}
        sources = front_source_status(context)['sources']
        switches = {control+str(index+1): getattr(self, 'front_'+control+'_'+kind+'_'+str(index+1), 0)
                    if kind in ('line','mic') else None
                    for index,kind in enumerate(sources) for control in ('phase','hpf','pad')}
        gains = {'gain'+str(index+1): getattr(self, 'front_gain_'+kind+'_'+str(index+1), 0)
                 if kind in ('line','mic') else None for index,kind in enumerate(sources)}
        return {**switches, **gains,
                **{'instrument'+str(index+1): getattr(self, 'front_instrument_'+str(index+1), 0) if kind=='line' else None for index,kind in enumerate(sources)}, 'source_status': front_source_status(context), 'link_context': context,
                'channel': 'front', 'line': getattr(self, 'front_line_link', 0),
                'mic': getattr(self, 'front_mic_link', 0), 'errors': {}, 'writes_available': True}
    def step_front_gain(self, channel, kind, direction):
        name = 'front_gain_'+kind+'_'+str(channel)
        value = max(0,min(55,getattr(self,name,0)+direction))
        setattr(self,name,value)
        return value
    def write_front_phase(self, channel, kind, value):
        setattr(self, 'front_phase_'+kind+'_'+str(channel), int(value))
        return int(value)
    def write_front_hpf(self, channel, kind, value):
        setattr(self, 'front_hpf_'+kind+'_'+str(channel), int(value))
        return int(value)
    def write_front_pad(self, channel, kind, value):
        setattr(self, 'front_pad_'+kind+'_'+str(channel), int(value))
        return int(value)
    def write_front_instrument(self, channel, value):
        setattr(self, 'front_instrument_'+str(channel), int(value))
        return int(value)
    def write_front_link(self, kind, value):
        setattr(self, 'front_'+kind+'_link', int(value))
        return int(value)
    def input_snapshot(self, channel):
        left = ((channel-1)//2)*2+1
        context=self.front_snapshot()['link_context']
        bank=input_link_bank(channel,context)
        bits = [self.inputs[left]['link'], self.inputs[left+1]['link']] if bank=='rear' else [self.front_snapshot()[bank]]*2
        return {'channel': channel, 'link_bank':bank, **self.inputs[channel], 'writes_available': True,
                'link_context': {'raw': {'force_rear': getattr(self, 'force_rear', 0)}, 'errors': {}},
                'pair': [left, left+1], 'link_bits': bits, 'link_mixed': bits[0] != bits[1],
                'link': bits[0] if bits[0] == bits[1] else None,
                'control_available': {'phase': True, 'hpf': True, 'pad': True, 'gain': True, 'link': True}, 'errors': {},
                'gain_signed': self.inputs[channel]['gain_raw'], 'gain_db': self.inputs[channel]['gain_raw']/256}
    def set_rear_pair_source(self, channel, force):
        self.force_rear = (getattr(self, 'force_rear', 3) & ~(3 << (((channel-1)//2)*2))) | ((3 if force else 0) << (((channel-1)//2)*2))
        return int(force)
    def write_input_bool(self, channel, name, value):
        self.inputs[channel][name] = int(value)
        return int(value)
    def step_input_gain(self, channel, direction):
        value = max(0, min(3072, self.inputs[channel]['gain_raw']+direction*256))
        self.inputs[channel]['gain_raw'] = value
        return value
    def write_input_link(self, channel, value):
        bank=input_link_bank(channel,self.front_snapshot()['link_context'])
        if bank!='rear':return self.write_front_link(bank,value)
        left = ((channel-1)//2)*2+1
        self.inputs[left]['link'] = self.inputs[left+1]['link'] = int(value)
        return int(value)
    def open(self): pass
    def close(self): pass
    def write_mixer_inclusion(self,bus,source,stereo,value,*,expected_mono,expected_stereo):
        AF16Rig.validate_mix_channel(bus,source)
        if type(stereo) is not bool or type(value) is not bool:raise ValueError('Invalid inclusion flags')
        mono=getattr(self,bus+'_show',65535);pairs=getattr(self,bus+'_stereo',0)
        if (mono,pairs)!=(expected_mono,expected_stereo):raise DeviceError('Selection changed externally')
        index=source-1;pair=index//2
        if (stereo and mono & (3<<(pair*2))) or (not stereo and pairs & (1<<pair)):
            raise DeviceError('Remove the conflicting selection first')
        attr=bus+('_stereo' if stereo else '_show');before=pairs if stereo else mono;bit=pair if stereo else index
        setattr(self,attr,before|(1<<bit) if value else before&~(1<<bit))
        return int(value)

    def write_output_route(self, destination, source_code, *, expected_source):
        from routing_labels import SOURCE_LABELS, DESTINATION_LABELS
        if (type(destination) is not int or destination not in DESTINATION_LABELS or
                type(source_code) is not int or source_code not in SOURCE_LABELS or
                type(expected_source) is not int or expected_source not in SOURCE_LABELS):
            raise ValueError('Only mapped routes can be edited')
        if self.read('output_source', destination) != expected_source:
            raise DeviceError('Routing changed externally. Read routing again.')
        if not hasattr(self,'output_routes'): self.output_routes={}
        self.output_routes[destination]=source_code
        return source_code

    def read(self, name, index=0):
        if name in ROUTING_FIELDS:
            validate_index(name, index)
            if name == 'output_source': return getattr(self,'output_routes',{}).get(index,128+index%32)
            return 0
        return self.values[name]
    def write_bool(self, name, value):
        if name not in BOOLEAN_CONTROLS or type(value) is not bool:
            raise ValueError('Invalid demo control')
        self.values[name] = int(value)
        return int(value)
    def step_volume(self, direction):
        current = struct.unpack('<h', struct.pack('<H', self.values['speaker_level']))[0]
        value = max(VOLUME_MIN_RAW, min(VOLUME_MAX_RAW, current + direction * VOLUME_UNITS_PER_DB))
        self.values['speaker_level'] = value & 0xffff
        return value
    def snapshot(self):
        signed = struct.unpack('<h', struct.pack('<H', self.values['speaker_level']))[0]
        return {**self.values, 'speaker_level_signed': signed, 'speaker_level_db': signed / VOLUME_UNITS_PER_DB, 'writes_available': True}
