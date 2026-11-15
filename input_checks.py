"""Build reversible tests for the active input signal paths."""
from functools import partial

from af16rig import DeviceError, front_source_status, mini_source_status


def topology(device):
    context = device.link_context()
    front = front_source_status(context)['sources']
    mini = mini_source_status(context)
    if front is None or mini is None:
        raise DeviceError('Input source selection could not be read')
    return (tuple(front + mini + ['rear'] * 12),
            device.read('rear_link'), device.read('front_line_link'),
            device.read('front_mic_link'))


def write_input(device, expected, channels, control, value):
    """Use existing UI setters and retain every member transaction."""
    sources = expected[0]
    transactions = []
    diagnostic = {'transactions': transactions, 'confirmed': False}
    with device.lock:
        try:
            for channel in channels:
                if topology(device) != expected:
                    raise DeviceError('Input source or link selection changed')
                kind = sources[channel - 1]
                device.last_write = None
                try:
                    if kind == 'rear':
                        logical = not value if control == 'pad' else value
                        device.write_input_bool(channel, control, logical)
                    elif control == 'instrument':
                        device.write_front_instrument(channel, value)
                    elif channel <= 2:
                        getattr(device, 'write_front_' + control)(channel, kind, value)
                    else:
                        device.write_mini_switch(channel, control, value)
                finally:
                    if device.last_write is not None:
                        transactions.append(device.last_write)
            diagnostic['confirmed'] = True
        finally:
            device.last_write = diagnostic


def input_button_checks(device):
    expected = topology(device)
    sources, rear_link, line_link, mic_link = expected
    checks = []
    consumed = set()
    for index, kind in enumerate(sources):
        if index in consumed:
            continue
        left = index & ~1
        link = rear_link if kind == 'rear' else mic_link if kind == 'mic' else line_link
        pair_mask = 3 << left
        # Front combo link is a single flag. Rear/minijack links use pair bits.
        linked = bool(link & 1) if kind != 'rear' and index < 2 else bool(link & pair_mask)
        members = (left, left + 1) if linked else (index,)
        if any(sources[member] != kind for member in members):
            raise DeviceError('Linked input members use different sources')
        consumed.update(members)
        channels = tuple(member + 1 for member in members)
        controls = ('phase', 'pad') if kind == 'line' and index in (2, 3) else ('phase', 'hpf', 'pad')
        if kind == 'line' and index < 2:
            controls += ('instrument',)
        prefix = 'rear' if kind == 'rear' else 'front_' + kind
        label = '/'.join(str(channel) for channel in channels)
        for control in controls:
            if kind == 'rear' and linked and control == 'phase':
                checks.append((f'rear input {channels[0]} phase (linked left)',
                               'rear_phase', left,
                               partial(write_input, device, expected, (channels[0],), control)))
                checks.append((f'rear input {channels[1]} phase (linked right)',
                               'rear_phase', left + 1, None))
                continue
            bit = members if linked else index
            checks.append((f'{kind} input {label} {control}', f'{prefix}_{control}', bit,
                           partial(write_input, device, expected, channels, control)))
    return checks
