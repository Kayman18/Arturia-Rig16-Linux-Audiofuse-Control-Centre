"""Single-row navigation: native-size buttons, scrolling instead of reflow."""
import tkinter as tk
from tkinter import ttk

class NavigationBar(tk.Frame):
    def __init__(self,parent,**options):
        super().__init__(parent,**options)
        self.items=[]
        self.canvas=tk.Canvas(self,bg=self.cget('bg'),highlightthickness=0,height=36)
        self.scroll=ttk.Scrollbar(self,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.scroll.set)
        self.canvas.pack(fill='x')
        self.canvas.bind('<Button-4>',lambda e:self.canvas.xview_scroll(-1,'units'))
        self.canvas.bind('<Button-5>',lambda e:self.canvas.xview_scroll(1,'units'))
        self.content=tk.Frame(self.canvas,bg=self.cget('bg'))
        self.content_id=self.canvas.create_window(0,0,window=self.content,anchor='nw')
        self.content.bind('<Configure>',self.measure)
        self.canvas.bind('<Shift-MouseWheel>',self.wheel)
    def add(self,button):
        self.items.append(button)
        button.pack(side='left',padx=3)
        button.bind('<FocusIn>',lambda event,b=button:self.reveal(b),add='+')
    def measure(self,event=None):
        width=self.content.winfo_reqwidth();height=self.content.winfo_reqheight()
        if self.canvas.winfo_reqheight()!=height:self.canvas.configure(height=height)
        self.canvas.configure(scrollregion=(0,0,width,height))
    def reveal(self,button):
        width=max(1,self.content.winfo_reqwidth());view=self.canvas.winfo_width()
        start=self.canvas.canvasx(0);left=button.winfo_x();right=left+button.winfo_width()
        if left<start:self.canvas.xview_moveto(left/width)
        elif right>start+view:self.canvas.xview_moveto(max(0,right-view)/width)
    def wheel(self,event):
        self.canvas.xview_scroll(-1 if event.delta>0 else 1,'units')
        return 'break'
