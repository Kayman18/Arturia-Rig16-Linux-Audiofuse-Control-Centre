"""Canvas patch bay backed by the established, readback-guarded routing editor."""
import tkinter as tk
import math
from tkinter import ttk
from routing_window import RoutingWindow
from routing_labels import SOURCE_LABELS, DESTINATION_LABELS
from routing_history import RoutingHistory
from routing_names import named_label
from cable_colors import CableColors,PALETTE,DEFAULT
from patchbay_search import matches

BG='#202225'; PANEL='#2b2e32'; TEXT='#e6e8ea'; MUTED='#969ca2'; CYAN='#62cbd5'


def source_bank(code):
    return 'Mix buses' if 192<=code<=197 else 'Analog' if 64<=code<=79 else 'ADAT' if 80<=code<=95 else 'USB' if 128<=code<=159 else 'Unknown'


def destination_bank(index):
    return 'Physical' if 0<=index<=11 else 'ADAT' if 12<=index<=27 else 'USB' if 28<=index<=59 else 'Unknown'


class PatchBayWindow(RoutingWindow):
    def __init__(self,app):
        if not hasattr(app,'cable_colors'):app.cable_colors=CableColors.load()
        self.history=RoutingHistory();self.history_job=None;self.history_done=None
        self.pending_color=None
        self.stereo_job=None;self.stereo_undo=None
        self.app=app;self.state={};self.previous=None;self.pending=False;self.request_id=None
        self.undo_record=None;self.editable=False;self.batch=None;self.batch_done=0;self.notice=''
        self.selected_destination=None;self.drag_source=None;self.armed_source=None;self.source_points={};self.destination_points={}
        self.channel=tk.StringVar(value='routing')
        self.window=app.make_panel();self.window.title('AF16Rig — Routing patch bay')
        shell=tk.Frame(self.window,bg=BG);shell.pack(fill='both',expand=True,padx=12,pady=12)
        header=tk.Frame(shell,bg=BG);header.pack(fill='x',pady=(0,12))
        tk.Label(header,text='ROUTING / PATCH BAY',bg=BG,fg=CYAN,font=('DejaVu Sans',17,'bold')).pack(side='left')
        self.refresh_button=ttk.Button(header,text='Read routing',command=self.refresh);self.refresh_button.pack(side='right',padx=4)
        self.preset_load_button=ttk.Button(header,text='Load routing…',command=self.load_preset);self.preset_load_button.pack(side='right',padx=4)
        self.preset_save_button=ttk.Button(header,text='Save routing…',command=self.save_preset);self.preset_save_button.pack(side='right',padx=4)
        filters=tk.Frame(shell,bg=BG);filters.pack(fill='x',pady=(0,8))
        tk.Label(filters,text='SOURCE BANK',bg=BG,fg=MUTED).pack(side='left',padx=(0,8))
        self.source_filter=tk.StringVar(value='Connected')
        f=ttk.Combobox(filters,textvariable=self.source_filter,values=('Connected','All','Mix buses','Analog','USB','ADAT'),state='readonly',width=14);f.pack(side='left')
        f.bind('<<ComboboxSelected>>',self.filter_changed)
        tk.Label(filters,text='OUTPUT BANK',bg=BG,fg=MUTED).pack(side='left',padx=(24,8))
        self.destination_filter=tk.StringVar(value='Physical')
        f=ttk.Combobox(filters,textvariable=self.destination_filter,values=('Physical','ADAT','USB','All'),state='readonly',width=14);f.pack(side='left')
        f.bind('<<ComboboxSelected>>',self.filter_changed)
        self.stereo_mode=tk.BooleanVar(value=False)
        self.stereo_toggle=ttk.Checkbutton(filters,text='Stereo pairs (L/R)',variable=self.stereo_mode,command=self.clear_selection)
        self.stereo_toggle.pack(side='left',padx=18)
        self.count_label=tk.Label(filters,text='',bg=BG,fg=MUTED);self.count_label.pack(side='right')
        search=tk.Frame(shell,bg=BG);search.pack(fill='x',pady=(0,8))
        self.source_search=tk.StringVar();self.destination_search=tk.StringVar()
        for title,var in (('Find source',self.source_search),('Find output',self.destination_search)):
            tk.Label(search,text=title,bg=BG,fg=MUTED).pack(side='left',padx=(0,8))
            entry=ttk.Entry(search,textvariable=var,width=24);entry.pack(side='left',padx=(0,16))
            entry.bind('<KeyRelease>',self.search_changed)
            entry.bind('<Escape>',lambda e:self.reset_search())
        ttk.Button(search,text='Clear search',command=self.reset_search).pack(side='left')
        palette=tk.Frame(shell,bg=BG);palette.pack(fill='x',pady=(0,10))
        tk.Label(palette,text='CABLE COLOUR',bg=BG,fg=MUTED).pack(side='left',padx=(0,10))
        self.color_buttons={}
        for name,color in PALETTE:
            b=tk.Button(palette,text=name,bg=color,activebackground=color,fg='#101820',activeforeground='#101820',
                        width=7,relief='flat',bd=2,highlightthickness=1,highlightbackground=BG,
                        command=lambda c=color:self.choose_color(c))
            b.pack(side='left',padx=3);self.color_buttons[color]=b
        self.color_label=tk.Label(palette,text='',bg=BG,fg=TEXT);self.color_label.pack(side='left',padx=12)
        self.refresh_palette()
        area=tk.Frame(shell,bg=BG);area.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(area,bg='#1b1e21',highlightthickness=0)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.canvas.yview);scroll.pack(side='right',fill='y')
        self.canvas.configure(yscrollcommand=scroll.set);self.canvas.pack(fill='both',expand=True,side='left')
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Motion>',self.motion)
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Button-4>',lambda e:self.scroll(-1));self.canvas.bind('<Button-5>',lambda e:self.scroll(1))
        self.canvas.bind('<MouseWheel>',lambda e:self.scroll(-1 if e.delta>0 else 1))
        self.canvas.bind('<Escape>',lambda e:self.clear_selection())
        self.canvas.bind('<Button-3>',lambda e:self.clear_selection())
        self.canvas.bind('<Control-z>',lambda e:self.history_shortcut('undo'))
        self.canvas.bind('<Control-y>',lambda e:self.history_shortcut('redo'))
        self.canvas.bind('<Control-Shift-Z>',lambda e:self.history_shortcut('redo'))
        editor=ttk.Frame(shell);editor.pack(fill='x',pady=10)
        self.route_label=ttk.Label(editor,text='Drag a source jack to an output');self.route_label.pack(side='left',fill='x',expand=True)
        self.redo_button=ttk.Button(editor,text='Redo',command=self.redo_route,state='disabled');self.redo_button.pack(side='right',padx=6)
        self.undo_button=ttk.Button(editor,text='Undo last route',command=self.undo_route);self.undo_button.pack(side='right',padx=6)
        ttk.Button(editor,text='Clear selection',command=self.clear_selection).pack(side='right')
        self.save_button=ttk.Button(editor,text='Save report…',command=self.save);self.save_button.pack(side='right',padx=6)
        self.message=ttk.Label(shell,text='',wraplength=1050);self.message.pack(anchor='w')
        ttk.Label(shell,text='Drag between jacks · Esc / right-click cancels · Ctrl+Z / Ctrl+Y: undo / redo · Search within selected banks').pack(anchor='w',pady=(6,0))
        # Keep the established controller's state adapters; no diagnostic table
        # or source-code controls are shown in the patch-bay interface.
        self.tree=ttk.Treeview(shell,columns=('field','slot','value','hex','description','previous'),show='headings')
        self.source_choices={f'{name} ({code})':code for code,name in SOURCE_LABELS.items()}
        self.source_choice=tk.StringVar();self.source_menu=ttk.Combobox(shell,textvariable=self.source_choice)
        self.apply_button=ttk.Button(shell,command=self.apply_route)
        app.worker.commands.put(('input_select',None));self.refresh()

    def port_label(self,kind,code):
        return named_label(getattr(self.app,'name_cache',None),kind,code)

    def output_text(self,index):
        source=self.routes().get(index);label=self.port_label('dest',index)
        if source is None:return label+' · unread'
        if source not in SOURCE_LABELS:return label+f' · unknown {source}'
        if source not in self.source_points:return label+' ← '+self.port_label('source',source)
        return label

    def refresh_names(self):
        if self.search_active() and getattr(self,'drag_source',None) is None and getattr(self,'drag_destination',None) is None:
            self.draw()
        # Update only text items: no cable redraw, drag cancellation or route writes.
        for kind,points in (('source',self.source_points),('dest',self.destination_points)):
            for code in points:
                tag=f'name_{kind}_{code}'
                text=self.port_label(kind,code) if kind=='source' else self.output_text(code)
                if self.canvas.itemcget(tag,'text')!=text:self.canvas.itemconfigure(tag,text=text)
        route=self.selected_route()
        if route:self.route_label.config(text=self.port_label('source',route[1])+' → '+self.port_label('dest',route[0]))
        elif self.armed_source is not None:self.route_label.config(text=self.port_label('source',self.armed_source)+' → click an output jack')

    def routing_history(self):
        if not hasattr(self,'history'):self.history=RoutingHistory()
        return self.history

    def begin_history(self,changes,label,replay=None):
        history=self.routing_history();history.bind(self.state.get('connection_serial'))
        self.history_job=dict(changes=history.checked(changes),confirmed=[],label=label,replay=replay)
        self.history_done=None

    def confirm_history(self,event):
        job=getattr(self,'history_job',None)
        if job is None:return
        expected=job['changes'][len(job['confirmed'])]
        actual=dict(destination=event['destination'],expected_source=event['previous'],source_code=event['actual'])
        if actual!=expected:
            self.routing_history().clear();self.history_job=None;self.history_done=None;return
        job['confirmed'].append(actual)
        if len(job['confirmed'])==len(job['changes']):
            if job['replay']:self.routing_history().complete(job['replay'])
            else:self.routing_history().record(job['changes'],job['label'])
            self.history_done=job['label'];self.history_job=None

    def send_route(self,destination,target,expected,undo=False):
        if self.pending or not self.editable or not self.app.connected:return
        if getattr(self,'history_job',None) is None:
            self.begin_history([dict(destination=destination,source_code=target,expected_source=expected)],'Patch')
        super().send_route(destination,target,expected,undo)

    def replay_history(self,direction):
        if self.pending or not self.editable or not self.app.connected or self.state.get('status')!='stable':return
        history=self.routing_history();history.bind(self.state.get('connection_serial'))
        try:changes=history.prepare(direction)
        except ValueError:return
        self.pending_color=None;self.stereo_job=None;self.stereo_undo=None;self.undo_record=None
        self.begin_history(changes,direction.title(),replay=direction)
        self.start_batch(changes,self.state['connection_serial'])
        self.message.config(text='Checking device routing before '+direction+'…')

    def redo_route(self):self.replay_history('redo')

    def history_shortcut(self,direction):
        if getattr(self,'drag_source',None) is not None or getattr(self,'armed_source',None) is not None:
            return 'break'
        self.replay_history(direction)
        return 'break'

    def close(self):
        self.routing_history().clear();self.history_job=None;self.history_done=None
        super().close()

    def routes(self):
        values=self.state.get('reads',{}).get('second',{}).get('values',{})
        return {i:values[f'output_source[{i}]'] for i in DESTINATION_LABELS if f'output_source[{i}]' in values}

    def selected_route(self):
        i=self.selected_destination;source=self.routes().get(i)
        return (i,source) if i in DESTINATION_LABELS and source in SOURCE_LABELS else None

    def update_editor(self,keep_choice=False):
        super().update_editor(keep_choice)
        if getattr(self,'stereo_toggle',None) is not None:self.stereo_toggle.config(state='disabled' if self.pending else 'normal')
        route=self.selected_route()
        if getattr(self,'stereo_undo',None):
            self.undo_button.config(state='normal' if self.app.connected and not self.pending and self.editable and self.state.get('status')=='stable' else 'disabled',text='Undo stereo patch')
        else:self.undo_button.config(text='Undo last route')
        if route:self.route_label.config(text=self.port_label('source',route[1])+' → '+self.port_label('dest',route[0]))
        elif self.armed_source is not None:self.route_label.config(text=self.port_label('source',self.armed_source)+' → click an output jack')
        else:self.route_label.config(text='Drag a source jack to an output')
        history=getattr(self,'history',None)
        if history is not None:
            ready=self.app.connected and not self.pending and self.editable and self.state.get('status')=='stable' and self.state.get('state_version')==18
            self.undo_button.config(text=f'Undo ({len(history.undo)})',state='normal' if ready and history.undo else 'disabled')
            if getattr(self,'redo_button',None) is not None:self.redo_button.config(text=f'Redo ({len(history.redo)})',state='normal' if ready and history.redo else 'disabled')

    def filter_changed(self,event=None):
        self.drag_source=None;self.drag_destination=None;self.armed_source=None;self.canvas.yview_moveto(0);self.update_editor();self.draw()

    def search_active(self):
        return any(getattr(self,name,None) and getattr(self,name).get().strip()
                   for name in ('source_search','destination_search'))

    def search_changed(self,event=None):
        if event is not None and event.keysym=='Escape':return
        self.selected_destination=None
        self.filter_changed()

    def reset_search(self):
        self.source_search.set('');self.destination_search.set('')
        self.search_changed();return 'break'

    def visible_ports(self):
        query=lambda name:getattr(self,name).get() if hasattr(self,name) else ''
        outputs=[i for i in DESTINATION_LABELS if
                 (self.destination_filter.get()=='All' or destination_bank(i)==self.destination_filter.get())
                 and matches(query('destination_search'),self.port_label('dest',i),DESTINATION_LABELS[i])]
        routes=self.routes();connected={routes[i] for i in outputs if i in routes}
        bank=self.source_filter.get()
        sources=[s for s in SOURCE_LABELS if bank=='All' or (bank=='Connected' and s in connected) or source_bank(s)==bank]
        if bank=='Connected' and not sources and not self.search_active():sources=[192,193,194,195,196,197]
        sources=[s for s in sources if matches(query('source_search'),self.port_label('source',s),SOURCE_LABELS[s])]
        sources.sort(key=lambda s:(source_bank(s)!='Mix buses',s))
        return sources,outputs

    def scroll(self,direction):
        self.canvas.yview_scroll(direction*3,'units');return 'break'

    def clear_selection(self):
        self.selected_destination=None;self.armed_source=None;self.drag_source=None;self.drag_destination=None;self.update_editor();self.draw()

    def draw(self):
        c=self.canvas;c.delete('all');self.source_points={};self.destination_points={}
        w=max(480,c.winfo_width());routes=self.routes()
        sources,outputs=self.visible_ports()
        connected={routes[i] for i in outputs if i in routes}
        row=52;top=100;left=min(235,w*.30);right=w-left
        height=max(c.winfo_height(),top+row*max(len(sources),len(outputs))+20)
        c.configure(scrollregion=(0,0,w,height))
        # Rack rails and metal module faces are procedural, not bitmap assets.
        for rail in range(0,int(height),360):
            c.create_rectangle(0,rail,w,rail+14,fill='#303438',outline='#101214')
            c.create_line(0,rail+2,w,rail+2,fill='#555c62')
            for hole in range(12,int(w),28):c.create_oval(hole,rail+5,hole+5,rail+10,fill='#111416',outline='')
        self.module_panel(8,20,left+27,height-12,'SIGNAL SOURCES','AF16 / OUTPUT JACKS',CYAN)
        self.module_panel(right-27,20,w-8,height-12,'DESTINATIONS','AF16 / INPUT JACKS','#ddb76d')
        if not sources:c.create_text((left+35)/2,top,text='No matching sources',fill=MUTED,font=('DejaVu Sans',9))
        if not outputs:c.create_text((right-27+w-8)/2,top,text='No matching outputs',fill=MUTED,font=('DejaVu Sans',9))
        for n,source in enumerate(sources):self.source_points[source]=(left,top+n*row)
        for n,index in enumerate(outputs):self.destination_points[index]=(right,top+n*row)
        colors={'Mix buses':CYAN,'Analog':'#e6b35b','USB':'#9cd66d','ADAT':'#b69be8'}
        visible_cables=0
        for index,source in routes.items():
            if source not in self.source_points or index not in self.destination_points:continue
            x,y=self.source_points[source];xx,yy=self.destination_points[index]
            selected=index==self.selected_destination
            color=self.route_color(source,index,colors.get(source_bank(source),MUTED))
            if self.selected_destination is not None and not selected:color='#49535c'
            tag=f'route:{index}'
            self.cable(x,y,xx,yy,color,tag)
            visible_cables+=1
        for source,(x,y) in self.source_points.items():
            tag=f'source:{source}';color=colors[source_bank(source)]
            c.create_line(22,y+23,x+12,y+23,fill='#939b99')
            c.create_oval(21,y-4,27,y+2,fill=color,outline='#626968',tags=(tag,))
            c.create_text(36,y,text=self.port_label('source',source),anchor='w',fill='#222a2d',font=('DejaVu Sans',10,'bold'),width=max(60,x-58),tags=(tag,f'name_source_{source}'))
            self.jack(x,y,color,tag,source in connected or source==self.armed_source)
        for index,(x,y) in self.destination_points.items():
            tag=f'dest:{index}';source=routes.get(index)
            selected=index==self.selected_destination
            if selected:c.create_rectangle(x-19,y-21,w-19,y+21,fill='#cbd8d6',outline='#608f94',tags=(tag,))
            c.create_line(x-12,y+23,w-22,y+23,fill='#939b99')
            label=self.output_text(index)
            c.create_text(x+23,y,text=label,anchor='w',fill='#222a2d' if source in SOURCE_LABELS else '#636b6b',width=max(60,w-x-35),font=('DejaVu Sans',9),tags=(tag,f'name_dest_{index}'))
            self.jack(x,y,self.route_color(source,index,colors.get(source_bank(source) if source is not None else 'Unknown',MUTED)),tag,source in SOURCE_LABELS)
        self.count_label.config(text=f'{len(sources)} sources · {len(outputs)} outputs · {visible_cables} cables · {len(routes)} routes read')

    def module_panel(self,l,t,r,b,title,subtitle,color):
        c=self.canvas
        c.create_rectangle(l+3,t+3,r+3,b+3,fill='#090b0d',outline='')
        c.create_rectangle(l,t,r,b,fill='#b9c0bd',outline='#e1e5e1',width=2)
        c.create_line(l+3,t+2,l+3,b-2,fill='#dbe0dd')
        c.create_line(r-3,t+2,r-3,b-2,fill='#88918f')
        c.create_rectangle(l+14,t+24,r-14,t+50,fill='#263137',outline='')
        c.create_text((l+r)/2,t+37,text=title,fill='#eff3ef',font=('DejaVu Sans',10,'bold'))
        c.create_text((l+r)/2,t+62,text=subtitle,fill='#465350',font=('DejaVu Sans',8))
        c.create_line(l+15,t+53,r-15,t+53,fill=color,width=3)
        for x,y in ((l+10,t+10),(r-10,t+10),(l+10,b-10),(r-10,b-10)):
            c.create_oval(x-4,y-4,x+4,y+4,fill='#78827f',outline='#e7ebe7')
            c.create_line(x-2,y+2,x+2,y-2,fill='#343c3c')

    def cable(self,x,y,xx,yy,color,tag):
        sag=min(100,max(30,abs(xx-x)*.14))
        points=(x,y,x+(xx-x)*.28,y+sag,xx-(xx-x)*.28,yy+sag,xx,yy)
        self.canvas.create_line(*[v+3 for v in points],smooth=True,splinesteps=40,fill='#101417',width=10,tags=(tag,))
        self.canvas.create_line(*points,smooth=True,splinesteps=40,fill='#333c40',width=9,tags=(tag,))
        self.canvas.create_line(*points,smooth=True,splinesteps=40,fill=color,width=6,tags=(tag,))
        # Fine bright ridge gives the cable its round rubber profile.
        rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
        highlight='#'+''.join(f'{min(255,int(v*.65+89)):02x}' for v in rgb)
        self.canvas.create_line(*points,smooth=True,splinesteps=40,fill=highlight,width=2,tags=(tag,))

    def plug(self,x,y,color,tag):
        c=self.canvas
        c.create_oval(x-9,y-9,x+11,y+11,fill='#242b2c',outline='',tags=(tag,))
        c.create_oval(x-9,y-9,x+9,y+9,fill=color,outline='#303b3d',width=2,tags=(tag,))
        c.create_oval(x-5,y-5,x+5,y+5,fill='#434b4e',outline='#d3dad5',tags=(tag,))
        c.create_oval(x-2,y-2,x+2,y+2,fill='#161c1e',outline='',tags=(tag,))

    def jack(self,x,y,color,tag,lit):
        c=self.canvas
        c.create_oval(x-14,y-13,x+15,y+15,fill='#89918e',outline='',tags=(tag,))
        points=[]
        for i in range(6):
            angle=math.pi/3*i
            points.extend((x+13*math.cos(angle),y+13*math.sin(angle)))
        c.create_polygon(*points,fill='#d9ddda',outline='#5b6565',width=2,tags=(tag,))
        c.create_oval(x-9,y-9,x+9,y+9,fill='#222a2c',outline='#f0f2ee',width=2,tags=(tag,))
        c.create_oval(x-5,y-5,x+5,y+5,fill='#080c0e',outline='#555f61',tags=(tag,))
        if lit:self.plug(x,y,color,tag)

    def hit(self,event):
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x-4,y-4,x+4,y+4)):
            for tag in self.canvas.gettags(item):
                if tag.startswith(('source:','dest:','route:')):
                    kind,value=tag.split(':');return kind,int(value)
        return None

    def press(self,event):
        self.canvas.focus_set()
        if self.pending:return
        hit=self.hit(event)
        if not hit:return
        kind,value=hit
        self.drag_moved=False;self.drag_origin=(getattr(event,'x',0),getattr(event,'y',0))
        self.drag_destination=None
        if kind=='source':self.drag_source=value;self.armed_source=value;self.selected_destination=None
        elif kind=='dest' and self.armed_source is not None:
            source=self.armed_source;self.armed_source=None;self.drag_source=None;self.patch(source,value);return
        else:
            self.selected_destination=value;self.armed_source=None;self.drag_source=None
            if kind=='dest':self.drag_destination=value
        self.update_editor();self.draw()

    def motion(self,event):
        source=self.drag_source if self.drag_source is not None else self.armed_source
        dest=getattr(self,'drag_destination',None)
        if (source is None and dest is None) or self.pending:return
        ox,oy=getattr(self,'drag_origin',(event.x,event.y))
        if abs(event.x-ox)+abs(event.y-oy)>4:self.drag_moved=True
        self.canvas.delete('preview')
        points=self.source_points if source is not None else self.destination_points
        anchor=source if source is not None else dest
        if anchor not in points:return
        x,y=points[anchor];xx=self.canvas.canvasx(event.x);yy=self.canvas.canvasy(event.y)
        hit=self.hit(event);target_kind='dest' if source is not None else 'source'
        target=None
        can_patch=self.app.connected and self.editable and self.state.get('status')=='stable' and self.state.get('state_version')==18
        if can_patch and hit and hit[0]==target_kind:
            if target_kind=='dest' and self.routes().get(hit[1]) in SOURCE_LABELS:target=self.destination_points.get(hit[1])
            elif target_kind=='source' and self.routes().get(dest) in SOURCE_LABELS:target=self.source_points.get(hit[1])
        color=self.chosen_color()
        if target and getattr(self,'stereo_mode',None) is not None and self.stereo_mode.get():
            from stereo_routing import plan
            try:pair_changes=plan(source if source is not None else hit[1],hit[1] if source is not None else dest,self.routes())
            except ValueError:target=None
            else:
                for change in pair_changes:
                    a=self.source_points.get(change['source_code']);b=self.destination_points.get(change['destination'])
                    if b:
                        bx,by=b
                        self.canvas.create_oval(bx-19,by-19,bx+19,by+19,outline='#8be9a3',width=3,tags=('preview',))
                    if a and b:self.cable(*a,*b,color,'preview');self.plug(*b,color,'preview')
                return
        if target:
            xx,yy=target
            self.canvas.create_oval(xx-19,yy-19,xx+19,yy+19,outline='#8be9a3',width=3,tags=('preview',))
        self.cable(x,y,xx,yy,color,'preview');self.plug(xx,yy,color,'preview')

    def release(self,event):
        source=self.drag_source;dest=getattr(self,'drag_destination',None)
        self.drag_source=None;self.drag_destination=None;self.canvas.delete('preview')
        if source is None and dest is None:return
        hit=self.hit(event)
        if source is not None and hit and hit[0]=='dest':self.armed_source=None;self.patch(source,hit[1])
        elif dest is not None and hit and hit[0]=='source':self.armed_source=None;self.patch(hit[1],dest)
        elif getattr(self,'drag_moved',False):self.armed_source=None;self.update_editor();self.draw()

    def patch(self,source,destination):
        self.selected_destination=destination
        route=self.selected_route()
        ready=self.app.connected and not self.pending and self.editable and self.state.get('status')=='stable' and self.state.get('state_version')==18
        if not ready or not route or source not in SOURCE_LABELS:
            self.message.config(text='Read stable, mapped device routing before patching this output.');self.update_editor();self.draw();return
        if getattr(self,'stereo_mode',None) is not None and self.stereo_mode.get():
            from stereo_routing import plan
            try:changes=plan(source,destination,self.routes())
            except ValueError as error:self.message.config(text=str(error));self.update_editor();self.draw();return
            if all(r['source_code']==r['expected_source'] for r in changes):
                for r in changes:self.remember_color(r['source_code'],r['destination'],self.chosen_color())
                self.update_editor();self.draw();return
            self.start_stereo(changes);return
        self.stereo_undo=None
        if source==route[1]:
            self.remember_color(source,destination,self.chosen_color());self.update_editor();self.draw();return
        # Keep confirmed cables unchanged until the normal worker confirms and
        # rereads routing. A drag only supplies a target to the existing guard.
        self.send_route(destination,source,route[1])
        if self.pending:self.pending_color=(self.request_id,destination,source,self.chosen_color())
        self.draw()

    def start_batch(self,changes,serial):
        if self.pending or not self.editable or not self.app.connected:return
        if getattr(self,'history_job',None) is None:self.begin_history(changes,'Stereo patch' if getattr(self,'stereo_job',None) is not None else 'Routing preset')
        if getattr(self,'stereo_job',None) is None:self.stereo_undo=None
        super().start_batch(changes,serial)

    def start_stereo(self,changes,undo=False):
        if self.pending or not self.editable or not self.app.connected:return
        self.pending_color=None
        self.stereo_job=dict(changes=changes,confirmed=[],undo=undo,color=self.chosen_color())
        self.stereo_undo=None;self.undo_record=None
        self.start_batch(changes,self.state['connection_serial'])
        self.message.config(text='Checking both L/R destinations before '+('undo…' if undo else 'stereo patch…'))

    def advance_batch(self):
        completed=getattr(self,'history_done',None)
        if not self.batch and completed:
            self.history_done=None
            if getattr(self,'stereo_job',None) is None:
                self.batch=None;self.undo_record=None;self.notice=completed+' complete: all routes confirmed.'
                self.refresh();return
        job=getattr(self,'stereo_job',None)
        if job is not None and not self.batch:
            from stereo_routing import reverse
            self.batch=None;self.undo_record=None
            self.stereo_undo=None if job['undo'] else reverse(job['confirmed'])
            self.stereo_job=None
            self.notice='Stereo '+('undo' if job['undo'] else 'patch')+' complete: both L/R routes confirmed.'
            self.refresh();return
        super().advance_batch()

    def undo_route(self):
        if getattr(self,'history',None) is not None:
            self.replay_history('undo');return
        if getattr(self,'stereo_undo',None):
            if self.undo_button.cget('state') not in ('normal','active'):return
            self.start_stereo(list(self.stereo_undo),undo=True);return
        super().undo_route()

    def chosen_color(self):
        prefs=getattr(self.app,'cable_colors',None)
        return prefs.selected if prefs is not None else DEFAULT

    def route_color(self,source,destination,fallback):
        prefs=getattr(self.app,'cable_colors',None)
        return prefs.get(source,destination,fallback) if prefs is not None else fallback

    def refresh_palette(self):
        for name,color in PALETTE:
            selected=color==self.chosen_color()
            self.color_buttons[color].config(text=('✓ ' if selected else '')+name,relief='sunken' if selected else 'flat',highlightbackground='#ffffff' if selected else BG)
            if selected:self.color_label.config(text=name+' selected')

    def choose_color(self,color):
        self.app.cable_colors.choose(color);self.app.cable_colors.save();self.refresh_palette()

    def remember_color(self,source,destination,color):
        prefs=getattr(self.app,'cable_colors',None)
        if prefs is not None:prefs.assign(source,destination,color);prefs.save()

    def handle(self,event):
        if event['kind']=='input_error' and event.get('channel')!='routing':return
        if event['kind'].startswith('routing_') and event.get('request_id')!=self.request_id:return
        if event['kind'] in ('routing_error','input_error'):
            self.routing_history().clear();self.history_job=None;self.history_done=None
        elif event['kind']=='routing_snapshot':
            self.routing_history().bind(event['state'].get('connection_serial'))
        elif event['kind']=='routing_written':self.confirm_history(event)
        job=getattr(self,'stereo_job',None)
        matching=event.get('request_id')==self.request_id
        if job is not None and matching and event['kind']=='routing_written':
            for change in job['changes']:
                if change['destination']==event['destination'] and change['source_code']==event['actual']:
                    job['confirmed'].append(change)
                    if not job['undo']:self.remember_color(event['actual'],event['destination'],job['color'])
                    break
        if event['kind']=='routing_snapshot' and self.state.get('connection_serial')!=event['state'].get('connection_serial'):
            self.stereo_undo=None
        pending=getattr(self,'pending_color',None)
        if pending and event.get('request_id')==pending[0]:
            if event['kind']=='routing_written':
                if event['destination']==pending[1] and event['actual']==pending[2]:self.remember_color(pending[2],pending[1],pending[3])
                self.pending_color=None
            elif event['kind']=='routing_error':self.pending_color=None
        if event['kind']=='input_error':self.pending_color=None
        super().handle(event)
        if job is not None and ((matching and event['kind']=='routing_error') or event['kind']=='input_error'):
            self.stereo_job=None;self.stereo_undo=None;self.undo_record=None
            self.message.config(text=f"Stereo operation stopped: {len(job['confirmed'])} routes confirmed. Earlier changes may remain; the failed route may be uncertain. Read routing before continuing. "+event.get('message',''))
        if event['kind'] in ('routing_snapshot','routing_error','routing_written','input_error'):
            self.drag_source=None;self.drag_destination=None;self.armed_source=None;self.draw()
        if event['kind'] in ('routing_error','input_error'):
            self.message.config(text=self.message.cget('text')+' Undo/Redo history cleared.')
