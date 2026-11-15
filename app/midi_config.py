"""Native MIDI assignment reads and guarded channel/number remapping."""
import time
import ctypes as C
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected

MESSAGE_TYPES=('CC','Note','Off')

STRIP_CONTROLS=('Fader','Pan','Mute','Solo','Aux 1','Aux 2','Aux 3','Aux 4')
MASTER_CONTROLS=('Master fader','Master Aux 1','Master Aux 2','Master Aux 3','Master Aux 4','Next bank','Previous bank')
FIELDS=tuple([(18,0),(19,0)]+[(p,i) for i in range(8) for p in range(20,28)]+[(p,0) for p in range(28,35)])

def validate(parameter,index):
    if type(parameter) is not int or type(index) is not int or (parameter,index) not in FIELDS:
        raise ValueError('Unsupported MIDI assignment register')

def decode(parameter,index,raw):
    validate(parameter,index)
    if type(raw) is not int or not 0<=raw<=65535:raise ValueError('Invalid MIDI register word')
    result=dict(parameter=parameter,index=index,raw=raw)
    if parameter<20:
        result.update(control='Channels per bank' if parameter==18 else 'Bank index',strip=None,value=raw)
    else:
        result.update(control=STRIP_CONTROLS[parameter-20] if parameter<28 else MASTER_CONTROLS[parameter-28],
            strip=index+1 if parameter<28 else None,channel_code=(raw>>8)&15,
            type_code=(raw>>14)&3,number_code=raw&255,reserved_bits=raw&0x3000)
    return result

def read_word(device,parameter,index):
    validate(parameter,index)
    if device.version!=18:raise DeviceError('MIDI configuration requires state version 18')
    if isinstance(device,DemoAF16Rig):
        # Synthetic Note assignments for demo mode.
        default=8 if parameter==18 else 0 if parameter==19 else 0x4000+(index<<8)+(parameter-20)
        return getattr(device,'midi_assignments',{}).get((parameter,index),default)
    if not device.handle:raise DeviceDisconnected('MIDI configuration: device disconnected')
    data=(C.c_ubyte*2)()
    rc=device.lib.libusb_control_transfer(device.handle,0xc0,0x93,parameter,index,data,2,1000)
    if rc==-4:raise DeviceDisconnected('MIDI configuration: device disconnected')
    if rc!=2:raise DeviceError(f'MIDI parameter {parameter}[{index}]: expected 2 bytes, received {rc}')
    return int.from_bytes(data,'little')

def read_entry(device,parameter,index):
    validate(parameter,index)
    lock=nullcontext() if isinstance(device,DemoAF16Rig) else device.lock
    with lock:
        values=[read_word(device,parameter,index),read_word(device,parameter,index)]
    record=decode(parameter,index,values[-1])
    record.update(reads=values,stable=values[0]==values[1],demo=isinstance(device,DemoAF16Rig))
    return record


def editable(record):
    return (record.get('stable') is True and type(record.get('parameter')) is int
            and 20<=record['parameter']<=34 and type(record.get('raw')) is int
            and 0<=record['raw']<=65535 and not record['raw']&0x3000
            and record['raw']>>14!=3 and record['raw']&255<=127)

def remap(device,parameter,index,channel,number,expected,message_type=None):
    """Edit channel/number and optional verified type; send OUT at most once."""
    device.last_write=None
    validate(parameter,index)
    if not editable(dict(parameter=parameter,raw=expected,stable=True)):
        raise ValueError('Assignment encoding is not supported for editing')
    if type(channel) is not int or not 1<=channel<=16 or type(number) is not int or not 0<=number<=127:
        raise ValueError('MIDI channel 1–16 and number 0–127 required')
    if device.version!=18:raise DeviceError('MIDI configuration requires state version 18')
    if message_type is not None and (type(message_type) is not int or message_type not in range(3)):
        raise ValueError('MIDI type must be CC, Note or Off')
    type_bits=expected&0xc000 if message_type is None else message_type<<14
    target=type_bits|((channel-1)<<8)|number
    lock=nullcontext() if isinstance(device,DemoAF16Rig) else device.lock
    with lock:
        device.last_write=None
        current=read_entry(device,parameter,index)
        if not current['stable'] or current['raw']!=expected:
            raise DeviceError('MIDI assignment changed externally; refresh before applying')
        if target==expected:return current
        if isinstance(device,DemoAF16Rig):
            if not hasattr(device,'midi_assignments'):device.midi_assignments={}
            device.midi_assignments[parameter,index]=target
            return read_entry(device,parameter,index)
        if not device.handle:raise DeviceDisconnected('MIDI configuration: device disconnected')
        data=(C.c_ubyte*2).from_buffer_copy(target.to_bytes(2,'little'))
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x13,parameter,index,data,2,1000)
        device.last_write=dict(control='midi_assignment',parameter=parameter,element_index=index,
            previous=expected,requested=target,out_result=rc,confirmed=False,readback_attempts=[])
        if rc==-4:raise DeviceDisconnected('MIDI assignment write: device disconnected')
        for delay in (.05,.10,.20,.40):
            time.sleep(delay)
            try:
                actual=read_entry(device,parameter,index)
                device.last_write['readback_attempts'].append(dict(actual=actual['raw'],stable=actual['stable']))
                if actual['stable'] and actual['raw']==target:
                    device.last_write['confirmed']=True;return actual
            except DeviceDisconnected:raise
            except DeviceError as error:device.last_write['readback_attempts'].append(dict(error=str(error)))
        raise DeviceError(f'MIDI assignment change not confirmed (OUT returned {rc}); refresh before another edit')


def set_bank_size(device,target,expected):
    """Set native channels-per-bank (1..8), with one OUT and confirmed readback."""
    device.last_write=None
    if any(type(v) is not int or not 1<=v<=8 for v in (target,expected)):
        raise ValueError('MIDI channels per bank must be 1–8')
    if device.version!=18:raise DeviceError('MIDI configuration requires state version 18')
    lock=nullcontext() if isinstance(device,DemoAF16Rig) else device.lock
    with lock:
        device.last_write=None
        current=read_entry(device,18,0)
        if not current['stable'] or current['raw']!=expected:
            raise DeviceError('MIDI bank size changed externally; refresh before applying')
        if target==expected:return current
        if isinstance(device,DemoAF16Rig):
            if not hasattr(device,'midi_assignments'):device.midi_assignments={}
            device.midi_assignments[18,0]=target
            return read_entry(device,18,0)
        if not device.handle:raise DeviceDisconnected('MIDI configuration: device disconnected')
        data=(C.c_ubyte*2).from_buffer_copy(target.to_bytes(2,'little'))
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x13,18,0,data,2,1000)
        device.last_write=dict(control='midi_bank_size',parameter=18,element_index=0,
            previous=expected,requested=target,out_result=rc,confirmed=False,readback_attempts=[])
        if rc==-4:raise DeviceDisconnected('MIDI bank size write: device disconnected')
        for delay in (.05,.10,.20,.40):
            time.sleep(delay)
            try:
                actual=read_entry(device,18,0)
                device.last_write['readback_attempts'].append(dict(actual=actual['raw'],stable=actual['stable']))
                if actual['stable'] and actual['raw']==target:
                    device.last_write['confirmed']=True;return actual
            except DeviceDisconnected:raise
            except DeviceError as error:device.last_write['readback_attempts'].append(dict(error=str(error)))
        raise DeviceError(f'MIDI bank size change not confirmed (OUT returned {rc}); refresh before another edit')
