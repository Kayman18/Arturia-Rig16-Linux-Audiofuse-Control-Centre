import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from mixer_view import show_page, ValueControl, configure_changed, Console, Field, sync_button

class Page:
    def __init__(self):self.visible=True
    def pack_forget(self):self.visible=False
    def pack(self,**kwargs):self.visible=True
    def lift(self):pass

class ViewTests(unittest.TestCase):
    def test_only_selected_page_visible_across_repeated_navigation(self):
        pages=[Page() for _ in range(9)]
        app=SimpleNamespace(page_host=SimpleNamespace(winfo_children=lambda:pages))
        for index in (1,2,7,8,0,4,0,4,3,0):
            show_page(app,pages[index])
            self.assertEqual([p.visible for p in pages],[i==index for i in range(9)])
    def test_unchanged_label_no_tk_mutation(self):
        widget=Mock();widget.cget=lambda key:{'text':'Main','fg':'cyan'}[key]
        configure_changed(widget,text='Main',fg='cyan');widget.config.assert_not_called()
        configure_changed(widget,text='Cue',fg='cyan');widget.config.assert_called_once_with(text='Cue')
    def dial(self):
        w=ValueControl.__new__(ValueControl)
        w.value=-12;w.readout=None;w.valid=True;w.ready=True
        w.draw=Mock();w.configure=Mock();w.cget=lambda key:'hand2';w.cancel_drag=Mock()
        return w
    def test_busy_then_ready_does_not_repaint(self):
        w=self.dial()
        w.update_value(-12,False);self.assertFalse(w.ready)
        w.update_value(-12,True);self.assertTrue(w.ready)
        w.draw.assert_not_called()
    def test_value_change_repaints_only_changed_widget(self):
        a,b=self.dial(),self.dial()
        a.update_value(-10,True);b.update_value(-12,True)
        a.draw.assert_called_once();b.draw.assert_not_called()
    def test_error_still_disables_and_repaints(self):
        w=self.dial();w.update_value(-12,False,valid=False)
        self.assertFalse(w.ready);w.cancel_drag.assert_called_once();w.draw.assert_called_once()
    def test_identical_layout_does_not_reconfigure_canvas(self):
        canvas=Mock();canvas.winfo_width.return_value=1000;canvas.winfo_height.return_value=800
        view=SimpleNamespace(canvas=canvas,visible=list(range(9)),bank_id=1,bank_size=(1732,850),bank_visible_count=9,master_view=SimpleNamespace(minimum_width=170))
        Console.resize(view)
        canvas.itemconfigure.assert_not_called();canvas.configure.assert_not_called()
    def test_pending_button_keeps_appearance_but_guard_stays_disabled(self):
        field=Field();field.config(state='disabled')
        widget=Mock();widget.cget=lambda k:{'state':'normal','bg':'#383c41','fg':'#e6e8ea'}[k]
        sync_button(widget,field,busy=True)
        widget.config.assert_not_called();self.assertEqual(field.cget('state'),'disabled')

if __name__=='__main__':unittest.main()
