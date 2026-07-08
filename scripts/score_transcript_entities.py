#!/usr/bin/env python3
"""Redacted entity scorer for transcript QA.

Counts, per transcript file, how often each canonical entity appears in its
**correct** form versus each **known-wrong** variant. Built for a real-meeting
A/B, QA report 2026-07-08 (local): does seeding vocab.txt + a stronger engine
actually move the right form's odds up and the mangles down?

PRIVACY, BY DESIGN: this tool reads transcript text but **emits only aggregate
counts** — never a transcript line, never the surrounding context of a match.
The input files may be private; the output is safe to paste. The built-in spec
names only public tech brands; meeting-specific entities (company names, app
IDs) belong in a local `--spec` file that never enters the repo.

Matching:
  * Word-boundary, unicode-aware. A variant matches only when not flanked by
    another word character, so "Doctolib" never fires inside "doctolibre" and
    a truncated ID never fires inside the full one.
  * Multi-word / hyphenated forms ("Data Dog", "en tropique", "K-8") match
    across either a space or a hyphen.
  * Case-insensitive by default. Where *case itself is the error* — "OPUZ" (an
    all-caps mangle of "Opus") — the form is matched case-sensitively so the
    two don't collapse into one count.

Usage:
    poetry run python scripts/score_transcript_entities.py FILE [FILE ...]
    poetry run python scripts/score_transcript_entities.py --json FILE ...
    poetry run python scripts/score_transcript_entities.py --spec my.json FILE

`--spec PATH` loads a JSON list of entities that REPLACES the built-in spec:
    [{"name": "...", "correct": [{"form": "...", "case_sensitive": false}],
      "wrong": [{"form": "..."}]}, ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Variant:
    """A surface form to count. `case_sensitive` when case IS the error."""

    form: str
    case_sensitive: bool = False


@dataclass
class Entity:
    """A canonical entity: its accepted correct form(s) + known-wrong mangles."""

    name: str
    correct: list[Variant]
    wrong: list[Variant] = field(default_factory=list)


# --- The default spec, derived from the QA report §1(b)/(c) and §4.3 ---------
# Each entry: canonical entity → (correct forms, known-wrong variants). Correct
# forms include accent/plural aliases the report treats as correct (Némotron,
# queries). Wrong variants are the exact mangles the report catalogued.
# Generic tech brands only — meeting-specific entities go in a --spec file.
ENTITY_SPEC: list[Entity] = [
    Entity("Algolia", correct=[Variant("Algolia")]),
    Entity(
        "Opus",
        correct=[Variant("Opus")],
        wrong=[Variant("OPUZ", case_sensitive=True), Variant("K-8")],
    ),
    Entity("Haiku", correct=[Variant("Haiku")], wrong=[Variant("Aiku")]),
    Entity("Gemini", correct=[Variant("Gemini")], wrong=[Variant("Gmini")]),
    Entity("Gemma", correct=[Variant("Gemma")], wrong=[Variant("GEMA")]),
    Entity("DeepSeek", correct=[Variant("DeepSeek")], wrong=[Variant("Dipsy")]),
    Entity("n8n", correct=[Variant("n8n")], wrong=[Variant("N8AIN")]),
    Entity(
        "Anthropic",
        correct=[Variant("Anthropic")],
        wrong=[Variant("Anthropy"), Variant("en tropique")],
    ),
    Entity("Claude", correct=[Variant("Claude")]),
    Entity("Datadog", correct=[Variant("Datadog")], wrong=[Variant("Data Dog")]),
    Entity("PostHog", correct=[Variant("PostHog")]),
    Entity(
        "Nemotron",
        correct=[Variant("Nemotron"), Variant("Némotron")],
        wrong=[Variant("motrons")],
    ),
    Entity("Doctolib", correct=[Variant("Doctolib")], wrong=[Variant("doctolibre")]),
    Entity(
        "query",
        correct=[Variant("query"), Variant("queries")],
        wrong=[Variant("quarry"), Variant("quéris")],
    ),
]


def _variant_from_json(obj: dict) -> Variant:
    return Variant(form=obj["form"], case_sensitive=bool(obj.get("case_sensitive")))


def load_spec(path: Path) -> list[Entity]:
    """Load a JSON entity spec (a list of {name, correct, wrong} objects).

    The loaded spec REPLACES the built-in default — it is the mechanism for
    meeting-specific entities that must stay out of the repo.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: spec must be a JSON list of entities")
    spec = []
    for obj in raw:
        spec.append(
            Entity(
                name=obj["name"],
                correct=[_variant_from_json(v) for v in obj["correct"]],
                wrong=[_variant_from_json(v) for v in obj.get("wrong", [])],
            )
        )
    return spec


def compile_variant(form: str, case_sensitive: bool) -> re.Pattern[str]:
    """A boundary-anchored, separator-flexible, unicode pattern for one form.

    Word runs are joined by ``[\\s-]+`` so "Data Dog" also matches "Data-Dog";
    lookarounds forbid an adjacent word char so a form never matches as a
    substring of a longer token.
    """
    parts = [p for p in re.split(r"[\s\-]+", form.strip()) if p]
    body = r"[\s\-]+".join(re.escape(p) for p in parts)
    pattern = r"(?<!\w)" + body + r"(?!\w)"
    flags = re.UNICODE if case_sensitive else re.UNICODE | re.IGNORECASE
    return re.compile(pattern, flags)


def count_variant(text: str, variant: Variant) -> int:
    return len(compile_variant(variant.form, variant.case_sensitive).findall(text))


def score_text(text: str, spec: list[Entity] = ENTITY_SPEC) -> dict:
    """Count correct/wrong occurrences of every entity in `text`. Counts only."""
    text = unicodedata.normalize("NFC", text)
    out: dict[str, dict] = {}
    for ent in spec:
        correct_n = sum(count_variant(text, v) for v in ent.correct)
        wrong = {v.form: count_variant(text, v) for v in ent.wrong}
        out[ent.name] = {
            "correct": correct_n,
            "wrong": wrong,
            "wrong_total": sum(wrong.values()),
        }
    return out


def score_file(path: Path, spec: list[Entity] = ENTITY_SPEC) -> dict:
    """Read a transcript file and score it. Returns counts only — no content."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return score_text(text, spec)


def _render_table(name: str, result: dict) -> str:
    rows = []
    header = f"{'entity':<12} {'correct':>7} {'wrong':>6}  wrong breakdown"
    rows.append(f"# {name}")
    rows.append(header)
    rows.append("-" * len(header))
    for ent, counts in result.items():
        breakdown = (
            ", ".join(f"{form}={n}" for form, n in counts["wrong"].items())
            if counts["wrong"]
            else "(no known-wrong variant)"
        )
        rows.append(
            f"{ent:<12} {counts['correct']:>7} {counts['wrong_total']:>6}  {breakdown}"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Redacted entity counts for transcript QA (counts only, "
        "never transcript text)."
    )
    ap.add_argument("files", nargs="+", type=Path, help="transcript .txt path(s)")
    ap.add_argument(
        "--json", action="store_true", help="emit machine JSON instead of a table"
    )
    ap.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="JSON entity spec replacing the built-in default (for "
        "meeting-specific entities kept out of the repo)",
    )
    args = ap.parse_args(argv)

    spec = load_spec(args.spec) if args.spec else ENTITY_SPEC

    files_out = []
    for path in args.files:
        if not path.exists():
            print(f"!! missing: {path}", file=sys.stderr)
            continue
        result = score_file(path, spec)
        files_out.append({"path": str(path), "name": path.name, "entities": result})

    if args.json:
        print(json.dumps({"spec_version": 1, "files": files_out}, ensure_ascii=False))
    else:
        for f in files_out:
            print(_render_table(f["name"], f["entities"]))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
