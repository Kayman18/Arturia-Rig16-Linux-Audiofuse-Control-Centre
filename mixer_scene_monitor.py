"""Scene adapters for existing Monitor and Phones controls."""
from af16rig import DemoAF16Rig
from monitor_level import set_level as set_monitor
from phones_level import set_level as set_phones

def read(device,bus,field):
    demo=isinstance(device,DemoAF16Rig)
    if bus=='phones':
        raw=device.headphones_snapshot()['knob_raw'] if demo else device.read('phones_knob')
    elif field=='level':raw=device.read('speaker_level')
    elif field=='dim_depth':return device.monitor_settings_snapshot()['dim_depth_raw'] if demo else device.read('dim_depth')
    else:return device.read(field)
    return raw-65536 if raw>=32768 else raw

def write(device,bus,field,value,expected):
    if bus=='phones':return set_phones(device,value/256,expected&65535)
    if field=='level':return set_monitor(device,value/256)
    if field=='dim_depth':return device.write_dim_depth(-10 if value==0 else -20)
    return device.write_bool(field,bool(value))
