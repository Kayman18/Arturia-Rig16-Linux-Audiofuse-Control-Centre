"""Read-only raw routing capture and comparison for AF16Rig mapping research."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from routing_labels import decoded_routes, AGENT_SHA256

from af16rig import AF16Rig, DeviceError, DeviceDisconnected, ROUTING_FIELDS


def scan(device):
    result = {'values': {}, 'errors': {}}
    for field, (_, count) in ROUTING_FIELDS.items():
        for index in range(count):
            key = f'{field}[{index}]'
            try:
                result['values'][key] = device.read(field, index)
            except DeviceDisconnected:
                raise
            except DeviceError as error:
                result['errors'][key] = str(error)
    return result


def changes(before, after):
    shared = before.keys() & after.keys()
    return {key: {'before': before[key], 'after': after[key]}
            for key in sorted(shared) if before[key] != after[key]}


def read_routing(device):
    """Capture through an already-open device owned by the caller."""
    first = scan(device)
    second = scan(device)
    changed = changes(first['values'], second['values'])
    return {'format': 'af16rig-routing-v1', 'build': 'BETA RC',
            'utc': datetime.now(timezone.utc).isoformat(),
            'source_names_verified': False, 'write_requests': 0,
            'label_basis': {'method': 'AFCC native static tables', 'agent_sha256': AGENT_SHA256,
                            'physical_routing_effects_verified': False},
            'decoded_output_routes': decoded_routes(second['values']),
            'state_version': device.version,
            'identity': {key: device.read(key) for key in
                         ('firmware_raw', 'hardware_raw', 'audio_firmware_raw')},
            'reads': {'first': first, 'second': second},
            'changes_during_capture': changed,
            'status': ('partial' if first['errors'] or second['errors'] else
                       'changed_during_capture' if changed else 'stable')}


def capture(device):
    try:
        device.open()
        return read_routing(device)
    except (Exception, KeyboardInterrupt) as error:
        return {'format': 'af16rig-routing-v1', 'build': 'BETA RC',
                'status': 'failed', 'write_requests': 0,
                'error': str(error) or type(error).__name__}
    finally:
        device.close()


def compare(before, after):
    if before.get('format') != 'af16rig-routing-v1':
        raise ValueError('Baseline must be a routing capture')
    if bool(before.get('demo')) != bool(after.get('demo')):
        raise ValueError('Demo and hardware captures cannot be compared')
    if before.get('status') != 'stable' or after.get('status') != 'stable':
        raise ValueError('Comparison requires two complete, stable captures')
    if (before.get('state_version'), before.get('identity')) != (
            after.get('state_version'), after.get('identity')):
        raise ValueError('Device firmware/hardware identity differs between captures')
    a = before['reads']['second']['values']
    b = after['reads']['second']['values']
    if a.keys() != b.keys():
        raise ValueError('Captured routing fields differ')
    return {'compared': len(a), 'changes': changes(a, b)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare', type=Path, help='compare with a previous routing JSON')
    parser.add_argument('--label', default='', help='describe the device setting for this capture')
    args = parser.parse_args()
    before = None
    if args.compare:
        try:
            before = json.loads(args.compare.read_text())
        except (ValueError, OSError) as error:
            parser.error(str(error))
    report = capture(AF16Rig())
    report['label'] = args.label
    if before is not None:
        try:
            report['comparison'] = compare(before, report)
        except (ValueError, KeyError, TypeError) as error:
            report['comparison_error'] = str(error)
    with tempfile.NamedTemporaryFile(mode='w', prefix='AF16Rig-routing-', suffix='.json',
                                     dir=Path.cwd(), delete=False) as output:
        json.dump(report, output, indent=2)
        output.write('\n')
        path = output.name
    print(report['status'])
    print('Routing report:', path)
    if 'comparison' in report:
        print(json.dumps(report['comparison'], indent=2))
    return 0 if report['status'] == 'stable' and 'comparison_error' not in report else 1


if __name__ == '__main__':
    raise SystemExit(main())
