#!/usr/bin/env bash
# One-time Wayland setup — hotkey + delivery without X11. Distro-portable
# (apt/pacman/dnf/zypper) and compositor-aware (GNOME extra, others fall back).
#
#   bash scripts/setup_wayland.sh     (asks for sudo)
#
# What it does, and why:
#  - input group: the evdev hotkey backend reads /dev/input directly,
#    since Wayland compositors never forward global keys to clients.
#  - uinput rule: delivery pastes via a ydotool virtual keyboard, the
#    only compositor-agnostic way to inject keys on Wayland.
#  - ydotool daemon: modern ydotool (≥1.0, Arch/Fedora) talks to a ydotoold
#    daemon — we install it as a *user* service. Ubuntu's 0.1.8 is daemon-less
#    (each call opens /dev/uinput itself); there we only clean up a stale unit.
#  - wl-clipboard: the real Wayland clipboard (xsel only sees XWayland's).
#
# Idempotent: re-running skips what's already done. Re-login required once
# (group membership is read at session start).
set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Run as yourself: $USER must be the dictating user, and systemd --user
# needs your session bus. The script sudo's the steps that need root.
if [[ $EUID -eq 0 ]]; then
    echo "error: run without sudo — bash scripts/setup_wayland.sh" >&2
    exit 1
fi

# --- portable system packages (kept in sync with install.sh) ------------------
detect_pm() {
    for pm in apt-get dnf pacman zypper; do
        command -v "$pm" >/dev/null && { echo "$pm"; return; }
    done
}
map_pkg() {
    case "$1:$2" in
        *:openblas-dev) case "$1" in
            apt-get) echo libopenblas-dev ;; *) echo openblas-devel ;; esac ;;
        pacman:openblas-dev) echo openblas ;;
        *:portaudio) case "$1" in
            pacman|dnf) echo portaudio ;; *) echo libportaudio2 ;; esac ;;
        *) echo "$2" ;;
    esac
}
pkg_install() {
    local pm; pm="$(detect_pm)"
    [[ -n "$pm" ]] || die "no supported package manager — install these yourself: $*"
    local pkgs=(); local p; for p in "$@"; do pkgs+=("$(map_pkg "$pm" "$p")"); done
    case "$pm" in
        apt-get) sudo apt-get update -qq && sudo apt-get install -y -q "${pkgs[@]}" ;;
        pacman)  sudo pacman -S --needed --noconfirm "${pkgs[@]}" ;;
        dnf)     sudo dnf install -y "${pkgs[@]}" ;;
        zypper)  sudo zypper install -y "${pkgs[@]}" ;;
    esac
}
# -----------------------------------------------------------------------------

say "System packages (sudo)…"
pkg_install wl-clipboard ydotool portaudio

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

# Modern ydotool (≥1.0) needs a running ydotoold; Ubuntu's 0.1.8 doesn't ship
# one and is daemon-less. Branch on the binary's presence.
if command -v ydotoold >/dev/null; then
    say "ydotoold user service (modern ydotool)…"
    SOCK='%t/.ydotool_socket'   # %t = $XDG_RUNTIME_DIR, expanded by systemd
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/ydotoold.service" <<EOF
[Unit]
Description=ydotoold — virtual input for TuParles Wayland delivery
Documentation=https://github.com/PLNech/TuParles

[Service]
ExecStart=$(command -v ydotoold) -p $SOCK -P 0660
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    # ydotool finds the daemon via $YDOTOOL_SOCKET; export it to the whole user
    # session (environment.d is read by systemd --user and the graphical login,
    # so TuParles launched from the menu inherits it too).
    ENV_DIR="$HOME/.config/environment.d"
    mkdir -p "$ENV_DIR"
    echo 'YDOTOOL_SOCKET=${XDG_RUNTIME_DIR}/.ydotool_socket' \
        > "$ENV_DIR/tuparles-ydotool.conf"
    systemctl --user daemon-reload
    # Needs /dev/uinput access, granted by the udev rule + input group above —
    # which only takes effect after re-login, so a start now may fail. Enable
    # unconditionally; it comes up cleanly on next login. Try a start anyway.
    systemctl --user enable ydotoold.service >/dev/null 2>&1 || true
    systemctl --user start ydotoold.service >/dev/null 2>&1 || \
        say "  (ydotoold will start after re-login, once input-group access lands)"
else
    # Ubuntu 0.1.8 path: daemon-less. Remove any obsolete user unit a previous
    # modern-ydotool setup (or an old version of this script) may have left.
    if systemctl --user is-enabled ydotoold.service &>/dev/null; then
        say "Removing obsolete ydotoold service (daemon-less ydotool)…"
        systemctl --user disable --now ydotoold.service 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/ydotoold.service"
        systemctl --user daemon-reload
    fi
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
elif [[ "${XDG_CURRENT_DESKTOP:-}" != *GNOME* ]]; then
    say "Non-GNOME desktop (${XDG_CURRENT_DESKTOP:-?}): terminal paste uses Ctrl+Shift+V"
    say "  heuristically by window title; plain Ctrl+V elsewhere."
fi

say "Done. Log out and back in (group membership + ydotoold + any extension),"
say "then start TuParles."
