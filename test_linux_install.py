import importlib.util,tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('linux_installer',Path(__file__).with_name('install-desktop.py'))
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class LinuxInstallTests(unittest.TestCase):
    def source(self,root):
        source=root/'download with spaces';source.mkdir()
        for name in ('run.sh','af16rig_gui.py','app_icon.py'):(source/name).write_text('original')
        shutil.copytree(Path(__file__).with_name('icons'),source/'icons')
        return source
    def test_install_survives_download_removal_and_preserves_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);data=root/'data with spaces'
            config=root/'config';config.mkdir();(config/'window.json').write_text('settings')
            entry=installer.install(source,data);shutil.rmtree(source)
            current=data/installer.ICON_NAME/'current'
            self.assertEqual((current/'af16rig_gui.py').read_text(),'original')
            self.assertIn(str(current/'run.sh'),entry.read_text())
            self.assertIn('StartupWMClass=AF16RigLinuxControl',entry.read_text())
            self.assertEqual((config/'window.json').read_text(),'settings')
    def test_update_switches_current_and_keeps_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);data=root/'data'
            installer.install(source,data);current=data/installer.ICON_NAME/'current';old=current.resolve()
            (source/'af16rig_gui.py').write_text('updated')
            installer.install(source,data)
            self.assertNotEqual(current.resolve(),old)
            self.assertEqual((current/'af16rig_gui.py').read_text(),'updated')
            self.assertEqual((old/'af16rig_gui.py').read_text(),'original')
            installer.install(current,data)
            self.assertEqual((current/'af16rig_gui.py').read_text(),'updated')
    def test_failed_copy_leaves_previous_install_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);data=root/'data'
            installer.install(source,data);current=data/installer.ICON_NAME/'current';old=current.resolve()
            with patch.object(installer.shutil,'copytree',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):installer.install(source,data)
            self.assertEqual(current.resolve(),old)
    def test_missing_asset_does_not_replace_existing_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);data=root/'data'
            installer.install(source,data);current=data/installer.ICON_NAME/'current';old=current.resolve()
            (source/'icons/af16rig-256.png').unlink()
            with self.assertRaises(FileNotFoundError):installer.install(source,data)
            self.assertEqual(current.resolve(),old)

    def test_failed_icon_copy_keeps_active_release_and_complete_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);data=root/'data'
            installer.install(source,data);current=data/installer.ICON_NAME/'current';old=current.resolve()
            icon=data/'icons/hicolor/16x16/apps'/f'{installer.ICON_NAME}.png';previous=icon.read_bytes()
            original=installer.shutil.copyfile
            def copy(src,dest,*a,**kw):
                if 'hicolor' in str(dest):
                    Path(dest).write_bytes(b'partial')
                    raise OSError('disk full during icon copy')
                return original(src,dest,*a,**kw)
            with patch.object(installer.shutil,'copyfile',side_effect=copy):
                with self.assertRaises(OSError):installer.install(source,data)
            self.assertEqual(current.resolve(),old);self.assertEqual(icon.read_bytes(),previous)
            self.assertEqual(list((current.parent/'releases').iterdir()),[old])
            self.assertEqual(list(icon.parent.iterdir()),[icon])

    def test_launcher_and_activation_failures_keep_previous_app(self):
        for failure in ('launcher','activation'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=self.source(root);data=root/'data'
                entry=installer.install(source,data);previous=entry.read_text()
                current=data/installer.ICON_NAME/'current';old=current.resolve();original=installer.os.replace
                def replace(src,dst):
                    if Path(dst)==(entry if failure=='launcher' else current):raise OSError('replace failed')
                    return original(src,dst)
                with patch.object(installer.os,'replace',side_effect=replace):
                    with self.assertRaises(OSError):installer.install(source,data)
                self.assertEqual(current.resolve(),old);self.assertEqual(entry.read_text(),previous)
                self.assertEqual(list((current.parent/'releases').iterdir()),[old])
                self.assertFalse(list(current.parent.glob('.current-*')))

    def test_activation_is_last_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);data=root/'data';replacements=[];original=installer.os.replace
            def replace(src,dst):replacements.append(Path(dst));return original(src,dst)
            with patch.object(installer.os,'replace',side_effect=replace):installer.install(source,data)
            self.assertEqual(replacements[-1],data/installer.ICON_NAME/'current')
            self.assertEqual(len(replacements),10)
