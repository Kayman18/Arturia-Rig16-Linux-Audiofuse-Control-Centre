"""Arturia-inspired console, backed by the existing verified control handlers."""
import math
import time
import tkinter as tk
from tkinter import ttk
from tkinter import simpledialog,messagebox
from value_entry import numeric_target,entry_description
from af16rig import MIXER_BUSES
from meter_view import Meter
from mixer_layout import bank_sources,fixed_geometry,expanded_geometry
from af16rig_gui import MixChannelWindow, MixerMastersWindow, BG, PANEL, TEXT, MUTED, ACCENT


def show_page(app, page):
    """The page host has exactly one managed child, including orphaned pages."""
    for child in app.page_host.winfo_children():
        if child is not page:
            child.pack_forget()
    page.pack(fill='both', expand=True)
    page.lift()


def configure_changed(widget, **options):
    changed={key:value for key,value in options.items() if str(widget.cget(key))!=str(value)}
    if changed: widget.config(**changed)


class QuietLabel(tk.Label):
    def config(self, **options):
        changed={k:v for k,v in options.items() if str(self.cget(k))!=str(v)}
        if changed: super().configure(**changed)



class Field:
    """Widget-independent state adapter for the existing control guards."""
    def __init__(self, value=None):
        self.value = value
        self.options = {'state': 'disabled', 'text': '', 'fg': TEXT}
    def get(self): return self.value
    def set(self, value): self.value = value
    def cget(self, key): return self.options.get(key, '')
    def config(self, **options): self.options.update(options)


class ChannelController(MixChannelWindow):
    def __init__(self, app, bus, source):
        self.app, self.state, self.pending, self.stale = app, {}, False, True
        self.bus, self.source = Field(bus), Field(source)
        self.channel = Field('mix_channel')
        for name in ('pan_reading', 'selection', 'level', 'mute_button', 'solo_button', 'bus_menu', 'source_spin', 'pan_summary'):
            setattr(self, name, Field())
        self.message = app.message
        self.live_status = 'Live mixer readback'
        self.pan_buttons = {}
        self.pan_edit = {key: Field() for key in ('Left','L step','Centre','R step','Right')}
        self.level_buttons = {d: Field() for d in (-1, 1)}
        self.send_buttons = {a: Field() for a in range(1, 5)}
        self.send_level_labels = {a: Field() for a in range(1, 5)}
        self.send_steps = {(a,d): Field() for a in range(1,5) for d in (-1,1)}
        self.view = None
    def target(self, control, value):
        if self.pending or self.stale or not self.app.connected: return False
        if control=='pan' and self.state.get('stereo_members'):
            expected=self.state.get('stereo_pan')
            if not expected or self.app.info.get('state_version')!=18:return False
            self.pending=True;self.refresh()
            self.app.worker.commands.put(('stereo_pan',dict(bus=self.bus.get(),source=self.source.get(),
                target=round(value),expected={k:list(expected[k]) for k in ('values','masks')},connection_serial=self.app.name_cache.serial)))
            return True
        if control == 'level': fields=self.level_buttons.values()
        elif control == 'pan': fields=self.pan_edit.values()
        else: fields=[self.send_steps[int(control[-1]),d] for d in (-1,1)]
        if not any(f.cget('state') in ('normal','active') for f in fields): return False
        self.pending=True
        self.refresh()
        raw=round(value) if control=='pan' else round(value*256)
        self.app.worker.commands.put(('console_set',(self.bus.get(),self.source.get(),control,raw,bool(self.state.get('stereo_members')))))
        return True
    def nudge_pan(self,direction):
        if self.state.get('stereo_members'):
            position=self.state.get('stereo_pan',{}).get('position')
            if position is not None:return self.target('pan',max(0,min(254,round(position)+direction)))
        else:return self.adjust_pan('R step' if direction>0 else 'L step')
    def handle(self,event):
        if event.get('name')=='inclusion':
            if event.get('bus')==self.bus.get():
                self.stale=True;self.refresh()
            return
        super().handle(event)

    def refresh(self):
        super().refresh()
        if self.view: self.view.refresh()


class MasterController(MixerMastersWindow):
    def __init__(self, app):
        self.app, self.state, self.pending, self.unavailable = app, {}, set(), set()
        self.channel = Field('masters')
        self.levels = {b: Field() for b in MIXER_BUSES}
        self.buttons = {(b,d): Field() for b in MIXER_BUSES for d in (-1,1)}
        self.mute_buttons = {b: Field() for b in MIXER_BUSES[2:]}
        self.mute_labels = {b: Field() for b in MIXER_BUSES[2:]}
        self.pre_buttons = {b: Field() for b in MIXER_BUSES[2:]}
        self.cue_button = Field()
        self.message = app.message
        self.live_status = 'Live mixer readback'
        self.view = None
    def target(self, bus, value):
        if not self.app.connected or not any(self.buttons[bus,d].cget('state') in ('normal','active') for d in (-1,1)): return False
        self.pending.add((bus,'level'));self.refresh()
        self.app.worker.commands.put(('console_set',(bus,0,'master',round(value*256),False)))
        return True
    def refresh(self):
        super().refresh()
        if self.view: self.view.refresh()


def button(parent, text, command, **kwargs):
    return tk.Button(parent, text=text, command=command, bg='#383c41', fg=TEXT,
                     activebackground=ACCENT, activeforeground=BG,
                     disabledforeground='#62686f', relief='flat', bd=0,
                     highlightthickness=0, padx=8, pady=5, **kwargs)


def lab(parent, text='', **kwargs):
    return QuietLabel(parent, text=text, bg=parent.cget('bg'), fg=kwargs.pop('fg', TEXT), **kwargs)


def sync_button(widget, field, active=False, color=ACCENT, busy=False):
    wanted = dict(state=widget.cget('state') if busy else field.cget('state'), bg=color if active else '#383c41', fg=BG if active else TEXT)
    if any(str(widget.cget(k)) != str(v) for k,v in wanted.items()): widget.config(**wanted)


class ValueControl(tk.Canvas):
    """Immediate drag feedback with coalesced, readback-verified device writes."""
    def __init__(self, parent, step, kind='dial', low=-60, high=6, target=None):
        self.kind, self.step, self.low, self.high = kind, step, low, high
        self.quantum=.25
        self.preview_drag=True
        self.edit_generation=0
        self.target_callback=target
        self.drag_origin=None;self.desired=None;self.flush_id=None;self.valid=False
        self.value, self.ready, self.last_y, self.readout = None, False, None, None
        super().__init__(parent, width=80, height=63 if kind=='dial' else 220,
                         bg=parent.cget('bg'), highlightthickness=0, takefocus=True)
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Button-1>', self.press)
        self.bind('<Double-Button-1>', self.edit_value)
        self.bind('<Return>', self.edit_value)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<Button-4>', lambda e: self.nudge(1))
        self.bind('<Button-5>', lambda e: self.nudge(-1))
        self.bind('<MouseWheel>', lambda e: self.nudge(1 if e.delta > 0 else -1))
        self.bind('<Up>', lambda e: self.nudge(1))
        self.bind('<Down>', lambda e: self.nudge(-1))
    def update_value(self, value, ready, readout=None, valid=True):
        repaint=(value,readout,valid)!=(self.value,self.readout,self.valid)
        if getattr(self,'visual_target',None) is not None and (not valid or value==self.visual_target):
            self.visual_target=None;repaint=True
        self.valid=valid
        if not valid: self.cancel_drag()
        self.value,self.ready,self.readout=value,ready,readout
        # Busy/readback gating is logical; it must not flash the entire strip.
        cursor='hand2' if valid and value is not None else ''
        if self.cget('cursor') != cursor: self.configure(cursor=cursor)
        if repaint: self.draw()
    def nudge(self, direction):
        if self.ready: self.step(direction)
        return 'break'
    def cancel_drag(self):
        self.edit_generation=getattr(self,'edit_generation',0)+1
        self.drag_origin=None;self.desired=None;self.visual_target=None
        if self.flush_id is not None:
            self.after_cancel(self.flush_id);self.flush_id=None
    def edit_value(self,event=None):
        if not self.ready or not self.valid or self.value is None or not self.target_callback:return 'break'
        self.cancel_drag()
        generation=self.edit_generation
        low,high,quantum=self.low,self.high,self.quantum
        title,prompt,initial,minimum,maximum=entry_description(self.value,low,high,quantum)
        try:
            value=simpledialog.askfloat(title,prompt,parent=self.winfo_toplevel(),initialvalue=initial,minvalue=minimum,maxvalue=maximum)
            if value is None or not self.winfo_exists():return 'break'
            # A disconnect, page switch, or gain-range change invalidates the dialog.
            if generation!=self.edit_generation or not self.ready or not self.valid or (low,high,quantum)!=(self.low,self.high,self.quantum):return 'break'
            target=numeric_target(value,low,high,quantum)
            if self.value is not None and abs(target-self.value)>=1/512:
                self.target_callback(target)
        except ValueError as error:
            messagebox.showerror('Invalid value',str(error),parent=self.winfo_toplevel())
        except tk.TclError:
            pass  # Window closed while the modal dialog was open.
        return 'break'
    def destroy(self):
        self.cancel_drag()
        super().destroy()
    def press(self, event):
        self.focus_set()
        self.last_y=event.y
        if self.ready and self.value is not None:
            self.drag_origin=(event.y,self.value)
    def drag(self, event):
        if self.drag_origin is None or not self.valid: return
        y,value=self.drag_origin
        travel=max(1,self.winfo_height()-46) if self.kind=='fader' else 120
        sensitivity=0.1 if event.state & 1 else 1.0
        target=max(self.low,min(self.high,value+(y-event.y)*(self.high-self.low)/travel*sensitivity))
        self.desired=round(target) if self.high==254 else round(target/getattr(self,'quantum',.25))*getattr(self,'quantum',.25)
        if getattr(self,'preview_drag',False):
            self.visual_target=self.desired;self.draw()
        if self.target_callback and self.flush_id is None:
            self.flush_id=self.after(30,self.flush_target)
    def release(self, event):
        if self.drag_origin is not None and event.y != self.drag_origin[0]: self.drag(event)
        self.drag_origin=None;self.last_y=None
    def flush_target(self):
        self.flush_id=None
        if self.desired is None or not self.valid: return
        wanted=self.desired
        if self.value is not None and abs(wanted-self.value)<1/512:
            self.desired=None;return
        if self.ready and self.target_callback(wanted):
            self.desired=None
        elif self.valid:
            self.flush_id=self.after(30,self.flush_target)
    def draw(self):
        self.delete('all')
        w, h = max(45, self.winfo_width()), max(40, self.winfo_height())
        x = w/2
        position=getattr(self,'visual_target',None)
        if position is None:position=self.value
        ratio = 0 if position is None else max(0,min(1,(position-self.low)/(self.high-self.low)))
        ink = ACCENT if self.valid and self.value is not None else MUTED
        if self.kind == 'dial':
            y, r = (h-16)/2, min(19,(h-20)/2)
            self.create_arc(x-r,y-r,x+r,y+r,start=-45,extent=270,style='arc',outline='#555b61',width=2)
            if self.value is not None:
                angle = math.radians(225-270*ratio)
                self.create_line(x,y,x+(r-5)*math.cos(angle),y-(r-5)*math.sin(angle),fill=ink,width=2)
                self.create_arc(x-r,y-r,x+r,y+r,start=225,extent=-270*ratio,style='arc',outline=ink,width=2)
            text = self.readout or ('—' if self.value is None else f'{self.value:.1f}')
            self.create_text(x,h-8,text=text,fill=ink,font=('DejaVu Sans',9))
        else:
            top, bottom = 14, h-32
            self.create_line(x,top,x,bottom,fill='#101214',width=7)
            for db in (6,0,-12,-24,-36,-48,-60):
                if db > self.high: continue
                y=bottom-(db-self.low)/(self.high-self.low)*(bottom-top)
                self.create_line(x-18,y,x-10,y,fill='#62686e')
                self.create_text(w-2,y,text=str(db),anchor='e',fill=MUTED,font=('DejaVu Sans',8))
            if self.value is not None:
                y=bottom-ratio*(bottom-top)
                # Launch Control-style dark cap: bevelled edges and a bright
                # horizontal position marker. Drawn locally at canvas scale.
                half=min(22,max(12,(w-40)/2))
                l,r=x-half,x+half;t,b=y-11,y+11
                self.create_rectangle(l+2,t+3,r+3,b+3,fill='#141618',outline='')
                self.create_polygon(l,t,r,t,r,b,l,b,fill='#383b3e',outline='#191b1d')
                self.create_polygon(l,t,r,t,r-5,t+5,l+5,t+5,fill='#5b5e61',outline='')
                self.create_polygon(l,t,l+5,t+5,l+5,b-5,l,b,fill='#484c4f',outline='')
                self.create_polygon(r,t,r,b,r-5,b-5,r-5,t+5,fill='#24272a',outline='')
                self.create_polygon(l,b,l+5,b-5,r-5,b-5,r,b,fill='#202326',outline='')
                self.create_line(l+2,y,r-2,y,fill='#e2e7e6' if self.valid else '#858b8e',width=3)
            self.create_text(x,h-13,text=self.readout or ('—' if self.value is None else f'{self.value:.2f} dB'),fill=ink,font=('DejaVu Sans',10))


def align_gain_rows(strips,visible):
    """Reserve the actual analog heading/label/dial height in mixed banks."""
    height=0
    for source in visible:
        if source not in strips:continue
        preamp=strips[source].preamp
        if source>16 or not hasattr(preamp,'heading'):continue
        row=max((preamp.labels[ch].winfo_reqheight()+int(dial.cget('height'))
                 for ch,dial in preamp.gains.items()),default=0)
        height=max(height,preamp.heading.winfo_reqheight()+row)
    for strip in strips.values():
        preamp=strip.preamp
        spacer=getattr(preamp,'gain_spacer',None)
        if spacer is None:continue
        if height:
            configure_changed(spacer,height=height)
            if not spacer.winfo_manager():spacer.pack(fill='x',before=preamp.link)
        elif spacer.winfo_manager():spacer.pack_forget()


class DigitalControls:
    """Digital membership link button; no analog preamp controls."""
    def __init__(self,parent,controller):
        self.c=controller
        self.gains={};self.source_button=None
        self.frame=tk.Frame(parent,bg=PANEL);self.frame.pack(fill='x',pady=(3,0))
        self.gain_spacer=tk.Frame(self.frame,bg=PANEL,height=0)
        self.gain_spacer.pack_propagate(False)
        self.link=button(self.frame,'LINK',self.toggle_link);self.link.pack(fill='x',padx=3,pady=2)
        self.source_slot=tk.Frame(self.frame,bg=PANEL,height=1)
        self.source_slot.pack(fill='x')
        self.source_slot.pack_propagate(False)
    def refresh(self):
        c=self.c;source=c.source.get();left=((source-1)//2)*2+1
        raw=c.state.get('raw',{});mono,pairs=raw.get('show'),raw.get('stereo')
        mask=3<<(left-1);bit=1<<((left-1)//2)
        known=type(mono) is int and type(pairs) is int
        linked=known and bool(pairs&bit)
        valid=known and ((mono&mask==mask and not linked) or (mono&mask==0 and linked))
        number=left-16 if left<=32 else left-32
        ready=c.app.connected and not c.stale and not c.pending and valid
        configure_changed(self.link,text=('UNLINK ' if linked else 'LINK ')+f'{number}/{number+1}',
                          state='normal' if ready else 'disabled',bg=ACCENT if linked else '#383c41',fg=BG if linked else TEXT)
    def toggle_link(self):
        if self.link.cget('state') not in ('normal','active'):return
        self.c.app.dashboard.link_digital(self.c.source.get())


class Strip:
    def __init__(self, parent, controller):
        self.c = controller
        controller.view = self
        self.frame = tk.Frame(parent, bg=PANEL, width=108, highlightbackground='#41454a', highlightthickness=1)
        self.frame.pack_propagate(False)
        self.title = lab(self.frame, 'ANALOG', font=('DejaVu Sans',9,'bold'),height=2,wraplength=100)
        self.title.pack(fill='x', pady=(4,3))
        self.title.bind('<Double-Button-1>',self.rename_title)
        self.title.bind('<Button-3>',self.rename_title)
        if controller.source.get()<=32:self.title.configure(cursor='hand2')
        self.mode = lab(self.frame, 'Reading…',fg=MUTED,font=('DejaVu Sans',8),height=2)
        self.mode.pack(pady=(0,3))
        self.dials, self.mutes = {}, {}
        for aux in range(1,5):
            row = tk.Frame(self.frame,bg=PANEL);row.pack(fill='x',padx=3)
            lab(row,f'AUX {aux}',fg=MUTED,font=('DejaVu Sans',8)).pack(side='left',anchor='center',pady=(0,16))
            b=button(row,'M',lambda a=aux:controller.toggle_send(a),width=1)
            b.configure(padx=3);b.pack(side='right',anchor='center',pady=(0,16));self.mutes[aux]=b
            dial=ValueControl(row,lambda d,a=aux:controller.step_send(a,d),target=lambda v,a=aux:controller.target('send'+str(a),v))
            dial.configure(width=40);dial.pack(side='left',fill='x',expand=True);self.dials[aux]=dial
        from preamp_view import PreampControls
        self.preamp=(PreampControls if controller.source.get()<=16 else DigitalControls)(self.frame,controller)
        self.pan=ValueControl(self.frame,controller.nudge_pan,low=0,high=254,target=lambda v:controller.target('pan',v))
        self.pan.pack(fill='x',pady=(4,0))
        self.pan_label=lab(self.frame,'PAN',fg=MUTED,font=('DejaVu Sans',8));self.pan_label.pack()
        switches=tk.Frame(self.frame,bg=PANEL);switches.pack(pady=3)
        self.mute=button(switches,'M',controller.toggle,width=2);self.mute.pack(side='left',padx=2)
        self.solo=button(switches,'S',lambda:controller.toggle('solo'),width=2);self.solo.pack(side='left',padx=2)
        self.pad=button(switches,'P',self.toggle_pad,width=2);self.pad.pack(side='left',padx=2)
        track=tk.Frame(self.frame,bg=PANEL);track.pack(fill='both',expand=True,padx=3)
        self.meter=Meter(track);self.meter.pack(side='right',fill='y')
        self.fader=ValueControl(track,controller.step,kind='fader',target=lambda v:controller.target('level',v));self.fader.pack(side='left',fill='both',expand=True)
        self.refresh()
    def toggle_pad(self):
        from strip_pad import toggle
        toggle(self)

    def refresh_pad(self):
        from strip_pad import refresh
        refresh(self)

    def rename_title(self,event):
        from quick_names import rename_targets,rename_input
        targets=rename_targets(self.c.source.get(),bool(self.c.state.get('stereo_members')))
        if not targets:return 'break'
        if len(targets)==1:rename_input(self.c.app,targets[0]);return 'break'
        # Linked channels retain independent hardware names; choose explicitly.
        from channel_names import source_label
        previous=getattr(self,'rename_menu',None)
        if previous is not None:previous.destroy()
        menu=tk.Menu(self.title,tearoff=False);self.rename_menu=menu
        for source in targets:
            menu.add_command(label='Rename '+source_label(source)+'…',command=lambda source=source:rename_input(self.c.app,source))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return 'break'

    def refresh_title(self):
        c,s=self.c,self.c.state
        source=c.source.get();stereo=bool(s.get('stereo_members'))
        cache=getattr(c.app,'name_cache',None)
        bank='ANALOG' if source<=16 else 'ADAT' if source<=32 else 'USB'
        number=source if source<=16 else source-16 if source<=32 else source-32
        number=f'{number}/{number+1}' if stereo else str(number)
        fallback=f'{bank} {number}'
        configure_changed(self.title,text=cache.title(source,stereo) if cache and source<=32 else fallback)
        mode='STEREO' if stereo else 'MONO' if s.get('mono_selected') else 'NOT IN MIX' if s else 'READING'
        configure_changed(self.mode,text=f'{bank} {number}\n{mode}')

    def refresh(self):
        c, s = self.c, self.c.state
        pair=s.get('stereo_members',[])
        source=c.source.get()
        self.refresh_title()
        self.preamp.refresh()
        self.refresh_pad()
        for a,dial in self.dials.items():
            send=s.get('stereo_sends',{}).get(str(a))
            values=send['levels'] if send else [s.get(f'aux{a}_send_level')]
            value=values[0] if values and values[0] is not None else None
            readout = ' / '.join('—' if v is None else f'{v/256:.1f}' for v in values) if len(values)==2 and values[0]!=values[1] else None
            dial.update_value(None if value is None else value/256,any(c.send_steps[a,d].cget('state') in ('normal','active') for d in (-1,1)),readout,valid=c.app.connected and not c.stale)
            mutes=send['mutes'] if send else [s.get(f'send{a}')]
            sync_button(self.mutes[a],c.send_buttons[a],bool(mutes) and all(x==1 for x in mutes), '#df776b',busy=c.pending and not c.stale)
        stereo_pan=s.get('stereo_pan',{})
        if pair:
            position=stereo_pan.get('position')
            valid=c.app.connected and not c.stale and position is not None
            readout=('Centre' if position==127 else ('L ' if position<127 else 'R ')+str(round(abs(position-127)))) if stereo_pan.get('canonical') else 'Custom L/R'
            self.pan.update_value(position,valid and not c.pending and c.app.info.get('state_version')==18,readout=readout,valid=valid)
        else:
            self.pan.update_value(s.get('raw',{}).get('pan'),any(c.pan_edit[a].cget('state') in ('normal','active') for a in ('L step','R step')),valid=c.app.connected and not c.stale)
        configure_changed(self.pan_label,text='STEREO PAN' if pair else 'PAN')
        for control,widget,field,color in (('mute',self.mute,c.mute_button,'#df776b'),('solo',self.solo,c.solo_button,'#dab86c')):
            active=all(m[control]==1 for m in pair) if pair else s.get(control)==1
            sync_button(widget,field,active,color,busy=c.pending and not c.stale)
        levels=[m['level_db'] for m in pair]
        readout=' / '.join('—' if v is None else f'{v:.1f}' for v in levels) if len(levels)==2 and levels[0]!=levels[1] else None
        self.fader.update_value(s.get('level_db'),any(b.cget('state') in ('normal','active') for b in c.level_buttons.values()),readout,valid=c.app.connected and not c.stale)


class MasterStrip:
    def __init__(self,parent,controller,dashboard):
        self.c,self.dashboard=controller,dashboard
        controller.view=self
        self.frame=tk.Frame(parent,bg='#25282c',width=164,padx=8)
        self.frame.pack(side='left',fill='y',padx=(5,0));self.frame.pack_propagate(False)
        self.header=tk.Frame(self.frame,bg='#25282c',height=400);self.header.pack(fill='x');self.header.pack_propagate(False)
        self.title=lab(self.header,'MAIN MASTER',fg=ACCENT,font=('DejaVu Sans',11,'bold'));self.title.pack(pady=(13,8))
        self.dials,self.mutes,self.pres={},{},{}
        self.aux_meters={}
        for a in range(1,5):
            bus=f'aux{a}'
            row=tk.Frame(self.header,bg=self.frame.cget('bg'));row.pack(fill='x')
            lab(row,f'AUX {a}',fg=MUTED,font=('DejaVu Sans',8)).pack(side='left',pady=(0,16))
            side=tk.Frame(row,bg=row.cget('bg'));side.pack(side='right')
            b=button(side,'M',lambda b=bus:controller.toggle_mute(b),width=1);b.configure(padx=3);b.pack();self.mutes[bus]=b
            b=button(side,'PRE',lambda b=bus:controller.toggle_pre(b),width=3);b.configure(padx=2,pady=1);b.pack();self.pres[bus]=b
            control=tk.Frame(row,bg=row.cget('bg'));control.pack(side='left',fill='x',expand=True)
            meter=Meter(control,caption='');meter.configure(width=16,height=40);meter.pack(side='right',fill='y');self.aux_meters[bus]=meter
            dial=ValueControl(control,lambda d,b=bus:controller.step(b,d),high=0,target=lambda v,b=bus:controller.target(b,v));dial.configure(width=40);dial.pack(side='left',fill='x',expand=True);self.dials[bus]=dial
        self.cue=button(self.header,'CUE ENABLE',controller.toggle_cue);self.cue.pack(fill='x',pady=(13,6))
        button(self.header,'Aux stereo links',dashboard.app.open_aux_links).pack(fill='x',pady=(0,8))
        track=tk.Frame(self.frame,bg=self.frame.cget('bg'));track.pack(fill='both',expand=True)
        self.meter=Meter(track);self.meter.pack(side='right',fill='y')
        self.fader=ValueControl(track,lambda d:controller.step(dashboard.bus,d),kind='fader',high=0,target=lambda v:controller.target(dashboard.bus,v))
        self.fader.preview_drag=True
        self.fader.pack(side='left',fill='both',expand=True)
        self.minimum_width=164
    def refresh(self):
        c,s=self.c,self.c.state
        configure_changed(self.title,text=self.dashboard.bus.upper()+' MASTER')
        for bus,dial in self.dials.items():
            dial.update_value(s.get('levels',{}).get(bus,{}).get('db'),any(c.buttons[bus,d].cget('state') in ('normal','active') for d in (-1,1)),valid=c.app.connected and (bus,'level') not in c.unavailable)
            sync_button(self.mutes[bus],c.mute_buttons[bus],s.get('aux_mutes',{}).get(bus)==1,'#df776b',busy=(bus,'mute') in c.pending)
            sync_button(self.pres[bus],c.pre_buttons[bus],s.get('aux_pre',{}).get(bus)==1,busy=(bus,'pre') in c.pending)
        sync_button(self.cue,c.cue_button,s.get('cue_enabled')==1,busy=('cue','enable') in c.pending)
        bus=self.dashboard.bus
        self.fader.update_value(s.get('levels',{}).get(bus,{}).get('db'),any(c.buttons[bus,d].cget('state') in ('normal','active') for d in (-1,1)),valid=c.app.connected and (bus,'level') not in c.unavailable)


class Console:
    def __init__(self,app,parent):
        self.app,self.bus,self.active=app,'main',True
        self.bank_start=1
        self.inflight=None; self.next_source=1; self.next_read=0; self.loading_layout=True
        self.meter_serial=None;self.latest_meters=None;self.meter_time=0
        self.master_inflight=False;self.next_master_read=0
        self.preamp_states={};self.preamp_pending=set()
        self.frame=tk.Frame(parent,bg=BG)
        self.frame.pack(fill='both',expand=True)
        row=tk.Frame(self.frame,bg=BG);row.pack(fill='x',pady=(0,8))
        self.bus_buttons={}
        for bus in ('main','cue'):
            b=button(row,bus.upper()+' MIX',lambda b=bus:self.change_bus(b));b.pack(side='left',padx=(0,6));self.bus_buttons[bus]=b
        button(row,'Sources…',app.open_mixer_sources).pack(side='left',padx=10)
        button(row,'Names…',app.open_channel_names).pack(side='left',padx=4)
        self.previous_page=button(row,'◀ Channels',lambda:self.change_channel_page(-1));self.previous_page.pack(side='left',padx=4)
        self.next_page=button(row,'Channels ▶',lambda:self.change_channel_page(1));self.next_page.pack(side='left',padx=4)
        lab(row,'Drag · Shift: fine · Scroll / arrows: step · Double-click / Enter: type value',fg=MUTED,font=('DejaVu Sans',9)).pack(side='right')
        banks=tk.Frame(self.frame,bg=BG);banks.pack(fill='x',pady=(0,4))
        self.bank_buttons={}
        for title,start in (('ANALOG',1),('ADAT 1–16',17),('USB 1–16',33),('USB 17–32',49)):
            b=button(banks,title,lambda start=start:self.change_bank(start));b.pack(side='left',padx=(0,6));self.bank_buttons[start]=b
        self.scenes_button=button(banks,'Fader scenes…',app.open_fader_scenes);self.scenes_button.pack(side='left',padx=8)
        self.meter_status=lab(self.frame,'Meters: waiting for connection',fg=MUTED,font=('DejaVu Sans',8));self.meter_status.pack(anchor='w')
        body=tk.Frame(self.frame,bg=BG);body.pack(fill='both',expand=True);self.body=body
        area=tk.Frame(body,bg=BG);area.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(area,bg=BG,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.bank=tk.Frame(self.canvas,bg=BG)
        self.bank_id=self.canvas.create_window(0,0,window=self.bank,anchor='nw')
        self.canvas.bind('<Configure>',self.resize)
        self.master=MasterController(app);self.master_view=MasterStrip(self.bank,self.master,self)
        from output_strips import OutputStrip
        self.phones_strip=OutputStrip(self.bank,app,'phones');self.monitor_strip=OutputStrip(self.bank,app,'monitor')
        self.output_strips=[self.phones_strip,self.monitor_strip]
        self.phones_inflight=False;self.next_phones_read=0
        self.channel_page=0;self.page_slots=9;self.all_visible=[]

        self.controllers={i:ChannelController(app,'main',i) for i in bank_sources(1)}
        self.strips={i:Strip(self.bank,c) for i,c in self.controllers.items()}
        self.visible=[]
        self.layout()
        app.root.after(100,self.tick)
        app.root.after(50,self.meter_tick)
    def cancel_drags(self):
        for strip in self.strips.values():
            for widget in [strip.fader,strip.pan,*strip.dials.values(),*strip.preamp.gains.values()]:widget.cancel_drag()
        for output in getattr(self,'output_strips',[]):output.fader.cancel_drag()
        for widget in [self.master_view.fader,*self.master_view.dials.values()]:widget.cancel_drag()

    def link_digital(self,source):
        if not self.app.connected or not 17<=source<=64:return
        left=((source-1)//2)*2+1
        members=[self.controllers.get(i) for i in (left,left+1)]
        if any(c is None or c.pending for c in members):return
        c=self.controllers[source]
        if c.stale:return
        raw=c.state.get('raw',{});mono,pairs=raw.get('show'),raw.get('stereo')
        mask=3<<(left-1);bit=1<<((left-1)//2)
        if type(mono) is not int or type(pairs) is not int:return
        if not ((mono&mask==mask and not pairs&bit) or (mono&mask==0 and pairs&bit)):return
        self.cancel_drags()
        request=time.monotonic_ns();self.digital_pair_request=request
        for member in members:member.pending=True;member.refresh()
        self.app.message.config(text='Changing digital pair and checking device readback…',fg=MUTED)
        self.app.worker.commands.put(('digital_pair',dict(request_id=request,connection_serial=self.app.name_cache.serial,
            bus=self.bus,source=left,linked=not bool(pairs&bit),mono=mono,pairs=pairs)))

    def change_bank(self,start):
        if start not in (1,17,33,49) or start==self.bank_start:return
        if self.preamp_pending or any(c.pending for c in self.controllers.values()):return
        self.cancel_drags()
        self.bank_start=start;self.next_source=start;self.next_read=0;self.loading_layout=True
        for source in bank_sources(start,self.bus):
            if source not in self.controllers:
                c=ChannelController(self.app,self.bus,source)
                self.controllers[source]=c;self.strips[source]=Strip(self.bank,c)
            c=self.controllers[source]
            c.state={};c.stale=True;c.refresh()
            self.strips[source].meter.clear()
        self.layout()

    def change_bus(self,bus):
        if bus==self.bus:return
        if any(c.pending for c in self.controllers.values()):return
        self.cancel_drags()
        self.bus=bus;self.next_source=getattr(self,'bank_start',1);self.next_read=0;self.loading_layout=True
        for c in self.controllers.values():
            c.bus.set(bus);c.state={};c.stale=True;c.refresh()
        self.master.refresh();self.layout()
        self.master_view.meter.clear()
        if self.latest_meters:self.master_view.meter.feed(self.latest_meters[bus],self.meter_time)
    def change_channel_page(self,direction):
        if getattr(self,'bank_start',1)==1 and getattr(self,'bus','main')=='main':return
        pages=max(1,(len(self.all_visible)+self.page_slots-1)//self.page_slots)
        self.channel_page=max(0,min(pages-1,self.channel_page+direction));self.layout()
    def layout(self):
        # Match the real source button's requested height, including its padding,
        # rather than a pixel constant that fails under different font scaling.
        source_height=max((strip.preamp.source_button.winfo_reqheight()+4
                           for strip in self.strips.values() if strip.preamp.source_button is not None),default=0)
        for strip in self.strips.values():
            configure_changed(strip.preamp.source_slot,height=source_height)
        visible=[]
        for i in bank_sources(getattr(self,'bank_start',1),getattr(self,'bus','main')):
            if i not in self.controllers:continue
            c=self.controllers[i]
            if i%2==0 and self.controllers[i-1].state.get('stereo_members'): continue
            visible.append(i)
        if hasattr(self,'output_strips'):
            self.all_visible=visible
            if getattr(self,'bank_start',1)==1 and getattr(self,'bus','main')=='main':
                self.page_slots=max(1,len(visible));self.channel_page=0
            pages=max(1,(len(visible)+self.page_slots-1)//self.page_slots)
            self.channel_page=min(self.channel_page,pages-1)
            visible=visible[self.channel_page*self.page_slots:(self.channel_page+1)*self.page_slots]
            configure_changed(self.previous_page,state='normal' if self.channel_page else 'disabled')
            configure_changed(self.next_page,state='normal' if self.channel_page+1<pages else 'disabled')
        if visible!=self.visible:
            # A different bank can have the same strip count but newly created
            # frames. Their initial widths must not reuse the previous cache.
            self.bank_size=None
            self.master_view.frame.pack_forget()
            for output in getattr(self,'output_strips',[]):output.frame.pack_forget()
            for strip in self.strips.values():strip.frame.pack_forget()
            for i in visible:self.strips[i].frame.pack(side='left',fill='y',expand=False,padx=(0,3))
            for output in getattr(self,'output_strips',[]):output.frame.pack(side='left',fill='y',expand=False,padx=(0,3))
            self.master_view.frame.pack(side='left',fill='y',expand=False,padx=(5,0))
            self.visible=visible
        for bus,b in self.bus_buttons.items():configure_changed(b,bg=ACCENT if bus==self.bus else '#383c41',fg=BG if bus==self.bus else TEXT)
        for start,b in getattr(self,'bank_buttons',{}).items():configure_changed(b,bg=ACCENT if start==self.bank_start else '#383c41',fg=BG if start==self.bank_start else TEXT)
        self.resize()
    def resize(self,event=None):
        if hasattr(self,'output_strips'):
            fit_main=getattr(self,'bank_start',1)==1 and getattr(self,'bus','main')=='main'
            slots=max(1,len(getattr(self,'all_visible',self.visible))) if fit_main else max(1,min(9,(self.canvas.winfo_width()-3*164-14)//167))
            if slots!=self.page_slots:
                self.page_slots=slots;self.channel_page=0;self.layout();return
        count=max(1,len(self.visible))+len(getattr(self,'output_strips',[]))
        minimum=getattr(self.master_view,'minimum_width',164)
        if hasattr(self,'output_strips'):
            widths,width,height,dial_height=expanded_geometry(self.canvas.winfo_width(),self.canvas.winfo_height(),count,minimum,fit=fit_main)
        else:
            channel_width,width,height,dial_height=fixed_geometry(count,minimum)
            widths=[channel_width]*(count+1)
        by_source=dict(zip(self.visible,widths))
        if getattr(self,'bank_size',None)==(width,height) and getattr(self,'bank_visible_count',None)==len(self.visible):
            align_gain_rows(getattr(self,'strips',{}),self.visible)
            return
        master_width=widths[-1]
        master_frame=getattr(self.master_view,'frame',None)
        if master_frame is not None:configure_changed(master_frame,width=master_width)
        for index,output in enumerate(getattr(self,'output_strips',[])):
            configure_changed(output.frame,width=widths[len(self.visible)+index])
        for source,strip in self.strips.items():
            channel_width=by_source.get(source,minimum)
            configure_changed(strip.frame,width=channel_width)
            configure_changed(strip.title,wraplength=max(1,channel_width-4))
            for dial in [strip.pan,*strip.dials.values(),*strip.preamp.gains.values()]:configure_changed(dial,height=dial_height)
        for dial in self.master_view.dials.values():configure_changed(dial,height=dial_height)
        align_gain_rows(self.strips,self.visible)
        self.bank_size=(width,height)
        self.bank_visible_count=len(self.visible)
        self.canvas.itemconfigure(self.bank_id,width=width,height=height)
        self.canvas.configure(scrollregion=(0,0,width,height))
    def meter_tick(self):
        now=time.monotonic()
        if self.active:
            for i in self.visible:self.strips[i].meter.draw(now)
            for output in getattr(self,'output_strips',[]):output.meter.draw(now)
            self.master_view.meter.draw(now)
            for meter in self.master_view.aux_meters.values():meter.draw(now)
        if self.latest_meters and now-self.meter_time>.5:
            configure_changed(self.meter_status,text='Meters: signal data stale')
        self.app.root.after(50,self.meter_tick)

    def tick(self):
        if hasattr(self,'phones_strip') and self.active and self.app.connected and not self.phones_inflight and time.monotonic()>=self.next_phones_read:
            self.phones_inflight=True;self.app.worker.commands.put(('phones_read',None))
        if self.active and self.app.connected and not self.master_inflight and time.monotonic()>=self.next_master_read:
            self.master_inflight=True
            self.app.worker.commands.put(('masters_read',None))
        if self.active and self.app.connected and not self.inflight and time.monotonic()>=self.next_read:
            source=self.next_source
            self.inflight=(self.bus,source)
            self.app.worker.commands.put(('console_read',self.inflight))
        self.app.root.after(40,self.tick)
    def handle(self,event):
        kind=event['kind']
        if kind in ('phones_written','phones_write_error'):
            if event.get('connection_serial')!=self.app.name_cache.serial:return
            self.phones_strip.phones_result(event)
            self.next_phones_read=0
            return
        if kind in ('phones_snapshot','phones_error'):
            if event.get('connection_serial')!=self.app.name_cache.serial:return
            self.phones_inflight=False;self.next_phones_read=time.monotonic()+.5
            self.phones_strip.phones_state(event.get('state',{}));return

        if kind in ('digital_pair_state','digital_pair_error'):
            if event.get('request_id')!=getattr(self,'digital_pair_request',None) or getattr(self,'digital_pair_request',None) is None:return
            self.digital_pair_request=None
            left=event['source']
            for source in (left,left+1):
                c=self.controllers[source];c.pending=False;c.state={};c.stale=True
                if kind=='digital_pair_state':
                    state=next(s for s in event['states'] if s['source']==source)
                    c.handle(dict(kind='input_snapshot',state=state))
                else:c.refresh()
            self.layout();self.next_source=left;self.next_read=0
            self.app.message.config(text='Digital pair updated from device readback.' if kind=='digital_pair_state' else event['message'],fg=MUTED if kind=='digital_pair_state' else '#efba76')
            return
        if kind in ('masters_snapshot','masters_error'):
            self.master_inflight=False;self.next_master_read=time.monotonic()+.2
            self.master.handle({'kind':'input_snapshot','state':event['state']} if kind=='masters_snapshot' else
                               {'kind':'input_error','channel':'masters','message':event['message']})
            return
        if kind in ('pair_state','pair_error'):
            left=((event['source']-1)//2)*2+1
            if kind=='pair_state':
                for state in event['states']:
                    self.controllers[state['source']].handle({'kind':'input_snapshot','state':state})
                self.layout()
            else:
                self.preamp_pending.discard(left)
                for i in (left,left+1):
                    self.controllers[i].state={};self.controllers[i].stale=True;self.controllers[i].refresh()
                self.app.message.config(text=event['message'],fg='#efba76')
                self.next_source=left;self.next_read=0
            return
        if kind in ('preamp_state','preamp_error'):
            source=event['source'];left=((source-1)//2)*2+1
            if left in self.preamp_pending and not event.get('operation'):return
            if event.get('operation'):self.preamp_pending.discard(left)
            if kind=='preamp_state':
                for state in event['states']:self.preamp_states[state['source']]=state
            else:
                for i in (left,left+1):self.preamp_states.pop(i,None)
                self.app.message.config(text=event['message'],fg='#efba76')
            for i in (left,left+1):
                self.strips[i].preamp.refresh()
                self.strips[i].refresh_pad()
            return
        if kind=='meter_frame':
            if event.get('connection_serial')!=self.meter_serial:return
            frame=event['state'];now=time.monotonic()
            self.latest_meters=frame;self.meter_time=now
            for i,strip in self.strips.items():
                count=2 if strip.c.state.get('stereo_members') else 1
                values=frame['inputs'] if i<=32 else frame['usb']
                index=i-1 if i<=32 else i-33
                strip.meter.feed(values[index:index+count],now)
            if hasattr(self,'output_strips'):
                self.phones_strip.meter.feed(frame['phones'],now);self.monitor_strip.meter.feed(frame['speakers'],now)
            self.master_view.meter.feed(frame[self.bus],now)
            for a,meter in enumerate(self.master_view.aux_meters.values()):meter.feed([frame['aux'][a]],now)
            configure_changed(self.meter_status,text=('DEMO · synthetic meters' if self.app.demo else 'Live input meters · master L/R · −60 to 0 dBFS'))
            return
        if kind=='meter_error':
            if event.get('connection_serial')!=self.meter_serial:return
            self.latest_meters=None
            for strip in self.strips.values():strip.meter.clear()
            self.master_view.meter.clear()
            for meter in self.master_view.aux_meters.values():meter.clear()
            configure_changed(self.meter_status,text='Meters unavailable · '+event['message']+' · reconnect to retry')
            return
        if kind in ('console_snapshot','console_error'):
            self.inflight=None
            bus,source=event['bus'],event['source']
            sources=bank_sources(getattr(self,'bank_start',1),self.bus)
            if bus!=self.bus or (source and source not in sources):return
            if kind=='console_snapshot':
                controller=self.master if source==0 else self.controllers[source]
                controller.handle({'kind':'input_snapshot','state':event['state']})
                if not getattr(self,'loading_layout',False):self.layout()
            else:
                controller=self.master if source==0 else self.controllers[source]
                controller.handle({'kind':'input_error','channel':'masters' if source==0 else 'mix_channel','bus':bus,'source':source,'message':event['message']})
            offset=sources.index(source)+1 if source else len(sources)
            if source and source%2 and self.controllers[source].state.get('stereo_members'):offset+=1
            self.next_source=sources[offset] if offset<len(sources) else 0
            if source==0:
                if getattr(self,'loading_layout',False):
                    self.loading_layout=False;self.layout()
                self.next_source=getattr(self,'bank_start',1);self.next_read=time.monotonic()+1
        elif kind in ('input_written','input_error','input_snapshot'):
            state=event.get('state',{})
            channel=event.get('channel',state.get('channel'))
            if channel=='masters':self.master.handle(event)
            elif channel=='mix_channel':
                source=event.get('source',state.get('source'))
                if source in self.controllers:self.controllers[source].handle(event)
        elif kind in ('error','disconnected','connected','preset_state_reset'):
            self.digital_pair_request=None
            self.phones_inflight=False;self.next_phones_read=0
            for output in getattr(self,'output_strips',[]):output.clear()
            self.master_inflight=False;self.next_master_read=0
            self.preamp_states.clear();self.preamp_pending.clear()
            self.meter_serial=event.get('connection_serial') if kind in ('connected','preset_state_reset') else None
            self.latest_meters=None
            for strip in self.strips.values():strip.meter.clear()
            self.master_view.meter.clear()
            for meter in self.master_view.aux_meters.values():meter.clear()
            configure_changed(self.meter_status,text='Meters: waiting for signal data' if kind in ('connected','preset_state_reset') else 'Meters: disconnected')
            self.inflight=None;self.next_source=getattr(self,'bank_start',1);self.next_read=0;self.loading_layout=True
            for c in self.controllers.values():
                c.state={};c.stale=True;c.pending=False;c.refresh()
            self.master.state={};self.master.pending.clear();self.master.refresh()
        elif kind in ('command_error','recovering'):
            for c in self.controllers.values():c.stale=True;c.refresh()


class EmbeddedPanel(tk.Frame):
    def __init__(self,app):
        super().__init__(app.page_host,bg=BG)
        self.app=app
        show_page(app,self)
    def title(self,text):
        self.app.page_title.config(text=text.replace('AF16Rig — ','').replace(' — TEST70','').upper())
    def geometry(self,*args):pass
    def minsize(self,*args):pass
    def protocol(self,*args):pass
    def destroy(self):
        super().destroy()


def build_console(app):
    root=app.root
    style=ttk.Style(root)
    style.theme_use('clam')
    style.configure('.',background=BG,foreground=TEXT,fieldbackground=PANEL)
    style.configure('TCombobox',fieldbackground=PANEL,foreground=TEXT,arrowcolor=TEXT)
    style.map('TCombobox',fieldbackground=[('disabled',BG),('readonly',PANEL)],
              foreground=[('disabled',MUTED),('readonly',TEXT)],
              selectbackground=[('disabled',BG),('readonly',PANEL)],
              selectforeground=[('disabled',MUTED),('readonly',TEXT)])
    root.option_add('*TCombobox*Listbox.background',PANEL)
    root.option_add('*TCombobox*Listbox.foreground',TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground','#32616a')
    root.option_add('*TCombobox*Listbox.selectForeground',TEXT)
    style.configure('Treeview',background=PANEL,foreground=TEXT,fieldbackground=PANEL,rowheight=27)
    style.configure('Treeview.Heading',background='#383c41',foreground=TEXT)
    style.map('Treeview',background=[('selected','#32616a')])
    header=tk.Frame(root,bg='#17191b',padx=20,pady=12);header.pack(fill='x')
    lab(header,'AUDIOFUSE 16RIG',font=('DejaVu Sans',21,'bold')).pack(side='left')
    lab(header,'LINUX CONTROL',fg=ACCENT,font=('DejaVu Sans',9,'bold')).pack(side='left',padx=20)
    app.connect_button=button(header,'Connect',app.connect);app.connect_button.pack(side='right')
    app.auto_reconnect=tk.BooleanVar(value=True)
    ttk.Checkbutton(header,text='Auto reconnect',variable=app.auto_reconnect,command=lambda:app.worker.commands.put(('auto_reconnect',app.auto_reconnect.get()))).pack(side='right',padx=10)
    app.connection=lab(header,'Disconnected',fg=MUTED);app.connection.pack(side='right',padx=20)
    from navigation_bar import NavigationBar
    nav=NavigationBar(root,bg='#292c30',padx=14,pady=7);nav.pack(fill='x');app.navigation=nav
    for title,callback in (('MIXER',app.show_mixer),('FRONT 1–2',app.open_front_inputs),('FRONT 3–4',app.open_mini_inputs),('REAR INPUTS',app.open_inputs),('OUTPUTS',app.open_outputs),('ROUTING',app.open_routing),('MONITOR',app.open_monitor_settings),('PRESETS',app.open_device_presets),('CLOCK',app.open_clock_status),('METERS',app.open_meters),('MIDI',app.open_midi_config)):
        nav.add(button(nav.content,title,callback))
    monitor=tk.Frame(root,bg='#24272a',padx=20,pady=8);monitor.pack(fill='x')
    app.page_title=lab(monitor,'MIXER',fg=ACCENT,font=('DejaVu Sans',12,'bold'));app.page_title.pack(side='left')
    app.controls={};app.volume_buttons={};app.level=Field()
    footer=tk.Frame(root,bg='#17191b',padx=15,pady=6);footer.pack(side='bottom',fill='x')
    app.message=lab(footer,'Connecting…',fg=MUTED,anchor='w');app.message.pack(side='left',fill='x',expand=True)
    app.details=lab(footer,'DEMO · no hardware' if app.demo else 'Native USB',fg=MUTED);app.details.pack(side='right')
    app.log_button=button(footer,'Log (0)',app.open_event_log);app.log_button.pack(side='right',padx=8)
    app.page_host=tk.Frame(root,bg=BG,padx=14,pady=10);app.page_host.pack(fill='both',expand=True)
    app.dashboard=Console(app,app.page_host)
