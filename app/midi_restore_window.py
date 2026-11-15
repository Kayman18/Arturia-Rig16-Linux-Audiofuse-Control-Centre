"""Reviewable, single-flight batch using the existing guarded remap command."""
import uuid
import tkinter as tk
from tkinter import ttk

class MidiRestoreWindow:
    def __init__(self,parent,changes,notice='',configuration=False):
        self.configuration=configuration
        self.parent=parent;self.app=parent.app;self.changes=changes;self.serial=parent.serial
        self.position=0;self.request=None;self.busy=False;self.stopped=False;self.closed=False;self.timer=None
        self.window=tk.Toplevel(parent.window);self.window.title('Review MIDI configuration' if configuration else 'Review MIDI assignments')
        self.window.transient(parent.app.root);self.window.geometry('880x510');self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=ttk.Frame(self.window,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=f'{len(changes)} MIDI configuration changes' if configuration else f'{len(changes)} MIDI assignment changes',font=('DejaVu Sans',16,'bold')).pack(anchor='w')
        ttk.Label(shell,text=('Review MIDI assignments, bank size, ports, sync and routing. Audio settings are excluded.\nChanges apply one at a time. Failure stops the batch; earlier changes remain.\nStop or Close cancels unsent changes.' if configuration else 'Review channel, type and number changes below. Bank settings and MIDI routing are excluded.\nA failed confirmation stops the batch; earlier confirmed changes remain.\nStop or Close cancels remaining entries; an already-sent assignment may still finish.'),wraplength=830).pack(anchor='w',pady=8)
        box=ttk.Frame(shell);box.pack(fill='both',expand=True)
        self.table=ttk.Treeview(box,columns=('control','before','after','status'),show='headings')
        for key,title,width in [('control','Control',240),('before','Current',160),('after','Proposed',160),('status','Result',150)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        scrollbar=ttk.Scrollbar(box,orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        for i,c in enumerate(changes):self.table.insert('','end',iid=str(i),values=(c['label'],c['before'],c['after'],'Pending'))
        row=ttk.Frame(shell);row.pack(fill='x',pady=10)
        self.apply=ttk.Button(row,text='Apply listed changes' if configuration else 'Apply listed assignments',command=self.start);self.apply.pack(side='left')
        self.stop=ttk.Button(row,text='Stop after current change' if configuration else 'Stop after current assignment',command=self.request_stop,state='disabled');self.stop.pack(side='left',padx=8)
        ttk.Button(row,text='Close',command=self.close).pack(side='right')
        self.message=ttk.Label(shell,text=notice or 'Review the changes, then apply.',wraplength=830);self.message.pack(anchor='w')
    def start(self):
        if self.closed or self.busy or self.position or self.stopped:return
        self.busy=True;self.apply.config(state='disabled');self.stop.config(state='normal');self.queue_next()
    def queue_next(self):
        self.timer=None
        if self.closed or not self.busy or self.request is not None:return
        if self.stopped:self.finish('Stopped.');return
        if not self.app.connected or self.serial!=self.app.name_cache.serial:
            self.finish('Connection changed; no further assignments sent.');return
        if self.position>=len(self.changes):self.finish('Batch complete.');return
        c=self.changes[self.position];self.request=uuid.uuid4().hex
        data={k:c[k] for k in ('parameter','index','expected','channel','number')}
        if 'message_type' in c:data['message_type']=c['message_type']
        data.update(request_id=self.request,connection_serial=self.serial)
        self.message.config(text=f'Applying {self.position+1}/{len(self.changes)} · {c["label"]}…')
        self.app.worker.commands.put(('midi_remap',data))
    def handle(self,event):
        if self.closed or not self.busy or self.request is None:return False
        if event['kind'] not in ('midi_written','midi_error') or event.get('request_id')!=self.request:return False
        self.request=None
        if event.get('connection_serial')!=self.serial or self.app.name_cache.serial!=self.serial:
            self.finish('Connection changed; current result discarded.');return True
        c=self.changes[self.position]
        if event['kind']=='midi_error':
            self.table.set(str(self.position),'status','Not confirmed')
            for n,r in enumerate(self.parent.records):
                if (r['parameter'],r['index'])==(c['parameter'],c['index']):
                    self.parent.records[n]=dict(r,stable=False)
                    self.parent.table.item(str(n),values=self.parent.row_values(self.parent.records[n]))
            self.finish('Stopped: '+event['message']);return True
        r=event['record'];target=(c.get('message_type',c['expected']>>14)<<14)|((c['channel']-1)<<8)|c['number']
        if (r.get('parameter'),r.get('index'),r.get('raw'),r.get('stable'))!=(c['parameter'],c['index'],target,True):
            self.finish('Stopped: unexpected confirmation; refresh before continuing.');return True
        for n,old in enumerate(self.parent.records):
            if (old['parameter'],old['index'])==(c['parameter'],c['index']):
                self.parent.records[n]=r;self.parent.table.item(str(n),values=self.parent.row_values(r));break
        self.table.set(str(self.position),'status','Confirmed');self.position+=1
        if self.stopped:self.finish('Stopped.');return True
        if self.position>=len(self.changes):self.finish('Batch complete.');return True
        self.timer=self.window.after(120,self.queue_next)
        return True
    def request_stop(self):
        self.stopped=True
        if self.request is None:self.finish('Stopped.')
        else:self.message.config(text='Stopping after the current assignment is checked…')
    def finish(self,message):
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
        self.busy=False;self.stopped=True;self.request=None
        self.apply.config(state='disabled');self.stop.config(state='disabled')
        text=f'{message} {self.position}/{len(self.changes)} assignments confirmed.'
        if getattr(self,'configuration',False):text=text.replace('assignments','changes')
        self.message.config(text=text);self.parent.message.config(text=text)
    def close(self,refresh=True):
        if self.closed:return
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
        self.closed=True;self.stopped=True;self.request=None
        self.parent.restore_dialog=None;self.window.destroy()
        if refresh and not self.parent.closed:self.parent.refresh()
