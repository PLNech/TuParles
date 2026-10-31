#!/usr/bin/env bash
# Put TuParles where Spotlight can find it.
#
# macOS does not index a Linux .desktop file. This writes a thin
# TuParles.app whose launcher execs the poetry-managed `tuparles` binary,
# so a checkout update is picked up on the next launch. Idempotent.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${TUPARLES_APP_DEST:-/Applications/TuParles.app}"
VENV="$(cd "$REPO" && poetry env info --path)"
EXEC="$VENV/bin/tuparles"
[[ -x "$EXEC" ]] || {
  echo "error: $EXEC not found — run 'poetry install --with mlx' first" >&2
  exit 1
}

MACOS="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"
rm -rf "$APP"
mkdir -p "$MACOS" "$RES"

# Spotlight matches CFBundleName. The executable must be a Mach-O that
# lives in this bundle. A shell that execs the poetry binary makes macOS
# attribute the process to Homebrew's Python.app: the menu-bar icon lands
# off-screen (measured at x=71105) and the chord prompt names Python.
# This stub embeds Python and stays TuParles.app. Site-packages stay in
# the venv; the boot script inserts them.
CC="${CC:-clang}"
# The venv does not ship python-config. The base interpreter does, and
# that is the libpython this process must link.
BASE_BIN="$(cd "$VENV/bin" && pwd -P)/python"
# readlink is not recursive and a relative link stays relative.
while [ -L "$BASE_BIN" ]; do
  LINK="$(readlink "$BASE_BIN")"
  case "$LINK" in
    /*) BASE_BIN="$LINK" ;;
    *) BASE_BIN="$(cd "$(dirname "$BASE_BIN")" && pwd)/$LINK" ;;
  esac
done
BASE_DIR="$(cd "$(dirname "$BASE_BIN")" && pwd)"
PY_VER="$("$VENV/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PYCFG="$BASE_DIR/python${PY_VER}-config"
[[ -x "$PYCFG" ]] || PYCFG="$BASE_DIR/python3-config"
[[ -x "$PYCFG" ]] || { echo "error: python-config not next to $BASE_BIN" >&2; exit 1; }
STUB="$REPO/scripts/macos_app_main.m"
"$CC" -O2 -o "$MACOS/TuParles" "$STUB" \
  $("$PYCFG" --cflags --ldflags --embed) -lpython3.13
chmod 755 "$MACOS/TuParles"

# Editable installs live in the checkout, not in site-packages. Take the
# interpreter's own path so a poetry relink is picked up on reinstall.
PATHS="$("$VENV/bin/python" -c 'import sys; print("\n".join(p for p in sys.path if p))')"
python3 - "$RES/tuparles-boot.py" "$PATHS" << 'PY'
import sys
from pathlib import Path

dest, raw = sys.argv[1], sys.argv[2]
paths = [p for p in raw.splitlines() if p]
lines = [
    "import os",
    "import sys",
]
for path in reversed(paths):
    lines.append(f"sys.path.insert(0, {path!r})")
lines += [
    "os.chdir(os.path.expanduser('~'))",
    "from tuparles.cli import main",
    "main()",
    "",
]
Path(dest).write_text("\n".join(lines), encoding="utf-8")
PY

# icns from the existing 256px icon. sips writes a one-size iconset entry.
ICONSET="$(mktemp -d)/tuparles.iconset"
mkdir -p "$ICONSET"
sips -z 256 256 "$REPO/packaging/tuparles.png" --out "$ICONSET/icon_256x256.png" >/dev/null
iconutil -c icns "$ICONSET" -o "$RES/tuparles.icns"
rm -rf "$(dirname "$ICONSET")"

cat > "$APP/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>TuParles</string>
  <key>CFBundleDisplayName</key>
  <string>TuParles</string>
  <key>CFBundleIdentifier</key>
  <string>pl.nech.tuparles</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>CFBundleShortVersionString</key>
  <string>0.5.1</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>TuParles</string>
  <key>PyRuntimeLocations</key>
  <array>
    <string>@executable_path/../Resources</string>
  </array>
  <key>CFBundleIconFile</key>
  <string>tuparles</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <!-- Tray-only: no Dock icon, no Cmd-Tab entry. The status item survives. -->
  <key>LSUIElement</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>TuParles listens while you hold the dictation chord.</string>
</dict>
</plist>
EOF

# Ask Spotlight to notice the new bundle without a full reindex.
mdimport "$APP" 2>/dev/null || true

echo "Installed: $APP"
echo "Launcher:  $EXEC"
echo "Open with Spotlight (TuParles) or: open -a TuParles"
# Rebuilding swaps the executable, and macOS TCC keys its grants to that
# binary: Input Monitoring (the chord) and Microphone can reset silently.
# The daemon probes both at boot and prompts, but the user should know why.
echo "Note: a reinstall can reset macOS permissions. If the chord is deaf or"
echo "the mic silent, re-grant TuParles in System Settings › Privacy & Security"
echo "(the app will also prompt at its next launch)."
