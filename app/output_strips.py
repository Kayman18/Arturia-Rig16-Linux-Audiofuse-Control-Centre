"""Phones readback and monitor controls in matching console strips."""
import tkinter as tk
import uuid
import time
from af16rig import VOLUME_MIN_RAW,VOLUME_MAX_RAW,VOLUME_UNITS_PER_DB
from meter_view import Meter
from phones_level import decode_level

class OutputStrip:
    def __init__(self,parent,app,kind):
        from mixer_view import lab,button,ValueControl,Field
        self.app,self.kind=app,kind
        self.phones_raw=None;self.phones_request=None;self.phones_read_at=0
        self.frame=tk.Frame(parent,bg='#25282c',width=164,padx=8);self.frame.pack_propagate(False)
        self.header=tk.Frame(self.frame,bg='#25282c',height=400)
        self.header.pack(fill='x');self.header.pack_propagate(False)
        lab(self.header,kind.upper(),fg='#62cbd5',font=('DejaVu Sans',11,'bold')).pack(pady=(13,8))
        lab(self.header,'SPEAKER LEVEL' if kind=='monitor' else 'HEADPHONE LEVEL',fg='#969ca2',font=('DejaVu Sans',8)).pack(pady=(0,10))
        self.level=lab(self.header,'—',font=('DejaVu Sans',14,'bold'));self.level.pack()
        row=tk.Frame(self.header,bg='#25282c');row.pack(fill='x',pady=10)
        if kind=='monitor':
            app.level=self.level;app.volume_buttons={};app.controls={}
            for direction,text in ((-1,'−'),(1,'+')):
                b=button(row,text,lambda d=direction:app.step_volume(d),width=3)
                b.pack(side='left',expand=True,fill='x',padx=2);app.volume_buttons[direction]=b
            for name in ('mute','dim','mono'):
                b=button(self.header,name.upper(),lambda n=name:app.toggle(n));b.pack(fill='x',pady=3)
                app.controls[name]=(Field(),b)
        else:
            self.phone_buttons=[]
            for direction,text in ((-1,'−'),(1,'+')):
                b=button(row,text,lambda d=direction:self.step_phones(d),width=3)
                b.pack(side='left',expand=True,fill='x',padx=2);self.phone_buttons.append(b)
            self.raw=lab(self.header,'Waiting for device',fg='#969ca2',font=('DejaVu Sans',8));self.raw.pack(pady=6)
            self.phone_status=lab(self.header,'',fg='#969ca2',font=('DejaVu Sans',8),wraplength=140);self.phone_status.pack(pady=6)
        track=tk.Frame(self.frame,bg='#25282c');track.pack(fill='both',expand=True)
        self.meter=Meter(track,caption='');self.meter.pack(side='right',fill='y')
        self.fader=ValueControl(track,app.step_volume if kind=='monitor' else self.step_phones,
            kind='fader',low=VOLUME_MIN_RAW/VOLUME_UNITS_PER_DB if kind=='monitor' else -60,
            high=VOLUME_MAX_RAW/VOLUME_UNITS_PER_DB if kind=='monitor' else 0,
            target=app.target_volume if kind=='monitor' else self.target_phones)
        self.fader.preview_drag=True;self.fader.pack(side='left',fill='both',expand=True)
        self.refresh()
    def refresh(self):
        if self.kind!='monitor':
            self.refresh_phones();return
        from mixer_view import configure_changed
        a=self.app;s=a.state;raw=s.get('speaker_level_signed')
        valid=a.connected and not a.stale and isinstance(raw,int) and VOLUME_MIN_RAW<=raw<=VOLUME_MAX_RAW
        self.fader.update_value(raw/VOLUME_UNITS_PER_DB if valid else None,
            valid and not a.pending and bool(s.get('writes_available')),valid=valid)
        configure_changed(self.level,text=a.format_level(raw) if valid else '—')
    def phones_ready(self):
        a=self.app;value,_=decode_level(self.phones_raw)
        return (a.connected and not a.stale and a.state.get('writes_available',False)
                and self.phones_request is None and value is not None and -60<=value<=0
                and time.monotonic()-self.phones_read_at<2)
    def refresh_phones(self):
        from mixer_view import configure_changed
        value,text=decode_level(self.phones_raw)
        ready=self.phones_ready()
        self.fader.update_value(value,ready,readout=text,valid=value is not None)
        for b in getattr(self,'phone_buttons',[]):configure_changed(b,state='normal' if ready else 'disabled')
    def phones_state(self,state):
        from mixer_view import configure_changed
        self.phones_raw=state.get('knob_raw');self.phones_read_at=time.monotonic()
        value,text=decode_level(self.phones_raw)
        configure_changed(self.raw,text='Live device level' if value is not None else 'Readback unavailable')
        configure_changed(self.level,text=text)
        self.refresh_phones()
    def step_phones(self,direction):
        value,_=decode_level(self.phones_raw)
        if value is not None:self.target_phones(max(-60,min(0,value+direction)))
    def target_phones(self,value):
        if not self.phones_ready():return False
        request=uuid.uuid4().hex;self.phones_request=request
        self.app.worker.commands.put(('phones_target',dict(db=value,expected_raw=self.phones_raw,
            connection_serial=self.app.name_cache.serial,request_id=request)))
        self.phone_status.config(text='Applying…')
        self.refresh_phones();return True
    def phones_result(self,event):
        if event.get('request_id')!=self.phones_request or self.phones_request is None:return
        self.phones_request=None
        if event['kind']=='phones_written':
            self.phones_state({'knob_raw':event['actual']&65535})
            self.phone_status.config(text='Level confirmed')
        else:
            self.phones_state({})
            self.phone_status.config(text='Change not confirmed')
            self.app.message.config(text=event['message'],fg='#efba76')
    def clear(self):
        self.meter.clear();self.fader.cancel_drag()
        if self.kind=='phones':
            self.phones_request=None
            self.phones_state({})
            if hasattr(self,'phone_status'):self.phone_status.config(text='')
