"""Native-traced 16Rig MIDI mode, port and source settings (state group 1)."""
import ctypes as C
import time
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
import midi_routes

OPTIONS={'preferred_mode':('Standalone','Hosted'), 'host_cable':tuple(str(i) for i in range(1,17)),
         'din_clock':('4 PPQN','24 PPQN','48 PPQN','Korg'),
         'mixer_source':('Disabled','DIN','USB Host','USB Device')}
PARAMETERS={'preferred_mode':5,'host_cable':6,'din_clock':7,'mixer_source':16}
LABELS={'preferred_mode':'Preferred MIDI mode','host_cable':'USB Host Cable Number','din_clock':'DIN clock mode','mixer_source':'Mixer control source'}

SCALAR_OPTIONS=OPTIONS.copy()
OPTIONS={**OPTIONS,**midi_routes.OPTIONS}
LABELS={**LABELS,**midi_routes.LABELS}

def read_word(device,field):
    if field not in SCALAR_OPTIONS:raise ValueError('Unsupported MIDI port setting')
    if device.version!=18:raise DeviceError('MIDI port settings require state version 18')
    if isinstance(device,DemoAF16Rig):return getattr(device,'midi_ports',{}).get(field,0)
    if not device.handle:raise DeviceDisconnected('MIDI ports: device disconnected')
    data=(C.c_ubyte*2)()
    rc=device.lib.libusb_control_transfer(device.handle,0xc0,0x91,PARAMETERS[field],0,data,2,1000)
    if rc==-4:raise DeviceDisconnected('MIDI ports: device disconnected')
    if rc!=2:raise DeviceError(f'{LABELS[field]}: expected 2 bytes, received {rc}')
    return int.from_bytes(data,'little')

def snapshot(device):
    with nullcontext() if isinstance(device,DemoAF16Rig) else device.lock:
        result={}
        for field in OPTIONS:
            if field in midi_routes.OPTIONS:
                result[field]=midi_routes.read_route(device,field);continue
            reads=[read_word(device,field),read_word(device,field)]
            result[field]=dict(raw=reads[-1],stable=reads[0]==reads[1],reads=reads)
        return result

def set_option(device,field,target,expected):
    if field in midi_routes.OPTIONS:return midi_routes.set_route(device,field,target,expected)
    device.last_write=None
    if field not in OPTIONS or any(type(v) is not int or not 0<=v<len(OPTIONS[field]) for v in (target,expected)):
        raise ValueError('Read a supported MIDI setting before applying')
    demo=isinstance(device,DemoAF16Rig)
    with nullcontext() if demo else device.lock:
        current=[read_word(device,field),read_word(device,field)]
        if current!=[expected,expected]:raise DeviceError('MIDI setting changed externally; refresh before applying')
        if target==expected:return snapshot(device)
        if demo:
            if not hasattr(device,'midi_ports'):device.midi_ports={}
            device.midi_ports[field]=target
            return snapshot(device)
        data=(C.c_ubyte*2).from_buffer_copy(target.to_bytes(2,'little'))
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x11,PARAMETERS[field],0,data,2,1000)
        device.last_write=dict(control=field,requested=target,previous=expected,out_result=rc,confirmed=False,readback_attempts=[])
        if rc==-4:raise DeviceDisconnected('MIDI port write: device disconnected')
        for delay in (.05,.1,.2,.4):
            time.sleep(delay)
            try:
                actual=snapshot(device);r=actual[field]
                device.last_write['readback_attempts'].append(r)
                if r['stable'] and r['raw']==target:
                    device.last_write['confirmed']=True;return actual
            except DeviceDisconnected:raise
            except DeviceError as error:device.last_write['readback_attempts'].append(dict(error=str(error)))
        raise DeviceError(f'{LABELS[field]} change not confirmed (OUT returned {rc}); refresh before another edit')
