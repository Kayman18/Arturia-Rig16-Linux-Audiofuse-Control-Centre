"""Active input gain/PAD recall with source and hardware-link guards."""
from af16rig import DemoAF16Rig,DeviceError
import preamp
from contextlib import nullcontext

def validate_link_recall(target,expected):
    for state in (target,expected):
        if state.get('kind') not in (['rear','rear'],['line','line'],['mic','mic']) or state.get('input_link') not in ([0,0],[1,1]) or any(type(v) is not int for v in state['input_link']):
            raise ValueError('Automatic input link recall requires matching rear, front Line or front Mic inputs with consistent link flags')
    if target['kind']!=expected['kind']:raise ValueError('Input source kinds differ')
    if target['input_link']==[1,1] and any(target[f][0]!=target[f][1] for f in ('gain','pad','phase','hpf','instrument')):
        raise ValueError('Saved input pair settings differ; match gain/PAD/polarity/HPF/Instrument before recalling a linked pair')

def apply_link(device,source,target,expected,layout_guard=lambda:None):
    if type(source) is not int or source not in range(1,17,2):raise ValueError('Invalid input pair')
    goal={k:list(v) for k,v in expected.items()};goal['input_link']=list(target)
    validate_link_recall(goal,expected)
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported input state version')
        def check(wanted):
            layout_guard()
            for _ in range(2):
                actual={f:[read(device,source+i,f) for i in range(2)] for f in wanted}
                if actual!=wanted:raise DeviceError('Input pair changed or link recall not confirmed; earlier writes remain')
        check(expected)
        if goal==expected:return target
        preamp.change(device,source,expected['kind'][0],'link',bool(target[0]))
        check(goal)
    return target

def read(device,source,field):
    state=preamp.snapshot(device,source)
    if field=='instrument':
        if source not in (1,2) or state['kind']!='line':return None
        if isinstance(device,DemoAF16Rig):return device.front_snapshot()['instrument'+str(source)]
        return (device.read('front_line_instrument')>>(source-1))&1
    if field=='kind':return state['kind']
    if field=='input_link':return state['link']
    if field=='pad':return state['pad']
    if field in ('phase','hpf'):
        kind=state['kind']
        if kind=='mini' and field=='hpf':return None
        if isinstance(device,DemoAF16Rig):
            record=device.input_snapshot(source) if kind=='rear' else device.mini_snapshot() if kind=='mini' else device.front_snapshot()
            return record[field if kind=='rear' else field+str(source)]
        parameter='rear_'+field if kind=='rear' else 'front_'+('line' if kind=='mini' else kind)+'_'+field
        return (device.read(parameter)>>(source-1))&1
    if not state['gain_available']:raise DeviceError('Input gain unavailable')
    return round(state['value']*256)

def context(device,source):
    states=[preamp.snapshot(device,ch) for ch in (source,source+1)]
    return dict(kind=[s['kind'] for s in states],input_link=[s['link'] for s in states])

def guard(device,source,expected):
    if context(device,source)!=expected:raise DeviceError('Input source or hardware link changed; stop recall')

def write(device,source,kind,field,target):
    state=preamp.snapshot(device,source)
    if device.version!=18 or state['kind']!=kind:raise DeviceError('Input source/version changed')
    if field=='instrument':
        if source not in (1,2) or kind!='line' or type(target) is not int or target not in (0,1):raise ValueError('Instrument mode requires an active front jack')
        return device.write_front_instrument(source,bool(target))
    if field in ('pad','phase','hpf'):
        if type(target) is not int or target not in (0,1) or (kind=='mini' and field=='hpf'):raise ValueError('Unsupported input switch')
        if field=='pad' and not state['pad_available']:raise DeviceError('Input PAD unavailable')
        if kind=='rear':device.write_input_bool(source,field,bool(target))
        elif kind=='mini':device.write_mini_switch(source,field,bool(target))
        else:getattr(device,'write_front_'+field)(source,kind,bool(target))
        return
    parameter,index,units,high=preamp.spec(source,kind)
    if not state['gain_available'] or not 0<=target<=high*256 or (units==1 and target%256):raise ValueError('Unsupported input gain')
    raw=target if units==256 else target//256
    if isinstance(device,DemoAF16Rig):
        if kind=='rear':device.inputs[source]['gain_raw']=raw
        elif kind=='mini':setattr(device,'mini_gain_'+str(source),raw)
        else:setattr(device,'front_gain_'+kind+'_'+str(source),raw)
    else:device._write_and_confirm(parameter,raw,index)
