import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig_gui import Worker
from mixer_view import Console

class StartupSpeedTests(unittest.TestCase):
    def worker(self):
        w=Worker.__new__(Worker)
        w.commands=queue.Queue();w.stop_event=Mock();w.stop_event.is_set.return_value=False
        w.names_paused=False;w.names_scan=Mock(done=False);w.names_scan.step.return_value=None
        w.next_poll=100;w.input_channel=None;w.input_next_poll=100
        w.meters_enabled=True;w.meters_failed=False;w.next_meter=100
        w.connection_serial=3;w.emit=Mock()
        return w
    def test_idle_slice_reads_eight_words_without_extra_queue_waits(self):
        w=self.worker()
        with patch('af16rig_gui.time.monotonic',return_value=1):w.read_name_slice()
        self.assertEqual(w.names_scan.step.call_count,8)
    def test_yields_immediately_to_queued_command(self):
        w=self.worker();w.commands.put(('set',None))
        with patch('af16rig_gui.time.monotonic',return_value=1):w.read_name_slice()
        w.names_scan.step.assert_not_called()
    def test_yields_to_due_live_polling(self):
        for attr in ('next_meter','next_poll','input_next_poll'):
            w=self.worker();w.input_channel=1;setattr(w,attr,0)
            with patch('af16rig_gui.time.monotonic',return_value=1):w.read_name_slice()
            w.names_scan.step.assert_not_called()
    def test_slow_word_ends_slice(self):
        w=self.worker()
        with patch('af16rig_gui.time.monotonic',side_effect=[1,1,1.010]):w.read_name_slice()
        self.assertEqual(w.names_scan.step.call_count,1)
    def test_new_command_between_words_stops_slice(self):
        w=self.worker();w.names_scan.step.side_effect=lambda:w.commands.put(('set',None))
        with patch('af16rig_gui.time.monotonic',return_value=1):w.read_name_slice()
        self.assertEqual(w.names_scan.step.call_count,1)
    def test_completed_name_emits_once_and_stops_at_end(self):
        w=self.worker()
        def done():w.names_scan.done=True;return {'source':1}
        w.names_scan.step.side_effect=done
        with patch('af16rig_gui.time.monotonic',return_value=1):w.read_name_slice()
        w.emit.assert_called_once_with('auto_name',connection_serial=3,state={'source':1})
    def test_initial_stereo_readbacks_relayout_once_per_pass(self):
        v=SimpleNamespace(inflight=None,bus='main',bank_start=1,loading_layout=True,
            controllers={i:SimpleNamespace(state={},handle=Mock()) for i in range(1,35)},
            master=Mock(),layout=Mock())
        for i in (1,3,5,7,9,11,13,15,33):
            v.controllers[i].state={'stereo_members':[i,i+1]}
            Console.handle(v,dict(kind='console_snapshot',bus='main',source=i,state=v.controllers[i].state))
        v.layout.assert_not_called()
        Console.handle(v,dict(kind='console_snapshot',bus='main',source=0,state={}))
        v.layout.assert_called_once();self.assertFalse(v.loading_layout)
        Console.handle(v,dict(kind='console_snapshot',bus='main',source=1,state={}))
        self.assertEqual(v.layout.call_count,2)

if __name__=='__main__':unittest.main()
