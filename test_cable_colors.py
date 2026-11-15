import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from cable_colors import CableColors,PALETTE,DEFAULT
import test_patchbay as fixtures


class CableColorTests(unittest.TestCase):
    def panel(self):
        p=fixtures.PatchBayTests().panel();p.app.cable_colors=CableColors();p.app.cable_colors.save=Mock(return_value=True)
        return p
    def test_eight_unique_named_colours(self):
        self.assertEqual(len(PALETTE),8);self.assertEqual(len({c for n,c in PALETTE}),8)
    def test_colour_preview_follows_selection(self):
        p=self.panel();p.app.cable_colors.choose(PALETTE[0][1]);p.draw();p.armed_source=192;p.hit=Mock(return_value=None);p.cable=Mock()
        p.motion(SimpleNamespace(x=600,y=250))
        self.assertEqual(p.cable.call_args.args[4],PALETTE[0][1]);self.assertTrue(p.app.worker.commands.empty())
    def test_confirmed_drop_remembers_colour_captured_at_drop(self):
        p=self.panel();p.app.cable_colors.choose(PALETTE[1][1]);p.patch(128,0);request=p.request_id
        p.app.cable_colors.choose(PALETTE[2][1])
        p.handle(dict(kind='routing_written',request_id=request,destination=0,previous=192,actual=128,undo=False))
        self.assertEqual(p.route_color(128,0,DEFAULT),PALETTE[1][1])
    def test_failed_drop_does_not_change_colour(self):
        p=self.panel();p.app.cable_colors.choose(PALETTE[0][1]);p.patch(128,0)
        p.handle(dict(kind='routing_error',request_id=p.request_id,message='Failed'))
        self.assertEqual(p.app.cable_colors.routes,{})
    def test_same_route_recolours_without_hardware_write(self):
        p=self.panel();p.app.cable_colors.choose(PALETTE[6][1]);p.patch(192,0)
        self.assertEqual(p.route_color(192,0,DEFAULT),PALETTE[6][1]);self.assertTrue(p.app.worker.commands.empty())
    def test_prefs_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp,patch('cable_colors.config_path',return_value=Path(tmp)/'colours.json'):
            c=CableColors();c.choose(PALETTE[3][1]);c.assign(192,0,PALETTE[7][1]);self.assertTrue(c.save())
            r=CableColors.load();self.assertEqual(r.selected,PALETTE[3][1]);self.assertEqual(r.get(192,0,DEFAULT),PALETTE[7][1])
    def test_bad_prefs_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp,patch('cable_colors.config_path',return_value=Path(tmp)/'colours.json'):
            path=Path(tmp)/'colours.json';path.write_text(json.dumps({'selected':'invalid','routes':{'999:0':'#f04b4b','192:0':'invalid'}}))
            c=CableColors.load();self.assertEqual(c.selected,DEFAULT);self.assertEqual(c.routes,{})
            path.write_text('{');self.assertEqual(CableColors.load().selected,DEFAULT)
    def test_colours_are_specific_to_each_source_destination(self):
        c=CableColors();c.assign(192,0,PALETTE[0][1]);c.assign(128,0,PALETTE[1][1])
        self.assertEqual(c.get(192,0,DEFAULT),PALETTE[0][1]);self.assertEqual(c.get(192,1,DEFAULT),DEFAULT)

if __name__=='__main__':unittest.main()
