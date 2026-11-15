"""Mixer title rename, using the existing guarded name_set worker command."""
import time
import tkinter as tk
from tkinter import simpledialog,messagebox
from name_edit import confirmed_text,encode_name
from channel_names import source_label
from af16rig import DeviceError

def rename_targets(source,stereo):
    if type(source) is not int or not 1<=source<=32:return ()
    return (source,source+1) if stereo and source%2 and source<32 else (source,)

def rename_input(app,source):
    if not rename_targets(source,False) or not app.connected or app.info.get('state_version')!=18:return
    if getattr(app,'quick_name_request',None) is not None:return
    serial=app.name_cache.serial
    try:
        expected=confirmed_text(app.name_cache.records.get(source,{}),app.demo)
    except DeviceError as error:
        app.message.config(text=str(error),fg='#efba76');return
    try:
        name=simpledialog.askstring('Rename '+source_label(source),'Equipment name (maximum 15 UTF-8 bytes):',initialvalue=expected,parent=app.root)
        if name is None:return
        encode_name(name)
        if not app.connected or serial!=app.name_cache.serial or app.info.get('state_version')!=18:
            app.message.config(text='Connection changed; name was not sent. Open rename again.',fg='#efba76');return
        if getattr(app,'quick_name_request',None) is not None:return
        if name==expected:return
        request=time.monotonic_ns();app.quick_name_request=request
        app.worker.commands.put(('name_set',dict(request_id=request,connection_serial=serial,source=source,expected=expected,name=name)))
        app.message.config(text='Saving equipment name and checking readback…',fg='#969ca2')
    except ValueError as error:messagebox.showerror('Invalid equipment name',str(error),parent=app.root)
    except tk.TclError:pass

def finish_rename(app,event):
    pending=getattr(app,'quick_name_request',None)
    if event['kind'] in ('error','disconnected','connected','preset_state_reset'):
        app.quick_name_request=None;return
    if pending is None or event.get('request_id')!=pending:return
    if event['kind'] not in ('name_written','name_write_error'):return
    app.quick_name_request=None
    if event['kind']=='name_written':
        app.message.config(text='Demo name updated.' if app.demo else 'Equipment name saved and confirmed by device readback.',fg='#62cbd5')
    else:app.message.config(text=event['message'],fg='#efba76')
