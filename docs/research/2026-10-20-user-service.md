# TuParles as a systemd user service (#48)

## Why

Until now the daemon started from the app launcher, or from a terminal with
`poetry run tuparles`. That works, but nothing brings it back after a crash,
and nothing starts it at login unless you remember to. A systemd *user* unit
covers both and adds journald logging. `journalctl --user -t tuparles`, which
`docs/CROSS_ENV.md` already recommends, now always works.

## What ships

- `packaging/tuparles.service.in`, a template with one placeholder (`@EXEC@`),
  the same shape as `tuparles.desktop.in`.
- `tuparles service install|uninstall|status|logs` (`service.py`). It is a
  subcommand rather than a shell script because the argparse tree already had
  room, and Python makes the no-clobber logic testable. Every `systemctl` call
  goes through an injected runner, so the tests pin the exact argv without
  systemd being present.

The launcher is resolved the way `install_desktop.sh` resolves it:
`<venv>/bin/tuparles`. The running interpreter's own `bin/` comes first. It is
the poetry env, so no `poetry env info` call is needed. Then the repo-root
`.venv`, then `tuparles` on PATH, and `--exec` overrides all three. Symlinks
are not resolved: a venv's `bin/` only means something unresolved. Paths
containing `%`, `$`, quotes or backslashes are refused. systemd would
reinterpret those characters, and refusing them is safer than escaping them
half-right.

## Why graphical-session.target, not default.target

TuParles is not a headless service. The tray (D-Bus StatusNotifierItem), the
bubble (Qt over X11 or XWayland), the X11 hotkey and the clipboard all need
the logged-in graphical session. `default.target` is reached before the
compositor exists, so a unit wanted by it would race the display and lose.
`After=` + `PartOf=` + `WantedBy=graphical-session.target` is the systemd
idiom for session-bound apps. The unit starts after the session is up, stops
when it ends (logout), and is pulled in again at the next login. That gives
"survives logout/login" without lingering.

## Environment: what the session must hand over

A user service inherits the **user manager's** environment, not the
compositor's. What the daemon reads:

| Variable | Used for |
|---|---|
| `DISPLAY`, `XAUTHORITY` | Qt `xcb` (also on Wayland: the bubble renders via XWayland), xdotool/xprop |
| `WAYLAND_DISPLAY` | wl-copy / wl-paste |
| `XDG_SESSION_TYPE` | `config.IS_WAYLAND`, which picks evdev+ydotool or pynput+xdotool |
| `XDG_RUNTIME_DIR` | single-instance lock, ydotool socket (set by systemd itself) |
| `DBUS_SESSION_BUS_ADDRESS` | tray, notifications (set by systemd with dbus-user-session) |
| `YDOTOOL_SOCKET` | modern ydotool only; `setup_wayland.sh` writes it to `environment.d`, which the user manager reads |

On this box (Ubuntu, GNOME on Wayland, systemd 255), `systemctl --user
show-environment` already lists every variable above except `YDOTOOL_SOCKET`.
That is expected here, because Ubuntu's ydotool 0.1.8 has no daemon.
gnome-session imports them at login, and KDE Plasma does the same. Nothing is
hardcoded in the unit: baking in `DISPLAY=:0` would be wrong on the next box,
and XWayland's `XAUTHORITY` is a random path per login.

The gotchas:

- **Bare X11 sessions** (`~/.xsession`, `startx`, some tiling WMs) may neither
  import the variables nor start `graphical-session.target`. The fix is to add
  `systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY
  XDG_SESSION_TYPE` and then `systemctl --user start tuparles` to the session
  start-up script. The unit carries a one-line `ExecStartPre=` guard. With no
  `DISPLAY` and no `WAYLAND_DISPLAY`, it fails with a journal line naming that
  command, instead of Qt aborting with "could not connect to display". `$$`
  in the guard is systemd's escape for a literal `$`, so the shell expands
  the variables, not systemd.
- **A missing `XDG_SESSION_TYPE` on Wayland** would quietly select the X11
  backends under XWayland. The hotkey would then only fire while an XWayland
  window has focus. GNOME exports the variable, so the unit doesn't guard
  against this; it is documented here in case another compositor skips it.
- **Group membership is per manager start.** `setup_wayland.sh` adds you to
  `input` for the evdev hotkey. `user@UID.service` keeps the groups it started
  with for as long as *any* session of yours exists, so one full logout of all
  sessions (or a reboot) is needed before the service can read
  `/dev/input`.
- **`environment.d`** changes, like `QT_QPA_PLATFORMTHEME` or `YDOTOOL_SOCKET`,
  reach the service at the next login, not before. Same rule as anything else
  systemd launches.

No sandboxing directives (`PrivateTmp`, `ProtectHome`, `PrivateDevices`...).
Each one would break something real: the ydotool socket, `/dev/uinput` and
`/dev/input`, the vocab file and models under the repo, or the clipboard
helpers.

## Restart and resource policy

- `Restart=on-failure`, `RestartSec=5`, `StartLimitBurst=5` in
  `StartLimitIntervalSec=120`. A crash loop gives up after about 25 s of
  attempts instead of spinning. Tray « Quitter » exits 0, so quitting stays
  quit until the next login. The single-instance guard also exits 0 ("TuParles
  tourne déjà"), so a launcher copy and the service never fight or loop. The
  daemon's in-place `execv` restart keeps the PID, so systemd doesn't see a
  restart.
- `Nice=5`, `CPUWeight=50` (default 100). On battery the decode runs on CPU,
  and a dictation daemon should give way to the foreground app under
  contention. Both are mild: without contention, a take decodes at full speed.
- `Environment=PYTHONUNBUFFERED=1` on top of the daemon's own line-buffered
  stdout, so output printed before `run()` reconfigures stdout still reaches
  the journal in order.

## Battery

The unit is the normal daemon and sets nothing about the engine: no
`CUDA_VISIBLE_DEVICES`, no settings override. `battery_aware` (default on) and
`prefer_cpu` decide exactly as for a launcher start (see
`2026-10-20-power-aware-engine.md`). On battery that means CPU decode with no
GPU touch, which is #48's acceptance criterion, met by construction.

## Why install-only by default

`tuparles service install` writes the file and runs `daemon-reload`. Nothing
else. Starting the service takes the microphone and a global hotkey on a live
session. That should be a deliberate act (`--now`, or `--enable` for "from the
next login"), never a side effect of re-running an installer. Same logic as
the no-clobber rule: an existing unit that differs is left alone, the fresh
render goes to `tuparles.service.new`, and the command exits 1 so a script
notices. `uninstall` removes the file only while it is byte-identical to the
current render. A hand-edited unit is disabled but kept.

## What was verified, and what was not

Verified:

- The rendered unit (exec = repo `.venv/bin/tuparles`) passes
  `systemd-analyze --user verify` with exit 0. Its only output was warnings
  about unrelated units already in `~/.config/systemd/user`.
- The unit tests: template contract, rendering, no-clobber, idempotence,
  uninstall safety, exact `systemctl`/`journalctl` argv, CLI wiring. No
  systemd needed.

**Not verified.** The service was never enabled or started on the dev box,
because it would grab the owner's microphone and hotkey on a live session.
Still open:

- That the daemon actually comes up under the unit on GNOME/Wayland: tray
  visible, bubble placed, evdev hotkey and ydotool paste working with the
  inherited environment.
- Logout/login survival in practice, and that `PartOf=` stops it cleanly
  without leaving a stale lock. The lock is an flock, so it dies with the
  process. It should be fine, but nobody watched it happen.
- An X11 session, a KDE session, and a bare `~/.xsession`.
- The restart policy on a real crash, and the start-limit give-up.
- That `Nice`/`CPUWeight` don't noticeably slow a CPU take on battery.
