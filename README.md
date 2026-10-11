# Local AI Screen Reader for macOS

Read copied text or a selected screen region aloud with a local Kokoro AI voice. Screen mode combines macOS capture with Tesseract OCR; clipboard mode reads copied text directly. No cloud speech API or API key is required.

This is a read-aloud utility, not a replacement for VoiceOver or application navigation.

## Install

Download or clone this repository into a permanent folder, then open Terminal there. Moving the folder later requires rebuilding `.venv` and updating the paths in your Shortcuts.

Requirements: macOS, [Homebrew](https://brew.sh/), Python **3.12**, Tesseract, internet access for installation, and approximately **1 GB** of free disk space. The pinned environment was tested on Apple Silicon with macOS 26.6.2; Intel Macs and older macOS versions are not validated and may not have compatible dependency wheels.

```bash
brew install python@3.12 tesseract
cd /path/to/screen_reader
./scripts/install.sh --check
./scripts/install.sh
```

Alternatively, after installing the prerequisites, double-click **Install.command** in Finder. The installer:

1. Creates this checkout's `.venv` with Python 3.12.
2. Installs direct and transitive dependency versions from `requirements.lock` and runs `pip check`.
3. Downloads roughly 354 MB of Kokoro model and voice data into `models/`, verifies SHA-256 hashes, then publishes each verified download atomically.
4. Runs syntax checks and unit tests and prints the launch commands.

You can rerun the installer. Verified models are reused, and already installed pinned packages are retained. `--check` only checks prerequisites; it does not verify a complete installation. Run only one installation or uninstallation at a time.

To select a Python 3.12 executable explicitly:

```bash
SCREEN_READER_PYTHON=/absolute/path/to/python3.12 ./scripts/install.sh
```

For assisted setup, give your coding assistant [the installation prompt](prompts/install.md). It includes migration, repeatability checks, Shortcuts, and permission troubleshooting.

## Usage

From the project folder:

```bash
# Select a screen region, then hear its text
./scripts/read.sh

# Copy text with Command+C first
./scripts/read.sh --clipboard

# Optional voice and playback speed
./scripts/read.sh --clipboard --voice af_bella --speed 1.0

# British English
./scripts/read.sh --voice bf_emma --speech-language en-gb
```

Screen mode asks you to drag a rectangle around text. Press Escape to cancel. The first reading automatically starts a local reader process; it loads Kokoro and keeps the model warm for later readings. The command returns after the reader accepts the text. A new reading replaces the current speech.

The reader exits after **30 minutes idle**, releasing model memory. Active generation and playback never count as idle. Nothing is installed to start at login.

```bash
./scripts/read.sh --stop                 # Stop speech; keep the model warm
./scripts/read.sh --shutdown-reader      # Stop speech, clean up, and exit
./scripts/read.sh --reader-status        # State, model directory, timeout, last error, log path
./scripts/read.sh --clipboard --idle-timeout 600  # Start with a 10-minute idle timeout
./scripts/read.sh --clipboard --direct   # Foreground diagnostic fallback
```

The timeout applies only when starting a reader. To change an existing reader's timeout, shut it down and start another reading with the desired value. `--idle-timeout 0` disables automatic expiry. Stop, status, and shutdown never start a reader. Shutdown stops playback promptly but can take about five seconds while waiting for inference; a stuck inference is terminated after that deadline. The next reading starts the reader again automatically.

Because normal reading is detached after acceptance, Control+C or stopping the original Shortcut does not stop that speech; use `--stop`. Control+C still stops `--direct` playback. Direct mode loads its own model and can overlap a background reading, so shut the reader down before using it for diagnostics.

Defaults are voice `af_heart`, speed `0.95`, speech language `en-us`, and OCR language `eng`. `--speed` changes speech pace, not model startup latency. See the [Kokoro voice guide](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) for voice choices.

## Keyboard shortcuts

Create **Read Screen** in the macOS Shortcuts app. Add **Run Shell Script**, select **zsh**, and paste this command, replacing the path with your checkout's absolute path:

```bash
"/absolute/path/to/screen_reader/scripts/read.sh"
```

Duplicate it as **Read Clipboard** and use:

```bash
"/absolute/path/to/screen_reader/scripts/read.sh" --clipboard
```

The launcher sets the executable search path and uses this project's Python environment, even when Shortcuts starts elsewhere.

In each shortcut's **Details**, enable **Use as Quick Action** and **Services Menu**, then set **Run with / Add Keyboard Shortcut**:

| Shortcut | Suggested binding | Action |
| --- | --- | --- |
| Read Screen | Control + Option + R | Drag over a text region |
| Read Clipboard | Shift + Command + > | Read text previously copied with Command + C |

Choose alternatives if these conflict with another app or accessibility feature. If macOS blocks scripting, review **Shortcuts → Settings → Advanced → Allow Running Scripts**. Existing reader shortcuts can be edited in place. The older `--engine kokoro` option is no longer needed or accepted.

Create two more shortcuts using the same **Run Shell Script** setup:

| Shortcut | Command | Suggested binding |
| --- | --- | --- |
| Stop Reading | `"/absolute/path/to/screen_reader/scripts/read.sh" --stop` | Shift + Command + < |
| Shut Down Reader | `"/absolute/path/to/screen_reader/scripts/read.sh" --shutdown-reader` | Control + Option + Q |

Stop Reading keeps Kokoro loaded for the next selection. Shut Down Reader releases its memory. Assign these bindings yourself in Shortcuts; the installer does not create or change keyboard bindings.

## Screen-recording permission

Screen capture needs permission for the app macOS considers responsible for the invocation. Open **System Settings → Privacy & Security → Screen & System Audio Recording**, review the relevant app, and quit/reopen it after changing permission if requested. [Apple's permission guide](https://support.apple.com/guide/mac-help/mchld6aa7d23/mac) describes this setting.

**“Could not create image from rect” happens before OCR.** Shortcuts permission alone may not cover a keyboard-triggered run. In a verified local case, macOS attributed the run to the foreground ChatGPT app; allowing that app resolved the error. This is an observed case, not a requirement to grant ChatGPT permission on every machine. Identify the responsible app and grant access only if you intend to allow it to capture your screen.

Clipboard mode does not capture the screen. Successful clipboard playback confirms speech generation works, but does not validate capture permissions or OCR.

## Performance: what has improved

| Improvement present in this version | Practical effect |
| --- | --- |
| Clipboard path skips capture and Tesseract | Avoids selection/OCR work and OCR transcription errors for copyable text |
| Verified model reuse | Repeat installs avoid downloading roughly 354 MB again; checksums are still read and checked |
| Shared launcher and pinned environment | Both shortcuts use the same tested runtime; improves setup consistency, not inference speed |
| Lazy reader with a reusable Kokoro engine | Later readings reuse the loaded model until idle expiry or shutdown |
| Progressive generation and playback | Long selections start playing after the first small chunk; later chunks generate during playback |

The first reading after startup still pays the model-loading and initial inference costs. Later readings reuse the engine. A small bounded queue limits audio generated ahead of playback, and a new reading stops the old player and discards old chunks. An in-progress inference finishes before synthesis of its replacement begins. Separate `afplay` processes may introduce short pauses at chunk boundaries.

[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) describes the implementation and validation approach. Historical timings and the earlier 1.5-second warm-start target are not guaranteed performance.

Prefer clipboard mode for copyable text. Tiny text, columns, tables, or code can reduce OCR quality.

## Uninstall / reinstall

The installer and uninstaller shut down this checkout's reader before modifying its environment. Double-click **Uninstall.command**, or run:

```bash
./scripts/uninstall.sh --dry-run
./scripts/uninstall.sh
./scripts/install.sh
```

Uninstall removes this checkout's `.venv`, the two downloaded Kokoro files, and their partial downloads. It preserves source, documents, unrelated model files, shared caches, Python, Tesseract, and Shortcuts. Models supplied via `--model-dir` outside this checkout are untouched. Delete unwanted shortcuts in Shortcuts yourself; they will work again after reinstalling at the same path.

To test repeatability: install twice, record package versions and model modification times, uninstall twice, then reinstall. Compare `.venv/bin/python -m pip freeze` outputs. Version pins improve repeatability but are not artifact hashes, and do not pin Homebrew packages, Python patch versions, or macOS.

## Command reference

```text
--clipboard                    Read the current clipboard
--voice NAME                   Default: af_heart
--speed NUMBER                 0.5–2.0; default: 0.95
--speech-language CODE         Default: en-us
--ocr-language CODE            Default: eng; requires corresponding Tesseract data
--model-dir DIRECTORY          Override models/
--show-text                    Print extracted text before speaking
--stop                         Stop speech and discard queued audio; keep model loaded
--shutdown-reader              Stop speech, clean up, and exit reader
--reader-status                Show state, last failure, PID, timeout, and log path
--idle-timeout SEC             Idle lifetime on startup; default 1800, 0 disables expiry
--direct                       Foreground full-selection synthesis and playback
```

`SCREEN_READER_MODEL_DIR` also overrides the model directory; the CLI option takes precedence. Run `./scripts/read.sh --help` for help.

## Privacy and troubleshooting

OCR and speech synthesis run locally. The reader's code does not send selected text to a cloud service. Installation contacts package/model hosts; dependencies have their own behavior and licenses. The client performs capture/OCR and passes text over a private Unix socket. Each checkout has a private runtime directory under macOS `$TMPDIR`; the reader removes temporary audio and its socket on shutdown and clears abandoned audio on restart. Small lock files and bounded diagnostic logs remain for reuse. The reader's logs omit selected text. `--show-text` writes text to the caller's output, so avoid it for sensitive material in shared logs.

- **Missing environment or Python packages:** run `./scripts/install.sh` from this checkout. Do not use system-wide pip or sudo.
- **Missing/corrupt model:** run `.venv/bin/python src/download_models.py`; it verifies and replaces invalid downloads.
- **Download or checksum failure:** rerun after restoring connectivity. Do not bypass TLS or checksum verification.
- **No text found:** select a clear paragraph or use clipboard mode. Copy text before invoking Read Clipboard.
- **OCR language error:** run `tesseract --list-langs`; install the required language data or use `eng`.
- **No audio:** check the Mac's output device/volume. Clipboard mode is useful for isolating audio from capture problems.
- **Reading accepted but no speech:** run `./scripts/read.sh --reader-status` for asynchronous synthesis/playback failures and the log location. Shut down the reader and retry with `--direct` for detailed errors.
- **Different model directory:** shut down the existing reader, then retry with `--model-dir`. A running reader uses one model directory.
- **Slow first reading:** model loading and first inference still occur after startup or idle expiry. Subsequent readings reuse that engine.

## Development and public release

Tests can run with Python 3.12 without downloading models or installing the speech dependencies:

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m py_compile src/*.py
bash -n scripts/install.sh scripts/uninstall.sh scripts/read.sh Install.command Uninstall.command
```

Tests use fake engines and players plus real local sockets and subprocesses. Sandboxed environments must permit Unix socket binding to run lifecycle tests. Live model inference, audible quality, screen permissions, and global keyboard invocation need a Mac acceptance test. No automated test suite can grant or verify your privacy choices.

`requirements.txt` records intended direct dependency ranges; `requirements.lock` records the tested full environment. For an intentional update, resolve requirements in a fresh Python 3.12 virtual environment, regenerate the lock, run `pip check`, tests, and both live reading modes. Do not regenerate it from an unrelated environment.

Git ignores environments, models, generated media, logs, and common secret files. Review the actual staged files as well; ignore rules are not a secret scanner.

## License and acknowledgements

Project source is available under the [MIT License](LICENSE). Models and dependencies are not relicensed by it; see [third-party notices](THIRD_PARTY_NOTICES.md). This repository distributes source and download instructions, not a bundled Python environment or model archive.

Built with [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [Tesseract](https://github.com/tesseract-ocr/tesseract), and macOS capture/audio utilities.
