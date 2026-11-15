"""Read-only AF16Rig meter frame, recovered from AFCC's native consumer.

Request C0, value/index zero, 236 bytes (118 little-endian unsigned words).
AFCC normalizes each word by 32767.
"""
import ctypes as C
import math
import struct
import time
from af16rig import DeviceError,DeviceDisconnected,VALIDATED_STATE_VERSION
FRAME_BYTES=236

def decode_frame(data):
    if len(data)!=FRAME_BYTES:raise DeviceError(f'Meters: expected {FRAME_BYTES} bytes, got {len(data)}')
    raw=struct.unpack('<118H',data)
    values=[v/32767 for v in raw]
    return dict(inputs=values[:32],outputs=values[32:40],speakers=values[40:42],
                phones=values[42:44],adat_outputs=values[44:60],main=values[60:62],
                aux=values[62:66],cue=values[66:68],usb=values[68:100],
                loopback=values[100:102],immersive=values[102:118],raw=list(raw))

def read_frame(device):
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Meters: disconnected')
        if device.version!=VALIDATED_STATE_VERSION:raise DeviceError('Meters: unsupported state version')
        data=(C.c_ubyte*FRAME_BYTES)()
        rc=device.lib.libusb_control_transfer(device.handle,0xC0,0xC0,0,0,data,FRAME_BYTES,20)
        if rc==-4:raise DeviceDisconnected('Meters: device disconnected')
        if rc<0:raise DeviceError('Meters: '+device.error(rc))
        return decode_frame(bytes(data[:rc]))

def demo_frame(now=None):
    t=time.monotonic() if now is None else now
    return decode_frame(struct.pack('<118H',*[round(32767*10**((-24+20*math.sin(t*1.7+i*.6))/20)) for i in range(118)]))

def meter_db(value):
    return -60.0 if value<=0 else max(-60.0,min(0.0,20*math.log10(value)))

class Ballistics:
    """Fast attack, 24 dB/s fall, one-second peak hold; stale data is blank."""
    def __init__(self):self.levels=[];self.peaks=[];self.holds=[];self.sample_time=None;self.last_tick=None
    def feed(self,values,now):
        db=[meter_db(v) for v in values]
        if len(db)!=len(self.levels):
            self.levels=[-60.]*len(db);self.peaks=[-60.]*len(db);self.holds=[now]*len(db)
        self.sample_time=now
        self.tick(now)
        for i,v in enumerate(db):
            self.levels[i]=max(v,self.levels[i])
            if v>=self.peaks[i]:self.peaks[i]=v;self.holds[i]=now+1
    def tick(self,now):
        dt=0 if self.last_tick is None else max(0,now-self.last_tick)
        self.last_tick=now
        if self.sample_time is None or now-self.sample_time>.5:return None
        self.levels=[max(-60,v-24*dt) for v in self.levels]
        self.peaks=[max(self.levels[i],v-24*dt) if now>self.holds[i] else v for i,v in enumerate(self.peaks)]
        return self.levels,self.peaks
