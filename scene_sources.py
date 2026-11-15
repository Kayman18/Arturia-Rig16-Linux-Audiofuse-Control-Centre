"""Explicit source matching before a fresh scene preview; no setting recall."""
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError,front_source_status,mini_source_status

def validate(kinds):
    if not isinstance(kinds,list) or len(kinds)!=16:raise ValueError('Invalid input sources')
    for i,kind in enumerate(kinds):
        allowed=('rear','line','mic') if i<2 else ('rear','mini') if i<4 else ('rear',)
        if kind not in allowed:raise ValueError('Invalid input source kind')
    return kinds

def from_scene(scene):
    result=[]
    entries={e['source']:e for e in scene['entries'] if e['bus']=='inputs'}
    if set(entries)!=set(range(1,17,2)):return None
    for source in range(1,17,2):result.extend(entries[source]['values']['kind'])
    return validate(result)

def raw(device):
    if isinstance(device,DemoAF16Rig):
        state=dict(force_rear=getattr(device,'force_rear',3),detect_status=getattr(device,'detect_status',0x31))
    else:state={k:device.read(k) for k in ('force_rear','detect_status')}
    if any(type(v) is not int or not 0<=v<=65535 for v in state.values()):raise DeviceError('Input source status unavailable')
    return state

def kinds(state):
    context=dict(raw=state)
    return front_source_status(context)['sources']+['mini' if k=='line' else k for k in mini_source_status(context)]+['rear']*12

def operations(state,target):
    validate(target);current=dict(state);result=[]
    # Plan both pairs before writing either. Only existing pair-source commands
    # are used, preserving unrelated override bits.
    for left in (0,2):
        if kinds(current)[left:left+2]==target[left:left+2]:continue
        matches=[]
        for forced in (False,True):
            mask=3<<left
            candidate=dict(current,force_rear=(current['force_rear']&~mask)|(mask if forced else 0))
            if kinds(candidate)[left:left+2]==target[left:left+2]:matches.append((forced,candidate))
        if not matches:raise DeviceError(f'Inputs {left+1}/{left+2}: saved sources cannot be selected with the connected front inputs; match connections/source selection manually')
        forced,current=matches[0];result.append((left+1,forced,dict(current)))
    return result

def apply(device,target,expected,layout_guard=lambda:None):
    validate(target);validate(expected)
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported source state version')
        layout_guard();current=raw(device)
        if raw(device)!=current or kinds(current)!=expected:raise DeviceError('Input sources changed after preview')
        steps=operations(current,target)
        for source,force,after in steps:
            layout_guard()
            if raw(device)!=current:raise DeviceError('Input connection or source changed; stop source matching')
            device.set_rear_pair_source(source,force)
            if raw(device)!=after or raw(device)!=after:raise DeviceError('Source change not confirmed; earlier source changes remain')
            current=after
        layout_guard()
        if kinds(raw(device))!=target:raise DeviceError('Input source matching not confirmed')
    return target
