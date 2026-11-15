"""Analog 3–10 output levels with stereo-link context guards."""
from af16rig import DemoAF16Rig,DeviceError
from output_target import set_raw
from contextlib import nullcontext

def links(device,source):
    mask=getattr(device,'output_link_mask',0) if isinstance(device,DemoAF16Rig) else device.read('output_link')
    return [(mask>>(source-3+i))&1 for i in range(2)]

def read(device,source,field):
    if field=='link':
        mask=getattr(device,'output_link_mask',0) if isinstance(device,DemoAF16Rig) else device.read('output_link')
        return (mask>>(source-3))&1
    if isinstance(device,DemoAF16Rig):return device.output_snapshot(source)['level_signed']
    raw=device.read('output_gain',source-3)
    return raw-65536 if raw>=32768 else raw

def guard(device,source,expected):
    if links(device,source)!=expected:raise DeviceError('Output stereo links changed; stop recall')

def validate_pair(state,target=False):
    if not isinstance(state,dict) or set(state)!={'level','link'}:
        raise ValueError('Invalid output pair configuration')
    for field,limits in [('level',(-15360,0)),('link',(0,1))]:
        values=state[field]
        if not isinstance(values,list) or len(values)!=2 or any(type(v) is not int or not limits[0]<=v<=limits[1] for v in values):
            raise ValueError('Invalid output pair '+field)
    if target:
        if state['link'][0]!=state['link'][1]:raise ValueError('Saved output link flags disagree; save a consistent pair before recall')
        if state['link']==[1,1] and state['level'][0]!=state['level'][1]:
            raise ValueError('Saved linked output levels differ; equalize them or unlink before saving')
    return state

def pair_snapshot(device,source):
    return validate_pair(dict(level=[read(device,source+i,'level') for i in range(2)],link=links(device,source)))

def apply_pair(device,source,target,expected,layout_guard=lambda:None):
    if type(source) is not int or source not in (3,5,7,9):raise ValueError('Invalid output pair')
    validate_pair(target,target=True);validate_pair(expected)
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported output state version')
        def check(wanted):
            layout_guard()
            if pair_snapshot(device,source)!=wanted or pair_snapshot(device,source)!=wanted:
                raise DeviceError('Output pair changed or recall not confirmed; earlier writes remain')
        current={k:list(v) for k,v in expected.items()}
        check(current)
        if current==target:return target
        def link(value):
            nonlocal current
            check(current)
            device.write_output_link(source,bool(value))
            current=dict(current,link=[value,value]);check(current)
        # Restore independent gains while unlinked. Link only after both are
        # at the saved equal level, so firmware gain mirroring is harmless.
        if any(current['link']) and (current['link']!=target['link'] or current['level']!=target['level']):link(0)
        for i,value in enumerate(target['level']):
            if current['level'][i]==value:continue
            check(current)
            set_raw(device,source+i,value,current['level'][i])
            current['level'][i]=value;check(current)
        if current['link']!=target['link']:link(target['link'][0])
        check(target)
    return target

def describe_pair(state):
    validate_pair(state)
    label='Linked' if state['link']==[1,1] else 'Unlinked' if state['link']==[0,0] else 'Mixed link flags'
    return label+' · '+' / '.join(f'{v/256:.2f} dB' for v in state['level'])
