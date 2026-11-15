"""Active-input gain/link controls shared by the mixer strips."""
import struct
from af16rig import DeviceDisconnected,DeviceError,DemoAF16Rig,front_source_status,mini_source_status

def sources(device):
    if isinstance(device,DemoAF16Rig):
        first=device.front_snapshot()['source_status']['sources']
        mini=device.mini_snapshot()['source_status']['sources']
    else:
        context=device.link_context()
        first=front_source_status(context)['sources'];mini=mini_source_status(context)
    if not first or not mini:raise DeviceError('Input source status unavailable')
    return first+['mini' if s=='line' else s for s in mini]+['rear']*12

def spec(channel,kind):
    if kind=='rear':return 'rear_gain',channel-1,256,12
    if channel in (1,2) and kind in ('mic','line'):return 'front_'+kind+'_gain',channel-1,1,55
    if channel in (3,4) and kind=='mini':return 'front_mini_gain',channel-3,256,12
    raise DeviceError('Unsupported active input')

def snapshot(device,channel):
    if type(channel) is not int or not 1<=channel<=16:raise ValueError('Invalid input')
    kinds=sources(device);kind=kinds[channel-1];left=((channel-1)//2)*2
    field,index,units,high=spec(channel,kind)
    if isinstance(device,DemoAF16Rig):
        if kind=='rear':raw=device.inputs[channel]['gain_raw'];link=device.input_snapshot(channel)['link']
        elif kind=='mini':raw=device.mini_snapshot()['gain'+str(channel)+'_raw'];link=None
        else:raw=device.front_snapshot()['gain'+str(channel)];link=device.front_snapshot()[kind]
    else:
        raw=device.read(field,index)
        if kind=='rear':
            mask=device.read('rear_link');bits=[(mask>>i)&1 for i in (left,left+1)]
            link=bits[0] if bits[0]==bits[1] else None
        elif kind in ('mic','line'):link=device.read('front_'+kind+'_link')&1
        else:link=None
    value=struct.unpack('<h',struct.pack('<H',raw))[0]/units
    pair_same=kinds[left:left+2]==[kind,kind]
    override=(getattr(device,'force_rear',3) if isinstance(device,DemoAF16Rig) else device.read('force_rear')) & 3 if channel in (1,2) else None
    try:pad=read_pad(device,channel,kind)
    except DeviceDisconnected:raise
    except DeviceError:pad=None
    return dict(pad=pad,pad_available=device.version==18 and pad in (0,1),source=channel,kind=kind,value=value,high=high,units=units,forced_rear=override,
                gain_available=device.version==18 and 0<=value<=high,
                link=link,link_available=device.version==18 and pair_same and kind!='mini' and link in (0,1),
                pair=[left+1,left+2])

def change(device,channel,expected_kind,control,value):
    # Caller runs on the single USB worker. Source is reread just before writes.
    state=snapshot(device,channel)
    if state['kind']!=expected_kind:raise DeviceError('Input source changed; refresh before editing')
    if control=='link':
        if type(value) is not bool or not state['link_available']:raise DeviceError('Pair cannot be linked in its current source mode')
        if expected_kind=='rear':device.write_input_link(channel,value)
        else:device.write_front_link(expected_kind,value)
    elif control=='gain':
        if type(value) is not int or not state['gain_available'] or not 0<=value<=state['high']:raise DeviceError('Unsupported gain target')
        if isinstance(device,DemoAF16Rig):
            if expected_kind=='rear':device.inputs[channel]['gain_raw']=value*256
            elif expected_kind=='mini':setattr(device,'mini_gain_'+str(channel),value*256)
            else:setattr(device,'front_gain_'+expected_kind+'_'+str(channel),value)
        else:
            field,index,units,_=spec(channel,expected_kind)
            with device.lock:
                if sources(device)[channel-1]!=expected_kind:raise DeviceError('Input source changed before write')
                device._write_and_confirm(field,value*units,index)
    else:raise ValueError('Unknown preamp control')
    return snapshot(device,channel)

def change_pair_gain(device,source,kind,value):
    """One stereo-strip gain sets both members, with readback after each write."""
    if type(source) is not int or source not in range(1,17) or type(value) is not int:
        raise ValueError('Invalid pair gain')
    left=((source-1)//2)*2+1
    def check_selection():
        if isinstance(device,DemoAF16Rig):raw=device.mix_channel_snapshot('main',left)['raw']
        else:raw={'show':device.read('main_channel_show'),'stereo':device.read('main_channel_stereo')}
        if raw['show']&(3<<(left-1)) or not raw['stereo']&(1<<((left-1)//2)):
            raise DeviceError('Stereo mixer selection changed; refresh gain controls')
    check_selection()
    states=[snapshot(device,i) for i in (left,left+1)]
    if any(s['kind']!=kind or not s['gain_available'] or not 0<=value<=s['high'] for s in states):
        raise DeviceError('Pair gain requires compatible active inputs and a supported target')
    for ch in (left,left+1):
        check_selection()
        current=snapshot(device,ch)
        if current['kind']!=kind:raise DeviceError('Pair input source changed during gain adjustment')
        # Firmware may already propagate the first write to its linked partner.
        if current['value']!=value:change(device,ch,kind,'gain',value)
    result=[snapshot(device,i) for i in (left,left+1)]
    if any(s['kind']!=kind or s['value']!=value for s in result):
        raise DeviceError('Both pair gains were not confirmed; refresh to inspect actual values')
    return result


def read_pad(device,channel,kind):
    if isinstance(device,DemoAF16Rig):
        state=device.input_snapshot(channel) if kind=='rear' else device.mini_snapshot() if kind=='mini' else device.front_snapshot()
        return state.get('pad' if kind=='rear' else 'pad'+str(channel))
    field='rear_pad' if kind=='rear' else 'front_line_pad' if kind=='mini' else 'front_'+kind+'_pad'
    bit=(device.read(field)>>(channel-1))&1
    return 1-bit if kind=='rear' else bit

def change_pad(device,source,stereo,expected):
    if type(source) is not int or not 1<=source<=16 or type(stereo) is not bool or (stereo and source%2==0):
        raise ValueError('Invalid PAD selection')
    channels=[source,source+1] if stereo else [source]
    def check():
        raw=device.mix_channel_snapshot('main',source)['raw']
        pair=bool(raw['stereo']&(1<<((source-1)//2)))
        mask=(3 if stereo else 1)<<(source-1)
        if pair!=stereo or (raw['show']&mask)!=(0 if stereo else mask):raise DeviceError('Stereo selection changed; refresh PAD controls')
        states=[snapshot(device,ch) for ch in channels]
        return states
    states=check()
    if [(s['kind'],s['pad']) for s in states]!=expected or any(not s['pad_available'] for s in states):
        raise DeviceError('Input source or PAD changed; refresh before editing')
    target=not all(s['pad']==1 for s in states)
    for ch,old in zip(channels,states):
        current=check()
        if any(s['kind']!=before['kind'] for s,before in zip(current,states)):
            raise DeviceError('Input source changed during PAD adjustment')
        state=current[channels.index(ch)]
        if state['pad']==int(target):continue
        if state['pad']!=old['pad']:raise DeviceError('PAD changed during adjustment; refresh')
        if old['kind']=='rear':device.write_input_bool(ch,'pad',target)
        elif old['kind']=='mini':device.write_mini_switch(ch,'pad',target)
        else:device.write_front_pad(ch,old['kind'],target)
    result=check()
    if any(s['pad']!=int(target) for s in result):raise DeviceError('PAD change not confirmed; refresh')
    left=((source-1)//2)*2+1
    return [snapshot(device,ch) for ch in (left,left+1)]
