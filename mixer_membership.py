"""64-input Main/Cue inclusion with bounded full-mask readback.

Native mask descriptors: mono four words, stereo two words. Reads index
words; writes index individual bits. Never write an assembled mask.
"""
import ctypes as C
import time
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected

BANKS={'Analog':(0,16),'ADAT':(16,16),'USB':(32,32)}


def source_id(bank,number):
    if bank not in BANKS or type(number) is not int or not 1<=number<=BANKS[bank][1]:raise ValueError('Invalid mixer source')
    return BANKS[bank][0]+number


def validate(device,bus,source):
    if bus not in ('main','cue') or type(source) is not int or not 1<=source<=64:raise ValueError('Main/Cue source 1–64 required')
    if device.version!=18:raise DeviceError('Unsupported mixer state version')


def masks(device,bus):
    validate(device,bus,1)
    if isinstance(device,DemoAF16Rig):
        high=getattr(device,'digital_selection',{}).get(bus,(0,0))
        return ((getattr(device,bus+'_show',65535)&65535)|high[0],(getattr(device,bus+'_stereo',0)&255)|high[1])
    values=[]
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Device disconnected during mixer selection read')
        for parameter,count in (((34,4),(35,2)) if bus=='main' else ((48,4),(49,2))):
            value=0
            for index in range(count):
                data=(C.c_ubyte*2)()
                rc=device.lib.libusb_control_transfer(device.handle,0xc0,0x91,parameter,index,data,2,1000)
                if rc==-4:raise DeviceDisconnected('Device disconnected during mixer selection read')
                if rc!=2:raise DeviceError(f'Mixer selection read returned {rc} bytes; expected 2')
                value|=int.from_bytes(data,'little')<<(16*index)
            values.append(value)
    return tuple(values)


def snapshot(device,bus,source):
    validate(device,bus,source)
    first=masks(device,bus);second=masks(device,bus)
    if first!=second:raise DeviceError('Mixer selection changed during read; wait for a stable snapshot')
    return dict(channel='mixer_sources',bus=bus,source=source,raw=dict(show=second[0],stereo=second[1]))


def change(device,bus,source,stereo,value,expected_mono,expected_stereo):
    validate(device,bus,source)
    if type(stereo) is not bool or type(value) is not bool:raise ValueError('Selection flags must be boolean')
    if type(expected_mono) is not int or not 0<=expected_mono<1<<64 or type(expected_stereo) is not int or not 0<=expected_stereo<1<<32:raise ValueError('Invalid expected masks')
    before=snapshot(device,bus,source)['raw'];mono,pairs=before['show'],before['stereo']
    if (mono,pairs)!=(expected_mono,expected_stereo):raise DeviceError('Mixer selection changed externally. Refresh before applying.')
    index=source-1;pair=index//2
    if stereo and mono&(3<<(pair*2)):raise DeviceError('Remove both mono members before editing this stereo pair')
    if not stereo and pairs&(1<<pair):raise DeviceError('Remove the stereo pair before editing a mono member')
    bit=pair if stereo else index;old=pairs if stereo else mono
    if bool(old&(1<<bit))==value:return snapshot(device,bus,source)
    target=(old|(1<<bit)) if value else (old&~(1<<bit))
    wanted=(mono,target) if stereo else (target,pairs)
    if isinstance(device,DemoAF16Rig):
        setattr(device,bus+'_show',wanted[0]&65535);setattr(device,bus+'_stereo',wanted[1]&255)
        if not hasattr(device,'digital_selection'):device.digital_selection={}
        device.digital_selection[bus]=(wanted[0]&~65535,wanted[1]&~255)
        return snapshot(device,bus,source)
    parameter=(35 if stereo else 34) if bus=='main' else (49 if stereo else 48)
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Device disconnected before mixer selection write')
        data=(C.c_ubyte*2)(int(value),0)
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x11,parameter,bit,data,2,1000)
    if rc==-4:raise DeviceDisconnected('Device disconnected during mixer selection write')
    for delay in (.05,.1,.2,.4):
        time.sleep(delay)
        try:result=snapshot(device,bus,source)
        except DeviceDisconnected:raise
        except DeviceError:continue
        raw=result['raw']
        if (raw['show'],raw['stereo'])==wanted:return result
    raise DeviceError(f'Mixer selection not confirmed or additional flags changed (OUT returned {rc}). Sent once; refresh and inspect sources.')
