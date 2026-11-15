"""Single-flight MIDI configuration restore using existing checked workers."""
import uuid
from midi_restore_window import MidiRestoreWindow

class MidiConfigurationRestore(MidiRestoreWindow):
    def __init__(self,parent,changes):
        super().__init__(parent,changes,configuration=True)
    def queue_next(self):
        if self.position>=len(self.changes) or self.changes[self.position].get('kind') not in ('port','bank'):
            return super().queue_next()
        self.timer=None
        if self.closed or not self.busy or self.request is not None:return
        if self.stopped:self.finish('Stopped.');return
        if not self.app.connected or self.serial!=self.app.name_cache.serial:
            self.finish('Connection changed; no further changes sent.');return
        c=self.changes[self.position];self.request=uuid.uuid4().hex
        data=dict(target=c['target'],expected=c['expected'],request_id=self.request,connection_serial=self.serial)
        if c['kind']=='port':data['field']=c['field']
        self.message.config(text=f'Applying {self.position+1}/{len(self.changes)} · {c["label"]}…')
        self.app.worker.commands.put(('midi_ports_set' if c['kind']=='port' else 'midi_bank_size',data))
    def handle(self,event):
        if self.position>=len(self.changes) or self.changes[self.position].get('kind') not in ('port','bank'):
            return super().handle(event)
        if self.closed or not self.busy or self.request is None or event.get('request_id')!=self.request:return False
        c=self.changes[self.position]
        success='midi_ports_written' if c['kind']=='port' else 'midi_written'
        if event['kind'] not in (success,'midi_error'):return False
        self.request=None
        if event.get('connection_serial')!=self.serial or self.app.name_cache.serial!=self.serial:
            self.finish('Connection changed; result discarded.');return True
        if event['kind']=='midi_error':
            self.table.set(str(self.position),'status','Not confirmed');self.finish('Stopped: '+event['message']);return True
        r=event.get('records',{}).get(c.get('field'),{}) if c['kind']=='port' else event.get('record',{})
        valid=r.get('stable') is True and r.get('raw')==c['target']
        if c['kind']=='bank':valid=valid and (r.get('parameter'),r.get('index'))==(18,0)
        if not valid:self.finish('Stopped: unexpected confirmation; refresh.');return True
        if c['kind']=='bank':
            for i,old in enumerate(self.parent.records):
                if (old['parameter'],old['index'])==(18,0):
                    self.parent.records[i]=r;self.parent.table.item(str(i),values=self.parent.row_values(r));break
        self.table.set(str(self.position),'status','Confirmed');self.position+=1
        if self.stopped:self.finish('Stopped.');return True
        if self.position>=len(self.changes):self.finish('Batch complete.');return True
        self.timer=self.window.after(120,self.queue_next);return True
