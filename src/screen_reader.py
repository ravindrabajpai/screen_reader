#!/usr/bin/env python3
"""Read a screen selection or copied text with a local Kokoro voice."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Sequence

from reader_process import DEFAULT_IDLE_TIMEOUT, control, submit
from text_chunker import normalize_text


def run_text(command: Sequence[str], *, timeout: int = 60) -> str:
    """Run a command and return stdout, raising a readable error on failure."""
    result = subprocess.run(
        list(command), capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Command failed")
    return result.stdout


def resolve_model_dir(value: str | None) -> Path:
    """Resolve the directory containing the Kokoro model and voice data."""
    configured = value or os.environ.get("SCREEN_READER_MODEL_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "models"


def read_clipboard() -> str:
    return run_text(["/usr/bin/pbpaste"], timeout=10)


def capture_text(image: Path, *, ocr_language: str) -> str:
    print("Drag over text. Press Escape to cancel.", flush=True)
    result = subprocess.run(
        [
            "/usr/sbin/screencapture",
            "-i",
            "-s",
            "-x",
            "-t",
            "png",
            str(image),
        ],
        capture_output=True,
        text=True,
    )
    if not image.is_file():
        if result.returncode and result.stderr.strip():
            raise RuntimeError(
                result.stderr.strip()
                + "\nCheck Screen Recording access for the app launching this script."
            )
        return ""

    return run_text(
        [
            "tesseract",
            str(image),
            "stdout",
            "-l",
            ocr_language,
            "--psm",
            "3",
        ]
    )


def synthesize(
    text: str,
    audio: Path,
    *,
    model: Path,
    voices: Path,
    voice: str,
    speed: float,
    speech_language: str,
) -> None:
    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            "Install dependencies with: ./scripts/install.sh"
        ) from exc

    print("Generating speech locally...", flush=True)
    engine = Kokoro(str(model), str(voices))
    samples, sample_rate = engine.create(
        text,
        voice=voice,
        speed=speed,
        lang=speech_language,
    )
    sf.write(str(audio), samples, sample_rate)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="Read text already copied with Command+C",
    )
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--stop", action="store_true", help="Stop speech and keep the model warm")
    commands.add_argument("--shutdown-reader", action="store_true", help="Stop speech, clean up, and exit the reader")
    commands.add_argument("--reader-status", action="store_true", help="Show reader state and the last asynchronous error")
    commands.add_argument("--direct", action="store_true", help="Generate and play in the foreground without the reader")
    parser.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE_TIMEOUT,
                        metavar="SEC", help="Idle lifetime when starting a reader (default: 1800; 0 disables expiry)")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=0.95)
    parser.add_argument(
        "--speech-language",
        default="en-us",
        help="Kokoro language, such as en-us or en-gb",
    )
    parser.add_argument(
        "--ocr-language",
        default="eng",
        help="Tesseract language code used for screen captures",
    )
    parser.add_argument(
        "--model-dir",
        help="Directory containing kokoro-v1.0.onnx and voices-v1.0.bin",
    )
    parser.add_argument(
        "--show-text",
        action="store_true",
        help="Print extracted text before speaking it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if sys.platform != "darwin":
        parser.error("This script requires macOS.")
    if args.stop or args.shutdown_reader or args.reader_status:
        kind = "stop" if args.stop else ("shutdown" if args.shutdown_reader else "status")
        result = control(kind)
        if args.reader_status:
            print(json.dumps(result, indent=2))
        elif result["state"] == "not_running":
            print("Reader is not running.")
        elif args.stop:
            print("Speech stopped. The model remains loaded.")
        else:
            print("Reader shut down.")
        return 0
    if not math.isfinite(args.idle_timeout) or args.idle_timeout < 0:
        parser.error("--idle-timeout must be a finite nonnegative number")
    if not 0.5 <= args.speed <= 2.0:
        parser.error("--speed must be between 0.5 and 2.0")
    if not args.clipboard and not shutil.which("tesseract"):
        parser.error("Install OCR first: brew install tesseract")

    model_dir = resolve_model_dir(args.model_dir)
    model = model_dir / "kokoro-v1.0.onnx"
    voices = model_dir / "voices-v1.0.bin"
    missing = [path for path in (model, voices) if not path.is_file()]
    if missing:
        names = ", ".join(path.name for path in missing)
        parser.error(
            f"Missing {names} in {model_dir}. Run: python src/download_models.py"
        )

    with tempfile.TemporaryDirectory(prefix="local-screen-reader-") as temp:
        temp_dir = Path(temp)
        if args.clipboard:
            text = read_clipboard()
        else:
            text = capture_text(
                temp_dir / "selection.png",
                ocr_language=args.ocr_language,
            )

        text = normalize_text(text)
        if not text:
            print("No text found. Try a clearer selection or clipboard mode.")
            return 0
        if args.show_text:
            print(text)

        if not args.direct:
            submit({"request_id": uuid.uuid4().hex, "text": text, "model_dir": str(model_dir),
                    "voice": args.voice, "speed": args.speed, "speech_language": args.speech_language},
                   idle_timeout=args.idle_timeout)
            print("Reading accepted. Use --stop to stop speech or --shutdown-reader to release the model.", flush=True)
            return 0

        audio = temp_dir / "speech.wav"
        synthesize(
            text,
            audio,
            model=model,
            voices=voices,
            voice=args.voice,
            speed=args.speed,
            speech_language=args.speech_language,
        )
        print("Reading aloud. Control+C stops playback.", flush=True)
        subprocess.run(["/usr/bin/afplay", str(audio)], check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(130)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
