"""Incremental capture, preview and sequential recall of Main/Cue faders."""
import json
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from fader_scene import addresses,make_scene,load_scene,plan

class FaderSceneWindow:
    def __init__(self,app):
        self.app=app;self.channel=tk.StringVar(value='fader_scenes');self.closed=False
        self.busy=False;self.request=None;self.timer=None;self.serial=None;self.scene=None
        self.target=None;self.changes=[];self.preview_current=None;self.mode='capture';self.stopped=False
        self.window=app.make_panel();self.window.title('AF16Rig — Main/Cue fader scenes')
        shell=ttk.Frame(self.window,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='MAIN / CUE FADER SCENES',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        ttk.Label(shell,text='Save active channel faders and Main/Cue master levels to a file. Recall requires matching source/stereo selection and L/R offsets.\nRouting, gain, pan, mute/solo, aux sends, Phones and Monitor settings are not included.',wraplength=1000).pack(anchor='w',pady=8)
        row=ttk.Frame(shell);row.pack(fill='x',pady=8)
        self.read_button=ttk.Button(row,text='Read current faders',command=self.refresh);self.read_button.pack(side='left')
        self.save_button=ttk.Button(row,text='Save fader scene…',command=self.save);self.save_button.pack(side='left',padx=8)
        self.load_button=ttk.Button(row,text='Open scene / preview…',command=self.open_scene);self.load_button.pack(side='left')
        self.apply_button=ttk.Button(row,text='Recall listed levels',command=self.start_apply);self.apply_button.pack(side='left',padx=8)
        self.stop_button=ttk.Button(row,text='Stop after current step',command=self.stop);self.stop_button.pack(side='left')
        box=ttk.Frame(shell);box.pack(fill='both',expand=True)
        self.table=ttk.Treeview(box,columns=('fader','current','saved','result'),show='headings',height=18)
        for key,title,width in [('fader','Fader',320),('current','Current dB',180),('saved','Scene dB',180),('result','Result',210)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scroll.set);self.table.pack(fill='both',expand=True)
        self.message=ttk.Label(shell,text='',wraplength=1000);self.message.pack(anchor='w',pady=8)
        ttk.Label(shell,text='Recall changes audible levels. A failure stops the batch; earlier confirmed changes remain. Stop/Close cannot withdraw an already-sent step.',wraplength=1000).pack(anchor='w')
        app.worker.commands.put(('input_select',None));self.refresh()
    def ready(self):return not self.closed and self.app.connected and self.serial==self.app.name_cache.serial
    def update_buttons(self):
        idle=self.ready() and not self.busy
        self.read_button.config(state='normal' if self.app.connected and not self.busy else 'disabled')
        self.load_button.config(state='normal' if idle else 'disabled')
        self.save_button.config(state='normal' if idle and self.scene else 'disabled')
        self.apply_button.config(state='normal' if idle and self.changes and self.preview_current else 'disabled')
        self.stop_button.config(state='normal' if self.busy and not self.stopped else 'disabled')
    def queue(self,command,**data):
        self.request=uuid.uuid4().hex
        self.app.worker.commands.put((command,dict(data,request_id=self.request,connection_serial=self.serial)))
    def refresh(self,target=None,mode='capture'):
        if self.closed or self.busy or not self.app.connected:return
        self.serial=self.app.name_cache.serial;self.scene=None;self.target=target;self.mode=mode
        if mode!='preflight':self.changes=[];self.preview_current=None
        self.entries=[];self.layout=None;self.position=0;self.stopped=False;self.busy=True
        self.message.config(text='Reading mixer layout…');self.update_buttons()
        self.queue('scene_read',part='layout')
    def next_read(self):
        if self.stopped:self.fail('Stopped; capture discarded.');return
        if self.position==len(self.addresses):self.queue('scene_read',part='layout_end');return
        self.message.config(text=f'{"Rechecking before recall" if self.mode=="preflight" else "Reading faders"} · {self.position+1}/{len(self.addresses)}')
        self.queue('scene_read',part='entry',layout=self.layout,address=self.addresses[self.position])
    @staticmethod
    def key(e):return f"{e['bus']}:{e['source']}"
    @staticmethod
    def label(e):
        source=e['source']
        if not source:return e['bus'].upper()+' MASTER'
        prefix='ANALOG' if source<=16 else 'ADAT' if source<=32 else 'USB'
        number=source if source<=16 else source-16 if source<=32 else source-32
        return f"{e['bus'].upper()} · {prefix} {number}"+(f'/{number+1}' if e['stereo'] else '')
    @staticmethod
    def db(e):return ' / '.join(f'{v/256:.2f}' for v in e['levels'])
    def render(self,current,target=None):
        for row in self.table.get_children():self.table.delete(row)
        saved={self.key(e):e for e in target['entries']} if target else {}
        for e in current['entries']:
            other=saved.get(self.key(e));changed=other is not None and other['levels']!=e['levels']
            self.table.insert('','end',iid=self.key(e),values=(self.label(e),self.db(e),self.db(other) if other else '—','Change' if changed else 'Matching' if other else 'Read'))
    def finish_capture(self):
        current=make_scene(self.layout,self.entries,self.app.demo)
        if self.mode=='preflight':
            if plan(self.preview_current,current):raise ValueError('Faders changed after preview; open the scene again. No recall started.')
            self.scene=current;self.position=0;self.mode='apply';self.queue_next();return
        self.scene=current;self.busy=False
        if self.target:
            self.changes=plan(self.target,current);self.preview_current=current
            self.render(current,self.target)
            self.message.config(text=f'{len(self.changes)} faders will change. Review, then Recall listed levels.' if self.changes else 'All scene faders already match; nothing to recall.')
        else:
            self.render(current);self.message.config(text=f'Read {len(current["entries"])} faders. Save scene, or open a scene to preview changes.')
        self.update_buttons()
    def open_scene(self):
        if self.busy or not self.ready():return
        serial=self.serial
        path=filedialog.askopenfilename(parent=self.window,title='Open Main/Cue fader scene',filetypes=[('Fader scene','*.json')])
        if not path or not self.ready() or self.serial!=serial:return
        try:target=load_scene(path)
        except (ValueError,OSError) as error:self.message.config(text=str(error));return
        self.refresh(target)
    def save(self):
        if self.busy or not self.ready() or self.scene is None:return
        content=json.dumps(self.scene,indent=2,allow_nan=False)+'\n'
        path=filedialog.asksaveasfilename(parent=self.window,title='Save Main/Cue fader scene',initialfile='AF16Rig-fader-scene.json',defaultextension='.json',filetypes=[('Fader scene','*.json')])
        if not path:return
        try:Path(path).write_text(content,encoding='utf-8')
        except OSError as error:
            if not self.closed:self.message.config(text=str(error))
            return
        if not self.closed:self.message.config(text='Fader scene saved. This file contains levels only, not a complete device preset.')
    def start_apply(self):
        if self.busy or not self.ready() or not self.changes or not self.preview_current:return
        self.refresh(self.target,mode='preflight')
    def queue_next(self):
        self.timer=None
        if self.closed:return
        if self.stopped or not self.ready():self.fail(f'Stopped after {self.position}/{len(self.changes)} confirmed faders.');return
        if self.position==len(self.changes):
            self.busy=False;self.scene=None;self.preview_current=None
            self.message.config(text=f'Recall complete: {self.position} faders confirmed. Read current faders to save a new scene.');self.update_buttons();return
        c=self.changes[self.position];self.message.config(text=f'Recalling {self.position+1}/{len(self.changes)} · {self.label(c)}')
        self.queue('scene_set',layout=self.layout,change=c)
    def stop(self):
        self.stopped=True;self.update_buttons()
        if self.request is None:
            if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
            self.fail('Stopped. Confirmed changes remain; read current faders before continuing.')
        else:self.message.config(text='Stopping after the current step finishes…')
    def fail(self,message):
        self.busy=False;self.request=None;self.scene=None;self.preview_current=None
        self.message.config(text=message);self.update_buttons()
    def connection_changed(self):
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
        self.stopped=True;self.fail('Connection or preset changed. Read current faders again.')
    def handle(self,event):
        if self.closed:return
        if event['kind']=='input_error' and event.get('channel')=='fader_scenes':self.connection_changed();return
        if event['kind'] not in ('scene_snapshot','scene_written','scene_error') or event.get('request_id')!=self.request:return
        self.request=None
        if not self.ready() or event.get('connection_serial')!=self.serial:self.connection_changed();return
        if event['kind']=='scene_error':
            suffix=f' {self.position}/{len(self.changes)} earlier faders confirmed; no rollback.' if self.mode=='apply' else ''
            self.fail(event['message']+suffix);return
        if event['kind']=='scene_written':
            c=self.changes[self.position];record=event['record']
            if record!={k:c[k] for k in ('bus','source','stereo','levels')}:
                self.fail('Unexpected recall confirmation; stopped. Read current faders.');return
            self.table.set(self.key(c),'result','Confirmed');self.table.set(self.key(c),'current',self.db(record))
            self.position+=1
            self.timer=self.window.after(80,self.queue_next);return
        if self.stopped:self.fail('Stopped; capture discarded.');return
        try:
            if event['part']=='layout':
                self.layout=event['layout'];self.addresses=addresses(self.layout);self.next_read()
            elif event['part']=='entry':
                record=event['record'];address=self.addresses[self.position]
                if any(record[k]!=address[k] for k in address):raise ValueError('Unexpected scene entry; read again')
                self.entries.append(record);self.position+=1;self.next_read()
            else:
                if event['layout']!=self.layout:raise ValueError('Mixer source layout changed during capture; read again')
                self.finish_capture()
        except (ValueError,KeyError,IndexError) as error:self.fail(str(error))
    def close(self):
        self.closed=True;self.stopped=True;self.request=None
        if self.timer is not None:self.window.after_cancel(self.timer)
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()
