#!/usr/bin/env python3
"""Seed ablation: quantify the initial_prompt's effect on the code-switch eval.

Decodes every generated WAV under three initial_prompt regimes and reports
per-case pass + aggregate recall (FN) / leak (FP). This is the harness that
caught the over-seeding hallucination (2026-06-25) — keep it runnable so future
seed/budget changes are measured, not argued. Needs the GPU box + WAVs
(`scripts/gen_codeswitch_wavs.py`). See
docs/research/2026-06-25-transliteration-forensics.md.

  OFF     — initial_prompt=None (no bias; the honest baseline)
  CURATED — manual vocab.txt glossary only (identity + stack), no auto-seeds
  FULL    — production prompt (codebase EDA auto-seeds + manual) = what ships

Run: poetry run python scripts/measure_seed_ablation.py
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

from tuparles import engine, seed_prompt
from tuparles.eval import score_case
from tuparles.pipeline import postprocess

DATA = Path(__file__).resolve().parents[1] / "tests" / "data" / "codeswitch"
WAV_DIR = DATA / "wav"
CORPUS = json.loads((DATA / "corpus.json").read_text())["cases"]
CASES = {c["id"]: c for c in CORPUS}
ENTRIES = json.loads((WAV_DIR / "manifest.json").read_text())["files"]

NEW_IDS = {
    "dkim-dmarc-not-des-marques",
    "pii-privacy-not-pil-prev",
    "qwen-build-cpu-not-quinn-bill",
    "ui-not-ueil",
    "postgres-not-postgre",
    "personal-domains-not-neck-tl",
    "identity-paul-louis-nech",
}

REGIMES = {
    "OFF": lambda: None,
    "CURATED": lambda: seed_prompt.initial_prompt(seeds=[], bias_enabled=True),
    "FULL": lambda: seed_prompt.initial_prompt(),
}


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def main() -> None:
    eng = engine.GpuEngine()
    audios = {e["file"]: read_wav(WAV_DIR / e["file"]) for e in ENTRIES}

    # results[regime][file] = (passed, missing, leaked, heard)
    results: dict[str, dict] = {}
    for regime, prompt_fn in REGIMES.items():
        engine._vocab_prompt = prompt_fn  # type: ignore[assignment]
        p = prompt_fn()
        print(
            f"\n### {regime}  (prompt={'None' if p is None else str(len(p)) + ' chars'})"
        )
        results[regime] = {}
        for e in ENTRIES:
            heard = postprocess(eng.transcribe(audios[e["file"]]).text)
            r = score_case(CASES[e["case_id"]], heard)
            results[regime][e["file"]] = (
                r.passed,
                r.missing,
                r.leaked,
                heard,
                e["case_id"],
            )

    # --- aggregate: pass-rate, recall (must_contain found), leak (FP) ---
    def agg(files: set[str], regime: str) -> tuple[int, int, int, int, int, int]:
        passed = mc_total = mc_found = mnc_total = mnc_leak = n = 0
        for f in files:
            ok, missing, leaked, _heard, cid = results[regime][f]
            c = CASES[cid]
            n += 1
            passed += int(ok)
            mc_total += len(c.get("must_contain", []))
            mc_found += len(c.get("must_contain", [])) - len(missing)
            mnc_total += len(c.get("must_not_contain", []))
            mnc_leak += len(leaked)
        return passed, n, mc_found, mc_total, mnc_leak, mnc_total

    all_files = {e["file"] for e in ENTRIES}
    new_files = {e["file"] for e in ENTRIES if e["case_id"] in NEW_IDS}

    for label, files in (("ALL CASES", all_files), ("NEW (2026-06-25)", new_files)):
        print(f"\n===== {label} =====")
        print(
            f"{'regime':9} {'pass':>9} {'recall(found/MC)':>18} {'leak/FP(leaked/MNC)':>22}"
        )
        for regime in REGIMES:
            pa, n, mcf, mct, lk, mnct = agg(files, regime)
            rec = f"{mcf}/{mct} ({100 * mcf / mct:.0f}%)" if mct else "-"
            leak = f"{lk}/{mnct} ({100 * lk / mnct:.0f}%)" if mnct else "-"
            print(f"{regime:9} {pa:>3}/{n:<5} {rec:>18} {leak:>22}")

    # --- per NEW case: what each regime heard (the qualitative story) ---
    print("\n===== NEW CASES — heard per regime =====")
    for e in ENTRIES:
        if e["case_id"] not in NEW_IDS:
            continue
        print(f"\n• {e['file']}")
        print(f"  said: {CASES[e['case_id']]['text']}")
        for regime in REGIMES:
            ok, missing, leaked, heard, _ = results[regime][e["file"]]
            flag = "PASS" if ok else f"FAIL miss={missing} leak={leaked}"
            print(f"  {regime:8} [{flag}] {heard!r}")


if __name__ == "__main__":
    main()
