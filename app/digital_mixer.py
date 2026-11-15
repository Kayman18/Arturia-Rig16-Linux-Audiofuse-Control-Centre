"""Digital-source facade over the existing guarded mono/stereo mixer logic.

Selection and switch reads assemble packed words; writes always address a
single bit. Indexed levels/pans address native inputs 16..63. Analog stays on
its existing driver. No USB OUT is retried.
"""
import ctypes as C
import time
import threading
from af16rig import AF16Rig, DemoAF16Rig, PARAMETERS, DeviceError, DeviceDisconnected
from mixer_membership import masks

PACKED = {f'{b}_channel_{f}': (2 if f == 'stereo' else 4)
          for b in ('main', 'cue') for f in ('show', 'stereo', 'mute', 'solo')}
PACKED.update({f'main_channel_send{a}': 4 for a in range(1, 5)})
INDEXED = {f'{b}_channel_{f}' for b in ('main', 'cue') for f in ('level', 'pan')}
INDEXED.update(f'aux{a}_send_level' for a in range(1, 5))
WRITABLE_BITS = set(PACKED) - {f'{b}_channel_{f}' for b in ('main', 'cue') for f in ('show', 'stereo')}


def mixer_device(device, source):
    return DigitalMixer(device) if type(source) is int and 17 <= source <= 64 else device


class DigitalMixer(AF16Rig):
    def __init__(self, device):
        self.device = device
        if isinstance(device, DemoAF16Rig) and not hasattr(device, 'lock'):
            device.lock = threading.RLock()
        self.lock = device.lock
        self.version = device.version

    @property
    def last_write(self): return self.device.last_write
    @last_write.setter
    def last_write(self, value): self.device.last_write = value

    @staticmethod
    def validate_mix_channel(bus, source):
        if bus not in ('main', 'cue') or type(source) is not int or not 17 <= source <= 64:
            raise ValueError('Digital Main/Cue source 17–64 required')

    def _word(self, name, index):
        d = self.device
        if not d.handle: raise DeviceDisconnected('Digital mixer disconnected')
        data = (C.c_ubyte * 2)()
        group, parameter = PARAMETERS[name]
        rc = d.lib.libusb_control_transfer(d.handle, 0xc0, 0x90 + group, parameter, index, data, 2, 1000)
        if rc == -4: raise DeviceDisconnected('Digital mixer disconnected')
        if rc != 2: raise DeviceError(f'{name}: read returned {rc} bytes; expected 2')
        return int.from_bytes(data, 'little')

    def read(self, name, index=0):
        if name not in PACKED and name not in INDEXED: raise ValueError('Unsupported digital mixer field')
        if name in PACKED and index != 0: raise ValueError('Packed masks use the assembled read API')
        if name in INDEXED and (type(index) is not int or not 16 <= index < 64): raise ValueError('Invalid digital channel index')
        with self.lock:
            if isinstance(self.device, DemoAF16Rig):
                if name.endswith(('_show', '_stereo')):
                    return masks(self.device, name.split('_')[0])[int(name.endswith('_stereo'))]
                values = getattr(self.device, 'digital_values', {})
                return values.get((name, index), 127 if name.endswith('_pan') else (-60*256)&65535 if '_send_level' in name else 0)
            if name in PACKED:
                return sum(self._word(name, word) << (16*word) for word in range(PACKED[name]))
            return self._word(name, index)

    def read_input_bit(self, name, bit_index):
        if name not in WRITABLE_BITS or type(bit_index) is not int or not 16 <= bit_index < 64:
            raise ValueError('Invalid digital mixer flag')
        return (self.read(name) >> bit_index) & 1

    def _write_and_confirm(self, name, word, index=0, **unused):
        if self.version != 18: raise DeviceError('Unsupported mixer state version')
        if type(index) is not int or not 16 <= index < 64: raise ValueError('Invalid digital write index')
        if name in WRITABLE_BITS:
            if type(word) is not int or word not in (0, 1): raise ValueError('Invalid digital switch value')
        elif name in INDEXED:
            if type(word) is not int or not 0 <= word <= 65535: raise ValueError('Invalid digital level/pan word')
        else: raise ValueError('Unsupported digital write field')
        d = self.device
        if isinstance(d, DemoAF16Rig):
            if not hasattr(d, 'digital_values'): d.digital_values = {}
            if name in WRITABLE_BITS:
                current = self.read(name)
                d.digital_values[name, 0] = (current | (1 << index)) if word else (current & ~(1 << index))
            else: d.digital_values[name, index] = word
            self.last_write = dict(control=name, element_index=index, confirmed=True, demo=True)
            return word
        if not d.handle: raise DeviceDisconnected('Digital mixer disconnected')
        group, parameter = PARAMETERS[name]
        data = (C.c_ubyte * 2)(word & 255, word >> 8)
        rc = d.lib.libusb_control_transfer(d.handle, 0x40, 0x10+group, parameter, index, data, 2, 1000)
        self.last_write = dict(control=name, element_index=index, requested=word,
                               out_result=rc, confirmed=False, readback_attempts=[])
        if rc == -4: raise DeviceDisconnected('Digital mixer disconnected during write')
        for delay in (.05, .1, .2, .4):
            time.sleep(delay)
            try:
                actual = self.read_input_bit(name, index) if name in WRITABLE_BITS else self.read(name, index)
            except DeviceDisconnected: raise
            except DeviceError as error:
                self.last_write['readback_attempts'].append(dict(error=str(error)))
                continue
            self.last_write['readback_attempts'].append(dict(actual=actual))
            if actual == word:
                self.last_write['confirmed'] = True
                return actual
        raise DeviceError(f'{name}: digital change not confirmed (OUT returned {rc}); refresh device state')
