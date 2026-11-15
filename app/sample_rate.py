"""Idle-device sample rate through ALSA; never detach the USB audio driver."""
import ctypes as C
import ctypes.util
import re
import time
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from clock_controls import RATES,CONFIG,demo_raw
from clock_status import read_register,alsa_streams

SUPPORTED=RATES[1:]

def idle_card(status):
    cards=status.get('cards',[]);streams=status.get('streams',[])
    if status.get('errors') or len(cards)!=1 or not streams:
        raise DeviceError('A single readable AF16Rig ALSA card is required')
    card=cards[0]['card']
    if not re.fullmatch(r'card[0-9]+',card):raise DeviceError('Invalid ALSA card identity')
    if any(s.get('card')!=card or s.get('state')!='Closed' for s in streams):
        raise DeviceError('AF16Rig audio is in use. Close its audio streams in your DAW/JACK/PipeWire before applying a sample rate.')
    if not any(s.get('pcm')=='pcm0p' for s in streams):raise DeviceError('AF16Rig playback PCM 0 was not found')
    return card

class AlsaRate:
    def __init__(self,library=None):
        try:self.lib=library if library is not None else C.CDLL(ctypes.util.find_library('asound') or 'libasound.so.2')
        except OSError as error:raise DeviceError('ALSA library is unavailable') from error
        ptr=C.c_void_p;uint=C.c_uint;integer=C.c_int
        signatures={
            'snd_pcm_open':([C.POINTER(ptr),C.c_char_p,integer,integer],integer),
            'snd_pcm_close':([ptr],integer),
            'snd_pcm_hw_params_malloc':([C.POINTER(ptr)],integer),
            'snd_pcm_hw_params_free':([ptr],None),
            'snd_pcm_hw_params_any':([ptr,ptr],integer),
            'snd_pcm_hw_params_set_access':([ptr,ptr,integer],integer),
            'snd_pcm_format_value':([C.c_char_p],integer),
            'snd_pcm_hw_params_set_format':([ptr,ptr,integer],integer),
            'snd_pcm_hw_params_set_rate':([ptr,ptr,uint,integer],integer),
            'snd_pcm_hw_params_get_channels_min':([ptr,C.POINTER(uint)],integer),
            'snd_pcm_hw_params_set_channels':([ptr,ptr,uint],integer),
            'snd_pcm_hw_params':([ptr,ptr],integer),
            'snd_pcm_hw_params_get_rate':([ptr,C.POINTER(uint),C.POINTER(integer)],integer),
            'snd_strerror':([integer],C.c_char_p)}
        for name,(args,result) in signatures.items():
            f=getattr(self.lib,name);f.argtypes=args;f.restype=result
    def check(self,rc,action):
        if rc<0:
            reason=self.lib.snd_strerror(rc)
            raise DeviceError(action+': '+(reason.decode(errors='replace') if reason else str(rc)))
    def apply(self,card,rate,before_apply):
        if not re.fullmatch(r'card[0-9]+',card) or type(rate) is not int or rate not in SUPPORTED:raise ValueError('Unsupported sample rate or card')
        pcm=C.c_void_p();params=C.c_void_p();lib=self.lib
        # Nonblocking raw hardware PCM: no plug conversion, no stream start or audio writes.
        self.check(lib.snd_pcm_open(C.byref(pcm),f'hw:{card[4:]},0'.encode(),0,1),'Open idle AF16Rig playback')
        try:
            self.check(lib.snd_pcm_hw_params_malloc(C.byref(params)),'Allocate ALSA parameters')
            self.check(lib.snd_pcm_hw_params_any(pcm,params),'Read hardware constraints')
            self.check(lib.snd_pcm_hw_params_set_access(pcm,params,3),'Select interleaved access')
            fmt=lib.snd_pcm_format_value(b'S32_LE');self.check(fmt,'Resolve audio format')
            self.check(lib.snd_pcm_hw_params_set_format(pcm,params,fmt),'Select audio format')
            self.check(lib.snd_pcm_hw_params_set_rate(pcm,params,rate,0),'Select exact sample rate')
            channels=C.c_uint()
            self.check(lib.snd_pcm_hw_params_get_channels_min(params,C.byref(channels)),'Read channel count')
            if not 1<=channels.value<=128:raise DeviceError('Unexpected ALSA channel count')
            self.check(lib.snd_pcm_hw_params_set_channels(pcm,params,channels.value),'Select channel count')
            before_apply()
            self.check(lib.snd_pcm_hw_params(pcm,params),'Apply sample rate')
            actual=C.c_uint();direction=C.c_int()
            self.check(lib.snd_pcm_hw_params_get_rate(params,C.byref(actual),C.byref(direction)),'Read configured sample rate')
            if actual.value!=rate or direction.value!=0:raise DeviceError('ALSA did not configure the exact requested rate')
        finally:
            if params.value:lib.snd_pcm_hw_params_free(params)
            lib.snd_pcm_close(pcm)

def set_rate(device,rate,expected,root='/proc/asound',backend=None):
    if type(rate) is not int or rate not in SUPPORTED:raise ValueError('Unsupported sample rate')
    if not isinstance(expected,dict) or type(expected.get('internal_frequency')) is not int or expected['internal_frequency'] not in range(1,7):raise ValueError('Refresh clock state before applying a rate')
    if device.version!=18:raise DeviceError('Sample-rate control requires state version 18')
    demo=isinstance(device,DemoAF16Rig)
    fields=(*CONFIG,'internal_frequency')
    def check():
        raw=demo_raw(device) if demo else {k:read_register(device,k) for k in fields}
        if any(raw.get(k)!=expected.get(k) for k in fields):raise DeviceError('Clock state changed; refresh before applying a rate')
        if raw['selected_source']!=0 or raw['preferred_source']!=0:raise DeviceError('Select Internal clock before changing sample rate')
        return raw
    device.last_write=None
    check();check()
    if RATES[expected['internal_frequency']]==rate:return rate
    if demo:
        device.clock_raw['internal_frequency']=RATES.index(rate);return rate
    card=idle_card(alsa_streams(root))
    diagnostic=dict(control='sample_rate',requested=rate,transport='ALSA hardware PCM',apply_attempts=0,confirmed=False,readback_attempts=[])
    device.last_write=diagnostic
    def before_apply():
        check()
        # Our playback handle is now open but not configured; all other streams must remain closed.
        status=alsa_streams(root)
        if idle_card(status)!=card:raise DeviceError('ALSA card changed during rate selection')
        diagnostic['apply_attempts']=1
    (backend if backend is not None else AlsaRate()).apply(card,rate,before_apply)
    for delay in (.05,.1,.2,.4):
        time.sleep(delay)
        try:
            source=read_register(device,'selected_source')
            values=[read_register(device,'internal_frequency') for _ in range(2)]
            diagnostic['readback_attempts'].append(dict(source=source,frequencies=values))
            if source==0 and values==[RATES.index(rate)]*2:
                diagnostic['confirmed']=True;return rate
        except DeviceDisconnected:raise
        except DeviceError as error:diagnostic['readback_attempts'].append(dict(error=str(error)))
    raise DeviceError('Sample-rate change was not confirmed after closing the ALSA handle. The rate may have changed; refresh before retrying.')
