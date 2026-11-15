"""Portable name-only backup, strict validation and restore preview.

No routing, mixer, preamp, clock or preset operations are part of this format.
"""
import json
from datetime import datetime,timezone
from channel_names import NAME_SOURCES,name_parameter,source_label,decode_words,MAX_WORDS
from name_edit import encode_name
from af16rig import DeviceError
FORMAT='af16rig-name-backup-v1'
MAX_FILE_BYTES=65536


def stable_name(record,demo=False):
    if demo and record.get('status')=='demo':return record['candidate']
    passes=record.get('passes',[])
    if len(passes)!=2 or passes[0]!=passes[1] or not 1<=len(passes[0])<=MAX_WORDS:
        raise DeviceError('Names must have two matching reads before backup or restore')
    if any(type(w) is not int or not 0<=w<=65535 for w in passes[0]):raise DeviceError('Invalid name readback words')
    decoded=decode_words(passes[0])
    if decoded['status'] not in ('candidate','blank') or decoded.get('encoding')!='packed UTF-8':raise DeviceError('A stable packed-text name is required')
    return decoded['candidate']


def make_backup(records,demo=False):
    entries=[];seen=set()
    for record in records:
        source=record['source'];parameter=name_parameter(source)
        if source in seen:raise ValueError('Duplicate channel in backup')
        if record.get('parameter',parameter)!=parameter:raise ValueError('Name parameter does not match channel')
        seen.add(source)
        entries.append(dict(source=source,parameter=parameter,channel=source_label(source),name=stable_name(record,demo)))
    result=dict(format=FORMAT,device='AF16Rig',state_version=18,created_utc=datetime.now(timezone.utc).isoformat(),demo=bool(demo),names=entries)
    validate(result)
    return result


def validate(data):
    if not isinstance(data,dict) or data.get('format')!=FORMAT or data.get('device')!='AF16Rig' or type(data.get('state_version')) is not int or data['state_version']!=18:
        raise ValueError('Not a supported AF16Rig name backup')
    if type(data.get('demo')) is not bool:raise ValueError('Backup must identify demo/device origin')
    entries=data.get('names')
    if not isinstance(entries,list) or not 1<=len(entries)<=len(NAME_SOURCES):raise ValueError('Backup must contain 1–60 names')
    seen=set();result=[]
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('Invalid backup entry')
        source=entry.get('source');parameter=name_parameter(source)
        if source in seen:raise ValueError('Duplicate name ID in backup')
        seen.add(source)
        if type(entry.get('parameter')) is not int or entry['parameter']!=parameter:raise ValueError('Backup channel/parameter mismatch')
        name=entry.get('name')
        if not isinstance(name,str) or any(not c.isprintable() for c in name) or len(name.encode('utf-8'))>31:raise ValueError('Invalid saved name text')
        result.append(dict(source=source,parameter=parameter,name=name))
    return sorted(result,key=lambda e:NAME_SOURCES.index(e['source']))


def load_backup(path):
    with open(path,'rb') as f:payload=f.read(MAX_FILE_BYTES+1)
    if len(payload)>MAX_FILE_BYTES:raise ValueError('Name backup is too large')
    data=json.loads(payload.decode('utf-8'));validate(data);return data


def restore_plan(data,records,demo=False):
    entries=validate(data)
    if data['demo'] and not demo:raise ValueError('Demo backups cannot be restored to hardware')
    changes=[]
    for entry in entries:
        source=entry['source']
        if source not in records:raise DeviceError(f'{source_label(source)} has not been read. Refresh names first.')
        current=stable_name(records[source],demo)
        if current==entry['name']:continue
        try:encode_name(entry['name'])
        except ValueError as error:raise ValueError(f'{source_label(source)}: {error}') from error
        changes.append(dict(source=source,expected=current,name=entry['name']))
    return changes
