"""`tuparles service` — run the daemon as a systemd *user* service (#48).

Renders `packaging/tuparles.service.in` into the user unit directory and hands
the rest to `systemctl --user`. Install-only by default: the daemon grabs the
microphone and a global hotkey, so starting it is always an explicit
`--enable` / `--now`, never a side effect of installing.

Non-destructive by construction: an existing unit that differs from the fresh
render is never overwritten (the render lands beside it as `.new`), and
uninstall deletes the file only while it is still byte-identical to what we
would render — a hand-edited unit survives both.

Every external command goes through an injectable `run(argv) -> returncode`,
so the tests pin the exact `systemctl` argv without a systemd on the box.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

UNIT_NAME = "tuparles.service"
PLACEHOLDER = "@EXEC@"

Runner = Callable[[Sequence[str]], int]
Printer = Callable[[str], None]


def _run(argv: Sequence[str]) -> int:
    try:
        return subprocess.run(list(argv), check=False).returncode
    except FileNotFoundError:
        print(f"Introuvable : {argv[0]} — systemd absent ?", file=sys.stderr)
        return 127


def template_path() -> Path:
    from tuparles.config import REPO_ROOT

    return REPO_ROOT / "packaging" / "tuparles.service.in"


def unit_dir(env: dict[str, str] | None = None) -> Path:
    """Where systemd looks for user units: `$XDG_CONFIG_HOME/systemd/user`."""
    env = dict(os.environ) if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def resolve_exec(override: str | None = None) -> Path:
    """The launcher the unit runs — same answer as the desktop entry.

    `install_desktop.sh` takes `<poetry env>/bin/tuparles`; here the running
    interpreter's own bin/ is that env (no poetry call needed), then the
    repo-root `.venv`, then whatever `tuparles` is on PATH. `--exec` overrides.
    Symlinks are kept as-is: a venv's bin/ only means something unresolved.
    """
    from tuparles.config import REPO_ROOT

    if override:
        candidates = [Path(override).expanduser().absolute()]
    else:
        on_path = shutil.which("tuparles")
        candidates = [
            Path(sys.executable).parent / "tuparles",
            REPO_ROOT / ".venv" / "bin" / "tuparles",
            *([Path(on_path).absolute()] if on_path else []),
        ]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    tried = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(
        f"lanceur tuparles introuvable ({tried}) — `poetry install` d'abord, "
        "ou --exec /chemin/vers/tuparles"
    )


def render(template: str, exec_path: Path) -> str:
    """Fill the ExecStart placeholder. Refuses characters systemd would
    reinterpret in a command line (`%` specifiers, `$` variables, quotes,
    backslashes, newlines) rather than escaping them half-right; a path with
    spaces is quoted."""
    text = str(exec_path)
    if not exec_path.is_absolute():
        raise ValueError(f"ExecStart doit être un chemin absolu : {text}")
    bad = set(text) & set("%$\"'\\\n")
    if bad:
        raise ValueError(f"caractère non pris en charge dans {text!r} : {sorted(bad)}")
    if PLACEHOLDER not in template:
        raise ValueError(f"gabarit sans {PLACEHOLDER}")
    value = f'"{text}"' if any(c.isspace() for c in text) else text
    return template.replace(PLACEHOLDER, value)


@dataclass(frozen=True)
class WriteResult:
    status: str  # "installed" | "unchanged" | "conflict"
    path: Path  # the file written (or left alone when unchanged)


def write_unit(text: str, directory: Path) -> WriteResult:
    """Write the rendered unit, never clobbering a different existing one."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / UNIT_NAME
    if target.exists():
        if target.read_text(encoding="utf-8") == text:
            return WriteResult("unchanged", target)
        proposal = directory / f"{UNIT_NAME}.new"
        proposal.write_text(text, encoding="utf-8")
        return WriteResult("conflict", proposal)
    target.write_text(text, encoding="utf-8")
    return WriteResult("installed", target)


def systemctl(*args: str) -> list[str]:
    return ["systemctl", "--user", *args]


def enable_argv(now: bool) -> list[str]:
    return systemctl("enable", *(["--now"] if now else []), UNIT_NAME)


def install(
    *,
    enable: bool = False,
    now: bool = False,
    exec_path: str | None = None,
    run: Runner = _run,
    directory: Path | None = None,
    template: str | None = None,
    out: Printer = print,
) -> int:
    directory = unit_dir() if directory is None else directory
    try:
        launcher = resolve_exec(exec_path)
        text = render(
            template_path().read_text(encoding="utf-8")
            if template is None
            else template,
            launcher,
        )
    except (FileNotFoundError, ValueError) as exc:
        out(f"Erreur : {exc}")
        return 1

    result = write_unit(text, directory)
    if result.status == "conflict":
        current = directory / UNIT_NAME
        out(f"{current} existe et diffère — laissé intact.")
        out(f"Nouvelle version écrite à côté : {result.path}")
        out(f"Compare (diff {current} {result.path}), puis renomme-la si elle te va.")
        return 1
    if result.status == "installed":
        out(f"Installé : {result.path} → {launcher}")
        rc = run(systemctl("daemon-reload"))
        if rc != 0:
            return rc
    else:
        out(f"Déjà à jour : {result.path}")

    if enable or now:
        return run(enable_argv(now))
    out("Rien n'est démarré. Pour l'activer :")
    out("  tuparles service install --now   # démarre maintenant + à chaque session")
    out("  tuparles service install --enable  # à partir de la prochaine session")
    return 0


def uninstall(
    *,
    exec_path: str | None = None,
    run: Runner = _run,
    directory: Path | None = None,
    template: str | None = None,
    out: Printer = print,
) -> int:
    directory = unit_dir() if directory is None else directory
    target = directory / UNIT_NAME
    if not target.exists():
        out(f"Pas de service installé ({target}).")
        return 0
    run(systemctl("disable", "--now", UNIT_NAME))  # already-disabled is fine

    try:
        expected: str | None = render(
            template_path().read_text(encoding="utf-8")
            if template is None
            else template,
            resolve_exec(exec_path),
        )
    except (FileNotFoundError, ValueError):
        expected = None
    if expected is not None and target.read_text(encoding="utf-8") == expected:
        target.unlink()
        out(f"Désactivé et supprimé : {target}")
        rc = run(systemctl("daemon-reload"))
    else:
        out(f"Désactivé. {target} a été modifié à la main — laissé en place.")
        rc = 0
    proposal = directory / f"{UNIT_NAME}.new"
    if proposal.exists():
        out(f"(une proposition reste là : {proposal})")
    return rc


def status(*, run: Runner = _run) -> int:
    return run(systemctl("status", "--no-pager", UNIT_NAME))


def logs_argv() -> list[str]:
    return ["journalctl", "--user", "-u", UNIT_NAME, "-n", "50", "-f"]


def logs(*, run: Runner = _run) -> int:
    return run(logs_argv())
