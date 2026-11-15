"""Device preset browser, separate from routing-file presets."""
import time
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog


class PresetsWindow:
    def __init__(self, app):
        self.app = app; self.channel = tk.StringVar(value='presets')
        self.closed = False; self.busy = False; self.records = {}; self.status = None
        self.request_id = None; self.serial = None; self.timer = None
        self.poll_request = None
        self.window = app.make_panel(); self.window.title('AF16Rig — Device presets')
        shell = ttk.Frame(self.window, padding=20); shell.pack(fill='both', expand=True)
        ttk.Label(shell, text='PRESETS ON THE 16RIG', font=('DejaVu Sans', 17, 'bold')).pack(anchor='w')
        ttk.Label(shell, text='Read, load and save the rig’s internal presets. These are separate from routing files.').pack(anchor='w', pady=10)
        self.current = ttk.Label(shell, text='Reading current preset…'); self.current.pack(anchor='w', pady=8)
        self.table = ttk.Treeview(shell, columns=('slot', 'name', 'access'), show='headings', height=9, selectmode='browse')
        for key, label, width in [('slot', 'Slot', 70), ('name', 'Preset name', 350), ('access', 'Access', 180)]:
            self.table.heading(key, text=label); self.table.column(key, width=width)
        self.table.pack(fill='x', pady=8); self.table.bind('<<TreeviewSelect>>', lambda e: self.update_buttons())
        row = ttk.Frame(shell); row.pack(fill='x', pady=12)
        self.refresh_button = ttk.Button(row, text='Read presets', command=self.start); self.refresh_button.pack(side='left')
        self.load_button = ttk.Button(row, text='Load selected from rig', command=lambda: self.action('load'), state='disabled'); self.load_button.pack(side='left', padx=12)
        self.save_button = ttk.Button(row, text='Save current settings to selected slot', command=lambda: self.action('save'), state='disabled'); self.save_button.pack(side='left')
        self.rename_button = ttk.Button(row,text='Rename selected preset',command=self.rename,state='disabled'); self.rename_button.pack(side='left',padx=12)
        copy_row=ttk.Frame(shell);copy_row.pack(fill='x',pady=4)
        ttk.Button(copy_row,text='Mixer scene files…',command=app.open_mixer_scenes).pack(side='right')
        self.copy_button=ttk.Button(copy_row,text='Copy selected preset to slot…',command=self.copy_selected,state='disabled');self.copy_button.pack(side='left')
        ttk.Label(shell, text='Load replaces the active device settings. Save overwrites the selected user slot.\nFactory (0) can only be loaded. No save or load runs automatically.', wraplength=950).pack(anchor='w', pady=8)
        self.report_button=ttk.Button(row,text='Save rename report…',command=self.save_rename_report,state='disabled');self.report_button.pack(side='left',padx=8)
        self.message = ttk.Label(shell, text='', wraplength=950); self.message.pack(anchor='w', pady=8)
        app.worker.commands.put(('input_select', None)); self.start()
        self.timer = self.window.after(1000, self.tick)

    def queue(self, command, **data):
        self.busy = True; self.request_id = time.monotonic_ns()
        self.app.worker.commands.put((command, dict(request_id=self.request_id, connection_serial=self.serial, **data)))
        self.update_buttons()

    def update_buttons(self):
        from mixer_view import configure_changed
        if hasattr(self,'report_button'):configure_changed(self.report_button,state='normal' if getattr(self.app,'last_preset_rename_report',None) else 'disabled')
        selected = self.table.selection()
        ready = (not self.busy and self.app.connected and self.app.info.get('state_version') == 18
                 and self.serial == self.app.name_cache.serial and self.status is not None and len(self.records) == 9)
        configure_changed(self.refresh_button,state='disabled' if self.busy else 'normal')
        configure_changed(self.load_button,state='normal' if ready and selected else 'disabled')
        configure_changed(self.save_button,state='normal' if ready and selected and int(selected[0]) != 0 else 'disabled')
        configure_changed(self.rename_button,state='normal' if ready and selected and int(selected[0]) != 0 else 'disabled')
        if hasattr(self,'copy_button'):configure_changed(self.copy_button,state='normal' if ready and selected else 'disabled')

    def copy_selected(self):
        selected=self.table.selection()
        if (self.closed or self.busy or not selected or self.status is None or len(self.records)!=9
                or not self.app.connected or self.serial!=self.app.name_cache.serial):return
        source=int(selected[0]);serial=self.serial;status=dict(self.status)
        names={slot:r['name'] for slot,r in self.records.items()}
        self.busy=True;self.update_buttons()
        try:
            destination=simpledialog.askinteger('Copy device preset',
                f'Copy stored settings from {source} — {names[source] or "Unnamed"}.\nDestination user slot (1–8):',
                minvalue=1,maxvalue=8,parent=self.window)
            if self.closed or destination is None:return
            if type(destination) is not int or not 1<=destination<=8 or destination==source:
                self.message.config(text='Choose a different user slot from 1–8.');return
            if not self.app.connected or serial!=self.serial or serial!=self.app.name_cache.serial:
                self.message.config(text='Connection changed. Read presets again.');return
            confirmed=messagebox.askyesno('Copy and overwrite device preset',
                f'Copy {source} — {names[source] or "Unnamed"} to {destination} — {names[destination] or "Unnamed"}?\n\n'
                'This loads the stored source, replacing the active mix and any unsaved changes, then overwrites the destination.\n'
                'The destination keeps its existing name and becomes the active preset. This cannot be undone automatically.',parent=self.window)
            if self.closed or not confirmed:return
            if not self.app.connected or serial!=self.serial or serial!=self.app.name_cache.serial:
                self.message.config(text='Connection changed. Read presets again.');return
        finally:
            self.busy=False
            if not self.closed:self.update_buttons()
        self.message.config(text=f'Copying slot {source} to {destination}: loading stored source, then saving destination…')
        self.queue('preset_copy',source=source,destination=destination,source_name=names[source],
            destination_name=names[destination],expected_status=status)

    def rename(self):
        selected=self.table.selection()
        if self.busy or not selected or self.status is None or len(self.records)!=9 or not self.app.connected:return
        if self.serial!=self.app.name_cache.serial:
            self.message.config(text='Connection changed. Read presets again.');return
        slot=int(selected[0])
        if slot==0:return
        expected=self.records[slot]['name']
        self.busy=True;self.update_buttons()
        name=simpledialog.askstring('Rename device preset',f'Name for slot {slot} (maximum 12 UTF-8 bytes):',initialvalue=expected,parent=self.window)
        self.busy=False
        if self.closed:return
        if name is None:self.update_buttons();return
        if not self.app.connected or self.serial!=self.app.name_cache.serial:
            self.status=None;self.message.config(text='Connection changed. Read presets again.');self.update_buttons();return
        from device_presets import encode_preset_name
        try:encode_preset_name(name)
        except ValueError as error:self.message.config(text=str(error));self.update_buttons();return
        self.message.config(text=f'Renaming slot {slot} and checking device readback…')
        self.queue('preset_rename',slot=slot,name=name,expected_name=expected)

    def save_rename_report(self):
        report=getattr(self.app,'last_preset_rename_report',None)
        if not report:return
        content=json.dumps(dict(report,current_records=self.records,current_status=self.status),indent=2,ensure_ascii=False)+'\n'
        path=filedialog.asksaveasfilename(parent=self.window,title='Save preset rename report',initialfile='AF16Rig-preset-rename-report.json',defaultextension='.json',filetypes=[('JSON report','*.json')])
        if not path:return
        try:Path(path).write_text(content,encoding='utf-8')
        except OSError as error:self.message.config(text=str(error));return
        self.message.config(text='Preset rename report saved. It contains the exact request and raw device replies.')

    def start(self):
        if self.busy: return
        if not self.app.connected:
            self.message.config(text='Connect the rig, then select Read presets.'); return
        self.serial = self.app.name_cache.serial; self.records = {}; self.status = None
        for item in self.table.get_children(): self.table.delete(item)
        self.message.config(text='Reading device slots…')
        self.queue('preset_read', slot=0)

    def tick(self):
        if self.closed: return
        if not self.busy and getattr(self,'poll_request',None) is None and self.status is not None and self.app.connected and self.serial == self.app.name_cache.serial:
            self.poll_request = time.monotonic_ns()
            self.app.worker.commands.put(('preset_status',dict(request_id=self.poll_request,connection_serial=self.serial)))
        self.timer = self.window.after(1000, self.tick)

    def set_status(self, status):
        from mixer_view import configure_changed
        self.status = status
        slot = status['current']; name = self.records.get(slot, {}).get('name', '')
        configure_changed(self.current,text=f'Current: {slot} — {name or "Unnamed"}  ·  '+('Unsaved changes' if status['changed'] else 'No unsaved changes reported'))

    def action(self, action):
        selected = self.table.selection()
        if self.busy or not selected or self.status is None or len(self.records) != 9 or not self.app.connected: return
        if self.serial != self.app.name_cache.serial: self.message.config(text='Connection changed. Read presets again.'); return
        slot = int(selected[0])
        if action == 'save' and slot == 0: return
        record = self.records[slot]; expected_status = dict(self.status)
        label = f'{slot} — {record["name"] or "Unnamed"}'
        text = (f'Overwrite device preset {label} with the rig’s current settings?' if action == 'save'
                else f'Load device preset {label}?\nThis replaces the active settings, including unsaved changes.')
        # Prevent periodic reads while the modal confirmation runs its event loop.
        self.busy = True; self.update_buttons()
        confirmed = messagebox.askyesno('Save device preset' if action == 'save' else 'Load device preset', text, parent=self.window)
        self.busy = False
        if self.closed: return
        if not confirmed: self.update_buttons(); return
        if not self.app.connected or self.serial != self.app.name_cache.serial:
            self.status = None; self.message.config(text='Connection changed. Read presets again.'); self.update_buttons(); return
        self.message.config(text=f'{action.capitalize()} slot {slot}: waiting for device readback…')
        self.queue('preset_action', action=action, slot=slot, expected_name=record['name'], expected_status=expected_status)

    def handle(self, event):
        kind = event['kind']
        if kind in ('preset_status','preset_error') and event.get('request_id') == getattr(self,'poll_request',None) and getattr(self,'poll_request',None) is not None:
            self.poll_request = None
            if self.busy or event.get('connection_serial') != self.serial or self.serial != self.app.name_cache.serial:return
            if kind == 'preset_status':self.set_status(event['status'])
            else:
                self.status=None;self.current.config(text='Current preset: refresh required');self.message.config(text=event['message'])
            self.update_buttons();return
        if kind == 'input_error' and event.get('channel') == 'presets':
            self.poll_request = None
            self.busy = False; self.status = None; self.current.config(text='Current preset: unavailable'); self.message.config(text=event['message']); self.update_buttons(); return
        if kind not in ('preset_snapshot', 'preset_status', 'preset_done', 'preset_renamed', 'preset_error') or event.get('request_id') != self.request_id: return
        if event.get('rename_report'):
            self.app.last_preset_rename_report=event['rename_report']
            if hasattr(self,'report_button'):self.report_button.config(state='normal')
        self.busy = False
        if kind == 'preset_error':
            self.status = None; self.current.config(text='Current preset: refresh required'); self.message.config(text=event['message']); self.update_buttons(); return
        if event.get('connection_serial') != self.serial or self.serial != self.app.name_cache.serial:
            self.status = None; self.message.config(text='Connection changed. Read presets again.'); self.update_buttons(); return
        if kind == 'preset_snapshot':
            record = event['record']; slot = record['slot']; self.records[slot] = record
            self.table.insert('', 'end', iid=str(slot), values=(slot, record['name'] or 'Unnamed', 'Load only' if slot == 0 else 'Load / Save'))
            self.set_status(event['status'])
            if slot < 8: self.queue('preset_read', slot=slot+1); return
            self.table.selection_set(str(self.status['current']))
            self.message.config(text='Demo slots only; no hardware accessed.' if self.app.demo else 'Device slots read. Select a slot to load or save.')
        elif kind == 'preset_status': self.set_status(event['status'])
        elif kind == 'preset_renamed':
            result=event['result'];record=result['record'];slot=record['slot']
            self.records[slot]=record
            self.table.item(str(slot),values=(slot,record['name'] or 'Unnamed','Load / Save'))
            self.set_status(event['status'])
            self.message.config(text=('Demo only: ' if result['demo'] else '')+f'Slot {slot} name confirmed: {record["name"] or "Unnamed"}.')
        elif kind == 'preset_done':
            result = event['result']; self.set_status(result['status'])
            if result['action']=='copy':
                self.message.config(text=('Demo only: ' if result['demo'] else '')+
                    f'Slot {result["source"]} copied to {result["slot"]}. Destination name retained. '
                    'Load/save current-slot and clean-state readbacks confirmed; mixer and names are refreshing.')
            else:
                self.message.config(text=('Demo only: ' if result['demo'] else '') + f'Slot {result["slot"]} {"saved" if result["action"] == "save" else "loaded"}. Current slot and clean state confirmed by readback.' + (' Mixer and channel names are refreshing.' if result['action'] == 'load' else ''))
        self.update_buttons()

    def close(self):
        self.closed = True
        if self.timer is not None: self.window.after_cancel(self.timer)
        self.app.worker.commands.put(('input_select', None)); self.app.input_window = None; self.window.destroy()
