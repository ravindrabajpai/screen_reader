#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    printf 'Reader is not installed. Run: "%s/scripts/install.sh"\n' "$PROJECT_DIR" >&2
    exit 1
fi
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/src/screen_reader.py" "$@"
