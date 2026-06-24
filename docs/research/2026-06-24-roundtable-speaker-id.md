# Roundtable mode: diarize, then put names to voices

*Research synthesis, 2026-06-24. Seeds the blog (#42). Three parallel angles
(diarization / enrollment-ID / roundtable-glue + eval + biometric privacy)
folded into one design. Extends the meeting-mode epic (#35-#39). No code yet -
landscape + build-vs-rent verdict.*

## Why

Meeting mode (#35) turns a recording into a transcript. A transcript that says
"Speaker 1 / Speaker 2 / Speaker 3" is half a product. "Roundtable mode" closes
it: at the top of the meeting each person says "moi c'est PLN" / "moi c'est
Guillaume" (optionally a short fixed passphrase), the tool enrolls each voice,
and the rest of the transcript is labelled by **name**. The payoff is a named,
searchable, action-item-able meeting record - all local.

Crucial crossover with the PII work: **voiceprints are biometric data** (GDPR
Art. 9 special category). The same local-only / consent / easy-delete doctrine
from the PII firewall is a hard requirement here, not a nicety.

## The shape: rent the models, own the spine

The spine we own: enrollment-centroid management, the abstain interlocks, the
name-binding from ASR, and the diarization-cluster→identity matching. The models
(diarization, embeddings) are rented.

```
recording (mic + monitor, on disk)
   │
   ├─ enrollment phase: each person says "moi c'est X" (+ passphrase)
   │     │   ASR transcribes ──► extract NAME ("moi c'est X")
   │     └─ capture clean 8-10s ──► embed ──► centroid[X]   (voiceprint)
   ▼
faster-whisper transcribe ─► wav2vec2 forced-align (word ±50ms)
   ▼
diarization (community-1) ─► anonymous clusters + segment times
   ▼
per-cluster centroid ─► cosine-match vs enrolled centroids
   ▼
   τ threshold + top1-vs-top2 margin  ──► name  OR  "unknown" (abstain)
   ▼
named transcript  ──►  manual re-label UI (locks user edits)
```

## Diarization (angle D): keep WhisperX, swap the model up

- **Spine to rent: WhisperX's flow** - transcribe → **wav2vec2 forced alignment**
  (word boundaries ±50ms vs ±500ms vanilla) → diarize → assign words to the
  max-overlap speaker. The forced-alignment step is the real value; it's what
  makes word→speaker attribution trustworthy. WhisperX lets you supply your own
  diarization pipeline, so improving the diarizer is a model swap, not a
  re-architecture.
- **GPU default: `pyannote/speaker-diarization-community-1`** (2025 successor to
  3.1; AMI 17.0, VoxConverse 11.2 DER; handy *exclusive-diarization* mode that
  collapses overlaps so each instant has one speaker - simplifies reconciliation
  with STT timestamps). Challenge to the #39 plan-as-written: WhisperX bundles
  the older **3.1** - swap up to community-1.
- **Licensing verdict (matters for a shippable/sellable tool):** community-1 is
  HF-gated but **CC-BY-4.0 → re-hostable with attribution**. So "every user
  fetches gated weights + accepts terms" is a **one-time packaging chore** (mirror
  + checksum + version in our release artifacts), not a per-user blocker. Never
  ship a tool that forces an HF account.
- **CPU-light fallback ("it's a setting"): `sherpa-onnx`** offline diarization
  (pyannote-segmentation-3.0 + CAM++ + agglomerative clustering). ~45MB, **no
  PyTorch/CUDA**, un-gated ONNX, ~12-15% DER, ~30s for a 45-min meeting on an M1.
  This is the recipe behind OpenWhispr's 100%-local notetaker - a near-exact
  TuParles analog. Smart default = community-1 on GPU; override = sherpa-onnx for
  no-GPU / low-RAM / zero-dependency installs.
- **Rejected:** NeMo Streaming Sortformer (hard **4-speaker cap**; CALLHOME DER
  6.6→21.7→28.7% at 2/5/6 speakers - fatal for a table; its 0.32s latency solves
  a streaming problem we don't have - this is batch). DiariZen (best open DER,
  VoxConverse 5.2%, but **CC-BY-NC weights → non-commercial** - taints
  distribution; note as the accuracy ceiling to revisit if licensing changes).
- **Two myth-busters:** (1) it's a **batch** job over the captured file, not
  streaming. (2) Dual-channel capture (#36) only gives a free split for **remote
  calls** (mic="you", monitor="them"); at an **in-person table everyone is on the
  mic**, so on-mic clustering does all the real work - the monitor channel adds
  nothing for roundtable. Don't assume dual-channel helps here.

## Enrollment + identification (angle E): the passphrase is a mic check

- **The key reframe: text-DEPENDENT scoring does NOT help here.** Its advantage
  exists only when the same phrase appears at enroll AND test; meeting-time ID
  scores free-flowing speech (text-independent). So the "brown fox" passphrase is
  a **clean-audio collector**, not a scoring trick - it guarantees a few seconds
  of near-field, single-speaker, full-phonetic-coverage audio for a robust
  centroid. Use a text-**independent** embedding model.
- **Rent the embedding model:** **3D-Speaker CAM++** (7.2M params, 0.65%
  VoxCeleb1-O EER, **Apache-2.0, native ONNX, no torch**) as primary - fits the
  fastembed/ONNX posture exactly. **NeMo TitaNet-L** (0.66% EER) on the 4080 if
  we accept CC-BY-4.0 + en-US-only. **ECAPA-TDNN** (SpeechBrain, Apache-2.0) is
  the most-documented fallback. (Avoid Resemblyzer as primary - ~4.5% EER, a
  generation behind.)
- **Enrollment:** capture passphrase (~3-5s) + the free "moi c'est X" (~2-5s),
  embed each window, **average into a centroid**; aim ≥8-10s total. Multiple
  short windows beat one long take (lower intra-speaker variance).
- **Abstain by design (the doctrine, structural):** (1) absolute cosine threshold
  τ calibrated *above* the EER point so false-accept ≪ false-reject; (2) a
  **top1-vs-top2 margin interlock** - if best−second < δ, emit "unknown" rather
  than guess. Two hard interlocks, not a confidence score. τ and δ are Réglages
  knobs with conservative defaults. A 3-person meeting has no cohort for
  AS-norm, so prefer absolute-τ + margin over score normalization.
- **Match at the cluster level** (mean of a diarization cluster's segment
  embeddings), not per-segment - the centroid averages out segment noise.
- **Where errors compound:** diarization boundary errors → mixed cluster →
  corrupted centroid → misattribution; over-clustering → one person split →
  spurious "unknown". Mitigation: cluster-level match + let "unknown" absorb
  low-confidence clusters. Tune τ/δ *jointly* with the diarizer, not in isolation.

## Roundtable glue, evaluation & biometric privacy (angle F)

This angle has its own dedicated note - **`2026-06-24-roundtable-name-binding-eval-privacy.md`**.
The load-bearing points it establishes:

- **Name-binding from ASR**: anchored FR+EN patterns primary ("moi c'est X", "je
  m'appelle X", "my name is X", "X here"); NER only as a *suggestion to confirm*
  (FR person-NER is weak); a one-glance confirm step turns the fallible
  extraction into a human-checked one. Binding (audio→embedding) is reliable;
  *extraction* rides ASR's worst case (proper nouns) - mitigate with a per-user
  name lexicon via dict-seed (#54). Store keys on the voiceprint, not the string
  (two Guillaumes → merge, never silent duplicate).
- **Cross-session voice memory**: two-threshold open-set match (accept / reject /
  **abstain grey-zone = the safety margin**); update centroid only on *confirmed*
  matches; **ephemeral by default, persistence opt-in - and that toggle is the
  consent boundary**.
- **Evaluation**: **DER**, **JER** (DIHARD II), **cpWER** (CHiME-6 Track 2 - the
  headline "is the named transcript right?" metric), plus a name-ID **asymmetric
  scorecard**: gate hard on **wrong-name rate (<~2%)**, *tolerate* abstain rate (a
  system that abstains more to drive wrong-name to zero scores better). In-house
  FR+EN roundtable corpus under `tests/data/roundtable/` is the load-bearing
  artifact (no public corpus has the intro ritual).
- **Biometric law**: voiceprints are GDPR **Art. 9** special category → lawful
  basis = explicit consent (the spoken opt-in). The **EU AI Act** escape: active
  spoken intro is **not** *remote* biometric ID (Art. 3), so it dodges both Art.
  5(1)(h) prohibition and Annex III high-risk. Requirements: local-only, consent
  ritual, **easy-delete** ("forget Guillaume") sharing one erasure path with the
  PII firewall, transparency, persistence = consent boundary. *Distinguish
  "we're recording" from "we're storing your voiceprint" - different asks.*

## Decisions & open questions

1. **Re-host community-1 weights** (CC-BY-4.0) in our release artifacts - legal,
   one-time, ours to maintain (mirror/checksum/version + attribution notice).
2. **Confirm a French wav2vec2 forced-alignment model** is wired in WhisperX -
   alignment is the per-language-weakest link in the chain.
3. **CAM++ ONNX no-torch path** - verify it runs under our pinned onnxruntime
   (likely yes; fastembed already pulls onnxruntime). Spike before committing.
4. **Short-enrollment reliability + FR accents + far-field** are the biggest
   empirical unknowns - validate on the in-house corpus, trust nothing published
   on clean monolingual English.
5. **Manual re-label UI is a first-class feature**, not an afterthought - every
   local tool ships one (overlaps, short utterances, walk-ins are unavoidable);
   lock user edits against re-runs.

## Proposed shape (for elicitation, not yet built)

A `roundtable/` module (or extend a `meeting/` package): `diarize` (rent WhisperX
+ community-1 / sherpa-onnx), `enroll` (passphrase capture + centroid),
`identify` (cosine + τ/δ abstain), `bind` (name-from-ASR), `memory` (persistent
voiceprints, consented + deletable), plus `tests/data/roundtable/` and
`test_roundtable_eval.py`. Phase 1 = anonymous diarization (delivers labelled-but-
unnamed transcripts immediately, the #39 target). Phase 2 = enrollment + named ID
+ abstain. Phase 3 = cross-session voice memory + the privacy controls.

## Sources

Diarization: [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) ·
[community-1 blog](https://www.pyannote.ai/blog/community-1) ·
[WhisperX](https://github.com/m-bain/whisperX) ·
[sherpa-onnx diarization](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-speaker-diarization.py) ·
[OpenWhispr local diarization](https://openwhispr.com/blog/local-speaker-diarization) ·
[Streaming Sortformer (4-spk cap)](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2) ·
[DiariZen (CC-BY-NC)](https://github.com/BUTSpeechFIT/DiariZen) ·
[Benchmarking diarization (arXiv 2509.26177)](https://arxiv.org/html/2509.26177v1)

Embeddings/ID: [3D-Speaker CAM++/ERes2Net](https://github.com/modelscope/3D-Speaker) ·
[ECAPA-TDNN (SpeechBrain)](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) ·
[NVIDIA TitaNet-L](https://huggingface.co/nvidia/speakerverification_en_titanet_large) ·
[ERes2NetV2 short-duration](https://www.isca-archive.org/interspeech_2024/chen24l_interspeech.pdf) ·
[TdSV Challenge 2024](https://arxiv.org/abs/2404.13428) ·
[pyannote known-speaker pattern](https://github.com/pyannote/pyannote-audio/discussions/1667)

> *"Tiri nko agyina"* - Akan: one head does not hold the council. Around a real
> table, neither does one channel - plan for the many, and ask each their name.
