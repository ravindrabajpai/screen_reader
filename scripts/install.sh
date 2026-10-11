#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="$PROJECT_DIR/.venv"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

info() {
    printf '\n==> %s\n' "$1"
}

fail() {
    printf '\nError: %s\n' "$1" >&2
    exit 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "This installer requires macOS."
fi

if [[ $# -gt 1 || ( "${1:-}" != "" && "${1:-}" != "--check" ) ]]; then
    fail "Unknown option: $1"
fi

command -v tesseract >/dev/null 2>&1 || fail \
    "Tesseract is not installed. Run: brew install tesseract"
PYTHON_BIN="${SCREEN_READER_PYTHON:-python3.12}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail \
    "Python 3.12 is missing. Run: brew install python@3.12 tesseract"

"$PYTHON_BIN" - <<'PY' || fail "Use Python 3.12 for this installation."
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY

if [[ "${1:-}" == "--check" ]]; then
    printf 'Project: %s\n' "$PROJECT_DIR"
    printf 'Python: %s\n' "$("$PYTHON_BIN" --version 2>&1)"
    printf 'Tesseract: %s\n' "$(tesseract --version | head -n 1)"
    printf 'Installer prerequisites look good.\n'
    exit 0
fi

if [[ ! -e "$VENV_DIR" && ! -L "$VENV_DIR" ]]; then
    info "Creating the Python 3.12 virtual environment"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
[[ ! -L "$VENV_DIR" && -x "$VENV_DIR/bin/python" && -f "$VENV_DIR/pyvenv.cfg" ]] || fail \
    "Invalid .venv. Move it aside and rerun the installer."
"$VENV_DIR/bin/python" - <<'PY' || fail "Existing .venv must use Python 3.12. Uninstall and reinstall."
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY

info "Installing Python packages"
if [[ -f "$PROJECT_DIR/src/reader_process.py" ]]; then
    "$VENV_DIR/bin/python" "$PROJECT_DIR/src/screen_reader.py" --shutdown-reader
fi
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.lock"
"$VENV_DIR/bin/python" -m pip check

info "Downloading and verifying the Kokoro model"
[[ ! -L "$PROJECT_DIR/models" ]] || fail "Refusing to install into a symlinked models directory."
"$VENV_DIR/bin/python" "$PROJECT_DIR/src/download_models.py"

info "Checking the installation"
"$VENV_DIR/bin/python" -m py_compile \
    "$PROJECT_DIR/src/screen_reader.py" \
    "$PROJECT_DIR/src/reader_process.py" \
    "$PROJECT_DIR/src/reader_protocol.py" \
    "$PROJECT_DIR/src/speech_pipeline.py" \
    "$PROJECT_DIR/src/text_chunker.py" \
    "$PROJECT_DIR/src/download_models.py"
(
    cd "$PROJECT_DIR"
    PYTHONPATH="$PROJECT_DIR/src" "$VENV_DIR/bin/python" -m unittest discover -s tests -v
)

cat <<EOF

Local AI Screen Reader is ready.

Read a screen selection:
  "$PROJECT_DIR/scripts/read.sh"

Read copied text:
  "$PROJECT_DIR/scripts/read.sh" --clipboard

Stop speech (keep model warm):
  "$PROJECT_DIR/scripts/read.sh" --stop

Shut down the reader (release model memory):
  "$PROJECT_DIR/scripts/read.sh" --shutdown-reader

See README.md for macOS Shortcut setup and voice options.
EOF
