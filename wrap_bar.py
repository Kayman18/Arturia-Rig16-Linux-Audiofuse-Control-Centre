"""Wrap navigation buttons only when their requested widths exceed the viewport."""
import tkinter as tk

def wrap_rows(width,widths,gap=6):
    rows=[];row=[];used=0
    for index,item in enumerate(widths):
        need=max(1,int(item))+gap
        if row and used+need>max(1,width):rows.append(row);row=[];used=0
        row.append(index);used+=need
    if row:rows.append(row)
    return rows

class WrapBar(tk.Frame):
    def __init__(self,parent,**kwargs):
        super().__init__(parent,**kwargs)
        self.items=[];self.rows=[];self.layout_key=None;self.job=None
        self.bind('<Configure>',self.schedule)
        self.bind('<Destroy>',self.on_destroy,add='+')
    def add(self,widget):
        self.items.append(widget);self.schedule()
    def schedule(self,event=None):
        if self.job is None:self.job=self.after_idle(self.reflow)
    def reflow(self):
        self.job=None
        if not self.winfo_exists():return
        width=self.winfo_width()-2*self.winfo_pixels(self.cget('padx'))
        plan=wrap_rows(width,[w.winfo_reqwidth() for w in self.items])
        key=tuple(tuple(row) for row in plan)
        if key==self.layout_key:return
        self.layout_key=key
        for item in self.items:item.pack_forget()
        for row in self.rows:row.pack_forget()
        while len(self.rows)<len(plan):self.rows.append(tk.Frame(self,bg=self.cget('bg')))
        for row,indices in zip(self.rows,plan):
            row.pack(fill='x')
            for i in indices:self.items[i].pack(in_=row,side='left',padx=3)
    def on_destroy(self,event):
        if event.widget is self and self.job is not None:
            self.after_cancel(self.job);self.job=None
