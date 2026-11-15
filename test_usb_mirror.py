import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from mixer_layout import bank_sources,strip_widths
from mixer_view import Console,Field

class USBMirrorTests(unittest.TestCase):
    def console(self):
        c=Console.__new__(Console);c.bank_start=1;c.bus='main';c.inflight=None
        c.controllers={i:SimpleNamespace(state={},handle=Mock()) for i in bank_sources(1)}
        c.master=SimpleNamespace(handle=Mock());c.layout=Mock();return c
    def test_main_analog_appends_only_usb_one_two(self):
        self.assertEqual(bank_sources(1),list(range(1,17))+[33,34])
        self.assertEqual(bank_sources(1,'cue'),list(range(1,17)))
        for start in (17,33,49):self.assertEqual(bank_sources(start),list(range(start,start+16)))
    def test_poll_continues_from_analog_to_mirrored_usb_then_master(self):
        c=self.console()
        for source,want in ((16,33),(33,34),(34,0),(0,1)):
            c.handle(dict(kind='console_snapshot',bus='main',source=source,state={}))
            self.assertEqual(c.next_source,want)
    def test_stereo_pairs_skip_partner_without_skipping_mirror(self):
        c=self.console();c.controllers[15].state={'stereo_members':[15,16]}
        c.controllers[33].state={'stereo_members':[33,34]}
        for source,want in ((15,33),(33,0)):
            c.handle(dict(kind='console_snapshot',bus='main',source=source,state={}))
            self.assertEqual(c.next_source,want)
    def test_mirror_read_updates_same_usb_controller(self):
        c=self.console();usb=c.controllers[33];state={'source':33,'bus':'main'}
        c.handle(dict(kind='console_snapshot',bus='main',source=33,state=state))
        usb.handle.assert_called_with(dict(kind='input_snapshot',state=state))
        c.bank_start=33
        c.handle(dict(kind='console_snapshot',bus='main',source=33,state=state))
        self.assertIs(c.controllers[33],usb);self.assertEqual(usb.handle.call_count,2)
    def test_linked_mirror_is_one_strip_before_master(self):
        c=self.console();c.layout=Console.layout.__get__(c);c.resize=Mock();c.visible=[];c.bus_buttons={}
        c.strips={i:SimpleNamespace(frame=Mock(),preamp=SimpleNamespace(source_button=None,source_slot=Field())) for i in c.controllers}
        c.master_view=SimpleNamespace(frame=Mock())
        c.controllers[33].state={'stereo_members':[33,34]};c.layout()
        self.assertEqual(c.visible,list(range(1,17))+[33])
        c.controllers[33].state={};c.layout()
        self.assertEqual(c.visible,list(range(1,17))+[33,34])
    def test_mirror_failure_does_not_stall_poll_cycle(self):
        c=self.console()
        c.handle(dict(kind='console_error',bus='main',source=33,message='Read failed'))
        self.assertEqual(c.next_source,34)
    def test_scaled_master_minimum_and_exact_window_fill(self):
        for total in (1000,1280,1920,2560):
            for n in (8,9,12,16,18):
                for minimum in (170,220,280):
                    widths,master=strip_widths(total,n,minimum)
                    self.assertGreaterEqual(master,minimum)
                    self.assertEqual(sum(widths)+master+3*n+5,total)
                    self.assertGreater(min(widths),0)

if __name__=='__main__':unittest.main()
