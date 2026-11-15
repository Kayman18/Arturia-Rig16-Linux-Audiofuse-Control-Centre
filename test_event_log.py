import json
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from event_log import EventLog
from event_log_window import EventLogWindow

class EventLogTests(unittest.TestCase):
    def test_meter_flood_cannot_evict_error(self):
        log=EventLog();log.capture(dict(kind='routing_error',message='Rejected'),3)
        for _ in range(2000):self.assertFalse(log.capture(dict(kind='meter_frame',state={'raw':[0]*118}),3))
        self.assertEqual(len(log.records),1);self.assertEqual(log.records[0]['message'],'Rejected')
    def test_repeat_count_keeps_first_and_last_times(self):
        log=EventLog();e=dict(kind='input_error',message='Timeout',channel=1)
        log.capture(e,4,'first');log.capture(e,4,'last')
        self.assertEqual(len(log.records),1);r=log.records[0]
        self.assertEqual((r['count'],r['first_time'],r['last_time']),(2,'first','last'))
    def test_different_channel_and_generation_are_separate(self):
        log=EventLog()
        for channel,serial in ((1,1),(2,1),(2,2)):log.capture(dict(kind='input_error',message='Timeout',channel=channel),serial)
        self.assertEqual(len(log.records),3)
    def test_event_generation_overrides_worker_generation(self):
        log=EventLog();log.capture(dict(kind='meter_error',message='Timeout',connection_serial=1),2)
        self.assertEqual(log.records[0]['connection_serial'],1)
    def test_readback_errors_are_retained(self):
        log=EventLog();log.capture(dict(kind='input_snapshot',state={'errors':{'gain':'Timeout'}}))
        self.assertEqual(log.records[0]['severity'],'error');self.assertIn('gain: Timeout',log.records[0]['message'])
    def test_name_read_failure_is_retained(self):
        log=EventLog();log.capture(dict(kind='auto_name',state={'status':'read_error','error':'USB failed'}))
        self.assertIn('USB failed',log.records[0]['message'])
    def test_normal_readbacks_not_logged(self):
        log=EventLog()
        for kind in ('snapshot','auto_name','masters_snapshot','input_snapshot'):
            self.assertFalse(log.capture(dict(kind=kind,state={'errors':{}})))
    def test_bounded_log_retains_latest_unique_events(self):
        log=EventLog(limit=3)
        for i in range(5):log.capture(dict(kind='error',message=str(i)))
        self.assertEqual([r['message'] for r in log.records],['2','3','4'])
    def test_clear_does_not_reuse_ids(self):
        log=EventLog();log.capture(dict(kind='error'));first=log.records[0]['id'];log.clear()
        log.capture(dict(kind='error'));self.assertGreater(log.records[0]['id'],first)
    def test_reconnect_and_discard_are_warnings(self):
        log=EventLog()
        for kind in ('reconnect_wait','commands_discarded'):log.capture(dict(kind=kind,count=3))
        self.assertEqual([r['severity'] for r in log.records],['warning','warning'])
        self.assertIn('3 pending',log.records[-1]['message'])
    def test_connection_events_retained_as_information(self):
        log=EventLog()
        for kind in ('connected','disconnected','reconnect_disabled'):log.capture(dict(kind=kind))
        self.assertTrue(all(r['severity']=='info' for r in log.records))
    def test_export_is_json_and_does_not_expose_mutable_records(self):
        log=EventLog();log.capture(dict(kind='error',message='Failed'))
        report=log.report(True);self.assertTrue(json.loads(json.dumps(report))['demo'])
        report['events'][0]['message']='changed';self.assertEqual(log.records[0]['message'],'Failed')

class LogWindowTests(unittest.TestCase):
    def window(self):
        w=EventLogWindow.__new__(EventLogWindow);w.app=SimpleNamespace(event_log=EventLog(),demo=True,log_button=Mock())
        w.table=Mock();w.detail=Mock();w.status=Mock();w.window=Mock();return w
    def test_refresh_preserves_unchanged_rows(self):
        w=self.window();w.app.event_log.capture(dict(kind='error',message='Failed'),now='now')
        r=w.app.event_log.records[0];w.table.selection.return_value=();w.table.get_children.return_value=['1'];w.table.exists.return_value=True
        w.table.item.return_value=('now','error','error','1','Failed')
        w.refresh();w.table.insert.assert_not_called();w.table.delete.assert_not_called()
        w.table.item.assert_called_once_with('1','values')
    def test_copy_uses_full_error_not_truncated_table_cell(self):
        w=self.window();message='Long error '+('details '*100);w.app.event_log.capture(dict(kind='error',message=message))
        w.table.selection.return_value=('1',);w.copy()
        copied=json.loads(w.window.clipboard_append.call_args.args[0]);self.assertEqual(copied['message'],message)
    def test_cancel_export_does_not_write(self):
        w=self.window()
        with patch('event_log_window.filedialog.asksaveasfilename',return_value=''),patch('event_log_window.Path') as path:
            w.save();path.assert_not_called()
    def test_save_failure_is_visible(self):
        w=self.window()
        with patch('event_log_window.filedialog.asksaveasfilename',return_value='/no/file'),patch('event_log_window.Path') as path:
            path.return_value.write_text.side_effect=OSError('Read only');w.save()
        self.assertIn('Could not save',w.status.config.call_args.kwargs['text'])
    def test_close_does_not_stop_worker_or_mixer(self):
        w=self.window();w.app.worker=Mock();w.close()
        self.assertIsNone(w.app.event_log_window);w.app.worker.stop_event.set.assert_not_called()

if __name__=='__main__':unittest.main()
