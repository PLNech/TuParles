#!/usr/bin/env python3
"""Exploratory data analysis for the corpus-analysis engine (#54).

Runs the full pipeline over one or more repos and reports:

* discovery: how much the noise filter dropped (the AlgoliaSaaS fixture problem),
* corpus size, and where salience comes from (the SrcType breakdown),
* dict-seed top-N, and how the three signals (symbol / tfidf / embed) disagree,
* whisper-risk distribution, and metafeature correlations,
* (with --embed) the embedding comparison + clusters/themes.

Prints Markdown-ready tables to stdout AND dumps a metrics JSON (separate path,
never overwriting source data). Feeds docs/research + the notebook.

    poetry run python scripts/nlp_eda.py                 # fast, no embeddings
    poetry run python scripts/nlp_eda.py --embed         # + fastembed signal
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from tuparles.nlp import Corpus, code_documents
from tuparles.nlp.engines import dictseed
from tuparles.nlp.parse import WEIGHT, SrcType

DEFAULT_REPOS = {
    "TuParles": Path("/home/pln/Work/Tools/TuParles"),
    "AlgoliaSaaS": Path("/home/pln/Work/AlgoliaSaaS"),
}
OUT_JSON = Path("docs/research/data/2026-06-24-nlp-eda.json")
EMBED_CAP = 4000  # cap candidates embedded for the (slow) semantic signal


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


def section_discovery(report: dict, repos: dict[str, Path]) -> None:
    print("\n## Discovery — the noise-filter footprint\n")
    print("| repo | tracked files | mineable | dropped | by kind |")
    print("|---|--:|--:|--:|---|")
    for name, root in repos.items():
        _, disc = build({name: root})
        report["discovery"][name] = disc
        dropped = disc["n_files"] - disc["mineable"]
        kinds = ", ".join(f"{k}:{v}" for k, v in sorted(disc["by_kind"].items()))
        print(
            f"| {name} | {disc['n_files']} | {disc['mineable']} | "
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


def section_seed(report: dict, corpus: Corpus, backend) -> None:
    label = "symbol+tfidf+embed" if backend else "symbol+tfidf"
    print(f"\n## Top dict-seed candidates ({label})\n")
    seeds = dictseed.seed(corpus, backend=backend, top=25)
    report["top_seeds"] = [
        {
            "surface": s.surface,
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
        print(
            f"| {i} | `{s.surface}` | {s.seed_score:.4f} | {s.whisper_risk:.2f} "
            f"| {s.salience:.0f} | {s.tfidf:.2f} |"
        )


def section_signal_disagreement(report: dict, corpus: Corpus) -> None:
    from tuparles.nlp.signals import rank_symbol, rank_tfidf

    cands = corpus.candidates()
    sym = rank_symbol(cands)[:15]
    tfidf = rank_tfidf(cands)[:15]
    surf = {t.key: t.surface for t in cands}
    report["disagreement"] = {"symbol_top15": sym, "tfidf_top15": tfidf}
    print("\n## Signal disagreement — symbol vs TF-IDF top-15\n")
    print("| rank | by salience (symbol) | by distinctiveness (tfidf) |")
    print("|--:|---|---|")
    for i in range(15):
        a = surf.get(sym[i], "") if i < len(sym) else ""
        b = surf.get(tfidf[i], "") if i < len(tfidf) else ""
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


def section_embed(report: dict, corpus: Corpus, backend) -> None:
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
    report["clusters"] = [{"size": c.size, "theme": c.label_terms} for c in clusters]
    print("\n## Semantic clusters / themes (KMeans on term embeddings)\n")
    print("| size | theme (top-salience members) |")
    print("|--:|---|")
    for c in clusters:
        print(f"| {c.size} | {', '.join('`' + m + '`' for m in c.label_terms)} |")


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

    repos = {n: r for n, r in DEFAULT_REPOS.items() if r.exists()}
    report: dict = {"repos": list(repos), "discovery": {}}

    backend = None
    if args.embed:
        from tuparles.nlp.signals import FastEmbedBackend

        backend = FastEmbedBackend()

    print(f"# NLP corpus-analysis EDA — {', '.join(repos)}")
    section_discovery(report, repos)

    corpus, _ = build(repos)
    report["n_terms"] = len(corpus.stats)
    report["n_candidates"] = len(corpus.candidates())
    print(
        f"\n**Corpus:** {len(corpus.stats):,} unique terms, "
        f"{len(corpus.candidates()):,} candidates (count≥2), {corpus.n_docs} docs.\n"
    )

    section_salience_sources(report, corpus)
    section_seed(report, corpus, backend)
    section_signal_disagreement(report, corpus)
    section_risk_and_corr(report, corpus)
    if backend is not None:
        section_embed(report, corpus, backend)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n_Metrics JSON → {args.out}_")


if __name__ == "__main__":
    main()
