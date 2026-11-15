"""One stereo-position knob backed by the two native channel pans."""
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected

def targets(position):
    if type(position) is not int or not 0<=position<=254:raise ValueError('Invalid stereo pan position')
    return [max(0,2*position-254),min(254,2*position)]

def describe(values):
    if len(values)!=2 or any(type(v) is not int or not 0<=v<=254 for v in values):
        return dict(values=list(values),position=None,canonical=False)
    position=sum(values)/2
    canonical=position.is_integer() and targets(int(position))==list(values)
    return dict(values=list(values),position=position,canonical=canonical)

def read_pair(device,bus,source):
    if bus not in ('main','cue') or type(source) is not int or source not in range(1,64,2):
        raise ValueError('Select the left channel of a Main/Cue stereo pair')
    from digital_mixer import mixer_device
    facade=mixer_device(device,source)
    demo=isinstance(device,DemoAF16Rig) and source<=16
    def read(name,index=0):
        if not demo:return facade.read(name,index)
        if name.endswith('_pan'):return getattr(device,'pan_positions',{}).get((bus,index+1),127)
        return getattr(device,bus+('_show' if name.endswith('_show') else '_stereo'),65535 if name.endswith('_show') else 0)
    masks=[read(bus+'_channel_show'),read(bus+'_channel_stereo')]
    index=source-1
    if masks[0]&(3<<index) or not masks[1]&(1<<(index//2)):
        raise DeviceError('Stereo pan requires an included stereo pair without overlapping mono channels')
    state=describe([read(bus+'_channel_pan',index+i) for i in (0,1)])
    state['masks']=masks
    if state['position'] is None:raise DeviceError('Stereo pan readback outside supported range')
    return state

def set_position(device,bus,source,position,expected):
    target=targets(position)
    from digital_mixer import mixer_device
    facade=mixer_device(device,source)
    demo=isinstance(device,DemoAF16Rig) and source<=16
    with nullcontext() if demo else facade.lock:
        device.last_write=None
        if device.version!=18:raise DeviceError('Unsupported stereo pan state version')
        current=read_pair(device,bus,source)
        if not isinstance(expected,dict) or any(current[k]!=expected.get(k) for k in ('masks','values')):
            raise DeviceError('Stereo pan or selection changed. Refresh before adjusting.')
        confirmed=current['values'][:]
        for side in (0,1):
            fresh=read_pair(device,bus,source)
            if fresh['masks']!=current['masks'] or fresh['values']!=confirmed:
                raise DeviceError('Stereo pair changed during adjustment; refresh to see current pans')
            if confirmed[side]==target[side]:continue
            if demo:
                if not hasattr(device,'pan_positions'):device.pan_positions={}
                device.pan_positions[bus,source+side]=target[side]
            else:
                try:facade._write_and_confirm(bus+'_channel_pan',target[side],source-1+side)
                except DeviceDisconnected:raise
                except DeviceError as error:
                    if confirmed!=current['values']:
                        raise DeviceError(f'Stereo pan partly applied; refresh both pans. {error}') from error
                    raise
            confirmed[side]=target[side]
        final=read_pair(device,bus,source)
        if final['values']!=target or final['masks']!=current['masks']:
            raise DeviceError('Stereo pan final readback differs; refresh device state')
        return final
