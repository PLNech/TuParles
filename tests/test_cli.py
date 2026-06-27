"""CLI smoke tests — just enough to pin that a command wires up and prints
something sane. `diag` (#29) is the cross-env diagnostic users paste into bugs."""

from tuparles import cli


def test_diag_prints_capability_and_environment(capsys):
    cli._diag()
    out = capsys.readouterr().out
    assert "capabilities:" in out  # the one-line report (verbose header)
    assert "### Environnement" in out  # the bug-report block follows
    assert "Capacités :" in out  # capability line rides inside the env block
