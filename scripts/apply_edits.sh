#!/bin/bash
# Apply source edits WITHOUT touching PaperFlow.app — the bundle (and its
# signature, and therefore your Full Disk Access grant) stays frozen.
#
# What it does:
#   1. rsync the current paperflow/ source to ~/.paperflow/app (the runtime
#      code home the app's launcher loads via PYTHONPATH)
#   2. restart the daemon so the new code is loaded
#
# Use this after every code edit. Use build_app.sh only for icon/launcher
# changes (and re-grant FDA afterwards).
#
# Usage:  bash scripts/apply_edits.sh

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="/Applications/PaperFlow.app"
[ -d "$APP" ] || APP="$HOME/Applications/PaperFlow.app"
[ -d "$APP" ] || { echo "PaperFlow.app not found — run scripts/build_app.sh first"; exit 1; }

CODE_DIR="$HOME/.paperflow/app"
mkdir -p "$CODE_DIR"
/usr/bin/rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO/paperflow" "$CODE_DIR/"
echo "synced source -> $CODE_DIR"

# restart the daemon (single-instance lock + launcher will respawn on next open)
pkill -f "paperflow.cli daemon" 2>/dev/null || true
rm -f "$HOME/.paperflow/daemon.pid"
sleep 1
open "$APP"
echo "daemon restarted with the new code."
