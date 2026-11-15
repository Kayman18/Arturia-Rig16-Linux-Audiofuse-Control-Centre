import unittest,queue
from unittest.mock import Mock,patch
from types import SimpleNamespace
from af16rig import DemoAF16Rig,DeviceError
from preamp import snapshot,change_pad
import test_preamp as base
import strip_pad

class StripPadTests(unittest.TestCase):
    def test_all_analog_mono_channels_on_off(self):
        d=DemoAF16Rig()
        for front in (False,True):
            d.force_rear=0 if front else 3
            for ch in range(1,17):
                for target in (1,0):
                    s=snapshot(d,ch);change_pad(d,ch,False,[(s['kind'],s['pad'])])
                    self.assertEqual(snapshot(d,ch)['pad'],target)
    def test_rear_polarity_and_unrelated_bits(self):
        b=base.PreampTests();d,u=b.device();self.addCleanup(d.close)
        from af16rig import PARAMETERS
        key=PARAMETERS['rear_pad'];u.values[key]=65535
        self.assertEqual(snapshot(d,5)['pad'],0)
        # Existing writer preserves all other bits and implements active-low PAD.
        d.write_input_bool(5,'pad',True)
        self.assertEqual([(c[1],c[2],c[3],c[4]) for c in u.calls if c[0]==0x40],[(0x11,68,4,b'\x00\x00')])
        u.values[key]=65535^(1<<4)
        self.assertEqual([snapshot(d,ch)['pad'] for ch in range(1,17)],[int(ch==5) for ch in range(1,17)])
    def test_linked_mixed_pair_on_then_off(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1;d.inputs[1]['pad']=1
        for target in (1,0):
            states=[snapshot(d,ch) for ch in (1,2)]
            result=change_pad(d,1,True,[(s['kind'],s['pad']) for s in states])
            self.assertEqual([s['pad'] for s in result],[target,target])
    def test_stale_source_pad_and_link_block(self):
        d=DemoAF16Rig()
        for expected,stereo in [([('line',0)],False),([('rear',1)],False),([('rear',0),('rear',0)],True)]:
            with self.assertRaises(DeviceError):change_pad(d,1,stereo,expected)
        self.assertEqual(d.inputs[1]['pad'],0)
    def test_second_write_failure_does_not_retry_first(self):
        d=DemoAF16Rig();d.main_show=65532;d.main_stereo=1
        original=d.write_input_bool
        def write(ch,name,value):
            if ch==2:raise DeviceError('rejected')
            return original(ch,name,value)
        with patch.object(d,'write_input_bool',side_effect=write) as call:
            with self.assertRaises(DeviceError):change_pad(d,1,True,[('rear',0),('rear',0)])
            self.assertEqual(call.call_count,2)
        self.assertEqual([d.inputs[ch]['pad'] for ch in (1,2)],[1,0])
    def test_ui_pending_and_digital_guard(self):
        d=DemoAF16Rig();dash=SimpleNamespace(preamp_states={1:snapshot(d,1)},preamp_pending=set())
        c=SimpleNamespace(source=SimpleNamespace(get=lambda:1),bus=SimpleNamespace(get=lambda:'main'),state={},stale=False,app=SimpleNamespace(connected=True,dashboard=dash,worker=SimpleNamespace(commands=queue.Queue())))
        strip=SimpleNamespace(c=c,pad=Mock());strip.pad.cget.return_value=None
        strip_pad.toggle(strip);strip_pad.toggle(strip)
        self.assertEqual(c.app.worker.commands.qsize(),1)
        self.assertEqual(c.app.worker.commands.get()[0],'preamp_pad')
        c.source.get=lambda:33;strip_pad.toggle(strip)
        self.assertTrue(c.app.worker.commands.empty())

if __name__=='__main__':unittest.main()
