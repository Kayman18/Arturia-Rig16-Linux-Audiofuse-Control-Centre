import copy
import unittest
from unittest.mock import Mock,patch
from af16rig import DemoAF16Rig
from midi_config import FIELDS,STRIP_CONTROLS,read_entry,remap
from midi_batch import plan_strip_batch
import test_midi_config as base

def records():return [read_entry(DemoAF16Rig(),p,i) for p,i in FIELDS]

class MidiBatchTests(unittest.TestCase):
    def test_all_controls_only_target_eight_strip_entries(self):
        for n,control in enumerate(STRIP_CONTROLS):
            source=records();before=copy.deepcopy(source)
            plan=plan_strip_batch(source,control,16,120,True)
            self.assertEqual([(c['parameter'],c['index']) for c in plan],[(20+n,i) for i in range(8)])
            self.assertEqual([c['number'] for c in plan],list(range(120,128)))
            self.assertTrue(all(c['channel']==16 for c in plan))
            self.assertEqual(source,before)

    def test_plan_applies_and_second_plan_is_empty(self):
        device=DemoAF16Rig();source=records()
        for c in plan_strip_batch(source,'Aux 4',1,0,True):
            remap(device,*[c[k] for k in ('parameter','index','channel','number','expected')])
        fresh=[read_entry(device,p,i) for p,i in FIELDS]
        self.assertEqual(plan_strip_batch(fresh,'Aux 4',1,0,True),[])

    def test_preserves_each_stored_type(self):
        source=records()
        for r in source:
            if r['parameter']==20:
                raw=((r['index']%3)<<14)|r['index'];r.update(raw=raw,reads=[raw,raw])
        for c in plan_strip_batch(source,'Fader',2,40):
            self.assertEqual(c['expected']>>14,c['index']%3)

    def test_rejects_invalid_values(self):
        for control,ch,num in [('Other',1,0),('Fader',0,0),('Fader',17,0),('Fader',True,0),('Fader',1,-1),('Fader',1,121),('Fader',1,True),('Fader',1,1.5)]:
            with self.assertRaises(ValueError):plan_strip_batch(records(),control,ch,num)

    def test_rejects_incomplete_or_unstable_capture(self):
        with self.assertRaises(ValueError):plan_strip_batch(records()[:-1],'Fader',1,0)
        source=records();source[-1]['stable']=False
        with self.assertRaises(ValueError):plan_strip_batch(source,'Fader',1,0)

    def test_unsupported_target_blocks_entire_plan(self):
        for raw in (0xc000,0x5000,0x4080):
            source=records();r=next(r for r in source if r['parameter']==20 and r['index']==7)
            r.update(raw=raw,reads=[raw,raw])
            with self.assertRaisesRegex(ValueError,'unsupported'):plan_strip_batch(source,'Fader',2,40)

    def test_unsupported_untouched_entry_is_preserved(self):
        source=records();source[-1].update(raw=0xffff,reads=[0xffff,0xffff])
        self.assertEqual(len(plan_strip_batch(source,'Fader',2,40)),8)

    def page(self):
        p=base.MidiPageTests().window();p.records=records()
        p.batch_control=Mock();p.batch_control.get.return_value='Fader'
        p.batch_channel=Mock();p.batch_channel.get.return_value='2'
        p.batch_first=Mock();p.batch_first.get.return_value='40'
        p.update_editor=Mock()
        return p

    def test_preview_does_not_write_and_blocks_other_operations(self):
        p=self.page()
        with patch('midi_restore_window.MidiRestoreWindow') as dialog:
            p.preview_batch();dialog.assert_called_once()
            self.assertEqual(len(dialog.call_args.args[1]),8)
        self.assertTrue(p.app.worker.commands.empty())
        self.assertFalse(p.backup_ready())

    def test_stale_connection_does_not_open_preview(self):
        p=self.page();p.app.name_cache.serial+=1
        with patch('midi_restore_window.MidiRestoreWindow') as dialog:
            p.preview_batch();dialog.assert_not_called()

    def test_invalid_ui_input_does_not_open_preview(self):
        p=self.page();p.batch_first.get.return_value='wrong'
        with patch('midi_restore_window.MidiRestoreWindow') as dialog:
            p.preview_batch();dialog.assert_not_called()
        self.assertTrue(p.app.worker.commands.empty())

if __name__=='__main__':unittest.main()
