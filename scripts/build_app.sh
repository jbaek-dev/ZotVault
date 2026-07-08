#!/bin/bash
# Build PaperFlow.app — a double-clickable launcher for the daemon + dashboard.
#
# What the app does on launch:
#   1. If the PaperFlow web/daemon isn't running, start the daemon in the
#      background (single-instance lock makes double-launch safe).
#   2. Open the dashboard in the default browser.
#
# The paperflow code is COPIED into the app bundle (Contents/Resources) and
# loaded via PYTHONPATH. Why: /Applications is not TCC-protected, so a
# GUI-launched (double-clicked) app can always import the code WITHOUT Full
# Disk Access. Only the vault (Obsidian, under a protected path) needs FDA,
# which you grant once.
#
# After editing the source, apply changes with the fast, no-resign helper:
#     bash scripts/apply_edits.sh      # rsync code into the app, restart daemon
# That preserves the FDA grant (no re-sign). Re-run THIS full build only for
# icon/launcher changes or a fresh install.
#
# Usage:  bash scripts/build_app.sh [/Applications]

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-/Applications}"
[ -w "$DEST_DIR" ] || DEST_DIR="$HOME/Applications"
mkdir -p "$DEST_DIR"
APP="$DEST_DIR/PaperFlow.app"

echo "building $APP"
echo "  source: $REPO"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ---- bundle the code (self-contained; loads without FDA) --------------------
/usr/bin/rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO/paperflow" "$APP/Contents/Resources/"
echo "  bundled: paperflow/ -> Contents/Resources/"

# ---- icon ------------------------------------------------------------------
if [ -d "$REPO/assets/icon.iconset" ]; then
  iconutil -c icns "$REPO/assets/icon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
fi

# ---- Info.plist -------------------------------------------------------------
cat > "$APP/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>PaperFlow</string>
    <key>CFBundleDisplayName</key><string>PaperFlow</string>
    <key>CFBundleIdentifier</key><string>com.paperflow.launcher</string>
    <key>CFBundleVersion</key><string>0.5.0</string>
    <key>CFBundleShortVersionString</key><string>0.5.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>PaperFlow</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSDocumentsFolderUsageDescription</key>
    <string>PaperFlow reads and writes paper notes in your Obsidian vault.</string>
    <key>NSDesktopFolderUsageDescription</key>
    <string>Only needed if your vault lives on the Desktop.</string>
    <key>NSDownloadsFolderUsageDescription</key>
    <string>Only needed if your vault lives in Downloads.</string>
</dict>
</plist>
PLIST

# ---- launcher ----------------------------------------------------------------
cat > "$APP/Contents/MacOS/PaperFlow" << 'LAUNCHER'
#!/bin/bash
# Self-contained launcher: code is bundled in ../Resources/paperflow.
HERE="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$(cd "$HERE/../Resources" && pwd)"
PY=/usr/bin/python3
CONF="$HOME/.paperflow/config.toml"
PORT=$(grep -m1 -E '^[[:space:]]*port[[:space:]]*=' "$CONF" 2>/dev/null | grep -oE '[0-9]+' | head -1)
PORT="${PORT:-8377}"
URL="http://127.0.0.1:${PORT}"

fail() {
  /usr/bin/osascript -e "display alert \"PaperFlow\" message \"$1\" as critical" >/dev/null 2>&1
  exit 1
}

# First run: create a starter config so `doctor`/daemon have somewhere to look.
if [ ! -f "$CONF" ]; then
  mkdir -p "$HOME/.paperflow"
  "$PY" -m paperflow.cli init >/dev/null 2>&1 || true
  /usr/bin/osascript -e 'display alert "PaperFlow — first run" message "A starter config was created at ~/.paperflow/config.toml. Set your vault path (and Unpaywall email), then click the icon again." as informational' >/dev/null 2>&1
  exec /usr/bin/open -e "$CONF"
fi

up() { /usr/bin/curl -s -m 1 -o /dev/null "$URL/api/status"; }

if ! up; then
  cd "$HOME"
  /usr/bin/nohup "$PY" -m paperflow.cli daemon >> "$HOME/.paperflow/launcher.log" 2>&1 &
  ok=""
  for _ in $(seq 1 40); do
    sleep 0.5
    if up; then ok=1; break; fi
  done
  [ -n "$ok" ] || fail "daemon did not come up — see ~/.paperflow/paperflow.log"
fi

exec /usr/bin/open "$URL"
LAUNCHER
chmod +x "$APP/Contents/MacOS/PaperFlow"

# ---- ad-hoc sign (harmless if codesign is missing) ------------------------------
command -v codesign >/dev/null && codesign --force --deep -s - "$APP" 2>/dev/null || true

# refresh LaunchServices registration so the new build launches cleanly
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" 2>/dev/null || true

echo "done: $APP"
