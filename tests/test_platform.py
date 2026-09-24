"""Cross-platform regression tests. No actual account or personal vault is used."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import atomic_text, export_root, redirected_path
from recorder import Application, InstanceLock, default_data_dir

ROOT = Path(__file__).resolve().parents[1]


class PlatformTests(unittest.TestCase):
    def test_windows_default_uses_localappdata(self):
        with patch('recorder.sys.platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': '/local-test-data'}):
            self.assertEqual(default_data_dir(), Path('/local-test-data') / 'CrashRoundRecorder')

    def test_macos_default_unchanged(self):
        with patch('recorder.sys.platform', 'darwin'):
            self.assertEqual(default_data_dir(), Path.home() / 'Library/Application Support/CrashRoundRecorder')

    def test_unicode_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / 'Vault cafe\u0301 \u03bb with spaces'
            vault.mkdir()
            folder = Path(tmp) / 'local data \u03bb'
            app = Application(folder)
            app.save_settings({'vault': str(vault)})
            app.close()
            reopened = Application(folder)
            try:
                self.assertEqual(reopened.config['vault'], str(vault))
                self.assertTrue((vault / 'Crash Round Research/ethercrash Dashboard.md').is_file())
            finally:
                reopened.close()

    def test_atomic_unicode_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'note \u03bb.md'
            atomic_text(file, '\u03bb \u2192 10.00x\n')
            self.assertEqual(file.read_text(encoding='utf-8'), '\u03bb \u2192 10.00x\n')
            atomic_text(file, 'replacement')
            self.assertEqual(file.read_text(encoding='utf-8'), 'replacement')

    def test_junction_tag_rejected(self):
        fake = Mock()
        fake.is_symlink.return_value = False
        fake.lstat.return_value = SimpleNamespace(st_reparse_tag=0xA0000003)
        self.assertTrue(redirected_path(fake))

    def test_cloud_placeholder_not_assumed_junction(self):
        fake = Mock()
        fake.is_symlink.return_value = False
        fake.lstat.return_value = SimpleNamespace(st_reparse_tag=0x9000001A)
        self.assertFalse(redirected_path(fake))

    def test_unknown_existing_folder_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            existing = vault / 'Crash Round Research'
            existing.mkdir()
            note = existing / 'personal.md'
            note.write_text('keep this', encoding='utf-8')
            with self.assertRaises(ValueError):
                export_root(vault)
            self.assertEqual(note.read_text(encoding='utf-8'), 'keep this')

    def test_process_lock_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'instance.lock'
            command = [sys.executable, '-c',
                       'from pathlib import Path; from recorder import InstanceLock; '
                       'import sys; lock=InstanceLock(Path(sys.argv[1])); lock.close()', str(file)]
            lock = InstanceLock(file)
            try:
                result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'already running', result.stderr)
            finally:
                lock.close()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_launchers_exist_and_delegate(self):
        for name in ['01_Setup_Windows.bat', '02_Start_Windows.bat', '03_Synthetic_Demo_Windows.bat', '04_Test_Windows.bat']:
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn('scripts\\windows.cmd', text)
        script = (ROOT / 'scripts/windows.cmd').read_text(encoding='utf-8')
        self.assertIn('DisableDelayedExpansion', script)
        self.assertNotIn('ExecutionPolicy', script)

    def test_demo_separate_and_live_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(Path(tmp), site='synthetic_demo', demo=True)
            try:
                self.assertTrue(app.status()['demo'])
                self.assertEqual(app.status()['site'], 'synthetic_demo')
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
