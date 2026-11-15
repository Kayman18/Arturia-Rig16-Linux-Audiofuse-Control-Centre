"""Exact analog-output level using the established output_gain write path."""
from af16rig import DeviceError,DemoAF16Rig
from value_entry import numeric_target
from contextlib import nullcontext

def set_level(device,channel,value,expected):
    return set_raw(device,channel,round(numeric_target(value,-60,0)*256),expected)

def set_raw(device,channel,target,expected):
    if type(channel) is not int or not 3<=channel<=10:raise ValueError('Invalid analog output')
    if type(target) is not int or not -60*256<=target<=0:raise ValueError('Invalid output target')
    if type(expected) is not int or not -60*256<=expected<=0:raise ValueError('Invalid expected output level')
    with nullcontext() if isinstance(device,DemoAF16Rig) else device.lock:
        if device.version!=18:raise DeviceError('Unsupported state version for output level')
        device.last_write=None
        state=device.output_snapshot(channel)
        if not state.get('writes_available') or state.get('level_signed')!=expected:
            raise DeviceError('Output level changed or is unavailable. Read the current level and try again.')
        if target==expected:return target
        if isinstance(device,DemoAF16Rig):setattr(device,'output_level_'+str(channel),target)
        else:device._write_and_confirm('output_gain',target & 0xffff,channel-3)
        return target
