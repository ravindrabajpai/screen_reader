#!/usr/bin/env python3
"""Download the Kokoro ONNX model and voice data used by src/screen_reader.py."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request


RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/"
    "releases/download/model-files-v1.1"
)
FILES = {
    "kokoro-v1.0.onnx": (
        f"{RELEASE}/kokoro-v1.0.onnx",
        "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    ),
    "voices-v1.0.bin": (
        f"{RELEASE}/voices-v1.0.bin",
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_hash: str) -> None:
    # Unique partial files allow interrupted/concurrent downloads without replacing
    # a usable model until its replacement has passed verification.
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=destination.name + ".", suffix=".part", delete=False
    ) as handle:
        partial = Path(handle.name)
    print(f"Downloading {destination.name}...")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        actual_hash = sha256(partial)
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Checksum mismatch for {destination.name}: expected {expected_hash}, got {actual_hash}"
            )
        partial.replace(destination)
    finally:
        if partial.exists():
            partial.unlink()


def main() -> int:
    model_dir = Path(__file__).resolve().parents[1] / "models"
    if model_dir.is_symlink():
        raise RuntimeError("Refusing to download into a symlinked models directory")
    model_dir.mkdir(exist_ok=True)

    for name, (url, expected_hash) in FILES.items():
        destination = model_dir / name
        if destination.is_file() and sha256(destination) == expected_hash:
            print(f"{name} is already downloaded and verified.")
            continue
        download(url, destination, expected_hash)
        print(f"Verified {name}.")

    print(f"Models are ready in {model_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
