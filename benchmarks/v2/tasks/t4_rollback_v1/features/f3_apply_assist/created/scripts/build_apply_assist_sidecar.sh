#!/bin/sh
set -eu
DEST=${1:?usage: $0 /absolute/outside-host/path}
case "$DEST" in "$PWD"/*) echo 'sidecar environment must be outside host tree' >&2; exit 2;; esac
python3 -m venv "$DEST"
"$DEST/bin/pip" install -r "$(dirname "$0")/../requirements-apply-assist.txt"
echo "set APPLY_ASSIST_SIDECAR_PYTHON=$DEST/bin/python"
