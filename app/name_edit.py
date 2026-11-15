"""Bounded, explicit hardware channel rename with stale-value protection."""
import ctypes as C
import time
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from channel_names import read_one,name_parameter,source_label
MAX_NAME_BYTES=15  # Conservative app limit; not a claim about the firmware maximum.

def encode_name(name):
    if not isinstance(name,str) or any(not c.isprintable() for c in name):
        raise ValueError('Use printable text without line breaks or control characters')
    data=name.encode('utf-8')
    if len(data)>MAX_NAME_BYTES:raise ValueError('Name exceeds this build’s 15-byte UTF-8 limit')
    return data+b'\0'

def read_name(device,source):
    parameter=name_parameter(source)
    if isinstance(device,DemoAF16Rig):
        return dict(source=source,parameter=parameter,candidate=getattr(device,'channel_names',{}).get(source,f'Demo input {source}' if source<=16 else f'Demo ADAT {source-16}' if source<=32 else f'Demo out {source-64}'),
                    status='demo',passes=[],write_requests=0)
    return read_one(device,source)

def confirmed_text(record,demo=False):
    if demo and record.get('status')=='demo':return record['candidate']
    if record.get('status') not in ('candidate','blank') or record.get('encoding')!='packed UTF-8':
        raise DeviceError('A stable packed-text read is required before renaming. Refresh names.')
    return record['candidate']

def rename(device,source,name,expected):
    payload=encode_name(name)
    parameter=name_parameter(source)
    if not isinstance(expected,str):raise ValueError('Expected current name is required')
    if device.version!=18:raise DeviceError('Unsupported state version for name editing')
    demo=isinstance(device,DemoAF16Rig)
    before=read_name(device,source)
    if confirmed_text(before,demo)!=expected:raise DeviceError('Name changed on the device. Refresh names before saving.')
    if name==expected:return before
    if demo:
        if not hasattr(device,'channel_names'):device.channel_names={}
        device.channel_names[source]=name
        return read_name(device,source)
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Device disconnected before rename')
        data=(C.c_ubyte*len(payload)).from_buffer_copy(payload)
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x1a,parameter,0,data,len(payload),1000)
        if rc==-4:raise DeviceDisconnected('Device disconnected during rename; refresh names after reconnecting')
    # Never repeat an uncertain OUT. Readback can establish success even if OUT timed out.
    last=''
    for delay in (.05,.1,.2):
        time.sleep(delay)
        result=read_name(device,source)
        try:
            if confirmed_text(result)==name:
                result['write_requests']=1;result['rename_confirmed']=True
                return result
        except DeviceError as error:last=str(error)
    raise DeviceError(f'Rename not confirmed (OUT returned {rc}). Refresh names to inspect the actual name. '+last)
