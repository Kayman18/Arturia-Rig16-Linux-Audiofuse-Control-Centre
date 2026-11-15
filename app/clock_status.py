"""Clock register status and separate Linux ALSA stream configuration."""
from clock_controls import decoded,demo_raw
import ctypes as C
import re
from pathlib import Path
from datetime import datetime,timezone
from af16rig import DeviceError,DeviceDisconnected,DemoAF16Rig

FIELDS={'validity':(0,9),'internal_frequency':(0,10),'adat_frequency':(0,11),
        'wordclock_frequency':(0,12),'wordclock_impedance':(1,0),
        'wordclock_thru':(1,1),'selected_source':(1,2),'preferred_source':(1,3),'double_smux':(1,4)}
LABELS={'validity':'Clock validity','internal_frequency':'Internal frequency','adat_frequency':'ADAT frequency',
        'wordclock_frequency':'Word-clock frequency','wordclock_impedance':'Word-clock impedance',
        'wordclock_thru':'Word-clock thru','selected_source':'Selected source','preferred_source':'Preferred source','double_smux':'Double SMUX'}


def text_file(path):
    with path.open('r',errors='replace') as f:return f.read(65536)


def alsa_streams(root='/proc/asound'):
    result={'cards':[],'streams':[],'errors':[]}
    root=Path(root)
    if not root.is_dir():result['errors'].append('ALSA status is unavailable on this system');return result
    for card in sorted(root.glob('card[0-9]*'))[:64]:
        if not re.fullmatch(r'card\d+',card.name):continue
        try:identity=text_file(card/'id').strip()
        except OSError:continue
        if not re.fullmatch(r'AF16Rig(?:_\d+)?',identity):continue
        result['cards'].append({'card':card.name,'id':identity})
        for pcm in sorted(card.glob('pcm*'))[:64]:
            if not re.fullmatch(r'pcm\d+[pc]',pcm.name):continue
            for sub in sorted(pcm.glob('sub[0-9]*'))[:16]:
                if not re.fullmatch(r'sub\d+',sub.name):continue
                item={'card':card.name,'pcm':pcm.name,'substream':sub.name,'direction':'Playback' if pcm.name.endswith('p') else 'Capture',
                      'rate_hz':None,'channels':None,'format':None,'state':'Unavailable'}
                try:
                    raw=text_file(sub/'hw_params');item['hw_params']=raw
                    if raw.strip()=='closed':item['state']='Closed'
                    else:
                        for key,pattern in [('rate_hz',r'^rate:\s*(\d+)'),('channels',r'^channels:\s*(\d+)'),('format',r'^format:\s*(\S+)')]:
                            match=re.search(pattern,raw,re.M)
                            if match:item[key]=match[1] if key=='format' else int(match[1])
                        item['state']='Configured'
                        try:
                            status=text_file(sub/'status');match=re.search(r'^state:\s*(\S+)',status,re.M)
                            if match:item['state']=match[1]
                        except OSError:pass
                except OSError as error:item['error']=str(error);result['errors'].append(f'{card.name}/{pcm.name}/{sub.name}: status unavailable')
                result['streams'].append(item)
    if not result['cards']:result['errors'].append('AF16Rig ALSA audio card not found')
    return result


def read_register(device,field):
    if field not in FIELDS:raise ValueError('Unsupported clock status field')
    if device.version!=18:raise DeviceError('Clock status requires state version 18')
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Clock status: device disconnected')
        group,parameter=FIELDS[field];data=(C.c_ubyte*2)()
        rc=device.lib.libusb_control_transfer(device.handle,0xc0,0x90+group,parameter,0,data,2,1000)
        if rc==-4:raise DeviceDisconnected('Clock status: device disconnected')
        if rc!=2:raise DeviceError(f'{field}: expected 2 bytes, received {rc}')
        return int.from_bytes(data,'little')


def snapshot(device,root='/proc/asound'):
    result=dict(channel='clock',utc=datetime.now(timezone.utc).isoformat(),demo=isinstance(device,DemoAF16Rig),
                alsa=alsa_streams(root),raw={},passes=[],stable=False,errors={},write_requests=0,clock_enums_verified=True,decoded={})
    if result['demo']:
        result['alsa']={'cards':[{'card':'demo','id':'AF16Rig'}],'streams':[dict(card='demo',pcm='pcm0p',substream='sub0',direction='Playback',rate_hz=48000,channels=32,format='S32_LE',state='DEMO')],'errors':[]}
        result['raw']=demo_raw(device);result['decoded']=decoded(result['raw']);result['stable']=True
        return result
    if getattr(device,'clock_status_failure',None):result['errors']['native']=device.clock_status_failure;return result
    try:
        with device.lock:
            for _ in range(2):
                values={};result['passes'].append(values)
                for field in FIELDS:values[field]=read_register(device,field)
        result['raw']=result['passes'][-1]
        result['decoded']=decoded(result['raw'])
        result['stable']=result['passes'][0]==result['passes'][1]
        if not result['stable']:result['errors']['changing']='Clock registers changed during capture; values are not a stable snapshot'
    except DeviceDisconnected:raise
    except DeviceError as error:
        device.clock_status_failure=str(error)
        result['errors']['native']=str(error)
    return result
