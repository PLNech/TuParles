"""`tuparles service` (#48): the systemd user unit, rendered and installed
without a systemd on the box. Every systemctl call goes through an injected
runner, so these pin the exact argv and prove nothing is started by default."""

import os
import sys
from pathlib import Path

import pytest

from tuparles import cli, service

TEMPLATE = service.template_path().read_text(encoding="utf-8")


@pytest.fixture
def launcher(tmp_path) -> Path:
    exe = tmp_path / "venv" / "bin" / "tuparles"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


class Recorder:
    def __init__(self, rc: int = 0):
        self.calls: list[list[str]] = []
        self.rc = rc

    def __call__(self, argv):
        self.calls.append(list(argv))
        return self.rc


def _lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines()}


# --- the template ------------------------------------------------------------


def test_template_ships_the_unit_contract():
    lines = _lines(TEMPLATE)
    for want in (
        "Type=simple",
        "ExecStart=@EXEC@",
        "After=graphical-session.target",
        "PartOf=graphical-session.target",
        "WantedBy=graphical-session.target",
        "Restart=on-failure",
        "SyslogIdentifier=tuparles",
        "StandardOutput=journal",
        "StandardError=journal",
    ):
        assert want in lines, want
    assert any(line.startswith("StartLimitBurst=") for line in lines)
    assert any(line.startswith("StartLimitIntervalSec=") for line in lines)
    nice = next(line for line in lines if line.startswith("Nice="))
    assert int(nice.split("=")[1]) > 0


def test_template_never_sandboxes_nor_picks_the_engine():
    # Sandboxing breaks the clipboard / ydotool socket / input devices; the
    # engine choice belongs to battery_aware / prefer_cpu, not the unit.
    for forbidden in (
        "PrivateTmp",
        "ProtectHome",
        "ProtectSystem",
        "PrivateDevices",
        "DynamicUser",
        "CUDA_VISIBLE_DEVICES",
        "battery_aware",
        "prefer_cpu",
        "DISPLAY=",
        "WAYLAND_DISPLAY=",
        "XAUTHORITY=",
    ):
        body = [ln for ln in TEMPLATE.splitlines() if not ln.lstrip().startswith("#")]
        assert not any(forbidden in ln for ln in body), forbidden


# --- rendering ---------------------------------------------------------------


def test_render_fills_exec_start(launcher):
    text = service.render(TEMPLATE, launcher)
    assert f"ExecStart={launcher}" in _lines(text)
    assert service.PLACEHOLDER not in text


def test_render_quotes_a_path_with_spaces(tmp_path):
    text = service.render(TEMPLATE, tmp_path / "my apps" / "tuparles")
    assert f'ExecStart="{tmp_path}/my apps/tuparles"' in _lines(text)


@pytest.mark.parametrize("bad", ["/opt/50%/tuparles", "/opt/$HOME/tuparles"])
def test_render_refuses_systemd_metacharacters(bad):
    with pytest.raises(ValueError):
        service.render(TEMPLATE, Path(bad))


def test_render_refuses_relative_path():
    with pytest.raises(ValueError):
        service.render(TEMPLATE, Path("bin/tuparles"))


def test_resolve_exec_prefers_the_running_venv(launcher, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(launcher.parent / "python"))
    assert service.resolve_exec() == launcher


def test_resolve_exec_override_and_missing(launcher, tmp_path):
    assert service.resolve_exec(str(launcher)) == launcher
    with pytest.raises(FileNotFoundError):
        service.resolve_exec(str(tmp_path / "nope"))


def test_unit_dir_follows_xdg_config_home(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    assert service.unit_dir(env) == tmp_path / "cfg" / "systemd" / "user"


# --- install: idempotent, never clobbers, never starts by default ------------


def test_install_default_writes_and_reloads_only(launcher):
    run = Recorder()
    rc = service.install(exec_path=str(launcher), run=run, out=lambda _s: None)
    unit = service.unit_dir() / "tuparles.service"  # tmp XDG_CONFIG_HOME (conftest)
    assert rc == 0
    assert str(unit).startswith(os.environ["XDG_CONFIG_HOME"])
    assert f"ExecStart={launcher}" in _lines(unit.read_text())
    assert run.calls == [["systemctl", "--user", "daemon-reload"]]


def test_install_twice_is_a_no_op(launcher):
    service.install(exec_path=str(launcher), run=Recorder(), out=lambda _s: None)
    run = Recorder()
    assert service.install(exec_path=str(launcher), run=run, out=lambda _s: None) == 0
    assert run.calls == []  # unchanged file: no reload, nothing started
    assert not (service.unit_dir() / "tuparles.service.new").exists()


def test_install_never_overwrites_a_different_unit(launcher):
    unit_dir = service.unit_dir()
    unit_dir.mkdir(parents=True)
    unit = unit_dir / "tuparles.service"
    unit.write_text("[Service]\nExecStart=/my/own/tuparles\n")
    run = Recorder()
    said: list[str] = []
    rc = service.install(exec_path=str(launcher), run=run, out=said.append, now=True)
    assert rc == 1
    assert unit.read_text() == "[Service]\nExecStart=/my/own/tuparles\n"
    proposal = unit_dir / "tuparles.service.new"
    assert f"ExecStart={launcher}" in _lines(proposal.read_text())
    assert run.calls == []  # a conflict reloads and enables nothing
    assert any(".new" in line for line in said)


@pytest.mark.parametrize(
    ("flags", "last"),
    [
        ({"enable": True}, ["systemctl", "--user", "enable", "tuparles.service"]),
        (
            {"now": True},
            ["systemctl", "--user", "enable", "--now", "tuparles.service"],
        ),
        (
            {"enable": True, "now": True},
            ["systemctl", "--user", "enable", "--now", "tuparles.service"],
        ),
    ],
)
def test_install_enable_flags_build_exact_argv(launcher, flags, last):
    run = Recorder()
    service.install(exec_path=str(launcher), run=run, out=lambda _s: None, **flags)
    assert run.calls == [["systemctl", "--user", "daemon-reload"], last]


def test_install_stops_when_reload_fails(launcher):
    run = Recorder(rc=1)
    rc = service.install(
        exec_path=str(launcher), run=run, out=lambda _s: None, now=True
    )
    assert rc == 1
    assert run.calls == [["systemctl", "--user", "daemon-reload"]]


def test_install_without_a_launcher_writes_nothing(tmp_path):
    run = Recorder()
    rc = service.install(exec_path=str(tmp_path / "nope"), run=run, out=lambda _s: None)
    assert rc == 1
    assert run.calls == []
    assert not (service.unit_dir() / "tuparles.service").exists()


# --- uninstall: only removes what is still ours ------------------------------


def test_uninstall_removes_our_own_unit(launcher):
    service.install(exec_path=str(launcher), run=Recorder(), out=lambda _s: None)
    run = Recorder()
    assert service.uninstall(exec_path=str(launcher), run=run, out=lambda _s: None) == 0
    assert not (service.unit_dir() / "tuparles.service").exists()
    assert run.calls == [
        ["systemctl", "--user", "disable", "--now", "tuparles.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_uninstall_keeps_a_hand_edited_unit(launcher):
    service.install(exec_path=str(launcher), run=Recorder(), out=lambda _s: None)
    unit = service.unit_dir() / "tuparles.service"
    unit.write_text(unit.read_text() + "\n# mine\n")
    run = Recorder()
    service.uninstall(exec_path=str(launcher), run=run, out=lambda _s: None)
    assert unit.exists()
    assert run.calls == [
        ["systemctl", "--user", "disable", "--now", "tuparles.service"]
    ]


def test_uninstall_when_absent_touches_nothing(launcher):
    run = Recorder()
    assert service.uninstall(exec_path=str(launcher), run=run, out=lambda _s: None) == 0
    assert run.calls == []


def test_status_and_logs_argv():
    run = Recorder()
    service.status(run=run)
    service.logs(run=run)
    assert run.calls == [
        ["systemctl", "--user", "status", "--no-pager", "tuparles.service"],
        ["journalctl", "--user", "-u", "tuparles.service", "-n", "50", "-f"],
    ]


# --- the CLI wiring ----------------------------------------------------------


def test_cli_service_help_lists_actions(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tuparles", "service", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for word in ("install", "uninstall", "status", "logs", "--enable", "--now"):
        assert word in out


def test_cli_service_install_passes_flags(monkeypatch):
    seen: dict = {}

    def fake_install(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(service, "install", fake_install)
    monkeypatch.setattr(
        sys,
        "argv",
        ["tuparles", "service", "install", "--now", "--exec", "/x/tuparles"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert seen == {"enable": False, "now": True, "exec_path": "/x/tuparles"}


def test_cli_service_rejects_unknown_action(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["tuparles", "service", "start"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
