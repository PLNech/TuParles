#!/usr/bin/env bash
# One-time Wayland setup — hotkey + delivery without X11.
#
#   bash scripts/setup_wayland.sh     (asks for sudo)
#
# What it does, and why:
#  - input group: the evdev hotkey backend reads /dev/input directly,
#    since Wayland compositors never forward global keys to clients.
#  - uinput rule: delivery pastes via a ydotool virtual keyboard, the
#    only compositor-agnostic way to inject keys on Wayland. (Ubuntu's
#    ydotool 0.1.8 is daemon-less — each call opens /dev/uinput itself.)
#  - wl-clipboard: the real Wayland clipboard (xsel only sees XWayland's).
#
# Idempotent: re-running skips what's already done. Re-login required once
# (group membership is read at session start).
set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# Run as yourself: $USER must be the dictating user, and systemd --user
# needs your session bus. The script sudo's the steps that need root.
if [[ $EUID -eq 0 ]]; then
    echo "error: run without sudo — bash scripts/setup_wayland.sh" >&2
    exit 1
fi

say "System packages (sudo)…"
sudo apt-get install -y -q wl-clipboard ydotool libportaudio2

say "Adding $USER to the input group…"
sudo usermod -aG input "$USER"

say "uinput permissions (udev rule + module at boot)…"
sudo tee /etc/udev/rules.d/60-tuparles-uinput.rules >/dev/null <<'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
EOF
echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput

# Earlier versions of this script installed a ydotoold user service;
# Ubuntu's ydotool 0.1.8 has no such binary — clean up if present.
if systemctl --user is-enabled ydotoold.service &>/dev/null; then
    say "Removing obsolete ydotoold service…"
    systemctl --user disable --now ydotoold.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/ydotoold.service"
    systemctl --user daemon-reload
fi

# GNOME-only: the focus-window extension lets delivery pick Ctrl+Shift+V for
# terminals (like xdotool does on X11). Skipped elsewhere — delivery falls
# back to Ctrl+V without it. New extensions load only after the shell
# restarts, i.e. the next login (Wayland can't reload gnome-shell live).
EXT_UUID="focuswindow@tuparles.local"
EXT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/packaging/gnome-extension/$EXT_UUID"
if [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* && -d "$EXT_SRC" ]]; then
    say "GNOME focus-window extension…"
    EXT_DST="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
    mkdir -p "$EXT_DST"
    cp "$EXT_SRC"/metadata.json "$EXT_SRC"/extension.js "$EXT_DST/"
    # `gnome-extensions enable` refuses an extension the running shell hasn't
    # scanned yet (every fresh install, since Wayland won't reload the shell).
    # The enabled-extensions gsettings array is what the shell reads at login,
    # so append there directly — equivalent, but works pre-scan.
    if ! gnome-extensions enable "$EXT_UUID" 2>/dev/null; then
        python3 - "$EXT_UUID" <<'PY'
import ast, subprocess, sys
uuid = sys.argv[1]
key = ("org.gnome.shell", "enabled-extensions")
cur = subprocess.run(["gsettings", "get", *key],
                     capture_output=True, text=True).stdout.strip()
lst = ast.literal_eval(cur) if cur.startswith("[") else []
if uuid not in lst:
    lst.append(uuid)
    subprocess.run(["gsettings", "set", *key,
                    "[" + ", ".join("'%s'" % e for e in lst) + "]"], check=True)
PY
    fi
fi

say "Done. Log out and back in (group membership + GNOME extension), then start TuParles."
