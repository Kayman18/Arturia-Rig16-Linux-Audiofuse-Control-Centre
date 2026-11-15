"""Run all offline regressions and optional AF16Rig hardware checks."""
import argparse
from check_selection import case_selected
from functools import partial
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from af16rig import CHANNEL_MAX_RAW, AF16Rig, DeviceError, VALIDATED_STATE_VERSION


def pan_case(device, bus, record, checkpoint):
    """Exercise one included mono source without changing its routing."""
    if device.version != VALIDATED_STATE_VERSION:
        raise DeviceError(f'Unsupported state version {device.version}')
    show = device.read(bus + '_channel_show')
    stereo = device.read(bus + '_channel_stereo')
    index = next((i for i in range(16) if show & (1 << i)
                  and not stereo & (1 << (i // 2))), None)
    if index is None:
        record.update(status='skipped', reason='No included mono source')
        return

    field = bus + '_channel_pan'
    start = device.read(field, index)
    if not 0 <= start <= 254:
        raise DeviceError(f'Uncalibrated pan value {start}')
    delta = -1 if start == 254 else 1
    target = start + delta
    forward, reverse = ('R step', 'L step') if delta == 1 else ('L step', 'R step')
    def step(action, expected):
        device.adjust_channel_pan(bus, index + 1, action, expected_current=expected)
    round_trip(device, field, index, start, target, forward, reverse, step, record, checkpoint)


def level_case(device, bus, record, checkpoint, *, aux=None):
    show = device.read(bus + '_channel_show')
    stereo = device.read(bus + '_channel_stereo')
    mute_field = bus + '_channel_mute' if aux is None else f'main_channel_send{aux}'
    muted = device.read(mute_field)
    field = bus + '_channel_level' if aux is None else f'aux{aux}_send_level'
    record['control'] = field
    for index in range(16):
        if not show & muted & (1 << index) or stereo & (1 << (index // 2)):
            continue
        start = device.read(field, index)
        signed = start if start < 32768 else start - 65536
        if not -59 * 256 <= signed <= CHANNEL_MAX_RAW:
            continue
        target = (signed - 256) & 65535
        record.update(start_db=signed / 256, target_db=signed / 256 - 1)
        def step(direction, expected):
            if aux is None:
                device.step_mix_channel_level(bus, index + 1, direction, expected_raw=expected,
                                              require_muted=direction < 0)
            else:
                device.step_send_level(bus, index + 1, aux, direction, expected_raw=expected,
                                       require_muted=direction < 0)
        round_trip(device, field, index, start, target, -1, 1, step, record, checkpoint)
        return
    record.update(status='skipped', reason='No eligible muted mono strip/send with room for a full downward step')


def round_trip(device, field, index, start, target, forward, reverse, step, record, checkpoint):
    record.update(source=index + 1, start=start, target=target, restoration='unverified')
    device.last_write = None
    checkpoint()
    try:
        step(forward, start)
        record['observed'] = device.read(field, index)
        if record['observed'] != target:
            raise DeviceError(f"Expected {target}, observed {record['observed']}")
    finally:
        current = device.read(field, index)
        if current == target and device.last_write is not None:
            step(reverse, target)
        elif current != start:
            raise DeviceError(f'{field} changed to {current}. Starting value was {start}.')
        record['final'] = device.read(field, index)
        if record['final'] != start:
            raise DeviceError(f"Restore expected {start}, observed {record['final']}")
        record['restoration'] = 'verified'
    record['status'] = 'passed'


def inspect_mixer(device, report):
    """Read the same master and strip registers that back the mixer UI."""
    masters = device.mixer_masters_snapshot()
    report['masters'] = masters
    for bus, level in masters['levels'].items():
        if level['raw'] is None:
            raise DeviceError(f'{bus} master: {masters["errors"].get(bus, "read failed")}')
    for field in ('aux_mutes', 'aux_pre', 'cue_enabled'):
        if field in masters['errors']:
            raise DeviceError(f'{field}: {masters["errors"][field]}')

    report['strips'] = {}
    for bus in ('main', 'cue'):
        strips = []
        report['strips'][bus] = strips
        fields = {key: device.read(bus + '_channel_' + key)
                  for key in ('show', 'stereo', 'mute', 'solo')}
        for index in range(16):
            pair = index // 2
            stereo = bool(fields['stereo'] & (1 << pair))
            if not stereo and not fields['show'] & (1 << index):
                continue
            strip = {'source': index + 1, 'mode': 'stereo' if stereo else 'mono'}
            strips.append(strip)
            strip['mute_bit'] = (fields['mute'] >> index) & 1
            strip['solo_bit'] = (fields['solo'] >> index) & 1
            raw = device.read(bus + '_channel_level', index)
            strip['level_raw'] = raw
            strip['level_db'] = (raw if raw < 32768 else raw - 65536) / 256


def batch_status(cases):
    if not cases:
        return 'no_matching_checks'
    if any(case['status'] == 'failed' for case in cases):
        return 'failed'
    if all(case['status'] == 'passed' for case in cases):
        return 'passed'
    if all(case['status'] == 'skipped' for case in cases):
        return 'read_only_passed'
    return 'passed_with_skips'


def button_case(device, field, bit, writer, record, checkpoint):
    """Toggle a scalar, mono bit, or uniform stereo pair via its public API."""
    stereo = isinstance(bit, tuple)
    width_mask = 3 if stereo else 1
    shift = bit[0] if stereo else bit
    def read():
        raw = device.read(field)
        return raw if bit is None else (raw >> shift) & width_mask

    start = read()
    if stereo and start not in (0, 3):
        record.update(status='skipped', control=field, pair=[i + 1 for i in bit],
                      start=start, reason='Stereo members have different starting button states')
        return
    if start not in (0, width_mask):
        raise DeviceError(f'{field} has unsupported button value {start}')
    target = width_mask - start
    record.update(control=field, bit=bit, start=start, target=target,
                  restoration='unverified')
    device.last_write = None
    checkpoint()

    def write(value, expected):
        with device.lock:
            device.last_write = None
            if device.version != VALIDATED_STATE_VERSION:
                raise DeviceError('Unsupported state version')
            if read() != expected:
                raise DeviceError('Button changed externally')
            writer(bool(value))

    try:
        write(target, start)
        record['observed'] = read()
        if record['observed'] != target:
            raise DeviceError('Button readback mismatch')
    finally:
        current = read()
        diagnostic = device.last_write
        record['write_diagnostic'] = diagnostic
        record['before_restore'] = current
        touched = 0
        if stereo and diagnostic:
            for transaction in diagnostic.get('transactions', []):
                member = transaction.get('element_index')
                if transaction.get('control') == field and member in bit:
                    touched |= 1 << (member - shift)
        changed = current ^ start
        partial_restore = stereo and changed and changed & ~touched == 0
        confirmed_pair = stereo and diagnostic and diagnostic.get('confirmed') and current == target
        if diagnostic is not None and ((not stereo and current == target) or confirmed_pair or partial_restore):
            record['restore_from'] = current
            write(start, current)
        elif current != start:
            raise DeviceError('Button restoration could not be attributed to this test; inspect recorded state')
        record['final'] = read()
        if record['final'] != start:
            raise DeviceError('Button restoration mismatch')
        record['restoration'] = 'verified'
    record['status'] = 'passed'


def button_suite(device, report, checkpoint, *, inputs=False, only=()):
    checks = [(name, name, None, partial(device.write_bool, name))
              for name in ('mute', 'mono', 'dim')]
    checks.append(('Cue enable', 'cue_enabled', None, device.write_cue_enabled))
    for aux in range(1, 5):
        for control, method in [('mute', device.write_aux_mute), ('pre', device.write_aux_pre)]:
            checks.append((f'Aux {aux} {control}', f'aux_{control}', aux - 1,
                           partial(method, f'aux{aux}')))
    for bus in ('main', 'cue'):
        show = device.read(bus + '_channel_show')
        stereo = device.read(bus + '_channel_stereo')
        for source in range(1, 17):
            index = source - 1
            if not show & (1 << index) or stereo & (1 << (index // 2)):
                continue
            for control, method in [('mute', device.write_mix_channel_mute),
                                    ('solo', device.write_mix_channel_solo)]:
                checks.append((f'{bus} {source} {control}', f'{bus}_channel_{control}',
                               index, partial(method, bus, source)))
            if bus == 'main':
                for aux in range(1, 5):
                    checks.append((f'Main {source} Aux {aux} send mute',
                                   f'main_channel_send{aux}', index,
                                   partial(device.write_send_mute, bus, source, aux)))
        for left in range(0, 16, 2):
            if not stereo & (1 << (left // 2)) or show & (3 << left):
                continue
            pair = (left, left + 1)
            source = left + 1
            for control in ('mute', 'solo'):
                checks.append((f'{bus} {source}/{source + 1} {control}',
                               f'{bus}_channel_{control}', pair,
                               partial(device.write_stereo_channel_switch, bus, source, control)))
            if bus == 'main':
                for aux in range(1, 5):
                    checks.append((f'Main {source}/{source + 1} Aux {aux} send mute',
                                   f'main_channel_send{aux}', pair,
                                   partial(device.write_stereo_send_mute, bus, source, aux)))
    if inputs:
        from input_checks import input_button_checks
        checks.extend(input_button_checks(device))
    checks = [check for check in checks if case_selected(check[0], only)]
    report['button_checks_planned'] = len(checks)
    checkpoint()
    for name, field, bit, writer in checks:
        record = {'name': name, 'status': 'running', 'kind': 'button'}
        report['cases'].append(record)
        print(f'Testing {name}', flush=True)
        try:
            if writer is None:
                record.update(status='skipped', control=field, bit=bit,
                              reason='Linked rear right phase write did not read back in TEST58; mapping unresolved')
            else:
                button_case(device, field, bit, writer, record, checkpoint)
        except (Exception, KeyboardInterrupt) as exc:
            record.update(status='failed', error=str(exc) or type(exc).__name__)
            if isinstance(exc, KeyboardInterrupt) or ' input ' not in name or record.get('restoration') != 'verified':
                raise
            record['continued_after_verified_restore'] = True
        finally:
            checkpoint()


def hardware_suite(device, report, checkpoint, *, buttons=False, inputs=False, levels=False, only=()):
    device.open()
    try:
        report['state_version'] = device.version
        report['monitor'] = device.snapshot()
        if not report['monitor']['writes_available']:
            raise DeviceError('Monitor snapshot or state version outside supported range')
        inspect_mixer(device, report)
        report['mixer_readback'] = 'passed'
        checkpoint()
        # Register future device checks here. Stop after the first failure.
        checks = [('mono pan', pan_case, ('main', 'cue')),
                  ('muted mono level', level_case, ('main', 'cue'))]
        checks.extend((f'Aux {aux} muted send level', partial(level_case, aux=aux), ('main',))
                      for aux in range(1, 5))
        for name, check, buses in checks:
            for bus in buses:
                if not case_selected(f'{bus} {name}', only):
                    continue
                record = {'name': f'{bus} {name}', 'status': 'running'}
                report['cases'].append(record)
                try:
                    check(device, bus, record, checkpoint)
                except (Exception, KeyboardInterrupt) as exc:
                    record.update(status='failed', error=str(exc) or type(exc).__name__)
                    raise
                finally:
                    checkpoint()
        if buttons or inputs:
            button_suite(device, report, checkpoint, inputs=inputs, only=only)
        if levels:
            from level_checks import level_suite
            level_suite(device, report, checkpoint, only=only)
            from mixer_level_checks import mixer_level_suite
            mixer_level_suite(device, report, checkpoint, only=only)
    finally:
        device.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', action='store_true',
                        help='also test Main and Cue pan and muted mono levels on the connected AF16Rig')
    parser.add_argument('--buttons', action='store_true',
                        help='include monitor, Aux, and included mono strip/send button toggles')
    parser.add_argument('--inputs', action='store_true',
                        help='include active input phase, HPF and pad in the button batch')
    parser.add_argument('--levels', action='store_true', help='test master and analog output levels')
    parser.add_argument('--all', action='store_true', help='run all hardware batches')
    parser.add_argument('--only', action='append', default=[], metavar='NAME',
                        help='run checks whose names contain NAME; repeat to select several groups')
    args = parser.parse_args()
    if any(not pattern.strip() for pattern in args.only):
        parser.error('--only requires a nonempty name')
    if args.only:
        args.all = True
    if args.all:
        args.hardware = args.buttons = args.inputs = args.levels = True
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent))
    result = unittest.TextTestRunner().run(suite)
    if not result.wasSuccessful() or result.testsRun == 0:
        return 1
    if not (args.hardware or args.buttons or args.inputs or args.levels):
        return 0

    with tempfile.NamedTemporaryFile(prefix='AF16Rig-autotest-', suffix='.json',
                                     dir=Path.cwd(), delete=False) as handle:
        path = Path(handle.name)
    print(f'Hardware report: {path}', flush=True)
    report = {'build': 'BETA RC', 'utc': datetime.now(timezone.utc).isoformat(),
              'offline_tests_run': result.testsRun, 'selected_checks': args.only, 'status': 'running', 'cases': []}

    def checkpoint():
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2) + '\n')
        os.replace(temp, path)

    checkpoint()
    try:
        hardware_suite(AF16Rig(), report, checkpoint, buttons=args.buttons, inputs=args.inputs, levels=args.levels, only=args.only)
        report['status'] = batch_status(report['cases'])
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status='failed', error=str(exc) or type(exc).__name__)
    checkpoint()
    for case in report['cases']:
        print(case['name'], case['status'], case.get('reason', case.get('error', '')))
    print(report['status'], report.get('error', ''))
    return 1 if report['status'] in ('failed', 'no_matching_checks') else 0


if __name__ == '__main__':
    raise SystemExit(main())
