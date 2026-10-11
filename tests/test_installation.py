from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reader install test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/uninstall.sh", self.root / "scripts")
        (self.root / "src").mkdir()
        (self.root / "src/screen_reader.py").touch()
        (self.root / "requirements.txt").touch()
        (self.root / ".venv").mkdir()
        (self.root / ".venv/pyvenv.cfg").write_text("test environment")
        (self.root / "models").mkdir()
        (self.root / "models/kokoro-v1.0.onnx").touch()
        (self.root / "models/unrelated.txt").write_text("keep")

    def run_uninstall(self, *args):
        return subprocess.run(
            ["bash", str(self.root / "scripts/uninstall.sh"), *args],
            capture_output=True, text=True,
        )

    def test_dry_run_and_repeated_uninstall_preserve_user_files(self):
        self.assertEqual(self.run_uninstall("--dry-run").returncode, 0)
        self.assertTrue((self.root / ".venv/pyvenv.cfg").exists())
        self.assertTrue((self.root / "models/kokoro-v1.0.onnx").exists())
        for _ in range(2):
            self.assertEqual(self.run_uninstall().returncode, 0)
        self.assertFalse((self.root / ".venv").exists())
        self.assertFalse((self.root / "models/kokoro-v1.0.onnx").exists())
        self.assertEqual((self.root / "models/unrelated.txt").read_text(), "keep")
        self.assertTrue((self.root / "src/screen_reader.py").exists())

    def test_rejects_symlink_before_removing_environment(self):
        (self.root / "models").rename(self.root / "external-models")
        (self.root / "models").symlink_to(self.root / "external-models")
        self.assertNotEqual(self.run_uninstall().returncode, 0)
        self.assertTrue((self.root / ".venv/pyvenv.cfg").exists())
        self.assertTrue((self.root / "external-models/kokoro-v1.0.onnx").exists())

    def test_rejects_unknown_options_and_unrecognized_environment(self):
        self.assertNotEqual(self.run_uninstall("--typo").returncode, 0)
        (self.root / ".venv/pyvenv.cfg").unlink()
        self.assertNotEqual(self.run_uninstall().returncode, 0)
        self.assertTrue((self.root / "models/kokoro-v1.0.onnx").exists())

    def test_directory_at_model_path_is_preserved_before_any_removal(self):
        target = self.root / "models/kokoro-v1.0.onnx"
        target.unlink()
        target.mkdir()
        (target / "user-document.txt").write_text("keep")
        self.assertNotEqual(self.run_uninstall().returncode, 0)
        self.assertEqual((target / "user-document.txt").read_text(), "keep")
        self.assertTrue((self.root / ".venv/pyvenv.cfg").exists())

    def test_unique_partial_download_is_removed_but_unrelated_file_stays(self):
        partial = self.root / "models/kokoro-v1.0.onnx.abc123.part"
        partial.touch()
        self.assertEqual(self.run_uninstall().returncode, 0)
        self.assertFalse(partial.exists())
        self.assertTrue((self.root / "models/unrelated.txt").exists())

    def test_shutdown_failure_preserves_installation_and_dry_run_does_not_stop(self):
        (self.root / "src/reader_process.py").touch()
        (self.root / ".venv/bin").mkdir()
        python = self.root / ".venv/bin/python"
        python.write_text('#!/bin/sh\nexit 1\n')
        python.chmod(0o700)
        self.assertEqual(self.run_uninstall("--dry-run").returncode, 0)
        self.assertNotEqual(self.run_uninstall().returncode, 0)
        self.assertTrue((self.root / ".venv/pyvenv.cfg").exists())
        self.assertTrue((self.root / "models/kokoro-v1.0.onnx").exists())
