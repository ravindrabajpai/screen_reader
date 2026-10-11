from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import reader_process
from reader_protocol import VERSION
from test_speech_pipeline import FakeEngine, FakePlayer, eventually, request


class ReaderProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lsr-test-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.model = self.runtime / "models"
        self.engine = FakeEngine()
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.errors = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.engine.release.set()
        self.stop.set()
        if self.thread:
            self.thread.join(3)
            self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors, [])

    def start(self, idle=1800, automatic=True, factory=None):
        def run():
            try:
                reader_process.serve(self.runtime, self.model, idle,
                                     engine_factory=factory or (lambda model: self.engine),
                                     player_factory=lambda audio: FakePlayer(audio, automatic),
                                     stop_event=self.stop, ready_event=self.ready)
            except Exception as exc:
                self.errors.append(exc)

        self.thread = threading.Thread(target=run)
        self.thread.start()
        self.assertTrue(self.ready.wait(3), self.errors)

    def speak(self, **changes):
        return reader_process.submit({**request("Hello."), "model_dir": str(self.model), **changes}, runtime=self.runtime)

    def test_warm_reuse_stop_and_shutdown(self):
        self.start(automatic=False)
        response = self.speak()
        eventually(lambda: bool(self.engine.calls))
        self.assertEqual(response["idle_timeout"], 1800)
        reader_process.control("stop", self.runtime)
        eventually(lambda: reader_process.control("status", self.runtime)["state"] == "idle")
        self.assertEqual(self.speak(request_id="second")["pid"], response["pid"])
        self.assertEqual(reader_process.control("shutdown", self.runtime)["state"], "stopped")
        self.thread.join(2)
        self.assertFalse((self.runtime / "s").exists())
        self.assertFalse((self.runtime / "reader.pid").exists())
        self.assertEqual(list((self.runtime / "audio").iterdir()), [])

    def test_idle_shutdown_and_no_expiry_during_inference(self):
        self.engine.release.clear()
        self.start(idle=0.1)
        self.speak()
        self.assertTrue(self.engine.entered.wait(2))
        # A pending inference must prevent idle shutdown even past the deadline.
        self.assertFalse(self.stop.wait(0.3))
        self.assertEqual(reader_process.control("status", self.runtime)["state"], "reading")
        self.engine.release.set()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse((self.runtime / "s").exists())

    def test_disabled_idle_timeout_and_model_mismatch(self):
        self.start(idle=0)
        self.assertFalse(self.stop.wait(0.25))
        self.assertEqual(reader_process.control("status", self.runtime)["state"], "idle")
        with self.assertRaisesRegex(RuntimeError, "Model directory differs"):
            self.speak(model_dir="/other-model")

    def test_stop_remains_available_during_model_loading(self):
        loading = threading.Event()
        loaded = threading.Event()
        calls = []
        self.addCleanup(loaded.set)

        def load(model):
            calls.append(model)
            loading.set()
            if not loaded.wait(3):
                raise RuntimeError("Test loading timed out")
            return self.engine

        self.start(factory=load)
        self.speak()
        self.assertTrue(loading.wait(2))
        reader_process.control("stop", self.runtime)
        self.assertFalse(loaded.is_set())
        loaded.set()
        eventually(lambda: reader_process.control("status", self.runtime)["state"] == "idle")
        self.assertEqual(list((self.runtime / "audio").iterdir()), [])
        self.speak(request_id="second")
        eventually(lambda: reader_process.control("status", self.runtime)["state"] == "idle")
        self.assertEqual(len(calls), 1)

    def test_controls_never_start_reader(self):
        with patch.object(reader_process.subprocess, "Popen") as launch:
            for kind in ("status", "stop", "shutdown"):
                self.assertEqual(reader_process.control(kind, self.runtime)["state"], "not_running")
            launch.assert_not_called()

    def test_malformed_request_does_not_kill_server(self):
        self.start()
        with self.assertRaisesRegex(RuntimeError, "Unknown reader command"):
            reader_process.exchange(self.runtime, {"version": VERSION, "type": "bad"})
        self.assertEqual(reader_process.control("status", self.runtime)["state"], "idle")

    def test_lifetime_lock_prevents_duplicate_engine(self):
        self.start()
        factory = unittest.mock.Mock()
        with self.assertRaises(TimeoutError):
            reader_process.serve(self.runtime, self.model, 0, engine_factory=factory)
        factory.assert_not_called()
        self.assertEqual(reader_process.control("status", self.runtime)["state"], "idle")

    def test_stale_socket_concurrent_start_and_restart(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(self.runtime / "s"))
        audio_dir = self.runtime / "audio"
        audio_dir.mkdir()
        (audio_dir / "abandoned.wav").touch()
        launched = []
        real_popen = subprocess.Popen

        def launch(args, **kwargs):
            args[1] = str(Path(__file__).with_name("fake_reader.py"))
            process = real_popen(args, **kwargs)
            launched.append(process)
            return process

        def cleanup():
            reader_process.control("shutdown", self.runtime)
            for process in launched:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)

        self.addCleanup(cleanup)
        with patch.object(reader_process.subprocess, "Popen", side_effect=launch):
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: self.speak(), range(2)))
            self.assertEqual(len(launched), 1)
            self.assertEqual(responses[0]["pid"], responses[1]["pid"])
            self.assertFalse((audio_dir / "abandoned.wav").exists())
            reader_process.control("shutdown", self.runtime)
            launched[0].wait(timeout=3)
            response = self.speak()
            self.assertEqual(len(launched), 2)
            self.assertNotEqual(response["pid"], responses[0]["pid"])
            launched[1].terminate()
            self.assertEqual(launched[1].wait(timeout=3), 0)
            self.assertFalse((self.runtime / "s").exists())
            self.assertFalse((self.runtime / "reader.pid").exists())

    def test_startup_failure_is_bounded_and_actionable(self):
        real_popen = subprocess.Popen
        with patch.object(reader_process.subprocess, "Popen", side_effect=lambda *a, **kw: real_popen([sys.executable, "-c", "raise SystemExit(1)"], **kw)):
            with self.assertRaisesRegex(RuntimeError, "failed to start"):
                self.speak()
