import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from quick_names import rename_targets,rename_input,finish_rename
from mixer_view import Strip,Field

class QuickNameTests(unittest.TestCase):
    def app(self):
        return SimpleNamespace(connected=True,info={'state_version':18},demo=True,root=Mock(),message=Mock(),
                               name_cache=SimpleNamespace(serial=5,records={1:dict(status='demo',candidate='Old synth')}),
                               worker=SimpleNamespace(commands=queue.Queue()))
    def test_only_real_input_name_slots_are_exposed(self):
        for source in (0,33,64,65,True,'1'):self.assertEqual(rename_targets(source,True),())
        self.assertEqual(rename_targets(1,True),(1,2));self.assertEqual(rename_targets(31,True),(31,32))
        self.assertEqual(rename_targets(2,False),(2,))
    def test_one_guarded_worker_request_with_expected_value(self):
        a=self.app()
        with patch('quick_names.simpledialog.askstring',return_value='New synth'):rename_input(a,1)
        command,data=a.worker.commands.get_nowait();self.assertEqual(command,'name_set')
        self.assertEqual((data['source'],data['expected'],data['name'],data['connection_serial']),(1,'Old synth','New synth',5))
        self.assertEqual(data['request_id'],a.quick_name_request)
        self.assertEqual(a.name_cache.records[1]['candidate'],'Old synth')
    def test_cancel_and_unchanged_names_never_write(self):
        for value in (None,'Old synth'):
            a=self.app()
            with patch('quick_names.simpledialog.askstring',return_value=value):rename_input(a,1)
            self.assertTrue(a.worker.commands.empty())
    def test_utf8_limit_and_control_chars_are_validated(self):
        for value in ('é'*8,'a\nb'):
            a=self.app()
            with patch('quick_names.simpledialog.askstring',return_value=value),patch('quick_names.messagebox.showerror') as error:
                rename_input(a,1);error.assert_called_once()
            self.assertTrue(a.worker.commands.empty())
    def test_disconnect_or_new_connection_during_dialog_cancels_write(self):
        for changed in ('connected','serial','version'):
            a=self.app()
            def dialog(*args,**kwargs):
                if changed=='connected':a.connected=False
                elif changed=='serial':a.name_cache.serial=6
                else:a.info['state_version']=19
                return 'New'
            with patch('quick_names.simpledialog.askstring',side_effect=dialog):rename_input(a,1)
            self.assertTrue(a.worker.commands.empty())
    def test_busy_and_unsupported_sources_do_not_open_dialog(self):
        for source,pending in ((33,None),(1,123)):
            a=self.app();a.quick_name_request=pending
            with patch('quick_names.simpledialog.askstring') as dialog:rename_input(a,source);dialog.assert_not_called()
    def test_unread_name_requires_readback_before_dialog(self):
        a=self.app();a.name_cache.records={}
        with patch('quick_names.simpledialog.askstring') as dialog:rename_input(a,1);dialog.assert_not_called()
        self.assertTrue(a.worker.commands.empty());a.message.config.assert_called_once()
    def test_success_message_only_for_matching_request(self):
        a=self.app();a.quick_name_request=20
        finish_rename(a,dict(kind='name_written',request_id=19));a.message.config.assert_not_called()
        finish_rename(a,dict(kind='name_written',request_id=20));self.assertIsNone(a.quick_name_request)
        self.assertIn('Demo',a.message.config.call_args.kwargs['text'])
    def test_failed_rename_is_reported_without_retry(self):
        a=self.app();a.quick_name_request=20
        finish_rename(a,dict(kind='name_write_error',request_id=20,message='Name changed on device'))
        self.assertIsNone(a.quick_name_request);self.assertTrue(a.worker.commands.empty())
        self.assertEqual(a.message.config.call_args.kwargs['text'],'Name changed on device')
    def test_connection_and_preset_events_clear_pending(self):
        for kind in ('connected','disconnected','error','preset_state_reset'):
            a=self.app();a.quick_name_request=20;finish_rename(a,dict(kind=kind));self.assertIsNone(a.quick_name_request)
    def test_empty_name_uses_existing_blank_name_support(self):
        a=self.app()
        with patch('quick_names.simpledialog.askstring',return_value=''):rename_input(a,1)
        self.assertEqual(a.worker.commands.get_nowait()[1]['name'],'')
    def test_stereo_menu_renames_only_chosen_side(self):
        app=self.app();strip=SimpleNamespace(c=SimpleNamespace(source=Field(1),state={'stereo_members':[1,2]},app=app),title=Mock())
        with patch('mixer_view.tk.Menu') as menu,patch('quick_names.rename_input') as rename:
            Strip.rename_title(strip,SimpleNamespace(x_root=10,y_root=20))
            commands=[call.kwargs['command'] for call in menu.return_value.add_command.call_args_list]
            self.assertEqual(len(commands),2);rename.assert_not_called()
            commands[1]();rename.assert_called_once_with(app,2)
    def test_mono_title_opens_directly_and_usb_does_nothing(self):
        app=self.app();strip=SimpleNamespace(c=SimpleNamespace(source=Field(17),state={},app=app))
        with patch('quick_names.rename_input') as rename:
            Strip.rename_title(strip,None);rename.assert_called_once_with(app,17)
            rename.reset_mock();strip.c.source.set(33);Strip.rename_title(strip,None);rename.assert_not_called()

if __name__=='__main__':unittest.main()
