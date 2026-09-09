# Qt6 apps render as bare Fusion, not GTK/Adwaita

TuParles (PySide6/Qt6) currently draws with unthemed Fusion — "feels 1996".
Cause: `QT_QPA_PLATFORMTHEME=qt5ct` is exported globally, but that variable
only wires up Qt5 apps to qt5ct; Qt6 ignores qt5ct and has no theme plugin
selected, so it falls back to bare Fusion.

Ubuntu 24.04.4 LTS (noble). Installed Qt6: 6.4.2+dfsg (libqt6core6t64 etc).

## Findings

| package | available (apt) | already installed | plugin already on disk |
|---|---|---|---|
| `qt6-gtk-platformtheme` | yes, universe, 6.4.2+dfsg-21.1build5 | **yes, already installed** | **yes** — `/usr/lib/x86_64-linux-gnu/qt6/plugins/platformthemes/libqgtk3.so` |
| `qt6ct` | yes, universe, 0.9-2build2 | no | no |
| `qt6-style-kvantum` | not found via `apt-cache policy`/`search` (no candidate on this machine) | no | no |
| `adwaita-qt6` | yes, universe, 1.4.2-3build4 | no | no (this only themes qt6ct's own style engine, not a platformtheme plugin) |

Decisive fact: `libqgtk3.so` (the Qt6 gtk3 platformtheme plugin) is **already
on disk**, shipped by the already-installed `qt6-gtk-platformtheme` package.
No install is needed — this is a pure env-var fix.

## Where `qt5ct` is set

`/etc/X11/Xsession.d/99qt5ct:3-5`:
```
if [ -z "$QT_QPA_PLATFORMTHEME" ] && [ "$XDG_CURRENT_DESKTOP" != "KDE" ]
then
        export QT_QPA_PLATFORMTHEME=qt5ct
```
This is an X11 session-startup script (distro-shipped, part of the qt5ct
package's Xsession integration), sourced at login for all X11 sessions except
KDE. It guards with `-z`, so anything that already exports
`QT_QPA_PLATFORMTHEME` before this script runs wins — this makes a
per-app/per-user override safe without touching the file.

## Recommended recipe — (a) set `QT_QPA_PLATFORMTHEME=gtk3`

No install required: the gtk3 platformtheme plugin is already present via
`qt6-gtk-platformtheme`. Just override the env var, either globally (picked
up by Qt6 apps; Qt5 apps still get qt5ct because the Xsession script's `-z`
guard only fires when nothing already set it — but if you export a fixed
value in `~/.profile`, it runs before/instead and Qt5 apps would also see
`gtk3`, which usually still renders fine via qt5's own gtk3 plugin) or scoped
to just TuParles:

```bash
# run these yourself, needs sudo only if you want it system-wide via /etc/environment;
# no sudo needed for the per-user or per-app options below

# Option 1 — scoped to TuParles only (safest, no risk to other apps):
QT_QPA_PLATFORMTHEME=gtk3 poetry run tuparles

# Option 2 — per-user, all apps, only for new sessions (edit your own shell rc):
echo 'export QT_QPA_PLATFORMTHEME=gtk3' >> ~/.zshenv

# Option 3 (not recommended today) — install qt6ct for finer per-app control later:
sudo apt install qt6ct
# then set QT_QPA_PLATFORMTHEME=qt6ct and configure via `qt6ct` GUI
```

Do NOT edit `/etc/X11/Xsession.d/99qt5ct` — it's a distro-owned file and
already yields to any pre-set value.

## Risks

- `QT_QPA_PLATFORMTHEME` is a global env var: setting it in `~/.zshenv` or
  `/etc/environment` affects every Qt5 *and* Qt6 app you run, not just
  TuParles. Qt5 apps that currently theme via qt5ct would instead try `gtk3`
  — likely fine (gtk3 plugin exists for Qt5 too) but not verified here.
- Safest rollout: scope the var to the TuParles launch command/desktop entry
  first, confirm the look, then decide whether to widen it.
- `qt6-style-kvantum` has no candidate in this machine's configured repos —
  don't chase it; gtk3 already solves the immediate problem.

## Correction (applied 2026-09-09): the right file is `~/.xsessionrc`, not `~/.zshenv`

`~/.zshenv` only reaches processes started by a zsh shell. TuParles is launched
by gnome-shell from `~/.local/share/applications/tuparles.desktop`, so it never
sources a zsh rc and the export would have had no effect on the app it was
meant to fix.

The right hook is `~/.xsessionrc`, because of ordering:

| Xsession.d script | priority | what it does |
|---|---|---|
| `40x11-common_xsessionrc` | 40 | sources `~/.xsessionrc` |
| `99qt5ct` | 99 | `export QT_QPA_PLATFORMTHEME=qt5ct` **if unset** |

Exporting at priority 40 means the `-z` guard at 99 finds the variable already
set and stands down, so `gtk3` wins for the whole session — every GUI app, and
terminals too, since they inherit from the session. No file needs editing.

Applied:

```sh
# ~/.xsessionrc
export QT_QPA_PLATFORMTHEME=gtk3
```

Takes effect at the next login. For the session already running,
`systemctl --user set-environment QT_QPA_PLATFORMTHEME=gtk3` covers anything
systemd launches from then on — but *not* apps launched by gnome-shell, which
inherit gnome-shell's own login-time environment. Verified after the change:
`QApplication` reports window colour `#2a2a2a` (the Adwaita dark palette)
where it previously had none, and the style stays Fusion — correct, since a
platform theme supplies the palette, not the style.

**On Wayland this would be the wrong file too**: Xsession.d is not consulted,
and the equivalent is `~/.config/environment.d/*.conf`. This box is
`XDG_SESSION_TYPE=x11`, so `~/.xsessionrc` is right here.
