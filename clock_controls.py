"""16Rig clock enums from the supplied model-specific Arturia XML."""
import ctypes as C
import time
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected

SOURCES=('Internal','ADAT','Word clock')
RATES=(None,44100,48000,88200,96000,176400,192000)
OPTIONS={'selected_source':SOURCES,'wordclock_impedance':('75 Ω','High impedance'),
         'wordclock_thru':('Disabled','Pass through'),'double_smux':('Normal','Force SMUX')}
ENUMS={**OPTIONS,'preferred_source':SOURCES}
CONFIG=tuple(ENUMS)
FREQUENCIES=('internal_frequency','adat_frequency','wordclock_frequency')
DEMO_RAW=dict(validity=7,internal_frequency=2,adat_frequency=2,wordclock_frequency=2,
              wordclock_impedance=0,wordclock_thru=0,selected_source=0,preferred_source=0,double_smux=0)

def decoded(raw):
    result={}
    for field,value in raw.items():
        if field in FREQUENCIES:
            result[field]=('Invalid' if value==0 else f'{RATES[value]:,} Hz') if type(value) is int and 0<=value<len(RATES) else f'Unknown ({value})'
        elif field in ENUMS:
            options=ENUMS[field]
            result[field]=options[value] if type(value) is int and 0<=value<len(options) else f'Unknown ({value})'
        else:result[field]=str(value)
    return result

def demo_raw(device):
    if not hasattr(device,'clock_raw'):device.clock_raw=DEMO_RAW.copy()
    return device.clock_raw.copy()

def set_option(device,field,target,expected):
    from clock_status import read_register,FIELDS
    if field not in OPTIONS or type(target) is not int or not 0<=target<len(OPTIONS[field]):
        raise ValueError('Unsupported clock option')
    if not isinstance(expected,dict) or any(type(expected.get(k)) is not int or not 0<=expected[k]<len(ENUMS[k]) for k in CONFIG):
        raise ValueError('Read supported clock settings before changing them')
    demo=isinstance(device,DemoAF16Rig)
    with nullcontext() if demo else device.lock:
        device.last_write=None
        if device.version!=18:raise DeviceError('Unsupported clock state version')
        current=demo_raw(device) if demo else {k:read_register(device,k) for k in CONFIG}
        if any(current[k]!=expected[k] for k in CONFIG):raise DeviceError('Clock settings changed. Refresh before applying.')
        if current[field]==target:return target
        if field=='selected_source' and target!=0:
            frequency=FREQUENCIES[target]
            code=current[frequency] if demo else read_register(device,frequency)
            if type(code) is not int or not 1<=code<len(RATES):
                raise DeviceError('Selected external clock has no recognized frequency. Check its connection first.')
        if demo:
            device.clock_raw[field]=target
            return target
        group,param=FIELDS[field]
        data=(C.c_ubyte*2).from_buffer_copy(target.to_bytes(2,'little'))
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x10+group,param,0,data,2,1000)
        device.last_write=dict(control=field,requested=target,out_result=rc,readback_attempts=[],confirmed=False)
        if rc==-4:raise DeviceDisconnected('Clock write: device disconnected')
        for delay in (.05,.1,.2,.4):
            time.sleep(delay)
            try:actual=read_register(device,field)
            except DeviceDisconnected:raise
            except DeviceError as error:
                device.last_write['readback_attempts'].append({'error':str(error)});continue
            device.last_write['readback_attempts'].append({'actual':actual})
            if actual==target:
                device.last_write['confirmed']=True;return actual
        raise DeviceError(f'{field}: change not confirmed (OUT returned {rc}); refresh device state')
