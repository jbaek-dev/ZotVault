#!/bin/bash
# Build PaperFlow.app — a double-clickable launcher for the daemon + dashboard.
#
# What the app does on launch:
#   1. If the PaperFlow web/daemon isn't running, start the daemon in the
#      background (single-instance lock makes double-launch safe).
#   2. Open the dashboard in the default browser.
#
# Usage:  bash scripts/build_app.sh [/Applications]
# The repo path is baked into the launcher at build time.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-/Applications}"
[ -w "$DEST_DIR" ] || DEST_DIR="$HOME/Applications"
mkdir -p "$DEST_DIR"
APP="$DEST_DIR/PaperFlow.app"

echo "building $APP (repo: $REPO)"

# Install the package into user site-packages first. This matters on macOS:
# a GUI-launched app cannot read code inside ~/Documents (TCC protection),
# so the daemon must import paperflow from site-packages instead of the repo.
/usr/bin/python3 -m pip install --user --quiet --upgrade . || {
  echo "pip install failed"; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

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
</dict>
</plist>
PLIST

# ---- launcher ----------------------------------------------------------------
cat > "$APP/Contents/MacOS/PaperFlow" << LAUNCHER
#!/bin/bash
REPO="$REPO"
LAUNCHER
cat >> "$APP/Contents/MacOS/PaperFlow" << 'LAUNCHER'
PY=/usr/bin/python3
CONF="$HOME/.paperflow/config.toml"
PORT=$(grep -m1 -E '^[[:space:]]*port[[:space:]]*=' "$CONF" 2>/dev/null | grep -oE '[0-9]+' | head -1)
PORT="${PORT:-8377}"
URL="http://127.0.0.1:${PORT}"

fail() {
  /usr/bin/osascript -e "display alert \"PaperFlow\" message \"$1\" as critical" >/dev/null 2>&1
  exit 1
}

"$PY" -c "import paperflow" 2>/dev/null || fail "paperflow not installed for $PY — run scripts/build_app.sh again"

up() { /usr/bin/curl -s -m 1 -o /dev/null "$URL/api/status"; }

if ! up; then
  mkdir -p "$HOME/.paperflow"
  cd "$HOME"
  /usr/bin/nohup "$PY" -m paperflow.cli daemon >> "$HOME/.paperflow/launcher.log" 2>&1 &
  ok=""
  for _ in $(seq 1 30); do
    sleep 0.5
    if up; then ok=1; break; fi
  done
  [ -n "$ok" ] || fail "daemon did not come up — check ~/.paperflow/paperflow.log"
fi

exec /usr/bin/open "$URL"
LAUNCHER
chmod +x "$APP/Contents/MacOS/PaperFlow"

# ---- ad-hoc sign (harmless if codesign is missing) ------------------------------
command -v codesign >/dev/null && codesign --force --deep -s - "$APP" 2>/dev/null || true

echo "done: $APP"
