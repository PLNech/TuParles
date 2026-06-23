"""Where a corpus comes from -- the modular seam.

The engine doesn't care whether vocabulary arrives from a git repo, a folder of
transcripts, or our dictation history DB. Everything becomes a `Document`: an
id, a source label, and a stream of typed terms. Add a new adapter (a Slack
export, a meeting transcript, a logfile) and the whole features -> signals ->
engines stack works on it unchanged. That generality is the point: dict-seeding
is one application; keyword/tag-cloud/clustering of chat history is another.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from tuparles.nlp.crawl import MINEABLE, discover, read_text
from tuparles.nlp.parse import SrcType, parse_file, parse_text


@dataclass
class Document:
    """One unit of corpus text, already typed into (term, SrcType) pairs."""

    doc_id: str
    source: str
    terms: Iterable[tuple[str, SrcType]]


@dataclass
class DiscoveryStats:
    """What the crawl saw -- so the EDA can report the filter's footprint."""

    n_files: int = 0
    mineable: int = 0
    skipped: Counter = field(default_factory=Counter)  # reason -> count
    by_kind: Counter = field(default_factory=Counter)  # kind -> mineable count


def code_documents(repos: dict[str, Path]) -> tuple[list[Document], DiscoveryStats]:
    """Git-tracked source across `repos` -> one Document per mineable file."""
    files = discover(repos)
    docs: list[Document] = []
    stats = DiscoveryStats(n_files=len(files))
    for sf in files:
        if sf.kind not in MINEABLE:
            stats.skipped[sf.kind.value] += 1
            continue
        text = read_text(sf)
        if text is None:
            stats.skipped["unreadable"] += 1
            continue
        stats.mineable += 1
        stats.by_kind[sf.kind.value] += 1
        docs.append(
            Document(f"{sf.repo}/{sf.relpath}", sf.repo, list(parse_file(sf, text)))
        )
    return docs, stats


def text_documents(
    paths: Iterable[str | Path], source: str = "text"
) -> Iterator[Document]:
    """A folder of prose (transcripts, logs, notes) -- each file one document.

    The proof that the engine is not code-only: plain text flows through the
    same pipeline as ASTs, just weighted as TEXT.
    """
    for p in paths:
        p = Path(p)
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield Document(str(p), source, list(parse_text(text)))


def message_documents(
    messages: Iterable[tuple[object, str]], source: str = "chat"
) -> Iterator[Document]:
    """In-memory (id, text) pairs -- our dictation history DB, a chat export, a
    meeting transcript -- without the engine knowing the schema."""
    for i, (mid, text) in enumerate(messages):
        yield Document(
            str(mid if mid is not None else i), source, list(parse_text(text))
        )
