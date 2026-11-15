"""Small independent meter canvases; meter ticks never rebuild mixer controls."""
import tkinter as tk
from meters import Ballistics

class Meter(tk.Canvas):
    def __init__(self,parent,caption='IN'):
        super().__init__(parent,width=26,height=120,bg=parent.cget('bg'),highlightthickness=0)
        self.caption=caption
        self.model=Ballistics();self.signature=object();self.items=[];self.size=None;self.paint_cache={}
    def feed(self,values,now):self.model.feed(values,now)
    def clear(self):self.model=Ballistics();self.signature=object()
    def paint(self,item,**options):
        for key,value in options.items():
            if self.paint_cache.get((item,key))!=value:
                self.itemconfigure(item,**{key:value});self.paint_cache[item,key]=value
    def place(self,item,*coordinates):
        pixels=tuple(round(v) for v in coordinates)
        if self.paint_cache.get((item,'coords'))!=pixels:
            self.coords(item,*pixels);self.paint_cache[item,'coords']=pixels
    def draw(self,now):
        reading=self.model.tick(now)
        n=len(self.model.levels) or 1
        w,h=max(8,self.winfo_width()),max(20,self.winfo_height())
        caption=self.caption if n==1 else 'L R'
        bottom=h-(25 if caption else 3);top=12;travel=max(1,bottom-top)
        if self.size!=(w,h,n):
            self.delete('all');self.items=[];self.size=(w,h,n);self.signature=object();self.paint_cache={}
            for i in range(n):
                x=3+i*(w-6)/n
                self.create_rectangle(x,top,x+(w-6)/n-3,bottom,fill='#111416',outline='#424950')
                bar=self.create_rectangle(x,bottom,x+(w-6)/n-3,bottom,fill='#70d7d1',outline='')
                peak=self.create_line(x,bottom,x+(w-6)/n-3,bottom,fill='#dbeeee',width=2)
                clip=self.create_rectangle(x,3,x+(w-6)/n-3,8,fill='#424950',outline='')
                self.items.append((bar,peak,clip))
            self.label=self.create_text(w/2,h-11,text=caption,fill='#939ca4',font=('DejaVu Sans',7))
        state=None if reading is None else tuple(tuple(round(v,1) for v in part) for part in reading)
        if state==self.signature:return
        self.signature=state
        for i,(bar,peak,clip) in enumerate(self.items):
            x=3+i*(w-6)/n;end=x+(w-6)/n-3
            level=-60 if reading is None else reading[0][i]
            held=-60 if reading is None else reading[1][i]
            y=bottom-(level+60)/60*travel;py=bottom-(held+60)/60*travel
            self.place(bar,x,y,end,bottom);self.place(peak,x,py,end,py)
            self.paint(bar,fill='#ef6961' if level>=-.1 else '#e4ba66' if level>=-6 else '#70d7d1')
            self.paint(peak,state='hidden' if reading is None else 'normal')
            self.paint(clip,fill='#ef6961' if reading is not None and held>=-.1 else '#424950')
