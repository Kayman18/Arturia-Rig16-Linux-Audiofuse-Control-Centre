import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from af16rig import AF16Rig,DeviceDisconnected
from channel_names import decode_words,read_word,read_one,MAX_WORDS,report
from test_controls import FakeUSB
from names_window import NamesWindow

def packed(text):
    raw=text.encode('utf-8')+b'\0\0'
    if len(raw)%2:raw+=b'\0'
    return [int.from_bytes(raw[i:i+2],'little') for i in range(0,len(raw),2)]

class NamesTests(unittest.TestCase):
    def test_packed_ascii(self):self.assertEqual(decode_words(packed('UB-Xa'))['candidate'],'UB-Xa')
    def test_byte_words(self):self.assertEqual(decode_words([ord(c) for c in 'OXI ONE']+[0])['candidate'],'OXI ONE')
    def test_utf8(self):self.assertEqual(decode_words(packed('Synth é'))['candidate'],'Synth é')
    def test_one_character(self):self.assertEqual(decode_words([65,0])['candidate'],'A')
    def test_blank(self):self.assertEqual(decode_words([0])['status'],'blank')
    def test_invalid_data_not_labels(self):
        for words in ([65535,0],[1,0],[0x4241]*16):self.assertIsNone(decode_words(words)['candidate'])
    def test_terminator_required(self):self.assertEqual(decode_words([0x4241])['status'],'unterminated')
    def test_two_stable_passes(self):
        words=packed('M8');reader=lambda d,p,i:words[i]
        r=read_one(None,1,reader);self.assertEqual(r['candidate'],'M8');self.assertEqual(r['passes'],[words,words])
    def test_changes_not_accepted(self):
        reader=Mock(side_effect=[65,0,66,0]);r=read_one(None,1,reader)
        self.assertEqual(r['status'],'changed_during_read');self.assertIsNone(r['candidate'])
    def test_read_bound(self):
        reader=Mock(return_value=0x4141);r=read_one(None,1,reader)
        self.assertEqual(reader.call_count,MAX_WORDS*2);self.assertEqual(r['status'],'unterminated')
    def test_usb_is_input_only_exact_request(self):
        usb=FakeUSB();d=AF16Rig(usb);d.open();calls=[];words=packed('FM-1')
        def transfer(h,bm,req,param,index,data,length,timeout):
            calls.append((bm,req,param,index,length));word=words[index];data[0]=word&255;data[1]=word>>8;return 2
        usb.libusb_control_transfer.func=transfer
        r=read_one(d,16);d.close()
        self.assertEqual(r['candidate'],'FM-1');self.assertTrue(all(bm==0xc0 and req==0x92 and param==15 and length==2 for bm,req,param,idx,length in calls))
    def test_short_transfer_preserves_error(self):
        usb=FakeUSB();d=AF16Rig(usb);d.open();usb.libusb_control_transfer.func=lambda *args:1
        r=read_one(d,1);d.close();self.assertEqual(r['status'],'read_error');self.assertEqual(r['passes'],[[]])
    def test_disconnection_propagates(self):
        reader=Mock(side_effect=DeviceDisconnected('gone'))
        with self.assertRaises(DeviceDisconnected):read_one(None,1,reader)
    def test_only_known_name_parameters(self):
        for p,i in [(60,0),(-1,0),(0,16),(True,0)]:
            with self.assertRaises(ValueError):read_word(None,p,i)
    def test_report_retains_raw_without_claiming_verification(self):
        record=read_one(None,1,lambda d,p,i:[65,0][i]);r=report([record])
        self.assertEqual(r['write_requests'],0);self.assertFalse(r['physical_text_format_verified']);self.assertEqual(r['names'][0]['passes'],[[65,0],[65,0]])
    def test_ui_stops_after_first_error(self):
        w=NamesWindow.__new__(NamesWindow);w.request_id=10;w.pending=True;w.records=[];w.table=Mock();w.finish=Mock();w.next_read=Mock()
        w.handle(dict(kind='name_snapshot',request_id=10,state=dict(source=1,status='read_error',candidate=None,error='stall')))
        w.next_read.assert_not_called();w.finish.assert_called_once()
    def test_ui_ignores_old_session_events(self):
        w=NamesWindow.__new__(NamesWindow);w.request_id=10;w.pending=True;w.records=[]
        w.handle(dict(kind='name_snapshot',request_id=9,state={}))
        self.assertEqual(w.records,[])

if __name__=='__main__':unittest.main()
