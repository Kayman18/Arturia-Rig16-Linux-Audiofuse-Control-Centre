import copy,queue,unittest
from unittest.mock import patch
from af16rig import AF16Rig,DemoAF16Rig,DeviceError
from af16rig_gui import Worker
from channel_names import NAME_SOURCES,name_parameter
from test_name_edit import NameUSB
from test_mixer_scene import capture
import test_mixer_scene_window as windows
import mixer_scene as m
from mixer_scene_window import MixerSceneWindow

class SceneNamesTests(unittest.TestCase):
    @patch('name_edit.time.sleep')
    def test_native_all_60_name_addresses(self,sleep):
        usb=NameUSB();d=AF16Rig(usb);d.open();self.addCleanup(d.close);layout=m.topology(d)
        for source in NAME_SOURCES:
            a=dict(bus='names',source=source,stereo=False)
            before=m.read_entry(d,layout,a)['values']['name']
            usb.out.clear();text=f'Synth {source}'
            m.apply_entry(d,layout,dict(a,field='name',expected=before,values=[text]))
            payload=text.encode()+b'\0'
            self.assertEqual(usb.out,[(0x40,0x1a,name_parameter(source),0,payload,len(payload))])
            self.assertEqual(m.read_entry(d,layout,a)['values']['name'],[text])
    def test_all_legacy_formats_leave_names_unchanged(self):
        for fmt in (m.LEGACY_FORMAT,m.MASTER_FORMAT,m.ROUTING_FORMAT):
            d=DemoAF16Rig();saved=capture(d);saved['format']=fmt;saved['entries']=[e for e in saved['entries'] if e['bus']!='sample_rate']
            saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('speaker_ab','clock')]
            saved['entries']=[e for e in saved['entries'] if e['bus'] not in ('names','monitor','phones','speaker_b','outputs','inputs') and (fmt==m.ROUTING_FORMAT or e['bus']!='routing')]
            if fmt==m.LEGACY_FORMAT:
                for e in saved['entries']:
                    if e['source']==0:e['values']={'level':e['values']['level']}
            d.channel_names={1:'Changed'}
            self.assertEqual(m.plan(saved,capture(d)),[])
    def test_long_names_capture_but_block_changed_recall_before_writes(self):
        d=DemoAF16Rig();d.channel_names={1:'x'*31};saved=capture(d)
        self.assertEqual(m.plan(saved,capture(d)),[])
        d.channel_names[1]='New'
        with self.assertRaisesRegex(ValueError,'15-byte'):m.plan(saved,capture(d))
        helper=windows.MixerPageTests();p=helper.page();sets=[]
        saved['entries'][0]['values']['level']=[-256]
        p.refresh(saved);helper.drain(p,d,sets)
        self.assertFalse(sets);self.assertFalse(p.busy)
        self.assertIn('15-byte',p.message.config.call_args.kwargs['text'])
    def test_stale_name_and_invalid_values_block(self):
        d=DemoAF16Rig();layout=m.topology(d)
        c=dict(bus='names',source=1,stereo=False,field='name',expected=['Old'],values=['New'])
        with patch('mixer_scene.rename') as write:
            with self.assertRaises(DeviceError):m.apply_entry(d,layout,c)
            write.assert_not_called()
        saved=capture(d)
        for value in (None,1,'bad\ntext','x'*32):
            bad=copy.deepcopy(saved);next(e for e in bad['entries'] if e['bus']=='names')['values']['name']=[value]
            with self.assertRaises(ValueError):m.validate(bad)
    def test_incremental_name_recall_blank_utf8_and_last_order(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d);sets=[]
        for e in target['entries']:
            if e['bus']=='names':e['values']['name']=['' if e['source']==1 else 'Synthé']
        target['entries'][0]['values']['mute']=[1]
        p.refresh(target);helper.drain(p,d,sets);self.assertFalse(sets)
        p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),61);self.assertEqual(sets[0]['field'],'mute')
        self.assertEqual(m.plan(target,capture(d)),[])
        self.assertIn('Recall complete',p.message.config.call_args.kwargs['text'])
        self.assertEqual(MixerSceneWindow.db(dict(field='name',values=[''])),'(blank)')
    def test_final_capture_detects_name_side_effect(self):
        helper=windows.MixerPageTests();p=helper.page();d=DemoAF16Rig();target=capture(d);sets=[]
        next(e for e in target['entries'] if e['bus']=='names' and e['source']==92)['values']['name']=['New'];original=m.rename
        def write(*args):
            result=original(*args);d.channel_names[1]='Side effect';return result
        p.refresh(target);helper.drain(p,d,sets)
        with patch('mixer_scene.rename',side_effect=write):
            p.start_apply();helper.drain(p,d,sets)
        self.assertEqual(len(sets),1)
        self.assertIn('differ on final readback',p.message.config.call_args.kwargs['text'])
    def test_worker_publishes_name_cache_update(self):
        d=DemoAF16Rig();events=queue.Queue();w=Worker(events,factory=lambda:d);w.start()
        try:
            w.commands.put(('connect',None))
            while events.get(timeout=3)['kind']!='connected':pass
            c=dict(bus='names',source=1,stereo=False,field='name',expected=['Demo input 1'],values=['Synth'])
            w.commands.put(('scene_set',dict(scope='mixer',connection_serial=1,request_id='scene',layout=m.topology(d),change=c)))
            updated=False
            while True:
                event=events.get(timeout=3)
                if event['kind']=='auto_name' and event['state']['source']==1 and event['state']['candidate']=='Synth':updated=True
                if event['kind']=='scene_error':self.fail(event['message'])
                if event['kind']=='scene_written':break
            self.assertTrue(updated);self.assertEqual(event['request_id'],'scene')
        finally:w.stop_event.set();w.join(2)
