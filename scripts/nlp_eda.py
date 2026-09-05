#!/usr/bin/env python3
"""Exploratory data analysis for the corpus-analysis engine (#54).

Runs the full pipeline over one or more repos and reports:

* discovery: how much the noise filter dropped (the fixture-noise problem),
* corpus size, and where salience comes from (the SrcType breakdown),
* dict-seed top-N, and how the three signals (symbol / tfidf / embed) disagree,
* whisper-risk distribution, and metafeature correlations,
* (with --embed) the embedding comparison + clusters/themes.

Prints Markdown-ready tables to stdout AND dumps a metrics JSON (separate path,
never overwriting source data). Feeds docs/research + the notebook.

    poetry run python scripts/nlp_eda.py                 # fast, no embeddings
    poetry run python scripts/nlp_eda.py --embed         # + fastembed signal

## Corpora: TuParles is the only corpus baked into this file

This repo is the built-in default and is always PUBLIC. Any other corpus (a
private/work codebase, say) comes from configuration, never from source, and
defaults to PRIVATE unless explicitly marked public -- "it's a setting": a
sensible default, a total override. Configure extra corpora with either:

* a local, gitignored `.eda-corpora.toml` next to this repo's root:

      [corpora.SomeName]
      path = "/abs/path/to/repo"
      public = false        # optional, default false (PRIVATE)

* and/or the `TUPARLES_EDA_CORPORA` env var -- comma-separated `name=path`
  pairs (a bare path is accepted too; the name defaults to the last path
  component). Append `:public` to a path to mark that one corpus public;
  everything else stays PRIVATE by default:

      TUPARLES_EDA_CORPORA="Work=/home/me/work-repo,Oss=/home/me/oss:public"

Both layers merge (env overrides the config file, which overrides the
built-in); either can be omitted.

Any term surface mined from a corpus NOT marked public is pseudonymized
(stable, deterministic) before it is printed or written to the metrics JSON --
never the real symbol. Aggregate numbers (counts, TF-IDF, correlations, risk
buckets) are computed over the real text and are never redacted; only the
example strings are. See docs/research/2026-06-24-codebase-aware-dict-seeding-eda.md
for the note this guards against recurring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tuparles.nlp import Corpus, code_documents
from tuparles.nlp.engines import dictseed
from tuparles.nlp.parse import WEIGHT, SrcType

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ENV_VAR = "TUPARLES_EDA_CORPORA"
CONFIG_FILE = REPO_ROOT / ".eda-corpora.toml"
OUT_JSON = Path("docs/research/data/2026-06-24-nlp-eda.json")
EMBED_CAP = 4000  # cap candidates embedded for the (slow) semantic signal


@dataclass(frozen=True)
class CorpusSpec:
    """One corpus to mine: where it lives, and whether it may be named/quoted
    raw in the report. Only an explicit `public=True` earns that; discovered
    (env/config) corpora default to private."""

    path: Path
    public: bool


def _builtin_corpora() -> dict[str, CorpusSpec]:
    return {"TuParles": CorpusSpec(REPO_ROOT, public=True)}


def _parse_env_corpora(value: str) -> dict[str, CorpusSpec]:
    """See the module docstring for the `TUPARLES_EDA_CORPORA` format."""
    corpora: dict[str, CorpusSpec] = {}
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, sep, rhs = chunk.partition("=")
        if not sep:  # bare path, no "name="
            rhs = name
            name = ""
        public = False
        if rhs.endswith(":public"):
            public = True
            rhs = rhs[: -len(":public")]
        elif rhs.endswith(":private"):
            rhs = rhs[: -len(":private")]
        path = Path(rhs.strip()).expanduser()
        corpora[name or path.name] = CorpusSpec(path, public=public)
    return corpora


def _parse_config_file_corpora(path: Path) -> dict[str, CorpusSpec]:
    """See the module docstring for the `.eda-corpora.toml` format."""
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    corpora: dict[str, CorpusSpec] = {}
    for name, entry in data.get("corpora", {}).items():
        raw_path = entry.get("path")
        if not raw_path:
            continue
        corpora[name] = CorpusSpec(
            Path(raw_path).expanduser(), public=bool(entry.get("public", False))
        )
    return corpora


def load_corpora() -> dict[str, CorpusSpec]:
    """Built-in (TuParles, public) < local config file < env var."""
    corpora = _builtin_corpora()
    corpora.update(_parse_config_file_corpora(CONFIG_FILE))
    env_value = os.environ.get(CONFIG_ENV_VAR)
    if env_value:
        corpora.update(_parse_env_corpora(env_value))
    return corpora


def _pseudonym(surface: str) -> str:
    """Stable, deterministic alias for a term mined from a private corpus --
    same alias every run (so diffs/history stay legible), never reversible to
    the real symbol by inspection."""
    digest = hashlib.sha1(surface.casefold().encode("utf-8")).hexdigest()[:10]
    return f"PrivateTerm_{digest}"


def _corpus_alias(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    return f"PrivateCorpus_{digest}"


@dataclass
class Redactor:
    """The redact-by-default guard: keep private-corpus names and term
    surfaces out of both stdout and the metrics JSON. Aggregate numbers never
    pass through this -- only display strings do."""

    private_repos: set[str] = field(default_factory=set)

    def repo(self, name: str) -> str:
        """Display name for a repo/corpus: itself if public, a stable alias
        (never the real name) if private."""
        return name if name not in self.private_repos else _corpus_alias(name)

    def surface(self, surface: str, key: str, corpus: Corpus) -> str:
        """Display string for a term surface: itself if every corpus it was
        seen in is public, a stable pseudonym otherwise."""
        if not self.private_repos:
            return surface
        if corpus.sources_for(key) & self.private_repos:
            return _pseudonym(surface)
        return surface


def _bar(frac: float, width: int = 28) -> str:
    return "█" * round(frac * width)


def build(repos: dict[str, Path]) -> tuple[Corpus, dict]:
    docs, stats = code_documents(repos)
    corpus = Corpus()
    corpus.ingest(docs)
    corpus.finalize()
    corpus.compute_metafeatures()
    disc = {
        "n_files": stats.n_files,
        "mineable": stats.mineable,
        "by_kind": dict(stats.by_kind),
        "skipped": dict(stats.skipped),
    }
    return corpus, disc


def section_discovery(report: dict, repos: dict[str, Path], red: Redactor) -> None:
    print("\n## Discovery — the noise-filter footprint\n")
    print("| repo | tracked files | mineable | dropped | by kind |")
    print("|---|--:|--:|--:|---|")
    for name, root in repos.items():
        disp = red.repo(name)
        _, disc = build({name: root})
        report["discovery"][disp] = disc
        dropped = disc["n_files"] - disc["mineable"]
        kinds = ", ".join(f"{k}:{v}" for k, v in sorted(disc["by_kind"].items()))
        print(
            f"| {disp} | {disc['n_files']} | {disc['mineable']} | "
            f"{dropped} ({_pct(dropped, disc['n_files'])}) | {kinds} |"
        )
        print(f"|   ↳ dropped breakdown | | | | {_fmt(disc['skipped'])} |")


def section_salience_sources(report: dict, corpus: Corpus) -> None:
    print("\n## Where salience comes from (Σ weight by SrcType)\n")
    totals: dict[str, float] = {}
    for ts in corpus.stats.values():
        for stype, n in ts.by_type.items():
            totals[stype] = totals.get(stype, 0.0) + n * WEIGHT[SrcType(stype)]
    grand = sum(totals.values()) or 1.0
    report["salience_by_srctype"] = totals
    print("| SrcType | Σ salience | share | |")
    print("|---|--:|--:|---|")
    for stype, val in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"| {stype} | {val:,.0f} | {val / grand:.1%} | {_bar(val / grand)} |")


def section_seed(report: dict, corpus: Corpus, backend, red: Redactor) -> None:
    label = "symbol+tfidf+embed" if backend else "symbol+tfidf"
    print(f"\n## Top dict-seed candidates ({label})\n")
    seeds = dictseed.seed(corpus, backend=backend, top=25)
    report["top_seeds"] = [
        {
            "surface": red.surface(s.surface, s.key, corpus),
            "seed_score": s.seed_score,
            "risk": s.whisper_risk,
            "salience": s.salience,
            "tfidf": s.tfidf,
            "signals": s.signals,
        }
        for s in seeds
    ]
    print("| # | term | seed | risk | salience | tfidf |")
    print("|--:|---|--:|--:|--:|--:|")
    for i, s in enumerate(seeds, 1):
        disp = red.surface(s.surface, s.key, corpus)
        print(
            f"| {i} | `{disp}` | {s.seed_score:.4f} | {s.whisper_risk:.2f} "
            f"| {s.salience:.0f} | {s.tfidf:.2f} |"
        )


def section_signal_disagreement(report: dict, corpus: Corpus, red: Redactor) -> None:
    from tuparles.nlp.signals import rank_symbol, rank_tfidf

    cands = corpus.candidates()
    sym = rank_symbol(cands)[:15]
    tfidf = rank_tfidf(cands)[:15]
    surf = {t.key: t.surface for t in cands}

    def disp(key: str) -> str:
        s = surf.get(key)
        return red.surface(s, key, corpus) if s else ""

    sym_disp = [disp(k) for k in sym]
    tfidf_disp = [disp(k) for k in tfidf]
    report["disagreement"] = {"symbol_top15": sym_disp, "tfidf_top15": tfidf_disp}
    print("\n## Signal disagreement — symbol vs TF-IDF top-15\n")
    print("| rank | by salience (symbol) | by distinctiveness (tfidf) |")
    print("|--:|---|---|")
    for i in range(15):
        a = sym_disp[i] if i < len(sym_disp) else ""
        b = tfidf_disp[i] if i < len(tfidf_disp) else ""
        print(f"| {i + 1} | `{a}` | `{b}` |")
    overlap = len(set(sym) & set(tfidf))
    print(
        f"\n*Top-15 overlap: {overlap}/15 — "
        f"{'signals largely agree' if overlap > 9 else 'signals see different vocab'}.*"
    )


def section_risk_and_corr(report: dict, corpus: Corpus) -> None:
    cands = corpus.candidates()
    risk = np.array([dictseed.whisper_risk(t) for t in cands])
    sal = np.array([t.salience for t in cands])
    tf = np.array([t.tfidf for t in cands])
    print("\n## Whisper-risk distribution (candidates, count≥2)\n")
    buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    dist = {}
    for lo, hi in buckets:
        n = int(((risk >= lo) & (risk < hi)).sum())
        dist[f"{lo:.1f}-{hi:.1f}"] = n
        print(f"| {lo:.1f}–{hi:.1f} | {n:5d} | {_bar(n / max(len(risk), 1))} |")
    ident = np.array([t.is_identifier for t in cands])
    report["risk"] = {
        "n_candidates": len(cands),
        "buckets": dist,
        "mean_risk_identifier": float(risk[ident].mean()) if ident.any() else 0.0,
        "mean_risk_prose": float(risk[~ident].mean()) if (~ident).any() else 0.0,
    }
    print(
        f"\nmean risk — identifiers {report['risk']['mean_risk_identifier']:.2f} "
        f"vs prose {report['risk']['mean_risk_prose']:.2f}"
    )
    # metafeature correlations
    corr = {
        "salience~tfidf": _corr(sal, tf),
        "salience~risk": _corr(sal, risk),
        "tfidf~risk": _corr(tf, risk),
    }
    report["correlations"] = corr
    print("\n## Metafeature correlations (Pearson)\n")
    for k, v in corr.items():
        print(f"- {k}: {v:+.2f}")


def section_embed(report: dict, corpus: Corpus, backend, red: Redactor) -> None:
    from scipy.stats import spearmanr

    from tuparles.nlp.engines import cluster
    from tuparles.nlp.signals import rank_embed, rank_symbol, rank_tfidf

    # Embedding 39k mostly-noise C++ tokens is slow and low-value. Cap to the
    # top-distinctive candidates (by TF-IDF) — where semantic structure is
    # meaningful — and SAY SO rather than silently truncating.
    all_cands = corpus.candidates()
    cands = sorted(all_cands, key=lambda t: -t.tfidf)[:EMBED_CAP]
    print(
        f"\n*(embedding the top {len(cands):,} of {len(all_cands):,} candidates "
        f"by TF-IDF — clustering 39k noise tokens adds little.)*"
    )
    emb_rank, _ = rank_embed(cands, backend)
    sym_rank = rank_symbol(cands)
    tf_rank = rank_tfidf(cands)
    pos = {k: i for i, k in enumerate(emb_rank)}
    sym_pos = {k: i for i, k in enumerate(sym_rank)}
    tf_pos = {k: i for i, k in enumerate(tf_rank)}
    keys = [t.key for t in cands]
    e = [pos[k] for k in keys]
    s = [sym_pos[k] for k in keys]
    t = [tf_pos[k] for k in keys]
    rho_es = spearmanr(e, s).correlation
    rho_et = spearmanr(e, t).correlation
    report["embed"] = {
        "backend": backend.name,
        "spearman_embed_symbol": float(rho_es),
        "spearman_embed_tfidf": float(rho_et),
    }
    print(f"\n## Embedding signal — {backend.name}\n")
    print(f"- Spearman(embed, symbol) = {rho_es:+.2f}")
    print(f"- Spearman(embed, tfidf)  = {rho_et:+.2f}")
    print("  *(low |ρ| ⇒ the embedding adds an independent view, worth fusing)*")
    clusters = cluster.cluster_terms(corpus, backend, cands=cands, n_clusters=10)
    report["clusters"] = [
        {
            "size": c.size,
            "theme": [red.surface(m, m.casefold(), corpus) for m in c.label_terms],
        }
        for c in clusters
    ]
    print("\n## Semantic clusters / themes (KMeans on term embeddings)\n")
    print("| size | theme (top-salience members) |")
    print("|--:|---|")
    for c in clusters:
        disp_terms = [red.surface(m, m.casefold(), corpus) for m in c.label_terms]
        print(f"| {c.size} | {', '.join('`' + m + '`' for m in disp_terms)} |")


def _pct(n: int, d: int) -> str:
    return f"{n / d:.0%}" if d else "0%"


def _fmt(d: dict) -> str:
    return ", ".join(f"{k}:{v}" for k, v in sorted(d.items()))


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", action="store_true", help="add the fastembed signal")
    ap.add_argument("--out", type=Path, default=OUT_JSON)
    args = ap.parse_args()

    corpora = load_corpora()
    repos = {name: spec.path for name, spec in corpora.items() if spec.path.exists()}
    red = Redactor({name for name in repos if not corpora[name].public})
    report: dict = {"repos": [red.repo(n) for n in repos], "discovery": {}}

    backend = None
    if args.embed:
        from tuparles.nlp.signals import FastEmbedBackend

        backend = FastEmbedBackend()

    print(f"# NLP corpus-analysis EDA — {', '.join(red.repo(n) for n in repos)}")
    section_discovery(report, repos, red)

    corpus, _ = build(repos)
    report["n_terms"] = len(corpus.stats)
    report["n_candidates"] = len(corpus.candidates())
    print(
        f"\n**Corpus:** {len(corpus.stats):,} unique terms, "
        f"{len(corpus.candidates()):,} candidates (count≥2), {corpus.n_docs} docs.\n"
    )

    section_salience_sources(report, corpus)
    section_seed(report, corpus, backend, red)
    section_signal_disagreement(report, corpus, red)
    section_risk_and_corr(report, corpus)
    if backend is not None:
        section_embed(report, corpus, backend, red)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n_Metrics JSON → {args.out}_")


if __name__ == "__main__":
    main()
