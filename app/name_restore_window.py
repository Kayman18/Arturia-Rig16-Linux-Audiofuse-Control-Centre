"""Preview and restore a batch through the existing one-name checked writer."""
import time
import tkinter as tk
from tkinter import ttk
from channel_names import source_label

class NameRestoreWindow:
    def __init__(self,parent,changes):
        self.parent=parent;self.app=parent.app;self.changes=changes;self.serial=self.app.name_cache.serial
        self.position=0;self.request_id=None;self.busy=False;self.stop_requested=False;self.closed=False;self.timer=None
        self.window=tk.Toplevel(parent.window);self.window.title('Restore equipment names');self.window.transient(parent.app.root)
        self.window.geometry('850x500');self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=ttk.Frame(self.window,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=f'{len(changes)} name changes',font=('DejaVu Sans',15,'bold')).pack(anchor='w')
        ttk.Label(shell,text='Only names are restored. Each current name is checked again before writing.\nA failure stops the batch; earlier confirmed changes remain.',wraplength=800).pack(anchor='w',pady=8)
        frame=ttk.Frame(shell);frame.pack(fill='both',expand=True)
        self.table=ttk.Treeview(frame,columns=('channel','old','new','status'),show='headings')
        for key,title,width in [('channel','Channel / slot',200),('old','Current',200),('new','Saved',200),('status','Result',130)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scroll.set);self.table.pack(side='left',fill='both',expand=True)
        for i,c in enumerate(changes):self.table.insert('','end',iid=str(i),values=(source_label(c['source']),c['expected'] or '(blank)',c['name'] or '(blank)','Pending'))
        row=ttk.Frame(shell);row.pack(fill='x',pady=10)
        self.apply=ttk.Button(row,text='Restore these names',command=self.start);self.apply.pack(side='left')
        self.stop=ttk.Button(row,text='Stop after current name',command=self.request_stop,state='disabled');self.stop.pack(side='left',padx=10)
        ttk.Button(row,text='Close',command=self.close).pack(side='right')
        self.message=ttk.Label(shell,text='Review the complete list, then restore.',wraplength=800);self.message.pack(anchor='w')
        parent.editing=True;parent.apply_button.config(state='disabled');parent.read_button.config(state='disabled')
    def start(self):
        if self.closed or self.busy or self.position or self.stop_requested:return
        self.busy=True;self.apply.config(state='disabled');self.stop.config(state='normal');self.queue_next()
    def queue_next(self):
        self.timer=None
        if self.closed:return
        if self.stop_requested:self.finish('Stopped.');return
        if not self.app.connected or self.serial!=self.app.name_cache.serial:self.finish('Connection changed; no further names sent.');return
        if self.position>=len(self.changes):self.finish('Restore complete.');return
        self.request_id=time.monotonic_ns();c=self.changes[self.position]
        self.message.config(text=f'Restoring {self.position+1}/{len(self.changes)} · {source_label(c["source"])}…')
        self.app.worker.commands.put(('name_set',dict(request_id=self.request_id,connection_serial=self.serial,**c)))
    def handle(self,event):
        if self.closed:return False
        if event['kind']=='input_error' and event.get('channel')=='names':
            self.finish('Disconnected; the current write may be uncertain. Refresh names before continuing.');return True
        if not self.busy or self.request_id is None or event.get('request_id')!=self.request_id or event['kind'] not in ('name_written','name_write_error'):return False
        self.request_id=None
        if event.get('connection_serial',self.serial)!=self.serial or self.app.name_cache.serial!=self.serial:
            self.finish('Connection changed; current result discarded. Refresh names.');return True
        if event['kind']=='name_write_error':
            self.table.set(str(self.position),'status','Not confirmed')
            self.finish('Stopped: '+event['message']);return True
        self.table.set(str(self.position),'status','Confirmed');self.position+=1
        if self.stop_requested:self.finish('Stopped.');return True
        if self.position==len(self.changes):self.finish('Restore complete.');return True
        # Yield between names so the normal worker polls can run.
        self.timer=self.window.after(120,self.queue_next)
        return True
    def request_stop(self):
        self.stop_requested=True
        if self.request_id is None:self.finish('Stopped.')
        else:self.message.config(text='Stopping after the current name is checked…')
    def finish(self,message):
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
        self.busy=False;self.stop_requested=True;self.request_id=None
        self.apply.config(state='disabled');self.stop.config(state='disabled')
        text=f'{message} {self.position}/{len(self.changes)} names confirmed.'
        self.message.config(text=text);self.parent.edit_feedback=text
        self.parent.editing=False;self.parent.refresh_names();self.parent.editing=True
        self.parent.read_button.config(state='disabled');self.parent.message.config(text=text)
    def close(self):
        if self.closed:return
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
        self.closed=True
        if self.busy:self.parent.edit_feedback=f'Restore stopped: {self.position} names confirmed. An already-sent name may still finish; refresh names.'
        self.parent.editing=False;self.parent.restore_dialog=None;self.parent.read_button.config(state='normal');self.parent.refresh_names()
        if self.parent.edit_feedback:self.parent.message.config(text=self.parent.edit_feedback)
        self.window.destroy()
