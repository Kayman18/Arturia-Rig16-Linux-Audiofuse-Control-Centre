import copy,unittest
from af16rig import DemoAF16Rig,DeviceError
from midi_config import FIELDS,read_entry,remap
from midi_backup import make_backup,restore_plan,FORMAT,LEGACY_FORMAT
from midi_batch import assignment_conflicts
import test_midi_backup as base

class TypedBackupTests(unittest.TestCase):
    def test_new_format_and_all_type_transitions_restore_all_assignments(self):
        for old in range(3):
            for new in range(3):
                device=DemoAF16Rig();device.midi_assignments={k:(old<<14)|0x0207 for k in FIELDS[2:]}
                current=[read_entry(device,p,i) for p,i in FIELDS]
                data=make_backup(current,True);self.assertEqual(data['format'],FORMAT)
                for e in data['assignments']:e['raw']=(new<<14)|0x0f7f
                plan=restore_plan(data,current,True);self.assertEqual(len(plan),71)
                for c in plan:
                    result=remap(device,c['parameter'],c['index'],c['channel'],c['number'],c['expected'],c['message_type'])
                    self.assertEqual(result['raw'],(new<<14)|0x0f7f)
                final=[read_entry(device,p,i) for p,i in FIELDS]
                self.assertEqual(restore_plan(data,final,True),[])
    def test_legacy_same_type_plan_preserves_type_and_refuses_mismatch(self):
        data=base.backup();data['format']=LEGACY_FORMAT;data['assignments'][0]['raw']=0x407f
        plan=restore_plan(data,base.records(),True);self.assertNotIn('message_type',plan[0])
        data['assignments'][0]['raw']=0x007f
        with self.assertRaisesRegex(ValueError,'message type differs'):restore_plan(data,base.records(),True)
    def test_type_only_preview_labels_and_off(self):
        data=base.backup();data['assignments'][0]['raw']=0x8000
        c=restore_plan(data,base.records(),True)[0]
        self.assertEqual(c['message_type'],2);self.assertIn('Note #0',c['before']);self.assertIn('Off #0',c['after'])
    def test_dialog_forwards_type_and_accepts_only_matching_confirmation(self):
        d=base.MidiRestoreTests().dialog(1);data=base.backup();data['assignments'][0]['raw']=0x8000
        d.changes=restore_plan(data,base.records(),True);d.start()
        cmd,sent=d.app.worker.commands.get_nowait();self.assertEqual(sent['message_type'],2)
        result=remap(DemoAF16Rig(),sent['parameter'],sent['index'],sent['channel'],sent['number'],sent['expected'],sent['message_type'])
        d.handle(dict(kind='midi_written',request_id=sent['request_id'],connection_serial=7,record=result))
        self.assertEqual(d.position,1);self.assertEqual(d.parent.records[2]['raw'],0x8000)
    def test_wrong_type_confirmation_stops_without_advancing(self):
        d=base.MidiRestoreTests().dialog(1);d.changes[0]['message_type']=2;d.start()
        _,sent=d.app.worker.commands.get_nowait()
        result=remap(DemoAF16Rig(),sent['parameter'],sent['index'],sent['channel'],sent['number'],sent['expected'])
        d.handle(dict(kind='midi_written',request_id=sent['request_id'],connection_serial=7,record=result))
        self.assertEqual(d.position,0);self.assertFalse(d.busy)
    def test_conflicts_use_proposed_type_and_ignore_disabled_assignments(self):
        records=base.records();data=make_backup(records,True)
        # First two assignments become identical CC messages.
        for e in data['assignments'][:2]:e['raw']=7
        plan=restore_plan(data,records,True);self.assertTrue(assignment_conflicts(records,plan))
        for e in data['assignments'][:2]:e['raw']=0x8007
        plan=restore_plan(data,records,True);self.assertEqual(assignment_conflicts(records,plan),[])
    def test_unknown_type_still_rejects_entire_plan(self):
        data=base.backup();data['assignments'][0]['raw']=0
        data['assignments'][-1]['raw']=0xc000
        with self.assertRaisesRegex(ValueError,'unsupported'):restore_plan(data,base.records(),True)

if __name__=='__main__':unittest.main()
