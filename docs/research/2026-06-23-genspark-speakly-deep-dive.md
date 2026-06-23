# Genspark Speakly, up close: the cloud dictation foil

*Captured 2026-06-23, after friends praised it. Verbatim-quotable, sources
inline. This is the dictation-side companion to the [Granola deep-dive](2026-06-23-granola-deep-dive.md):
Granola is the meeting-notes leader, **Speakly is the dictation leader — and
the architectural opposite of TuParles.** Where TuParles keeps the voice on the
machine, Speakly sends it to the cloud and an undisclosed transcriber.*

> **The through-line.** Speakly is a cloud-credit-metered dictation layer whose
> real moat is **Agent Mode** (double-tap → hand the cleaned voice prompt to
> Genspark's agent stack). Its "Your voice stays private" billboard means
> *not-sold / encrypted-in-transit*, **not** *on-device*. The lanes its funding
> can't follow into — **local, Linux, FR-EN code-switching** — are exactly where
> TuParles already stands.

> **Sourcing caveat.** `speakly.ai` and `genspark.ai` hard-block automated fetch
> (HTTP 403), so primary claims come from search snippets of those pages + app
> store listings + dated reviews that quote the marketing. Flagged inline. The
> complaint corpus is **genuinely thin** (launched Jan 2026; one detailed review
> blog + a ~13-rating App Store page) — Speakly-specific "recurring" means
> recurring-within-a-tiny-sample; the rich signal is category-wide.

---

## 0. Identity & scale

- **"AI voice dictation app, 4x faster than typing."** Press-hotkey → speak →
  text appears at the cursor in any app. Launched **2026-01-28** as part of
  Genspark "AI Workspace 2.0." ([speakly.ai](https://speakly.ai/),
  [BusinessWire](https://www.businesswire.com/news/home/20260128322682/en/))
- **Built, not acquired**, by **Genspark Inc. / MainFunc Inc.** (Palo Alto +
  Singapore, founded 2023; CEO Eric Jing ex-Baidu/Bing, CTO Kay Zhu ex-Baidu/Google).
  Speakly is a **system-wide voice front-end to Genspark's agent stack.**
  ([TechCrunch](https://techcrunch.com/2024/06/18/genspark-is-the-latest-attempt-at-an-ai-powered-search-engine/))
- **Parent scale:** Genspark crossed **$100M ARR in ~9 months**, **Series B
  extended to ~$485M at a $2.6B valuation (Jun 2026)**. ARR arc $10M→$36M→$100M
  (Jan 2026)→~$250M (Apr 2026). ~2M MAU, ~100k paying seats.
  ([finsmes](https://www.finsmes.com/2026/06/genspark-ai-extends-series-b-to-485m-at-2-6-billion-valuation.html),
  [Axios](https://www.axios.com/pro/enterprise-software-deals/2026/01/21/genspark-funding-100-million-arr-genai))

---

## 1. The feature surface

### Core gesture & text injection
- Tap/hold a global hotkey, speak, release → text at the cursor, *"no
  copy-pasting, no switching windows."* Default hotkey is version-dependent
  (reviews cite Right Alt **and** Option+Space; customizable).
- **Injects via accessibility permissions** (Mac needs Accessibility + Mic). If
  insertion fails, *"Speakly will automatically show a popup with the transcribed
  text so you can copy and paste manually."* (type-via-API primary, paste-popup
  fallback — mirror image of TuParles' paste-primary policy.)
- "100+ apps" (Slack, Gmail, Notion, VSCode, …). Speed claim "4× typing" is
  unbenchmarked. ([Scribe guide](https://scribehow.com/page/Genspark_Speakly_Complete_Feature_Guide_Voice_Commands_Live_Translation_and_AI_Agent_Mode__s0v4sq3UQIaChKpYiit7Qg),
  [kuronyankotan](https://kuronyankotan.com/en/genspark-speakly-review/))

### AI auto-editing (the cleanup pass)
- *"Automatically removes filler words ('um,' 'uh,' 'like')… fixes errors,
  corrects punctuation."* Restructures *"messy spoken language"* into
  *"readable business documents."* Smart formatting auto-builds emails/lists.
- Aggressiveness is controlled via **Modes** (below), not a clear global on/off.
  **No source confirms a raw-transcription / disable-editing toggle, nor whether
  editing ever changes meaning** — the sharpest contrast to test against a
  conservative local tool. ([App Store](https://apps.apple.com/us/app/speakly-ai-voice-keyboard/id6759094391),
  [note/kazu](https://note.com/kazu_t/n/n3e1b3d3711ab?hl=en))

### Modes & vocabulary
- Built-in templates: **Translation, Terminal Helper (speech→runnable commands),
  Professional Rewrite/Proofread, Workplace/Business, Chaos (emoji+memes),
  Buzzword.** Plus user-defined custom instructions.
- **Selection + voice editing:** highlight text, hold key, say *"make this more
  concise"* / *"translate this to Japanese"* → edits in place.
- **Custom Dictionary** for proper nouns/jargon; mobile v1.2.0 added "smarter
  autocorrect." Voice shortcuts for instant actions.

### Languages & translation
- **"100+ languages"** (marketing rose from 50+ since launch). Real-time
  translation across them; **code-switching** *"mix languages mid-sentence, with
  automatic detection and zero configuration."* ([speakly.ai](https://speakly.ai/))

### Agent Mode (the headline differentiator)
- **Double-tap the shortcut** = Agent Mode (vs single-tap dictation) — that's the
  dictation-vs-command disambiguation. A pop-up search window appears.
- Mechanism: passes the cleaned voice as *"a high-quality AI prompt"* to Genspark,
  which executes — *"build slide decks, draft emails, research topics, create
  spreadsheets."*
- **Known rough edge:** Agent Mode *"opens a new browser tab and Genspark launches
  there"* — it hands off to the web app rather than acting in place.
  ([note/kazu](https://note.com/kazu_t/n/n3e1b3d3711ab?hl=en))

### Platforms & pricing
- **macOS, Windows, iOS, Android, Chrome extension. No Linux.**
- **Bundled into Genspark's credit system**, not separately priced: Free ~200
  credits/day · Plus $24.99/mo · Pro $249.99/mo. **Agent Mode + AI correction
  consume credits** even during the 7-day unlimited trial. (A circulating "$9.99
  Speakly Pro" is the unrelated indie app or stale.)

---

## 2. The privacy story — the whole point of the comparison

**Verdict: cloud-only, no offline mode, audio leaves the machine.**

- *"Speakly does speech recognition and text-polishing in the cloud; a network
  connection is required and offline use is not supported."* (help center, via
  search) Independent review confirms: *"Superwhisper is Local/Offline; Speakly
  is Cloud/Agent-based… requires internet."* ([kuronyankotan](https://kuronyankotan.com/en/genspark-speakly-review/))
- Privacy policy: voice features **transmit recordings off-device to third-party
  "audio processing providers."** Stored data on **Microsoft Azure (US default).**
- **⚠️ Which STT engine actually hears your voice is UNDISCLOSED.** No source —
  primary or secondary — names it (not Whisper, Deepgram, AssemblyAI, nor a stated
  Genspark model). Named AI providers generally: OpenAI, Anthropic, Google, xAI,
  ElevenLabs. This is the single biggest undisclosed fact.
- **⚠️ Marketing-vs-reality:** "Your voice stays private. We never store or sell
  what you say" reads as *local* to a normal user. It is **not** — it means
  *not-sold / not-permanently-retained / encrypted-in-transit.* The App Store
  privacy label doesn't even declare audio as collected, despite voice being the
  core function.
- **Consumer data trains models BY DEFAULT** (manual opt-out). The strong
  guarantees — Zero Data Retention, Zero Training, SOC 2 Type II, claimed ISO
  27001 — are **scoped to enterprise/DPA customers.** Transcripts are retained and
  user-visible; no numeric retention period published. **No HIPAA / BAA.**
  ([LayerX](https://layerxsecurity.com/generative-ai/genspark-risks-and-vulnerabilities/),
  [genspark.ai/business](https://www.genspark.ai/business))
- No confirmed breach. Billing complaints cluster on Trustpilot (~2.5/5:
  auto-renewal, credits charged on failed outputs). LayerX flags fragmented
  multi-domain policies and an AI-browser that blocked only 7% of phishing tests.

### Developer surface
- **No public Speakly API, webhooks, SDK, or MCP server.** It's an input client,
  not an invocable service. **Contrast: Spokenly ships an MCP "Voice for Agents"
  story** ([spokenly.app/docs/macos/voice-for-agents](https://spokenly.app/docs/macos/voice-for-agents))
  — an angle Speakly lacks and **TuParles can own** (decision: build the MCP server).
- Genspark itself *consumes* MCP (an "MCP Store," 700+ tools) — it's an MCP host,
  not a server others call. Speakly feeds voice *into* that host.

---

## 3. What users complain about / wish for

*Thin Speakly-specific corpus; flagged.*

**Speakly-specific** (one reviewer / ~13 App Store ratings):
- **Hotkey misses + freezes** — *"I press the Right Alt key… nothing happens. I
  have to press it 2 or 3 times… Occasionally it freezes."* (verdict: "for early
  adopters"). TuParles has fought exactly this class of bug (stuck modifiers,
  GUI-stall watchdog) — a parity-and-beyond opening.
- **iOS: can't STOP dictation** — *"I can start dictation… but I can't end it."*
- **Mobile keyboard-switching trap** — no button to revert to stock keyboard
  (recurring across both stores).
- **Cumbersome mic switching (desktop)** — buried in Settings (TuParles shipped
  named-mic selection in #40 — already ahead here).
- **Less stable/accurate than Aqua Voice** — *"stick with Aqua for now."* (No
  public Speakly WER exists; "less accurate" is inferred.)
- *Architecturally-plausible-but-UNSUBSTANTIATED:* meaning-distorting auto-edits,
  agent-mode misfires, dictation-vs-command misrouting. No public reports yet.

**The "Aqua Voice killer" framing is aspirational hype** — concentrated on the
Speakly↔Aqua axis, mostly Japanese-language launch-window posts; same reviewers
conclude Aqua is *"rock-solid in comparison."*

**Category-wide (the well-evidenced demand):**
1. **Offline / local-only processing — the loudest unmet ask.** ("Local inference
   only is an absolute requirement." — Aqua HN thread.) **This is TuParles'
   architecture.**
2. Automatic (not manual-CSV) custom vocabulary. 3. Android. 4. **Linux.**
   5. Cross-device sync. 6. Voice editing that *executes* vs types literally.
   7. A genuine free tier without weekly word caps.

**Category gripes with peer-reviewed backing** (directly relevant to the cleanup
decision): **hallucination** — *"Careless Whisper"* (ACM FAccT) found ~1% of
segments fabricated, **38% with explicit harm**; medical tools invented a fake
drug. **Hallucination on silence/pauses.** **Over-correction changing meaning**
("denied suicidal ideation" ≠ "said they were not thinking about suicide").
**Accent WER** can exceed 50% in the wild. **Code-switching breaks most ASR** —
and is itself a hallucination trigger.
([Careless Whisper](https://arxiv.org/html/2402.08021v2),
[science.org](https://www.science.org/content/article/ai-transcription-tools-hallucinate-too),
[gladia](https://www.gladia.io/blog/what-is-code-switching-in-speech-recognition))

---

## 4. The landscape: cloud vs local (dictation)

| Tool | Platform | Local/Cloud | Offline | Notable |
|---|---|---|---|---|
| **Genspark Speakly** | Mac/Win/iOS/Android, **no Linux** | **Cloud only** | **No** | Agent Mode → Genspark agents; undisclosed STT; train-by-default |
| **Wispr Flow** | Mac/Win/iOS/Android, no Linux | **Cloud only** | No | Command Mode; ~$2B valuation talks; screenshot-upload privacy saga |
| **Aqua Voice** | Web/Mac/iOS | **Cloud only** | No | "Avalon" model for coding; Privacy Mode OFF by default; stable |
| **superwhisper** | Mac/Win/iOS, **no Linux** | **Local** (Apple Silicon) | Yes | Genuine on-device mode |
| **Spokenly** | Mac/iOS, **no Linux** | **Local** + BYOK | Yes | "Local Only Mode"; **MCP voice-for-agents** |
| **MacWhisper / VoiceInk** | macOS only | **Local** | Yes | Never phones home; VoiceInk is OSS |
| **Handy / Whispering / OpenWhispr** | Mac/Win/**Linux** | **Local** OSS | Yes | The only Linux options — and "run poorly, if at all" on Linux/Wayland |
| **TuParles** | **Linux (X11+Wayland)** | **Local** (RTX GPU) | Yes | FR-EN code-switch focus; audio never leaves the box |

**The pattern:** every *funded, polished* product is cloud-only or
Apple-Silicon-only. **Linux is served only by rough open-source.** Nobody ships
*polished, FR-EN-tuned, local, Linux-first.* That intersection is empty.

---

## 5. What this means for TuParles — decisions taken (2026-06-23)

Informed by this brief, via a structured decision pass:

1. **Nail the dictation core first** (Sprint 4), meeting-notes (#35-39) sequenced
   after. The friends-praised competitor is a dictation tool; this is our turf.
2. **AI cleanup pass: opt-in, conservative, LOCAL, 80/20** (spaCy / small local
   models). Default OFF. The hallucination evidence makes "a visible mishear beats
   a confident wrong autocorrect" a *feature and trust posture*, not a gap. (Note:
   revisits the earlier *no-spaCy-ever* stance of #33 — decide deliberately.)
3. **Voice command meta-language (#41): prioritized, un-parked.** The *honest*
   Agent Mode — narrow, deterministic, local: "efface la dernière phrase", "mets
   en bullets", "ouvre un terminal." No cloud round-trip. Not Speakly's slide-deck
   agent (that's their cloud moat / our cage).
4. **Code-switching: validate now (#34), plan the FR-EN fine-tune as long-term.**
   It's both the moat and Whisper's documented weak spot (turbo ranked worst).
5. **Build an MCP "voice for agents" server** — let Claude Code/Cursor request
   local dictation. Spokenly does it, Speakly doesn't; fits our own workflow,
   stays fully local.
6. **Full modes/templates system** (translate / professional / terminal / casual)
   — Speakly's modes are genuinely useful; terminal-command mode especially.
7. **Selection-aware voice editing: later**, after the cleanup-pass machinery
   exists (shared local-model plumbing).
8. **Blog series (#42): draft the spine now, publish later** — *local, Linux,
   bilingual: the three lanes the funded players left empty.* Store blog-worthy
   notes in `docs/research/` as we build (the standing convention).

> *Ndànk ndànk mooy japp golo ci ñaay* — "gently, gently catches the monkey in
> the bush" (Wolof). The incumbents sprint toward the cloud-agent canopy; we walk
> the forest floor they abandoned — local, Linux, bilingual.

---

## Sources

**Primary (403 to fetch; via search snippets + app stores):**
[speakly.ai](https://speakly.ai/) ·
[genspark help: speakly](https://www.genspark.ai/helpcenter/speakly) ·
[genspark privacy](https://www.genspark.ai/privacy) ·
[enterprise data policy](https://www.genspark.ai/policies/enterprise-clients-data-security-and-privacy-policy) ·
[genspark business](https://www.genspark.ai/business) ·
[iOS App Store](https://apps.apple.com/us/app/speakly-ai-voice-keyboard/id6759094391) ·
[Google Play](https://play.google.com/store/apps/details?id=ai.mainfunc.speakly) ·
[OpenAI x Genspark](https://openai.com/index/genspark/)

**Dated coverage / funding:**
[BusinessWire launch](https://www.businesswire.com/news/home/20260128322682/en/) ·
[Yahoo: Workspace 2.0 + $100M ARR](https://finance.yahoo.com/news/genspark-launches-ai-workspace-2-150000379.html) ·
[finsmes: Series B → $485M @ $2.6B](https://www.finsmes.com/2026/06/genspark-ai-extends-series-b-to-485m-at-2-6-billion-valuation.html) ·
[Axios: $100M ARR](https://www.axios.com/pro/enterprise-software-deals/2026/01/21/genspark-funding-100-million-arr-genai) ·
[TechCrunch origin](https://techcrunch.com/2024/06/18/genspark-is-the-latest-attempt-at-an-ai-powered-search-engine/)

**Reviews / feature guides:**
[kuronyankotan review ("Aqua killer?")](https://kuronyankotan.com/en/genspark-speakly-review/) ·
[note/kazu (install, credits, modes)](https://note.com/kazu_t/n/n3e1b3d3711ab?hl=en) ·
[note/yoshimasa (Agent Mode)](https://note.com/yoshimasa__/n/n9b7031a4021e?hl=en) ·
[Scribe feature guide](https://scribehow.com/page/Genspark_Speakly_Complete_Feature_Guide_Voice_Commands_Live_Translation_and_AI_Agent_Mode__s0v4sq3UQIaChKpYiit7Qg) ·
[whytryai](https://www.whytryai.com/p/new-genspark-features)

**Security / privacy:**
[LayerX risks](https://layerxsecurity.com/generative-ai/genspark-risks-and-vulnerabilities/) ·
[VerifyWise trust index](https://verifywise.ai/ai-trust-index/genspark) ·
[Trustpilot](https://www.trustpilot.com/review/genspark.ai)

**Competitors / landscape:**
[Spokenly](https://spokenly.app/) ·
[Spokenly: voice-for-agents (MCP)](https://spokenly.app/docs/macos/voice-for-agents) ·
[superwhisper](https://superwhisper.com/) ·
[Aqua Voice](https://aquavoice.com/) ·
[Wispr Flow pricing](https://wisprflow.ai/pricing) ·
[Wispr privacy incident](https://modelpiper.com/blog/wispr-flow-privacy-incident) ·
[Handy (Linux OSS)](https://github.com/cjpais/Handy) ·
[VoiceInk (OSS)](https://github.com/beingpax/VoiceInk) ·
[Whispering (Mac/Win/Linux)](https://github.com/braden-w/whispering)

**Category evidence (hallucination / code-switch):**
[Careless Whisper (FAccT)](https://arxiv.org/html/2402.08021v2) ·
[science.org: ASR hallucinates](https://www.science.org/content/article/ai-transcription-tools-hallucinate-too) ·
[ServiceNow code-switch benchmark](https://huggingface.co/blog/ServiceNow-AI/code-switching) ·
[gladia: code-switching](https://www.gladia.io/blog/what-is-code-switching-in-speech-recognition) ·
[Open ASR Leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard) ·
[HN: Whispering local-first (591 pts)](https://news.ycombinator.com/item?id=44942731)
</content>
