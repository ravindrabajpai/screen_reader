#!/usr/bin/env python3
"""Opt-in macOS smoke benchmark with real Kokoro and muted afplay (no clipboard)."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import time

from speech_pipeline import KokoroEngine, LazyEngine, SpeechPipeline


def wait_for(predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise RuntimeError("Benchmark timed out")


def main():
    if sys.platform != "darwin":
        raise SystemExit("This benchmark needs macOS, installed models, and speech dependencies.")
    import soundfile

    results = {"measurement": "request-to-afplay-launch, muted; not acoustic onset or a release guarantee"}
    load_times = []
    play_events = []
    events_lock = threading.Lock()

    def load():
        start = time.monotonic()
        engine = KokoroEngine(Path(__file__).resolve().parents[1] / "models")
        load_times.append(time.monotonic() - start)
        return engine

    def player(audio):
        info = soundfile.info(audio)
        assert info.samplerate == 24000 and info.frames > 0
        launched = time.monotonic()
        process = subprocess.Popen(["/usr/bin/afplay", "-v", "0", str(audio)])
        with events_lock:
            play_events.append((launched, info.duration, process))
        return process

    with tempfile.TemporaryDirectory(prefix="reader-benchmark-") as directory:
        pipeline = SpeechPipeline(LazyEngine(load), Path(directory), player)
        try:
            for label, text in (("cold", "The reader is ready."), ("warm", "The reader is ready."),
                                ("long", " ".join(f"This is sentence number {i}." for i in range(24)))):
                with events_lock:
                    offset = len(play_events)
                started = time.monotonic()
                pipeline.speak({"request_id": label, "text": text, "voice": "af_heart", "speed": 0.95, "speech_language": "en-us"})

                def started_or_failed():
                    error = pipeline.status()["last_error"]
                    if error:
                        raise RuntimeError(error)
                    with events_lock:
                        return len(play_events) > offset

                wait_for(started_or_failed)
                with events_lock:
                    first, duration, _ = play_events[offset]
                results[label + "_launch_seconds"] = round(first - started, 3)
                results[label + "_first_audio_seconds"] = round(duration, 3)
                if label == "long":
                    # A queued second chunk while the first player is active proves real overlap.
                    wait_for(lambda: pipeline.status()["queued_chunks"] > 0)
                    with events_lock:
                        results["later_chunk_ready_during_first_playback"] = play_events[offset][2].poll() is None
                    stop_start = time.monotonic()
                    pipeline.stop()
                    results["stop_seconds"] = round(time.monotonic() - stop_start, 3)
                wait_for(lambda: pipeline.status()["state"] == "idle")
                if pipeline.status()["last_error"]:
                    raise RuntimeError(pipeline.status()["last_error"])
            assert len(load_times) == 1, "Engine reloaded across readings"
            assert not list(Path(directory).iterdir()), "Audio files survived playback/cancellation"
            results["engine_loads"] = len(load_times)
            results["engine_load_seconds"] = round(load_times[0], 3)
        finally:
            if not pipeline.close():
                raise RuntimeError("Inference exceeded the shutdown deadline")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
