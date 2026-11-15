"""Window/taskbar identity and bundled icon sizes; no extra dependencies."""
from pathlib import Path
APP_CLASS='AF16RigLinuxControl'
ICON_NAME='af16rig-linux-control'

def install_window_icon(root):
    import tkinter as tk
    directory=Path(__file__).resolve().parent/'icons'
    images=[tk.PhotoImage(master=root,file=str(directory/f'af16rig-{size}.png')) for size in (16,32,48,64,128,256)]
    root.iconphoto(True,*images)
    root._af16rig_icons=images
