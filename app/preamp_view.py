"""Active input gain, pair link and front/rear selection inside mixer strips."""
import tkinter as tk
from mixer_view import ValueControl,button,lab,configure_changed
from af16rig_gui import PANEL,MUTED,ACCENT,BG

class PreampControls:
    def __init__(self,parent,controller):
        self.c=controller;self.app=controller.app
        self.frame=tk.Frame(parent,bg=PANEL);self.frame.pack(fill='x',pady=(3,0))
        self.heading=lab(self.frame,'INPUT GAIN',fg=MUTED,font=('DejaVu Sans',8));self.heading.pack()
        self.row=tk.Frame(self.frame,bg=PANEL);self.row.pack(fill='x')
        source=controller.source.get();left=((source-1)//2)*2+1
        self.gains={};self.cells={};self.labels={}
        for channel in (source,source+1) if source%2 and source<16 else (source,):
            cell=tk.Frame(self.row,bg=PANEL);cell.pack(side='left',fill='x',expand=True);self.cells[channel]=cell
            self.labels[channel]=lab(cell,str(channel),fg=MUTED,font=('DejaVu Sans',7));self.labels[channel].pack()
            dial=ValueControl(cell,lambda d,ch=channel:self.step(ch,d),low=0,high=12,target=lambda v,ch=channel:self.set_gain(ch,v))
            dial.quantum=1;dial.configure(width=40,height=40);dial.pack(fill='x');self.gains[channel]=dial
        self.link=button(self.frame,'LINK '+str(left)+'/'+str(left+1),self.toggle_link)
        self.link.pack(fill='x',padx=3,pady=2)
        # Every strip reserves the same optional source-control row.
        self.source_slot=tk.Frame(self.frame,bg=PANEL,height=1)
        self.source_slot.pack(fill='x')
        self.source_slot.pack_propagate(False)
        self.source_button=None
        if source in (1,2):
            self.source_button=button(self.source_slot,'FRONT / REAR',self.toggle_source)
            self.source_button.pack(fill='x',padx=3,pady=2)
    @property
    def dashboard(self):return self.app.dashboard
    def refresh(self):
        # During console construction app.dashboard is assigned only after __init__.
        dash=getattr(self.app,'dashboard',None)
        states={} if dash is None else dash.preamp_states
        pending=set() if dash is None else dash.preamp_pending
        source=self.c.source.get();left=((source-1)//2)*2+1
        ready=self.app.connected and not self.c.stale and self.c.bus.get()=='main' and left not in pending
        stereo=bool(self.c.state.get('stereo_members'))
        for ch,dial in self.gains.items():
            show=ch==source
            if show:self.cells[ch].pack(side='left',fill='x',expand=True)
            else:self.cells[ch].pack_forget()
            state=states.get(ch,{})
            high=state.get('high',12)
            if dial.high!=high:dial.cancel_drag();dial.high=high
            kind=state.get('kind','')
            self.labels[ch].config(text=(f'{source}/{source+1}' if stereo and ch==source else str(ch))+' '+{'rear':'REAR','line':'LINE','mic':'MIC','mini':'FRONT'}.get(kind,''))
            partner=states.get(source+1,{}) if stereo else state
            compatible=not stereo or (partner.get('kind')==kind and partner.get('gain_available',False))
            readout=None
            if stereo and ch==source and partner.get('value')!=state.get('value'):
                readout=' / '.join('—' if v is None else f'{v:g}' for v in (state.get('value'),partner.get('value')))
            dial.update_value(state.get('value'),ready and state.get('gain_available',False) and compatible,readout=readout,
                              valid=self.app.connected and bool(state) and self.c.bus.get()=='main' and compatible)
        state=states.get(source,{})
        raw=self.c.state.get('raw',{})
        mono,pairs=raw.get('show'),raw.get('stereo')
        known=type(mono) is int and type(pairs) is int
        mask=3<<(left-1);bit=1<<((left-1)//2)
        link=int(bool(pairs&bit)) if known else None
        can_convert=known and ((mono&mask==mask and not pairs&bit) or (mono&mask==0 and pairs&bit))
        pair=f'{left}/{left+1}'
        configure_changed(self.link,text=('UNLINK ' if link==1 else 'LINK ')+pair,
                          state='normal' if ready and can_convert and state.get('link_available') else 'disabled',bg=ACCENT if link==1 else '#383c41',fg=BG if link==1 else '#e6e8ea')
        if self.source_button:
            pair_states=[states.get(i,{}) for i in (1,2)]
            kinds=[x.get('kind') for x in pair_states]
            override=pair_states[0].get('forced_rear')
            self.source_target=override!=3
            text='1/2 → FRONT' if override==3 else '1/2 → REAR' if override is not None else 'FRONT / REAR'
            configure_changed(self.source_button,text=text,state='normal' if self.app.connected and self.c.bus.get()=='main' and left not in pending and all(kinds) and override is not None else 'disabled')
    def set_gain(self,channel,value):
        state=self.dashboard.preamp_states.get(channel,{})
        left=((channel-1)//2)*2+1
        if not self.app.connected or self.c.stale or self.c.bus.get()!='main' or left in self.dashboard.preamp_pending or not state.get('gain_available'):return False
        target=max(0,min(state['high'],round(value)))
        stereo=bool(self.c.state.get('stereo_members'))
        partner=self.dashboard.preamp_states.get(left+1,{})
        if stereo and (partner.get('kind')!=state['kind'] or not partner.get('gain_available')):return False
        self.dashboard.preamp_pending.add(left)
        command=('preamp_pair_gain',(left,state['kind'],target)) if stereo else ('preamp_set',(channel,state['kind'],'gain',target))
        self.app.worker.commands.put(command)
        self.refresh();return True
    def step(self,channel,direction):
        state=self.dashboard.preamp_states.get(channel,{})
        if state.get('value') is not None:self.set_gain(channel,state['value']+direction)
    def toggle_link(self):
        if self.link.cget('state') not in ('normal','active'):return
        source=self.c.source.get();state=self.dashboard.preamp_states[source];left=state['pair'][0]
        if left in self.dashboard.preamp_pending:return
        self.dashboard.preamp_pending.add(left)
        raw=self.c.state['raw'];value=not bool(raw['stereo']&(1<<((left-1)//2)))
        self.app.worker.commands.put(('stereo_pair',('main',left,state['kind'],value,raw['show'],raw['stereo'])))
        self.refresh()
    def toggle_source(self):
        if self.source_button is None or self.source_button.cget('state') not in ('normal','active'):return
        if 1 in self.dashboard.preamp_pending:return
        states=self.dashboard.preamp_states
        force=getattr(self,'source_target',states.get(1,{}).get('forced_rear')!=3)
        self.dashboard.preamp_pending.add(1)
        self.app.worker.commands.put(('preamp_source',force));self.refresh()
