# Lean APK + on-device model download — Android build note (#13)

**Date:** 2026-07-23 · **Issue:** [#13](https://github.com/PLNech/TuParles/issues/13)
· **Goal:** the standing app-weight goal — "130mb is heavy!"

## The problem, and the reframe

The Android APK shipped one bundled `ggml-base` (~142 MB of a ~186 MB debug
build — roughly 95% of the weight). The obvious fix — bundle a smaller model —
just trades quality for size. The real fix is to bundle *no* model and fetch one
at first run, which also lets the user pick where they sit on the speed↔quality
ladder instead of living with whatever we shipped.

That requires the `INTERNET` permission, which the app had proudly never
declared. The owner's reframe settled it: **our moat is not our current
permission set, but our outlook.** The privacy invariant is precise and
unchanged — *voice, recordings, and user data never leave the device* — and a
model download does not touch it: it is **inbound only** (huggingface.co → the
phone), and nothing about the user is ever uploaded. The manifest comment now
says exactly that, rather than the old "no INTERNET by design" absolute that the
change would have made a lie.

## Decisions

### Why the system `DownloadManager`, not an HTTP client

A model is 30–550 MB; the download must survive the user leaving the app and
even the process being killed, resume rather than restart, and not need a
foreground service of our own. Android's `DownloadManager` gives all of that for
free, with its own progress notification, and **adds no dependency** — the house
rule for this task barred OkHttp/Retrofit anyway. The one cost is that it stages
to app-private *external* files, so we copy-and-atomic-rename into internal
`filesDir/models/` after verifying. We abstracted it behind a tiny
`FileDownloader` interface so the whole download *coordination* (progress →
verify → install → wake pending notes) is pure Kotlin and unit-testable on the
JVM with a fake; only the ~40-line `DownloadManagerFileDownloader` is Android.

### Why verify sha256 *before* activation

Consistent with the house line — *safety is structural, not statistical.* A
model file is only ever activated (moved into `filesDir/models/` where the engine
will load it) after its bytes hash to the catalog's sha256; a mismatch deletes the
staged file and reports `FailReason.CHECKSUM`, never a half-download the native
loader might crash on. The move itself streams to a same-dir `.part` then renames
(atomic on one filesystem), so the destination file exists only complete and
verified — never a truncated model masquerading as installed. `isInstalled` also
re-checks the exact byte length, so an interrupted move never counts.

The catalog's sha256 values are the git-LFS pointer `oid`s from the whisper.cpp
mirror (`.../raw/main/<file>` → a few hundred bytes each), which is the
authoritative digest HF serves the real bytes against. Four of the five were
cross-checked at build time against local copies (`tiny-q5_1`, `small-f16`,
`medium-q5_0`, `base-f16`); all matched. `large-v3-turbo-q5_0` had no local copy
and is taken from its pointer alone.

### Resolution order and the runtime switch

The engine no longer assumes a bundled asset. It reads a `ModelResolver` each
time it needs a context, in order: **active downloaded model → recommended if
downloaded → any downloaded (catalog order) → bundled asset (dev builds) →
unavailable.** Downloaded always beats the bundled asset so a fresh user choice
is never shadowed by a stale dev file. `available` is computed live, so the app
flips to ready the instant a model lands (and the waiting notes decode).

The native whisper context is a non-thread-safe process singleton, so a model
switch cannot happen mid-decode. `ensureContext()` compares the resolved source
against what is loaded and, when they differ, releases the old context and loads
the new — always under the existing `DecodeGate` mutex on the committed path. A
live partial that arrives during the swap simply skips (the gate is busy); the
recording is never touched. This reuses the #42 priority machinery rather than
adding a second lock.

### Packaging: lean by default, dev-bundle by opt-out

`androidResources.ignoreAssetsPatterns += "models"` excludes the dev model
directory from every build, so a clean checkout (the dir is gitignored) *and* a
dev box that ran `fetch-android-model.sh` both produce a ~45 MB debug APK.
Verified empirically: a clean `assembleDebug` yields **47,619,533 bytes**. The
engine keeps its asset-load branch, so a deliberate offline-demo build works by
dropping that one exclusion line and fetching a model.

### First-run behaviour = dictaphone-first, unchanged doctrine

Recording is never blocked by the absence of a model. A note that cannot be
decoded yet is `PENDING` ("en attente d'un modèle") rather than a terminal
`UNAVAILABLE` — it is genuinely *waiting for a model*, and `retryPending()`
(called when a download completes) sweeps up everything waiting. The first-run
card is a nudge, not a gate; it is dismissible and disappears on its own once a
model is present.

## What still needs a device

Unit tests cover the catalog integrity, the resolution *order*, the download
state machine (fake downloader), `ModelStore` sha256/atomic-install, and the two
ViewModels (fake `DownloadManager`, temp-dir store, sparse-file fixtures for
"installed" catalog models). Device-only: the real `DownloadManager` fetch and
its progress/notification, the native context load from a downloaded file
(`createContextFromFile`) vs a bundled asset, and a model switch under live
decode. Those are the manual QA checklist for the first on-device run.

## Play Data-safety form — DRAFT wording (human-gated)

The form itself is filled by a human; this is the wording to paste, grounded in
what the app actually does:

- **Does your app collect or share any of the required user data types?** No.
- **Data collected:** None. Microphone audio, transcripts, and notes are created
  and stored **only on the device**; they are never transmitted off it.
- **Data shared:** None. Sharing a note (audio or text) is the user's own
  explicit action through the Android system share sheet to an app they choose;
  the app itself sends nothing.
- **Network use:** The app downloads a speech-recognition model from
  huggingface.co (inbound only) so it need not bundle it. No user data is sent as
  part of this or any other request.
- **Data encrypted in transit:** N/A for user data (none is sent); the model
  download is over HTTPS.
- **Users can request deletion:** Notes are deleted in-app; downloaded models are
  deleted in Réglages → Modèles. Uninstalling removes everything.
