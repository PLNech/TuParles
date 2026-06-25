#!/usr/bin/env bash
# TuParles installer — Linux, distro-portable (apt/pacman/dnf/zypper). X11 works
# out of the box; a Wayland session additionally needs
# `bash scripts/setup_wayland.sh` afterward (see README).
#
#   curl -fsSL https://github.com/PLNech/TuParles/releases/latest/download/install.sh | bash
#
# Idempotent: re-running updates the checkout and skips what's already done.
set -euo pipefail

REPO_URL="https://github.com/PLNech/TuParles"
DIR="${TUPARLES_HOME:-$HOME/.local/share/tuparles}"
MODEL_DIR="models/qwen3-asr-0.6b"
MODEL_BASE="https://huggingface.co/Qwen/Qwen3-ASR-0.6B/resolve/main"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- portable system packages -------------------------------------------------
# install.sh runs standalone (the curl one-liner fetches only this file, then it
# clones the repo), so the package layer is self-contained here rather than
# sourced. setup_wayland.sh carries an identical copy; keep them in sync.
detect_pm() {
    for pm in apt-get dnf pacman zypper; do
        command -v "$pm" >/dev/null && { echo "$pm"; return; }
    done
}
# Map a logical name to the package providing it on $1=pm. Names equal across
# distros (xdotool, xsel, ffmpeg, wl-clipboard, ydotool) just echo through.
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
    [[ -n "$pm" ]] || die "no supported package manager (apt/pacman/dnf/zypper) — install these yourself: $*"
    local pkgs=(); local p; for p in "$@"; do pkgs+=("$(map_pkg "$pm" "$p")"); done
    case "$pm" in
        apt-get) sudo apt-get update -qq && sudo apt-get install -y -q "${pkgs[@]}" ;;
        pacman)  sudo pacman -S --needed --noconfirm "${pkgs[@]}" ;;
        dnf)     sudo dnf install -y "${pkgs[@]}" ;;
        zypper)  sudo zypper install -y "${pkgs[@]}" ;;
    esac
}
# -----------------------------------------------------------------------------

command -v git >/dev/null || die "git is required"
command -v poetry >/dev/null || die "poetry is required (https://python-poetry.org)"
[[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] && \
    echo "note: Wayland session — after this finishes, run 'bash scripts/setup_wayland.sh'" \
         "for native Wayland delivery (or keep using the X11 path under XWayland)" >&2

say "System dependencies (sudo)…"
pkg_install openblas-dev xdotool xsel portaudio ffmpeg

if [[ -d "$DIR/.git" ]]; then
    say "Updating existing install in $DIR"
    git -C "$DIR" pull --ff-only
else
    say "Cloning into $DIR"
    git clone --depth 1 "$REPO_URL" "$DIR"
fi
cd "$DIR"

say "Python environment…"
poetry install --quiet

say "CPU fallback engine (antirez/qwen-asr)…"
if [[ ! -d vendor/qwen-asr ]]; then
    git clone --depth 1 https://github.com/antirez/qwen-asr vendor/qwen-asr
fi
make -C vendor/qwen-asr blas

say "Model weights (~1.8 GB, skipped if present)…"
mkdir -p "$MODEL_DIR"
for f in config.json generation_config.json model.safetensors vocab.json merges.txt; do
    [[ -f "$MODEL_DIR/$f" ]] || curl -fL --progress-bar -o "$MODEL_DIR/$f" "$MODEL_BASE/$f"
done

[[ -f vocab.txt ]] || cp vocab.example.txt vocab.txt

say "Desktop entry…"
bash scripts/install_desktop.sh

say "Done. Launch 'TuParles' from your app launcher, or: cd $DIR && poetry run tuparles"
say "Dictate with Right Ctrl + Right Alt. Edit vocab.txt with your own names."
[[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] && \
    say "Wayland: run 'bash $DIR/scripts/setup_wayland.sh' first, then log out and back in."
