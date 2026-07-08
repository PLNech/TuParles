#!/usr/bin/env python3
"""Render a before/after transcript diff as a single self-contained HTML page.

Given pairs of (baseline, re-run) transcript files, produce one local page —
"TuParles — avant/après" — showing, inline, exactly what a re-run changed:
removed baseline words struck through in red, added words highlighted green,
unchanged prose dimmed, entity forms badged (green pill = correct form, red
pill = known-wrong variant per the entity spec), and turn seams ("— " block
starts) styled as first-class citizens.

Design choice — unified inline diff, anchored on the RE-RUN token stream —
rather than two aligned columns: ASR re-runs substitute words, they don't
restructure documents, so most tokens are identical and a two-column layout
would duplicate every unchanged word and split single-word changes across the
screen. Inline (the `git --word-diff` idiom) keeps one readable prose flow:
you read the transcript you'll keep, and see what it cost. Timestamps and
seam markers are structural — stripped before matching, re-attached from the
re-run side for display (baseline timestamps are dropped; they may drift by a
second anyway).

PRIVACY: the OUTPUT embeds transcript text and therefore belongs in a
local-only directory (e.g. the gitignored docs/reports/). This script itself
carries no meeting-specific strings; meeting entities come from --spec (same
JSON format as score_transcript_entities.py --spec).

Usage:
    poetry run python scripts/render_ab_diff.py \
        --pair baseline1.txt rerun1.txt --pair baseline2.txt rerun2.txt \
        --spec entities.json --chart /tmp/chart.png -o out/ab_diff.html
"""

from __future__ import annotations

import argparse
import base64
import difflib
import html
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_scorer():
    """Import the sibling scorer module (scripts/ is not a package)."""
    name = "score_transcript_entities"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scorer = _load_scorer()

TS_RE = re.compile(r"^\[\d{1,2}:\d{2}(?::\d{2})?\]")
SEAM_PREFIX = "— "
FOLD_CONTEXT = 8  # unchanged words kept visible on each side of a fold
FOLD_MIN_RUN = 30  # unchanged runs shorter than this never fold


@dataclass
class Token:
    kind: str  # "header" | "ts" | "seam" | "word" | "nl"
    text: str


def tokenize(text: str) -> list[Token]:
    """Split a transcript into structural tokens + words.

    Header lines (#…), [mm:ss] stamps and "— " seam prefixes are structural:
    excluded from diff matching, re-attached at render time.
    """
    out: list[Token] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(Token("header", stripped))
            out.append(Token("nl", ""))
            continue
        rest = stripped
        m = TS_RE.match(rest)
        if m:
            out.append(Token("ts", m.group(0)))
            rest = rest[m.end() :].lstrip()
        if rest.startswith(SEAM_PREFIX):
            out.append(Token("seam", "—"))
            rest = rest[len(SEAM_PREFIX) :]
        elif rest == "—":
            out.append(Token("seam", "—"))
            rest = ""
        out.extend(Token("word", w) for w in rest.split())
        out.append(Token("nl", ""))
    return out


def words_of(tokens: list[Token]) -> list[str]:
    return [t.text for t in tokens if t.kind == "word"]


def badge_words(words: list[str], spec) -> dict[int, str]:
    """Map word index -> 'ok'|'bad' for entity correct/wrong variant matches.

    Runs the scorer's own compiled patterns over the space-joined words, then
    maps character spans back to word indices, so multi-word variants badge
    every word they cover.
    """
    joined = " ".join(words)
    # char offset -> word index
    starts: list[int] = []
    pos = 0
    for w in words:
        starts.append(pos)
        pos += len(w) + 1
    badges: dict[int, str] = {}
    for ent in spec:
        for variants, mark in ((ent.correct, "ok"), (ent.wrong, "bad")):
            for v in variants:
                pat = scorer.compile_variant(v.form, v.case_sensitive)
                for m in pat.finditer(joined):
                    for i, s in enumerate(starts):
                        if s >= m.end():
                            break
                        if s + len(words[i]) > m.start():
                            badges[i] = mark
    return badges


@dataclass
class Cell:
    html: str
    changed: bool  # part of a diff hunk (never folded)
    foldable: bool  # words/newlines may fold; ts/seam/header may not


def _word_html(word: str, cls: str, badge: str | None) -> str:
    classes = cls
    if badge:
        classes += f" pill-{badge}"
    return f'<span class="{classes}">{html.escape(word)}</span>'


def render_pair_body(base_text: str, rerun_text: str, spec) -> str:
    """The inline diff HTML for one file pair (no page chrome)."""
    base_tokens = tokenize(base_text)
    rerun_tokens = tokenize(rerun_text)
    base_words = words_of(base_tokens)
    rerun_words = words_of(rerun_tokens)
    base_badges = badge_words(base_words, spec)
    rerun_badges = badge_words(rerun_words, spec)

    sm = difflib.SequenceMatcher(None, base_words, rerun_words, autojunk=False)
    # rerun word index -> ("equal"|"ins", deletions to inject before it)
    word_cls: dict[int, str] = {}
    inject: dict[int, list[int]] = {}  # rerun word idx -> base word idxs
    tail_deletions: list[int] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for j in range(j1, j2):
                word_cls[j] = "eq"
        else:
            for j in range(j1, j2):
                word_cls[j] = "ins"
            if i2 > i1:
                if j1 < len(rerun_words):
                    inject.setdefault(j1, []).extend(range(i1, i2))
                else:
                    tail_deletions.extend(range(i1, i2))

    cells: list[Cell] = []

    def flush_deletions(idxs: list[int]) -> None:
        frags = [_word_html(base_words[i], "del", base_badges.get(i)) for i in idxs]
        cells.append(
            Cell('<span class="hunk">' + " ".join(frags) + "</span>", True, False)
        )

    j = 0
    for tok in rerun_tokens:
        if tok.kind == "word":
            if j in inject:
                flush_deletions(inject[j])
            cls = word_cls.get(j, "eq")
            cell_html = _word_html(tok.text, cls, rerun_badges.get(j))
            if cls == "ins":
                cell_html = f'<span class="hunk">{cell_html}</span>'
            cells.append(Cell(cell_html, cls != "eq", cls == "eq"))
            j += 1
        elif tok.kind == "ts":
            cells.append(
                Cell(f'<span class="ts">{html.escape(tok.text)}</span>', False, False)
            )
        elif tok.kind == "seam":
            cells.append(
                Cell(
                    '<span class="seam" title="tour de parole ?">— '
                    '<span class="seam-tag">tour?</span></span>',
                    False,
                    False,
                )
            )
        elif tok.kind == "header":
            cells.append(
                Cell(f'<div class="thead">{html.escape(tok.text)}</div>', False, False)
            )
        elif tok.kind == "nl":
            cells.append(Cell("<br>", False, True))
    if tail_deletions:
        flush_deletions(tail_deletions)

    return _fold(cells)


def _fold(cells: list[Cell]) -> str:
    """Wrap long unchanged runs so 'changes only' mode can collapse them."""
    out: list[str] = []
    run: list[Cell] = []

    def flush_run() -> None:
        n_words = sum(1 for c in run if c.html.startswith("<span"))
        if n_words >= FOLD_MIN_RUN:
            # keep FOLD_CONTEXT words of context on each side, fold the middle
            head, mid, tail, seen = [], [], [], 0
            for c in run:
                is_word = c.html.startswith("<span")
                seen += is_word
                if seen <= FOLD_CONTEXT:
                    head.append(c.html)
                elif seen > n_words - FOLD_CONTEXT:
                    tail.append(c.html)
                else:
                    mid.append(c.html)
            folded_words = n_words - 2 * FOLD_CONTEXT
            out.extend(head)
            out.append(
                f'<span class="fold-mark">⋯ {folded_words} mots inchangés ⋯</span>'
                f'<span class="fold">{" ".join(mid)}</span>'
            )
            out.extend(tail)
        else:
            out.extend(c.html for c in run)
        run.clear()

    for c in cells:
        if c.foldable and not c.changed:
            run.append(c)
        else:
            flush_run()
            out.append(c.html)
    flush_run()
    return "\n".join(out)


def stat_strip(base_text: str, rerun_text: str, spec) -> str:
    """Aggregate scorer counts + structure counts for one pair. Counts only."""
    b = scorer.score_text(base_text, spec)
    r = scorer.score_text(rerun_text, spec)
    b_ok = sum(e["correct"] for e in b.values())
    r_ok = sum(e["correct"] for e in r.values())
    b_bad = sum(e["wrong_total"] for e in b.values())
    r_bad = sum(e["wrong_total"] for e in r.values())

    def arrow(before: int, after: int, good_when: str) -> str:
        if after == before:
            return f"{before} → {after} ="
        up = after > before
        good = (good_when == "up") == up
        sym = "↑" if up else "↓"
        cls = "good" if good else "warn"
        return f'{before} → {after} <b class="{cls}">{sym}{abs(after - before)}</b>'

    seams = sum(1 for t in tokenize(rerun_text) if t.kind == "seam")
    segs_b = sum(1 for t in tokenize(base_text) if t.kind == "ts")
    segs_r = sum(1 for t in tokenize(rerun_text) if t.kind == "ts")

    rows = []
    for name in b:
        bo, ro = b[name]["correct"], r[name]["correct"]
        bw, rw = b[name]["wrong_total"], r[name]["wrong_total"]
        if bo + ro + bw + rw == 0:
            continue
        rows.append(
            f"<tr><td>{html.escape(name)}</td>"
            f"<td>{arrow(bo, ro, 'up')}</td><td>{arrow(bw, rw, 'down')}</td></tr>"
        )
    table = (
        "<details><summary>détail par entité</summary>"
        "<table><tr><th>entité</th><th>correct</th><th>fautif</th></tr>"
        + "".join(rows)
        + "</table></details>"
    )
    return (
        '<div class="stats">'
        f"<span>entités correctes : {arrow(b_ok, r_ok, 'up')}</span>"
        f"<span>formes fautives : {arrow(b_bad, r_bad, 'down')}</span>"
        f"<span>segments : {segs_b} → {segs_r}</span>"
        f"<span>tours détectés : {seams}</span>"
        f"</div>{table}"
    )


CSS = """
:root { --base:#1e1e2e; --mantle:#181825; --surface:#313244; --text:#cdd6f4;
  --sub:#a6adc8; --dim:#6c7086; --green:#a6e3a1; --red:#f38ba8;
  --mauve:#cba6f7; --yellow:#f9e2af; }
* { box-sizing: border-box; }
body { background: var(--base); color: var(--text); margin: 0;
  font: 16px/1.75 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1rem 1.5rem 6rem; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 3rem; }
nav { position: sticky; top: 0; background: var(--mantle); padding: .6rem 1.5rem;
  display: flex; gap: 1.5rem; align-items: center; z-index: 5;
  border-bottom: 1px solid var(--surface); flex-wrap: wrap; }
nav a { color: var(--mauve); text-decoration: none; }
nav .hint { color: var(--dim); font-size: .8rem; margin-left: auto; }
.eq { color: var(--sub); }
.del { color: var(--red); text-decoration: line-through; opacity: .85; }
.ins { color: var(--green); background: rgba(166,227,161,.12);
  border-radius: 3px; padding: 0 2px; }
.pill-ok { border: 1px solid var(--green); border-radius: 999px;
  padding: 0 .45em; color: var(--green); font-weight: 600; }
.pill-bad { border: 1px solid var(--red); border-radius: 999px;
  padding: 0 .45em; color: var(--red); font-weight: 600; }
.ts { color: var(--dim); font-size: .8rem; font-family: monospace;
  margin-right: .4em; }
.seam { color: var(--mauve); border-left: 3px solid var(--mauve);
  padding-left: .5em; margin-left: -.8em; font-weight: 700; }
.seam-tag { font-size: .65rem; background: var(--surface); color: var(--mauve);
  border-radius: 999px; padding: 0 .5em; vertical-align: super; font-weight: 400; }
.thead { color: var(--dim); font-family: monospace; font-size: .8rem;
  border-bottom: 1px dashed var(--surface); margin: 1rem 0; }
.fold-mark { display: none; color: var(--dim); font-style: italic;
  font-size: .85rem; }
body.only .fold { display: none; }
body.only .fold-mark { display: inline; }
.hunk.focus { outline: 2px solid var(--yellow); border-radius: 3px; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; background: var(--mantle);
  padding: .6rem 1rem; border-radius: 8px; font-size: .9rem; }
.stats .good { color: var(--green); } .stats .warn { color: var(--yellow); }
details { margin: .5rem 0 1.5rem; font-size: .85rem; color: var(--sub); }
table { border-collapse: collapse; }
td, th { padding: .15rem .8rem; border-bottom: 1px solid var(--surface);
  text-align: left; }
img.chart { max-width: 100%; border-radius: 8px; margin: 1rem 0; }
label { color: var(--sub); font-size: .85rem; cursor: pointer; }
"""

JS = """
const box = document.getElementById('only');
const sync = () => document.body.classList.toggle('only', box.checked);
box.addEventListener('change', sync); sync();
const hunks = [...document.querySelectorAll('.hunk')];
let cur = -1;
function go(d) {
  if (!hunks.length) return;
  if (cur >= 0) hunks[cur].classList.remove('focus');
  cur = Math.min(Math.max(cur + d, 0), hunks.length - 1);
  hunks[cur].classList.add('focus');
  hunks[cur].scrollIntoView({block: 'center', behavior: 'smooth'});
}
document.addEventListener('keydown', e => {
  if (e.key === 'j') go(1);
  if (e.key === 'k') go(-1);
});
"""


def render_page(pairs: list[tuple[Path, Path]], spec, chart: Path | None) -> str:
    sections = []
    nav_links = []
    for n, (base_path, rerun_path) in enumerate(pairs, 1):
        base_text = base_path.read_text(encoding="utf-8", errors="replace")
        rerun_text = rerun_path.read_text(encoding="utf-8", errors="replace")
        anchor = f"f{n}"
        title = html.escape(base_path.name)
        nav_links.append(f'<a href="#{anchor}">{title}</a>')
        sections.append(
            f'<h2 id="{anchor}">{title}</h2>'
            + stat_strip(base_text, rerun_text, spec)
            + '<div class="diff">'
            + render_pair_body(base_text, rerun_text, spec)
            + "</div>"
        )

    chart_html = ""
    if chart and chart.exists():
        b64 = base64.b64encode(chart.read_bytes()).decode("ascii")
        chart_html = (
            '<img class="chart" alt="Comparaison A/B des entités" '
            f'src="data:image/png;base64,{b64}">'
        )

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TuParles — avant/après</title>
<style>{CSS}</style></head>
<body class="only">
<nav>{"".join(nav_links)}
<label><input type="checkbox" id="only" checked> changements seulement</label>
<span class="hint">j / k : sauter entre modifications</span></nav>
<main>
<h1>TuParles — avant/après</h1>
<p class="thead">baseline (avant) barré rouge · re-run (après) surligné vert ·
pilule verte = forme correcte · pilule rouge = variante fautive ·
— = tour de parole détecté</p>
{chart_html}
{"".join(sections)}
</main>
<script>{JS}</script>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--pair",
        nargs=2,
        action="append",
        required=True,
        metavar=("BASELINE", "RERUN"),
        type=Path,
        help="baseline + re-run transcript paths (repeatable)",
    )
    ap.add_argument("--spec", type=Path, default=None, help="entity spec JSON")
    ap.add_argument("--chart", type=Path, default=None, help="PNG chart to embed")
    ap.add_argument("-o", "--out", type=Path, required=True, help="output HTML path")
    args = ap.parse_args(argv)

    spec = scorer.load_spec(args.spec) if args.spec else scorer.ENTITY_SPEC
    page = render_page([tuple(p) for p in args.pair], spec, args.chart)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
