"""Incremental MIDI assignment capture and guarded existing-assignment edits."""
import json
import uuid
from datetime import datetime,timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from midi_config import FIELDS,editable,STRIP_CONTROLS,MESSAGE_TYPES

class MidiWindow:
    def __init__(self,app):
        self.app=app;self.channel=tk.StringVar(value='midi');self.closed=False
        self.pending_edit=None;self.restore_dialog=None
        self.records=[];self.request=None;self.position=0;self.serial=None;self.error=None
        self.window=app.make_panel();self.window.title('AF16Rig — MIDI controller assignments')
        shell=ttk.Frame(self.window,padding=16);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='MIDI CONTROLLER ASSIGNMENTS',font=('DejaVu Sans',17,'bold')).pack(anchor='w')
        ttk.Label(shell,text='Saved controller assignments for eight strips, master controls and bank switching.',wraplength=950).pack(anchor='w',pady=6)
        self.summary=ttk.Label(shell,text='Waiting for device');self.summary.pack(anchor='w',pady=6)
        bank=ttk.Frame(shell);bank.pack(fill='x',pady=6)
        ttk.Label(bank,text='MIDI channels per bank').pack(side='left')
        self.bank_size=ttk.Combobox(bank,values=tuple(str(i) for i in range(1,9)),width=4,state='disabled');self.bank_size.pack(side='left',padx=8)
        self.bank_apply=ttk.Button(bank,text='Apply bank size',command=self.apply_bank_size,state='disabled');self.bank_apply.pack(side='left')
        ttk.Label(bank,text='Controller strips per bank · assignments are retained').pack(side='left',padx=12)
        box=ttk.Frame(shell);box.pack(fill='both',expand=True)
        columns=('strip','control','channel','type','number','raw','status')
        self.table=ttk.Treeview(box,columns=columns,show='headings',height=20)
        for col,title,width in zip(columns,('Strip','Control','MIDI channel','Type','Number / value','Raw word','Readback'),(70,190,110,90,120,100,130)):
            self.table.heading(col,text=title);self.table.column(col,width=width,minwidth=50)
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        ttk.Label(shell,text='Select an assignment to edit its MIDI channel, CC/Note/Off type and number. Off disables the assignment. Use Ports/sync for MIDI mode, clock and output routing. MIDI learn is not enabled.',wraplength=1050).pack(anchor='w',pady=8)
        edit=ttk.Frame(shell);edit.pack(fill='x',pady=6)
        self.edit_label=ttk.Label(edit,text='Select a captured assignment');self.edit_label.pack(side='left',padx=(0,12))
        ttk.Label(edit,text='MIDI channel').pack(side='left')
        self.edit_channel=tk.StringVar(value='1')
        self.channel_entry=ttk.Spinbox(edit,from_=1,to=16,width=4,textvariable=self.edit_channel,state='disabled');self.channel_entry.pack(side='left',padx=6)
        ttk.Label(edit,text='Type').pack(side='left')
        self.type_entry=ttk.Combobox(edit,values=MESSAGE_TYPES,state='disabled',width=7);self.type_entry.pack(side='left',padx=6)
        ttk.Label(edit,text='CC / Note number').pack(side='left')
        self.edit_number=tk.StringVar(value='0')
        self.number_entry=ttk.Spinbox(edit,from_=0,to=127,width=5,textvariable=self.edit_number,state='disabled');self.number_entry.pack(side='left',padx=6)
        self.apply_button=ttk.Button(edit,text='Apply assignment',command=self.apply_edit,state='disabled');self.apply_button.pack(side='left',padx=8)
        self.table.bind('<<TreeviewSelect>>',lambda event:self.select_entry())
        batch=ttk.LabelFrame(shell,text='Batch assignments · strips 1–8',padding=6);batch.pack(fill='x',pady=6)
        self.batch_control=tk.StringVar(value='Fader');self.batch_channel=tk.StringVar(value='1');self.batch_first=tk.StringVar(value='0')
        self.batch_control_widget=ttk.Combobox(batch,textvariable=self.batch_control,values=('All controls (64)',)+STRIP_CONTROLS,width=18,state='disabled');self.batch_control_widget.pack(side='left')
        self.batch_control_widget.bind('<<ComboboxSelected>>',lambda event:self.batch_scope_changed())
        ttk.Label(batch,text='MIDI channel').pack(side='left',padx=(12,4))
        self.batch_channel_widget=ttk.Spinbox(batch,textvariable=self.batch_channel,from_=1,to=16,width=4,state='disabled');self.batch_channel_widget.pack(side='left')
        ttk.Label(batch,text='First CC / Note number').pack(side='left',padx=(12,4))
        self.batch_first_widget=ttk.Spinbox(batch,textvariable=self.batch_first,from_=0,to=120,width=5,state='disabled');self.batch_first_widget.pack(side='left')
        self.batch_button=ttk.Button(batch,text='Preview assignments…',command=self.preview_batch,state='disabled');self.batch_button.pack(side='left',padx=12)
        row=ttk.Frame(shell);row.pack(fill='x')
        self.refresh_button=ttk.Button(row,text='Refresh assignments',command=self.refresh);self.refresh_button.pack(side='left')
        self.save_button=ttk.Button(row,text='Save assignments report…',command=self.save,state='disabled');self.save_button.pack(side='left',padx=8)
        self.backup_button=ttk.Button(row,text='Save MIDI backup…',command=self.save_backup,state='disabled');self.backup_button.pack(side='left',padx=8)
        self.restore_button=ttk.Button(row,text='Restore MIDI backup…',command=self.open_restore,state='disabled');self.restore_button.pack(side='left')
        self.ports_button=ttk.Button(row,text='Ports / sync…',command=self.open_ports,state='disabled');self.ports_button.pack(side='left',padx=8)
        self.message=ttk.Label(shell,text='');self.message.pack(anchor='w',pady=8)
        app.worker.commands.put(('input_select',None));self.refresh()
    def refresh(self):
        if self.closed or getattr(self,'pending_edit',None) or getattr(self,'restore_dialog',None):return
        self.records=[];self.position=0;self.error=None;self.request=None
        self.update_editor()
        self.serial=self.app.name_cache.serial;self.started_utc=datetime.now(timezone.utc).isoformat()
        for row in self.table.get_children():self.table.delete(row)
        self.save_button.config(state='disabled');self.refresh_button.config(state='normal')
        if not self.app.connected or self.serial is None:
            self.summary.config(text='Device disconnected');return
        self.refresh_button.config(state='disabled');self.message.config(text='Reading in small batches; normal polling continues.')
        self.next_entry()
    def next_entry(self):
        if self.closed or not self.app.connected or self.serial!=self.app.name_cache.serial:return
        if self.position==len(FIELDS):
            self.request=None;self.refresh_button.config(state='normal')
            unstable=sum(not r['stable'] for r in self.records)
            self.summary.config(text=f'{"DEMO · " if self.app.demo else ""}Read {len(FIELDS)} entries · {unstable} changed during read')
            self.message.config(text='Capture complete. Select an assignment to edit its channel, type and number. Batch templates preserve message types.')
            if hasattr(self,'bank_size'):
                self.bank_size.set(str(self.records[0]['raw']))
            self.select_entry()
            return
        parameter,index=FIELDS[self.position];self.request=uuid.uuid4().hex
        self.summary.config(text=f'Reading MIDI assignments {self.position+1}/{len(FIELDS)}…')
        self.app.worker.commands.put(('midi_read',dict(parameter=parameter,index=index,request_id=self.request,connection_serial=self.serial)))
    def connection_changed(self):
        dialog=getattr(self,'restore_dialog',None)
        if dialog:dialog.close(refresh=False)
        self.pending_edit=None;self.refresh()
    def selected_position(self):
        try:
            selected=self.table.selection()
            position=int(selected[0]) if selected else -1
            return position if 0<=position<len(self.records) else None
        except (TypeError,ValueError,IndexError):return None
    def update_editor(self):
        if not hasattr(self,'apply_button'):return
        position=self.selected_position()
        ready=(self.app.connected and self.serial==self.app.name_cache.serial
            and self.request is None and not getattr(self,'pending_edit',None) and not getattr(self,'restore_dialog',None)
            and position is not None and editable(self.records[position]))
        for widget in (self.apply_button,self.channel_entry,self.number_entry):widget.config(state='normal' if ready else 'disabled')
        if hasattr(self,'type_entry'):self.type_entry.config(state='readonly' if ready else 'disabled')
        if hasattr(self,'ports_button'):
            ports_ready=(not self.closed and self.app.connected and self.serial==self.app.name_cache.serial and self.request is None and not getattr(self,'pending_edit',None) and not getattr(self,'restore_dialog',None))
            self.ports_button.config(state='normal' if ports_ready else 'disabled')
        if hasattr(self,'bank_apply'):
            ready_bank=self.bank_ready()
            self.bank_size.config(state='readonly' if ready_bank else 'disabled')
            self.bank_apply.config(state='normal' if ready_bank else 'disabled')
        if hasattr(self,'backup_button'):
            state='normal' if self.backup_ready() else 'disabled'
            self.backup_button.config(state=state);self.restore_button.config(state=state)
            if hasattr(self,'batch_button'):
                self.batch_button.config(state=state)
                self.batch_channel_widget.config(state=state);self.batch_first_widget.config(state=state)
                self.batch_control_widget.config(state='readonly' if state=='normal' else 'disabled')
    def select_entry(self):
        if not hasattr(self,'apply_button'):return
        position=self.selected_position()
        if position is not None:
            r=self.records[position]
            suffix=' · read-only' if r['parameter']<20 else ' · refresh required' if not r['stable'] else ' · encoding not supported' if not editable(r) else ''
            self.edit_label.config(text=(f"Strip {r['strip']} · " if r.get('strip') else '')+r['control']+suffix)
            if 'channel_code' in r:
                self.edit_channel.set(str(r['channel_code']+1));self.edit_number.set(str(r['number_code']))
                if hasattr(self,'type_entry'):self.type_entry.set(MESSAGE_TYPES[r['type_code']] if r['type_code']<3 else 'Unknown')
            else:self.edit_channel.set('');self.edit_number.set('')
        else:self.edit_label.config(text='Select a captured assignment')
        self.update_editor()
    def bank_ready(self):
        return (not self.closed and self.app.connected and self.serial==self.app.name_cache.serial
            and self.request is None and not getattr(self,'pending_edit',None)
            and not getattr(self,'restore_dialog',None) and len(self.records)==len(FIELDS)
            and self.records[0].get('parameter')==18 and self.records[0].get('index')==0
            and self.records[0].get('stable') is True
            and type(self.records[0].get('raw')) is int and 1<=self.records[0]['raw']<=8)
    def apply_bank_size(self):
        if not self.bank_ready():return
        try:target=int(self.bank_size.get())
        except ValueError:return
        if not 1<=target<=8:return
        expected=self.records[0]['raw']
        if target==expected:
            self.message.config(text='Bank size unchanged.');return
        request=uuid.uuid4().hex
        self.pending_edit=dict(request_id=request,position=0,parameter=18,index=0,bank_size=True)
        self.refresh_button.config(state='disabled');self.save_button.config(state='disabled');self.update_editor()
        self.message.config(text='Applying MIDI bank size · checking device state…')
        self.app.worker.commands.put(('midi_bank_size',dict(request_id=request,connection_serial=self.serial,target=target,expected=expected)))
    def apply_edit(self):
        position=self.selected_position()
        if (self.closed or getattr(self,'pending_edit',None) or getattr(self,'restore_dialog',None) or self.request is not None
                or not self.app.connected or self.serial!=self.app.name_cache.serial or position is None):return
        r=self.records[position]
        if not editable(r):return
        try:
            channel=int(self.edit_channel.get());number=int(self.edit_number.get())
            if not 1<=channel<=16 or not 0<=number<=127:raise ValueError()
        except ValueError:
            self.message.config(text='Enter a MIDI channel from 1 to 16 and a number from 0 to 127.');return
        message_type=self.type_entry.current() if hasattr(self,'type_entry') else r['type_code']
        if message_type not in range(3):return
        if channel==r['channel_code']+1 and number==r['number_code'] and message_type==r['type_code']:
            self.message.config(text='Assignment unchanged.');return
        request=uuid.uuid4().hex
        self.pending_edit=dict(request_id=request,position=position,parameter=r['parameter'],index=r['index'])
        self.refresh_button.config(state='disabled');self.save_button.config(state='disabled');self.update_editor()
        self.message.config(text='Applying assignment · checking current device state…')
        self.app.worker.commands.put(('midi_remap',dict(request_id=request,connection_serial=self.serial,
            parameter=r['parameter'],index=r['index'],channel=channel,number=number,expected=r['raw'],message_type=message_type)))
    @staticmethod
    def row_values(r):
        return (r.get('strip') or '—',r['control'],r['channel_code']+1 if 'channel_code' in r else '—',
                MESSAGE_TYPES[r['type_code']] if r.get('type_code') in range(3) else ('Unknown' if 'type_code' in r else '—'),r.get('number_code',r.get('value','—')),f"0x{r['raw']:04X}",
                'Matching reads' if r['stable'] else 'Refresh required')

    def handle(self,event):
        if self.closed:return
        if event['kind']=='input_error' and event.get('channel')=='midi':
            self.connection_changed();return
        dialog=getattr(self,'restore_dialog',None)
        if dialog and dialog.handle(event):return
        pending=getattr(self,'pending_edit',None)
        if (pending and event['kind'] in ('midi_written','midi_error')
                and event.get('request_id')==pending['request_id']
                and event.get('connection_serial')==self.serial==self.app.name_cache.serial):
            position=pending['position'];self.pending_edit=None;self.refresh_button.config(state='normal');self.save_button.config(state='normal')
            if event['kind']=='midi_written':
                self.records[position]=event['record'];self.message.config(text='Assignment confirmed by device readback.')
            else:
                self.records[position]=dict(self.records[position],stable=False)
                self.error=event['message'];self.message.config(text=self.error+' · Refresh before editing this assignment again.')
            self.table.item(str(position),values=self.row_values(self.records[position]))
            if pending.get('bank_size') and event['kind']=='midi_written':
                self.refresh();return
            self.select_entry();return
        if event['kind'] not in ('midi_snapshot','midi_error'):return
        if event.get('request_id')!=self.request or event.get('connection_serial')!=self.serial or self.serial!=self.app.name_cache.serial:return
        self.request=None
        if event['kind']=='midi_error':
            self.error=event['message'];self.message.config(text=self.error)
            self.summary.config(text=f'Read stopped · {len(self.records)}/{len(FIELDS)} entries captured')
            self.refresh_button.config(state='normal');self.save_button.config(state='normal');return
        r=event['record']
        if (r['parameter'],r['index'])!=FIELDS[self.position]:return
        self.records.append(r)
        values=self.row_values(r)
        self.table.insert('','end',iid=str(self.position),values=values)
        self.position+=1;self.save_button.config(state='normal');self.next_entry()
    def save(self):
        if getattr(self,'pending_edit',None) or getattr(self,'restore_dialog',None) or (not self.records and not self.error):return
        # Serialize before opening the modal dialog, so refresh/reconnect cannot mix captures.
        data=dict(format='af16rig-midi-assignments-v1',build='BETA RC',started_utc=self.started_utc,
            exported_utc=datetime.now(timezone.utc).isoformat(),connection_serial=self.serial,
            demo=self.app.demo,complete=len(self.records)==len(FIELDS),error=self.error,
            records=self.records,export_writes_device=False,message_types_verified=True)
        content=json.dumps(data,indent=2,ensure_ascii=False)+'\n'
        path=filedialog.asksaveasfilename(parent=self.window,title='Save MIDI assignment report',initialfile='AF16Rig-midi-assignments.json',defaultextension='.json',filetypes=[('JSON report','*.json')])
        if path:
            try:Path(path).write_text(content,encoding='utf-8')
            except OSError as error:
                if not self.closed:self.message.config(text=str(error))
                return
            if not self.closed:self.message.config(text='MIDI assignment report saved.')
    def backup_ready(self):
        if (self.closed or not self.app.connected or self.serial!=self.app.name_cache.serial
                or self.request is not None or getattr(self,'pending_edit',None) or getattr(self,'restore_dialog',None)):return False
        from midi_backup import stable_records
        try:stable_records(self.records)
        except ValueError:return False
        return True
    def save_backup(self):
        if not self.backup_ready():return
        from midi_backup import make_backup
        content=json.dumps(make_backup(self.records,self.app.demo),indent=2)+'\n'
        path=filedialog.asksaveasfilename(parent=self.window,title='Save MIDI assignment backup',initialfile='AF16Rig-midi-backup.json',defaultextension='.json',filetypes=[('MIDI backup','*.json')])
        if not path:return
        try:Path(path).write_text(content,encoding='utf-8')
        except OSError as error:
            if not self.closed:self.message.config(text=str(error))
            return
        if not self.closed:self.message.config(text='MIDI backup saved: channels, CC/Note/Off types and numbers.')
    def open_restore(self):
        if not self.backup_ready():return
        serial=self.serial
        path=filedialog.askopenfilename(parent=self.window,title='Open MIDI assignment backup',filetypes=[('MIDI backup','*.json')])
        if not path or not self.backup_ready() or serial!=self.serial:return
        from midi_backup import load_backup,restore_plan
        try:changes=restore_plan(load_backup(path),self.records,self.app.demo)
        except (OSError,ValueError) as error:self.message.config(text=str(error));return
        if not changes:self.message.config(text='All saved MIDI assignments already match.');return
        from midi_restore_window import MidiRestoreWindow
        from midi_batch import assignment_conflicts
        conflicts=assignment_conflicts(self.records,changes)
        notice=('Duplicate channel/type/number assignments: '+ '; '.join(conflicts)) if conflicts else ''
        self.restore_dialog=MidiRestoreWindow(self,changes,notice=notice)
        self.refresh_button.config(state='disabled');self.save_button.config(state='disabled');self.update_editor()
    def batch_scope_changed(self):
        full=self.batch_control.get()=='All controls (64)'
        self.batch_first_widget.config(to=64 if full else 120)
        self.message.config(text=('All 64 strip controls: eight consecutive numbers each for Fader, Pan, Mute, Solo, Aux 1–4. '
            'Stored message types stay unchanged; master and bank assignments are untouched. '
            'Check for conflicts with their existing numbers in the preview.' if full else
            'Eight consecutive numbers for the selected control; stored message types stay unchanged.'))
    def preview_batch(self):
        if not self.backup_ready():return
        from midi_batch import plan_strip_batch,plan_full_batch,assignment_conflicts
        try:
            channel=int(self.batch_channel.get());first=int(self.batch_first.get())
        except ValueError:
            self.message.config(text='Enter a MIDI channel from 1–16 and a first number from 0–120.');return
        full=self.batch_control.get()=='All controls (64)'
        try:
            changes=(plan_full_batch(self.records,channel,first,self.app.demo) if full else
                plan_strip_batch(self.records,self.batch_control.get(),channel,first,self.app.demo))
        except ValueError as error:self.message.config(text=str(error));return
        if not changes:self.message.config(text='All selected assignments already match.');return
        from midi_restore_window import MidiRestoreWindow
        conflicts=assignment_conflicts(self.records,changes)
        notice=('Duplicate channel/type/number assignments: '+ '; '.join(conflicts)) if conflicts else ''
        self.restore_dialog=MidiRestoreWindow(self,changes,notice=notice)
        self.refresh_button.config(state='disabled');self.save_button.config(state='disabled');self.update_editor()
    def open_ports(self):
        if self.closed or not self.app.connected or self.serial!=self.app.name_cache.serial or self.request is not None or getattr(self,'pending_edit',None) or getattr(self,'restore_dialog',None):return
        from midi_ports_window import MidiPortsWindow
        self.restore_dialog=MidiPortsWindow(self);self.update_editor()
    def close(self):
        dialog=getattr(self,'restore_dialog',None)
        if dialog:dialog.close(refresh=False)
        self.closed=True;self.request=None;self.pending_edit=None
        self.app.worker.commands.put(('input_select',None));self.app.input_window=None;self.window.destroy()
