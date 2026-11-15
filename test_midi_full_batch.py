import copy
import unittest
from unittest.mock import patch
from af16rig import DemoAF16Rig
from midi_config import FIELDS,read_entry,remap
from midi_batch import plan_full_batch,assignment_conflicts
from test_midi_batch import records
import test_midi_batch as batch_tests

class FullBatchTests(unittest.TestCase):
    def test_maps_all_64_in_blocks_and_leaves_master_bank(self):
        source=records();before=copy.deepcopy(source)
        plan=plan_full_batch(source,16,64,True)
        self.assertEqual(len(plan),64)
        self.assertEqual({c['number'] for c in plan},set(range(64,128)))
        for c in plan:
            self.assertEqual(c['number'],64+(c['parameter']-20)*8+c['index'])
            self.assertEqual(c['channel'],16)
        self.assertEqual(source,before)
        self.assertTrue(all(20<=c['parameter']<=27 for c in plan))
    def test_roundtrip_and_repeat_noop(self):
        d=DemoAF16Rig();source=records()
        for c in plan_full_batch(source,2,0,True):
            remap(d,*[c[k] for k in ('parameter','index','channel','number','expected')])
        fresh=[read_entry(d,p,i) for p,i in FIELDS]
        self.assertEqual(plan_full_batch(fresh,2,0,True),[])
        self.assertEqual([r for r in fresh if r['parameter']<20 or r['parameter']>27],
                         [r for r in source if r['parameter']<20 or r['parameter']>27])
    def test_preserves_mixed_types(self):
        source=records()
        for r in source:
            if 20<=r['parameter']<=27:
                raw=((r['index']%3)<<14)|r['index'];r.update(raw=raw,reads=[raw,raw])
        for c in plan_full_batch(source,16,64):self.assertEqual(c['expected']>>14,c['index']%3)
    def test_invalid_inputs(self):
        for ch,num in [(0,0),(17,0),(True,0),(1,-1),(1,65),(1,True),(1,1.5)]:
            with self.assertRaises(ValueError):plan_full_batch(records(),ch,num)
    def test_incomplete_unstable_unsupported(self):
        with self.assertRaises(ValueError):plan_full_batch(records()[:-1],1,0)
        for raw in (0xc000,0x5000,0x4080):
            source=records();r=next(r for r in source if r['parameter']==27 and r['index']==7)
            r.update(raw=raw,reads=[raw,raw])
            with self.assertRaisesRegex(ValueError,'unsupported'):plan_full_batch(source,1,0)
        source=records();source[2]['stable']=False
        with self.assertRaises(ValueError):plan_full_batch(source,1,0)
    def test_preview_only_no_writes(self):
        p=batch_tests.MidiBatchTests().page();p.batch_control.get.return_value='All controls (64)'
        with patch('midi_restore_window.MidiRestoreWindow') as dialog:
            p.preview_batch();self.assertEqual(len(dialog.call_args.args[1]),64)
        self.assertTrue(p.app.worker.commands.empty());self.assertFalse(p.backup_ready())
    def test_range_error_no_partial_plan(self):
        p=batch_tests.MidiBatchTests().page();p.batch_control.get.return_value='All controls (64)';p.batch_first.get.return_value='65'
        with patch('midi_restore_window.MidiRestoreWindow') as dialog:
            p.preview_batch();dialog.assert_not_called()
        self.assertTrue(p.app.worker.commands.empty())
    def test_master_collision_notice(self):
        source=records();plan=plan_full_batch(source,1,0,True)
        collisions=assignment_conflicts(source,plan)
        self.assertTrue(any('Master fader' in c for c in collisions))
        self.assertEqual(assignment_conflicts(source,plan_full_batch(source,16,64,True)),[])
    def test_stale_connection_blocks_full_preview(self):
        p=batch_tests.MidiBatchTests().page();p.batch_control.get.return_value='All controls (64)';p.app.name_cache.serial+=1
        with patch('midi_restore_window.MidiRestoreWindow') as dialog:
            p.preview_batch();dialog.assert_not_called()

if __name__=='__main__':unittest.main()
