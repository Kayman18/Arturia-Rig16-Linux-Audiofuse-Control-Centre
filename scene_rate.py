"""Optional Internal-clock rate in scenes; matched explicitly via idle ALSA."""
from contextlib import nullcontext
from af16rig import DemoAF16Rig,DeviceError
from clock_controls import CONFIG,RATES,demo_raw
from clock_status import read_register
from sample_rate import SUPPORTED,set_rate

def state(device):
    if isinstance(device,DemoAF16Rig):return demo_raw(device)
    return {k:read_register(device,k) for k in (*CONFIG,'internal_frequency')}

def read(device):
    raw=state(device)
    if raw.get('selected_source') not in (0,1,2) or raw.get('preferred_source') not in (0,1,2):raise DeviceError('Clock source unavailable')
    if raw['selected_source']!=0 or raw['preferred_source']!=0:return None
    code=raw.get('internal_frequency')
    if type(code) is not int or code not in range(1,7):raise DeviceError('Internal sample rate unavailable')
    return RATES[code]

def saved_rate(scene):
    for entry in scene['entries']:
        if entry['bus']=='sample_rate':return entry['values']['rate'][0]
    return None

def needed(target,current):
    rate=saved_rate(target)
    # A scene explicitly targeting external clock never tries to set its rate.
    clock=next((e for e in target['entries'] if e['bus']=='clock'),None)
    return rate is not None and (clock is None or clock['values']['clock_config'][0]//8==0) and rate!=saved_rate(current)

def apply(device,target,expected):
    if type(target) is not int or target not in SUPPORTED:raise ValueError('Scene has no supported Internal sample rate')
    with getattr(device,'lock',nullcontext()):
        if device.version!=18:raise DeviceError('Unsupported sample-rate state version')
        if read(device)!=expected:raise DeviceError('Sample rate changed after preview')
        raw=state(device)
        if raw['selected_source']!=0 or raw['preferred_source']!=0:raise DeviceError('Select Internal clock on the Clock page, then refresh the scene preview before matching sample rate')
        set_rate(device,target,raw)
        if read(device)!=target or read(device)!=target:raise DeviceError('Scene sample rate not confirmed; refresh device state')
    return target
