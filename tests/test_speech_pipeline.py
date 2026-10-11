from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from speech_pipeline import SpeechPipeline


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for worker state")


def request(text, request_id="test"):
    return {"request_id": request_id, "text": text, "voice": "af_heart", "speed": 0.95, "speech_language": "en-us"}


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = False

    def create(self, text, audio, **options):
        self.calls.append(text)
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("Test engine timed out")
        if self.fail:
            raise ValueError("private selected text must not appear in status")
        audio.write_text(text)


class FakePlayer:
    def __init__(self, audio, automatic=False):
        self.text = audio.read_text()
        self.done = threading.Event()
        self.code = 0
        if automatic:
            self.done.set()

    def poll(self):
        return self.code if self.done.is_set() else None

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise subprocess.TimeoutExpired("fake-player", timeout)
        return self.code

    def terminate(self):
        self.code = -15
        self.done.set()

    kill = terminate


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audio = Path(self.temp.name)
        self.engine = FakeEngine()
        self.players = []

        def player_factory(audio):
            player = FakePlayer(audio)
            self.players.append(player)
            return player

        self.pipeline = SpeechPipeline(self.engine, self.audio, player_factory)
        self.addCleanup(self.pipeline.close)
        self.addCleanup(self.engine.release.set)

    def test_progressive_overlap_bounded_queue_and_order(self):
        text = " ".join(f"Sentence {i} with words." for i in range(60))
        self.pipeline.speak(request(text))
        eventually(lambda: len(self.players) == 1 and len(self.pipeline.queue) == 2)
        self.assertFalse(self.players[0].done.is_set())
        self.assertEqual(len(self.engine.calls), 3)
        self.assertTrue(self.pipeline.status()["state"] == "reading")
        index = 0
        while self.pipeline.status()["state"] != "idle":
            eventually(lambda: len(self.players) > index or self.pipeline.status()["state"] == "idle")
            if len(self.players) > index:
                self.players[index].done.set()
                index += 1
        self.assertEqual(" ".join(player.text for player in self.players), text)
        self.assertEqual(list(self.audio.iterdir()), [])

    def test_replacement_discards_inflight_inference(self):
        self.engine.release.clear()
        self.pipeline.speak(request("Old text."))
        self.assertTrue(self.engine.entered.wait(2))
        self.pipeline.speak(request("New text.", "new"))
        self.engine.release.set()
        eventually(lambda: len(self.players) == 1)
        self.assertEqual(self.players[0].text, "New text.")
        self.pipeline.stop()
        eventually(lambda: self.pipeline.status()["state"] == "idle")
        self.assertEqual(list(self.audio.iterdir()), [])

    def test_replacement_stops_active_player_and_discards_queue(self):
        self.pipeline.speak(request("Old sentence. " * 40))
        eventually(lambda: len(self.players) == 1 and len(self.pipeline.queue) == 2)
        self.pipeline.speak(request("New text.", "new"))
        eventually(lambda: len(self.players) == 2)
        self.assertEqual(self.players[0].poll(), -15)
        self.assertEqual(self.players[1].text, "New text.")
        self.assertIsNone(self.pipeline.status()["last_error"])

    def test_stop_during_inference_and_bounded_shutdown(self):
        self.engine.release.clear()
        self.pipeline.speak(request("Text."))
        self.assertTrue(self.engine.entered.wait(2))
        self.pipeline.stop()
        self.assertFalse(self.pipeline.close(timeout=0.01))
        self.engine.release.set()
        self.assertTrue(self.pipeline.close(timeout=2))
        self.assertEqual(self.players, [])
        self.assertEqual(list(self.audio.iterdir()), [])

    def test_generation_failure_is_visible_and_next_request_recovers(self):
        self.engine.fail = True
        self.pipeline.speak(request("Private text."))
        eventually(lambda: self.pipeline.status()["last_error"] is not None)
        self.assertNotIn("private", self.pipeline.status()["last_error"])
        self.engine.fail = False
        self.pipeline.speak(request("Retry."))
        eventually(lambda: len(self.players) == 1)
        self.assertIsNone(self.pipeline.status()["last_error"])

    def test_player_failure_cancels_pending_audio(self):
        self.pipeline.speak(request("Some sentence. " * 40))
        eventually(lambda: len(self.players) == 1)
        self.players[0].code = 1
        self.players[0].done.set()
        eventually(lambda: self.pipeline.status()["state"] == "idle")
        self.assertIsNotNone(self.pipeline.status()["last_error"])
        self.assertEqual(list(self.audio.iterdir()), [])
