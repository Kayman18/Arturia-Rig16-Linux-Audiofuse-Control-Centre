"""Incremental capture, preview and sequential recall of Main/Cue mixer settings."""
import json
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from mixer_scene import addresses,make_scene,load_scene,plan
from channel_names import source_label
import scene_sources
import scene_layout
import scene_rate
from clock_scene import describe as describe_clock
from speaker_ab_scene import describe as describe_ab
from routing_labels import SOURCE_LABELS,DESTINATION_LABELS

class MixerSceneWindow:
    def __init__(self,app):
        self.app=app;self.channel=tk.StringVar(value='mixer_scenes');self.closed=False
        self.busy=False;self.request=None;self.timer=None;self.serial=None;self.scene=None
        self.target=None;self.changes=[];self.preview_current=None;self.mode='capture';self.stopped=False
        self.window=app.make_panel();self.window.title('AF16Rig — Main/Cue mixer scenes')
        shell=ttk.Frame(self.window,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='MAIN / CUE MIXER SCENES',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        ttk.Label(shell,text='Save Main/Cue levels, pan, mute/solo, Main Aux sends and Main/Cue and Aux master controls, Cue enable, Aux stereo links, 60 audio output routes, all 60 input/output names, Monitor controls, Phones level, speaker B trim, analog output levels/stereo links and active-input gain/PAD, polarity, supported high-pass filters and front Line/Instrument mode and speaker A/B configuration.\nUse Match mixer layout to restore channel inclusion and mono/stereo selection before recall. Older scene files still require matching output links. Use Match input sources to select compatible front/rear pairs, then review a fresh preview. New scenes restore rear and compatible front Line/Mic hardware links. Clock source, word-clock termination/thru and SMUX mode are included; Internal sample rate is captured and matched separately with idle audio streams.',wraplength=1000).pack(anchor='w',pady=8)
        row=ttk.Frame(shell);row.pack(fill='x',pady=8)
        self.read_button=ttk.Button(row,text='Read mixer settings',command=self.refresh);self.read_button.pack(side='left')
        self.save_button=ttk.Button(row,text='Save mixer scene…',command=self.save);self.save_button.pack(side='left',padx=8)
        self.load_button=ttk.Button(row,text='Open scene / preview…',command=self.open_scene);self.load_button.pack(side='left')
        self.source_button=ttk.Button(row,text='Match input sources',command=self.match_sources);self.source_button.pack(side='left',padx=8)
        self.apply_button=ttk.Button(row,text='Recall listed settings',command=self.start_apply);self.apply_button.pack(side='left',padx=8)
        self.stop_button=ttk.Button(row,text='Stop after current step',command=self.stop);self.stop_button.pack(side='left')
        layout_row=ttk.Frame(shell);layout_row.pack(fill='x')
        self.layout_button=ttk.Button(layout_row,text='Match mixer layout',command=self.match_layout);self.layout_button.pack(side='left')
        self.rate_button=ttk.Button(layout_row,text='Match sample rate',command=self.match_rate);self.rate_button.pack(side='left',padx=8)
        box=ttk.Frame(shell);box.pack(fill='both',expand=True)
        self.table=ttk.Treeview(box,columns=('control','current','saved','result'),show='headings',height=18)
        for key,title,width in [('control','Control',320),('current','Current',180),('saved','Saved',180),('result','Result',210)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scroll.set);self.table.pack(fill='both',expand=True)
        self.message=ttk.Label(shell,text='',wraplength=1000);self.message.pack(anchor='w',pady=8)
        ttk.Label(shell,text='Source matching changes the active audio inputs without recalling gains; review again afterwards. Recall changes audible levels, speaker routing and clock configuration. Clock changes may interrupt audio; external clock must be connected. A/B recall may temporarily enable A/B or select Speaker A to restore the saved configuration. Input link changes run before or after input settings as needed. Output-pair recall may temporarily unlink a pair to restore its levels before relinking. A failure stops the batch; earlier confirmed changes remain. Stop/Close cannot withdraw an already-sent step.',wraplength=1000).pack(anchor='w')
        app.worker.commands.put(('input_select',None));self.refresh()
    def ready(self):return not self.closed and self.app.connected and self.serial==self.app.name_cache.serial
    def update_buttons(self):
        idle=self.ready() and not self.busy
        self.read_button.config(state='normal' if self.app.connected and not self.busy else 'disabled')
        self.load_button.config(state='normal' if idle else 'disabled')
        self.save_button.config(state='normal' if idle and self.scene else 'disabled')
        self.apply_button.config(state='normal' if idle and self.changes and self.preview_current else 'disabled')
        self.stop_button.config(state='normal' if self.busy and not self.stopped else 'disabled')
        if hasattr(self,'rate_button'):self.rate_button.config(state='normal' if idle and self.rate_match_needed() else 'disabled')
        if hasattr(self,'layout_button'):self.layout_button.config(state='normal' if idle and self.layout_match_needed() else 'disabled')
        if hasattr(self,'source_button'):self.source_button.config(state='normal' if idle and self.source_match_needed() else 'disabled')
    def rate_match_needed(self):
        return bool(self.scene and self.target and self.scene['demo']==self.target['demo'] and scene_rate.needed(self.target,self.scene))
    def match_rate(self):
        if self.busy or not self.ready() or not self.rate_match_needed():return
        self.rate_change=dict(bus='sample_rate',source=0,stereo=False,field='rate',
            values=[scene_rate.saved_rate(self.target)],expected=[scene_rate.saved_rate(self.scene)])
        self.mode='rate_apply';self.busy=True;self.stopped=False;self.changes=[];self.preview_current=None
        self.message.config(text='Matching sample rate using the idle ALSA device; a fresh preview follows…')
        self.update_buttons();self.queue('scene_set',layout=self.layout,change=self.rate_change)
    def layout_match_needed(self):
        return bool(self.scene and self.target and self.scene['demo']==self.target['demo'] and self.scene['layout']!=self.target['layout'])
    def match_layout(self):
        if self.busy or not self.ready() or not self.layout_match_needed():return
        self.changes=scene_layout.plan(self.target['layout'],self.scene['layout'])
        self.mode='layout_apply';self.position=0;self.busy=True;self.stopped=False;self.preview_current=None
        self.update_buttons();self.queue_next()
    def render_layout(self,current,target):
        for row in self.table.get_children():self.table.delete(row)
        for bus in ('main','cue'):
            for left in range(0,64,2):
                a=scene_layout.pair_label(current['layout'][bus],left);b=scene_layout.pair_label(target['layout'][bus],left)
                if a==b=='Not included':continue
                source=left+1;bank='ANALOG' if source<=16 else 'ADAT' if source<=32 else 'USB'
                number=source if source<=16 else source-16 if source<=32 else source-32
                self.table.insert('','end',iid=f'layout:{bus}:{source}',values=(f'{bus.upper()} · {bank} {number}/{number+1}',a,b,'Change' if a!=b else 'Matching'))
    def source_match_needed(self):
        if not self.scene or not self.target or self.scene['layout']!=self.target['layout'] or self.scene['demo']!=self.target['demo']:return False
        current=scene_sources.from_scene(self.scene);target=scene_sources.from_scene(self.target)
        return current is not None and target is not None and current!=target
    def match_sources(self):
        if self.busy or not self.ready() or not self.source_match_needed():return
        self.source_change=dict(bus='input_sources',source=0,stereo=False,field='sources',
            values=scene_sources.from_scene(self.target),expected=scene_sources.from_scene(self.scene))
        self.mode='source_apply';self.busy=True;self.stopped=False;self.changes=[];self.preview_current=None
        self.message.config(text='Matching connected input sources to the scene; then reading a fresh preview…')
        self.update_buttons();self.queue('scene_set',layout=self.layout,change=self.source_change)
    def queue(self,command,**data):
        self.request=uuid.uuid4().hex
        self.app.worker.commands.put((command,dict(data,scope='mixer',request_id=self.request,connection_serial=self.serial)))
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
        self.message.config(text=f'{"Rechecking before recall" if self.mode=="preflight" else "Reading mixer settings"} · {self.position+1}/{len(self.addresses)}')
        self.queue('scene_read',part='entry',layout=self.layout,address=self.addresses[self.position])
    @staticmethod
    def key(e):return f"{e['bus']}:{e['source']}"+(":"+e["field"] if "field" in e else "")
    @staticmethod
    def label(e):
        source=e['source']
        if e['bus']=='sample_rate':return 'INTERNAL SAMPLE RATE'
        if e['bus']=='clock':return 'CLOCK · CONFIGURATION'
        if e['bus']=='speaker_ab':return 'SPEAKER A/B · CONFIGURATION'
        if e['bus']=='inputs':return f"INPUT {source}/{source+1} · "+e.get('field','').replace('_',' ').upper()
        if e['bus']=='outputs':return f"ANALOG OUTPUT {source}/{source+1} · "+e.get('field','').upper()
        if e['bus']=='speaker_b':return 'SPEAKER B · TRIM'
        if e['bus'] in ('monitor','phones'):return e['bus'].upper()+' · '+e.get('field','').replace('_',' ').upper()
        if e['bus']=='names':return 'NAME · '+source_label(source)
        if e['bus']=='routing':return 'ROUTE · '+DESTINATION_LABELS[source]
        if not source:return e['bus'].upper()+' MASTER · '+e.get('field','').replace('_',' ').upper()
        prefix='ANALOG' if source<=16 else 'ADAT' if source<=32 else 'USB'
        number=source if source<=16 else source-16 if source<=32 else source-32
        return f"{e['bus'].upper()} · {prefix} {number}"+(f'/{number+1}' if e['stereo'] else '')+' · '+e.get('field','').replace('_',' ').upper()
    @staticmethod
    def db(e):
        field=e['field']
        if field=='rate':return 'External / not captured' if e['values'][0] is None else f"{e['values'][0]:,} Hz"
        if e.get('bus')=='outputs' and field=='configuration':
            from mixer_scene_outputs import describe_pair
            return describe_pair(e['values'])
        if field=='clock_config':return describe_clock(e['values'][0])
        if field=='ab_config':return describe_ab(e['values'][0])
        if field=='instrument':return ' / '.join('N/A' if v is None else 'Instrument' if v else 'Line' for v in e['values'])
        if field=='hpf':return ' / '.join('N/A' if v is None else 'On' if v else 'Off' for v in e['values'])
        if field=='phase':return ' / '.join('Inverted' if v else 'Normal' for v in e['values'])
        if field=='kind':return ' / '.join(e['values'])
        if field=='input_link':return ' / '.join('N/A' if v is None else 'Linked' if v else 'Unlinked' for v in e['values'])
        if field=='link':return ' / '.join('Linked' if v else 'Unlinked' for v in e['values'])
        if field=='dim_depth':return '−10 dB' if e['values'][0]==0 else '−20 dB'
        if field=='name':return e['values'][0] or '(blank)'
        if field=='route':return SOURCE_LABELS[e['values'][0]]
        if field.endswith('_pre'):return ' / '.join('Pre' if v else 'Post' for v in e['values'])
        if field.startswith('aux_link'):return ' / '.join('Linked' if v else 'Unlinked' for v in e['values'])
        if field in ('pad','mute','solo','dim','mono','cue_enabled') or field.endswith('_mute'):return ' / '.join('On' if v else 'Off' for v in e['values'])
        if field=='pan':return ' / '.join('Centre' if v==127 else ('L ' if v<127 else 'R ')+str(abs(v-127)) for v in e['values'])
        return ' / '.join(f'{v/256:.2f} dB' for v in e['values'])
    @staticmethod
    def flatten(scene):
        return [dict(bus=e['bus'],source=e['source'],stereo=e['stereo'],field=f,values=values)
                for e in scene['entries'] for f,values in ({'configuration':e['values']} if e['bus']=='outputs' else e['values']).items()]
    def render(self,current,target=None):
        for row in self.table.get_children():self.table.delete(row)
        saved={self.key(e):e for e in self.flatten(target)} if target else {}
        for e in self.flatten(current):
            other=saved.get(self.key(e));changed=other is not None and other['values']!=e['values']
            self.table.insert('','end',iid=self.key(e),values=(self.label(e),self.db(e),self.db(other) if other else '—','Change' if changed else 'Matching' if other else 'Read'))
    def finish_capture(self):
        current=make_scene(self.layout,self.entries,self.app.demo)
        if self.mode=='verify':
            differences=plan(self.target,current)
            if differences:raise ValueError(f'Recall finished but {len(differences)} settings differ on final readback. Inspect the mixer; no retry or rollback was performed.')
            self.scene=current;self.busy=False;self.preview_current=None
            self.render(current,self.target);self.message.config(text=f'Recall complete: {self.applied_count} settings confirmed, followed by a complete scene readback.');self.update_buttons();return
        if self.mode=='preflight':
            if plan(self.preview_current,current):raise ValueError('Mixer controls changed after preview; open the scene again. No recall started.')
            self.scene=current;self.position=0;self.mode='apply';self.queue_next();return
        self.scene=current;self.busy=False
        if self.target:
            if self.rate_match_needed():
                self.changes=[];self.preview_current=None;self.render(current,self.target)
                self.message.config(text='Saved Internal sample rate differs. Select Internal clock and close AF16Rig audio streams, then Match sample rate. A fresh preview follows; settings are not recalled automatically.')
                self.update_buttons();return
            if self.layout_match_needed():
                self.changes=[];self.preview_current=None;self.render_layout(current,self.target)
                self.message.config(text='Mixer layout differs. Review the channel selections, then Match mixer layout. This can change audible channels at their current levels. A fresh preview follows; settings are not recalled automatically.')
                self.update_buttons();return
            if self.source_match_needed():
                self.changes=[];self.preview_current=None;self.render(current,self.target)
                self.message.config(text='Input sources differ. Review the KIND rows, then Match input sources. Compatible front inputs must be connected. After matching, review the fresh preview before recalling settings.')
                self.update_buttons();return
            self.changes=plan(self.target,current);self.preview_current=current
            self.render(current,self.target)
            self.message.config(text=f'{len(self.changes)} mixer settings will change. Review, then Recall listed settings.' if self.changes else 'All scene mixer settings already match; nothing to recall.')
        else:
            self.render(current);self.message.config(text=f'Read {len(current["entries"])} mixer settings. Save scene, or open a scene to preview changes.')
        self.update_buttons()
    def open_scene(self):
        if self.busy or not self.ready():return
        serial=self.serial
        path=filedialog.askopenfilename(parent=self.window,title='Open Main/Cue mixer scene',filetypes=[('Mixer scene','*.json')])
        if not path or not self.ready() or self.serial!=serial:return
        try:target=load_scene(path)
        except (ValueError,OSError) as error:self.message.config(text=str(error));return
        self.refresh(target)
    def save(self):
        if self.busy or not self.ready() or self.scene is None:return
        content=json.dumps(self.scene,indent=2,allow_nan=False)+'\n'
        path=filedialog.asksaveasfilename(parent=self.window,title='Save Main/Cue mixer scene',initialfile='AF16Rig-mixer-scene.json',defaultextension='.json',filetypes=[('Mixer scene','*.json')])
        if not path:return
        try:Path(path).write_text(content,encoding='utf-8')
        except OSError as error:
            if not self.closed:self.message.config(text=str(error))
            return
        if not self.closed:self.message.config(text='Mixer scene saved. This file contains mixer controls, not a complete device preset.')
    def start_apply(self):
        if self.busy or not self.ready() or not self.changes or not self.preview_current:return
        self.refresh(self.target,mode='preflight')
    def queue_next(self):
        self.timer=None
        if self.closed:return
        if self.stopped or not self.ready():self.fail(f'Stopped after {self.position}/{len(self.changes)} confirmed mixer settings.');return
        if self.position==len(self.changes) and self.mode=='layout_apply':
            self.busy=False;self.scene=None;self.refresh(self.target);return
        if self.position==len(self.changes):
            self.applied_count=self.position;self.mode='verify';self.entries=[];self.layout=None;self.position=0
            self.message.config(text='Checking complete mixer state after recall…')
            self.queue('scene_read',part='layout');return
        c=self.changes[self.position]
        if self.mode=='layout_apply':
            self.message.config(text=f'Matching mixer layout · {self.position+1}/{len(self.changes)}')
            self.queue('scene_set',layout=c['expected_layout'],change=c);return
        self.message.config(text=f'Recalling {self.position+1}/{len(self.changes)} · {self.label(c)}')
        self.queue('scene_set',layout=self.layout,change=c)
    def stop(self):
        self.stopped=True;self.update_buttons()
        if self.request is None:
            if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
            self.fail('Stopped. Confirmed changes remain; read current mixer settings before continuing.')
        else:self.message.config(text='Stopping after the current step finishes…')
    def fail(self,message):
        self.busy=False;self.request=None;self.scene=None;self.preview_current=None
        self.message.config(text=message);self.update_buttons()
    def connection_changed(self):
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
        self.stopped=True;self.fail('Connection or preset changed. Read mixer settings again.')
    def handle(self,event):
        if self.closed:return
        if event['kind']=='input_error' and event.get('channel')=='mixer_scenes':self.connection_changed();return
        if event['kind'] not in ('scene_snapshot','scene_written','scene_error') or event.get('request_id')!=self.request:return
        self.request=None
        if not self.ready() or event.get('connection_serial')!=self.serial:self.connection_changed();return
        if event['kind']=='scene_error':
            suffix=f' {self.position}/{len(self.changes)} earlier mixer settings confirmed; no rollback.' if self.mode=='apply' else ''
            self.fail(event['message']+suffix);return
        if event['kind']=='scene_written' and self.mode=='rate_apply':
            if event['record']!={k:self.rate_change[k] for k in ('bus','source','stereo','field','values')}:
                self.fail('Unexpected rate confirmation; read device state again.');return
            self.busy=False;self.scene=None;self.preview_current=None
            if self.stopped:self.fail('Rate matching finished; stopped before fresh preview. Read current settings.');return
            self.refresh(self.target);return
        if event['kind']=='scene_written' and self.mode=='source_apply':
            if event['record']!={k:self.source_change[k] for k in ('bus','source','stereo','field','values')}:
                self.fail('Unexpected source confirmation; read device state again.');return
            self.busy=False;self.scene=None;self.preview_current=None
            if self.stopped:self.fail('Source matching finished; stopped before fresh preview. Read current settings.');return
            self.refresh(self.target);return
        if event['kind']=='scene_written':
            c=self.changes[self.position];record=event['record']
            if record!={k:c[k] for k in ('bus','source','stereo','field','values')}:
                self.fail('Unexpected recall confirmation; stopped. Read mixer settings.');return
            if self.mode=='layout_apply':
                self.position+=1;self.timer=self.window.after(80,self.queue_next);return
            display=record
            if c['bus']=='outputs' and c['field']=='level':
                display=dict(record,field='configuration',values=dict(level=record['values'],link=c['output_links']))
            self.table.set(self.key(display),'result','Confirmed');self.table.set(self.key(display),'current',self.db(display))
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
