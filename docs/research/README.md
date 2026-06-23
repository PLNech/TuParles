# Research notebook

Verbatim outputs of focused research passes, kept so future work (and future
blog posts) can stand on them without re-deriving. Each file is a dated,
self-contained brief. `SOURCES.md` aggregates the external links.

> Design note — *how we display this matters as much as what we found.* These
> are written as readable prose, not link-dumps, precisely because the long
> game is to turn them into stories: how a private, local dictation tool grew
> a meeting-notes brain, and the product choices made along the way. When a
> brief becomes load-bearing for a sprint, lift its recommendation into a
> `docs/spike-*.md` decision record (see `spike-backend.md` for the shape).

## Index

### Meeting note-taking sprint (researched 2026-06-23)
The pivot from *dictation* (you speak → it types) to *meeting capture* (it
listens → you get notes). Five orthogonal dimensions:

- [Commercial landscape](2026-06-23-meeting-notes-commercial-landscape.md) —
  Granola, Otter, Fireflies, Zoom, Teams, Fathom, tl;dv, + local-first
  (Hyprnote, Meetily). Table-stakes vs differentiators.
- [Speaker diarization SOTA](2026-06-23-diarization-sota.md) — who-said-what,
  local, on a 4080. Verdict: WhisperX + pyannote 4.x.
- [Local LLM summarization](2026-06-23-local-llm-summarization.md) — transcript
  → notes locally. The Granola "augment my notes" pattern, models for 16 GB.
- [Linux audio capture](2026-06-23-audio-capture-linux.md) — capturing both
  sides of a call (mic + system monitor) on PipeWire. Dual-channel = free
  diarization.
- [Voice UI command & control](2026-06-23-voice-ui-command-control.md) — Dragon,
  Talon, the command-vs-dictation disambiguation problem. Feeds the "effacer
  effacer effacer" meta-language idea and task #33.
- [Granola, up close](2026-06-23-granola-deep-dive.md) — a close-range competitive
  study of the category leader (researched from inside an actual call): full feature
  surface, the API/MCP platform, the privacy varnish, and every user complaint that
  maps to a local-first opening. The companion deep-dive to the landscape brief.

## The story so far (one paragraph, for the eventual post)

TuParles started as push-to-talk dictation for French-English code-switchers.
The product thesis that kept paying off: **the differentiator is not the
features — every tool lists the same features — it is *where your voice lives
afterward*.** Cloud bucket, or your own silicon. Build for the silicon and the
privacy story writes itself. The meeting-notes pivot is the same bet at larger
scale: the whole Granola/Otter/Fireflies map is reproducible locally on one
RTX 4080, and the one thing none of them can offer — the audio never leaving
the machine — is the thing we get for free.
