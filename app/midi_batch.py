"""Plan consecutive strip assignments without changing their message types."""
from midi_backup import make_backup, restore_plan
from midi_config import STRIP_CONTROLS, editable

def plan_strip_batch(records,control,channel,first_number,demo=False):
    if control not in STRIP_CONTROLS:raise ValueError('Choose a strip control')
    if type(channel) is not int or not 1<=channel<=16:
        raise ValueError('MIDI channel must be 1–16')
    if type(first_number) is not int or not 0<=first_number<=120:
        raise ValueError('First number must be 0–120 so all eight numbers fit within 0–127')
    data=make_backup(records,demo)
    parameter=20+STRIP_CONTROLS.index(control)
    for entry in data['assignments']:
        if entry['parameter']!=parameter:continue
        if not editable(dict(entry,stable=True)):
            raise ValueError(f"Strip {entry['index']+1}: unsupported assignment encoding; refresh or choose another control")
        entry['raw']=(entry['raw']&0xc000)|((channel-1)<<8)|(first_number+entry['index'])
    return restore_plan(data,records,demo)


def plan_full_batch(records,channel,first_number,demo=False):
    """64 strip controls, consecutive blocks of eight, with no device writes."""
    if type(channel) is not int or not 1<=channel<=16:
        raise ValueError('MIDI channel must be 1–16')
    if type(first_number) is not int or not 0<=first_number<=64:
        raise ValueError('First number must be 0–64 so all 64 numbers fit within 0–127')
    data=make_backup(records,demo)
    for entry in data['assignments']:
        parameter=entry['parameter']
        if not 20<=parameter<=27:continue
        if not editable(dict(entry,stable=True)):
            raise ValueError(f"{STRIP_CONTROLS[parameter-20]} · strip {entry['index']+1}: unsupported assignment encoding")
        number=first_number+(parameter-20)*8+entry['index']
        entry['raw']=(entry['raw']&0xc000)|((channel-1)<<8)|number
    return restore_plan(data,records,demo)


def assignment_conflicts(records,changes):
    """Describe duplicate supported assignments in the proposed final state."""
    targets={(c['parameter'],c['index']):(c.get('message_type',c['expected']>>14)<<14)|((c['channel']-1)<<8)|c['number'] for c in changes}
    groups={}
    for r in records:
        key=(r['parameter'],r['index']);raw=targets.get(key,r['raw'])
        if not editable(dict(r,raw=raw)) or raw>>14==2:continue
        label=(f"Strip {r['index']+1} · " if r['parameter']<28 else '')+r['control']
        groups.setdefault(raw,[]).append((key,label))
    return [' / '.join(label for key,label in entries) for entries in groups.values()
            if len(entries)>1 and any(key in targets for key,label in entries)]
