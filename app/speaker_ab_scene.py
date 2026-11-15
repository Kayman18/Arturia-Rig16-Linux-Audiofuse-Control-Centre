"""Dependency-ordered recall of the three established A/B controls."""
from contextlib import nullcontext
from af16rig import DeviceError

def unpack(code):
    if type(code) is not int or not 0<=code<16:raise ValueError('Invalid A/B configuration')
    return dict(enabled=code&1,selected=(code>>1)&1,destination=code>>2)

def pack(state):return state['enabled'] | state['selected']<<1 | state['destination']<<2

def read(device):
    state=device.monitor_settings_snapshot()
    values=dict(enabled=state['ab_enabled'],selected=state['ab_selected'],destination=state['ab_destination_raw'])
    if any(type(values[k]) is not int or values[k] not in (0,1) for k in ('enabled','selected')) or type(values['destination']) is not int or not 0<=values['destination']<=3:
        raise DeviceError('A/B state unavailable')
    return pack(values)

def steps(expected,target):
    current=unpack(expected);goal=unpack(target);result=[]
    def add(field,value):
        if current[field]==value:return
        result.append((field,value));current[field]=value
    # Changing B assignment while listening to B is rejected by the device.
    if current['destination']!=goal['destination']:
        if current['enabled'] and current['selected']:add('selected',0)
        add('destination',goal['destination'])
    # Selection writes require A/B enabled, even for a saved disabled state.
    if current['selected']!=goal['selected']:
        add('enabled',1);add('selected',goal['selected'])
    add('enabled',goal['enabled'])
    return result

def apply(device,target,expected):
    operations=steps(expected,target)
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported A/B state version')
        current=unpack(expected)
        if read(device)!=expected:raise DeviceError('A/B state changed after preview')
        for field,value in operations:
            if read(device)!=pack(current):raise DeviceError('A/B state changed during recall; earlier writes remain')
            if field=='enabled':device.write_ab_enabled(bool(value))
            elif field=='selected':device.write_ab_selected('B' if value else 'A')
            else:device.write_ab_destination(3+2*value)
            current[field]=value
            if read(device)!=pack(current):raise DeviceError('A/B step not confirmed; earlier writes remain')
        if read(device)!=target:raise DeviceError('A/B recall not confirmed')
    return target

def describe(code):
    s=unpack(code);first=3+2*s['destination']
    return ('Enabled' if s['enabled'] else 'Disabled')+' · '+('B' if s['selected'] else 'A')+f' · B outputs {first}/{first+1}'
