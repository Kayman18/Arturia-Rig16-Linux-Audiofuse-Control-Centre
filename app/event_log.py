"""Bounded session diagnostics independent of the high-rate meter trace."""
import copy
import datetime

class EventLog:
    def __init__(self,limit=300):
        self.limit=limit;self.records=[];self.sequence=0
    def clear(self):self.records.clear()
    def capture(self,event,serial=None,now=None):
        kind=event.get('kind','')
        errors=event.get('state',{}).get('errors') if isinstance(event.get('state'),dict) else None
        if isinstance(event.get('state'),dict) and event['state'].get('status')=='read_error':
            errors={'read':event['state'].get('error','Read failed')}
        severity='error' if kind=='error' or kind.endswith('_error') or errors else 'info'
        if kind in ('recovering','reconnect_wait','commands_discarded'):severity='warning'
        if severity=='info' and kind not in ('connected','disconnected','reconnect_disabled'):return False
        message=event.get('message') or ('; '.join(f'{k}: {v}' for k,v in errors.items()) if isinstance(errors,dict) else str(errors) if errors else '')
        if kind=='commands_discarded':message=f'{event.get("count",0)} pending changes discarded'
        if not message:message=kind.replace('_',' ').capitalize()
        stamp=now or datetime.datetime.now(datetime.timezone.utc).isoformat()
        context={key:event[key] for key in ('bus','source','channel','name','destination','request_id') if key in event}
        serial=event.get('connection_serial',serial)
        key=(kind,message,context,serial)
        last=self.records[-1] if self.records else None
        if last and (last['kind'],last['message'],last['context'],last['connection_serial'])==key:
            last['last_time']=stamp;last['count']+=1
        else:
            self.sequence+=1
            self.records.append(dict(id=self.sequence,first_time=stamp,last_time=stamp,kind=kind,severity=severity,
                                     message=message,context=copy.deepcopy(context),connection_serial=serial,count=1))
            self.records=self.records[-self.limit:]
        return True
    def report(self,demo=False):
        return dict(format='af16rig-event-log-v1',build='BETA RC',demo=bool(demo),events=copy.deepcopy(self.records))
