"""New console bindings: actual snapshots, dispatch, stale guards, read-only polls."""
import queue
import time
import unittest
from types import SimpleNamespace
from af16rig import DemoAF16Rig, AF16Rig, PARAMETERS
from af16rig_gui import Worker
from mixer_view import ChannelController, MasterController, Field
from test_controls import FakeUSB

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.commands=queue.Queue()
        self.app=SimpleNamespace(connected=True,info={'state_version':18},message=Field(),worker=SimpleNamespace(commands=self.commands))
        self.device=DemoAF16Rig()
        self.controller=ChannelController(self.app,'main',1)
        self.controller.handle({'kind':'input_snapshot','state':self.device.mix_channel_snapshot('main',1)})
    def command(self):return self.commands.get_nowait()
    def test_loading_does_not_write(self):
        self.assertTrue(self.commands.empty())
        self.assertEqual(self.controller.state['level_db'],-12)
    def test_mute_waits_for_readback_and_prevents_duplicate(self):
        c=self.controller;c.toggle();c.toggle()
        self.assertEqual(self.command(),('mix_channel_mute',('main',1,True)))
        self.assertTrue(self.commands.empty());self.assertEqual(c.state['mute'],0)
        c.handle({'kind':'input_written','channel':'mix_channel','bus':'main','source':1,'name':'mute','actual':1})
        self.assertFalse(c.pending);self.assertEqual(c.state['mute'],1)
    def test_solo_dispatch(self):
        self.controller.toggle('solo')
        self.assertEqual(self.command(),('mix_channel_solo',('main',1,True)))
    def test_fader_dispatch(self):
        self.controller.step(-1)
        self.assertEqual(self.command(),('mix_channel_level',('main',1,-1)))
    def test_send_dispatch(self):
        self.controller.step_send(4,1)
        self.assertEqual(self.command(),('send_level',('main',1,4,1)))
    def test_send_mute_dispatch(self):
        self.controller.toggle_send(2)
        self.assertEqual(self.command(),('send_mute',('main',1,2,True)))
    def test_pan_dispatch(self):
        self.controller.adjust_pan('R step')
        self.assertEqual(self.command(),('adjust_pan',('main',1,'R step')))
    def test_stale_disables_writes(self):
        c=self.controller
        c.handle({'kind':'input_error','channel':'mix_channel','message':'timeout'})
        c.step(1);c.toggle();c.step_send(1,1);c.adjust_pan('Left')
        self.assertTrue(self.commands.empty())
    def test_disconnected_disables_writes(self):
        self.app.connected=False;self.controller.refresh();self.controller.toggle()
        self.assertTrue(self.commands.empty())
    def test_other_bus_snapshot_is_ignored(self):
        self.controller.handle({'kind':'input_snapshot','state':self.device.mix_channel_snapshot('cue',1)})
        self.assertEqual(self.controller.state['bus'],'main')
    def test_cue_send_controls_disabled(self):
        c=ChannelController(self.app,'cue',1)
        c.handle({'kind':'input_snapshot','state':self.device.mix_channel_snapshot('cue',1)})
        c.step_send(1,1);c.toggle_send(1)
        self.assertTrue(self.commands.empty())
    def stereo(self):
        usb=FakeUSB();usb.values[PARAMETERS['main_channel_show']]=3
        usb.values[PARAMETERS['main_channel_stereo']]=254
        d=AF16Rig(usb);d.open()
        c=ChannelController(self.app,'main',3)
        c.handle({'kind':'input_snapshot','state':d.mix_channel_snapshot('main',3)})
        d.close();return c
    def test_stereo_mute_dispatch(self):
        self.stereo().toggle()
        self.assertEqual(self.command(),('mix_channel_pair',('main',3,'mute',True)))
    def test_stereo_level_dispatch(self):
        self.stereo().step(-1)
        self.assertEqual(self.command(),('stereo_level',('main',3,-1)))
    def test_stereo_send_dispatch(self):
        self.stereo().step_send(2,-1)
        self.assertEqual(self.command(),('pair_send_level',('main',3,2,-1)))
    def test_stereo_pan_disabled(self):
        self.stereo().adjust_pan('Left');self.assertTrue(self.commands.empty())
    def test_master_dispatch(self):
        c=MasterController(self.app)
        c.handle({'kind':'input_snapshot','state':self.device.mixer_masters_snapshot()})
        c.step('main',-1)
        self.assertEqual(self.command(),('master_step',('main',-1)))
    def test_master_pre_dispatch(self):
        c=MasterController(self.app)
        c.handle({'kind':'input_snapshot','state':self.device.mixer_masters_snapshot()})
        c.toggle_pre('aux2')
        self.assertEqual(self.command(),('aux_pre',('aux2',True)))
    def test_worker_console_reads_without_writes(self):
        usb=FakeUSB();out=queue.Queue();worker=Worker(out,factory=lambda:AF16Rig(usb));worker.start()
        try:
            worker.commands.put(('connect',None))
            worker.commands.put(('console_read',('main',3)))
            worker.commands.put(('console_read',('main',0)))
            snapshots=[];deadline=time.monotonic()+3
            while len(snapshots)<2 and time.monotonic()<deadline:
                event=out.get(timeout=3)
                if event['kind']=='console_snapshot':snapshots.append(event)
            self.assertEqual([s['source'] for s in snapshots],[3,0])
            self.assertFalse(any(call[0]==0x40 for call in usb.calls))
        finally:
            worker.stop_event.set();worker.join(2)

if __name__=='__main__':unittest.main()
