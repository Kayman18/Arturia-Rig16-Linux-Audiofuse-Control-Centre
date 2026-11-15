"""Portable configuration for supported MIDI settings; excludes audio settings."""
import json
from datetime import datetime,timezone
from midi_ports import OPTIONS,LABELS
import midi_backup

FORMAT='af16rig-midi-configuration-v1'
MAX_BYTES=131072

def bank_value(records):
    bank=[r for r in records if (r.get('parameter'),r.get('index'))==(18,0)]
    if len(bank)!=1:raise ValueError('Refresh MIDI bank size before exporting')
    r=bank[0];value=r.get('raw')
    if type(value) is not int or not 1<=value<=8 or r.get('stable') is not True or r.get('reads')!=[value,value]:
        raise ValueError('MIDI bank size needs two matching reads')
    return value

def port_values(records):
    if not isinstance(records,dict) or set(records)!=set(OPTIONS):raise ValueError('Read all MIDI port settings first')
    result={}
    for field,options in OPTIONS.items():
        r=records[field];v=r.get('raw')
        if r.get('stable') is not True or type(v) is not int or not 0<=v<len(options):raise ValueError('Unsupported or unstable '+LABELS[field])
        result[field]=v
    return result

def make_configuration(records,ports,demo=False):
    return validate(dict(format=FORMAT,device='AF16Rig',state_version=18,demo=bool(demo),
        created_utc=datetime.now(timezone.utc).isoformat(),bank_size=bank_value(records),
        ports=port_values(ports),assignments=midi_backup.make_backup(records,demo)))

def validate(data):
    if (not isinstance(data,dict) or data.get('format')!=FORMAT or data.get('device')!='AF16Rig'
        or type(data.get('state_version')) is not int or data['state_version']!=18 or type(data.get('demo')) is not bool):
        raise ValueError('Not an AF16Rig MIDI configuration file')
    if set(data)!={'format','device','state_version','demo','created_utc','bank_size','ports','assignments'}:
        raise ValueError('Unexpected or missing MIDI configuration sections')
    if type(data['bank_size']) is not int or not 1<=data['bank_size']<=8:raise ValueError('Invalid MIDI bank size')
    ports=data['ports']
    if not isinstance(ports,dict) or set(ports)!=set(OPTIONS):raise ValueError('Missing or extra MIDI port settings')
    for field,value in ports.items():
        if type(value) is not int or not 0<=value<len(OPTIONS[field]):raise ValueError('Unsupported '+LABELS[field])
    midi_backup.validate(data['assignments'])
    if data['assignments']['format']!=midi_backup.FORMAT or data['assignments']['demo']!=data['demo']:
        raise ValueError('Inconsistent MIDI assignments section')
    return data

def load(path):
    with open(path,'rb') as f:raw=f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('MIDI configuration file is too large')
    try:return validate(json.loads(raw.decode('utf-8'),object_pairs_hook=midi_backup.unique_object))
    except RecursionError as error:raise ValueError('Invalid JSON nesting') from error

def plan(data,records,ports,demo=False):
    validate(data)
    if data['demo']!=bool(demo):raise ValueError('Demo and hardware configurations cannot be mixed')
    bank=bank_value(records);current=port_values(ports)
    changes=midi_backup.restore_plan(data['assignments'],records,demo)
    if bank!=data['bank_size']:
        changes.append(dict(kind='bank',label='MIDI channels per bank',before=str(bank),after=str(data['bank_size']),expected=bank,target=data['bank_size']))
    # Change preferred operating mode last, after routing and assignments.
    fields=[f for f in OPTIONS if f!='preferred_mode']+['preferred_mode']
    for field in fields:
        value=data['ports'][field]
        if value!=current[field]:changes.append(dict(kind='port',field=field,label=LABELS[field],
            before=OPTIONS[field][current[field]],after=OPTIONS[field][value],expected=current[field],target=value))
    return changes
