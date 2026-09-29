# Performance audit and implementation — 2026-09-29

## Implemented

1. **Preview worker lifecycle.** Each recording owns a cancellation event. A new
   recording never clears the previous worker's event. Preview candidates carry
   a generation ID and are checked on the GUI thread before publication, covering
   both in-flight decoding and already-queued signals. Language reset runs under
   the engine lock in the worker, rather than blocking the GUI.
2. **Asynchronous analytics.** Tabs render lazily through a Qt worker pool. Only
   the GUI thread updates widgets. Loading and safe error states replace the
   synchronous dialog constructor; close, Escape, and deletion during rendering
   are covered. Results are cached for that dialog only, so reopening reads fresh
   data and there is no application-wide cache of cleared history.
3. **Bounded audio snapshots.** `Recorder.snapshot(max_samples=...)` selects only
   the chunks needed for the preview tail. Concatenation happens outside the
   audio callback lock. The existing unlimited snapshot API remains supported.

The synthetic lifecycle reproduction previously let both old and new preview
threads decode five times after rapid stop/start. Regression tests now cover the
same overlap and stale queued publication.

A synthetic ten-minute capture (18,000 blocks of 533 mono int16 samples) measured
25.05 ms per full snapshot versus 0.54 ms for a ten-second bounded snapshot on the
development machine. These are audio-copy timings, not end-to-end decode gains.
The audit's synthetic 2,000-dictation analytics workload took about 4.1 seconds
for tag/keyphrase computation; that work now runs outside the GUI thread.

## Validation

- Default regression suite after the UX follow-up: 1,036 passed, 75 deselected; one existing
  `silero_vad` deprecation warning.
- Ruff lint and format checks passed.
- Mypy passed across 75 source files.
- New tests cover cancellation/generations, bounded copying and lock scope,
  lazy analytics rendering, failure handling, dismissal, deletion, and fresh
  results after reopening. The follow-up adds switch-timing censoring/boundary
  checks and benchmark return-type/error-completion regressions.

## Local inference benchmark scope

The two further candidates are optional desktop word alignment and reduced
language-detection frequency for live previews. Neither changes production
decoding in this patch.

Inputs are selected using a read-only `share_ok = 1` query. Explicitly private
and unreviewed recordings are excluded. References are screened with the existing
secret/structured-PII/denylist detectors plus basic identifier patterns; audio
format and duration are checked. Selection balances duration and broad language
metadata. The current store has 62 consented recordings; 56 pass the 2–90 second
duration/format/filter rules. The bounded sample contains 12 recordings totaling
283.4 seconds. These filters cannot recognize every name, so audio and decoded
text stay inside the local process regardless of screening. Reports contain only
aggregate metrics; no take IDs, filenames, prompts, or transcript examples.

During the initial phase, the machine reported battery power. Those benchmarks used cached CPU models and serialized
inference with a shared lock; no GPU decode or model download is required.
Stored transcripts are earlier ASR outputs, not human-verified references:
differences are **drift**, not proof of recognition accuracy. CPU alignment
measurements are a proxy and cannot establish the GPU turbo model's speedup.

### Word alignment: small CPU proxy gain

Cached faster-whisper `base`, CPU int8, four threads, batched beam-five decode;
one warmup per condition and two timed repeats per recording, with alternating
condition order. Both conditions use the same prepared audio, language options,
and in-memory vocabulary prompt.

| Metric | Word timestamps on | Word timestamps off |
|---|---:|---:|
| Decode median, 24 measurements | 2.2943 s | 2.1959 s |
| Decode p90 | 8.1841 s | 7.7454 s |
| Median token drift against stored ASR | 0.2379 | 0.2379 |
| Repeat output agreement | 12/12 | 12/12 |

The median **paired** off/on time ratio is 0.9702 (about 3% lower time), with
p90 1.074: some recordings were slower without alignment. Filtered, normalized
output matched between conditions for all 12 recordings. This is a small,
variable gain on the proxy, not evidence for a large GPU speedup. Keep production
alignment unchanged pending a benchmark of the actual turbo/GPU path.

The installed batched decoder removes `max_speech_duration_s` from its caller's
options dictionary and substitutes `chunk_length` (30 seconds here). This affects
the dictionary recorded by the initial runner, but not the effective VAD cap in
either condition. Future runs pass a fresh dictionary to avoid misleading metadata.

Aggregate artifact: [word-alignment benchmark](data/2026-09-29-word-alignment-bench.json).

### Preview language detection: faster median, observable behavior changes

Cached faster-whisper `base` CPU int8, six-second preview window, one-second
sampling, up to the first eight ticks per recording. The 12 recordings produced
88 paired windows. After warmup, condition order alternated by recording (six
baseline-first and six prototype-first). The prototype detects every window until
a sticky language exists, then collects fresh language evidence every third
window; it does not count cached detections as new evidence. Both paths retain
the production hysteresis and partial sanitizer.

| Metric | Detect every window | Reduced cadence |
|---|---:|---:|
| Total window time, median | 1,196.902 ms | 936.231 ms |
| Total window time, p90 | 4,125.477 ms | 4,236.248 ms |
| Fresh detection calls | 88 | 42 |

The paired median time difference is -289.416 ms; its p90 is +932.259 ms.
The ratio of overall medians suggests about 22% lower typical latency, but tail
latency did not improve. Filtered output matched for 82/88 windows (93.18%);
token edit drift relative to the baseline was 3.81%. Sticky language conditioning
disagreed in two of the 77 windows with a language on either path.

Only one baseline language transition occurred in the sampled intervals. The
prototype did not reach that language again before the interval ended (reported
switch lag is null, not zero). This small sample cannot prove code-switch
accuracy; it already shows a behavioral tradeoff. **Do not adopt the cadence
change from this result.** Prefer investigating reuse of compatible encoder
results, preserving the frequency of fresh language evidence, then validate with
longer recordings containing known language switches. The current production
detector remains unchanged.

Aggregate artifact: [preview-language benchmark](data/2026-09-29-preview-language-bench.json).

## GPU follow-up on mains power

The following follow-up used the RTX 4080 Laptop GPU on AC power. Inference jobs
shared an exclusive lock so benchmarks did not decode concurrently. Models were
loaded from the existing cache with downloads disabled.

### Alignment on the actual turbo model

The same 12 consented recordings ran through turbo CUDA float16, batch size 16,
beam size five, with three repeats per condition and alternating order.

| Metric | Word timestamps on | Word timestamps off |
|---|---:|---:|
| Pooled median, 36 decodes | 0.9496 s | 0.8821 s |
| Pooled p90 | 1.3678 s | 1.2063 s |
| Repeat agreement | 12/12 | 12/12 |

The per-recording paired off/on time ratio has median 0.9726 and p90 1.0099:
about **2.7% lower time at the paired median**, with some slower recordings.
The pooled median difference is not a paired speedup estimate. Filtered outputs
matched in all 12 recordings and all repeats; median drift from stored ASR was
0.0665 in both conditions. The gain remains small even on the actual GPU, so
alignment stays unchanged.

Artifact: [GPU alignment A/B](data/2026-09-29-word-alignment-gpu.json).

### Exact encoder reuse: no cache hits

The investigation instrumented eight consented recordings, two growing windows
per recording, two repeats, and alternating baseline/prototype order. Language
state reset once per two-window take. The cache lived only inside one preview
invocation and reused results only when feature shape, dtype, and every value
matched. There was no cross-window reuse or change to language evidence.

**Every raw-detection feature input differed from the VAD-transcription input.**
Across 32 preview calls per condition, both paths made 64 encoder calls. There
were zero exact cache hits and no output differences or exceptions. Mean preview
wall time was 0.6033 s baseline versus 0.5936 s with caching; because no work was
eliminated, that difference is not evidence of an optimization.

Baseline mean measured stages were 0.3502 s encoding, 0.0718 s feature extraction,
and 0.0922 s decoder generation. Detection took 0.2207 s **including** its feature
extraction and encoding; these overlapping stage timings must not be summed.
They are CPU wall wrappers, not independently synchronized CUDA kernel profiles.
Uninstrumented two-window mean time was 1.1977 s, versus about 1.2066 s with
instrumentation (roughly 0.7% overhead).

Do not add this cache to production. Saving an encoder pass would require a
deliberate change to a shared audio/feature preparation path, which changes the
language detector's input and must earn its place on switch-quality tests.

Artifact: [GPU encoder reuse profile](data/2026-09-29-encoder-reuse-gpu.json).

### Existing adversarial bilingual baseline

The existing 72 public synthesized fixtures were also decoded on the current
GPU/application path, with only aggregate scoring retained. **20/72 passed**
their strict required/forbidden phrase gates; 52 missed required anchors and six
contained a forbidden phrase (overlapping counts). None of the eight
mid-sentence-switch fixtures passed all their gates. Median reference WER was
0.6364. These are deliberately difficult synthetic fixtures, not a representative
field accuracy estimate. No decoding behavior changed in this patch; this is a
current baseline, not a measured regression against a previous version.

Artifact: [adversarial GPU baseline](data/2026-09-29-codeswitch-gpu-baseline.json).

### Real GPU previews, stop/restart, and Analytics together

The responsiveness harness now accepts the `Transcription` return type and exits
on decode failures. Its `controller-gpu` mode exercises the real Controller and
GPU engine with public audio, a fake recorder, stubbed delivery, and an isolated
temporary history containing 2,000 synthetic rows. The run stops during a real
preview and restarts while the first final decode is still pending.

- Restart occurred after 63.8 ms, before the first delivery; both queued takes,
  stub deliveries, and completion signals retained order `[1, 2]`.
- Stop-to-stub-delivery took 1,476.4 ms and 510.2 ms. These include scheduling and
  inference, but exclude physical typing/pasting.
- Three preview decodes took 941.7, 562.9, and 584.9 ms; the single measured
  interval between published previews was 1,031.9 ms.
- Analytics loaded in 3,052.7 ms. Across 105 GUI heartbeat ticks, p99 was
  111.1 ms and the maximum was 128.5 ms; two gaps exceeded 100 ms.
- No harness errors occurred. Separate direct GPU runs decoded 8-second and
  66-second public clips in 1.35 and 1.59 seconds, respectively, with no GUI
  heartbeat gap above 100 ms.

This supports correct ordering and concurrent progress under actual inference,
while showing occasional UI pauses remain. It does not measure physical hotkeys,
microphone capture, clipboard/paste delivery, or repeated-trial latency tails.
Run with `QT_QPA_PLATFORM=offscreen poetry run python scripts/bench_responsiveness.py
--mode controller-gpu --json-out /tmp/tuparles_responsiveness_gpu.json` (hold the
shared inference lock when running alongside other benchmarks).

Artifact: [combined GPU responsiveness](data/2026-09-29-responsiveness-gpu.json).

### Independent synthetic phrase and translation controls

Two additional fixtures join locally synthesized English and French speech, with
known splice times, independently specified phrases, and explicit opposite-language
translation traps. Their target segments last more than 33 seconds, allowing
the old language to leave the 20-second preview window completely. No model or
voice downloads were needed. Twelve sampled ticks per fixture cover the lead-in,
transition, and fully replaced window.

| Direction | First sampled target-language selection | Target anchors after old audio leaves | Translation-trap hits |
|---|---:|---:|---:|
| French → English | +5 s | 8/10 | 0 |
| English → French | +22 s | 0/10 | 0 |

The English-target case had one empty output among its five fully replaced
windows; an earlier run hit all ten anchors. The French-target case produced
nonempty output in all five windows but missed every expected anchor. Therefore,
zero forbidden-phrase hits does **not** establish successful preservation or
absence of translation: that control is inconclusive when the expected words
are missing. No decoded text was retained.

These are coarse observations from robotic speech, not production switch-lag
estimates: sparse ticks update the sticky-language hysteresis less often than
the production roughly 1 Hz loop. They expose a useful quality failure to keep
in the evaluation set, without establishing general bilingual accuracy.

Artifact: [public synthetic switch controls](data/2026-09-29-switch-controls-gpu.json).

### Controlled switches from consented recordings

The 56 eligible recordings were screened for sufficient duration, stored EN/FR
language metadata, and agreement from three disjoint three-second detection
probes with confidence at least 0.85. Fourteen donors passed. Four in-memory
fixtures use seven distinct donors: two French → English and two English →
French, each with a ten-second lead and a 24-second target segment. One donor
appears twice. The labels are automatically screened, not human-verified; a
splice marks the target clip's start, not an annotated first phoneme.

Both conditions replay 136 windows at one-second audio timestamps, with a
20-second maximum window and production greedy decoding, sanitizer, and sticky
language hysteresis. The prototype gathers fresh evidence every third window
after a language is established. Models are warmed up, state resets per fixture
and condition, and condition order alternates by fixture. This is a single
paired run per fixture; order also coincides with switch direction, so it does
not isolate ordering effects. Timing is detection plus consumed decode wall
time, not a real-time UI replay.

| Metric | Fresh detection every window | Every third window after lock |
|---|---:|---:|
| Median window time | 632.8 ms | 477.7 ms |
| p90 window time | 816.3 ms | 727.6 ms |
| Fresh detection calls | 136 | 48 |
| Switches confirmed within 24 s | 4/4 | 3/4 |

The paired median time difference is -172.2 ms; its p90 is +38.8 ms. Filtered
outputs agree in 113/136 windows (83.09%), with 21.32% token edit drift relative
to baseline. Conditioning languages disagree in 13/134 windows where either
path has selected a language. No detection or decoding exceptions occurred.

| Fixture | Baseline switch lag | Reduced-cadence switch lag |
|---|---:|---:|
| French → English A | 21 s | Not observed within 24 s |
| English → French A | 4 s | 6 s |
| French → English B | 21 s | 24 s |
| English → French B | 9 s | 13 s |

These lags measure audio elapsed since the splice, separately from decode wall
time. A missed transition is censored, never treated as zero delay. Comparing
the conditions' medians only over successful switches would be misleading:
the candidate's apparent lower successful-only median excludes its missed case.
Output drift is not a verified translation-error rate.

**Keep the existing detection cadence.** The GPU savings are measurable, but
all three jointly observed switches are delayed by 2–4 seconds and the fourth
is not observed within the available horizon. The baseline's own 21-second
switch delays also warrant investigation, with independently labeled natural
switches before changing language conditioning or audio preparation.

Artifact: [consented GPU switch timing A/B](data/2026-09-29-switch-timing-gpu.json).

## Next work

Retain the lifecycle, asynchronous Analytics, and bounded-snapshot fixes. Keep
alignment and language-detection behavior unchanged. Prioritize a small human-
verified natural switch set and experiments that improve baseline switch lag
while preserving fresh evidence; separately profile the remaining roughly
129 ms GUI pauses. Exact encoder caching alone cannot save work on the current
distinct detection/transcription inputs. Physical microphone/hotkey/paste
validation remains outside these replay-based checks.

## Shipping follow-up: earlier Analytics content and Android recovery

The desktop patch retains all three validated responsiveness fixes. Analytics
now publishes its tag cloud as soon as it is ready, then adds keyphrases after
the existing extraction completes. The rankings, history limits, and final
successful content are unchanged. If keyphrase extraction fails, the cloud stays
visible alongside a generic recovery message. Three additional regression cases
cover progressive display, a later failure, and dismissal during extraction.

One isolated synthetic 2,000-row Controller run, after other validation jobs
finished, showed the cloud after 2,933.9 ms and the full result after 3,672.5 ms:
**738.6 ms earlier visible content**. This is a within-run comparison of two
render milestones, not an extraction speedup. It includes cold NLP imports and
uses a delayed fake engine, so it does not update the earlier GPU comparison.
The maximum GUI heartbeat gap was 109.4 ms, with one gap over 100 ms; occasional
pauses remain. Delivery order was preserved and the harness reported no errors.
Artifact: [progressive Analytics](data/2026-09-29-progressive-analytics.json).

Android receives small UX fixes found during the shipping review:

- Microphone denial explains how to enable access and opens app settings.
- The first-run model card displays download failure reasons with Retry, reusing
  the model picker's messages. Its primary button has its own row to fit narrow
  screens.
- Transcript text supports selection/copy. Search dismisses the keyboard through
  its IME action, and tapping Record clears search focus.
- The record button uses the recording color already computed for its label,
  with the corresponding theme foreground color for contrast.

These Android changes do not alter decoding, storage, or download policy. They
claim usability benefits, not an unmeasured mobile inference speedup.

Android validation: all 132 JVM unit tests passed; `:app:lintDebug` and
`:app:assembleDebug` passed using the local offline Gradle toolchain. A debug APK
was built. Permission recovery, selection gestures, keyboard dismissal, and
small-screen layout have not yet had a physical-phone smoke test. No release
was published or installed on a device.
