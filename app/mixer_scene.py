"""Main/Cue mixer scene files: levels, pan, flags and Main Aux sends."""
import json
from contextlib import nullcontext
from datetime import datetime,timezone
from af16rig import DemoAF16Rig,DeviceError
from digital_mixer import mixer_device
from fader_scene import topology,addresses as mixer_addresses,validate_layout,validate_address as validate_mixer_address,unique_keys

LEGACY_FORMAT='af16rig-mixer-scene-v1'
MASTER_FORMAT='af16rig-mixer-scene-v2'
ROUTING_FORMAT='af16rig-mixer-scene-v3'
NAMES_FORMAT='af16rig-mixer-scene-v4'
MONITOR_FORMAT='af16rig-mixer-scene-v5'
TRIM_FORMAT='af16rig-mixer-scene-v6'
OUTPUT_FORMAT='af16rig-mixer-scene-v7'
INPUT_FORMAT='af16rig-mixer-scene-v8'
FILTER_FORMAT='af16rig-mixer-scene-v9'
INSTRUMENT_FORMAT='af16rig-mixer-scene-v10'
AB_FORMAT='af16rig-mixer-scene-v11'
CLOCK_FORMAT='af16rig-mixer-scene-v12'
OUTPUT_LINK_FORMAT='af16rig-mixer-scene-v13'
REAR_LINK_FORMAT='af16rig-mixer-scene-v14'
FRONT_LINK_FORMAT='af16rig-mixer-scene-v15'
FORMAT='af16rig-mixer-scene-v16'
import scene_rate
import clock_scene
import speaker_ab_scene as speaker_ab
import mixer_scene_inputs as inputs
import mixer_scene_outputs as outputs
import speaker_trim
import mixer_scene_monitor as monitor
from channel_names import NAME_SOURCES
from name_edit import read_name,encode_name,rename
from name_backup import stable_name
from routing_labels import SOURCE_LABELS,DESTINATION_LABELS
import mixer_scene_masters as masters
MAX_BYTES=262144
BASE=('level','pan','mute','solo')
SENDS=tuple(f'send{a}_{kind}' for a in range(1,5) for kind in ('level','mute'))

def route_addresses(layout):
    return mixer_addresses(layout)+[dict(bus='routing',source=d,stereo=False) for d in sorted(DESTINATION_LABELS)]

def name_addresses(layout):
    return route_addresses(layout)+[dict(bus='names',source=s,stereo=False) for s in NAME_SOURCES]

def monitor_addresses(layout):
    return name_addresses(layout)+[dict(bus=b,source=0,stereo=False) for b in ('monitor','phones')]

def trim_addresses(layout):
    return monitor_addresses(layout)+[dict(bus='speaker_b',source=0,stereo=False)]

def output_addresses(layout):
    return trim_addresses(layout)+[dict(bus='outputs',source=s,stereo=True) for s in (3,5,7,9)]

def input_addresses(layout):
    return output_addresses(layout)+[dict(bus='inputs',source=s,stereo=True) for s in range(1,17,2)]

def ab_addresses(layout):
    return input_addresses(layout)+[dict(bus='speaker_ab',source=0,stereo=False)]

def clock_addresses(layout):
    return ab_addresses(layout)+[dict(bus='clock',source=0,stereo=False)]

def addresses(layout):
    return clock_addresses(layout)+[dict(bus='sample_rate',source=0,stereo=False)]

def validate_address(layout,address):
    if address.get('bus')=='inputs':
        if (set(address)!={'bus','source','stereo'} or type(address['source']) is not int
                or address['source'] not in range(1,17,2) or address['stereo'] is not True):
            raise ValueError('Invalid input scene address')
        return address
    if address.get('bus')=='outputs':
        if (set(address)!={'bus','source','stereo'} or type(address['source']) is not int
                or address['source'] not in (3,5,7,9) or address['stereo'] is not True):
            raise ValueError('Invalid analog output scene address')
        return address
    if address.get('bus') in ('monitor','phones','speaker_b','speaker_ab','clock','sample_rate'):
        if (set(address)!={'bus','source','stereo'} or type(address['source']) is not int
                or address['source']!=0 or address['stereo'] is not False):
            raise ValueError('Invalid monitor/phones scene address')
        return address
    if address.get('bus')=='names':
        if (set(address)!={'bus','source','stereo'} or type(address['source']) is not int
                or address['source'] not in NAME_SOURCES or address['stereo'] is not False):
            raise ValueError('Invalid name scene address')
        return address
    if address.get('bus')!='routing':return validate_mixer_address(layout,address)
    if (set(address)!={'bus','source','stereo'} or type(address['source']) is not int
            or address['source'] not in DESTINATION_LABELS or address['stereo'] is not False):
        raise ValueError('Invalid routing scene address')
    return address

def valid_value(field,source,value):
    if field=='rate':return value is None or type(value) is int and value in scene_rate.SUPPORTED
    if field in ('hpf','instrument') and value is None:return True
    if field=='kind':return value in ('rear','mic','line','mini')
    if field=='input_link':return value is None or type(value) is int and value in (0,1)
    if field=='name':
        return isinstance(value,str) and all(c.isprintable() for c in value) and len(value.encode('utf-8'))<=31
    if type(value) is not int:return False
    if field=='route':return value in SOURCE_LABELS
    low,high=bounds(field,source)
    return low<=value<=high

def fields(address):
    if address['bus']=='sample_rate':return ('rate',)
    if address['bus']=='clock':return ('clock_config',)
    if address['bus']=='speaker_ab':return ('ab_config',)
    if address['bus']=='inputs':return ('kind','input_link','gain','pad','phase','hpf','instrument')
    if address['bus']=='outputs':return ('level','link')
    if address['bus']=='speaker_b':return ('trim',)
    if address['bus']=='monitor':return ('level','mute','dim','mono','dim_depth')
    if address['bus']=='phones':return ('level',)
    if address['bus']=='names':return ('name',)
    if address['bus']=='routing':return ('route',)
    if address['source']==0:return ('level',)+(masters.FIELDS if address['bus']=='main' else ())
    return BASE+(SENDS if address['bus']=='main' else ())
def bounds(field,source):return (0,23) if field=='clock_config' else (0,15) if field=='ab_config' else (0,14080) if field=='gain' else (-3072,3072) if field=='trim' else (0,254) if field=='pan' else (0,1) if field in ('instrument','phase','hpf','pad','link','mute','solo','dim','mono','dim_depth','cue_enabled','aux_link12','aux_link34') or field.endswith(('_mute','_pre')) else (-15360,0 if source==0 else 1536)
def native(bus,source,field):
    if source==0:return bus+'_master',False
    if field.startswith('send'):
        aux=field[4];return (f'aux{aux}_send_level',False) if field.endswith('_level') else (f'main_channel_send{aux}',True)
    return bus+'_channel_'+field,field in ('mute','solo')

def read_value(device,bus,source,field):
    if bus=='sample_rate':return scene_rate.read(device)
    if bus=='clock':return clock_scene.read(device)
    if bus=='speaker_ab':return speaker_ab.read(device)
    if bus=='inputs':return inputs.read(device,source,field)
    if bus=='outputs':return outputs.read(device,source,field)
    if bus=='speaker_b':return speaker_trim.read(device)
    if bus in ('monitor','phones'):return monitor.read(device,bus,field)
    if bus=='names':return stable_name(read_name(device,source),isinstance(device,DemoAF16Rig))
    if bus=='routing':return device.read('output_source',source)
    if source==0 and field in masters.FIELDS:return masters.read(device,field)
    name,bit=native(bus,source,field);index=source-1
    if isinstance(device,DemoAF16Rig) and source<=16:
        if source==0:return getattr(device,bus+'_master',-12*256)
        if field=='level':return getattr(device,'mix_levels',{}).get((bus,source),-12*256)
        if field=='pan':return getattr(device,'pan_positions',{}).get((bus,source),127)
        if field.endswith('_level'):return getattr(device,'send_levels',{}).get((source,int(field[4])),-12*256)
        return (getattr(device,f'send{field[4]}' if field.startswith('send') else name,0)>>index)&1
    facade=mixer_device(device,source)
    raw=facade.read(name) if source==0 or bit else facade.read(name,index)
    if bit:return (raw>>index)&1
    return raw if field=='pan' or raw<32768 else raw-65536

def write_value(device,bus,source,field,value):
    if bus in ('routing','names','monitor','phones','speaker_b','outputs','inputs','speaker_ab','clock','sample_rate'):raise ValueError('Routing requires an expected source')
    if source==0 and field in masters.FIELDS:return masters.write(device,field,value)
    name,bit=native(bus,source,field);index=source-1
    if isinstance(device,DemoAF16Rig) and source<=16:
        if source==0:setattr(device,bus+'_master',value)
        elif field in ('level','pan') or field.endswith('_level'):
            attr='mix_levels' if field=='level' else 'pan_positions' if field=='pan' else 'send_levels'
            if not hasattr(device,attr):setattr(device,attr,{})
            key=(source,int(field[4])) if field.startswith('send') else (bus,source)
            getattr(device,attr)[key]=value
        else:
            attr=f'send{field[4]}' if field.startswith('send') else name;mask=getattr(device,attr,0)
            setattr(device,attr,mask|(1<<index) if value else mask&~(1<<index))
    else:mixer_device(device,source)._write_and_confirm(name,value&65535,0 if source==0 else index)

def checked_values(address,values,legacy=False,old_inputs=False,old_filters=False):
    expected=set(fields(address))
    if legacy and address['source']==0:expected={'level'}
    if address['bus']=='inputs':
        if old_inputs:expected={'kind','input_link','gain','pad'}
        elif old_filters:expected.remove('instrument')
    if not isinstance(values,dict) or set(values)!=expected:raise ValueError('Scene mixer fields are missing or unsupported')
    count=2 if address['stereo'] else 1
    for field,items in values.items():
        low,high=bounds(field,address['source'])
        if address['bus']=='outputs' and field=='level' and isinstance(items,list) and any(type(v) is not int or v>0 for v in items):raise ValueError('Invalid output level')
        if not isinstance(items,list) or len(items)!=count or any(not valid_value(field,address['source'],v) for v in items):raise ValueError('Unsupported scene '+field)
    if address['bus']=='inputs':
        for i,kind in enumerate(values['kind']):
            if 'instrument' in values and ((kind=='line' and address['source']+i in (1,2)) == (values['instrument'][i] is None)):raise ValueError('Unsupported saved instrument mode')
            if not old_inputs and ((kind=='mini') != (values['hpf'][i] is None)):raise ValueError('Unsupported saved input HPF')
            _,_,units,high=inputs.preamp.spec(address['source']+i,kind)
            if values['gain'][i]>high*256 or (units==1 and values['gain'][i]%256):raise ValueError('Unsupported saved input gain')
    return values

def read_entry(device,layout,address):
    validate_address(layout,address)
    if topology(device)!=layout:raise DeviceError('Mixer layout changed; capture again')
    sources=[address['source']+i for i in range(2 if address['stereo'] else 1)]
    def read():return {field:[read_value(device,address['bus'],s,field) for s in sources] for field in fields(address)}
    first=read();second=read()
    if first!=second:raise DeviceError('Mixer control changed during capture; read again')
    checked_values(address,second)
    return dict(address,values=second)

def validate(scene):
    if (not isinstance(scene,dict) or scene.get('format') not in (FORMAT,FRONT_LINK_FORMAT,REAR_LINK_FORMAT,OUTPUT_LINK_FORMAT,CLOCK_FORMAT,AB_FORMAT,INSTRUMENT_FORMAT,FILTER_FORMAT,INPUT_FORMAT,OUTPUT_FORMAT,TRIM_FORMAT,MONITOR_FORMAT,NAMES_FORMAT,ROUTING_FORMAT,MASTER_FORMAT,LEGACY_FORMAT) or scene.get('device')!='AF16Rig'
        or type(scene.get('state_version')) is not int or scene['state_version']!=18 or type(scene.get('demo')) is not bool):raise ValueError('Not an AF16Rig mixer scene')
    layout=validate_layout(scene.get('layout'));expected=addresses(layout) if scene['format']==FORMAT else clock_addresses(layout) if scene['format'] in (FRONT_LINK_FORMAT,REAR_LINK_FORMAT,OUTPUT_LINK_FORMAT,CLOCK_FORMAT) else ab_addresses(layout) if scene['format']==AB_FORMAT else input_addresses(layout) if scene['format'] in (INSTRUMENT_FORMAT,FILTER_FORMAT,INPUT_FORMAT) else output_addresses(layout) if scene['format']==OUTPUT_FORMAT else trim_addresses(layout) if scene['format']==TRIM_FORMAT else monitor_addresses(layout) if scene['format']==MONITOR_FORMAT else name_addresses(layout) if scene['format']==NAMES_FORMAT else route_addresses(layout) if scene['format']==ROUTING_FORMAT else mixer_addresses(layout);entries=scene.get('entries')
    if not isinstance(entries,list) or len(entries)!=len(expected):raise ValueError('Scene has missing or extra mixer strips')
    seen=set()
    for e in entries:
        if not isinstance(e,dict) or set(e)!={'bus','source','stereo','values'}:raise ValueError('Invalid mixer scene entry')
        a={k:e[k] for k in ('bus','source','stereo')};validate_address(layout,a)
        if a not in expected:raise ValueError('Unsupported scene address for this format')
        key=e['bus'],e['source']
        if key in seen:raise ValueError('Duplicate scene strip')
        seen.add(key);checked_values(a,e['values'],scene['format']==LEGACY_FORMAT,scene['format']==INPUT_FORMAT,scene['format']==FILTER_FORMAT)
    return scene

def make_scene(layout,entries,demo=False):
    return validate(json.loads(json.dumps(dict(format=FORMAT,device='AF16Rig',state_version=18,demo=bool(demo),
        created_utc=datetime.now(timezone.utc).isoformat(),layout=layout,entries=entries))))

def load_scene(path):
    with open(path,'rb') as f:raw=f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Mixer scene exceeds 256 KiB')
    try:return validate(json.loads(raw.decode('utf-8'),object_pairs_hook=unique_keys))
    except RecursionError as error:raise ValueError('Invalid JSON nesting') from error

def plan(saved,current):
    validate(saved);validate(current)
    if saved['demo']!=current['demo']:raise ValueError('Demo and hardware scenes cannot be mixed')
    if saved['layout']!=current['layout']:raise ValueError('Select matching mixer sources and stereo links before recall')
    if scene_rate.needed(saved,current):raise ValueError('Match sample rate before recalling settings')
    before={(e['bus'],e['source']):e for e in current['entries']};changes=[]
    for e in saved['entries']:
        if e['bus']=='sample_rate':continue
        old=before.get((e['bus'],e['source']))
        if old is None:raise ValueError('Read a complete current mixer scene before recall')
        if e['bus']=='inputs':
            if e['values']['kind']!=old['values']['kind']:raise ValueError('Match active input sources before recall')
            if e['values']['input_link']!=old['values']['input_link']:
                if saved['format'] not in (FORMAT,FRONT_LINK_FORMAT,REAR_LINK_FORMAT):raise ValueError('Match active input hardware links before recall for older scenes')
                if saved['format']==REAR_LINK_FORMAT and e['values']['kind']!=['rear','rear']:raise ValueError('Older scene link recall requires two rear inputs')
                inputs.validate_link_recall(e['values'],old['values'])
                state=json.loads(json.dumps(old['values'] if e['values']['input_link']==[0,0] else e['values']))
                state['input_link']=list(old['values']['input_link'])
                changes.append(dict(bus='inputs',source=e['source'],stereo=True,field='input_link',values=list(e['values']['input_link']),expected=list(old['values']['input_link']),input_state=state))
        if e['bus']=='outputs' and saved['format'] in (FORMAT,FRONT_LINK_FORMAT,REAR_LINK_FORMAT,OUTPUT_LINK_FORMAT):
            if e['values']!=old['values']:
                outputs.validate_pair(e['values'],target=True)
                changes.append(dict(bus='outputs',source=e['source'],stereo=True,field='configuration',
                                    values=json.loads(json.dumps(e['values'])),expected=json.loads(json.dumps(old['values']))))
            continue
        if e['bus']=='outputs' and e['values']['link']!=old['values']['link']:raise ValueError('Match analog output stereo links before recall')
        for field,target in e['values'].items():
            if e['bus']=='inputs' and field=='input_link':continue
            if field not in old['values']:raise ValueError('Read a complete current mixer scene before recall')
            if field=='name' and target!=old['values'][field]:encode_name(target[0])
            if target!=old['values'][field]:changes.append(dict(bus=e['bus'],source=e['source'],stereo=e['stereo'],field=field,values=list(target),expected=list(old['values'][field])))
    for c in changes:
        if c['bus']=='inputs' and c['field']!='input_link':
            c['input_context']={f:list(before[c['bus'],c['source']]['values'][f]) for f in ('kind','input_link')}
            if any(x['bus']=='inputs' and x['source']==c['source'] and x['field']=='input_link' for x in changes):c['input_context']['input_link']=[0,0]
        if c['bus']=='outputs' and c['field']!='configuration':c['output_links']=list(before[c['bus'],c['source']]['values']['link'])
    # Set levels/pans before restoring mute/solo and send switches.
    return sorted(changes,key=lambda c:(-2 if c['values']==[0,0] else -.5) if c['bus']=='inputs' and c['field']=='input_link' else 10 if c['bus']=='clock' else 4.75 if c['bus']=='speaker_ab' else -1 if c['bus']=='inputs' else 4.25 if c['bus']=='outputs' else 4.5 if c['bus']=='speaker_b' else (5+{'level':0,'dim_depth':1,'mono':2,'dim':3,'mute':4}[c['field']]) if c['bus'] in ('monitor','phones') else 4 if c['field']=='name' else 3 if c['field']=='route' else 2 if c['field'].startswith('aux_link') else int(bounds(c['field'],c['source'])==(0,1)))

def apply_entry(device,layout,change):
    if isinstance(change,dict) and change.get('bus')=='sample_rate':
        if set(change)!={'bus','source','stereo','field','values','expected'} or change.get('source')!=0 or type(change.get('source')) is not int or change.get('stereo') is not False or change.get('field')!='rate':raise ValueError('Invalid rate change')
        for key in ('values','expected'):
            if not isinstance(change[key],list) or len(change[key])!=1 or not valid_value('rate',0,change[key][0]):raise ValueError('Invalid scene rate')
        if topology(device)!=layout:raise DeviceError('Mixer layout changed; refresh before matching sample rate')
        scene_rate.apply(device,change['values'][0],change['expected'][0])
        return {k:change[k] for k in ('bus','source','stereo','field','values')}

    if isinstance(change,dict) and change.get('bus')=='mixer_layout':
        import scene_layout
        return scene_layout.apply_step(device,layout,change)

    if isinstance(change,dict) and change.get('bus')=='input_sources':
        import scene_sources
        if set(change)!={'bus','source','stereo','field','values','expected'} or change.get('source')!=0 or type(change.get('source')) is not int or change.get('stereo') is not False or change.get('field')!='sources':raise ValueError('Invalid source matching change')
        def layout_guard():
            if topology(device)!=layout:raise DeviceError('Mixer layout changed; stop source matching')
        scene_sources.apply(device,change['values'],change['expected'],layout_guard)
        return {k:change[k] for k in ('bus','source','stereo','field','values')}

    if isinstance(change,dict) and change.get('bus')=='inputs' and change.get('field')=='input_link':
        if set(change)!={'bus','source','stereo','field','values','expected','input_state'}:raise ValueError('Invalid input link change')
        address={k:change[k] for k in ('bus','source','stereo')};validate_address(layout,address)
        checked_values(address,change['input_state'])
        if change['expected']!=change['input_state']['input_link']:raise ValueError('Invalid expected input link')
        target=dict(change['input_state'],input_link=change['values'])
        checked_values(address,target);inputs.validate_link_recall(target,change['input_state'])
        def layout_guard():
            if topology(device)!=layout:raise DeviceError('Mixer layout changed; stop recall')
        inputs.apply_link(device,address['source'],change['values'],change['input_state'],layout_guard)
        return {k:change[k] for k in ('bus','source','stereo','field','values')}

    if isinstance(change,dict) and change.get('bus')=='outputs' and change.get('field')=='configuration':
        if set(change)!={'bus','source','stereo','field','values','expected'}:raise ValueError('Invalid output configuration change')
        address={k:change[k] for k in ('bus','source','stereo')};validate_address(layout,address)
        def layout_guard():
            if topology(device)!=layout:raise DeviceError('Mixer layout changed; stop recall')
        outputs.apply_pair(device,address['source'],change['values'],change['expected'],layout_guard)
        return {k:change[k] for k in ('bus','source','stereo','field','values')}

    if not isinstance(change,dict) or set(change)!=({'bus','source','stereo','field','values','expected'} | ({'output_links'} if change.get('bus')=='outputs' else {'input_context'} if change.get('bus')=='inputs' else set())):raise ValueError('Invalid mixer scene change')
    address={k:change[k] for k in ('bus','source','stereo')};validate_address(layout,address)
    field=change['field']
    if address['bus']=='inputs':
        ctx=change['input_context']
        if field not in ('gain','pad','phase','hpf','instrument') or not isinstance(ctx,dict) or set(ctx)!={'kind','input_link'}:raise ValueError('Invalid input scene context')
        for f,v in ctx.items():
            if not isinstance(v,list) or len(v)!=2 or any(not valid_value(f,address['source'],x) for x in v):raise ValueError('Invalid input context')
    if address['bus']=='outputs':
        if field!='level' or not isinstance(change['output_links'],list) or len(change['output_links'])!=2 or any(type(v) is not int or v not in (0,1) for v in change['output_links']):raise ValueError('Invalid output scene context')
        if any(not isinstance(change[k],list) for k in ('values','expected')) or any(type(v) is not int or v>0 for k in ('values','expected') for v in change[k]):raise ValueError('Invalid output level')
    if field not in fields(address):raise ValueError('Unsupported scene field')
    low,high=bounds(field,address['source']);count=2 if address['stereo'] else 1
    for key in ('values','expected'):
        values=change[key]
        if not isinstance(values,list) or len(values)!=count or any(not valid_value(field,address['source'],v) for v in values):raise ValueError('Invalid scene values')
    if address['bus']=='inputs':
        for i,kind in enumerate(change['input_context']['kind']):
            if field=='instrument' and any((kind=='line' and address['source']+i in (1,2))==(v is None) for v in (change['values'][i],change['expected'][i])):raise ValueError('Unsupported instrument mode')
            if field=='hpf' and any((kind=='mini')!=(v is None) for v in (change['values'][i],change['expected'][i])):raise ValueError('Unsupported input HPF')
            _,_,units,high=inputs.preamp.spec(address['source']+i,kind)
            if field=='gain' and any(v>high*256 or (units==1 and v%256) for v in (change['values'][i],change['expected'][i])):raise ValueError('Unsupported input gain')
    if field=='name' and change['values']!=change['expected']:encode_name(change['values'][0])
    with getattr(device,'lock',nullcontext()):
        def read():
            if address['bus']=='inputs':inputs.guard(device,address['source'],change['input_context'])
            if address['bus']=='outputs':outputs.guard(device,address['source'],change['output_links'])
            if topology(device)!=layout:raise DeviceError('Mixer layout changed; stop recall')
            return [read_value(device,address['bus'],address['source']+i,field) for i in range(count)]
        if read()!=change['expected'] or read()!=change['expected']:raise DeviceError('Mixer setting changed after preview; stop recall')
        for i,target in enumerate(change['values']):
            current=read()
            if current[i]==target:continue
            if current[i]!=change['expected'][i]:raise DeviceError('Mixer setting changed during recall; inspect current state')
            if address['bus']=='clock':clock_scene.apply(device,target,current[i])
            elif address['bus']=='speaker_ab':speaker_ab.apply(device,target,current[i])
            elif address['bus']=='inputs':inputs.write(device,address['source']+i,change['input_context']['kind'][i],field,target)
            elif address['bus']=='outputs':outputs.set_raw(device,address['source']+i,target,current[i])
            elif address['bus']=='speaker_b':speaker_trim.set_raw(device,target,current[i])
            elif address['bus'] in ('monitor','phones'):monitor.write(device,address['bus'],field,target,current[i])
            elif field=='name':rename(device,address['source'],target,current[i])
            elif field=='route':device.write_output_route(address['source'],target,expected_source=current[i])
            else:write_value(device,address['bus'],address['source']+i,field,target)
        if read()!=change['values'] or read()!=change['values']:raise DeviceError('Mixer recall not confirmed; earlier writes may remain')
    return {k:change[k] for k in ('bus','source','stereo','field','values')}
