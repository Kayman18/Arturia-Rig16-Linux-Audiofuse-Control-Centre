import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from names_window import NamesWindow
from routing_window import RoutingWindow
from clock_window import ClockWindow

class PageReconnectTests(unittest.TestCase):
    def names(self,connected=True):
        w=NamesWindow.__new__(NamesWindow);w.app=SimpleNamespace(connected=connected)
        w.pending=True;w.editing=True;w.edit_source=1;w.edit_serial=1;w.edit_expected='Old';w.request_id=99;w.records=[{}]
        for name in ('table','name_value','edit_label','name_entry','apply_button','save_button','read_button','message'):setattr(w,name,Mock())
        w.table.get_children.return_value=['1','2'];w.restore_dialog=None;return w
    def test_names_reconnect_clears_old_rows_and_editor(self):
        w=self.names();w.connection_changed()
        self.assertEqual(w.records,[]);self.assertFalse(w.pending);self.assertFalse(w.editing)
        self.assertIsNone(w.edit_serial);self.assertIsNone(w.request_id)
        self.assertEqual(w.table.delete.call_count,2);w.name_value.set.assert_called_once_with('')
        w.apply_button.config.assert_called_once_with(state='disabled')
    def test_disconnect_stops_restore_before_it_can_queue_next_name(self):
        w=self.names(False);w.restore_dialog=Mock()
        w.handle(dict(kind='input_error',channel='names',message='Disconnected'))
        w.restore_dialog.close.assert_called_once();w.restore_dialog.handle.assert_not_called()
        w.read_button.config.assert_called_once_with(state='disabled')
    def test_late_reply_cannot_reenable_old_editor(self):
        w=self.names();w.connection_changed();w.apply_button.reset_mock()
        w.handle(dict(kind='name_written',request_id=99,state={'candidate':'Late'}))
        w.apply_button.config.assert_not_called();self.assertIsNone(w.edit_source)
    def test_name_refresh_removes_rows_absent_from_current_cache(self):
        w=self.names();w.pending=False;w.editing=False;w.edit_feedback=None
        w.app.name_cache=SimpleNamespace(records={1:dict(source=1,candidate='New',status='demo')})
        w.table.exists.return_value=True;w.table.item.return_value=()
        w.refresh_names();w.table.delete.assert_called_once_with('2')
        self.assertEqual(len(w.records),1)
    def routing(self,connected=True):
        w=RoutingWindow.__new__(RoutingWindow);w.app=SimpleNamespace(connected=connected)
        w.pending=True;w.state={'old':True};w.request_id=99;w.batch=[1];w.update_editor=Mock();w.refresh=Mock();w.draw=Mock()
        w.routing_history=Mock();w.history_job={};w.pending_color=(1,);w.stereo_job={};w.armed_source=64;return w
    def test_routing_reconnect_clears_pending_and_reloads_without_writes(self):
        w=self.routing();w.connection_changed()
        self.assertEqual(w.state,{});self.assertFalse(w.pending);self.assertIsNone(w.batch)
        self.assertIsNone(w.armed_source);self.assertIsNone(w.history_job)
        w.routing_history.return_value.clear.assert_called_once();w.refresh.assert_called_once()
    def test_routing_does_not_reload_while_disconnected(self):
        w=self.routing(False);w.connection_changed();w.refresh.assert_not_called()
    def test_clock_clears_export_and_rows_before_refresh(self):
        w=ClockWindow.__new__(ClockWindow);w.state={'old':True};w.save_button=Mock();w.summary=Mock()
        w.streams=Mock();w.registers=Mock();w.streams.get_children.return_value=['old'];w.registers.get_children.return_value=['code']
        w.refresh=Mock();w.connection_changed()
        self.assertIsNone(w.state);w.save_button.config.assert_called_once_with(state='disabled')
        w.streams.delete.assert_called_once_with('old');w.registers.delete.assert_called_once_with('code');w.refresh.assert_called_once()

if __name__=='__main__':unittest.main()
