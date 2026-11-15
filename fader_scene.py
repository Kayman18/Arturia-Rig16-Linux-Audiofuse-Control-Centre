"""Portable Main/Cue fader scenes, using existing guarded level writes only."""
import json
from contextlib import nullcontext
from datetime import datetime,timezone
from af16rig import DemoAF16Rig,DeviceError
from digital_mixer import mixer_device
from mixer_membership import masks

FORMAT='af16rig-main-cue-faders-v1'
MAX_BYTES=65536

def validate_layout(layout):
    if not isinstance(layout,dict) or set(layout)!= {'main','cue'}:raise ValueError('Main and Cue layouts required')
    for value in layout.values():
        if not isinstance(value,list) or len(value)!=2:raise ValueError('Invalid mixer layout')
        mono,pairs=value
        if type(mono) is not int or not 0<=mono<1<<64 or type(pairs) is not int or not 0<=pairs<1<<32:
            raise ValueError('Invalid mixer selection masks')
        if any(pairs&(1<<i) and mono&(3<<(i*2)) for i in range(32)):
            raise ValueError('Ambiguous mono/stereo selection; resolve Sources before using scenes')
    return layout

def addresses(layout):
    validate_layout(layout);result=[]
    for bus in ('main','cue'):
        mono,pairs=layout[bus]
        for source in range(1,65):
            if mono&(1<<(source-1)):result.append(dict(bus=bus,source=source,stereo=False))
            elif source%2 and pairs&(1<<((source-1)//2)):result.append(dict(bus=bus,source=source,stereo=True))
        result.append(dict(bus=bus,source=0,stereo=False))
    return result

def topology(device):
    if device.version!=18:raise DeviceError('Fader scenes require state version 18')
    passes=[{bus:list(masks(device,bus)) for bus in ('main','cue')} for _ in range(2)]
    if passes[0]!=passes[1]:raise DeviceError('Mixer sources changed during read; refresh the scene')
    return validate_layout(passes[0])

def validate_address(layout,address):
    if (not isinstance(address,dict) or set(address)!={'bus','source','stereo'}
            or type(address['source']) is not int or type(address['stereo']) is not bool
            or address not in addresses(layout)):raise ValueError('Fader is not part of this scene layout')

def read_entry(device,layout,address):
    validate_address(layout,address)
    if topology(device)!=layout:raise DeviceError('Mixer source/stereo layout changed; refresh the scene')
    bus,source,stereo=address['bus'],address['source'],address['stereo']
    facade=mixer_device(device,source)
    def levels():
        indices=range(source-1,source+1) if stereo else [source-1]
        if isinstance(device,DemoAF16Rig) and source<=16:
            return [getattr(device,bus+'_master',-12*256)] if source==0 else [getattr(device,'mix_levels',{}).get((bus,i+1),-12*256) for i in indices]
        words=[device.read(bus+'_master')] if source==0 else [facade.read(bus+'_channel_level',i) for i in indices]
        return [v-65536 if v>=32768 else v for v in words]
    values=levels();again=levels()
    if values!=again:raise DeviceError('Fader moved during read; refresh the scene')
    maximum=0 if source==0 else 6*256
    if any(type(v) is not int or not -60*256<=v<=maximum for v in values):raise DeviceError('Fader is outside the supported range')
    return dict(address,levels=values)

def validate(scene):
    if (not isinstance(scene,dict) or scene.get('format')!=FORMAT or scene.get('device')!='AF16Rig'
            or type(scene.get('state_version')) is not int or scene['state_version']!=18
            or type(scene.get('demo')) is not bool):raise ValueError('Not an AF16Rig Main/Cue fader scene')
    layout=validate_layout(scene.get('layout'));expected=addresses(layout);entries=scene.get('entries')
    if not isinstance(entries,list) or len(entries)!=len(expected):raise ValueError('Scene has missing or extra faders')
    seen=set()
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!= {'bus','source','stereo','levels'}:raise ValueError('Invalid scene fader')
        address={k:entry[k] for k in ('bus','source','stereo')};validate_address(layout,address)
        key=(entry['bus'],entry['source'])
        if key in seen:raise ValueError('Duplicate scene fader')
        seen.add(key);values=entry['levels']
        if (not isinstance(values,list) or len(values)!=(2 if entry['stereo'] else 1)
                or any(type(v) is not int or not -60*256<=v<=(0 if entry['source']==0 else 6*256) for v in values)):
            raise ValueError('Invalid scene level')
    return scene

def make_scene(layout,entries,demo=False):
    # Round-trip makes a detached snapshot; no later poll can mutate an open file dialog's data.
    return validate(json.loads(json.dumps(dict(format=FORMAT,device='AF16Rig',state_version=18,demo=bool(demo),
        created_utc=datetime.now(timezone.utc).isoformat(),layout=layout,entries=entries))))

def unique_keys(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key in scene')
        result[key]=value
    return result

def load_scene(path):
    with open(path,'rb') as f:raw=f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Scene file exceeds 64 KiB')
    try:return validate(json.loads(raw.decode('utf-8'),object_pairs_hook=unique_keys))
    except RecursionError as error:raise ValueError('Scene nesting is invalid') from error

def plan(saved,current):
    validate(saved);validate(current)
    if saved['demo']!=current['demo']:raise ValueError('Demo and hardware scenes cannot be mixed')
    if saved['layout']!=current['layout']:raise ValueError('Mixer sources/stereo layout differs. Scenes recall levels only; select the matching layout first.')
    actual={(e['bus'],e['source']):e for e in current['entries']};changes=[]
    for entry in saved['entries']:
        old=actual[entry['bus'],entry['source']]
        if entry['stereo'] and entry['levels'][1]-entry['levels'][0]!=old['levels'][1]-old['levels'][0]:
            raise ValueError('Stereo L/R offset differs; match the pair balance before recalling this fader scene')
        if entry['levels']!=old['levels']:changes.append(dict(entry,expected=list(old['levels'])))
    return changes

def apply_entry(device,layout,change):
    if not isinstance(change,dict) or set(change)!={'bus','source','stereo','levels','expected'}:raise ValueError('Invalid scene change')
    address={k:change[k] for k in ('bus','source','stereo')};validate_address(layout,address)
    # Validate both old and target without needing any other fader values.
    size=2 if address['stereo'] else 1;maximum=0 if address['source']==0 else 6*256
    for key in ('levels','expected'):
        value=change[key]
        if not isinstance(value,list) or len(value)!=size or any(type(v) is not int or not -60*256<=v<=maximum for v in value):raise ValueError('Invalid scene level')
    if size==2 and change['levels'][1]-change['levels'][0]!=change['expected'][1]-change['expected'][0]:raise ValueError('Stereo offset must be preserved')
    with getattr(device,'lock',nullcontext()):
        current=read_entry(device,layout,address)
        if current['levels']!=change['expected']:raise DeviceError('Fader changed since preview; refresh before recalling')
        if current['levels']==change['levels']:return current
        bus,source,stereo=address['bus'],address['source'],address['stereo']
        if isinstance(device,DemoAF16Rig) and source and source<=16 and stereo:
            # Explicit demo state simulation; no USB or expansion of native commands.
            if not hasattr(device,'mix_levels'):device.mix_levels={}
            for i,v in enumerate(change['levels']):device.mix_levels[bus,source+i]=v
        else:mixer_device(device,source).set_console_value(bus,source,'master' if source==0 else 'level',change['levels'][0],stereo)
        result=read_entry(device,layout,address)
        if result['levels']!=change['levels']:raise DeviceError('Scene fader readback did not match; stopped without retry')
        return result
