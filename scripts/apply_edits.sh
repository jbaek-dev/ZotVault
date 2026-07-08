#!/bin/bash
# Apply source edits to the installed PaperFlow.app WITHOUT rebuilding or
# re-signing — so your Full Disk Access grant is preserved.
#
# What it does:
#   1. rsync the current paperflow/ source into the app bundle
#   2. restart the daemon so the new code is loaded
#
# Use this after editing code. Use build_app.sh only for icon/launcher changes.
#
# Usage:  bash scripts/apply_edits.sh

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="/Applications/PaperFlow.app"
[ -d "$APP" ] || APP="$HOME/Applications/PaperFlow.app"
[ -d "$APP" ] || { echo "PaperFlow.app not found — run scripts/build_app.sh first"; exit 1; }

/usr/bin/rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO/paperflow" "$APP/Contents/Resources/"
echo "synced source -> $APP"

# restart the daemon (single-instance lock + launcher will respawn on next open)
pkill -f "paperflow.cli daemon" 2>/dev/null || true
rm -f "$HOME/.paperflow/daemon.pid"
sleep 1
open "$APP"
echo "daemon restarted with the new code."
