import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig
import test_midi_backup as base
import midi_configuration as config
from midi_ports import snapshot,OPTIONS,set_option
from midi_config import remap,set_bank_size
from midi_configuration_restore import MidiConfigurationRestore

def current():return base.records(),snapshot(DemoAF16Rig())
def saved():
    records,ports=current();return config.make_configuration(records,ports,True)
def altered():
    data=saved()
    for entry in data['assignments']['assignments']:entry['raw']=0x0f7f
    data['bank_size']=4
    for field,options in OPTIONS.items():data['ports'][field]=len(options)-1
    return data

class ConfigurationTests(unittest.TestCase):
    def test_roundtrip_and_no_changes(self):
        data=saved();records,ports=current();self.assertEqual(config.plan(data,records,ports,True),[])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps(data));self.assertEqual(config.load(path),data)
    def test_every_section_and_mode_last(self):
        records,ports=current();changes=config.plan(altered(),records,ports,True)
        self.assertEqual(len(changes),71+1+len(OPTIONS))
        self.assertEqual(changes[-1]['field'],'preferred_mode')
        self.assertEqual(changes[71]['kind'],'bank')
        self.assertEqual({c['field'] for c in changes[72:]},set(OPTIONS))
    def test_bad_or_missing_sections_rejected(self):
        for key,value in [('bank_size',True),('bank_size',9),('ports',{}),('demo',1),('format','wrong'),('state_version',True)]:
            data=saved();data[key]=value
            with self.assertRaises(ValueError):config.validate(data)
        data=saved();data['audio']={}
        with self.assertRaises(ValueError):config.validate(data)
        for field,options in OPTIONS.items():
            for value in (True,-1,len(options)):
                data=saved();data['ports'][field]=value
                with self.assertRaises(ValueError):config.validate(data)
    def test_unstable_reads_and_demo_mismatch_rejected(self):
        records,ports=current();records[0]['stable']=False
        with self.assertRaises(ValueError):config.make_configuration(records,ports,True)
        records,ports=current();ports['preferred_mode']['stable']=False
        with self.assertRaises(ValueError):config.make_configuration(records,ports,True)
        records,ports=current()
        with self.assertRaises(ValueError):config.plan(saved(),records,ports,False)
        data=saved();data['assignments']['demo']=False
        with self.assertRaises(ValueError):config.validate(data)
    def test_duplicate_json_and_oversized_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            for text in ('{"format":1,"format":2}',' '* (config.MAX_BYTES+1)):
                path.write_text(text)
                with self.assertRaises(ValueError):config.load(path)

class RestoreTests(unittest.TestCase):
    def dialog(self):
        old=base.MidiRestoreTests().dialog(1)
        d=MidiConfigurationRestore.__new__(MidiConfigurationRestore);d.__dict__.update(old.__dict__)
        records,ports=current();d.changes=config.plan(altered(),records,ports,True);d.configuration=True
        return d
    def reply(self,d,device):
        cmd,data=d.app.worker.commands.get_nowait()
        event=dict(request_id=data['request_id'],connection_serial=7)
        if cmd=='midi_remap':
            r=remap(device,data['parameter'],data['index'],data['channel'],data['number'],data['expected'],message_type=data.get('message_type'))
            return dict(event,kind='midi_written',record=r)
        if cmd=='midi_bank_size':return dict(event,kind='midi_written',record=set_bank_size(device,data['target'],data['expected']))
        self.assertEqual(cmd,'midi_ports_set')
        return dict(event,kind='midi_ports_written',records=set_option(device,data['field'],data['target'],data['expected']))
    def test_all_sections_sequential_readback(self):
        d=self.dialog();device=DemoAF16Rig();d.start()
        for i in range(len(d.changes)):
            self.assertTrue(d.handle(self.reply(d,device)));self.assertEqual(d.position,i+1)
            self.assertTrue(d.app.worker.commands.empty())
            if i+1<len(d.changes):d.queue_next()
        self.assertTrue(d.stopped)
        self.assertEqual(config.port_values(snapshot(device)),altered()['ports'])
    def test_failed_port_stops_remaining_changes(self):
        d=self.dialog();d.changes=d.changes[72:];d.start()
        _,data=d.app.worker.commands.get_nowait()
        self.assertTrue(d.handle(dict(kind='midi_error',request_id=data['request_id'],connection_serial=7,message='failed')))
        d.queue_next();self.assertTrue(d.app.worker.commands.empty());self.assertTrue(d.stopped);self.assertEqual(d.position,0)
    def test_stale_reply_and_reconnect(self):
        d=self.dialog();d.changes=d.changes[72:];d.start();event=self.reply(d,DemoAF16Rig())
        self.assertFalse(d.handle(dict(event,request_id='old')))
        d.app.name_cache.serial=8;self.assertTrue(d.handle(event));self.assertTrue(d.stopped);self.assertEqual(d.position,0)
    def test_stop_after_current_port(self):
        d=self.dialog();d.changes=d.changes[72:];d.start();d.request_stop()
        self.assertTrue(d.handle(self.reply(d,DemoAF16Rig())));self.assertEqual(d.position,1)
        d.queue_next();self.assertTrue(d.app.worker.commands.empty());self.assertTrue(d.stopped)
    def test_wrong_bank_confirmation_stops(self):
        d=self.dialog();d.changes=d.changes[71:];d.start();event=self.reply(d,DemoAF16Rig());event['record']['raw']=8
        d.handle(event);self.assertEqual(d.position,0);self.assertTrue(d.stopped)

if __name__=='__main__':unittest.main()
