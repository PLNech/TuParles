#!/usr/bin/env bash
# Install TuParles into the desktop: icon + launcher visible in the app launcher
# (GNOME search, KDE Kickoff, etc. — any XDG-compliant desktop).
# Idempotent; run from anywhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

VENV="$(cd "$REPO" && poetry env info --path)"
EXEC="$VENV/bin/tuparles"
[[ -x "$EXEC" ]] || { echo "error: $EXEC not found — run 'poetry install' first"; exit 1; }

if [[ ! -f "$REPO/packaging/tuparles.png" ]]; then
    (cd "$REPO" && QT_QPA_PLATFORM=offscreen poetry run python scripts/app_icon.py)
fi

mkdir -p "$APPS_DIR" "$ICON_DIR"
cp "$REPO/packaging/tuparles.png" "$ICON_DIR/tuparles.png"
sed "s|@EXEC@|$EXEC|" "$REPO/packaging/tuparles.desktop.in" > "$APPS_DIR/tuparles.desktop"

update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed: $APPS_DIR/tuparles.desktop → $EXEC"
echo "Your app launcher (GNOME search, KDE Kickoff, …) should now find 'TuParles'."
