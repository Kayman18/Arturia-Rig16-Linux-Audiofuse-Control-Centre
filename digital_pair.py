"""Convert digital mixer membership without touching preamps or signal levels."""
from contextlib import nullcontext
from af16rig import DeviceError,DeviceDisconnected
from mixer_membership import snapshot,change
from digital_mixer import DigitalMixer


def convert(device,bus,source,linked,expected_mono,expected_stereo):
    if bus not in ('main','cue') or type(source) is not int or not 17<=source<=64 or type(linked) is not bool:
        raise ValueError('Digital Main/Cue pair required')
    if type(expected_mono) is not int or not 0<=expected_mono<1<<64 or type(expected_stereo) is not int or not 0<=expected_stereo<1<<32:
        raise ValueError('Invalid expected selection masks')
    left=((source-1)//2)*2+1;mask=3<<(left-1);bit=1<<((left-1)//2)
    with device.lock if hasattr(device,'lock') else nullcontext():
        current=snapshot(device,bus,left)['raw']
        mono,pairs=current['show'],current['stereo']
        if (mono,pairs)!=(expected_mono,expected_stereo):raise DeviceError('Mixer selection changed; refresh before linking')
        mono_pair=mono&mask==mask and not pairs&bit
        stereo_pair=mono&mask==0 and bool(pairs&bit)
        if not (mono_pair or stereo_pair):raise DeviceError('Include both mono inputs or the stereo pair in Sources first')
        actions=[] if linked==stereo_pair else [(left,False,False),(left+1,False,False),(left,True,True)] if linked else [(left,True,False),(left,False,True),(left+1,False,True)]
        try:
            for channel,stereo,on in actions:
                result=change(device,bus,channel,stereo,on,mono,pairs)
                mono,pairs=result['raw']['show'],result['raw']['stereo']
            states=[DigitalMixer(device).mix_channel_snapshot(bus,i) for i in (left,left+1)]
            if any((s['raw'].get('show'),s['raw'].get('stereo'))!=(mono,pairs) for s in states):
                raise DeviceError('Final pair selection readback differs')
            return states
        except DeviceDisconnected:raise
        except DeviceError as error:
            raise DeviceError(f'Digital pair conversion stopped: {error}. Some changes may have applied; inspect Sources before retrying.') from error
