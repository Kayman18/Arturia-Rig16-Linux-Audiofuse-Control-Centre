"""Exact signed-Q8 speaker B trim through the established native register."""
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError

def read(device):
    raw=device.monitor_settings_snapshot()['ab_trim_raw'] if isinstance(device,DemoAF16Rig) else device.read('ab_trim')
    if type(raw) is not int or not 0<=raw<=65535:raise DeviceError('Invalid B trim readback')
    return raw-65536 if raw>=32768 else raw

def set_raw(device,target,expected):
    if any(type(v) is not int or not -3072<=v<=3072 for v in (target,expected)):
        raise ValueError('B trim must be within −12 to +12 dB')
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported state version for B trim')
        if read(device)!=expected:raise DeviceError('B trim changed on device; read again')
        if target==expected:return target
        if isinstance(device,DemoAF16Rig):device.ab_trim=target
        else:device._write_and_confirm('ab_trim',target&65535)
        if read(device)!=target:raise DeviceError('B trim not confirmed; no retry performed')
        return target
