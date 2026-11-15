"""Analog, ADAT and USB mixer inclusion; source conversion is explicit."""
import tkinter as tk
from tkinter import ttk
from mixer_view import button,lab,configure_changed
from af16rig_gui import BG,MUTED


def inclusion_options(state, source):
    raw=state.get('raw',{})
    mono,pairs=raw.get('show'),raw.get('stereo')
    if type(source) is not int or not 1<=source<=64 or type(mono) is not int or type(pairs) is not int:
        return {}
    index=source-1;pair=index//2
    stereo=bool(pairs & (1<<pair));selected=bool(mono & (1<<index));pair_mono=bool(mono & (3<<(pair*2)))
    return {'mono_add':not stereo and not selected,'mono_remove':not stereo and selected,
            'stereo_add':not stereo and not pair_mono,'stereo_remove':stereo and not pair_mono}


class MixerSourcesWindow:
    def __init__(self,app):
        self.app=app;self.state={};self.pending=False;self.stale=True
        self.channel=tk.StringVar(value='mixer_sources');self.bus=tk.StringVar(value='main');self.source=tk.IntVar(value=1);self.bank=tk.StringVar(value='Analog')
        self.window=app.make_panel();self.window.title('AF16Rig — Mixer sources')
        shell=tk.Frame(self.window,bg=BG,padx=24,pady=20);shell.pack(fill='both',expand=True)
        lab(shell,'MIXER SOURCES',font=('DejaVu Sans',18,'bold')).pack(anchor='w')
        lab(shell,'Include Analog, ADAT or USB returns as mono sources or stereo pairs in Main or Cue.',fg=MUTED).pack(anchor='w',pady=12)
        row=tk.Frame(shell,bg=BG);row.pack(anchor='w',pady=12)
        self.bus_menu=ttk.Combobox(row,textvariable=self.bus,values=('main','cue'),state='readonly',width=10);self.bus_menu.pack(side='left',padx=(0,20))
        self.bus_menu.bind('<<ComboboxSelected>>',self.select)
        self.bank_menu=ttk.Combobox(row,textvariable=self.bank,values=('Analog','ADAT','USB'),state='readonly',width=12);self.bank_menu.pack(side='left',padx=(0,10))
        self.bank_menu.bind('<<ComboboxSelected>>',self.change_bank)
        lab(row,'Input').pack(side='left',padx=(0,10))
        self.source_menu=ttk.Combobox(row,textvariable=self.source,values=list(range(1,17)),state='readonly',width=6);self.source_menu.pack(side='left')
        self.source_menu.bind('<<ComboboxSelected>>',self.select)
        self.summary=lab(shell,'Reading…',font=('DejaVu Sans',13),justify='left');self.summary.pack(anchor='w',pady=15)
        self.buttons={}
        for key,title in [('mono_add','Include mono input'),('mono_remove','Remove mono input'),('stereo_add','Include stereo pair'),('stereo_remove','Remove stereo pair')]:
            b=button(shell,title,lambda k=key:self.apply(k),width=25,state='disabled');b.pack(anchor='w',pady=5);self.buttons[key]=b
        lab(shell,'To switch from mono inputs to stereo, remove both mono inputs first.\nTo switch back, remove the stereo pair, then include each mono input.\nExisting levels, mute, solo and sends are retained.',fg=MUTED,justify='left').pack(anchor='w',pady=18)
        self.refresh_button=button(shell,'Refresh sources',self.select);self.refresh_button.pack(anchor='w')
        self.message=lab(shell,'',fg=MUTED,justify='left');self.message.pack(anchor='w',pady=12)
        lab(shell,'Use the Analog, ADAT and USB bank buttons on the Mixer page to adjust these sources.',fg=MUTED,wraplength=900).pack(anchor='w',pady=8)
        self.select()
    def global_source(self):
        from mixer_membership import source_id
        return source_id(self.bank.get(),self.source.get())
    def change_bank(self,event=None):
        if self.pending:return
        self.source.set(1);self.source_menu.config(values=list(range(1,33 if self.bank.get()=='USB' else 17)));self.select()
    def select(self,event=None):
        if self.pending:return
        self.state={};self.stale=True;self.update()
        self.app.worker.commands.put(('input_select',('mixer_sources',self.bus.get(),self.global_source())))
    def refresh_names(self):
        self.update()

    def update(self):
        source=self.global_source();left=((source-1)//2)*2+1
        raw=self.state.get('raw',{});mono=raw.get('show');pairs=raw.get('stereo')
        if type(mono) is int and type(pairs) is int:
            cache=getattr(self.app,'name_cache',None)
            local_left=((self.source.get()-1)//2)*2+1
            label=cache.title(left,True) if cache and self.bank.get() in ('Analog','ADAT') else f'{self.bank.get()} {local_left}/{local_left+1}'
            text=f'{self.bus.get().title()} mix · {label}\n'
            text+=f'Mono {local_left}: '+('included' if mono&(1<<(left-1)) else 'absent')+'    '
            text+=f'Mono {local_left+1}: '+('included' if mono&(1<<left) else 'absent')+'\n'
            text+='Stereo pair: '+('included' if pairs&(1<<((left-1)//2)) else 'absent')
        else:text='Reading source selection…'
        configure_changed(self.summary,text=text)
        options=inclusion_options(self.state,source)
        ready=self.app.connected and not self.stale and not self.pending and self.app.info.get('state_version')==18
        for key,b in self.buttons.items():configure_changed(b,state='normal' if ready and options.get(key) else 'disabled')
        for menu in (self.bus_menu,self.bank_menu,self.source_menu):configure_changed(menu,state='disabled' if self.pending else 'readonly')
        configure_changed(self.refresh_button,state='disabled' if self.pending else 'normal')
    def apply(self,key):
        if key not in self.buttons or self.buttons[key].cget('state') not in ('normal','active'):return
        self.pending=True;self.update()
        raw=self.state['raw']
        self.message.config(text='Updating mixer source selection…')
        self.app.worker.commands.put(('membership_set',dict(bus=self.bus.get(),source=self.global_source(),stereo=key.startswith('stereo'),value=key.endswith('add'),mono=raw['show'],pairs=raw['stereo'],connection_serial=self.state['connection_serial'])))
    def handle(self,event):
        state=event.get('state',{})
        if event.get('channel',state.get('channel'))!='mixer_sources':return
        bus=event.get('bus',state.get('bus'));source=event.get('source',state.get('source'))
        if bus is not None and (bus!=self.bus.get() or source!=self.global_source()):return
        if event['kind']=='input_snapshot':
            self.state=state;self.pending=False;self.stale=False
            self.message.config(text='Demo source selection' if self.app.demo else 'Live source selection · hardware readback')
        elif event['kind']=='input_written' and event.get('name')=='inclusion':
            self.message.config(text='Selection write confirmed; reading updated sources…')
        elif event['kind']=='input_error':
            self.pending=False;self.stale=True
            self.message.config(text=event.get('message','Read failed'))
        self.update()
    def close(self):
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()
