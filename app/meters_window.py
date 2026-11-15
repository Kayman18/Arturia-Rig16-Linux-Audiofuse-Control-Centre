"""Read-only meter bridge reusing the worker's existing 20 Hz frames."""
import time
import copy
import json
from pathlib import Path
from tkinter import filedialog,messagebox
from meter_capture import capture
import tkinter as tk
from af16rig_gui import BG,PANEL,TEXT,MUTED,ACCENT
from meter_view import Meter
from meter_bridge import BANKS,MeterSession,label

class MetersWindow:
    def __init__(self,app):
        from mixer_view import button,lab
        self.app=app; self.closed=False; self.job=None; self.bank=None; self.tiles={}
        self.held=None; self.held_time=None; self.held_names={}
        self.channel=tk.StringVar(value='meters')
        self.session=MeterSession(app.dashboard.meter_serial)
        self.window=app.make_panel(); self.window.title('AF16Rig — Meters')
        self.window.configure(padx=10,pady=8)
        row=tk.Frame(self.window,bg=BG);row.pack(fill='x',pady=(0,6))
        self.buttons={}
        for bank in BANKS:
            b=button(row,bank.upper(),lambda bank=bank:self.show_bank(bank))
            b.pack(side='left',padx=(0,6));self.buttons[bank]=b
        button(row,'Reset all peaks',self.reset_peaks).pack(side='right')
        button(row,'Save snapshot…',self.save_snapshot).pack(side='right',padx=6)
        self.hold_button=button(row,'Hold',self.toggle_hold);self.hold_button.pack(side='right')
        lab(self.window,'Peak since opening / reset · red = observed ≥0 dBFS · click a peak to reset it',fg=MUTED).pack(anchor='w')
        self.status=lab(self.window,'Waiting for live meter data',fg=MUTED);self.status.pack(anchor='w',pady=4)
        self.body=tk.Frame(self.window,bg=BG);self.body.pack(fill='both',expand=True)
        for c in range(16):self.body.columnconfigure(c,weight=1,uniform='meters')
        for r in range(2):self.body.rowconfigure(r,weight=1,uniform='meters')
        app.worker.commands.put(('input_select',None))
        self.show_bank('Inputs')
        d=app.dashboard
        if d.latest_meters and time.monotonic()-d.meter_time<=.5:
            self.accept(d.meter_serial,d.latest_meters,d.meter_time)
        self.tick()
    def show_bank(self,bank):
        if bank == self.bank:return
        self.bank=bank
        for child in self.body.winfo_children():child.destroy()
        self.tiles={}
        for i,key in enumerate(BANKS[bank]):
            tile=tk.Frame(self.body,bg=PANEL);tile.grid(row=i//16,column=i%16,sticky='nsew',padx=2,pady=3)
            title=tk.Label(tile,bg=PANEL,fg=TEXT,text=label(key,self.display_names()),wraplength=72,font=('DejaVu Sans',8))
            title.pack(fill='x',pady=4)
            m=Meter(tile,caption='dBFS');m.pack(fill='both',expand=True)
            peak=tk.Button(tile,text='Peak —',command=lambda key=key:self.reset_peaks(key),bg=PANEL,fg=MUTED,relief='flat',borderwidth=0,font=('DejaVu Sans',8))
            peak.pack(fill='x',pady=3)
            self.tiles[key]=(title,m,peak)
            session=self.display_session()
            if session.frame and session.fresh(self.display_time()):m.feed([session.frame[key]],session.time)
        for name,b in self.buttons.items():b.config(bg=ACCENT if name==bank else '#363c41',fg=BG if name==bank else TEXT)
    def refresh_names(self):
        for key,(title,_,_) in self.tiles.items():
            text=label(key,self.display_names())
            if title.cget('text')!=text:title.config(text=text)
    def display_session(self):return getattr(self,'held',None) or self.session
    def display_time(self):return self.held_time if getattr(self,'held',None) else time.monotonic()
    def display_names(self):return self.held_names if getattr(self,'held',None) else self.app.name_cache.names
    def clear_hold(self):
        self.held=None;self.held_time=None;self.held_names={}
        if hasattr(self,'hold_button'):self.hold_button.config(text='Hold',bg='#363c41',fg=TEXT)
    def toggle_hold(self):
        if getattr(self,'held',None):self.clear_hold()
        else:
            now=time.monotonic()
            if not self.session.fresh(now):return
            self.held=copy.deepcopy(self.session);self.held_time=now
            self.held_names=dict(self.app.name_cache.names)
            self.hold_button.config(text='Resume',bg=ACCENT,fg=BG)
        session=self.display_session()
        for key,(_,meter,_) in self.tiles.items():
            meter.clear()
            if session.frame:meter.feed([session.frame[key]],session.time)
        self.refresh_names()
    def reset_peaks(self,key=None):
        self.session.reset_peaks(key)
        if getattr(self,'held',None):self.held.reset_peaks(key)
    def save_snapshot(self):
        # Freeze all banks and labels before the modal file picker processes events.
        data=capture(self.display_session(),self.display_names(),self.display_time(),
                     demo=self.app.demo,held=bool(getattr(self,'held',None)))
        path=filedialog.asksaveasfilename(parent=self.window,title='Save all meter readings',
            defaultextension='.json',initialfile='AF16Rig-meter-snapshot.json',
            filetypes=[('JSON snapshot','*.json')])
        if not path:return
        try:Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
        except OSError as e:messagebox.showerror('Snapshot not saved',str(e),parent=self.window)

    def accept(self,serial,frame,now):
        if not self.session.feed(serial,frame,now):return
        if getattr(self,'held',None):return
        for key,(_,meter,_) in self.tiles.items():meter.feed([self.session.frame[key]],now)
    def handle(self,event):pass
    def handle_meter_event(self,event):
        kind=event['kind']
        if kind in ('connected','preset_state_reset','disconnected','error'):
            self.clear_hold()
            self.session.reset(event.get('connection_serial') if kind in ('connected','preset_state_reset') else None)
            for key,(title,m,_) in self.tiles.items():
                m.clear();title.config(text=label(key,{}))
        elif kind=='meter_error' and event.get('connection_serial')==self.session.serial:
            self.clear_hold()
            self.session.reset(self.session.serial)
            for _,m,_ in self.tiles.values():m.clear()
        elif kind=='meter_frame':self.accept(event.get('connection_serial'),event['state'],time.monotonic())
    def tick(self):
        if self.closed:return
        now=self.display_time();session=self.display_session();fresh=session.fresh(now)
        message=('DEMO · synthetic meters' if self.app.demo else 'Live meters · −60 to 0 dBFS') if fresh else 'Meter data unavailable / stale · retained peaks are historical'
        if getattr(self,'held',None):message='HELD snapshot · live polling and peaks continue in background'
        if self.status.cget('text')!=message:self.status.config(text=message)
        for key,(_,meter,peak) in self.tiles.items():
            meter.draw(now)
            text=session.peak_text(key)
            color='#ef6961' if key in session.full_scale else ACCENT
            if peak.cget('text')!=text or peak.cget('fg')!=color:peak.config(text=text,fg=color)
        self.job=self.app.root.after(50,self.tick)
    def close(self):
        self.closed=True
        if self.job is not None:self.app.root.after_cancel(self.job)
        self.app.worker.commands.put(('input_select',None))
        self.app.input_window=None;self.window.destroy()
