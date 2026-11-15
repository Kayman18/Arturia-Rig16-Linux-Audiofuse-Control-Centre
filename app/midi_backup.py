"""Portable MIDI assignment backup; versioned restore of channel, type and number."""
import json
from datetime import datetime,timezone
from midi_config import FIELDS,decode,editable,MESSAGE_TYPES,validate as validate_address

LEGACY_FORMAT='af16rig-midi-channel-number-backup-v1'
FORMAT='af16rig-midi-assignments-backup-v2'
ASSIGNMENTS=FIELDS[2:]
MAX_FILE_BYTES=65536

def stable_records(records):
    result={}
    for r in records:
        if not isinstance(r,dict):raise ValueError('Invalid MIDI readback record')
        p,i=r.get('parameter'),r.get('index');validate_address(p,i)
        if p<20:continue
        key=p,i
        if key in result:raise ValueError('Duplicate MIDI readback record')
        raw=r.get('raw');decode(p,i,raw)
        reads=r.get('reads')
        if (r.get('stable') is not True or not isinstance(reads,list) or len(reads)!=2
                or any(type(v) is not int or v!=raw for v in reads)):
            raise ValueError('Refresh MIDI assignments: two matching reads are required for every entry')
        result[key]=raw
    if set(result)!=set(ASSIGNMENTS):raise ValueError('Read all 71 MIDI assignments before backup or restore')
    return result

def make_backup(records,demo=False):
    values=stable_records(records)
    return dict(format=FORMAT,device='AF16Rig',state_version=18,demo=bool(demo),
        created_utc=datetime.now(timezone.utc).isoformat(),
        scope='Channel, CC/Note/Off type and number. Bank settings and MIDI routing are excluded.',
        assignments=[dict(parameter=p,index=i,raw=values[p,i]) for p,i in ASSIGNMENTS])

def validate(data):
    if (not isinstance(data,dict) or data.get('format') not in (FORMAT,LEGACY_FORMAT) or data.get('device')!='AF16Rig'
            or type(data.get('state_version')) is not int or data['state_version']!=18
            or type(data.get('demo')) is not bool):raise ValueError('Not a supported MIDI assignment backup')
    entries=data.get('assignments')
    if not isinstance(entries,list) or len(entries)!=len(ASSIGNMENTS):raise ValueError('Backup must contain exactly 71 assignments')
    result={}
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('Invalid MIDI backup entry')
        p,i=entry.get('parameter'),entry.get('index');validate_address(p,i)
        if (p,i) not in ASSIGNMENTS or (p,i) in result:raise ValueError('Unsupported or duplicate MIDI assignment')
        raw=entry.get('raw');decode(p,i,raw);result[p,i]=raw
    return result

def unique_object(pairs):
    data={}
    for key,value in pairs:
        if key in data:raise ValueError('Duplicate JSON key in MIDI backup')
        data[key]=value
    return data

def load_backup(path):
    with open(path,'rb') as f:payload=f.read(MAX_FILE_BYTES+1)
    if len(payload)>MAX_FILE_BYTES:raise ValueError('MIDI backup is too large')
    try:data=json.loads(payload.decode('utf-8'),object_pairs_hook=unique_object)
    except RecursionError as error:raise ValueError('MIDI backup nesting is invalid') from error
    validate(data);return data

def restore_plan(data,records,demo=False):
    target=validate(data)
    if data['demo'] and not demo:raise ValueError('Demo MIDI backups cannot be restored to hardware')
    current=stable_records(records);changes=[]
    for p,i in ASSIGNMENTS:
        old,new=current[p,i],target[p,i]
        if old==new:continue
        before,after=decode(p,i,old),decode(p,i,new)
        label=(f"Strip {before['strip']} · " if before['strip'] else '')+before['control']
        if not editable(dict(before,stable=True)) or not editable(dict(after,stable=True)):
            raise ValueError(f'{label}: unsupported assignment encoding; no restore started')
        if data['format']==LEGACY_FORMAT and old&0xc000!=new&0xc000:
            raise ValueError(f'{label}: saved message type differs; only channel/number changes can be restored')
        changes.append(dict(parameter=p,index=i,expected=old,channel=after['channel_code']+1,
            number=after['number_code'],label=label,before=f"Ch {before['channel_code']+1} · {MESSAGE_TYPES[before['type_code']]} #{before['number_code']}",
            after=f"Ch {after['channel_code']+1} · {MESSAGE_TYPES[after['type_code']]} #{after['number_code']}"))
        if data['format']==FORMAT:changes[-1]['message_type']=after['type_code']
    return changes
