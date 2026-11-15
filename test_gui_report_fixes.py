import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from af16rig_gui import OutputWindow,MiniInputWindow
from mixer_view import Console

class GuiReportFixTests(unittest.TestCase):
    def test_outputs_constructor_reaches_initial_read(self):
        app=Mock()
        with patch('af16rig_gui.tk') as tk:
            tk.IntVar.return_value.get.return_value=3
            p=OutputWindow(app)
        app.worker.commands.put.assert_called_with(('input_select',('output',3)))
        self.assertTrue(hasattr(p,'message'))

    def test_minijack_constructor_reaches_initial_read(self):
        app=Mock()
        with patch('af16rig_gui.tk'):p=MiniInputWindow(app)
        app.worker.commands.put.assert_called_with(('input_select','mini'))
        self.assertTrue(hasattr(p,'message'))

    def test_equal_count_new_usb_bank_recalculates_widths(self):
        canvas=Mock();canvas.winfo_width.return_value=1500;canvas.winfo_height.return_value=800
        strips={i:SimpleNamespace(frame=Mock(),title=Mock(),pan=Mock(),dials={},
            preamp=SimpleNamespace(source_button=None,source_slot=Mock(),gains={})) for i in range(17,65)}
        view=SimpleNamespace(canvas=canvas,bank_id=1,bank_size=(1500,800),bank_visible_count=16,
            visible=list(range(17,33)),bank_start=33,bus='main',strips=strips,
            controllers={i:SimpleNamespace(state={}) for i in strips},bus_buttons={},bank_buttons={},
            master_view=SimpleNamespace(frame=Mock(),dials={},minimum_width=173))
        view.resize=lambda:Console.resize(view)
        with patch('mixer_view.align_gain_rows'):
            for bank in (33,49):
                view.bank_start=bank;canvas.itemconfigure.reset_mock();Console.layout(view)
                canvas.itemconfigure.assert_called_once_with(1,width=2994,height=850)
                self.assertEqual(view.visible,list(range(bank,bank+16)))
                widths=[strips[i].frame.config.call_args.kwargs['width'] for i in view.visible]
                self.assertEqual(sum(widths)+16*3+173+5,2994)
            canvas.itemconfigure.reset_mock();Console.layout(view)
            canvas.itemconfigure.assert_not_called()

if __name__=='__main__':unittest.main()
