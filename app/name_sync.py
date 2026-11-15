"""Incremental name sync, low priority to regular polling and user commands."""
from channel_names import read_word,decode_words,MAX_WORDS,name_parameter,source_label,NAME_SOURCE_COUNT,NAME_SOURCES,NAME_PARAMETERS
from af16rig import DeviceError,DeviceDisconnected

class NameScan:
    def __init__(self,device,reader=read_word,demo=False):
        self.device,self.reader,self.demo=device,reader,demo
        self.position=0;self.source=NAME_SOURCES[0];self.passes=[[]];self.done=False
    def step(self):
        """At most one USB word read. Return a record only when a name completes."""
        if self.done:return None
        if self.demo:
            from name_edit import read_name
            record=read_name(self.device,self.source)
            return self.advance(record)
        words=self.passes[-1]
        try:word=self.reader(self.device,name_parameter(self.source),len(words))
        except DeviceDisconnected:raise
        except (DeviceError,ValueError) as error:
            self.done=True
            return dict(source=self.source,candidate=None,status='read_error',error=str(error),passes=self.passes,write_requests=0)
        words.append(word)
        if word!=0 and len(words)<MAX_WORDS:return None
        if len(self.passes)==1:
            self.passes.append([]);return None
        record=dict(source=self.source,parameter=name_parameter(self.source),passes=self.passes,candidate=None,write_requests=0)
        if self.passes[0]!=self.passes[1]:record['status']='changed_during_read'
        else:record.update(decode_words(self.passes[0]))
        return self.advance(record)
    def advance(self,record):
        self.position+=1;self.passes=[[]];self.done=self.position>=NAME_SOURCE_COUNT
        if not self.done:self.source=NAME_SOURCES[self.position]
        return record

class NameCache:
    def __init__(self):self.reset(None)
    def reset(self,serial):
        self.serial=serial;self.names={};self.records={}
    def accept(self,serial,record,demo=False):
        if serial is None or serial!=self.serial:return False
        source=record.get('source')
        if type(source) is not int or source not in NAME_PARAMETERS:return False
        self.records[source]=record
        old=self.names.get(source)
        value=None
        if demo and record.get('status')=='demo':value=record.get('candidate')
        else:
            passes=record.get('passes',[])
            if len(passes)==2 and passes[0]==passes[1] and passes[0]:
                decoded=decode_words(passes[0])
                if decoded.get('encoding')=='packed UTF-8' and decoded['status'] in ('candidate','blank'):
                    value=decoded['candidate']
        if isinstance(value,str) and value.strip() and value.strip().upper()!=('ANALOG IN' if source<=16 else 'ADAT IN' if source<=32 else 'ANALOG OUT' if source<=76 else 'ADAT OUT'):
            self.names[source]=value
        else:self.names.pop(source,None)
        return old!=self.names.get(source)
    def title(self,source,stereo=False):
        left=self.names.get(source)
        if not stereo:return left or source_label(source)
        right=self.names.get(source+1)
        if left and right:return left if left==right else f'{left} / {right}'
        return left or right or source_label(source,True)
