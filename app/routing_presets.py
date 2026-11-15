"""Portable, strictly validated known-output routing presets (no device writes)."""
from datetime import datetime, timezone
from routing_labels import SOURCE_LABELS, DESTINATION_LABELS

FORMAT='af16rig-output-routing-v1'

def validate_preset(preset):
    if not isinstance(preset,dict) or preset.get('format')!=FORMAT:
        raise ValueError('Not an AF16Rig output routing preset')
    if preset.get('state_version')!=18 or type(preset.get('state_version')) is not int:
        raise ValueError('Preset requires state version 18')
    if type(preset.get('demo')) is not bool:
        raise ValueError('Preset must declare whether it is a demo')
    routes=preset.get('routes')
    if not isinstance(routes,list) or not 1<=len(routes)<=60:
        raise ValueError('Preset must contain 1–60 mapped routes')
    seen=set()
    for route in routes:
        if not isinstance(route,dict) or set(route)!={'destination','source_code'}:
            raise ValueError('Each route needs exactly destination and source_code')
        index,code=route['destination'],route['source_code']
        if type(index) is not int or index not in DESTINATION_LABELS or type(code) is not int or code not in SOURCE_LABELS:
            raise ValueError('Preset contains an unmapped destination or source')
        if index in seen:raise ValueError('Preset repeats a destination')
        seen.add(index)
    return preset

def make_preset(capture):
    if capture.get('status')!='stable' or capture.get('state_version')!=18:
        raise ValueError('Read complete, stable routing first')
    values=capture['reads']['second']['values']
    routes=[dict(destination=i,source_code=values[f'output_source[{i}]']) for i in DESTINATION_LABELS
            if values.get(f'output_source[{i}]') in SOURCE_LABELS]
    return validate_preset(dict(format=FORMAT,state_version=18,demo=bool(capture.get('demo')),
                               created_utc=datetime.now(timezone.utc).isoformat(),routes=routes))

def preview(preset,capture):
    validate_preset(preset)
    if capture.get('status')!='stable' or capture.get('state_version')!=18:
        raise ValueError('Read complete, stable routing before loading a preset')
    if preset['demo']!=bool(capture.get('demo')):
        raise ValueError('Demo and hardware presets cannot be mixed')
    values=capture['reads']['second']['values']
    changes=[]
    for route in preset['routes']:
        i,target=route['destination'],route['source_code']
        current=values.get(f'output_source[{i}]')
        if current not in SOURCE_LABELS:
            raise ValueError(f'{DESTINATION_LABELS[i]} has an unmapped current source; cannot apply this preset')
        if current!=target:changes.append(dict(destination=i,source_code=target,expected_source=current))
    return sorted(changes,key=lambda x:x['destination'])


def preflight(device, changes):
    """Recheck every original route before the first OUT; never writes."""
    if device.version!=18:raise ValueError('Unsupported routing state version')
    if not isinstance(changes,list) or not 1<=len(changes)<=60:raise ValueError('No valid preset changes')
    seen=set()
    for route in changes:
        if not isinstance(route,dict) or set(route)!={'destination','source_code','expected_source'}:
            raise ValueError('Invalid preset change')
        i,target,current=route['destination'],route['source_code'],route['expected_source']
        if (type(i) is not int or i not in DESTINATION_LABELS or i in seen or
                type(target) is not int or target not in SOURCE_LABELS or
                type(current) is not int or current not in SOURCE_LABELS):
            raise ValueError('Invalid preset change')
        seen.add(i)
    for route in changes:
        if device.read('output_source',route['destination'])!=route['expected_source']:
            raise ValueError('A route changed after preview. Read routing and load the preset again.')
