"""Bounded read-only capture of AF16Rig analog and ADAT input/output name parameters.

Group 2 and parameter ids are recovered from AFCC. Scalar request/index layout
is established by its read wrapper. Text packing is a candidate until hardware
capture confirms it. Explicit rename is implemented separately in name_edit.py.
"""
import argparse
import ctypes as C
import json
from datetime import datetime,timezone
from pathlib import Path
from af16rig import AF16Rig,DeviceError,DeviceDisconnected

MAX_WORDS=16
# IDs1..32 retain mixer input identities; output IDs65..92 never alias USB inputs.
NAME_PARAMETERS={**{s:s-1 for s in range(1,17)}, **{s:s+11 for s in range(17,33)},
                 **{s:s-49 for s in range(65,77)}, **{s:s-33 for s in range(77,93)}}
NAME_SOURCES=tuple(NAME_PARAMETERS)
NAME_SOURCE_COUNT=len(NAME_SOURCES)

def name_parameter(source):
    if type(source) is not int or source not in NAME_PARAMETERS:
        raise ValueError('Unsupported input/output name ID')
    return NAME_PARAMETERS[source]

def source_label(source,stereo=False):
    name_parameter(source)
    bank='ANALOG' if source<=16 else 'ADAT' if source<=32 else 'ANALOG OUT SLOT' if source<=76 else 'ADAT OUT'
    number=source if source<=16 else source-16 if source<=32 else source-64 if source<=76 else source-76
    return f'{bank} {number}/{number+1}' if stereo else f'{bank} {number}'


def decode_words(words):
    if not words or words[-1]!=0:return {'candidate':None,'encoding':None,'status':'unterminated'}
    payload=words[:-1];candidates={}
    packed=b''.join(w.to_bytes(2,'little') for w in payload)
    head,sep,tail=packed.partition(b'\0')
    if not sep or not any(tail):
        try:
            value=head.decode('utf-8')
            if all(c.isprintable() for c in value):candidates[value]='packed UTF-8'
        except UnicodeDecodeError:pass
    if all(w<=255 for w in payload):
        try:
            value=bytes(payload).decode('utf-8')
            if all(c.isprintable() for c in value):candidates.setdefault(value,'one byte per word')
        except UnicodeDecodeError:pass
    if len(candidates)!=1:return {'candidate':None,'encoding':None,'status':'ambiguous' if candidates else 'unrecognized'}
    value,encoding=next(iter(candidates.items()))
    return {'candidate':value,'encoding':encoding,'status':'candidate' if value else 'blank'}


def read_word(device,parameter,index):
    if type(parameter) is not int or parameter not in NAME_PARAMETERS.values() or type(index) is not int or not 0<=index<MAX_WORDS:
        raise ValueError('Only bounded analog/ADAT input/output name reads are allowed')
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Device is disconnected')
        if device.version!=18:raise DeviceError('Unsupported state version for name capture')
        data=(C.c_ubyte*2)()
        rc=device.lib.libusb_control_transfer(device.handle,0xc0,0x92,parameter,index,data,2,1000)
        if rc==-4:raise DeviceDisconnected('Device disconnected during name capture')
        if rc<0:raise DeviceError('Name read: '+device.error(rc))
        if rc!=2:raise DeviceError(f'Name read returned {rc} bytes; expected 2')
        return int.from_bytes(data,'little')


def read_one(device,source,reader=read_word):
    parameter=name_parameter(source)
    record={'source':source,'parameter':parameter,'passes':[],'candidate':None,'status':'unread','write_requests':0}
    try:
        for _ in range(2):
            words=[];record['passes'].append(words)
            for index in range(MAX_WORDS):
                word=reader(device,parameter,index);words.append(word)
                if word==0:break
        if record['passes'][0]!=record['passes'][1]:record['status']='changed_during_read'
        else:record.update(decode_words(record['passes'][1]))
    except DeviceDisconnected:raise
    except (DeviceError,ValueError) as error:
        record.update(status='read_error',error=str(error))
    return record


def report(records,demo=False):
    return dict(format='af16rig-channel-names-v1',build='BETA RC',utc=datetime.now(timezone.utc).isoformat(),
                demo=demo,physical_text_format_verified=False,write_requests=sum(r.get('write_requests',0) for r in records),
                method={'request':'0x92','group':2,'parameters':'0–15 analog inputs; 16–27 analog output slots; 28–43 ADAT inputs; 44–59 ADAT outputs','max_words':MAX_WORDS,'passes':2},
                names=records)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('AF16Rig-channel-names.json'))
    args=parser.parse_args();device=AF16Rig();records=[];error=None
    try:
        device.open()
        for source in NAME_SOURCES:
            record=read_one(device,source);records.append(record)
            print(f"{source_label(source)}: {record['candidate']!r} ({record['status']})")
            if record['status']=='read_error':break  # No repeated unsupported-request probing.
    except (DeviceError,OSError) as exc:error=str(exc)
    finally:device.close()
    result=report(records)
    if error:result['error']=error
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print('Saved:',args.output)
    return 0 if len(records)==NAME_SOURCE_COUNT and all(r['status'] in ('candidate','blank') for r in records) else 1

if __name__=='__main__':raise SystemExit(main())
