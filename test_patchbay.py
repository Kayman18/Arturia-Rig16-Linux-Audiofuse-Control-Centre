import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from mixer_view import Field
from patchbay_window import PatchBayWindow,source_bank,destination_bank
from routing_labels import SOURCE_LABELS


class PatchBayTests(unittest.TestCase):
    def panel(self):
        p=PatchBayWindow.__new__(PatchBayWindow)
        p.app=SimpleNamespace(connected=True,demo=False,worker=SimpleNamespace(commands=queue.Queue()))
        p.state=dict(status='stable',state_version=18,connection_serial=3,reads={'second':{'values':{'output_source[0]':192,'output_source[1]':193,'output_source[2]':64},'errors':{}}})
        p.pending=False;p.editable=True;p.undo_record=None;p.batch=None;p.batch_done=0;p.notice='';p.previous=None;p.request_id=None
        p.selected_destination=None;p.armed_source=None;p.drag_source=None;p.source_points={};p.destination_points={}
        p.source_filter=Field('Connected');p.destination_filter=Field('Physical')
        p.source_choices={f'{name} ({code})':code for code,name in SOURCE_LABELS.items()};p.source_choice=Field('')
        for name in ('source_menu','route_label','apply_button','undo_button','preset_save_button','preset_load_button','refresh_button','save_button','message','count_label'):setattr(p,name,Field())
        p.canvas=Mock();p.canvas.winfo_width.return_value=1200;p.canvas.winfo_height.return_value=700
        p.canvas.canvasx.side_effect=lambda x:x;p.canvas.canvasy.side_effect=lambda y:y
        return p

    def test_drag_target_uses_existing_stale_and_connection_guards(self):
        p=self.panel();p.patch(128,0)
        cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual(cmd,'routing_set');self.assertEqual(data['source_code'],128)
        self.assertEqual(data['expected_source'],192);self.assertEqual(data['connection_serial'],3)
        self.assertEqual(p.routes()[0],192);self.assertTrue(p.pending)

    def test_identical_route_sends_nothing(self):
        p=self.panel();p.patch(192,0);self.assertTrue(p.app.worker.commands.empty())

    def test_unknown_and_unread_routes_are_not_written(self):
        for destination,source in ((60,128),(5,128),(0,999)):
            p=self.panel();p.patch(source,destination);self.assertTrue(p.app.worker.commands.empty())
        p=self.panel();p.state['reads']['second']['values']['output_source[0]']=999
        p.patch(128,0);self.assertTrue(p.app.worker.commands.empty())

    def test_busy_disconnected_unstable_and_version_mismatch_block_writes(self):
        for mode in ('busy','disconnected','unstable','version'):
            p=self.panel()
            if mode=='busy':p.pending=True
            if mode=='disconnected':p.app.connected=False
            if mode=='unstable':p.state['status']='changed'
            if mode=='version':p.state['state_version']=19
            p.patch(128,0);self.assertTrue(p.app.worker.commands.empty())

    def test_connected_filter_shows_current_physical_routes(self):
        p=self.panel();p.draw()
        self.assertEqual(set(p.source_points),{192,193,64})
        self.assertEqual(set(p.destination_points),set(range(12)))

    def test_filters_expose_all_verified_banks_without_fabricated_jacks(self):
        p=self.panel();p.source_filter.set('USB');p.destination_filter.set('ADAT');p.draw()
        self.assertEqual(set(p.source_points),set(range(128,160)))
        self.assertEqual(set(p.destination_points),set(range(12,28)))
        self.assertEqual(source_bank(194),'Mix buses');self.assertEqual(destination_bank(10),'Physical')

    def test_click_source_then_destination_patches(self):
        p=self.panel();p.hit=Mock(side_effect=[('source',128),('dest',0)])
        p.press(SimpleNamespace());self.assertEqual(p.armed_source,128)
        p.release=Mock() # Click workflow is independent of drag release.
        p.press(SimpleNamespace());self.assertEqual(p.app.worker.commands.get_nowait()[0],'routing_set')

    def test_drag_release_only_accepts_destination(self):
        p=self.panel();p.drag_source=128;p.hit=Mock(return_value=('dest',0))
        p.release(SimpleNamespace());self.assertEqual(p.app.worker.commands.get_nowait()[0],'routing_set')
        p=self.panel();p.drag_source=128;p.hit=Mock(return_value=None)
        p.release(SimpleNamespace());self.assertTrue(p.app.worker.commands.empty())

    def test_route_selection_does_not_write(self):
        p=self.panel();p.hit=Mock(return_value=('route',0));p.press(SimpleNamespace())
        self.assertEqual(p.selected_route(),(0,192));self.assertTrue(p.app.worker.commands.empty())

    def test_undo_uses_readback_expected_value(self):
        p=self.panel();p.undo_record=(0,64,192);p.update_editor();p.undo_route()
        cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual(data['source_code'],64);self.assertEqual(data['expected_source'],192);self.assertTrue(data['undo'])

    def test_error_keeps_old_cable_and_requires_read(self):
        p=self.panel();p.patch(128,0)
        p.handle(dict(kind='routing_error',request_id=p.request_id,message='Write not confirmed'))
        self.assertEqual(p.routes()[0],192);self.assertFalse(p.editable)
        self.assertIn('Write not confirmed',p.message.cget('text'))

    def test_clear_selection_cannot_disconnect_hardware(self):
        p=self.panel();p.selected_destination=0;p.armed_source=128;p.clear_selection()
        self.assertIsNone(p.selected_destination);self.assertTrue(p.app.worker.commands.empty())

    def test_motion_renders_solid_cable_and_free_plug_without_usb_write(self):
        p=self.panel();p.draw();p.drag_source=128;p.source_points[128]=(235,100)
        p.hit=Mock(return_value=None);p.cable=Mock();p.plug=Mock()
        p.motion(SimpleNamespace(x=600,y=250))
        self.assertEqual(p.cable.call_args.args[:4],(235,100,600,250))
        self.assertEqual(p.plug.call_args.args[:2],(600,250))
        self.assertTrue(p.app.worker.commands.empty())

    def test_hover_snaps_to_valid_jack(self):
        p=self.panel();p.draw();p.drag_source=192;p.hit=Mock(return_value=('dest',0));p.cable=Mock()
        p.motion(SimpleNamespace(x=960,y=105))
        self.assertEqual(p.cable.call_args.args[2:4],p.destination_points[0])
        self.assertTrue(p.app.worker.commands.empty())

    def test_reverse_drag_from_output_to_source(self):
        p=self.panel();p.hit=Mock(side_effect=[('dest',0),('source',128)])
        p.press(SimpleNamespace(x=900,y=100));p.release(SimpleNamespace(x=230,y=200))
        cmd,data=p.app.worker.commands.get_nowait()
        self.assertEqual((data['destination'],data['source_code']),(0,128))

    def test_blank_drop_cancels_drag_without_writing(self):
        p=self.panel();p.drag_source=128;p.armed_source=128;p.drag_moved=True;p.hit=Mock(return_value=None)
        p.release(SimpleNamespace(x=600,y=200))
        self.assertIsNone(p.armed_source);self.assertTrue(p.app.worker.commands.empty())

    def test_click_carry_preview_works_without_mouse_button(self):
        p=self.panel();p.draw();p.armed_source=192;p.drag_source=None;p.hit=Mock(return_value=None);p.cable=Mock()
        p.motion(SimpleNamespace(x=600,y=250))
        p.cable.assert_called_once();self.assertTrue(p.app.worker.commands.empty())

    def test_cancel_clears_both_drag_directions(self):
        p=self.panel();p.drag_destination=0;p.drag_source=192;p.armed_source=192;p.clear_selection()
        self.assertIsNone(p.drag_destination);self.assertIsNone(p.drag_source);self.assertIsNone(p.armed_source)


if __name__=='__main__':unittest.main()
