"""Lazy per-checkout reader process, local IPC, and bounded shutdown."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

from reader_protocol import MAX_MESSAGE, VERSION, receive_message, send_message, validate_request
from speech_pipeline import KokoroEngine, LazyEngine, SpeechPipeline

DEFAULT_IDLE_TIMEOUT = 30 * 60
STARTUP_TIMEOUT = 60.0
LOG = logging.getLogger(__name__)


def runtime_directory() -> Path:
    checkout = hashlib.sha256(str(Path(__file__).resolve().parents[1]).encode()).hexdigest()[:10]
    # Keep sockaddr_un below macOS's 104-byte limit, even under its long TMPDIR.
    return Path(tempfile.gettempdir()) / f"lsr-{os.getuid()}-{checkout}"


def private_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError(f"Unsafe reader directory: {path}")
    path.chmod(0o700)


@contextmanager
def lock_file(path: Path, timeout: float):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Reader is already starting or shutting down. Retry shortly.")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def exchange(runtime: Path, request: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(str(runtime / "s"))
        send_message(connection, request)
        response = receive_message(connection)
    if response.get("version") != VERSION:
        raise RuntimeError("Reader protocol mismatch. Stop the existing reader before retrying.")
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Reader rejected the request."))
    return response


def control(command: str, runtime: Path | None = None) -> dict:
    runtime = runtime or runtime_directory()
    try:
        result = exchange(runtime, {"version": VERSION, "type": command})
    except (FileNotFoundError, ConnectionRefusedError):
        return {"ok": True, "state": "not_running", "log_file": str(runtime / "reader.log")}
    if command == "shutdown":
        deadline = time.monotonic() + 10
        # The server removes its socket only after worker/player cleanup.
        while (runtime / "s").exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("Shutdown requested, but the reader has not exited yet. Check --reader-status.")
            time.sleep(0.05)
        result["state"] = "stopped"
    return result


def submit(request: dict, *, idle_timeout=DEFAULT_IDLE_TIMEOUT, runtime: Path | None = None) -> dict:
    runtime = runtime or runtime_directory()
    request = {**request, "version": VERSION, "type": "speak"}
    validate_request(request)
    if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > MAX_MESSAGE:
        raise ValueError("Reading request exceeds the 1 MiB limit. Select less text.")
    try:
        return exchange(runtime, request)
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    private_directory(runtime)
    with lock_file(runtime / "startup.lock", STARTUP_TIMEOUT):
        try:
            return exchange(runtime, request)
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        # The lifetime lock is held before loading the model and until full cleanup.
        # Never remove a socket owned by a live or still-starting reader.
        with lock_file(runtime / "reader.lock", STARTUP_TIMEOUT):
            (runtime / "s").unlink(missing_ok=True)
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", "--runtime-dir", str(runtime),
             "--model-dir", request["model_dir"], "--idle-timeout", str(idle_timeout)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Reader failed to start. See {runtime / 'reader.log'}; try --direct for detailed errors.")
                try:
                    return exchange(runtime, request)
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(0.05)
            raise RuntimeError(f"Reader did not become ready within {STARTUP_TIMEOUT:g}s. See {runtime / 'reader.log'}.")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise


def configure_log(runtime: Path):
    # Private, per-checkout, bounded diagnostics. No selected text is logged.
    handler = RotatingFileHandler(runtime / "reader.log", maxBytes=512 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def serve(runtime: Path, model_dir: Path, idle_timeout: float, *, engine_factory=None,
          player_factory=None, stop_event=None, ready_event=None, shutdown_timeout=5.0) -> bool:
    """Return False if a stuck inference requires forced process exit after cleanup."""
    model_dir = model_dir.resolve()
    private_directory(runtime)
    stop_event = stop_event or threading.Event()
    clean = True
    pipeline = None
    with lock_file(runtime / "reader.lock", 0):
        audio_dir = runtime / "audio"
        private_directory(audio_dir)
        # Lifetime lock proves any leftovers belong to a dead reader.
        for audio in audio_dir.glob("*.wav"):
            audio.unlink(missing_ok=True)
        (runtime / "s").unlink(missing_ok=True)
        (runtime / "reader.pid").write_text(str(os.getpid()))
        try:
            # Publish the control endpoint before model loading. Loading/inference
            # run on the same worker and cannot block stop/status/shutdown requests.
            engine = LazyEngine(lambda: (engine_factory or KokoroEngine)(model_dir))
            if stop_event.is_set():
                return True
            options = {} if player_factory is None else {"player_factory": player_factory}
            pipeline = SpeechPipeline(engine, audio_dir, **options)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(runtime / "s"))
                (runtime / "s").chmod(0o600)
                server.listen(8)
                server.settimeout(0.2)
                if ready_event is not None:
                    ready_event.set()
                LOG.info("Reader ready; idle timeout %s seconds", idle_timeout)
                while not stop_event.is_set():
                    state = pipeline.status()
                    if idle_timeout and state["state"] == "idle" and state["idle_seconds"] >= idle_timeout:
                        LOG.info("Idle timeout reached")
                        break
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(1)
                        try:
                            request = validate_request(receive_message(connection))
                            kind = request["type"]
                            if kind == "speak":
                                if Path(request["model_dir"]).resolve() != model_dir:
                                    raise ValueError("Model directory differs from the running reader. Use --shutdown-reader, then retry.")
                                pipeline.speak(request)
                            elif kind == "stop":
                                pipeline.stop()
                            elif kind == "shutdown":
                                pipeline.stop()
                                stop_event.set()
                            response = {"version": VERSION, "ok": True, **pipeline.status(),
                                        "pid": os.getpid(), "model_dir": str(model_dir), "idle_timeout": idle_timeout,
                                        "log_file": str(runtime / "reader.log")}
                            if kind == "shutdown":
                                response["state"] = "shutting_down"
                        except (ValueError, OSError, RuntimeError) as exc:
                            response = {"version": VERSION, "ok": False, "error": str(exc)}
                        try:
                            send_message(connection, response)
                        except (OSError, ValueError):
                            pass
        finally:
            if pipeline is not None:
                clean = pipeline.close(timeout=shutdown_timeout)
            for audio in audio_dir.glob("*.wav"):
                audio.unlink(missing_ok=True)
            (runtime / "reader.pid").unlink(missing_ok=True)
            (runtime / "s").unlink(missing_ok=True)
            LOG.info("Reader stopped%s", "" if clean else "; inference exceeded shutdown deadline")
    return clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE_TIMEOUT)
    args = parser.parse_args()
    if not math.isfinite(args.idle_timeout) or args.idle_timeout < 0:
        parser.error("Idle timeout must be a finite nonnegative number.")
    os.umask(0o077)
    private_directory(args.runtime_dir)
    configure_log(args.runtime_dir)
    stop = threading.Event()

    def terminate(signum, frame):
        stop.set()
        # Also bound shutdown during initial model loading, before serve can poll.
        signal.alarm(8)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        clean = serve(args.runtime_dir, args.model_dir.resolve(), args.idle_timeout, stop_event=stop)
    except Exception as exc:
        LOG.error("Reader stopped with %s. Use --direct for detailed diagnostics.", type(exc).__name__)
        return 1
    if not clean:
        # Inference threads are daemons, but native runtimes may delay interpreter exit.
        os._exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
