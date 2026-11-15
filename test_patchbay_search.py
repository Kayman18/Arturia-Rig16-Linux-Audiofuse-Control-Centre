import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from patchbay_search import matches
from patchbay_window import PatchBayWindow
from mixer_view import Field

class SearchTests(unittest.TestCase):
    def panel(self):
        p=PatchBayWindow.__new__(PatchBayWindow)
        p.app=SimpleNamespace(name_cache=SimpleNamespace(names={1:'Hydrasynth',17:'FX Return',77:'FX Send'}),worker=Mock())
        p.source_filter=Field('All');p.destination_filter=Field('All')
        p.source_search=Field('');p.destination_search=Field('')
        p.state={'reads':{'second':{'values':{'output_source[0]':64,'output_source[12]':80}}}}
        return p
    def test_empty_search_preserves_all_ports(self):
        p=self.panel();s,d=p.visible_ports();self.assertEqual((len(s),len(d)),(70,60))
        self.assertEqual(s[:6],[192,193,194,195,196,197])
    def test_equipment_name_finds_input(self):
        p=self.panel();p.source_search.set('HYDRA');self.assertEqual(p.visible_ports()[0],[64])
    def test_name_and_native_label_tokens_match_together(self):
        p=self.panel();p.source_search.set('adat return');self.assertEqual(p.visible_ports()[0],[80])
    def test_output_name_search_keeps_native_index(self):
        p=self.panel();p.destination_search.set('fx send');self.assertEqual(p.visible_ports()[1],[12])
    def test_queries_respect_bank_filters(self):
        p=self.panel();p.source_filter.set('USB');p.source_search.set('Hydra')
        self.assertEqual(p.visible_ports()[0],[])
        p.destination_filter.set('Physical');p.destination_search.set('FX');self.assertEqual(p.visible_ports()[1],[])
    def test_connected_sources_follow_filtered_outputs(self):
        p=self.panel();p.source_filter.set('Connected');p.destination_search.set('FX')
        self.assertEqual(p.visible_ports(),([80],[12]))
    def test_nonmatching_search_has_no_fallback_results(self):
        p=self.panel();p.source_filter.set('Connected');p.source_search.set('not here')
        self.assertEqual(p.visible_ports()[0],[])
        p.source_search.set('');p.destination_search.set('not here')
        self.assertEqual(p.visible_ports(),([],[]))
    def test_literal_unicode_matching_without_regex(self):
        self.assertTrue(matches('ＳＹＮＴＨ','Synth'))
        self.assertTrue(matches('café','CAFÉ'))
        self.assertFalse(matches('.*','Synth'));self.assertTrue(matches('  ','anything'))
    def test_search_does_not_mutate_routes_or_send_commands(self):
        p=self.panel();before=p.routes();p.source_search.set('FX');p.destination_search.set('FX')
        p.visible_ports();self.assertEqual(p.routes(),before);p.app.worker.commands.put.assert_not_called()
    def test_search_cancels_drag_without_changing_history(self):
        p=self.panel();p.selected_destination=12;p.drag_source=64;p.drag_destination=12;p.armed_source=64
        p.canvas=Mock();p.update_editor=Mock();p.draw=Mock();p.history=object();history=p.history
        p.search_changed();self.assertIsNone(p.drag_source);self.assertIsNone(p.selected_destination)
        self.assertIs(p.history,history);p.app.worker.commands.put.assert_not_called()
    def test_clear_search_restores_queries_without_changing_banks(self):
        p=self.panel();p.source_search.set('Hydra');p.destination_search.set('FX');p.search_changed=Mock()
        self.assertEqual(p.reset_search(),'break');self.assertFalse(p.search_active())
        self.assertEqual(p.source_filter.get(),'All');p.search_changed.assert_called_once()
    def test_shortcuts_use_existing_guarded_history(self):
        p=self.panel();p.replay_history=Mock()
        self.assertEqual(p.history_shortcut('undo'),'break');p.replay_history.assert_called_once_with('undo')
        p.replay_history.reset_mock();p.drag_source=64
        p.history_shortcut('redo');p.replay_history.assert_not_called()

if __name__=='__main__':unittest.main()
