"""Bounded, connection-local history of fully confirmed routing operations."""
from copy import deepcopy
from routing_labels import SOURCE_LABELS,DESTINATION_LABELS

class RoutingHistory:
    def __init__(self,limit=50):
        if type(limit) is not int or limit<1:raise ValueError('Positive history limit required')
        self.limit=limit;self.serial=None;self.undo=[];self.redo=[]
    def clear(self):self.undo.clear();self.redo.clear()
    def bind(self,serial):
        if serial!=self.serial:self.clear();self.serial=serial
    @staticmethod
    def checked(changes):
        if not isinstance(changes,list) or not 1<=len(changes)<=60:raise ValueError('Invalid routing operation')
        result=[];seen=set()
        for c in changes:
            if not isinstance(c,dict):raise ValueError('Invalid routing change')
            d=c.get('destination');old=c.get('expected_source');new=c.get('source_code')
            if type(d) is not int or d not in DESTINATION_LABELS or d in seen or type(old) is not int or old not in SOURCE_LABELS or type(new) is not int or new not in SOURCE_LABELS:
                raise ValueError('Unmapped or duplicate routing change')
            seen.add(d);result.append(dict(destination=d,expected_source=old,source_code=new))
        return result
    def record(self,changes,label):
        changes=self.checked(changes)
        if not any(c['source_code']!=c['expected_source'] for c in changes):return
        self.undo.append(dict(changes=changes,label=str(label)));self.undo=self.undo[-self.limit:];self.redo.clear()
    def prepare(self,direction):
        stack=self.undo if direction=='undo' else self.redo if direction=='redo' else None
        if not stack:raise ValueError('No routing operation to '+str(direction))
        entry=stack[-1];changes=deepcopy(entry['changes'])
        if direction=='undo':
            for c in changes:c['source_code'],c['expected_source']=c['expected_source'],c['source_code']
        return changes
    def complete(self,direction):
        source,target=(self.undo,self.redo) if direction=='undo' else (self.redo,self.undo) if direction=='redo' else ([],[])
        if not source:raise ValueError('No pending history operation')
        target.append(source.pop())
