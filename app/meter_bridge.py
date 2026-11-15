"""All decoded meter taps, with session peaks; no device access or writes."""
import math

BANKS = {
    'Inputs': [('inputs', i) for i in range(32)],
    'USB': [('usb', i) for i in range(32)],
    'Outputs': [(group, i) for group, count in
                [('outputs', 8), ('speakers', 2), ('phones', 2), ('adat_outputs', 16), ('loopback', 2)]
                for i in range(count)],
    'Buses': [(group, i) for group, count in
              [('main', 2), ('cue', 2), ('aux', 4), ('immersive', 16)]
              for i in range(count)],
}
KEYS = tuple(key for bank in BANKS.values() for key in bank)

def label(key, names):
    group, i = key
    if group == 'inputs':
        default = f'Analog {i+1}' if i < 16 else f'ADAT In {i-15}'
        return names.get(i+1, default)
    if group == 'adat_outputs': return names.get(77+i, f'ADAT Out {i+1}')
    # Do not guess physical analog-output name slot ordering.
    if group in ('speakers', 'phones', 'main', 'cue', 'loopback'):
        return f'{group.title()} {"LR"[i]}'
    return f'{dict(outputs="Line Out", usb="USB", aux="Aux", immersive="Immersive")[group]} {i+1}'

class MeterSession:
    def __init__(self, serial=None): self.reset(serial)
    def reset(self, serial):
        self.serial=serial; self.time=None; self.frame=None
        self.peaks={}; self.full_scale=set()
    def feed(self, serial, frame, now):
        if serial is None or serial != self.serial: return False
        # Validate the whole frame before changing any displayed state.
        values={key:frame[key[0]][key[1]] for key in KEYS}
        if any(not isinstance(v, (int,float)) or not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError('Invalid meter frame')
        self.frame=dict(values); self.time=now
        for key,v in values.items():
            self.peaks[key]=max(v,self.peaks.get(key,0))
            if v >= 1: self.full_scale.add(key)
        return True
    def fresh(self, now): return self.time is not None and now-self.time <= .5
    def reset_peaks(self, key=None):
        if key is None: self.peaks.clear(); self.full_scale.clear()
        else: self.peaks.pop(key,None); self.full_scale.discard(key)
    def peak_text(self, key):
        if key not in self.peaks: return 'Peak —'
        value=self.peaks[key]
        return 'Peak ≤−60' if value <= .001 else f'Peak {20*math.log10(value):.1f}'
