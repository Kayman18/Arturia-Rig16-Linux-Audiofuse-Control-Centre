"""Exercise included mixer strips and sends with exact level restoration."""
from functools import partial
from check_selection import case_selected

from af16rig import CHANNEL_MAX_RAW, DeviceError
from level_checks import level_group


def check_routing(device, bus, show, stereo, aux_link):
    if (device.read(bus + '_channel_show'), device.read(bus + '_channel_stereo')) != (show, stereo):
        raise DeviceError('Mixer inclusion or stereo selection changed')
    if device.read('aux_link') != aux_link:
        raise DeviceError('Aux link selection changed')


def mixer_level_suite(device, report, checkpoint, *, only=()):
    checks = []
    aux_link = device.read('aux_link')
    for bus in ('main', 'cue'):
        show = device.read(bus + '_channel_show')
        stereo = device.read(bus + '_channel_stereo')
        guard = partial(check_routing, device, bus, show, stereo, aux_link)
        for index in range(16):
            paired = bool(stereo & (1 << (index // 2)))
            if paired:
                if index % 2 or show & (3 << index):
                    continue
                indices = (index, index + 1)
                channel_step = partial(device.step_stereo_channel_level, bus, index + 1)
            elif show & (1 << index):
                indices = (index,)
                channel_step = partial(device.step_mix_channel_level, bus, index + 1)
            else:
                continue
            fields = [(bus + '_channel_level', channel_step, 'level')]
            if bus == 'main':
                send_step = device.step_stereo_send_level if paired else device.step_send_level
                fields.extend((f'aux{aux}_send_level', partial(send_step, bus, index + 1, aux),
                               f'Aux {aux} send level') for aux in range(1, 5))
            label = '/'.join(str(member + 1) for member in indices)
            for field, writer, title in fields:
                members = [(field, member) for member in indices]
                # The level_group lock, range and routing guards protect these
                # absolute restores, including a partially completed stereo step.
                restores = [partial(device._write_and_confirm, field, index=member)
                            for member in indices]
                linked_send = field.startswith('aux') and bool(
                    aux_link & (1 << (1 if int(field[3]) <= 2 else 3)))
                checks.append((f'{bus} {label} {title}', members,
                               [writer] * len(indices), restores, guard, linked_send))
    checks = [check for check in checks if case_selected(check[0], only)]
    report['mixer_level_checks_planned'] = len(checks)
    for name, members, writers, restores, guard, linked_send in checks:
        record = {'name': name, 'kind': 'mixer_level', 'status': 'running'}
        report['cases'].append(record)
        print('Testing ' + name, flush=True)
        try:
            if linked_send:
                record.update(status='skipped', reason='Linked Aux bus send-level coupling needs separate verification')
                continue
            level_group(device, members, writers, None, None, record, checkpoint,
                        maximum=CHANNEL_MAX_RAW, guard=guard,
                        restore_writers=restores, require_all=True)
        except (Exception, KeyboardInterrupt) as error:
            record.update(status='failed', error=str(error) or type(error).__name__)
            if isinstance(error, KeyboardInterrupt) or record.get('restoration') != 'verified':
                raise
        finally:
            checkpoint()
