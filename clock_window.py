"""Decoded clock status and checked native clock settings."""
import json
import uuid
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from clock_status import LABELS
from clock_controls import OPTIONS,CONFIG,ENUMS,RATES
from mixer_view import configure_changed

class ClockWindow:
    def __init__(self,app):
        self.app=app;self.channel=tk.StringVar(value='clock');self.state=None
        self.pending=None;self.last_read=0;self.choices={};self.apply_buttons={}
        self.window=app.make_panel();self.window.title('AF16Rig — Clock / audio status')
        shell=ttk.Frame(self.window,padding=20);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='CLOCK / AUDIO STATUS',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        ttk.Label(shell,text='Clock changes can interrupt audio. Apply a sample rate only with Internal clock and idle audio streams. Your audio application may select its own rate when reopened.',wraplength=950).pack(anchor='w',pady=8)
        self.summary=ttk.Label(shell,text='Reading…');self.summary.pack(anchor='w',pady=8)
        self.streams=ttk.Treeview(shell,columns=('stream','rate','channels','format','state'),show='headings',height=5)
        for field,label,width in [('stream','ALSA stream',250),('rate','Configured rate',160),('channels','Channels',90),('format','Format',100),('state','State',120)]:
            self.streams.heading(field,text=label);self.streams.column(field,width=width)
        self.streams.pack(fill='x')
        ttk.Label(shell,text='Device clock settings — decoded from the 16Rig parameter files. Clock validity remains a raw bitmask.',wraplength=950).pack(anchor='w',pady=(16,8))
        self.registers=ttk.Treeview(shell,columns=('field','decoded','value'),show='headings',height=9)
        self.registers.heading('decoded',text='Current setting');self.registers.column('decoded',width=200);self.registers.heading('field',text='Device field');self.registers.heading('value',text='Raw readback')
        self.registers.column('field',width=300);self.registers.column('value',width=150);self.registers.pack(fill='both',expand=True)
        controls=ttk.Frame(shell);controls.pack(fill='x',pady=8)
        for index,(field,options) in enumerate(OPTIONS.items()):
            ttk.Label(controls,text=LABELS[field]).grid(row=index,column=0,sticky='w',padx=5)
            choice=ttk.Combobox(controls,values=options,state='disabled',width=22)
            choice.grid(row=index,column=1,padx=5,pady=2);self.choices[field]=choice
            button=ttk.Button(controls,text='Apply',command=lambda f=field:self.apply(f),state='disabled')
            button.grid(row=index,column=2,padx=5);self.apply_buttons[field]=button
        rate_row=ttk.Frame(shell);rate_row.pack(fill='x',pady=4)
        ttk.Label(rate_row,text='Sample rate (idle device)').pack(side='left',padx=5)
        self.rate_choice=ttk.Combobox(rate_row,values=[f'{r:,} Hz' for r in RATES[1:]],state='disabled',width=22);self.rate_choice.pack(side='left',padx=5)
        self.rate_button=ttk.Button(rate_row,text='Apply rate',command=self.apply_rate,state='disabled');self.rate_button.pack(side='left',padx=5)
        self.rate_note=ttk.Label(shell,text='',wraplength=950);self.rate_note.pack(anchor='w')
        self.write_status=ttk.Label(shell,text='',wraplength=950);self.write_status.pack(anchor='w')
        row=ttk.Frame(shell);row.pack(fill='x',pady=10)
        ttk.Button(row,text='Refresh / retry',command=self.refresh).pack(side='left')
        self.save_button=ttk.Button(row,text='Save clock report',command=self.save,state='disabled');self.save_button.pack(side='left',padx=10)
        self.message=ttk.Label(shell,text='Updates once per second while this page is open.',wraplength=950);self.message.pack(anchor='w')
        app.worker.commands.put(('input_select','clock'))
    @staticmethod
    def update_rows(table,rows):
        keep={key for key,_ in rows}
        for key in table.get_children():
            if key not in keep:table.delete(key)
        for key,values in rows:
            if not table.exists(key):table.insert('','end',iid=key,values=values)
            elif tuple(map(str,table.item(key,'values')))!=tuple(map(str,values)):table.item(key,values=values)
    def connection_changed(self):
        self.state=None;self.pending=None;self.sync_controls();self.save_button.config(state='disabled')
        self.update_rows(self.streams,[]);self.update_rows(self.registers,[])
        self.summary.config(text='Reading clock status from the new connection…')
        self.refresh()
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='clock':return
        if event['kind']=='input_error':
            self.state=None;self.pending=None;self.sync_controls();self.save_button.config(state='disabled');self.summary.config(text='Clock status unavailable')
            self.update_rows(self.streams,[]);self.update_rows(self.registers,[]);self.message.config(text=event['message']);return
        if event['kind']!='input_snapshot':return
        if state.get('connection_serial')!=self.app.name_cache.serial:return
        self.state=state;self.last_read=time.monotonic();self.sync_controls();alsa=state['alsa'];rows=[]
        for s in alsa['streams']:
            key='/'.join(s[k] for k in ('card','pcm','substream'))
            rows.append((key,(s['direction']+' · '+key,f"{s['rate_hz']:,} Hz" if s['rate_hz'] else '—',s['channels'] or '—',s['format'] or '—',s['state'])))
        self.update_rows(self.streams,rows)
        self.update_rows(self.registers,[(k,(label,state.get('decoded',{}).get(k,'—'),state['raw'].get(k,'—'))) for k,label in LABELS.items()])
        self.summary.config(text='DEMO · synthetic stream values' if state['demo'] else 'AF16Rig audio streams' if rows else 'No AF16Rig stream configuration available')
        messages=list(alsa['errors'])+list(state['errors'].values())
        self.message.config(text=' · '.join(messages) if messages else 'Stable device readback · choose a setting and press Apply.' if state['stable'] else 'Demo mode · no device clock registers read.')
        self.save_button.config(state='normal')
    def sync_controls(self):
        state=self.state or {};raw=state.get('raw',{})
        ready=(self.pending is None and state.get('stable',False) and
            all(type(raw.get(k)) is int and 0<=raw[k]<len(ENUMS[k]) for k in CONFIG))
        for field,choice in getattr(self,'choices',{}).items():
            configure_changed(choice,state='readonly' if ready else 'disabled')
            if not choice.get() and field in raw and type(raw[field]) is int and 0<=raw[field]<len(OPTIONS[field]):
                choice.current(raw[field])
            configure_changed(self.apply_buttons[field],state='normal' if ready else 'disabled')
        if hasattr(self,'rate_choice'):
            rate_ready=ready and raw.get('selected_source')==0 and raw.get('preferred_source')==0 and raw.get('internal_frequency') in range(1,7)
            reason='Ready — apply an exact hardware rate; reopening an audio application can change it again.' if rate_ready else 'Requires stable Internal clock and idle AF16Rig audio streams.'
            if rate_ready and not state.get('demo'):
                from sample_rate import idle_card
                try:idle_card(state.get('alsa',{}))
                except Exception as error:rate_ready=False;reason=str(error)
            if hasattr(self,'rate_note'):configure_changed(self.rate_note,text=reason)
            configure_changed(self.rate_choice,state='readonly' if rate_ready else 'disabled')
            configure_changed(self.rate_button,state='normal' if rate_ready else 'disabled')
            if not self.rate_choice.get() and raw.get('internal_frequency') in range(1,7):self.rate_choice.current(raw['internal_frequency']-1)
    def apply_rate(self):
        if self.rate_button.cget('state') not in ('normal','active'):return
        self.apply('sample_rate')
    def apply(self,field):
        if not self.state or self.pending or not self.app.connected or not self.state.get('stable') or time.monotonic()-self.last_read>3:return
        if self.state.get('connection_serial')!=self.app.name_cache.serial:return
        if field=='sample_rate':
            index=self.rate_choice.current()
            if not 0<=index<6:return
            target=RATES[index+1]
        else:
            target=self.choices[field].current()
            if target<0:return
        self.pending=uuid.uuid4().hex
        self.app.worker.commands.put(('clock_set',dict(field=field,target=target,
            expected=self.state['raw'].copy(),connection_serial=self.app.name_cache.serial,request_id=self.pending)))
        self.write_status.config(text='Applying clock setting…');self.sync_controls()
    def clock_result(self,event):
        if event.get('connection_serial')!=self.app.name_cache.serial or not self.pending or event.get('request_id')!=self.pending:return
        self.pending=None;self.state=None;self.sync_controls()
        self.write_status.config(text='Setting confirmed · reading updated clock state' if event['kind']=='clock_written' else event['message'])
        self.refresh()
    def refresh(self):
        if self.app.connected:self.app.worker.commands.put(('clock_refresh',None))
    def save(self):
        if not self.state:return
        path=filedialog.asksaveasfilename(title='Save clock report',initialfile='AF16Rig-clock-report.json',defaultextension='.json',filetypes=[('JSON report','*.json')])
        if path:
            try:Path(path).write_text(json.dumps({'format':'af16rig-clock-status-v1','build':'BETA RC','state':self.state},indent=2)+'\n')
            except OSError as error:self.message.config(text=str(error));return
            self.message.config(text='Clock report saved.')
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()
