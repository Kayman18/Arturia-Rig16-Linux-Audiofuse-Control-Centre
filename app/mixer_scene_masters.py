"""Extra scene fields mapped to existing Aux/Cue controls."""
from af16rig import DemoAF16Rig

FIELDS=tuple(f'aux{a}_{kind}' for a in range(1,5) for kind in ('level','mute','pre'))+('aux_link12','aux_link34','cue_enabled')

def address(field):
    if field not in FIELDS:raise ValueError('Unsupported scene master field')
    if field=='cue_enabled':return 'cue_enabled',0,False
    if field.startswith('aux_link'):return 'aux_link',1 if field.endswith('12') else 3,True
    bus,kind=field.split('_');index=int(bus[3])-1
    return (bus+'_master',0,False) if kind=='level' else ('aux_'+kind,index,True)

def read(device,field):
    name,index,bit=address(field)
    if isinstance(device,DemoAF16Rig):
        if name=='cue_enabled':raw=getattr(device,name,0)
        elif bit:raw=getattr(device,name+'_mask',0)
        else:raw=getattr(device,name,-12*256)&65535
    else:raw=device.read(name)
    if bit:return (raw>>index)&1
    return raw-65536 if field.endswith('_level') and raw>=32768 else raw

def write(device,field,value):
    name,index,bit=address(field)
    if field=='cue_enabled':return device.write_cue_enabled(bool(value))
    if name=='aux_link':return device.write_aux_link(index,bool(value))
    if name=='aux_mute':return device.write_aux_mute('aux'+str(index+1),bool(value))
    if name=='aux_pre':return device.write_aux_pre('aux'+str(index+1),bool(value))
    if isinstance(device,DemoAF16Rig):setattr(device,name,value);return value
    return device.step_mixer_master(name[:-7],1,target_raw=value)
