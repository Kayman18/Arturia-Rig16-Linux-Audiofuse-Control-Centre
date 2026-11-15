"""On-demand routing inspector, using the application's serialized USB worker."""
import json
import time
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

from routing_capture import compare
from routing_labels import describe_route, SOURCE_LABELS, DESTINATION_LABELS


class RoutingWindow:
    def __init__(self, app):
        self.app = app
        self.state = {}
        self.previous = None
        self.pending = False
        self.request_id = None
        self.undo_record = None
        self.editable = False
        self.batch = None
        self.batch_done = 0
        self.notice = ""
        self.channel = tk.StringVar(value='routing')
        self.window = app.make_panel()
        self.window.title('AF16Rig — Routing inspection')
        self.window.geometry('1040x620')
        self.window.minsize(680, 420)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Routing inspection', font=('DejaVu Sans', 17, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Select one output row to change its source · Analog destinations use AFCC native numbering',
                  wraplength=700).pack(anchor='w', pady=(6, 12))
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('field', 'slot', 'value', 'hex', 'description', 'previous'),
                                 show='headings', selectmode='browse')
        for name, title, width in [('field', 'Register', 230), ('slot', 'Index', 65),
                                   ('value', 'Code', 90), ('hex', 'Hex', 90),
                                   ('description', 'Recovered routing labels', 300),
                                   ('previous', 'Previous code', 120)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=55)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', lambda event:self.update_editor())
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        editor = ttk.Frame(frame)
        editor.pack(fill='x',pady=(10,0))
        self.route_label = ttk.Label(editor,text='Select an output_source row')
        self.route_label.pack(side='left',padx=(0,12))
        self.source_choices={f'{name} ({code})':code for code,name in SOURCE_LABELS.items()}
        self.source_choice=tk.StringVar()
        self.source_menu=ttk.Combobox(editor,textvariable=self.source_choice,values=list(self.source_choices),state='disabled',width=25)
        self.source_menu.pack(side='left',padx=(0,12))
        self.source_menu.bind('<<ComboboxSelected>>',lambda event:self.update_editor(keep_choice=True))
        self.apply_button=ttk.Button(editor,text='Apply source',command=self.apply_route,state='disabled')
        self.apply_button.pack(side='left')
        self.undo_button=ttk.Button(editor,text='Undo last route',command=self.undo_route,state='disabled')
        self.undo_button.pack(side='left',padx=10)
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        self.refresh_button = ttk.Button(actions, text='Read routing', command=self.refresh)
        self.refresh_button.pack(side='left')
        self.save_button = ttk.Button(actions, text='Save routing JSON', command=self.save, state='disabled')
        self.save_button.pack(side='left', padx=10)
        self.preset_save_button=ttk.Button(actions,text='Save routing preset',command=self.save_preset,state='disabled')
        self.preset_save_button.pack(side='left',padx=8)
        self.preset_load_button=ttk.Button(actions,text='Load routing preset…',command=self.load_preset,state='disabled')
        self.preset_load_button.pack(side='left',padx=8)
        self.message = ttk.Label(frame, text='', wraplength=700)
        self.message.pack(anchor='w', pady=(10, 0))
        app.worker.commands.put(('input_select', None))
        self.refresh()

    def selected_route(self):
        selected=self.tree.selection()
        if not selected:return None
        values=self.tree.item(selected[0],'values')
        if not values or values[0]!='output_source':return None
        try:
            index=int(values[1])
            source=self.state['reads']['second']['values'][f'output_source[{index}]']
        except (KeyError,TypeError,ValueError):return None
        if index not in DESTINATION_LABELS or source not in SOURCE_LABELS:return None
        return index,source

    def update_editor(self, keep_choice=False):
        route=self.selected_route()
        ready=(self.app.connected and not self.pending and self.editable and
               self.state.get('status')=='stable' and self.state.get('state_version')==18)
        self.source_menu.config(state='readonly' if ready and route else 'disabled')
        if route:
            index,current=route
            self.route_label.config(text=DESTINATION_LABELS[index]+' ← '+SOURCE_LABELS[current])
            if not keep_choice:self.source_choice.set(f'{SOURCE_LABELS[current]} ({current})')
        else:
            self.route_label.config(text='Select a mapped output_source row')
            self.source_choice.set('')
        target=self.source_choices.get(self.source_choice.get())
        self.apply_button.config(state='normal' if ready and route and target is not None and target!=route[1] else 'disabled')
        self.undo_button.config(state='normal' if ready and self.undo_record else 'disabled')
        self.preset_save_button.config(state='normal' if ready else 'disabled')
        self.preset_load_button.config(state='normal' if ready else 'disabled')

    def save_preset(self):
        if self.pending or not self.editable:return
        from routing_presets import make_preset
        try:
            preset=make_preset(self.state)
            path=filedialog.asksaveasfilename(title='Save routing preset',initialfile='AF16Rig-routing-preset.json',defaultextension='.json',filetypes=[('Routing preset','*.json')])
            if path:
                Path(path).write_text(json.dumps(preset,indent=2)+'\n')
                self.message.config(text=f"Saved {len(preset['routes'])} known routes. Unmapped routes were omitted.")
        except (ValueError,OSError,KeyError) as error:self.message.config(text=str(error))

    def load_preset(self):
        if self.pending or not self.editable:return
        from routing_presets import preview
        path=filedialog.askopenfilename(title='Load routing preset',filetypes=[('Routing preset','*.json')])
        if not path:return
        try:
            if Path(path).stat().st_size>131072:raise ValueError('Routing preset is too large')
            changes=preview(json.loads(Path(path).read_text()),self.state)
        except (ValueError,OSError,KeyError,TypeError) as error:
            self.message.config(text=str(error));return
        if not changes:
            self.message.config(text='All routes in this preset already match. No changes needed.');return
        serial=self.state['connection_serial']
        dialog=tk.Toplevel(self.window);dialog.title('Preview routing preset');dialog.geometry('760x480')
        dialog.transient(self.app.root)
        shell=ttk.Frame(dialog,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=f'{len(changes)} routes will change',font=('DejaVu Sans',14,'bold')).pack(anchor='w')
        table=ttk.Treeview(shell,columns=('destination','before','after'),show='headings')
        for key,title in [('destination','Destination'),('before','Current source'),('after','Preset source')]:
            table.heading(key,text=title);table.column(key,width=210)
        table.pack(fill='both',expand=True,pady=12)
        scroll=ttk.Scrollbar(shell,orient='vertical',command=table.yview);scroll.pack(side='right',fill='y');table.configure(yscrollcommand=scroll.set)
        for route in changes:
            table.insert('','end',values=(DESTINATION_LABELS[route['destination']],SOURCE_LABELS[route['expected_source']],SOURCE_LABELS[route['source_code']]))
        ttk.Label(shell,text='Unlisted routes stay unchanged. Stops at the first failure; earlier changes remain applied.').pack(anchor='w')
        ttk.Label(shell,text='Save your current routing preset first if you want to restore the full routing later.').pack(anchor='w')
        actions=ttk.Frame(shell);actions.pack(fill='x',pady=(12,0))
        def apply():
            dialog.destroy();self.start_batch(changes,serial)
        ttk.Button(actions,text='Cancel',command=dialog.destroy).pack(side='right')
        ttk.Button(actions,text='Apply these changes',command=apply).pack(side='right',padx=12)
        dialog.grab_set()

    def start_batch(self, changes, serial):
        if self.pending or not self.editable or not self.app.connected:return
        self.batch=list(changes);self.batch_done=0;self.notice=''
        self.pending=True;self.request_id=time.monotonic_ns()
        self.update_editor();self.refresh_button.config(state='disabled');self.save_button.config(state='disabled')
        self.message.config(text='Checking all routes against the preview…')
        self.app.worker.commands.put(('routing_preflight',dict(request_id=self.request_id,connection_serial=serial,changes=changes)))

    def advance_batch(self):
        if self.batch:
            route=self.batch.pop(0)
            self.send_route(route['destination'],route['source_code'],route['expected_source'])
        else:
            self.batch=None
            self.notice=f'Preset complete: {self.batch_done} route changes confirmed. Undo last route affects only the last destination.'
            self.refresh()

    def send_route(self, destination, target, expected, undo=False):
        if self.pending or not self.editable or not self.app.connected:return
        self.pending=True
        self.request_id=time.monotonic_ns()
        self.refresh_button.config(state='disabled');self.save_button.config(state='disabled')
        self.update_editor(keep_choice=True)
        self.message.config(text='Applying '+DESTINATION_LABELS[destination]+' ← '+SOURCE_LABELS[target]+'…')
        self.app.worker.commands.put(('routing_set',dict(request_id=self.request_id,
            connection_serial=self.state['connection_serial'],destination=destination,
            source_code=target,expected_source=expected,undo=undo)))

    def apply_route(self):
        if self.apply_button.cget('state') not in ('normal','active'):return
        route=self.selected_route()
        target=self.source_choices.get(self.source_choice.get())
        if route and target is not None:self.send_route(route[0],target,route[1])

    def undo_route(self):
        if self.undo_button.cget('state') not in ('normal','active') or not self.undo_record:return
        index,old,new=self.undo_record
        self.send_route(index,old,new,undo=True)

    def refresh(self):
        if self.pending:
            return
        if not self.app.connected:
            self.message.config(text='Connect the AF16Rig, then choose Read routing.')
            return
        self.pending = True
        self.editable = False
        self.update_editor()
        self.request_id = time.monotonic_ns()
        self.refresh_button.config(state='disabled')
        self.save_button.config(state='disabled')
        self.message.config(text='Reading routing…')
        self.app.worker.commands.put(('routing_capture', self.request_id))

    def connection_changed(self):
        self.pending=False;self.request_id=None;self.editable=False
        self.batch=None;self.batch_done=0;self.undo_record=None;self.previous=None
        self.state={}
        if hasattr(self,'routing_history'):
            self.routing_history().clear();self.history_job=None;self.history_done=None
            self.pending_color=None;self.stereo_job=None;self.stereo_undo=None
            self.selected_destination=None;self.drag_source=None;self.drag_destination=None;self.armed_source=None
        self.update_editor()
        if hasattr(self,'draw'):self.draw()
        if self.app.connected:self.refresh()

    def handle(self, event):
        kind = event['kind']
        if kind == 'input_error' and event.get('channel') == 'routing':
            self.pending = False
            if self.batch is not None:
                self.notice=f'Preset stopped: {self.batch_done} changes confirmed; in-flight result may be unknown.'
                self.batch=None
            self.editable=False
            self.update_editor()
            self.refresh_button.config(state='normal')
            self.message.config(text=event.get('message', 'Disconnected') + ' · displayed values are from the last capture.')
            return
        if kind not in ('routing_snapshot', 'routing_error', 'routing_written', 'routing_ready') or event.get('request_id') != self.request_id:
            return
        self.pending = False
        self.refresh_button.config(state='normal')
        if kind == 'routing_ready':
            self.advance_batch()
            return
        if kind == 'routing_written':
            self.undo_record=None if event['undo'] else (event['destination'],event['previous'],event['actual'])
            if self.batch is not None:
                self.batch_done+=1
                self.advance_batch()
            else:self.refresh()
            return
        if kind == 'routing_error':
            if self.batch is not None:
                self.notice=f'Preset stopped: {self.batch_done} changes confirmed; failed route needs readback. Remaining routes were not sent.'
                self.batch=None
            self.editable=False
            self.update_editor()
            self.message.config(text=event['message'] + ' · '+self.notice+' · Read routing before continuing.')
            return
        current = event['state']
        if self.state.get('connection_serial') != current.get('connection_serial'):self.undo_record=None
        previous_values = {}
        if self.previous:
            try:
                delta = compare(self.previous, current)
                previous_values = {key: change['before'] for key, change in delta['changes'].items()}
            except ValueError:
                pass
        self.state = current
        self.editable=current.get('status')=='stable' and 'connection_serial' in current
        self.previous = current if current['status'] == 'stable' else None
        for row in self.tree.get_children():
            self.tree.delete(row)
        snapshot = current['reads']['second']
        for key, value in snapshot['values'].items():
            field, index = key[:-1].split('[')
            self.tree.insert('', 'end', values=(field, index, value, f'0x{value:04X}', describe_route(field, int(index), value), previous_values.get(key, '')))
        for key, error in snapshot['errors'].items():
            field, index = key[:-1].split('[')
            self.tree.insert('', 'end', values=(field, index, 'Read error', '', error, ''))
        self.update_editor()
        self.save_button.config(state='normal')
        demo = 'Demo values · ' if self.app.demo else ''
        self.message.config(text=f"{demo}{current['status']} · {len(snapshot['values'])} values · "
                                 f"{len(previous_values)} changes from the previous comparable capture · {current['utc']} · {self.notice}")

    def save(self):
        if self.pending or not self.state:
            return
        path = filedialog.asksaveasfilename(title='Save routing capture',
                                           initialfile='AF16Rig-routing.json',
                                           defaultextension='.json',
                                           filetypes=[('JSON report', '*.json')])
        if path:
            report = dict(self.state, demo=self.app.demo)
            try:
                Path(path).write_text(json.dumps(report, indent=2) + '\n')
                self.message.config(text='Routing capture saved.')
            except OSError as error:
                self.message.config(text='Could not save capture: ' + str(error))

    def close(self):
        if self.batch is not None:
            self.batch=None
            self.app.message.config(text=f'Preset canceled on page change after {self.batch_done} confirmed changes; an in-flight change may still finish.')
        self.app.worker.commands.put(('input_select', None))
        self.app.input_window = None
        self.window.destroy()
