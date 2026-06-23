# AI Meeting Note-Taker Landscape (2025-2026) — for a Local, Private, GPU Clone

*Researched 2026-06-23. Verbatim research brief.*

## Per-product one-liners

**Granola** — *No bot.* Captures system audio + mic locally on Mac/Windows/iPhone, streams to cloud ASR (Deepgram/AssemblyAI), then deletes audio. Its signature is the **"augment your own notes"** model: you jot sparse notes, it weaves transcript context into enhanced notes via OpenAI/Anthropic. Custom templates, CRM push. Only "Me vs Them" channel separation on desktop (no true diarization); SOC 2 Type 2; notes in US AWS, audio never stored.

**Otter.ai** — Visible **bot** ("Otter Notetaker") on Zoom/Meet/Teams + local mic for in-person. Live real-time transcript, summary with decisions + auto-assigned action items, "My Action Items," AI Chat. Differentiator: live transcription + education/enterprise governance. Cloud-only (AWS), SOC 2 Type II + HIPAA, **one-click filler cleanup**. May train on your data depending on plan. Hit with a 2025 consent class action.

**Fireflies.ai** — Visible **bot** + mobile/upload capture. Transcript with speaker labels, NLP summaries/action items, Soundbites, Topic Trackers, AskFred chat across the whole workspace. Differentiator: **CRM sync + conversation intelligence + cross-meeting search**. Cloud-only, SOC 2 Type II/GDPR/HIPAA, optional bring-your-own-storage (still their cloud). Primarily post-meeting/batch. Sued under Illinois BIPA over voiceprints.

**Zoom AI Companion** — **Platform-native**, no bot. Meeting Summary works off live speech-to-text without recording; Smart Recording (needs cloud recording) adds highlights, smart chapters, next steps. Differentiator: **bundled free** with paid Zoom. Uses a **federated LLM committee** (Zoom's own + Claude/Gemini/GPT). No training on customer content; data-residency deployment tiers. Meeting Coach even treats filler words as a *coaching metric*.

**Microsoft Copilot in Teams** — **Platform-native**, no bot. Live in-meeting chat/notes need no transcription; post-meeting intelligent recap (notes, **AI recommended tasks**, speaker timeline markers, chapters, audio/video recap) needs transcription or recording on. Differentiator: **deep M365/Graph grounding + enterprise governance** (Purview, eDiscovery, EU Data Boundary). Azure OpenAI inside the M365 service boundary; no training on customer data. Requires Teams Premium / Copilot license.

**Fathom** — **Bot or bot-free desktop** capture. Near-instant post-call summaries, action items with assignee attribution, live Highlights, 17 templates, "Ask Fathom" across all meetings. Differentiator: **generous free tier + summary speed**. Cloud (AWS US/Canada), SOC 2 Type II/HIPAA/GDPR, LLMs Anthropic+OpenAI+Google (no training). Keeps filler words.

**tl;dv** — **Bot or botless desktop**. Recording, translatable transcript, timestamped highlights + shareable clip "Reels," **multi-meeting AI reports**, CRM push. Differentiator: **30+ language depth + sales coaching + clips**. Cloud, **EU-hosted**, SOC 2 Type II/GDPR/ISO 27001, **Anthropic-only** LLM, privacy-engineered (anonymized metadata, meetings chunked in randomized order so the LLM provider can't reconstruct them). Whisper Large for ASR; keeps filler words.

**Supernormal** — Bot-optional (bot only when platform requires video). Live transcription, template-driven structured notes, action items, plus downstream AI work-products (emails, slides, docs). Cloud (AWS), SOC 2.

**Fellow** — Bot / botless desktop / Zoom native / mobile. **Meeting-management lifecycle**: shared agendas + talking points → recap → auto-assigned action items synced to task lists, "Ask Fellow." Differentiator: governance-heavy, **Zero-Day Retention** (deletes recordings/transcripts after processing, keeps only summaries/decisions/actions). Cloud (AWS Canada), SOC 2 Type II/GDPR/HIPAA, never trains on your data.

**Local-first standouts** — **Hyprnote** (YC S25, now continued as *anarlog*): fully on-device, no bot, captures mic + system audio, **Whisper** for ASR + **HyprLLM** (Qwen3-1.7B fine-tune) via **llama.cpp**, GGUF models, **GPU-first with CPU fallback**, GBNF grammars to constrain output to markdown/JSON, optional bring-your-own Ollama/cloud LLM. **Meetily** (MIT, self-hosted, system-audio capture, Whisper). **MacWhisper** (local Whisper + speaker ID). **Superwhisper**, **Vibe** (offline Whisper).

## Table Stakes vs Differentiators

### Table stakes (every serious product has these)
- **Transcript** with timestamps.
- **Speaker diarization** — who-said-what. Universal among the bot/platform tools (Otter, Fireflies, Zoom, Teams, Fathom, tl;dv, Fellow). **Exception: Granola does NOT do true diarization on desktop** — only "Me" (mic) vs "Them" (system audio) channel split, because it doesn't process per-speaker. So diarization is table-stakes for *bot* tools but Granola proves a beloved product can ship without it.
- **AI summary** (clean, structured).
- **Action-item extraction** — LLM pulls tasks from the transcript post-meeting; the better ones (Otter, Fathom, Fireflies, Fellow) **auto-assign to participants**.
- **Decisions / key topics** surfaced in the summary.
- **"Ask my meetings" chat** — now standard (Ask Fathom, AskFred, Ask Fellow, Otter AI Chat, Zoom/Teams Q&A).
- **Calendar auto-join + integration push** (Slack/CRM/Notion).

### Differentiators (where products actually compete)
- **Capture without a bot** — Granola, Fathom, tl;dv, Fellow, Supernormal, and all local tools now offer botless/desktop capture. The visible-bot-only tools (classic Otter/Fireflies) look dated.
- **The notes model** — Granola's "augment your own notes" vs everyone else's "auto-summarize the whole transcript." This is *the* loved differentiator: output reflects *your* priorities.
- **Custom templates** per meeting type.
- **Cross-meeting intelligence** — Fireflies Topic Trackers, tl;dv multi-meeting reports, sales coaching.
- **Clips / highlights / Reels** — Fathom, tl;dv.
- **Data residency & governance** — EU hosting (tl;dv), EU Data Boundary (Teams), Zero-Day Retention (Fellow), federated/no-train (Zoom).
- **Where your voice lives afterward** — the only true dividing line: someone's cloud bucket vs your own silicon.

### Specific answers
- **Diarization?** Yes for all bot/platform tools (pyannote-class server-side, or Whisper + speaker-ID layer for tl;dv). **No** for Granola desktop (channel split only). Locally it's the hardest piece — needs WhisperX + pyannote.
- **Filler words — keep or clean?** Mostly **kept verbatim**. **Otter** has explicit one-click filler cleanup; **Zoom** detects fillers but exposes them as a coaching metric (doesn't strip from notes); Fathom and tl;dv keep them (removal "in development" at tl;dv). The LLM summary pass is where fillers effectively disappear, even when the raw transcript retains them.
- **Live vs batch?** Split. **Live transcription**: Otter, Granola, Supernormal, Zoom Meeting Summary, Teams in-meeting Copilot, local tools (Hyprnote). **Post-meeting batch** for the heavy lifting (summary, action items, chapters, diarized recap) across essentially all of them. The pattern: live transcript streaming + batch LLM enrichment at meeting end.
- **Action-item / decision extraction?** Uniformly an **LLM pass over the cleaned, diarized transcript** post-meeting. Best-in-class adds **assignee attribution**.

## What a privacy-first LOCAL clone most needs to match (ranked)

1. **Botless local capture of system audio + mic** — table stakes, natural fit for local. Granola/Hyprnote prove no-bot is a *feature*.
2. **Live local transcription** — Whisper on the RTX 4080. faster-whisper (CTranslate2) default, or WhisperX for batched throughput.
3. **Local LLM summary + action-item extraction** — the genuine table stake. Quantized model via llama.cpp/Ollama, output constrained with GBNF grammars (Hyprnote's trick). Auto-assign if you have speaker labels.
4. **Speaker diarization** — hardest local piece. WhisperX + pyannote.audio gives word-level timestamps + who-said-what offline on GPU. Granola shows you can ship with just mic-vs-system channel split as a stopgap.
5. **The "augment your own notes" model** — strongest differentiation opportunity; *why Granola is loved*, and cheaper to do well locally than full diarized auto-summary.
6. **Custom templates** per meeting type — low-cost, high-perceived-value prompt scaffolding.
7. **Decisions + key-topic surfacing** and **"ask my past meetings" chat** — both fall out of transcripts + a local LLM + a small local vector index.

**Reference patterns worth stealing:** Hyprnote's GPU-first / CPU-fallback inference (mirrors our turbo-GPU → qwen-CPU fallback exactly), GBNF-grammar-constrained LLM output, and Fellow's Zero-Day Retention privacy posture — though locally we can simply *keep everything on disk*, which beats every cloud retention promise.

The canonical local pipeline the whole local-first cohort converges on:
**system+mic audio → faster-whisper/whisper.cpp → WhisperX align + pyannote diarize → local LLM (llama.cpp/Ollama) for summary + action items**, GPU-accelerated throughout.

> Unverified: Granola's exact filler-word handling has no primary source — treat as unconfirmed if load-bearing.
