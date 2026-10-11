#!/bin/bash
set -u
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
"$PROJECT_DIR/scripts/uninstall.sh"
status=$?
read -r -p "Press Return to close this window..." _
exit "$status"
