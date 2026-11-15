"""Native AF16Rig preset slots.

No preset write is retried. USB completion plus current-slot/dirty readback
confirms the observed device state, not power-cycle persistence.
"""
import ctypes as C
import time
from af16rig import DemoAF16Rig, DeviceError, DeviceDisconnected
from channel_names import decode_words


def check_slot(slot, saving=False):
    if type(slot) is not int or not (1 if saving else 0) <= slot <= 8:
        raise ValueError('Save slots are 1–8; load slots are 0–8 (0 is Factory)')


def check_device(device):
    if device.version != 18:
        raise DeviceError('Unsupported state version for device presets')


def read_word(device, parameter, index=0):
    if parameter not in range(8, 18) or type(index) is not int or not 0 <= index < 16:
        raise ValueError('Invalid preset read')
    check_device(device)
    with device.lock:
        if not device.handle: raise DeviceDisconnected('Device disconnected')
        data = (C.c_ubyte * 2)()
        rc = device.lib.libusb_control_transfer(device.handle, 0xc0, 0x93, parameter, index, data, 2, 1000)
        if rc == -4: raise DeviceDisconnected('Device disconnected during preset read')
        if rc != 2: raise DeviceError(f'Preset read returned {rc} bytes; expected 2')
        return int.from_bytes(data, 'little')


def read_status(device):
    check_device(device)
    if isinstance(device, DemoAF16Rig):
        return dict(current=getattr(device, 'preset_current', 1), changed=getattr(device, 'preset_changed', 0))
    current, changed = read_word(device, 8), read_word(device, 9)
    if current not in range(9) or changed not in (0, 1):
        raise DeviceError(f'Unexpected preset state: current={current}, changed={changed}; actions disabled')
    return dict(current=current, changed=changed)


def read_slot(device, slot):
    check_slot(slot); check_device(device)
    if slot == 0: return dict(slot=0, name='Factory', status='read-only')
    if isinstance(device, DemoAF16Rig):
        return dict(slot=slot, name=getattr(device,'preset_names',{}).get(slot,f'Demo preset {slot}'), status='demo')
    passes=[]
    for _ in range(2):
        words=[read_word(device,slot+9,index) for index in range(6)]
        passes.append(words)
    if passes[0]!=passes[1]:raise DeviceError(f'Slot {slot} name changed during read; refresh presets')
    raw=b''.join(word.to_bytes(2,'little') for word in passes[0])
    try:name=raw.split(b'\0',1)[0].decode('utf-8')
    except UnicodeDecodeError as error:raise DeviceError('Preset name is not valid UTF-8') from error
    if any(not c.isprintable() for c in name):raise DeviceError('Preset name contains non-printable data')
    return dict(slot=slot,name=name,status='read',words=passes[0])

PRESET_NAME_BYTES=12

def encode_preset_name(name):
    if not isinstance(name,str) or any(not c.isprintable() for c in name):
        raise ValueError('Use printable text without control characters')
    data=name.encode('utf-8')
    if len(data)>PRESET_NAME_BYTES:raise ValueError('Preset names have a 12-byte UTF-8 limit')
    return data.ljust(PRESET_NAME_BYTES,b'\0')


def rename_preset(device, slot, name, expected_name):
    """Write one slot's global name, never its preset contents."""
    check_slot(slot, saving=True); check_device(device)
    payload=encode_preset_name(name)
    from datetime import datetime,timezone
    from preset_rename_report import capture
    diagnostic=dict(format='af16rig-preset-rename-report-v1',build='BETA RC',utc=datetime.now(timezone.utc).isoformat(),
        slot=slot,requested_name=name,expected_name=expected_name,state_version=device.version,
        demo=isinstance(device,DemoAF16Rig),request=0x1b,parameter=slot+9,index=0,payload_hex=payload.hex(),
        payload_bytes=len(payload),write_requests=0,readbacks=[])
    device.last_preset_rename=diagnostic
    if not isinstance(expected_name,str):raise ValueError('Expected preset name is required')
    before=read_slot(device,slot)
    diagnostic['before']=before
    if before['name']!=expected_name:
        raise DeviceError('Preset name changed on the rig. Read presets before renaming.')
    if name==expected_name:return dict(record=before,write_requests=0,demo=isinstance(device,DemoAF16Rig))
    if isinstance(device,DemoAF16Rig):
        if not hasattr(device,'preset_names'):device.preset_names={}
        device.preset_names[slot]=name
        return dict(record=read_slot(device,slot),write_requests=0,demo=True)
    diagnostic['storage_before']=capture(device,slot)
    with device.lock:
        if not device.handle:raise DeviceDisconnected('Device disconnected before preset rename')
        data=(C.c_ubyte*len(payload)).from_buffer_copy(payload)
        # AFCC string write 0x18+group, globals group 3; slot names IDs 10–17.
        diagnostic['write_requests']=1
        rc=device.lib.libusb_control_transfer(device.handle,0x40,0x1b,slot+9,0,data,len(payload),1000)
        diagnostic['out_result']=rc
    if rc==-4:raise DeviceDisconnected('Device disconnected during preset rename; reread after reconnecting')
    diagnostic['storage_after']=capture(device,slot)
    for delay in (.05,.1,.2,.4):
        time.sleep(delay)
        try:record=read_slot(device,slot)
        except DeviceDisconnected:raise
        except DeviceError:continue
        diagnostic['readbacks'].append(record)
        if record['name']==name:
            diagnostic['confirmed']=True
            return dict(record=record,write_requests=1,demo=False)
    diagnostic['confirmed']=False
    actual=diagnostic['readbacks'][-1]['name'] if diagnostic['readbacks'] else 'unreadable'
    raise DeviceError(f'Preset rename not confirmed: requested {name!r}, received {actual!r} (OUT returned {rc}). Sent once. Save rename report for diagnosis.')


def operate(device, action, slot, expected_name, expected_status, on_attempt=None):
    if action not in ('load', 'save'): raise ValueError('Unknown preset action')
    check_slot(slot, saving=action == 'save'); check_device(device)
    before = read_status(device)
    if before != expected_status:
        raise DeviceError('Current preset state changed. Refresh presets before continuing.')
    if read_slot(device, slot)['name'] != expected_name:
        raise DeviceError('Selected preset name changed. Refresh presets before continuing.')
    if isinstance(device, DemoAF16Rig):
        if on_attempt: on_attempt()
        device.preset_current = slot; device.preset_changed = 0
        return dict(action=action, slot=slot, status=read_status(device), demo=True, write_requests=0)
    # Native AFCC: vendor OUT 0x48, wValue 0=load / 1=save,
    # wIndex literal slot, length 1, payload zero. Do not use scalar writes.
    with device.lock:
        if not device.handle: raise DeviceDisconnected('Device disconnected before preset operation')
        if on_attempt: on_attempt()
        data = (C.c_ubyte * 1)(0)
        rc = device.lib.libusb_control_transfer(device.handle, 0x40, 0x48,
                                               int(action == 'save'), slot, data, 1, 1000)
    if rc == -4: raise DeviceDisconnected('Device disconnected during preset operation; inspect state after reconnecting')
    last = None
    for delay in (.1, .2, .4, .8):
        time.sleep(delay)
        try:
            last = read_status(device)
        except DeviceDisconnected: raise
        except DeviceError: continue
        if rc == 1 and last == dict(current=slot, changed=0):
            return dict(action=action, slot=slot, status=last, demo=False, write_requests=1)
    raise DeviceError(f'Preset {action} not confirmed (OUT returned {rc}; state {last}). '
                      'Command was sent only once. Refresh and inspect the rig before retrying.')
