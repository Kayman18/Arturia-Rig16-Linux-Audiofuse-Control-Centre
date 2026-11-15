import queue
import time
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from af16rig import DemoAF16Rig,DeviceError,DeviceDisconnected
from af16rig_gui import Worker
from mixer_view import ChannelController,MasterController

class MeterFairnessTests(unittest.TestCase):
    def worker(self):
        w=Worker(queue.Queue(),demo=True);w.device=DemoAF16Rig();w.meters_enabled=True
        return w
    def test_due_meter_runs_with_queued_commands_and_honours_interval(self):
        w=self.worker();w.commands.put(('masters_read',None))
        with patch('af16rig_gui.time.monotonic',return_value=10):
            w.poll_meter_if_due();w.poll_meter_if_due()
        self.assertEqual(w.output.get_nowait()['kind'],'meter_frame')
        self.assertTrue(w.output.empty());self.assertEqual(w.commands.qsize(),1)
        self.assertEqual(w.next_meter,10.05)
    def test_disabled_paused_and_failed_meter_do_not_read(self):
        for key,value in [('meters_enabled',False),('names_paused',True),('meters_failed',True),('device',None)]:
            w=self.worker();setattr(w,key,value);w.poll_meter_if_due()
            self.assertTrue(w.output.empty())
    def test_meter_error_does_not_become_command_error(self):
        w=self.worker();w.device=Mock()
        with patch('meters.read_frame',side_effect=DeviceError('meter failed')):w.poll_meter_if_due()
        self.assertEqual(w.output.get_nowait()['kind'],'meter_error');self.assertTrue(w.meters_failed)
    def test_disconnect_is_propagated(self):
        w=self.worker();w.device=Mock()
        with patch('meters.read_frame',side_effect=DeviceDisconnected('gone')):
            with self.assertRaises(DeviceDisconnected):w.poll_meter_if_due()
    def test_busy_worker_delivers_meter_frames_between_snapshot_commands(self):
        class SlowDemo(DemoAF16Rig):
            def mixer_masters_snapshot(self):
                time.sleep(.015)
                return super().mixer_masters_snapshot()
        events=queue.Queue();w=Worker(events,factory=SlowDemo);w.meters_enabled=True;w.start()
        try:
            w.commands.put(('connect',None))
            while events.get(timeout=3)['kind']!='connected':pass
            for _ in range(80):w.commands.put(('masters_read',None))
            completed=0;meter_positions=[]
            while completed<60:
                event=events.get(timeout=3)
                self.assertNotIn(event['kind'],('error','meter_error','masters_error'))
                if event['kind']=='masters_snapshot':completed+=1
                if event['kind']=='meter_frame':meter_positions.append(completed)
            self.assertGreaterEqual(len(meter_positions),8)
            self.assertTrue(any(10<p<50 for p in meter_positions))
            self.assertGreater(w.commands.qsize(),0)
        finally:w.stop_event.set();w.join(3)
    def test_master_channel_normal_status_is_identical_but_errors_are_preserved(self):
        app=SimpleNamespace(message=Mock())
        channel=ChannelController(app,'main',1);master=MasterController(app)
        channel.refresh=Mock();master.refresh=Mock()
        channel.handle(dict(kind='input_snapshot',state=dict(channel='mix_channel',bus='main',source=1)))
        first=app.message.config.call_args.kwargs['text']
        master.handle(dict(kind='input_snapshot',state=dict(channel='masters')))
        self.assertEqual(app.message.config.call_args.kwargs['text'],first)
        self.assertEqual(first,'Live mixer readback')
        master.handle(dict(kind='input_snapshot',state=dict(channel='masters',errors={'read':'Read failed'})))
        self.assertEqual(app.message.config.call_args.kwargs['text'],'Read failed')

if __name__=='__main__':unittest.main()
