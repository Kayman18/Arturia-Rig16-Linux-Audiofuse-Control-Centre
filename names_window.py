"""Live channel names with explicit guarded rename and report capture."""
import json
import time
import tkinter as tk
from tkinter import ttk,filedialog
from pathlib import Path
from channel_names import report,source_label,NAME_SOURCE_COUNT,NAME_SOURCES

class NamesWindow:
    def __init__(self,app):
        self.app=app;self.channel=tk.StringVar(value='names');self.records=[];self.pending=False;self.request_id=None;self.editing=False;self.edit_source=None;self.edit_expected=None;self.edit_serial=None;self.edit_feedback=None;self.restore_dialog=None
        self.window=app.make_panel();self.window.title('AF16Rig — Channel names')
        shell=ttk.Frame(self.window,padding=20);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='CHANNEL NAMES FROM THE 16RIG',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        ttk.Label(shell,text='Loaded automatically from the device · Analog/ADAT inputs and outputs · Select a row to rename').pack(anchor='w',pady=12)
        table_frame=ttk.Frame(shell);table_frame.pack(fill='both',expand=True)
        self.table=ttk.Treeview(table_frame,columns=('input','name','status','format'),show='headings')
        for key,title,width in [('input','Channel / output slot',200),('name','Equipment name',300),('status','Read status',190),('format','Text format',190)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        scroll=ttk.Scrollbar(table_frame,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left',fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',self.select_name)
        editor=ttk.Frame(shell);editor.pack(fill='x',pady=(12,0))
        self.edit_label=ttk.Label(editor,text='Select a channel');self.edit_label.pack(side='left')
        self.name_value=tk.StringVar()
        self.name_entry=ttk.Entry(editor,textvariable=self.name_value,width=30,state='disabled');self.name_entry.pack(side='left',padx=12)
        self.apply_button=ttk.Button(editor,text='Save name to rig',command=self.apply_name,state='disabled');self.apply_button.pack(side='left')
        ttk.Label(shell,text='Maximum 15 UTF-8 bytes. Analog output slots use the native name order; speaker/line/headphone mapping is not yet verified.').pack(anchor='w',pady=(4,0))
        row=ttk.Frame(shell);row.pack(fill='x',pady=12)
        self.read_button=ttk.Button(row,text='Refresh names',command=self.start);self.read_button.pack(side='left')
        self.save_button=ttk.Button(row,text='Save name report',command=self.save,state='disabled');self.save_button.pack(side='left',padx=12)
        ttk.Button(row,text='Save names backup…',command=self.backup).pack(side='left',padx=6)
        ttk.Button(row,text='Restore names…',command=self.restore).pack(side='left',padx=6)
        self.message=ttk.Label(shell,text='',wraplength=900);self.message.pack(anchor='w')
        app.worker.commands.put(('input_select',None))
        self.refresh_names()
    def backup(self):
        if self.pending or self.editing:return
        from name_backup import make_backup
        try:data=make_backup(self.records,self.app.demo)
        except Exception as error:
            self.message.config(text=str(error));return
        path=filedialog.asksaveasfilename(title='Save equipment names backup',initialfile='AF16Rig-names-backup.json',defaultextension='.json',filetypes=[('JSON backup','*.json')])
        if path:
            try:Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
            except OSError as error:self.message.config(text=str(error));return
            self.edit_feedback=f'Backed up {len(data["names"])} names.';self.message.config(text=self.edit_feedback)
    def connection_changed(self):
        dialog=getattr(self,'restore_dialog',None)
        if dialog:dialog.close()
        self.pending=False;self.editing=False;self.request_id=None
        self.edit_source=None;self.edit_expected=None;self.edit_serial=None;self.edit_feedback=None
        self.records=[]
        for row in self.table.get_children():self.table.delete(row)
        self.name_value.set('');self.edit_label.config(text='Select a freshly read channel')
        self.name_entry.config(state='disabled');self.apply_button.config(state='disabled');self.save_button.config(state='disabled')
        self.read_button.config(state='normal' if self.app.connected else 'disabled')
        self.message.config(text='Reading names from the new connection…' if self.app.connected else 'Disconnected · names cleared')
    def restore(self):
        if self.pending or self.editing or not self.app.connected:return
        if getattr(self,'restore_dialog',None):self.restore_dialog.window.lift();return
        path=filedialog.askopenfilename(title='Load equipment names backup',filetypes=[('JSON backup','*.json')])
        if not path:return
        from name_backup import load_backup,restore_plan
        try:changes=restore_plan(load_backup(path),self.app.name_cache.records,self.app.demo)
        except Exception as error:self.message.config(text=str(error));return
        if not changes:self.message.config(text='All saved names already match; nothing to restore.');return
        from name_restore_window import NameRestoreWindow
        self.restore_dialog=NameRestoreWindow(self,changes)

    def select_name(self,event=None):
        if self.pending or self.editing:return
        selected=self.table.selection()
        if not selected:return
        source=int(selected[0]);record=self.app.name_cache.records.get(source,{})
        from name_edit import confirmed_text
        try:expected=confirmed_text(record,self.app.demo)
        except Exception as error:
            self.message.config(text=str(error));self.apply_button.config(state='disabled');return
        self.edit_feedback=None
        self.edit_source=source;self.edit_expected=expected;self.edit_serial=self.app.name_cache.serial
        self.name_value.set(expected);self.edit_label.config(text=source_label(source))
        ready=self.app.connected and self.app.info.get('state_version')==18
        self.name_entry.config(state='normal' if ready else 'disabled');self.apply_button.config(state='normal' if ready else 'disabled')

    def apply_name(self):
        if self.pending or self.editing or self.edit_source is None or not self.app.connected:return
        from name_edit import encode_name
        name=self.name_value.get()
        try:encode_name(name)
        except ValueError as error:self.message.config(text=str(error));return
        if self.edit_serial!=self.app.name_cache.serial:
            self.message.config(text='Connection changed. Select the channel again before saving.');return
        self.edit_feedback=None
        self.editing=True;self.request_id=time.monotonic_ns()
        self.apply_button.config(state='disabled');self.name_entry.config(state='disabled');self.read_button.config(state='disabled')
        self.message.config(text='Saving name and checking device readback…')
        self.app.worker.commands.put(('name_set',dict(request_id=self.request_id,connection_serial=self.edit_serial,
            source=self.edit_source,expected=self.edit_expected,name=name)))

    def refresh_names(self):
        if self.pending or self.editing:return
        cache=getattr(self.app,'name_cache',None)
        if cache is None:return
        self.records=[cache.records[i] for i in sorted(cache.records)]
        keep={str(record['source']) for record in self.records}
        for row in self.table.get_children():
            if row not in keep:self.table.delete(row)
        for record in self.records:
            row=str(record['source'])
            values=(source_label(record['source']),record.get('candidate') or '—',record['status'],record.get('encoding','—'))
            if self.table.exists(row):
                if tuple(map(str,self.table.item(row,'values')))!=tuple(map(str,values)):self.table.item(row,values=values)
            else:self.table.insert('','end',iid=row,values=values)
        self.save_button.config(state='normal' if self.records else 'disabled')
        if not self.edit_feedback:self.message.config(text=f'{len(self.records)}/{NAME_SOURCE_COUNT} names read automatically.'+(' Refresh names rereads them from the device.' if len(self.records)==NAME_SOURCE_COUNT else ''))
    def start(self):
        if self.pending or self.editing:return
        if not self.app.connected:
            self.message.config(text='Connect the device, then click Read names.');return
        self.edit_feedback=None
        self.records=[]
        for row in self.table.get_children():self.table.delete(row)
        self.pending=True;self.read_button.config(state='disabled');self.save_button.config(state='disabled')
        self.request_id=time.monotonic_ns();self.next_read()
    def next_read(self):
        source=NAME_SOURCES[len(self.records)]
        self.message.config(text=f'Reading {source_label(source)} ({len(self.records)+1} of {NAME_SOURCE_COUNT})…')
        self.app.worker.commands.put(('name_read',(self.request_id,source)))
    def finish(self,message):
        self.pending=False;self.read_button.config(state='normal')
        self.save_button.config(state='normal' if self.records else 'disabled');self.message.config(text=message)
    def handle(self,event):
        if event['kind']=='input_error' and event.get('channel')=='names':
            self.connection_changed();return
        dialog=getattr(self,'restore_dialog',None)
        if dialog and dialog.handle(event):return
        if event['kind'] in ('name_written','name_write_error'):
            if event.get('request_id')!=self.request_id or not self.editing:return
            self.editing=False;self.read_button.config(state='normal');self.name_entry.config(state='normal');self.apply_button.config(state='normal')
            self.refresh_names()
            if event['kind']=='name_written':
                self.edit_expected=event['state']['candidate']
                self.edit_feedback='Demo name updated; no hardware written.' if self.app.demo else 'Name saved and confirmed by hardware readback.'
            else:self.edit_feedback=event['message']
            self.message.config(text=self.edit_feedback)
            return
        if event['kind'] not in ('name_snapshot','name_error') or event.get('request_id')!=self.request_id or not self.pending:return
        if event['kind']=='name_error':self.finish(event['message']);return
        record=event['state'];self.records.append(record)
        self.table.insert('','end',iid=str(record['source']),values=(source_label(record['source']),record.get('candidate') or '—',record['status'],record.get('encoding','—')))
        if record['status']=='read_error':
            self.finish('Stopped on a read error: '+record.get('error','')+'. Save the report for diagnosis.');return
        if len(self.records)<NAME_SOURCE_COUNT:self.next_read();return
        candidates=sum(r.get('status')=='candidate' for r in self.records)
        self.finish('Demo values only; no device was read.' if self.app.demo else f'Read complete: {candidates} non-empty names. Mixer labels refreshed from device readback.')
    def save(self):
        if self.pending or not self.records:return
        path=filedialog.asksaveasfilename(title='Save channel name report',initialfile='AF16Rig-channel-names.json',defaultextension='.json',filetypes=[('JSON report','*.json')])
        if path:
            try:Path(path).write_text(json.dumps(report(self.records,self.app.demo),indent=2,ensure_ascii=False)+'\n')
            except OSError as error:self.message.config(text=str(error));return
            self.message.config(text='Name report saved.')
    def close(self):
        dialog=getattr(self,'restore_dialog',None)
        if dialog:dialog.close()
        self.pending=False;self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()
