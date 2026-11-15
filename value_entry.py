"""Validate typed mixer values against the existing control limits."""
import math

def numeric_target(value,low,high,quantum=.25):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
        raise ValueError('Enter a finite number.')
    pan=low==0 and high==254
    minimum,maximum=(-100,100) if pan else (low,high)
    if not minimum<=value<=maximum:
        raise ValueError(f'Enter a value from {minimum:g} to {maximum:g}.')
    if pan:return round((value+100)*254/200)
    return max(low,min(high,round(value/quantum)*quantum))

def entry_description(value,low,high,quantum):
    if low==0 and high==254:
        return ('Set pan','Pan: −100 = left, 0 = centre, +100 = right',round(value/254*200-100,2),-100,100)
    return ('Set level',f'Level in dB ({low:g} to {high:g}) · step {quantum:g} dB',value,low,high)
