#!/bin/bash
# Apply source edits WITHOUT touching ZotVault.app — the bundle (and its
# signature, and therefore your Full Disk Access grant) stays frozen.
#
# What it does:
#   1. rsync the current zotvault/ source to ~/.zotvault/app (the runtime
#      code home the app's launcher loads via PYTHONPATH)
#   2. restart the daemon so the new code is loaded
#
# Use this after every code edit. Use build_app.sh only for icon/launcher
# changes (and re-grant FDA afterwards).
#
# Usage:  bash scripts/apply_edits.sh

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="/Applications/ZotVault.app"
[ -d "$APP" ] || APP="$HOME/Applications/ZotVault.app"
[ -d "$APP" ] || { echo "ZotVault.app not found — run scripts/build_app.sh first"; exit 1; }

CODE_DIR="$HOME/.zotvault/app"
mkdir -p "$CODE_DIR"
/usr/bin/rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO/zotvault" "$CODE_DIR/"
echo "synced source -> $CODE_DIR"

# restart the daemon (single-instance lock + launcher will respawn on next open)
pkill -f "zotvault.cli daemon" 2>/dev/null || true
rm -f "$HOME/.zotvault/daemon.pid"
sleep 1
open "$APP"
echo "daemon restarted with the new code."
