"""AFCC TrimPhones signed Q8 readback and checked level writes."""
import math
from contextlib import nullcontext

def set_level(device, db, expected_raw):
    from af16rig import DemoAF16Rig, DeviceError
    if type(db) not in (int,float) or not math.isfinite(db) or not -60 <= db <= 0:
        raise ValueError('Phones level must be between -60 and 0 dB')
    if type(expected_raw) is not int or not 0 <= expected_raw <= 65535:
        raise ValueError('Invalid expected Phones level')
    target=round(db*256)
    demo=isinstance(device,DemoAF16Rig)
    with nullcontext() if demo else device.lock:
        device.last_write=None
        if device.version!=18:raise DeviceError('Unsupported Phones state version')
        current=device.headphones_snapshot()['knob_raw'] if demo else device.read('phones_knob')
        if current!=expected_raw:raise DeviceError('Phones level changed on device. Read again before adjusting.')
        value,_=decode_level(current)
        if value is None or not -60<=value<=0:
            raise DeviceError('Phones readback outside supported adjustment range')
        if current==(target&65535):return target
        if demo:device.phones_knob=target&65535
        else:device._write_and_confirm('phones_knob',target&65535,phones_checked=True)
        return target

def decode_level(raw):
    """Return signed Q8 dB and text; 0x8000 is the minus-infinity code.

    Preserve the actual value rather than claiming a calibrated hardware range.
    ValueControl clamps drawing to its visible scale; the text stays exact.
    """
    if type(raw) is not int or not 0 <= raw <= 65535:
        return None, '—'
    if raw == 32768:
        # Use a finite bottom-of-scale position for the read-only fader.
        return -128.0, '−∞ dB'
    signed = raw - 65536 if raw >= 32768 else raw
    db = signed / 256.0
    return db, f'{db:.2f} dB'
