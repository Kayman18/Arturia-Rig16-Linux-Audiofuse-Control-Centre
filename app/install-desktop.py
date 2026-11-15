#!/usr/bin/env python3
"""Install a per-user launcher and icon for this extracted application folder."""
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from app_icon import APP_CLASS,ICON_NAME

def exec_quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'

def atomic_copy(source,destination):
    fd,name=tempfile.mkstemp(prefix='.'+destination.name+'-',dir=destination.parent)
    os.close(fd);temporary=Path(name)
    try:
        shutil.copyfile(source,temporary)
        os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)

def install(source=None,data_home=None):
    source=Path(source or Path(__file__).resolve().parents[1]).resolve()
    data_home=Path(data_home or os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    launcher=source/'run.sh'
    if any(c in str(source) for c in ('\n','\r')):raise ValueError('Application path cannot contain line breaks')
    if not launcher.is_file():raise FileNotFoundError(launcher)
    # Validate assets before touching an existing installation.
    for required in ('app/af16rig_gui.py','app/app_icon.py','run.sh','icons/'+ICON_NAME+'.svg',
                     *(f'icons/af16rig-{n}.png' for n in (16,24,32,48,64,128,256))):
        if not (source/required).is_file():raise FileNotFoundError(source/required)
    data_home=data_home.expanduser().resolve()
    if any(c in str(data_home) for c in ('\n','\r')):raise ValueError('Install path cannot contain line breaks')
    base=data_home/ICON_NAME
    releases=base/'releases'
    if releases.is_relative_to(source):raise ValueError('Install directory must be outside the extracted app folder')
    releases.mkdir(parents=True,exist_ok=True)
    current=base/'current'
    if current.exists() and not current.is_symlink():raise ValueError('Install current path is not an app-managed symlink')
    release=Path(tempfile.mkdtemp(prefix='beta-rc-',dir=releases))
    temporary=base/('.current-'+uuid.uuid4().hex)
    activated=False
    try:
        shutil.copytree(source,release,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.git'))
        launcher=current/'run.sh'
        for size in (16,24,32,48,64,128,256):
            dest=data_home/f'icons/hicolor/{size}x{size}/apps';dest.mkdir(parents=True,exist_ok=True)
            atomic_copy(release/f'icons/af16rig-{size}.png',dest/f'{ICON_NAME}.png')
        dest=data_home/'icons/hicolor/scalable/apps';dest.mkdir(parents=True,exist_ok=True)
        atomic_copy(release/'icons'/f'{ICON_NAME}.svg',dest/f'{ICON_NAME}.svg')
        apps=data_home/'applications';apps.mkdir(parents=True,exist_ok=True)
        entry=apps/f'{ICON_NAME}.desktop'
        staged=release/'launcher.desktop'
        staged.write_text('[Desktop Entry]\nType=Application\nName=AF16Rig Linux Control\nComment=AudioFuse 16Rig control panel\nExec=/bin/bash '+exec_quote(launcher)+'\nIcon='+ICON_NAME+'\nTerminal=false\nCategories=AudioVideo;Audio;Mixer;\nStartupNotify=true\nStartupWMClass='+APP_CLASS+'\n',encoding='utf-8')
        atomic_copy(staged,entry)
        staged.unlink()
        # The launcher always refers to current, so a failed asset/launcher
        # update leaves the previous active application selected.
        temporary.symlink_to(release.relative_to(base),target_is_directory=True)
        os.replace(temporary,current)
        activated=True
    finally:
        temporary.unlink(missing_ok=True)
        if not activated:shutil.rmtree(release,ignore_errors=True)
    return entry

if __name__=='__main__':
    print('Installed launcher:',install())
    print('App installed. Open AF16Rig Linux Control from your applications menu.')
    print('You may now move or delete the extracted download. Run this installer again to update.')
