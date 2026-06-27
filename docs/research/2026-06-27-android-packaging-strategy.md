# Android Packaging Strategy — resolving the central fork

**Issue**: #2 — Make TuParles Android-library-ready for local voice apps  
**Angle**: Packaging & portability strategy  
**Date**: 2026-06-27  
**Status**: Research complete; recommendation: Branch 2 (Kotlin port), conditionally reversible

---

## The thing being packaged

Before evaluating how to carry the code, tally exactly what it is.

The on-device postprocess chain lives in these files (pure Python, `re`/`string`/`dataclasses`/`collections.abc`/`json` only — nothing from the heavy desktop deps):

| file | LOC | deps (internal) |
|---|---|---|
| `pipeline.py` | 45 | orchestrates the chain |
| `punctuation.py` | 127 | — |
| `lexicon.py` | 42 | — |
| `repeats.py` | 41 | — |
| `syntax.py` | 145 | `settings` (XDG read) |
| `casing.py` | 183 | `settings` (XDG read) |
| `spans.py` | 96 | — |
| `syntax_features/caps.py` | 80 | — |
| `syntax_features/quotes.py` | 153 | — |
| **total** | **~912 LOC** | — |

Plus `settings.py` (~175 LOC, pure Python, `json`/`os`/`pathlib`) — the one non-portable piece (reads `~/.config/tuparles/settings.json`, a desktop XDG path).

The data — `SPOKEN_TO_SYMBOL` list (20 bilingual FR/EN patterns), `LEXICON` dict (4 entries), `PROTECTED_PHRASES` list — is embedded in Python source but is logically separable from the algorithm.

**Key calibration**: carrying the postprocess to Android means carrying ~912 LOC of stdlib regex, not a framework or a scientific computing stack. This number drives the fork decision more than any latency or size benchmark.

---

## The two branches

### Branch 1 — Embed CPython, run the modules as-is

A Python runtime is bundled in the APK alongside the Kotlin app. Kotlin calls `pipeline.postprocess(text, ctx)` over a JNI bridge. The STT engine (whisper.cpp or sherpa-onnx, native C/C++) operates independently.

**Candidate runtimes**

| runtime | status (2026) | notes |
|---|---|---|
| **Chaquopy** (CHAQUO Ltd) | Commercial, active; Python 3.13 supported; arm64-v8a only for 3.11+ | Gradle plugin; designed for Kotlin/Java embed pattern; not a full-app shell |
| **BeeWare/Briefcase** | PyPI "4 - Beta" (Dec 2025); focused on producing standalone APKs with Python shell | Not designed for library-embed use case; requires a BeeWare app wrapper |
| **python-for-android (p4a)** | Community; "recipes" for C-extension packages; pure Python automatic | Lower bus factor; Kivy-centric; library embed requires custom bootstrap |
| **CPython tier-3 (PEP 738)** | Accepted; tier-3 for aarch64-linux-android in 3.13+ | Official core support reduces reliance on any single packager; BeeWare/p4a already leverage it |

PEP 738 (accepted, shipping in CPython 3.13) makes Android a first-class build target in CPython core. This is a material development: it distributes the maintenance burden from Chaquopy alone across the entire CPython project. The risk column for Branch 1 is therefore softer in 2026 than it was in 2024.

**APK size contribution (Branch 1)**

- Chaquopy demo app: **46-52 MB** (MEASURED from published APK — but this is a demo that includes numpy, scipy, matplotlib; not a pure-Python-only embed)
- Minimal CPython arm64 runtime `.so`: **~5-8 MB** (ESTIMATED; no published figure for pure-Python-only app; prescribe: build a "hello world" Chaquopy APK with zero third-party packages and measure)
- Minimal stdlib needed for `re`/`string`/`dataclasses`: **~2-4 MB** (ESTIMATED)
- The 912 LOC Python source: negligible (< 50 KB)
- **Realistic minimal embed overhead: 8-15 MB** (ESTIMATED, not directly measured)

For comparison, the STT decode model dominates:
- whisper.cpp tiny.en Q5_1: **31 MB** (MEASURED)
- whisper.cpp tiny multilingual Q5_1: **77 MB** (MEASURED)
- sherpa-onnx Zipformer-small: **~60-80 MB** (MEASURED)

The Python runtime layer is not the APK budget constraint. The model is.

**Cold-start / import cost**

No publicly measured figure for minimal Chaquopy (pure-Python-only) cold-start was found. Claimed figures for BeeWare production apps (~145ms) originate from a single case study of unclear methodology — treat as unverified CLAIM. The CPython interpreter, once loaded, persists in-process; postprocess runs are subsequently microseconds per call (all regex, no IO). Cold-start is a one-time cost if the Python interpreter is kept resident.

**JNI bridge**

For this use case the bridge pattern is: one UTF-8 string in (raw ASR text) → one UTF-8 string out (processed text). Single string marshal per take is best-practice JNI and carries negligible overhead. Recursive JNI crossings would be expensive, but `pipeline.postprocess()` is a pure function — no callbacks or object passing required.

**Regex dialect (Branch 1): identical**  
CPython `re` runs on Android exactly as on desktop. No dialect translation needed.

---

### Branch 2 — Port the postprocess semantics to Kotlin

~912 LOC Python → estimated **~1,000-1,300 LOC Kotlin** (ESTIMATED; no direct measurement; based on regex-heavy Python→Kotlin porting ratio, noting Kotlin is not more verbose than Python for regex/string work).

**One-time port effort**: 2-4 weeks (ESTIMATED) for a careful implementation that passes the code-switch eval harness.

**The critical regex-dialect risk**: Python `re` and JVM/Kotlin `Regex` diverge on exactly what this code uses. `\b` word boundaries and `IGNORECASE` around non-ASCII French characters (à, é, œ, æ, ç) behave differently: JVM `\w`/`\b` are ASCII-only by default; `à`, `é` etc. are treated as non-word characters unless `RegexOption.UNICODE_CHARACTER_CLASS` is set (Java `Pattern.UNICODE_CHARACTER_CLASS` flag). A naive port will silently break French-typography cases — the eval corpus will catch this, but it must be checked exhaustively. This is validate-not-assume; it is not a blocker, but it is non-trivial.

**Ongoing maintenance: the dual-harness cost**

The code-switch eval harness (`tests/test_codeswitch_eval.py` + corpus in `tests/data/codeswitch/`) currently pins correctness of one implementation. With Branch 2, every change to the postprocess logic requires:

1. Updating Python source
2. Porting the change to Kotlin
3. Running both implementations against the full corpus and asserting identical output

This is a permanent maintenance tax on every postprocess evolution. The lexicon and spoken-to-symbol rules are data that will evolve (new tech terms, new bilingual patterns, new syntax features). The eval harness *can* serve as a cross-language conformance gate — the inputs/outputs are raw strings, language-agnostic — but it requires discipline to run it against both sides on every commit.

**The data-externalisation mitigation**: the churning part of the postprocess is data, not algorithm. `SPOKEN_TO_SYMBOL` (20 entries), `LEXICON` (4 entries), `PROTECTED_PHRASES` are all simple lists/dicts. Extracting these to a shared `postprocess-data.json` consumed by both the Python desktop module and the Kotlin Android module would gut most of the "keeping two impls in sync" objection. The stable algorithm then needs porting once; only data updates are shared. This is the single highest-leverage mitigation for Branch 2's ongoing cost.

---

## Portability of `settings.py`

Both branches require solving the same problem: `settings.py` reads a desktop XDG path. On Android there is no `~/.config/tuparles/settings.json`.

The fix is the same either way: extract a `SettingsProvider` interface (Python protocol or ABC) with `get(key)` / `set(key, value)`, inject it at startup, and make `XDGSettingsProvider` one implementation. `AndroidSharedPrefsProvider` is the Kotlin-side companion. This is a one-day refactor, branch-independent.

The existing `capability.py` design — `Chain`/`Layer`/`Tool` with `resolved` property, probe-once, inject fake runner for tests — is the right shape for the `CapabilityReport` the Android library should emit at init time.

---

## Contract layer sketch (branch-independent)

The public API to the Kotlin app is the same regardless of which branch is chosen:

```
// Kotlin caller (pseudocode)
val session = TuParlesSession.create(context, CapabilityReport.probe())
val processed = session.postprocess(rawAsrText, SyntaxContext(fmt = "plain", appClass = "terminal"))
```

```python
# Python side (Branch 1) — existing pipeline.postprocess unchanged
def postprocess(text: str, ctx: SyntaxContext | None = None) -> str: ...
```

Events the library should emit:
- `OnTakeReady(raw: String, processed: String, durationMs: Long)`
- `OnCapabilityReport(report: CapabilityReport)` — at init, per the `capability.py` doctrine

`CapabilityReport.probe()` on Android: engine (whisper.cpp / sherpa-onnx / vosk / none), ABI, Android API level, available RAM tier (coarse: <2GB / 2-4GB / >4GB), postprocess mode (embedded-python / kotlin-port / unavailable).

The interface is identical whether the impl is Branch 1 or Branch 2. **The decision is reversible**: define the contract, implement behind it, switch later. This matters for sequencing: a team can ship Branch 2 first (lower APK overhead, no runtime dep) and migrate to Branch 1 if the postprocess logic grows complex enough to justify the runtime cost.

---

## STT engine (noted, not the focus)

The decode engine is native C/C++ either way — the postprocess fork doesn't affect this choice.

| engine | size | WER FR (MLS) | notes |
|---|---|---|---|
| whisper.cpp tiny multilingual Q5_1 | 77 MB (MEASURED) | 36.8% (MEASURED) | — |
| whisper.cpp base multilingual | 148 MB (MEASURED) | ~20% (CLAIM) | — |
| whisper.cpp tiny.en Q5_1 | 31 MB (MEASURED) | — | EN-only, unsuitable for code-switching |
| sherpa-onnx Zipformer-small | ~60-80 MB (MEASURED) | varies by model (CLAIM) | broader model zoo |
| Vosk | ~40-50 MB (MEASURED) | higher WER than Whisper (MEASURED) | lower accuracy, lighter |

For a FR/EN code-switching app, whisper.cpp base multilingual (148 MB) is the minimum for acceptable quality. This number, not the Python runtime, is the APK budget constraint.

---

## Recommendation

**Branch 2 (Kotlin port) is the default recommendation, with data-externalisation.**

The decisive factors, in order of weight:

1. **Surface is bounded and stable.** ~912 LOC of stdlib regex is a one-time, bounded port. It is not a framework rewrite.

2. **No runtime overhead.** Carrying a CPython runtime (8-15 MB ESTIMATED) + JNI bridge for 912 LOC of regex, when Kotlin `Regex` covers the same ground natively, is "shipping a fridge to carry a sandwich." The model (77-148 MB) already dominates APK size; minimising the code layer keeps the app lean.

3. **No single-vendor runtime dependency.** Even with PEP 738 softening the risk, Chaquopy (currently the most mature embed path) is a commercial product maintained by a small company. A Kotlin port has zero runtime dependency outside the JVM.

4. **The eval harness becomes a cross-language conformance gate.** The corpus (`tests/data/codeswitch/`) is raw-string-in / expected-string-out — language-agnostic. Running it against the Kotlin impl on every CI build makes the port *safe* and *auditable*.

5. **Data externalisation guts the ongoing dual-maintenance cost.** Extract `SPOKEN_TO_SYMBOL`, `LEXICON`, `PROTECTED_PHRASES` to `postprocess-data.json`. Both implementations consume the file; only data updates are shared. Algorithm changes are infrequent; data additions are the day-to-day churn.

**Discriminating threshold — when to flip to Branch 1 (embed)**:

- If the postprocess logic were to grow significantly in complexity (e.g., adding a statistical re-ranker, integrating an ML model, absorbing a NLP library) such that the Kotlin port becomes unbounded in scope.
- If the regex-dialect audit reveals more than ~5 substantive divergence cases that the eval corpus does not cover — indicating the port is fragile in ways that are hard to gate.
- If the team has zero Kotlin/JVM expertise and the port cost materially exceeds the 2-4 week estimate.

**Prescribe before committing — two cheap experiments**:

1. Build a minimal Chaquopy APK (no third-party packages, just `re` and a 50-line hello-world). Measure the APK delta. This converts the "8-15 MB" ESTIMATED overhead to MEASURED and settles the Branch 1 size argument definitively.

2. Port `punctuation.py` to Kotlin first (127 LOC, most complex regex). Run the codeswitch corpus against it. Count the `\b`/IGNORECASE mismatches on French text. If zero mismatches: the port is safe to proceed. If multiple: document the divergence pattern and add corpus entries before continuing.

---

## What to do next (sequenced)

1. **Abstract `SettingsProvider`** (branch-independent, one day) — required either way; unblocks both branches.
2. **Externalise postprocess data to `postprocess-data.json`** (one day) — guts ongoing dual-maintenance cost.
3. **Port `punctuation.py` to Kotlin, run corpus** (2-3 days) — the discriminating experiment; confirms or rejects Branch 2.
4. **Define the `TuParlesSession` contract** (one day) — Kotlin interface, language-agnostic; makes the decision reversible.
5. **Port remaining modules** (1-2 weeks) — once experiment 3 passes.
6. **Wire whisper.cpp AAR** (separate epic) — native engine, not blocked by postprocess fork decision.

---

## Figures summary

| figure | value | status |
|---|---|---|
| Postprocess chain LOC | ~912 | MEASURED (counted) |
| Branch 2 Kotlin port effort | 2-4 weeks | ESTIMATED |
| Branch 2 ongoing dual-harness tax | per-evolution, permanent | STRUCTURAL |
| Chaquopy demo APK size | 46-52 MB | MEASURED (demo app, not minimal) |
| Minimal CPython embed overhead | 8-15 MB | ESTIMATED |
| BeeWare "145ms cold start" | — | CLAIM REJECTED (single case, unclear methodology) |
| whisper.cpp tiny.en Q5_1 | 31 MB | MEASURED |
| whisper.cpp tiny multilingual Q5_1 | 77 MB | MEASURED |
| WER whisper tiny FR (MLS) | 36.8% | MEASURED |
| WER whisper small FR (MLS) | 16.2% | MEASURED |
| PEP 738 Android tier-3 | CPython 3.13+, aarch64 | FACT (accepted PEP) |
