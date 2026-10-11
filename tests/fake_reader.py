"""Subprocess fixture: exercise the real reader lifecycle without model or audio."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import reader_process
from speech_pipeline import SpeechPipeline


class Engine:
    def __init__(self, model_dir):
        pass

    def create(self, text, audio, **options):
        audio.write_text(text)


class Player:
    def __init__(self, audio):
        pass

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


if __name__ == "__main__":
    reader_process.KokoroEngine = Engine
    reader_process.SpeechPipeline = lambda engine, audio, **kwargs: SpeechPipeline(engine, audio, Player)
    raise SystemExit(reader_process.main())
