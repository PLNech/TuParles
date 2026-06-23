# Granola, up close: a competitive deep-dive

*Captured 2026-06-23, from inside an actual Granola call (Algolia), then widened
by web research. Verbatim-quotable, sources inline. This is the close-range
companion to [the commercial landscape brief](2026-06-23-meeting-notes-commercial-landscape.md):
that one maps the field, this one studies the leader.*

> **The through-line.** Granola's whole moat is one sentence: *botless local
> capture, no stored audio, AI-augmented notes.* Every limitation users complain
> about is the shadow of that same design choice — and almost every one is a place
> a **fully-local, Linux-first** tool can stand where Granola architecturally
> cannot follow. The market keeps asking for exactly what their architecture forbids.

---

## 0. Identity & scale

- **"The AI Notepad for back-to-back meetings"** — *"Notes, actions and memory.
  Without a meeting bot."* Desktop-first (macOS/Windows) + iPhone. Transcribes via
  **your computer's audio** (no meeting bot), then enhances the rough notes *you*
  type, using the transcript + calendar context. ([granola.ai](https://www.granola.ai/))
- **Founded March 2023, London UK** (a non-SV outlier; now a UK unicorn).
  Co-founders Chris Pedregal (CEO, ex-Google PM, founded Socratic→acquired by Google)
  + Sam Stephenson. Product launched 2024-05-22.
  ([businesscloud](https://businesscloud.co.uk/news/granola-founded-in-2023-becomes-latest-uk-unicorn/))
- **Funding, ~$192M total:** Seed $4.25M (May 2023, Lightspeed) → Series A $20M
  (Oct 2024, Spark; angels Nat Friedman + Daniel Gross) → Series B $43M @ $250M
  (May 2025, NFDG) → **Series C $125M @ $1.5B (2026-03-25**, Index + Kleiner Perkins).
  6× valuation in under a year.
  ([TechCrunch 2026-03-25](https://techcrunch.com/2026/03/25/granola-raises-125m-hits-1-5b-valuation-as-it-expands-from-meeting-notetaker-to-enterprise-ai-app/))
- **Strategic pivot:** from prosumer notepad → **enterprise "AI context layer"** —
  the central store of a team's meeting data, exposed via API + MCP. Named enterprise
  customers (2026): Vanta, Gusto, Thumbtack, Asana, Cursor, Lovable, Decagon, Mistral AI.
  Headcount ~116 (Latka, approximate). ARR not disclosed.

---

## 1. The feature surface (what they boast about)

### The defining trick — "augment my notes"
The moat isn't transcription, it's the **three-input synthesis**: notes are built from
*"The transcription captured during the meeting, Any 'raw' notes you took, Information
from the calendar event."* ([docs](https://docs.granola.ai/help-center/taking-notes/ai-enhanced-notes))
- *"Write down as much or as little as you like — Granola uses meeting context to write
  clear notes, personal to you."* ([granola.ai](https://www.granola.ai/))
- **Your text is preserved and distinguished**: raw notes shown in black, AI content
  distinguished.
- **Traceable provenance**: a magnifying-glass tool lets you *"investigate your enhanced
  notes to see why Granola wrote a certain point,"* tracing each line back to transcript
  or raw notes. ← *This is the single feature most worth borrowing for #38.*

### Transcription
- **Bot-free, system-audio capture** — *"Uses your computer audio, so doesn't invite a
  bot."* Captures mic + system audio in the background. Audio only, not video.
- **Real-time on desktop, batch on iOS** (iOS transcribes after the meeting from
  temporarily-cached audio).
- **No audio retention** — *"It does not record or save audio or video at any point during
  the call."* ([docs](https://docs.granola.ai/help-center/taking-notes/transcription))
- **Transcription vendors: Deepgram + AssemblyAI** (cloud sub-processors).

### Speaker handling — a known weak spot
- **Desktop = binary only:** *"you'll see 'Me' and 'Them'... which correspond to your
  microphone input and your system audio."* No live diarization: *"the models don't yet
  support live diarization."*
- **Per-speaker diarization is iPhone-only**, for face-to-face meetings.
- → **At 3+ participants the labels break.** *"Every action item is unowned... statements
  are orphaned."* Finance users report it "messes up numbers."

### Multi-language + translation
- **Desktop: 10 languages** (EN, FR, DE, ES, IT, PT, NL, JA, RU, HI); iPhone adds 7 more.
- **Summary-language toggle** ("Always English" vs Auto) — the closest thing to the
  "view all in EN/FR" experience: a *summary*-language setting, **not** live transcript
  re-rendering.
- **Translation is quote-level, not whole-doc:** *"you can't translate old transcripts,
  although you can ask the chat... to generate translations of quotes."*
- **Custom vocabulary doesn't work in multi-language mode** — you choose specialist
  English terms OR multilingual handling, not both. (Confirmed in their own docs.)

### Granola Chat — "ask your meetings" / cross-meeting memory
- Shipped with **Granola 2.0 (2025-05-14)**; agentic rebuild 2026-04-21.
- Four query scopes: all meetings / one meeting / folder / selected meetings.
- *"Why are we losing deals this quarter?"* — "a year of pitches becomes a queryable dataset."
- **Inline citations** with jump-to-source on every answer.
- Underlying LLMs: multi-provider with an Auto router (Standard vs Thinking tiers).
  Point-in-time early-2026 snapshot (drifts): single-meeting→GPT-5.1, multi→Claude 4 Sonnet,
  Fable 5 as an Enterprise-only Thinking model.

### Export — a friction point (and an opening)
- **No first-class file export.** Primary path is copy/paste; a teardown found no native
  PDF/Markdown/DOCX/JSON export. (Granola docs do mention CSV + a GDPR data request, so
  "no export *at all*" is overstated — but the friction is real and widely felt.)
- The **sanctioned LLM-context path is MCP**, not file export (server launched 2026-02-04;
  `https://mcp.granola.ai/mcp`; connects Claude/ChatGPT/Cursor).
- A **cottage industry of workarounds** proves the gap: Raycast extension, 4+ Obsidian-sync
  plugins, a reverse-engineered local-cache pull, granolatasks.com polling action items into
  Todoist/Linear. Third-party products filling a first-party gap = strong demand signal.

---

## 2. Developer platform

- **Public REST API, launched early 2026.** Base `https://public-api.granola.ai/v1`;
  `GET /notes` + `GET /notes/{id}` (`include=transcript`). Per-user Bearer keys (`grn_...`),
  created in-app. Rate limits 25 req/5s burst, 5 req/s sustained. Only returns notes that
  already have a summary + transcript. ([docs](https://docs.granola.ai/introduction))
- **Two tiers:** Personal API (Business+) and Enterprise API (admin/team context).
- **No webhooks** — *"Not yet. You need to poll the API... Webhooks are on our roadmap."*
- **No official SDK, no public dev portal.** But a thriving community MCP ecosystem reads
  the local `cache-v3.json` directly (offline, no key).
- The API partly answered **developer backlash** after Granola locked down its local cache
  and broke on-device agent workflows.

### Integrations (official vs Zapier-only)
- **Official native:** Google/Outlook calendar, Slack, Notion, HubSpot/Attio/Affinity (CRMs),
  Zapier, MCP.
- **Zapier-only (NOT native):** Salesforce, Pipedrive, Linear, Jira, Asana, ClickUp.
- **Key architectural fact:** Zoom/Meet/Teams/Webex are **audio sources, not integrations**
  (OS-layer capture, no bot). All outbound integrations are one-way "share a note" — **no
  two-way sync**; notes flow out, nothing comes back.

---

## 3. The privacy story — and where the varnish is thin

This is the crux for a local-first competitor. Granola's marketing leans "local-first," but:

- **⚠️ Transcription is cloud, not on-device.** Audio is captured locally, **streamed to
  Deepgram/AssemblyAI**, transcribed, then deleted. What stays local is the *notes cache*,
  not the audio pipeline. Two independent research passes flagged this same gap.
  ([security FAQ](https://docs.granola.ai/help-center/consent-security-privacy/security-privacy-data-faqs))
- **Storage: AWS, US region, in a VPC. No EU/UK/regional residency** *"at this time."*
  ([granola.ai/security](https://www.granola.ai/security))
- **LLM processing ships to OpenAI/Anthropic** (third parties contractually barred from
  training on your data — but Granola's *own* pipeline does).
- **Self-training is opt-OUT, not opt-in** for Free/Business: *"We only use De-Identified
  Data to train AI models, which you can opt-out of."* Off by default only for Enterprise.
- **Consent is left to the user** — *"You are responsible for obtaining consent."* Automatic
  consent messaging is narrow: Zoom-on-macOS only, **paused for Google Meet**, absent on iPhone.
  This is the weakest part of the privacy story.
- **Compliance:** SOC 2 Type II (2025-07-07). GDPR/UK GDPR with DPA + SCCs. **NOT HIPAA
  compliant — will not sign BAAs.** No ISO 27001, no FERPA.
- **Two real, disclosed security incidents:** a hardcoded AssemblyAI API key in an iOS beta
  (333 testers; PoC pulled 29 transcripts) and a Workspace session-logout flaw (187 users).
  Plus a PromptArmor (Apr 2026) indirect prompt-injection / data-exfil via Markdown images,
  with the **mobile app missing sanitization the desktop app had.**
- **Contested:** an April 2026 "private notes are public by default" story (The Verge /
  TechBuzz). Granola's *current* docs refute it (*"Your notes remain private unless you
  create or enable sharing links"*) — treat as a since-remediated-or-disputed default-setting
  controversy, not necessarily live.

---

## 4. What users and businesses actually complain about

*Signal strength flagged: **recurring** (multi-source) vs one-off. Direct Reddit verbatim was
thin — themes are high-confidence, individual quotes illustrative.*

**Platform & capture**
- **No Android, no Linux; Windows arrived late (June 2025).** *Recurring, universal.* Demand
  proven by a clone ecosystem — including a DEV.to post literally titled *"SaaS Companies Fear
  Me: Cloning Granola for Linux."* Granola told a developer directly they have **no plans** for Linux.
- **No audio/video recording or playback.** *Recurring, top-cited.* Audio is deleted after
  transcription → *"minor transcription errors become permanent and unverifiable."* A "dealbreaker"
  for legal/investor/research use.
- **No file upload** (live-meetings only) → your backlog of recorded calls stays undocumented.
- **Silent capture failures** — on-device capture can break on OS disruption *"and the app
  doesn't always tell you when something has gone wrong."* (Notably the same bug class as
  TuParles' own CUDA-on-suspend — see [[cuda-dies-on-suspend-resume]].)

**Quality**
- **Diarization breaks at 3+ participants** (architectural, §1).
- **Hallucination in summaries** — App Store: *"AI notes are often hallucinating and change
  the meaning."* One turned election small-talk into *"schedule a meeting with the Prime Minister."*

**Commercial / trust**
- **Feb 2026 rebrand backlash** + free-tier gutting (free cut to ~25 lifetime notes / 30-day
  history; jumps to $14/user/mo Business). *"Screw it I'm going to vibe code my own version,
  it's so ugly now and I want my data."* (A circulating "60% dissatisfaction" stat has **no
  primary source** — cite as reported, not fact.)
- **Covert recording / consent legality.** *"Is it weird that it doesn't tell other people
  that it's recording?... a little bit sketchy."* — *"the concealment is a feature, not a bug."*
- **Training on your data + buried opt-out.**

**Unmet feature requests (proven by the hack ecosystem)**
- Export/API (the cottage industry, §1).
- **Interactive action items** (granolatasks.com polls every 30 min to push them into Todoist/Linear).
- CRM auto-population + post-call automation + rep coaching (clearest sales-org loss, to Fireflies).
- Multi-language custom vocabulary; search at scale (softening post-2.0).

**Enterprise blockers**
- **No data residency outside the US** (hard EU blocker).
- **Not HIPAA, won't sign a BAA** (excludes healthcare).
- **Admin/governance thin or gated** — admins can't view a member's history without sharing;
  RBAC/audit logs not advertised. Loses to MS Copilot's inherited M365 compliance + Purview.
- **Vendor lock-in** worry, amplified by export friction + the "central context layer" positioning.

**Pricing (mid-2026, per-user/mo):** Basic $0 (limited history) · Business $14 (unlimited,
integrations, MCP, API) · Enterprise $35 (SSO, admin controls, org-wide auto-delete + training opt-out,
Fable 5). Recording is unlimited on all tiers — the free cap is *history retention*, not recording count.

---

## 5. What this means for TuParles (Sprint 3, #35–#39)

1. **Borrow the augment pattern, not the transcription.** The black-text-yours / AI-distinguished
   hybrid **plus magnifying-glass traceability** back to the transcript is the part worth replicating
   in **#38** — and it's cheap locally, since we already hold the full transcript with word-level
   `avg_logprob`.
2. **Leapfrog them on desktop diarization.** Granola punts (only "Me/Them"; real per-speaker labels
   confined to iPhone). Our **dual-side capture (#36) is the diarization cheat code** — channel-split
   is "nearly perfect" for the local speaker, so true diarization (**#39**, pyannote community-1) is
   only needed on the merged far-end. We'd *beat* the $1.5B incumbent on desktop, not reach parity.
3. **"Local-first" is partly varnish — ours isn't.** Their ASR is cloud Deepgram/AssemblyAI, US-only
   AWS, LLM to OpenAI/Anthropic, training opt-out-not-in. A genuinely on-device TuParles is opt-in
   *by construction* — the differentiator is real and named by their own critics. This is the spine
   of the blog series (**#42**).
4. **Every Granola loss is a design choice the market keeps voting against.** No bot, no stored audio,
   cloud-enhanced, US-only, no Linux. The regulated/NDA/Linux audience is *already self-selecting* into
   exactly the trade we sell: **sovereignty for convenience.** None of the cloud incumbents can follow
   us to Linux or the air-gap without abandoning their architecture.

> *Tikoro nko agyina* — "one head does not hold a council" (Akan). Granola bet on the single human in
> the room; users keep asking for the whole table — and for the table to stay in their own house.

---

## Sources

**Primary (granola.ai / docs):** [home](https://www.granola.ai/) ·
[security](https://www.granola.ai/security) · [pricing](https://www.granola.ai/pricing) ·
[updates](https://www.granola.ai/updates) · [API intro](https://docs.granola.ai/introduction) ·
[transcription](https://docs.granola.ai/help-center/taking-notes/transcription) ·
[AI-enhanced notes](https://docs.granola.ai/help-center/taking-notes/ai-enhanced-notes) ·
[multi-language](https://docs.granola.ai/help-center/customising-granola/multi-language) ·
[chat](https://docs.granola.ai/help-center/getting-more-from-your-notes/chatting-with-your-meetings) ·
[security FAQ](https://docs.granola.ai/help-center/consent-security-privacy/security-privacy-data-faqs) ·
[privacy policy](https://docs.granola.ai/article/privacy-policy) ·
[MCP](https://www.granola.ai/blog/granola-mcp) · [2.0](https://www.granola.ai/blog/two-dot-zero) ·
[SOC2](https://www.granola.ai/updates/granola-is-soc2-type-2-compliant)

**Dated coverage:** [TechCrunch Series C](https://techcrunch.com/2026/03/25/granola-raises-125m-hits-1-5b-valuation-as-it-expands-from-meeting-notetaker-to-enterprise-ai-app/) ·
[TechCrunch Series B](https://techcrunch.com/2025/05/14/ai-note-taking-app-granola-raises-43m-at-250m-valuation-launches-collaborative-features/) ·
[Bloomberg](https://www.bloomberg.com/news/articles/2026-03-25/ai-notetaker-granola-hits-1-5-billion-value-in-125-million-funding) ·
[Sifted](https://sifted.eu/articles/ai-notetaking-startup-granola-hits-unicorn-status) ·
[businesscloud](https://businesscloud.co.uk/news/granola-founded-in-2023-becomes-latest-uk-unicorn/)

**Teardowns / reviews:** [meetingnotes 66/100](https://meetingnotes.com/blog/granola-ai-teardown) ·
[tl;dv](https://tldv.io/blog/granola-review/) · [itsconvo](https://www.itsconvo.com/blog/granola-ai-review) ·
[krisp](https://krisp.ai/blog/granola-ai-review-alternatives/) ·
[App Store reviews](https://apps.apple.com/us/app/granola-ai-meeting-notes/id6739429409)

**Security / privacy:** [PromptArmor](https://www.promptarmor.com/resources/granola-ai-security-risks-and-remediations) ·
[AssemblyAI key (Vulnu)](https://www.vulnu.com/p/hard-coded-api-key-in-ai-note-taking-app-exposed-users-private-meeting-transcripts) ·
[reverse-engineering the cache](https://josephthacker.com/hacking/2025/05/08/reverse-engineering-granola-notes.html) ·
[buildbetter privacy review](https://blog.buildbetter.ai/do-they-own-your-data-granola-ai-privacy-policy-reviewed/)

**Hack ecosystem:** [Raycast](https://www.raycast.com/Rob/granola) ·
[Granola-to-Obsidian](https://github.com/dannymcc/Granola-to-Obsidian) ·
[granolatasks](https://www.granolatasks.com/) ·
[community MCP](https://github.com/chrisguillory/granola-mcp) ·
[clone-for-Linux](https://dev.to/thisisryanswift/saas-companies-fear-me-cloning-granola-for-linux-3pk0)
</content>
</invoke>
