"""Mixer-strip PAD button, driven by active-input readback."""
from mixer_view import configure_changed
from af16rig_gui import ACCENT,BG,TEXT

def selection(strip):
    c=strip.c;source=c.source.get();stereo=bool(c.state.get('stereo_members'))
    dash=getattr(c.app,'dashboard',None)
    channels=[source,source+1] if stereo else [source]
    states=[dash.preamp_states.get(ch,{}) for ch in channels] if dash else []
    ready=(source<=16 and c.app.connected and not c.stale and c.bus.get()=='main' and dash is not None
           and ((source-1)//2)*2+1 not in dash.preamp_pending and bool(states)
           and all(s.get('pad_available') and s.get('pad') in (0,1) for s in states))
    return source,stereo,states,ready

def refresh(strip):
    source,stereo,states,ready=selection(strip)
    pads=[s.get('pad') for s in states]
    known=bool(pads) and all(p in (0,1) for p in pads)
    active=known and all(p==1 for p in pads)
    mixed=known and len(set(pads))>1
    configure_changed(strip.pad,text='P±' if mixed else 'P',state='normal' if ready else 'disabled',
                      bg='#dab86c' if mixed else ACCENT if active else '#383c41',fg=BG if active or mixed else TEXT)

def toggle(strip):
    source,stereo,states,ready=selection(strip)
    if not ready:return
    dash=strip.c.app.dashboard;dash.preamp_pending.add(((source-1)//2)*2+1)
    strip.c.app.worker.commands.put(('preamp_pad',(source,stereo,[(s['kind'],s['pad']) for s in states])))
    refresh(strip)
