"""Screen-bounded startup size and per-user window preferences."""
import json
import os
from pathlib import Path

def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'af16rig-control'/'window.json'

def bounded_size(width, height, screen_width, screen_height):
    return (max(1,min(int(width),max(1,screen_width-24))),
            max(1,min(int(height),max(1,screen_height-80))))

def restore(root):
    sw,sh=root.winfo_screenwidth(),root.winfo_screenheight()
    saved={}
    try:
        value=json.loads(config_path().read_text())
        if isinstance(value,dict):saved=value
    except (OSError,ValueError):pass
    try:w,h=bounded_size(saved.get('width',sw-24),saved.get('height',sh-80),sw,sh)
    except (ValueError,TypeError,OverflowError):w,h=bounded_size(sw,sh,sw,sh)
    root.minsize(min(1000,w),min(600,h))
    root.geometry(f'{w}x{h}+0+0')
    if saved.get('maximized',True):
        def maximize():
            try:root.attributes('-zoomed',True)
            except Exception:
                try:root.state('zoomed')
                except Exception:pass
        root.after_idle(maximize)

def save(root):
    try:
        try:maximized=bool(root.attributes('-zoomed'))
        except Exception:maximized=root.state()=='zoomed'
        p=config_path();p.parent.mkdir(parents=True,exist_ok=True)
        temp=p.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(width=root.winfo_width(),height=root.winfo_height(),maximized=maximized)))
        temp.replace(p)
    except (OSError,ValueError):pass
