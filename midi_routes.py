"""Native MIDI source routing: DIN / host source flags indexed by destination."""
import ctypes as C
import time
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected

OPTIONS={'din1_source':('None','DIN','USB Host','USB Host + DIN'),
         'din2_source':('None','DIN','USB Host','USB Host + DIN'),
         'sync_source':('None','DIN','USB Host'),'host_source':('None','DIN')}
DESTINATIONS={'din1_source':5,'din2_source':6,'sync_source':7,'host_source':4}
LABELS={'din1_source':'DIN 1 output source','din2_source':'DIN 2 output source',
        'sync_source':'Sync output source','host_source':'USB Host output source'}

def read_bit(device,parameter,index):
    if device.version!=18:raise DeviceError('MIDI routing requires state version 18')
    if isinstance(device,DemoAF16Rig):return getattr(device,'midi_route_bits',{}).get((parameter,index),0)
    if not device.handle:raise DeviceDisconnected('MIDI routing: device disconnected')
    data=(C.c_ubyte*2)()
    rc=device.lib.libusb_control_transfer(device.handle,0xc0,0x91,parameter,index,data,2,1000)
    if rc==-4:raise DeviceDisconnected('MIDI routing: device disconnected')
    if rc!=2:raise DeviceError(f'MIDI route {parameter}[{index}]: expected 2 bytes, received {rc}')
    return int.from_bytes(data,'little')

def read_route(device,field):
    if field not in OPTIONS:raise ValueError('Unsupported MIDI route')
    index=DESTINATIONS[field]
    with nullcontext() if isinstance(device,DemoAF16Rig) else device.lock:
        reads=[[read_bit(device,p,index) for p in (13,12)] for _ in range(2)]
    bits=reads[-1];known=all(type(v) is int and v in (0,1) for v in bits)
    raw=bits[0]+2*bits[1] if known else 65535
    return dict(raw=raw,bits=bits,reads=reads,stable=reads[0]==reads[1])

def set_route(device,field,target,expected):
    from midi_ports import snapshot
    device.last_write=None
    if field not in OPTIONS or any(type(v) is not int or not 0<=v<len(OPTIONS[field]) for v in (target,expected)):
        raise ValueError('Read a supported MIDI route before applying')
    demo=isinstance(device,DemoAF16Rig);changed=0
    with nullcontext() if demo else device.lock:
        current=read_route(device,field)
        if not current['stable'] or current['raw']!=expected:raise DeviceError('MIDI route changed externally; refresh before applying')
        state=current['bits'][:];wanted=[target&1,target>>1];index=DESTINATIONS[field]
        device.last_write=dict(control=field,previous=expected,requested=target,confirmed=False,writes=[])
        try:
            for member,param in enumerate((13,12)):
                if state[member]==wanted[member]:continue
                fresh=read_route(device,field)
                if not fresh['stable'] or fresh['bits']!=state:raise DeviceError('MIDI route changed during apply')
                if demo:
                    if not hasattr(device,'midi_route_bits'):device.midi_route_bits={}
                    device.midi_route_bits[param,index]=wanted[member];rc=2
                else:
                    data=(C.c_ubyte*2).from_buffer_copy(wanted[member].to_bytes(2,'little'))
                    rc=device.lib.libusb_control_transfer(device.handle,0x40,0x11,param,index,data,2,1000)
                attempt=dict(parameter=param,index=index,value=wanted[member],out_result=rc,confirmed=False)
                device.last_write['writes'].append(attempt)
                if rc==-4:raise DeviceDisconnected('MIDI routing: device disconnected; route may be partially changed')
                next_state=state[:];next_state[member]=wanted[member]
                for delay in (0,.05,.1,.2,.4):
                    if delay and not demo:time.sleep(delay)
                    try:actual=read_route(device,field)
                    except DeviceDisconnected:raise
                    except DeviceError:continue
                    if actual['stable'] and actual['bits']==next_state:
                        attempt['confirmed']=True;state=next_state;changed+=1;break
                else:raise DeviceError(f'MIDI route not confirmed (OUT returned {rc})')
            result=snapshot(device)
            if not result[field]['stable'] or result[field]['raw']!=target:raise DeviceError('Final MIDI route readback changed')
            device.last_write['confirmed']=True
            return result
        except DeviceDisconnected:raise
        except DeviceError as error:
            raise DeviceError(f'{error}. {changed} route component(s) confirmed; route may be partially changed. Refresh before another edit.') from error
