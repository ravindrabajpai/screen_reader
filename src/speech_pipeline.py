"""One inference worker and bounded progressive playback, owned by the reader."""

from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
import subprocess
import threading
import time

from text_chunker import chunk_text

LOG = logging.getLogger(__name__)


class KokoroEngine:
    def __init__(self, model_dir: Path):
        try:
            from kokoro_onnx import Kokoro
            import soundfile
        except ImportError as exc:
            raise RuntimeError("Install dependencies with: ./scripts/install.sh") from exc
        self.engine = Kokoro(str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin"))
        self.soundfile = soundfile

    def create(self, text: str, audio: Path, *, voice: str, speed: float, speech_language: str) -> None:
        samples, rate = self.engine.create(text, voice=voice, speed=speed, lang=speech_language)
        self.soundfile.write(str(audio), samples, rate)


class LazyEngine:
    """Load on the inference worker so stop/status remain available during loading."""

    def __init__(self, factory):
        self.factory = factory
        self.engine = None

    def create(self, *args, **kwargs):
        if self.engine is None:
            self.engine = self.factory()
        self.engine.create(*args, **kwargs)


def start_player(audio: Path):
    return subprocess.Popen(["/usr/bin/afplay", str(audio)])


class SpeechPipeline:
    def __init__(self, engine, audio_dir: Path, player_factory=start_player):
        self.engine = engine
        self.audio_dir = audio_dir
        self.player_factory = player_factory
        self.condition = threading.Condition()
        self.queue = deque()
        self.generation = 0
        self.pending = None
        self.generating = False
        self.playing = False
        self.player = None
        self.closed = False
        self.last_error = None
        self.request_id = None
        self.last_activity = time.monotonic()
        self.workers = [threading.Thread(target=target, daemon=True) for target in (self._synthesize, self._play)]
        for worker in self.workers:
            worker.start()

    def _cancel_locked(self):
        self.generation += 1
        self.pending = None
        while self.queue:
            _, audio = self.queue.popleft()
            audio.unlink(missing_ok=True)
        if self.player is not None and self.player.poll() is None:
            try:
                self.player.terminate()
                self.player.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.player.kill()
                self.player.wait(timeout=0.5)
            except ProcessLookupError:
                pass
        self.last_activity = time.monotonic()
        self.condition.notify_all()

    def speak(self, request: dict):
        with self.condition:
            if self.closed:
                raise RuntimeError("Reader is shutting down. Retry the reading shortly.")
            self._cancel_locked()
            self.pending = (self.generation, request)
            self.request_id = request["request_id"]
            self.last_error = None
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self._cancel_locked()

    def _fail_locked(self, generation, exc):
        if generation == self.generation:
            # Do not include text, voice values, or exception payloads in logs.
            self.last_error = f"Reading failed ({type(exc).__name__}). Check voice/language, model files and audio output; retry with --direct for details."
            LOG.error("%s", self.last_error)
            self._cancel_locked()

    def _synthesize(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                generation, request = self.pending
                self.pending = None
                self.generating = True
            try:
                for index, text in enumerate(chunk_text(request["text"])):
                    with self.condition:
                        self.condition.wait_for(lambda: self.closed or generation != self.generation or len(self.queue) < 2)
                        if self.closed or generation != self.generation:
                            break
                    audio = self.audio_dir / f"{generation}-{index}.wav"
                    try:
                        self.engine.create(text, audio, **{key: request[key] for key in ("voice", "speed", "speech_language")})
                        with self.condition:
                            if self.closed or generation != self.generation:
                                audio.unlink(missing_ok=True)
                                break
                            self.queue.append((generation, audio))
                            self.condition.notify_all()
                    except Exception:
                        audio.unlink(missing_ok=True)
                        raise
            except Exception as exc:
                with self.condition:
                    self._fail_locked(generation, exc)
            finally:
                with self.condition:
                    self.generating = False
                    self.last_activity = time.monotonic()
                    self.condition.notify_all()

    def _play(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or bool(self.queue))
                if self.closed:
                    return
                generation, audio = self.queue.popleft()
                self.condition.notify_all()
                if generation != self.generation:
                    audio.unlink(missing_ok=True)
                    continue
                self.playing = True
                try:
                    # Start under the same lock as cancellation: no stale player can start afterward.
                    player = self.player_factory(audio)
                    self.player = player
                except Exception as exc:
                    self.playing = False
                    audio.unlink(missing_ok=True)
                    self._fail_locked(generation, exc)
                    continue
            try:
                code = player.wait()
                if code:
                    raise RuntimeError("Audio playback failed.")
            except Exception as exc:
                with self.condition:
                    self._fail_locked(generation, exc)
            finally:
                with self.condition:
                    self.player = None
                    self.playing = False
                    audio.unlink(missing_ok=True)
                    self.last_activity = time.monotonic()
                    self.condition.notify_all()

    def status(self) -> dict:
        with self.condition:
            busy = self.generating or self.playing or self.pending is not None or bool(self.queue)
            return {"state": "shutting_down" if self.closed else ("reading" if busy else "idle"),
                    "request_id": self.request_id, "last_error": self.last_error,
                    "queued_chunks": len(self.queue), "idle_seconds": 0 if busy else time.monotonic() - self.last_activity}

    def close(self, timeout=5.0) -> bool:
        with self.condition:
            self.closed = True
            self._cancel_locked()
        deadline = time.monotonic() + timeout
        for worker in self.workers:
            worker.join(max(0, deadline - time.monotonic()))
        return not any(worker.is_alive() for worker in self.workers)
