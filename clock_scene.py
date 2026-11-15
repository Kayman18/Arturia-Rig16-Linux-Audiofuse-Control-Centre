"""Scene recall for established clock controls; sample rate is separate."""
from contextlib import nullcontext
from af16rig import DemoAF16Rig, DeviceError
import clock_controls as controls
from clock_status import read_register

ORDER=('wordclock_impedance','wordclock_thru','double_smux','selected_source')

def unpack(code):
    if type(code) is not int or not 0<=code<24:
        raise ValueError('Invalid clock configuration')
    return dict(selected_source=code//8,wordclock_impedance=code&1,
                wordclock_thru=(code>>1)&1,double_smux=(code>>2)&1)

def pack(state):
    return state['selected_source']*8+state['wordclock_impedance']+2*state['wordclock_thru']+4*state['double_smux']

def snapshot(device):
    state=controls.demo_raw(device) if isinstance(device,DemoAF16Rig) else {k:read_register(device,k) for k in controls.CONFIG}
    if any(type(state.get(k)) is not int or not 0<=state[k]<len(controls.ENUMS[k]) for k in controls.CONFIG):
        raise DeviceError('Clock configuration unavailable')
    return state

def read(device):
    return pack(snapshot(device))

def apply(device,target,expected):
    goal=unpack(target);unpack(expected)
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported clock state version')
        current=snapshot(device)
        if pack(current)!=expected:raise DeviceError('Clock settings changed after preview')
        if target==expected:return target
        # Check external frequency before any clock writes, and the existing
        # source setter checks it again immediately before selecting it.
        if goal['selected_source']:
            field=controls.FREQUENCIES[goal['selected_source']]
            code=current[field] if isinstance(device,DemoAF16Rig) else read_register(device,field)
            if type(code) is not int or not 1<=code<len(controls.RATES):
                raise DeviceError('Saved external clock has no recognized frequency; check its connection')
        for field in ORDER:
            if current[field]==goal[field]:continue
            controls.set_option(device,field,goal[field],current)
            after=snapshot(device)
            wanted=dict(current,**{field:goal[field]})
            # Preferred source is device-managed, and may follow a source write.
            keys=controls.OPTIONS if field=='selected_source' else controls.CONFIG
            if any(after[k]!=wanted[k] for k in keys):
                raise DeviceError('Clock step not confirmed; earlier writes remain')
            current=after
        if read(device)!=target:raise DeviceError('Clock recall not confirmed')
    return target

def describe(code):
    s=unpack(code)
    return ' · '.join(controls.OPTIONS[k][s[k]] for k in ('selected_source',)+ORDER[:3])
