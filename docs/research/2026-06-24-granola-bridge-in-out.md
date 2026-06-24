# Granola, in and out: vocab-in, sovereign-notes-out

*2026-06-24. Companion to [the Granola deep-dive](2026-06-23-granola-deep-dive.md).
Trigger: a team lead asked us to record ad-hoc Agent Studio conversations in
Granola and drop them in the shared GenAI folder so knowledge isn't lost. That
raises the obvious question for our own tool — can TuParles leverage Granola in
both directions? Yes, asymmetrically.*

## IN — Granola transcripts as a dict-seed context source (#54 / #71 / #117)

The morning's forensics ([real-take error taxonomy](2026-06-24-real-take-error-taxonomy.md))
showed the decoder dies on rare proper nouns and domain jargon **when there's no
context to attach to** (greenfield). The team's Granola folder is a corpus *full*
of exactly that vocabulary: product names ("Agent Studio"), feature names,
colleague names, recurring jargon.

So the bridge: **pull the team's meeting transcripts → mine entities/technical
tokens (we already do this in `vocab.suggest`) → feed the dict-seed bias (#68).**
TuParles learns to spell the team's vocabulary right *because the meetings taught
it.* This is:
- a new **live-context source for #71** (alongside active project / clipboard);
- the literal **"warm" personal prior of #117** (your own corpus, TF-IDF'd
  against general French to surface what's distinctively yours);
- and it closes the loop on the greenfield problem with the one corpus that
  always has the right words: your own conversations.

**Do it via the local cache, not the cloud API.** The community offline path
(`cache-v3.json`, read directly — no key, no round-trip) keeps the local-first
story intact: we mine vocabulary on-device, nothing leaves the box. The REST API
is the fallback when the cache isn't present.

## OUT — roundtable mode as the *sovereign* note-taker (#108 / #38)

One honest constraint discovered in the deep-dive: **Granola's API is read-only**
(`GET /notes`, `GET /notes/{id}`) — there is no note-*create* endpoint. So "out"
is **not** "write into the GenAI folder programmatically." It's:

- TuParles **roundtable mode (#108)** + augment-notes (#38) produce **local,
  diarized, named** meeting notes (markdown, with the magnifying-glass
  traceability borrowed from Granola), then emit them to the team's destinations
  (the folder, Slack, Notion) — by export, not by Granola write-back.
- And we **beat** Granola on the part they punt: desktop diarization is only
  "Me/Them" for them; our dual-channel capture (#36) + pyannote (#39) gives real
  per-speaker labels. For sensitive Agent Studio internals, TuParles is the
  sovereign alternative — fully on-device, EU-friendly, no sub-processors.

## The privacy flag (raise it kindly)

Recording internal Agent Studio convos in Granola means: audio → **US-cloud +
Deepgram/AssemblyAI sub-processors**, storage US-only AWS, and self-training is
**opt-out, not opt-in** on Business. Responsible guidance for the team:
1. confirm the **workspace training opt-out** is set;
2. keep genuinely-unreleased details to a local path;
3. folder/sharing access follows Granola permissions — not everyone with the
   link, but do check before assuming privacy.

This isn't anti-Granola; it's the exact sovereignty-for-convenience trade our
research says the market keeps voting for.

## Team enablement — 3 links + tips (shared in the thread)

1. **Official Granola MCP** — <https://www.granola.ai/blog/granola-mcp> — connect
   Claude/Cursor/ChatGPT to *ask* the meetings. First-party, respects folder
   permissions. *Business tier; add `mcp.granola.ai/mcp` in your MCP client.*
2. **Granola REST API** — <https://docs.granola.ai/introduction> — automation
   (folder digests, action-item bots). *Per-user `grn_` key, **read-only**, **no
   webhooks** (poll); only notes that already have summary+transcript.*
3. **Community power tools** (offline / agent-first):
   - [pedramamini/GranolaMCP](https://github.com/pedramamini/GranolaMCP) — reads
     the **local cache** (no key, offline) via CLI + MCP.
   - [joelhooks/granola-cli](https://github.com/joelhooks/granola-cli) —
     agent-first CLI, structured JSON.
   - [mishkinf/granola-mcp](https://github.com/mishkinf/granola-mcp) — **semantic
     search** across notes (local LanceDB).

## Backlog seeded
- **Granola bridge (#71/#117 IN):** ingest the meeting corpus (local cache first)
  as a dict-seed context source → entity/jargon mining → bias feed. Blocked on
  the #117 prior and #69 harness (measure the vocab lift before trusting it).
- **Roundtable export (#108/#38 OUT):** markdown notes → team destinations; not a
  Granola write-back (their API is read-only).

> *Tikoro nko agyina* — "one head does not hold a council" (Akan, echoing the
> deep-dive). The team's council already lives in Granola; we can let TuParles
> *listen* to it (learn the vocabulary) and, when the room is sensitive, *hold*
> it ourselves (sovereign notes) — in our own house.
