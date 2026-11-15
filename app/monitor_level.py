"""Absolute monitor target through the existing verified speaker register."""
import math
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,VOLUME_MIN_RAW,VOLUME_MAX_RAW,VOLUME_UNITS_PER_DB

def set_level(device,db):
    if isinstance(db,bool) or not isinstance(db,(int,float)) or not math.isfinite(db):raise ValueError('Invalid monitor level')
    raw=round(db*VOLUME_UNITS_PER_DB)
    if not VOLUME_MIN_RAW<=raw<=VOLUME_MAX_RAW:raise ValueError('Monitor level outside supported range')
    with nullcontext() if isinstance(device,DemoAF16Rig) else device.lock:
        if device.version!=18:raise DeviceError('Unsupported monitor state version')
        current=device.snapshot()['speaker_level_signed']
        if not VOLUME_MIN_RAW<=current<=VOLUME_MAX_RAW:raise DeviceError('Monitor readback outside supported range')
        if current==raw:return current
        if isinstance(device,DemoAF16Rig):device.values['speaker_level']=raw&65535
        else:device._write_and_confirm('speaker_level',raw&65535)
        return raw
