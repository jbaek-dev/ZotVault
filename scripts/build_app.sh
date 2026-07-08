#!/bin/bash
# Build ZotVault.app — a double-clickable launcher for the daemon + dashboard.
#
# What the app does on launch:
#   1. If the ZotVault web/daemon isn't running, start the daemon in the
#      background (single-instance lock makes double-launch safe).
#   2. Open the dashboard in the default browser.
#
# macOS TCC/identity design (hard-won — do not "simplify" this):
#   * The app must be able to hold a Full Disk Access grant (the Obsidian
#     vault lives in an iCloud container). TCC binds grants to the code
#     identity of the RUNNING process:
#       - unsigned bundles           -> cannot hold grants at all
#       - bash-script main executables -> process identity is /bin/bash,
#         not the app, so grants never apply
#     Therefore the app is an **AppleScript applet** (a real Mach-O main
#     binary carrying the bundle identity) that runs Resources/launch.sh via
#     `do shell script` — children inherit the app's TCC identity.
#   * The bundle is ad-hoc signed and then FROZEN. ZotVault code is NOT in
#     the bundle: it lives in ~/.zotvault/app (non-TCC path, PYTHONPATH).
#     Code edits ship with scripts/apply_edits.sh (rsync + daemon restart),
#     which never touches the bundle -> the FDA grant survives.
#   * Re-running THIS script changes the signature: afterwards, remove and
#     re-add the app in System Settings -> Privacy & Security -> Full Disk
#     Access. Only needed for icon/launcher changes.
#
# Usage:  bash scripts/build_app.sh [/Applications]

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-/Applications}"
[ -w "$DEST_DIR" ] || DEST_DIR="$HOME/Applications"
mkdir -p "$DEST_DIR"
APP="$DEST_DIR/ZotVault.app"
PB=/usr/libexec/PlistBuddy

echo "building $APP"
echo "  source: $REPO"

# ---- 1. sync code to its runtime home (outside bundle, outside TCC) ---------
CODE_DIR="$HOME/.zotvault/app"
mkdir -p "$CODE_DIR"
/usr/bin/rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO/zotvault" "$CODE_DIR/"
echo "  code: -> $CODE_DIR/zotvault"

# ---- 2. compile the AppleScript applet (real Mach-O identity holder) --------
TMP_AS="$(mktemp -t zotvault_main).applescript"
cat > "$TMP_AS" << 'AS'
set sh to POSIX path of (path to resource "launch.sh")
do shell script "/bin/bash " & quoted form of sh
AS
rm -rf "$APP"
/usr/bin/osacompile -o "$APP" "$TMP_AS"
rm -f "$TMP_AS"

# ---- 3. launcher shell logic (inside the frozen bundle) ----------------------
cat > "$APP/Contents/Resources/launch.sh" << 'LAUNCH'
#!/bin/bash
# ZotVault launcher body. Runs with the app's TCC identity via the applet.
export PYTHONPATH="$HOME/.zotvault/app"
PY=/usr/bin/python3
CONF="$HOME/.zotvault/config.toml"
PORT=$(grep -m1 -E '^[[:space:]]*port[[:space:]]*=' "$CONF" 2>/dev/null | grep -oE '[0-9]+' | head -1)
PORT="${PORT:-8377}"
URL="http://127.0.0.1:${PORT}"

alertq() {
  /usr/bin/osascript -e "display alert \"ZotVault\" message \"$1\"" >/dev/null 2>&1
  exit 0
}

[ -d "$HOME/.zotvault/app/zotvault" ] || alertq "code not found in ~/.zotvault/app — run scripts/build_app.sh (or apply_edits.sh) from the repo"

# First run: create a starter config, open it, and stop here.
if [ ! -f "$CONF" ]; then
  mkdir -p "$HOME/.zotvault"
  "$PY" -m zotvault.cli init >/dev/null 2>&1 || true
  /usr/bin/open -e "$CONF" 2>/dev/null
  alertq "First run: a starter config was created at ~/.zotvault/config.toml. Set your vault path (and Unpaywall email), then click the icon again."
fi

up() { /usr/bin/curl -s -m 1 -o /dev/null "$URL/api/status"; }

if ! up; then
  /usr/bin/nohup "$PY" -m zotvault.cli daemon >> "$HOME/.zotvault/launcher.log" 2>&1 &
  ok=""
  for _ in $(seq 1 40); do
    sleep 0.5
    if up; then ok=1; break; fi
  done
  [ -n "$ok" ] || alertq "daemon did not come up — see ~/.zotvault/zotvault.log"
fi

/usr/bin/open "$URL"
exit 0
LAUNCH
chmod +x "$APP/Contents/Resources/launch.sh"

# ---- 4. bundle metadata -------------------------------------------------------
PLIST="$APP/Contents/Info.plist"
set_or_add() {  # key type value
  $PB -c "Set :$1 $3" "$PLIST" 2>/dev/null || $PB -c "Add :$1 $2 $3" "$PLIST"
}
set_or_add CFBundleIdentifier string com.zotvault.launcher
set_or_add CFBundleName string ZotVault
set_or_add CFBundleDisplayName string ZotVault
set_or_add CFBundleShortVersionString string 0.9.0
set_or_add CFBundleVersion string 0.9.0
set_or_add LSUIElement bool true
set_or_add LSMinimumSystemVersion string 11.0
set_or_add NSDocumentsFolderUsageDescription string "ZotVault reads and writes paper notes in your Obsidian vault."

# ---- 5. icon (osacompile names it applet.icns) --------------------------------
if [ -d "$REPO/assets/icon.iconset" ]; then
  iconutil -c icns "$REPO/assets/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
fi

# ---- 6. sign LAST, then freeze -------------------------------------------------
codesign --force --deep -s - "$APP"
echo "  signed (ad-hoc, frozen — do not modify the bundle after this)"

/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" 2>/dev/null || true

echo "done: $APP"
echo "REMINDER: (re)grant Full Disk Access to this app now (remove old entry, add this one)."
