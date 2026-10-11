#!/bin/bash

# Double-click this file in Finder to install Local AI Screen Reader.

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

"$PROJECT_DIR/scripts/install.sh"
status=$?

echo
if [[ $status -eq 0 ]]; then
    echo "Installation finished successfully."
else
    echo "Installation stopped with an error."
fi

read -r -p "Press Return to close this window..." _
exit "$status"
