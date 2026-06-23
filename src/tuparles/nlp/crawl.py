"""Discover the source files worth mining for vocabulary.

We mine *git-tracked* files only. That respects `.gitignore` for free -- no
`node_modules`, no `.venv`, no build artefacts -- and scopes us to "the project
as committed", which is what a developer actually talks about.

On top of that we drop non-prose noise (generated fixtures, logs, binaries) so
a repo full of `.cmd`/`.res`/`.log` test vectors (hello, AlgoliaSaaS) doesn't
drown the real symbols. Every dropped file is *counted*, never silently
swallowed -- the EDA reports the filter's footprint.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Kind(str, Enum):
    PYTHON = "python"
    MARKDOWN = "markdown"
    MANIFEST = "manifest"  # pyproject / package.json / requirements -- dep names
    CODE = "code"  # other source: cpp / h / js / ts / go / rs ...
    DATA = "data"  # json / yaml / txt that isn't a manifest -- skipped for v1
    NOISE = "noise"  # generated / log / binary -- skipped


MINEABLE = frozenset({Kind.PYTHON, Kind.MARKDOWN, Kind.MANIFEST, Kind.CODE})

_CODE_EXT = {
    ".cpp",
    ".cc",
    ".cxx",
    ".c",
    ".h",
    ".hpp",
    ".hxx",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".swift",
    ".scala",
    ".sh",
}
_MD_EXT = {".md", ".mdx", ".markdown", ".rst"}
_DATA_EXT = {".json", ".yml", ".yaml", ".txt", ".toml", ".cfg", ".ini", ".csv", ".xml"}
_MANIFEST_NAMES = {
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    "go.mod",
    "cargo.toml",
}

# Files bigger than this are almost always generated/data, not hand-written
# vocabulary. Skip them whatever the extension.
_MAX_BYTES = 1_000_000


@dataclass(frozen=True)
class SourceFile:
    repo: str
    relpath: str
    abspath: Path
    kind: Kind
    size: int


def classify(relpath: str) -> Kind:
    p = Path(relpath)
    name = p.name.lower()
    if name in _MANIFEST_NAMES:
        return Kind.MANIFEST
    ext = p.suffix.lower()
    if ext == ".py":
        return Kind.PYTHON
    if ext in _MD_EXT:
        return Kind.MARKDOWN
    if ext in _CODE_EXT:
        return Kind.CODE
    if ext in _DATA_EXT:
        return Kind.DATA
    return Kind.NOISE


def _git_tracked(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def discover(repos: dict[str, Path]) -> list[SourceFile]:
    """All git-tracked files across `repos`, classified.

    Returns every file (including NOISE/DATA) so the EDA can quantify what the
    filter removed; callers mine only those whose `kind in MINEABLE`.
    """
    files: list[SourceFile] = []
    for name, root in repos.items():
        root = Path(root).expanduser().resolve()
        for rel in _git_tracked(root):
            ab = root / rel
            try:
                size = ab.stat().st_size
            except OSError:
                continue
            kind = classify(rel)
            if kind in MINEABLE and size > _MAX_BYTES:
                kind = Kind.NOISE  # too big to be hand-written vocab
            files.append(SourceFile(name, rel, ab, kind, size))
    return files


def read_text(sf: SourceFile) -> str | None:
    """Best-effort UTF-8 read; None on binary/unreadable (counts as a skip)."""
    try:
        return sf.abspath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
