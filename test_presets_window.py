import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from mixer_view import Field
from presets_window import PresetsWindow


class PresetPageTests(unittest.TestCase):
    def page(self, slot=3):
        p = PresetsWindow.__new__(PresetsWindow)
        p.app = SimpleNamespace(connected=True, demo=False, info={'state_version':18}, name_cache=SimpleNamespace(serial=4), worker=SimpleNamespace(commands=queue.Queue()))
        p.serial=4; p.closed=False; p.busy=False; p.status={'current':2,'changed':1}
        p.records={s:dict(slot=s,name=f'Preset {s}') for s in range(9)}
        p.table=Mock(); p.table.selection.return_value=(str(slot),)
        p.window=Mock(); p.timer=None; p.request_id=100
        for name in ('refresh_button','load_button','save_button','rename_button','message','current'): setattr(p,name,Field())
        return p

    def test_factory_save_disabled(self):
        p=self.page(0); p.update_buttons()
        self.assertEqual(p.load_button.cget('state'),'normal')
        self.assertEqual(p.save_button.cget('state'),'disabled')
        with patch('presets_window.messagebox.askyesno') as dialog: p.action('save')
        dialog.assert_not_called(); self.assertTrue(p.app.worker.commands.empty())

    def test_cancel_load_sends_nothing(self):
        p=self.page()
        with patch('presets_window.messagebox.askyesno',return_value=False): p.action('load')
        self.assertTrue(p.app.worker.commands.empty()); self.assertFalse(p.busy)

    def test_confirm_save_has_concrete_slot_and_stale_guard(self):
        p=self.page()
        with patch('presets_window.messagebox.askyesno',return_value=True) as dialog: p.action('save')
        self.assertIn('3 — Preset 3',dialog.call_args.args[1])
        cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'preset_action'); self.assertEqual(data['action'],'save')
        self.assertEqual(data['expected_status'],{'current':2,'changed':1}); self.assertEqual(data['connection_serial'],4)
        self.assertTrue(p.busy)

    def test_disconnect_during_confirmation_prevents_command(self):
        p=self.page()
        def disconnect(*a,**kw): p.app.connected=False; return True
        with patch('presets_window.messagebox.askyesno',side_effect=disconnect): p.action('load')
        self.assertTrue(p.app.worker.commands.empty()); self.assertIsNone(p.status)

    def test_duplicate_click_while_busy_is_ignored(self):
        p=self.page(); p.busy=True
        with patch('presets_window.messagebox.askyesno') as dialog: p.action('load')
        dialog.assert_not_called(); self.assertTrue(p.app.worker.commands.empty())

    def test_failed_operation_disables_actions_preserves_error(self):
        p=self.page(); p.busy=True
        p.handle(dict(kind='preset_error',request_id=100,message='Save not confirmed'))
        self.assertIsNone(p.status); self.assertFalse(p.busy)
        self.assertEqual(p.message.cget('text'),'Save not confirmed')
        self.assertEqual(p.load_button.cget('state'),'disabled')
        self.assertEqual(p.save_button.cget('state'),'disabled')

    def test_wrong_request_cannot_complete_action(self):
        p=self.page(); p.busy=True
        p.handle(dict(kind='preset_error',request_id=99,message='Old error'))
        self.assertTrue(p.busy)

    def test_periodic_read_does_not_erase_operation_feedback(self):
        p=self.page(); p.message.config(text='Slot saved')
        p.handle(dict(kind='preset_status',request_id=100,connection_serial=4,status={'current':3,'changed':0}))
        self.assertEqual(p.message.cget('text'),'Slot saved')

    def test_status_poll_never_saves_or_loads(self):
        p=self.page(); p.tick()
        cmd,data=p.app.worker.commands.get_nowait(); self.assertEqual(cmd,'preset_status')

    def test_closed_page_does_not_poll(self):
        p=self.page(); p.closed=True; p.tick()
        self.assertTrue(p.app.worker.commands.empty())

    def test_background_poll_keeps_actions_available(self):
        p=self.page();p.update_buttons();p.tick()
        self.assertFalse(p.busy)
        self.assertEqual(p.save_button.cget('state'),'normal')
        with patch('presets_window.messagebox.askyesno',return_value=True):p.action('save')
        self.assertEqual(p.app.worker.commands.get_nowait()[0],'preset_status')
        self.assertEqual(p.app.worker.commands.get_nowait()[0],'preset_action')

    def test_unchanged_background_poll_does_not_reconfigure_buttons(self):
        p=self.page();p.set_status(p.status);p.update_buttons()
        for widget in (p.refresh_button,p.load_button,p.save_button,p.current):widget.config=Mock(wraps=widget.config)
        p.tick()
        p.handle(dict(kind='preset_status',request_id=p.poll_request,connection_serial=4,status=dict(p.status)))
        for widget in (p.refresh_button,p.load_button,p.save_button,p.current):widget.config.assert_not_called()

    def test_poll_reply_cannot_clear_pending_save(self):
        p=self.page();p.tick();poll_id=p.poll_request
        with patch('presets_window.messagebox.askyesno',return_value=True):p.action('save')
        p.handle(dict(kind='preset_status',request_id=poll_id,connection_serial=4,status={'current':2,'changed':1}))
        self.assertTrue(p.busy);self.assertEqual(p.save_button.cget('state'),'disabled')

    def test_background_poll_error_disables_controls(self):
        p=self.page();p.tick()
        p.handle(dict(kind='preset_error',request_id=p.poll_request,connection_serial=4,message='Read failed'))
        self.assertIsNone(p.status);self.assertEqual(p.save_button.cget('state'),'disabled')

    def test_rename_factory_disallowed(self):
        p=self.page(0);p.update_buttons()
        self.assertEqual(p.rename_button.cget('state'),'disabled')
        with patch('presets_window.simpledialog.askstring') as dialog:p.rename()
        dialog.assert_not_called()

    def test_rename_dialog_queues_guarded_explicit_edit(self):
        p=self.page()
        with patch('presets_window.simpledialog.askstring',return_value='Studio'):p.rename()
        cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'preset_rename');self.assertEqual(data['slot'],3)
        self.assertEqual(data['expected_name'],'Preset 3');self.assertEqual(data['name'],'Studio')

    def test_cancel_rename_no_write(self):
        p=self.page()
        with patch('presets_window.simpledialog.askstring',return_value=None):p.rename()
        self.assertTrue(p.app.worker.commands.empty());self.assertFalse(p.busy)

    def test_confirmed_rename_updates_only_the_selected_row(self):
        p=self.page();p.busy=True
        p.handle(dict(kind='preset_renamed',request_id=100,connection_serial=4,status=dict(p.status),
                      result=dict(record=dict(slot=3,name='Studio'),demo=False,write_requests=1)))
        p.table.item.assert_called_once_with('3',values=(3,'Studio','Load / Save'))
        p.table.delete.assert_not_called();self.assertEqual(p.records[3]['name'],'Studio')

    def test_rename_button_does_not_flicker_on_background_poll(self):
        p=self.page();p.update_buttons();p.rename_button.config=Mock(wraps=p.rename_button.config)
        p.tick();p.handle(dict(kind='preset_status',request_id=p.poll_request,connection_serial=4,status=dict(p.status)))
        p.rename_button.config.assert_not_called()


if __name__=='__main__': unittest.main()
