"""On-demand MIDI port settings; shared single-flight page edit lock."""
import uuid
import tkinter as tk
from tkinter import ttk,filedialog
import json
from pathlib import Path
from midi_ports import OPTIONS,LABELS

class MidiPortsWindow:
    def __init__(self,parent):
        self.parent=parent;self.app=parent.app;self.serial=parent.serial
        self.closed=False;self.request=None;self.records={}
        self.window=tk.Toplevel(parent.window);self.window.title('AF16Rig — MIDI ports / sync')
        self.window.transient(parent.app.root);self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=ttk.Frame(self.window,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='MIDI PORTS / SYNC / ROUTING',font=('DejaVu Sans',16,'bold')).grid(row=0,column=0,columnspan=4,sticky='w',pady=8)
        self.selectors={};self.buttons={};self.values={}
        for row,field in enumerate(OPTIONS,1):
            ttk.Label(shell,text=LABELS[field]).grid(row=row,column=0,sticky='w',padx=6,pady=8)
            self.values[field]=ttk.Label(shell,text='Waiting');self.values[field].grid(row=row,column=1,padx=8)
            combo=ttk.Combobox(shell,values=OPTIONS[field],state='disabled',width=14);combo.grid(row=row,column=2,padx=8);self.selectors[field]=combo
            button=ttk.Button(shell,text='Apply',command=lambda f=field:self.apply(f),state='disabled');button.grid(row=row,column=3);self.buttons[field]=button
        ttk.Label(shell,text='USB Host Cable Number selects a cable/port on a connected USB MIDI device.\nIt is separate from MIDI message channel. DIN clock mode selects the sync format.\nMixer control source selects which MIDI input controls the main mixer.\nOutput-source routing applies to standalone MIDI operation.',wraplength=650).grid(row=len(OPTIONS)+1,column=0,columnspan=4,sticky='w',pady=10)
        self.refresh_button=ttk.Button(shell,text='Refresh settings',command=self.refresh);self.refresh_button.grid(row=len(OPTIONS)+2,column=0,sticky='w')
        self.export_config=ttk.Button(shell,text='Export MIDI configuration…',command=self.save_configuration,state='disabled');self.export_config.grid(row=len(OPTIONS)+3,column=0,columnspan=2,sticky='w',pady=8)
        self.import_config=ttk.Button(shell,text='Import MIDI configuration…',command=self.load_configuration,state='disabled');self.import_config.grid(row=len(OPTIONS)+3,column=2,columnspan=2,sticky='w',pady=8)
        self.message=ttk.Label(shell,text='',wraplength=650);self.message.grid(row=len(OPTIONS)+4,column=0,columnspan=4,sticky='w',pady=10)
        self.refresh()
    def ready(self):
        return not self.closed and self.app.connected and self.serial==self.app.name_cache.serial and self.request is None
    def update_controls(self):
        ready=self.ready()
        for field in OPTIONS:
            r=self.records.get(field,{})
            enabled=ready and r.get('stable') is True and type(r.get('raw')) is int and 0<=r['raw']<len(OPTIONS[field])
            self.selectors[field].config(state='readonly' if enabled else 'disabled')
            self.buttons[field].config(state='normal' if enabled else 'disabled')
        self.refresh_button.config(state='normal' if ready else 'disabled')
        if hasattr(self,'export_config'):
            enabled=ready and self.configuration_ready()
            self.export_config.config(state='normal' if enabled else 'disabled');self.import_config.config(state='normal' if enabled else 'disabled')
    def refresh(self):
        if not self.ready():return
        self.records={};self.request=uuid.uuid4().hex;self.update_controls()
        self.message.config(text='Reading device settings…')
        self.app.worker.commands.put(('midi_ports_read',dict(request_id=self.request,connection_serial=self.serial)))
    def apply(self,field):
        if not self.ready() or field not in OPTIONS:return
        r=self.records.get(field,{})
        if r.get('stable') is not True or type(r.get('raw')) is not int or not 0<=r['raw']<len(OPTIONS[field]):return
        target=self.selectors[field].current()
        if target not in range(len(OPTIONS[field])):return
        if target==r['raw']:
            self.message.config(text='Setting unchanged.');return
        self.request=uuid.uuid4().hex;self.update_controls()
        self.message.config(text='Applying · waiting for device confirmation…')
        self.app.worker.commands.put(('midi_ports_set',dict(request_id=self.request,connection_serial=self.serial,field=field,target=target,expected=r['raw'])))
    def handle(self,event):
        if self.closed or self.request is None or event['kind'] not in ('midi_ports_snapshot','midi_ports_written','midi_error') or event.get('request_id')!=self.request:return False
        self.request=None
        if event.get('connection_serial')!=self.serial or self.serial!=self.app.name_cache.serial:
            self.records={};self.message.config(text='Connection changed; reopen MIDI ports.');self.update_controls();return True
        if event['kind']=='midi_error':
            self.records={};self.message.config(text=event['message']+' · Refresh before another edit.')
        else:
            self.records=event['records']
            for field,r in self.records.items():
                raw=r['raw'];known=type(raw) is int and 0<=raw<len(OPTIONS[field])
                label=OPTIONS[field][raw] if known else f'Unknown ({raw})'
                self.values[field].config(text=label if r['stable'] else 'Refresh required')
                self.selectors[field].set(label)
            self.message.config(text='Setting confirmed by device readback.' if event['kind']=='midi_ports_written' else 'Device settings read.')
        self.update_controls();return True
    def configuration_ready(self):
        if not self.ready():return False
        from midi_configuration import make_configuration
        try:make_configuration(self.parent.records,self.records,self.app.demo)
        except (ValueError,KeyError):return False
        return True
    def save_configuration(self):
        if not self.configuration_ready():return
        from midi_configuration import make_configuration
        content=json.dumps(make_configuration(self.parent.records,self.records,self.app.demo),indent=2)+'\n'
        path=filedialog.asksaveasfilename(parent=self.window,title='Export MIDI configuration',initialfile='AF16Rig-midi-configuration.json',defaultextension='.json',filetypes=[('MIDI configuration','*.json')])
        if not path:return
        try:Path(path).write_text(content,encoding='utf-8')
        except OSError as error:
            if not self.closed:self.message.config(text=str(error))
            return
        if not self.closed:self.message.config(text='MIDI configuration exported: assignments, bank size, mode, ports, clock output and routing. Audio settings are excluded.')
    def load_configuration(self):
        if not self.configuration_ready():return
        serial=self.serial
        path=filedialog.askopenfilename(parent=self.window,title='Import MIDI configuration',filetypes=[('MIDI configuration','*.json')])
        if not path or not self.configuration_ready() or serial!=self.serial:return
        from midi_configuration import load,plan
        try:changes=plan(load(path),self.parent.records,self.records,self.app.demo)
        except (OSError,ValueError) as error:self.message.config(text=str(error));return
        if not changes:self.message.config(text='All supported MIDI settings already match.');return
        parent=self.parent
        self.close(refresh=False)
        from midi_configuration_restore import MidiConfigurationRestore
        parent.restore_dialog=MidiConfigurationRestore(parent,changes)
        parent.refresh_button.config(state='disabled');parent.save_button.config(state='disabled');parent.update_editor()
    def close(self,refresh=True):
        if self.closed:return
        self.closed=True;self.request=None;self.parent.restore_dialog=None;self.window.destroy()
        if refresh and not self.parent.closed:self.parent.update_editor()
