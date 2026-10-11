#!/usr/bin/env bash
# Remove only generated runtime files from this checkout; keep source and Shortcuts.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ $# -gt 1 || ( "${1:-}" != "" && "${1:-}" != "--dry-run" ) ]]; then
    printf 'Usage: %s [--dry-run]\n' "$0" >&2
    exit 1
fi
[[ -f "$PROJECT_DIR/src/screen_reader.py" && -f "$PROJECT_DIR/requirements.txt" ]] || exit 1
# Validate everything before removing anything. Never follow directory symlinks.
for name in .venv models; do
    if [[ -L "$PROJECT_DIR/$name" ]]; then
        printf 'Refusing to remove symlink: %s\n' "$PROJECT_DIR/$name" >&2
        exit 1
    fi
done
if [[ -d "$PROJECT_DIR/.venv" && ! -f "$PROJECT_DIR/.venv/pyvenv.cfg" ]]; then
    printf 'Refusing to remove .venv without pyvenv.cfg\n' >&2
    exit 1
fi
shopt -s nullglob
targets=("$PROJECT_DIR/.venv" "$PROJECT_DIR/models/kokoro-v1.0.onnx" "$PROJECT_DIR/models/voices-v1.0.bin"
    "$PROJECT_DIR/models/kokoro-v1.0.onnx.part" "$PROJECT_DIR/models/voices-v1.0.bin.part"
    "$PROJECT_DIR"/models/kokoro-v1.0.onnx.*.part "$PROJECT_DIR"/models/voices-v1.0.bin.*.part)
for target in "${targets[@]}"; do
    if [[ "$target" != "$PROJECT_DIR/.venv" && -d "$target" && ! -L "$target" ]]; then
        printf 'Refusing to remove directory at model file path: %s\n' "$target" >&2
        exit 1
    fi
done
if [[ "${1:-}" != "--dry-run" && -x "$PROJECT_DIR/.venv/bin/python" && -f "$PROJECT_DIR/src/reader_process.py" ]]; then
    "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/src/screen_reader.py" --shutdown-reader
fi
for target in "${targets[@]}"; do
    if [[ -e "$target" || -L "$target" ]]; then
        printf 'Remove: %s\n' "$target"
        if [[ "${1:-}" != "--dry-run" ]]; then
            if [[ "$target" == "$PROJECT_DIR/.venv" ]]; then
                rm -rf -- "$target"
            else
                rm -f -- "$target"
            fi
        fi
    fi
done
if [[ "${1:-}" != "--dry-run" && -d "$PROJECT_DIR/models" ]]; then
    rmdir "$PROJECT_DIR/models" 2>/dev/null || true
fi
printf 'Source, unrelated model files, Shortcuts, Homebrew packages, and shared caches are preserved.\n'
