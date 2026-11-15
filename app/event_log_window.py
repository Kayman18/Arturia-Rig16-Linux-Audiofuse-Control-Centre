"""A session log window that leaves mixer polling and navigation running."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog

class EventLogWindow:
    def __init__(self,app):
        self.app=app
        self.window=tk.Toplevel(app.root);self.window.title('AF16Rig — Event log')
        self.window.geometry('900x520');self.window.protocol('WM_DELETE_WINDOW',self.close)
        shell=ttk.Frame(self.window,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='Session errors and connection history · repeated entries are counted · times in UTC').pack(anchor='w',pady=(0,8))
        area=ttk.Frame(shell);area.pack(fill='both',expand=True)
        self.table=ttk.Treeview(area,columns=('time','severity','kind','count','message'),show='headings',height=10,selectmode='browse')
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scroll.set)
        for key,title,width in [('time','Last seen (UTC)',170),('severity','Level',65),('kind','Event',130),('count','Count',50),('message','Message',380)]:
            self.table.heading(key,text=title);self.table.column(key,width=width,stretch=key=='message')
        self.table.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',self.select)
        self.detail=tk.Text(shell,height=7,wrap='word',state='disabled');self.detail.pack(fill='both',expand=True,pady=8)
        buttons=ttk.Frame(shell);buttons.pack(fill='x')
        ttk.Button(buttons,text='Copy selected',command=self.copy).pack(side='left')
        ttk.Button(buttons,text='Save log…',command=self.save).pack(side='left',padx=8)
        ttk.Button(buttons,text='Clear log',command=self.clear).pack(side='right')
        self.status=ttk.Label(shell,text='Retained for this app session; save a log to keep it.');self.status.pack(anchor='w',pady=(8,0))
        self.refresh()
    def refresh(self):
        selected=self.table.selection();keep={str(r['id']) for r in self.app.event_log.records}
        for key in self.table.get_children():
            if key not in keep:self.table.delete(key)
        for r in self.app.event_log.records:
            key=str(r['id']);values=(r['last_time'],r['severity'],r['kind'],r['count'],r['message'])
            if not self.table.exists(key):self.table.insert('','end',iid=key,values=values)
            elif tuple(map(str,self.table.item(key,'values')))!=tuple(map(str,values)):self.table.item(key,values=values)
        if selected and selected[0] not in keep:self.select()
    def selected(self):
        keys=self.table.selection()
        return next((r for r in self.app.event_log.records if keys and str(r['id'])==keys[0]),None)
    def select(self,event=None):
        r=self.selected();text=json.dumps(r,indent=2,ensure_ascii=False) if r else ''
        self.detail.config(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',text);self.detail.config(state='disabled')
    def copy(self):
        r=self.selected()
        if r:
            self.window.clipboard_clear();self.window.clipboard_append(json.dumps(r,indent=2,ensure_ascii=False))
            self.status.config(text='Selected event copied.')
    def save(self):
        path=filedialog.asksaveasfilename(parent=self.window,title='Save event log',initialfile='AF16Rig-BETA RC-events.json',defaultextension='.json',filetypes=[('JSON log','*.json')])
        if not path:return
        try:Path(path).write_text(json.dumps(self.app.event_log.report(self.app.demo),indent=2,ensure_ascii=False)+'\n')
        except OSError as e:self.status.config(text=f'Could not save: {e}');return
        self.status.config(text='Event log saved.')
    def clear(self):
        self.app.event_log.clear();self.app.log_button.config(text='Log (0)');self.refresh();self.select()
    def close(self):self.app.event_log_window=None;self.window.destroy()
