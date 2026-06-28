# STT backend host decision (#5) — domovoy is the engine, erable is the door

*2026-06-28. Closes the "where does the public CPU rung actually run?" fork left
open in the gradient plan. Companion to `2026-06-23`-era audit notes and the
`#3` CPU bench / `#9` SIMD audit.*

## The measurement (always measure the rung before placing it)

`ssh pln@domovoy.local` — domovoy is a **Raspberry Pi 5 Model B Rev 1.1**:

| Axis | Value | Consequence |
|---|---|---|
| SoC | BCM2712, **Cortex-A76 ×4 @ 2.4 GHz**, aarch64 | a real quad-core, not a toy |
| RAM | **16 GiB** (14 free), 9 GiB swap | medium/large-q5 weights fit with headroom |
| Storage | 477 GB NVMe (5% used) | model cache + audio scratch, no SD-card wear |
| SIMD | `asimd` (NEON), `fphp`+`asimdhp` (fp16), **`asimddp` (dotprod)** | exactly whisper.cpp's tuned ARM kernels; no `i8mm` (A76 predates it) |
| GPU | none | CPU rung only — as expected |
| Thermal | 52.7 °C idle, `throttled=0x0` | active-cooled, no throttle headroom worry |
| Toolchain | Debian 13 trixie, kernel 6.18, Python 3.13.5, **Docker present** | container-ready today; no poetry/ffmpeg yet |

Contrast with [[erable-host-specs]] (2011 i3-2130, ~1.8 GB free, no AVX2, glibc-only
pain): domovoy has **~8× the RAM, ~3× the usable cores, NVMe, and a SIMD profile
whisper.cpp loves**. It is a genuine inference host; erable is not.

## Decision

- **domovoy (Pi 5, 16 GB) is the STT *engine* host** — the primary public CPU rung.
- **erable stays the *front-door*** — the `api.nech.pl` nginx gateway + the thin
  `/stt/v1/` shim, which **dispatches** to domovoy. erable does no real inference.
- This honours [[feedback-progressive-enhancement-gradient]]: the rejected pattern
  is tunnelling to a *personal laptop*; a dedicated always-on Pi is **home-server
  compute**, which the doctrine explicitly endorses. domovoy qualifies.

## The engine: whisper.cpp, vindicated twice over

The host choice confirms the engine choice from two independent angles already on
record:
- **#9 SIMD audit** — ggml/whisper.cpp does *runtime* SIMD dispatch; the *same*
  source builds and runs on x86 (Raptor-Lake→Sandy-Bridge) **and** ARM NEON. qwen_asr
  is `-march=native` with compile-time AVX2 gates → wrong ISA entirely on aarch64.
  On a Pi, whisper.cpp isn't merely the portable choice, it's the *only* turnkey one.
- **#3 CPU bench** — domovoy's `fphp`+`asimddp` are what make q5/q8 quantized
  small/medium tractable on ARM. The `#4` bar is unchanged: **whisper.cpp-q5 must
  match qwen's 0.68 WER with prompt-bias restored at ≤1× RTF** — now to be measured
  on *this* silicon, not a laptop proxy.

## What this hands to the next tasks

- **#6 (shim)** gains a hard requirement: erable→domovoy needs a **private mesh**
  (tailscale/wireguard), since domovoy is a home box and `api.nech.pl` is public.
  The shim proxies; it must **never** vendor qwen_asr onto a no-AVX2 host (#9).
  And per house style (*graceful degradation, never X-or-nothing*): erable should
  keep a local **whisper.cpp-tiny rung-0** so a domovoy outage degrades (slow/coarse)
  rather than 503s.
- **#4 (WhisperCppEngine)** now has its real CPU-rung target hardware identified;
  the bench (`scripts/bench_cpu_stt.py`, registry-driven) should add an ARM/domovoy
  run alongside the laptop numbers.
- **Gradient, updated**: rung-0 erable=whisper.cpp-tiny (degraded fallback) →
  **rung-1/2 domovoy=whisper.cpp small/medium-q5 (primary public CPU)** → rung-3+
  GPU runner (faster-whisper large-v3-turbo, future). One weight family spans 2-5.

## Open / deferred

- **#5b** measure domovoy under load — actual whisper.cpp small-q5 RTF on A76 (the
  table above is idle specs; RTF is the number that places the rung). Folds into #4's
  bench run.
- domovoy has no `poetry`/`ffmpeg` yet — provisioning is part of #6, not #5.
- Mesh choice (tailscale vs wireguard) deferred to #6 build.
