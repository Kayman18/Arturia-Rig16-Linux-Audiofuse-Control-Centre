"""Master/output level checks through the existing control methods."""
from functools import partial
from check_selection import case_selected
import time

from af16rig import DeviceError, MIXER_BUSES, VALIDATED_STATE_VERSION


def signed(raw):
    return raw if raw < 32768 else raw - 65536


def level_group(device, members, writers, link_field, link_mask, record, checkpoint,
                *, maximum=0, guard=None, restore_writers=None, require_all=False):
    def read():
        return [device.read(field, index) for field, index in members]

    def check_links():
        if guard is not None:
            guard()
        if link_field and device.read(link_field) != link_mask:
            raise DeviceError('Level link selection changed')

    check_links()
    start = read()
    record.update(controls=members, start=start, start_db=[signed(v) / 256 for v in start])
    if any(not -60 * 256 <= signed(v) <= maximum for v in start):
        record.update(status='skipped', reason='Outside supported level range')
        return
    if len(set(start)) != 1:
        record.update(status='skipped', reason='Linked members have different starting levels')
        return
    direction = 1 if signed(start[0]) < -59 * 256 else -1
    targets = [(signed(v) + direction * 256) & 65535 for v in start]
    record.update(target=targets, step_db=direction, restoration='unverified')
    checkpoint()
    attempted = False

    def step(member, step_direction, expected, *, restoring=False):
        nonlocal attempted
        with device.lock:
            device.last_write = None
            check_links()
            if device.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version')
            current = read()
            record.setdefault('pre_write_reads', []).append(
                {'member': member, 'restoring': restoring, 'actual': current})
            if restoring:
                if not attempted or any(v not in (a, b) for v, a, b in zip(current, start, targets)):
                    raise DeviceError('Unexpected level during restoration; see pre_write_reads')
                if current[member] == start[member]:
                    return
            elif current != expected:
                raise DeviceError('Starting level changed before write; see pre_write_reads')
            attempted = True
            if restoring and restore_writers is not None:
                restore_writers[member](start[member])
            else:
                writers[member](step_direction)

    try:
        step(0, direction, start)
        actual = read()
        record['observed'] = actual
        if (require_all and actual != targets) or actual[0] != targets[0] or any(v not in (a, b) for v, a, b in zip(actual, start, targets)):
            raise DeviceError('Unexpected level readback')
    finally:
        record['before_restore'] = read()
        for member in range(len(members)):
            actual = read()
            if actual == start:
                break
            if not attempted or any(v not in (a, b) for v, a, b in zip(actual, start, targets)):
                raise DeviceError('Level restoration unverified; inspect starting and current values')
            if actual[member] == targets[member]:
                step(member, -direction, actual, restoring=True)
        record['restore_reads'] = []
        for delay in (0, 0.05, 0.10, 0.20, 0.40):
            if delay:
                time.sleep(delay)
            record['final'] = read()
            record['restore_reads'].append(record['final'])
            if record['final'] == start:
                break
        if record['final'] != start:
            raise DeviceError('Level restoration mismatch')
        record['restoration'] = 'verified'
    record['status'] = 'passed'


def level_suite(device, report, checkpoint, *, only=()):
    checks = [('Speaker level', [('speaker_level', 0)], [device.step_volume], None, None)]
    aux_mask = device.read('aux_link')
    consumed = set()
    for bus in MIXER_BUSES:
        if bus in consumed:
            continue
        group = [bus]
        if bus in ('aux1', 'aux3'):
            aux = int(bus[-1])
            if aux_mask & (1 << aux):
                group.append(f'aux{aux + 1}')
        consumed.update(group)
        checks.append(('/'.join(group) + ' master level',
                       [(name + '_master', 0) for name in group],
                       [partial(device.step_mixer_master, name) for name in group],
                       'aux_link', aux_mask))
    output_mask = device.read('output_link')
    consumed = set()
    for channel in range(3, 11):
        if channel in consumed:
            continue
        index = channel - 3
        left = index & ~1
        group = [channel]
        if output_mask & (3 << left):
            group = [left + 3, left + 4]
        consumed.update(group)
        checks.append(('Output ' + '/'.join(map(str, group)) + ' level',
                       [('output_gain', ch - 3) for ch in group],
                       [partial(device.step_output_gain, ch) for ch in group],
                       'output_link', output_mask))
    checks = [check for check in checks if case_selected(check[0], only)]
    report['level_checks_planned'] = len(checks)
    for name, members, writers, field, mask in checks:
        record = {'name': name, 'kind': 'level', 'status': 'running'}
        report['cases'].append(record)
        print('Testing ' + name, flush=True)
        try:
            level_group(device, members, writers, field, mask, record, checkpoint)
        except (Exception, KeyboardInterrupt) as error:
            record.update(status='failed', error=str(error) or type(error).__name__)
            if isinstance(error, KeyboardInterrupt) or record.get('restoration') != 'verified':
                raise
        finally:
            checkpoint()
