"""Incremental source inclusion matching using existing single-bit writes."""
import copy
from contextlib import nullcontext
from af16rig import DeviceError
from fader_scene import validate_layout,topology
from mixer_membership import change

def plan(target,expected):
    validate_layout(target);validate_layout(expected)
    current=copy.deepcopy(expected);result=[]
    # Remove obsolete selections before adding any replacements. This avoids
    # ambiguous mono/stereo overlap and sends only changed bits.
    for value in (False,True):
        for bus in ('main','cue'):
            for stereo in (False,True):
                index=int(stereo)
                bits=(target[bus][index]&~current[bus][index]) if value else (current[bus][index]&~target[bus][index])
                for bit in range(32 if stereo else 64):
                    if not bits&(1<<bit):continue
                    before=copy.deepcopy(current)
                    if value:current[bus][index]|=1<<bit
                    else:current[bus][index]&=~(1<<bit)
                    validate_layout(current)
                    result.append(dict(bus='mixer_layout',mix_bus=bus,source=bit*2+1 if stereo else bit+1,
                        stereo=stereo,field='inclusion',values=[int(value)],expected_layout=before,target_layout=copy.deepcopy(current)))
    return result

def apply_step(device,layout,step):
    keys={'bus','mix_bus','source','stereo','field','values','expected_layout','target_layout'}
    if not isinstance(step,dict) or set(step)!=keys or step['bus']!='mixer_layout' or step['field']!='inclusion':raise ValueError('Invalid layout step')
    if type(step['source']) is not int or type(step['stereo']) is not bool or not isinstance(step['values'],list) or len(step['values'])!=1 or type(step['values'][0]) is not int or step['values'][0] not in (0,1):raise ValueError('Invalid layout selection')
    if layout!=step['expected_layout'] or plan(step['target_layout'],step['expected_layout'])!=[step]:raise ValueError('Invalid layout transition')
    with getattr(device,'lock',nullcontext()):
        if topology(device)!=layout:raise DeviceError('Mixer layout changed after preview; stop layout matching')
        bus=step['mix_bus']
        change(device,bus,step['source'],step['stereo'],bool(step['values'][0]),*layout[bus])
        if topology(device)!=step['target_layout']:raise DeviceError('Mixer layout step not confirmed; earlier changes remain')
    return {k:step[k] for k in ('bus','source','stereo','field','values')}

def pair_label(masks,left):
    mono,stereo=masks
    if stereo&(1<<(left//2)):return 'Stereo'
    number=left if left<16 else left-16 if left<32 else left-32
    selected=[str(number+i+1) for i in range(2) if mono&(1<<(left+i))]
    return 'Mono '+', '.join(selected) if selected else 'Not included'
