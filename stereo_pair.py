"""Explicit stereo conversion using guarded inclusion writes and input link."""
from af16rig import DeviceError
from preamp import snapshot,change

def convert(device,bus,source,kind,value,expected_mono,expected_stereo):
    device.validate_mix_channel(bus,source) if hasattr(device,'validate_mix_channel') else None
    if bus!='main' or type(source) is not int or not 1<=source<=16 or type(value) is not bool:raise ValueError('Invalid pair conversion')
    left=((source-1)//2)*2+1;mask=3<<(left-1);bit=1<<((left-1)//2)
    original=device.mix_channel_snapshot(bus,left)['raw']
    if (original.get('show'),original.get('stereo'))!=(expected_mono,expected_stereo):raise DeviceError('Mixer selection changed; refresh before linking')
    mono,pairs=expected_mono,expected_stereo
    if not ((mono&mask==mask and not pairs&bit) or (mono&mask==0 and pairs&bit)):
        raise DeviceError('Select both mono inputs or the stereo pair before linking/unlinking')
    state=snapshot(device,left)
    if state['kind']!=kind or not state['link_available']:raise DeviceError('Input pair source changed or is incompatible')
    change(device,left,kind,'link',value)
    def apply(ch,stereo,on):
        nonlocal mono,pairs
        device.write_mixer_inclusion(bus,ch,stereo,on,expected_mono=mono,expected_stereo=pairs)
        flag=1<<((ch-1)//2 if stereo else ch-1)
        if stereo:pairs=pairs|flag if on else pairs&~flag
        else:mono=mono|flag if on else mono&~flag
    try:
        if value and not pairs&bit:
            apply(left,False,False);apply(left+1,False,False);apply(left,True,True)
        elif not value and pairs&bit:
            apply(left,True,False);apply(left,False,True);apply(left+1,False,True)
        result=[device.mix_channel_snapshot(bus,i) for i in (left,left+1)]
        if any((s['raw'].get('show'),s['raw'].get('stereo'))!=(mono,pairs) for s in result):raise DeviceError('Pair selection readback differs')
        return result
    except DeviceError as error:
        raise DeviceError(f'Pair conversion stopped: {error}. Some changes may have applied; inspect Sources before retrying.') from error
