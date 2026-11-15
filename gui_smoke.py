"""Unattended real-Tk smoke checks, strictly isolated from physical USB devices."""
import argparse
import contextlib
import json
import platform
import tempfile
import time
import traceback
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

class DemoGuard(contextlib.ExitStack):
    def __enter__(self):
        super().__enter__()
        import af16rig
        from cable_colors import CableColors
        self.enter_context(patch.object(af16rig.AF16Rig,'__init__',side_effect=AssertionError('Physical USB access is disabled in GUI checks')))
        self.enter_context(patch('window_state.restore',return_value=None))
        self.enter_context(patch('window_state.save',return_value=None))
        self.enter_context(patch.object(CableColors,'load',return_value=CableColors()))
        self.enter_context(patch.object(CableColors,'save',return_value=True))
        return self

class Runner:
    def __init__(self,root,app,report,folder):
        self.root,self.app,self.report,self.folder=root,app,report,Path(folder)
        self.steps=[];self.position=0;self.current=None;self.done=False
        self.started=time.monotonic();self.callback_errors=0
    def add(self,name,action,ready=lambda:True,check=lambda:None,timeout=15,settle=.3):
        self.steps.append(dict(name=name,action=action,ready=ready,check=check,timeout=timeout,settle=settle))
    def callback_error(self,kind,value,tb):
        self.callback_errors+=1
        if len(self.report['callback_errors'])<50:self.report['callback_errors'].append(''.join(traceback.format_exception(kind,value,tb)))
    def tick(self):
        if self.done:return
        if time.monotonic()-self.started>360:self.finish('timed_out');return
        if self.current is None:
            if self.position>=len(self.steps):self.finish();return
            self.current=self.steps[self.position];self.step_started=time.monotonic()
            print(f'[{self.position+1}/{len(self.steps)}] {self.current["name"]}',flush=True)
            try:self.current['action']()
            except Exception:self.record_failure(traceback.format_exc())
        if self.current is not None:
            try:
                elapsed=time.monotonic()-self.step_started
                if elapsed>=self.current['settle'] and self.current['ready']():
                    self.current['check']();self.record('passed')
                elif elapsed>self.current['timeout']:self.record_failure('Timed out waiting for UI/readback')
            except Exception:self.record_failure(traceback.format_exc())
        self.root.after(50,self.tick)
    def record_failure(self,message):self.record('failed',message)
    def record(self,status,message=None):
        self.report['checks'].append(dict(name=self.current['name'],status=status,detail=message,
            elapsed_seconds=round(time.monotonic()-self.step_started,3)))
        self.current=None;self.position+=1
    def finish(self,status=None):
        if self.done:return
        self.done=True
        self.report['status']=status or ('failed' if self.callback_errors or any(r['status']=='failed' for r in self.report['checks']) else 'passed')
        self.report['callback_error_count']=self.callback_errors
        self.report['completed_checks']=self.position;self.report['planned_checks']=len(self.steps)
        self.report['elapsed_seconds']=round(time.monotonic()-self.started,2)
        self.app.close()
    def nav(self,title):
        button=next(b for b in self.app.navigation.items if b.cget('text')==title)
        button.invoke()
    def panels(self):
        visible=[w for w in self.app.page_host.winfo_children() if w.winfo_manager() and w.winfo_ismapped()]
        expected=self.app.input_window.window if self.app.input_window else self.app.dashboard.frame
        assert visible==[expected],f'Expected one active page, found {[str(w) for w in visible]}'
    def navigation(self):
        nav=self.app.navigation
        expected = ('MIXER', 'FRONT 1–2', 'FRONT 3–4', 'REAR INPUTS', 'OUTPUTS', 'ROUTING',
                    'MONITOR', 'PRESETS', 'CLOCK', 'METERS', 'MIDI')
        actual = tuple(button.cget('text') for button in nav.items)
        assert actual == expected, f'Expected navigation {expected}, found {actual}'
        ys={b.winfo_y() for b in nav.items}
        assert len(ys)==1,'Navigation wrapped'
        for b in nav.items:
            assert b.winfo_ismapped() and b.winfo_width()>1,f'Navigation hidden: {b.cget("text")}'
            assert b.master is nav.content,'Navigation button has wrong parent'
        assert nav.content.winfo_reqwidth()>=nav.items[-1].winfo_x()+nav.items[-1].winfo_width(),'Last tab outside scrollable row'
    def mixer_ready(self):
        d=self.app.dashboard
        return self.app.connected and bool(d.visible) and all(d.controllers[i].state and not d.controllers[i].stale for i in d.visible)
    def mixer(self):
        self.panels();d=self.app.dashboard
        master=d.master_view.frame
        from mixer_layout import expanded_geometry
        widths,width,height,dial_height=expanded_geometry(d.canvas.winfo_width(),d.canvas.winfo_height(),len(d.visible)+2,d.master_view.minimum_width,fit=d.bus=='main' and d.bank_start==1)
        assert d.bank.winfo_width()==width and d.bank.winfo_height()==height,'Mixer does not use expected viewport extent'
        assert master.winfo_ismapped() and master.winfo_width()==widths[-1],'Master strip width changed'
        assert all(d.strips[i].frame.winfo_width()==widths[n] for n,i in enumerate(d.visible)),'Channel widths changed'
        self.root.update_idletasks()
        left=master.winfo_rootx()-d.canvas.winfo_rootx()
        assert left+master.winfo_width()<=d.canvas.winfo_width()+3,'Master outside fixed output row'
        assert [o.kind for o in d.output_strips]==['phones','monitor'],'Output strip order changed'
        self.report['layouts'].append(dict(bus=d.bus,bank=d.bank_start,width=self.root.winfo_width(),height=self.root.winfo_height(),
            visible_strips=len(d.visible),master_width=master.winfo_width(),nav_rows=len({b.winfo_y() for b in self.app.navigation.items})))
    def size(self,width,height):
        self.root.geometry(f'{max(400,min(width,self.root.winfo_screenwidth()-40))}x{max(400,min(height,self.root.winfo_screenheight()-80))}+0+0')
    def plan(self):
        a=self.app
        self.add('Demo connection',lambda:None,lambda:a.connected,self.panels)
        for width,height in ((1000,720),(1500,1000)):
            self.add(f'Navigation at {width}×{height}',lambda w=width,h=height:self.size(w,h),self.mixer_ready,self.navigation)
            self.add(f'Mixer at {width}×{height}',lambda:None,self.mixer_ready,self.mixer)
        for bus in ('main','cue'):
            for bank in (1,17,33,49):
                def action(bus=bus,bank=bank):
                    self.nav('MIXER');a.dashboard.change_bus(bus);a.dashboard.change_bank(bank)
                self.add(f'{bus} mixer bank {bank}',action,self.mixer_ready,self.mixer)
        for title in ('FRONT 1–2','FRONT 3–4','REAR INPUTS','OUTPUTS','MONITOR'):
            self.add(title,lambda title=title:self.nav(title),check=self.panels,settle=1.2)
            self.add('Return from '+title,lambda:self.nav('MIXER'),check=self.panels)
        self.add('Routing canvas',lambda:self.nav('ROUTING'),lambda:bool(a.input_window.state) and not a.input_window.pending,self.routing_check)
        self.add('Routing bank filters',self.routing_filters,check=self.routing_check)
        self.add('Fader scene capture',a.open_fader_scenes,self.scene_ready,self.panels)
        self.add('Fader scene save',self.scene_save,check=lambda:assert_file(self.folder/'fader-scene.json'))
        self.add('Fader scene preview',self.scene_preview,lambda:not a.input_window.busy and a.input_window.preview_current is not None,self.scene_preview_check)
        self.add('Fader scene recall',lambda:a.input_window.apply_button.invoke(),lambda:not a.input_window.busy,self.scene_recall_check)
        self.add('Fader scene reread',lambda:a.input_window.read_button.invoke(),self.scene_ready,self.scene_readback_check)
        self.add('Mixer scene capture',a.open_mixer_scenes,self.scene_ready,self.panels,timeout=60)
        self.add('Mixer scene save',self.mixer_scene_save,check=lambda:assert_file(self.folder/'mixer-scene.json'))
        self.add('Mixer scene rate preview',self.mixer_scene_preview,lambda:not a.input_window.busy,self.mixer_rate_preview_check,timeout=60)
        self.add('Mixer scene rate matching',lambda:a.input_window.rate_button.invoke(),lambda:not a.input_window.busy,self.mixer_settings_preview_check,timeout=60)
        self.add('Mixer scene setting recall',lambda:a.input_window.apply_button.invoke(),lambda:not a.input_window.busy,self.mixer_scene_result,timeout=90)
        self.add('Presets readback',lambda:self.nav('PRESETS'),lambda:len(a.input_window.records)==9 and not a.input_window.busy,self.panels)
        self.add('Preset copy via confirmation',self.preset_copy,lambda:not a.input_window.busy and a.input_window.status is not None and a.input_window.status['current']==8,self.preset_copy_check)
        self.add('Clock status',lambda:self.nav('CLOCK'),lambda:bool(a.input_window.state),self.panels)
        self.add('Names page',a.open_channel_names,lambda:len(a.name_cache.records)==60,self.panels)
        self.add('Meters page',lambda:self.nav('METERS'),lambda:a.input_window.session.fresh(time.monotonic()),self.panels)
        self.add('Meter hold while polling continues',lambda:a.input_window.hold_button.invoke(),lambda:a.input_window.held is not None and a.input_window.session.time>a.input_window.held.time,self.meter_export)
        self.add('Meter resume and USB bank',self.meter_resume,check=self.panels)
        self.add('MIDI capture',lambda:self.nav('MIDI'),self.midi_ready,self.panels)
        self.add('MIDI backup',self.midi_backup,check=lambda:assert_file(self.folder/'midi.json'))
        self.add('MIDI edit through Apply button',self.midi_edit,lambda:a.input_window.pending_edit is None and a.input_window.records[2]['raw']==0x4f4a,self.panels)
        self.add('MIDI restore preview',self.midi_preview,lambda:a.input_window.restore_dialog is not None,self.preview_check)
        self.add('MIDI batch restore',lambda:a.input_window.restore_dialog.apply.invoke(),lambda:not a.input_window.restore_dialog.busy,self.restore_check)
        self.add('Close restore and refresh',lambda:a.input_window.restore_dialog.close(),self.midi_ready,self.panels)
        self.add('Eight-strip MIDI assignment preview',self.strip_batch_preview,check=self.strip_batch_preview_check)
        self.add('Eight-strip MIDI assignment apply',lambda:a.input_window.restore_dialog.apply.invoke(),lambda:not a.input_window.restore_dialog.busy,self.strip_batch_result)
        self.add('Eight-strip MIDI assignment reread',lambda:a.input_window.restore_dialog.close(),self.midi_ready,self.strip_batch_readback)
        self.add('Full MIDI template preview',self.full_batch_preview,check=self.full_batch_preview_check)
        self.add('Full MIDI template apply',lambda:a.input_window.restore_dialog.apply.invoke(),lambda:not a.input_window.restore_dialog.busy,self.full_batch_result,timeout=30)
        self.add('Full MIDI template reread',lambda:a.input_window.restore_dialog.close(),self.midi_ready,self.full_batch_readback)
        self.add('Return to main mixer',self.main_mixer,self.mixer_ready,self.mixer)
        self.add('Monitor strip target',lambda:a.target_volume(-8.5),lambda:not a.pending and a.state.get('speaker_level_signed')==-2176,self.panels)
        self.add('Monitor strip restore',lambda:a.target_volume(-12),lambda:not a.pending and a.state.get('speaker_level_signed')==-3072,self.panels)
        self.add('Phones level ready',lambda:None,lambda:a.dashboard.phones_strip.phones_ready(),self.phones_check)
        self.add('Phones target',self.phones_target,lambda:self.phones_at(-18),self.phones_check)
        self.add('Phones restore',lambda:a.dashboard.phones_strip.target_phones(self.phones_before),lambda:self.phones_at(self.phones_before),self.phones_check)
        self.add('Reconnect demo',self.reconnect,lambda:a.connected and a.name_cache.serial>self.previous_serial,self.panels)
    def mixer_scene_save(self):
        with patch('mixer_scene_window.filedialog.asksaveasfilename',return_value=str(self.folder/'mixer-scene.json')):
            self.app.input_window.save_button.invoke()
    def mixer_scene_preview(self):
        path=self.folder/'mixer-scene.json';saved=json.loads(path.read_text())
        next(e for e in saved['entries'] if e['bus']=='sample_rate')['values']['rate']=[96000]
        first=next(e for e in saved['entries'] if e['bus']=='main' and e['source'])
        first['values']['level']=[-256]*len(first['values']['level'])
        path.write_text(json.dumps(saved))
        with patch('mixer_scene_window.filedialog.askopenfilename',return_value=str(path)):
            self.app.input_window.load_button.invoke()
    def mixer_rate_preview_check(self):
        p=self.app.input_window
        assert p.rate_match_needed() and not p.changes,'Rate preview not isolated from setting recall'
        assert p.rate_button.instate(('!disabled',)),'Match rate button disabled'
        self.panels()
    def mixer_settings_preview_check(self):
        p=self.app.input_window
        assert p.preview_current is not None and p.changes and not p.rate_match_needed(),'Fresh setting preview missing'
        assert p.apply_button.instate(('!disabled',)),'Setting recall disabled'
    def mixer_scene_result(self):
        from mixer_scene import plan
        p=self.app.input_window
        assert p.scene and not plan(p.target,p.scene),'Mixer scene final readback differs'
        assert 'Recall complete' in p.message.cget('text'),'Recall completion missing'
        self.panels()
    def phones_target(self):
        from phones_level import decode_level
        p=self.app.dashboard.phones_strip;self.phones_before=decode_level(p.phones_raw)[0]
        assert p.target_phones(-18),'Phones target was not queued'
    def phones_at(self,value):
        from phones_level import decode_level
        p=self.app.dashboard.phones_strip
        return p.phones_ready() and decode_level(p.phones_raw)[0]==value
    def routing_check(self):
        self.panels();p=self.app.input_window
        assert p.canvas.find_all(),'Routing canvas empty'
        assert p.source_points and p.destination_points,'Routing nodes missing'
    def routing_filters(self):
        p=self.app.input_window;p.source_filter.set('All');p.destination_filter.set('ADAT');p.filter_changed()
    def meter_export(self):
        p=self.app.input_window;path=self.folder/'meters.json'
        with patch('meters_window.filedialog.asksaveasfilename',return_value=str(path)):p.save_snapshot()
        data=json.loads(path.read_text());assert data['held'] and data['demo'] and len(data['readings'])==118
        self.panels()
    def meter_resume(self):
        p=self.app.input_window;p.hold_button.invoke();assert p.held is None;p.buttons['USB'].invoke()
    def scene_ready(self):
        p=self.app.input_window
        return p is not None and not p.busy and p.scene is not None
    def scene_save(self):
        with patch('fader_scene_window.filedialog.asksaveasfilename',return_value=str(self.folder/'fader-scene.json')):
            self.app.input_window.save_button.invoke()
    def scene_preview(self):
        import json
        path=self.folder/'fader-scene.json';data=json.loads(path.read_text())
        entry=next(e for e in data['entries'] if e['bus']=='main' and e['source']==0)
        self.scene_target=-256 if entry['levels']!=[-256] else -512
        entry['levels']=[self.scene_target];path.write_text(json.dumps(data))
        with patch('fader_scene_window.filedialog.askopenfilename',return_value=str(path)):
            self.app.input_window.load_button.invoke()
    def scene_preview_check(self):
        p=self.app.input_window
        assert len(p.changes)==1 and p.changes[0]['source']==0,'Unexpected fader scene preview'
    def scene_recall_check(self):
        p=self.app.input_window
        assert p.mode=='apply' and p.position==1 and p.preview_current is None,'Scene recall did not complete'
    def scene_readback_check(self):
        p=self.app.input_window
        entry=next(e for e in p.scene['entries'] if e['bus']=='main' and e['source']==0)
        assert entry['levels']==[self.scene_target],'Scene master readback mismatch'
    def preset_copy(self):
        p=self.app.input_window;p.table.selection_set('1');p.update_buttons()
        self.preset_destination_name=p.records[8]['name']
        with patch('presets_window.simpledialog.askinteger',return_value=8),patch('presets_window.messagebox.askyesno',return_value=True):
            p.copy_button.invoke()
    def preset_copy_check(self):
        p=self.app.input_window
        assert p.status==dict(current=8,changed=0),'Preset copy state not confirmed'
        assert p.records[8]['name']==self.preset_destination_name,'Copy changed destination name'
        assert not p.busy,'Copy left the page busy'
    def midi_ready(self):
        p=self.app.input_window
        return p is not None and p.request is None and len(p.records)==73 and p.backup_ready()
    def midi_backup(self):
        with patch('midi_window.filedialog.asksaveasfilename',return_value=str(self.folder/'midi.json')):self.app.input_window.save_backup()
    def midi_edit(self):
        p=self.app.input_window;p.table.selection_set('2');p.select_entry()
        p.edit_channel.set('16');p.edit_number.set('74');p.apply_button.invoke()
    def midi_preview(self):
        with patch('midi_window.filedialog.askopenfilename',return_value=str(self.folder/'midi.json')):self.app.input_window.open_restore()
    def preview_check(self):
        self.panels();d=self.app.input_window.restore_dialog
        assert len(d.changes)==1 and not d.busy and d.request is None,'Preview submitted a write or unexpected plan'
    def restore_check(self):
        d=self.app.input_window.restore_dialog
        assert d.position==1 and self.app.input_window.records[2]['raw']==0x4000,'Demo assignment was not restored'
    def strip_batch_preview(self):
        p=self.app.input_window
        p.batch_control.set('Fader');p.batch_channel.set('16');p.batch_first.set('120');p.batch_button.invoke()
    def strip_batch_preview_check(self):
        d=self.app.input_window.restore_dialog
        assert d is not None and len(d.changes)==8 and not d.busy and d.request is None,'Eight-strip preview missing or already writing'
    def strip_batch_result(self):
        assert self.app.input_window.restore_dialog.position==8,'Eight-strip batch incomplete'
        self.strip_batch_readback()
    def strip_batch_readback(self):
        p=self.app.input_window
        rows=[r for r in p.records if r['parameter']==20]
        assert len(rows)==8 and all(r['stable'] and r['raw']==0x4f78+r['index'] for r in rows),'Eight-strip readback mismatch'
    def full_batch_preview(self):
        p=self.app.input_window
        p.batch_control.set('All controls (64)');p.batch_scope_changed()
        p.batch_channel.set('15');p.batch_first.set('64');p.batch_button.invoke()
    def full_batch_preview_check(self):
        d=self.app.input_window.restore_dialog
        assert d is not None and len(d.changes)==64 and not d.busy and d.request is None,'Full template preview missing or already writing'
    def full_batch_result(self):
        assert self.app.input_window.restore_dialog.position==64,'Full template incomplete'
        self.full_batch_readback()
    def full_batch_readback(self):
        rows=[r for r in self.app.input_window.records if 20<=r['parameter']<=27]
        assert len(rows)==64 and all(r['stable'] and r['raw']==0x4e40+(r['parameter']-20)*8+r['index'] for r in rows),'Full template readback mismatch'
    def main_mixer(self):
        self.nav('MIXER');self.app.dashboard.change_bus('main');self.app.dashboard.change_bank(1)
    def phones_check(self):
        p=self.app.dashboard.phones_strip
        assert p.fader.ready and p.fader.target_callback is not None,'Confirmed headphone level control unavailable'
        assert len(p.meter.model.levels)==2,'Phones stereo meters missing'
    def reconnect(self):
        self.previous_serial=self.app.name_cache.serial;self.app.connect_button.invoke()

def assert_file(path):
    assert path.is_file() and path.stat().st_size>0,'Export file missing'

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',default='AF16Rig-GUI-check.json')
    args=parser.parse_args(argv);path=Path(args.report).expanduser().resolve()
    report=dict(format='af16rig-demo-gui-check-v1',build='BETA RC',utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),platform=platform.platform(),demo=True,physical_usb_blocked=True,
        status='blocked',checks=[],callback_errors=[],layouts=[],limitations='Demo GUI check; does not verify firmware, physical audio, hardware readback or sound.')
    root=None;app=None
    try:
        import tkinter as tk
        from af16rig_gui import App
        with tempfile.TemporaryDirectory(prefix='af16rig-gui-check-') as folder,DemoGuard():
            root=tk.Tk();report['tk_patchlevel']=str(root.tk.call('info','patchlevel'))
            app=App(root,demo=True);runner=Runner(root,app,report,folder)
            root.report_callback_exception=runner.callback_error
            root.protocol('WM_DELETE_WINDOW',lambda:runner.finish('interrupted'))
            runner.size(1500,1000);runner.plan();root.after(50,runner.tick)
            root.mainloop()
            if not runner.done:report['status']='interrupted'
    except Exception:
        report['error']=traceback.format_exc()
        if app is not None:report['status']='failed'
    finally:
        if app is not None and app.worker.is_alive():app.worker.stop_event.set();app.worker.join(timeout=4)
        if root is not None:
            try:root.destroy()
            except Exception:pass
    try:path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    except OSError as error:print(f'Could not save GUI report: {error}');return 2
    print(f'GUI check: {report["status"]}\nReport: {path}')
    if report['status']=='blocked':print('Run this command inside your Linux desktop session with Tk installed. No rig is required.')
    return 0 if report['status']=='passed' else 2 if report['status']=='blocked' else 1

if __name__=='__main__':raise SystemExit(main())
