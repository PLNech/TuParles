# Roundtable mode — name-binding, evaluation, and biometric law

*Researched 2026-06-24. Verbatim research brief. The glue + rigor + law angle.*

**Companion to** [`2026-06-23-diarization-sota.md`](2026-06-23-diarization-sota.md)
(diarization tech: WhisperX/pyannote, DER numbers, licensing) and the
speaker-embedding sibling workstream. This brief does **not** re-litigate the
embedding model choice; it owns the four things those don't: binding a spoken
NAME to a voiceprint, cross-session voice memory, evaluating the whole pipeline,
and the biometric-privacy law.

**Bottom line up front.** The clean design is *enroll-by-introduction*: each
participant says "moi c'est <Name>"; the same ASR that powers dictation
transcribes that utterance, a pattern matcher pulls the name, and the voiceprint
captured **during that same segment** is bound to it. Everything else
(diarize → identify → label) is rented from the sibling stack. The spine we own
is small and high-leverage: the name extractor, the voice-memory store, and the
eval harness. The single non-negotiable interlock — **when binding is not
clean, the speaker is labelled "Speaker N" / "inconnu", never a guessed name.**

---

## 1. Name-binding from the introduction

### The elegant trick (and its one sharp edge)
The enrollment utterance is itself dictation. "Moi c'est Guillaume" passes
through the *same* faster-whisper path as everything else, so the transcript
already contains the name — no separate keyboard step, no account lookup. We
bind the name to the speaker embedding extracted from that exact segment's audio
(the diarizer/embedder hands us the segment; we average the frame embeddings
over it, the standard enrollment recipe — see §2).

**The sharp edge the synthesizer must see:** the name rides on a transcript, and
proper nouns are exactly where ASR is weakest. "PLN" will not survive as
letters; "Antoine" is fine, "Ngozi" or "Siân" less so. So name *extraction* is
fallible in a way name *binding* (audio→embedding) is not. The structural answer
is a confirmation/placeholder path, never a silent guess (§ safety).

### Extraction: pattern-first, NER-second, confirm-always
French person-name NER is genuinely weak — spaCy's `fr_core_news_*` is
documented to mis-tag people (it has labelled "Kylian Mbappé" as an *org*). So:

- **Primary: anchored patterns**, because an introduction is a closed
  construction, not free text. FR: `moi c'est X` / `moi je suis X` /
  `je suis X` / `je m'appelle X` / `c'est X à l'appareil`. EN: `my name is X`, `this is X`,
  `I'm X`, `X here`. The token(s) after the anchor are the candidate name. This
  is the same family of structural matching the project already trusts for
  voice commands (anchored trigger, not a classifier).
- **Fallback: NER on the residue** only when no pattern fires (someone says just
  "Guillaume"). Treat NER output as a *suggestion to confirm*, not a binding.
- **Always: surface the extracted name for a one-glance confirm.** Show
  "Enrolled: Guillaume ✓ / edit" in the roundtable UI. Cheap, and it converts
  the fallible step into a human-checked one. "It's a setting": auto-confirm
  high-confidence single-token FR/EN names by default; require explicit confirm
  off by default for the paranoid.

### Disambiguation (two Guillaumes)
Names are not identities. The store keys on the *voiceprint*, not the string. If
two enrolled embeddings both claim "Guillaume", they are distinct speakers with
a colliding label; disambiguate at the label layer ("Guillaume B." /
"Guillaume 2") and let the user rename. If one person enrolls twice (re-says
their intro), the embeddings will be near-identical — offer a *merge*, don't
silently create a phantom second speaker.

### Passphrase vs. intro — use both, for different jobs
- The **intro** ("moi c'est X") carries the *name* but is short and varies in
  length — mediocre enrollment audio.
- An optional **fixed passphrase** ("the quick brown fox" / a fixed FR sentence)
  after the intro gives a few clean seconds of **phonetically richer, consistent
  audio for the voiceprint**, improving embedding quality and giving a stable
  text-dependent anchor for future re-verification. Recommend: intro for the
  name, optional passphrase for embedding quality. Default on for cross-session
  memory users; skippable for one-off meetings.

### Prior art — and why this is under-served
Remote meeting tools assign names from **platform/account/calendar identity**,
not voice:
- **Zoom / Google Meet**: Fireflies and peers display *actual participant names*
  only on those platforms (they read the participant roster); on everything else
  they fall back to "Speaker 1, Speaker 2."
- **Otter.ai**: builds voiceprints, but enrollment is *manual tagging after the
  fact* ("type their name, Tag") and workspace members' profiles auto-apply —
  again an account/roster anchor, not a spoken self-enrollment.
- **Teams**: same family — roster/account identity.

The gap: **co-located, in-person participants sharing one mic have no roster.**
That is precisely TuParles' case, and *self-enrollment by spoken introduction*
is the natural local-first answer nobody ships well. This is a real
differentiator, not a me-too feature.

---

## 2. Cross-session voice memory

### Design (own this spine; it's a store, not a model)
A local **voiceprint store**: per known person, a label + one or more averaged
speaker embeddings (192-D / 256-D from the sibling's ECAPA-TDNN-class model) +
provenance (enrolled date, source meeting, sample count). At meeting start, each
intro segment's embedding is compared by **cosine similarity against the store**:

- match above the *accept* threshold → reuse the known name (no re-intro
  needed: "welcome back, Guillaume");
- below the *reject* threshold → new/unknown speaker (cold-start: enrol now);
- in the **grey zone between the two thresholds → abstain to "unknown"**, ask
  for a quick re-intro. Two thresholds, not one — the gap is the safety margin.

This is **open-set speaker identification**: thresholds tuned on **EER** (equal
error rate), with explicit out-of-set rejection, exactly the watchlist
formulation in the literature. We rent the embedding model; we own the
store, the thresholds, and the abstain logic.

### Drift, merge/split, cold-start
- **Drift** (a cold, a different mic): keep multiple embeddings per person and
  optionally update the centroid on *confirmed* matches only — never on an
  abstain. Confirmed-only update keeps a bad match from poisoning the profile.
- **Merge**: two profiles that keep co-matching are the same person → offer
  merge. **Split**: one profile matching two clearly separable clusters →
  flag, don't auto-split.
- **Cold-start**: a brand-new participant is just an enrol; the cost of being
  wrong is "unknown speaker", which is acceptable by doctrine.

### "It's a setting"
Voice memory is **off by default for a given meeting** (a roundtable can be
fully ephemeral — enrol, label, forget) and **opt-in to persist**. Persistence
is the thing that turns voiceprints into stored biometric data (§4), so the
toggle is also the consent boundary.

---

## 3. Evaluation — the part that earns trust

Mirror the existing code-switch harness (`tests/test_codeswitch_eval.py`):
**corpus-first, slot-style gate + error-rate trend, GPU-gated/skippable,
regenerable audio, corpus-under-test.** We are measuring a *named transcript*,
so we need metrics at three layers.

### Metrics (get the provenance right — these are load-bearing)
| Metric | What it scores | Origin | Use here |
|---|---|---|---|
| **DER** (Diarization Error Rate) | who-spoke-when: miss + false-alarm + speaker-confusion | NIST RT, standard | Trend on the diarizer; sibling already cites ~17-22% AMI for pyannote |
| **JER** (Jaccard Error Rate) | per-speaker, equal-weight, **bounded 0-100%** (Hungarian map, 1 − mean Jaccard) | **DIHARD II (2019)** | Companion to DER; fairer when one speaker dominates a standup |
| **cpWER** (concatenated minimum-permutation WER) — aka the speaker-attributed-WER (**SA-WER**) family | **joint** ASR + speaker attribution: concatenate per speaker, take the speaker permutation that **minimises WER** | **CHiME-6 Track 2 (2020)** | The headline number — "is the *named* transcript right?" |
| **DA-WER** (diarization-attributed WER) | like cpWER but permutation **minimises DER**, not WER | CHiME-7 (evolution) | Optional; separates diarization error from ASR error |
| **Name-ID accuracy** | of segments where we *asserted* a name, how many were the right person; and abstain rate | open-set ID (EER-tuned) | Our specific layer — see asymmetric framing below |

**The asymmetric scorecard (the doctrine made measurable).** Report two numbers
separately, never one blended accuracy:
- **Wrong-name rate** — asserted a name, it was the wrong person. This is the
  *expensive* error (a quote attributed to the wrong human). Gate hard; target
  near-zero.
- **Abstain rate** — labelled "unknown" when we could have named. The *cheap*
  error. Report as trend; tolerate generously.
A system that abstains more to drive wrong-name toward zero is *better* by our
doctrine, and the scorecard must reward that, not punish it. Slot-style: each
case declares the expected speaker label for a span; `must_name`/`must_abstain`.

### Datasets to pull
- **English / multi**: **AMI Meeting Corpus** (the canonical meeting set, close-
  & far-field), **ICSI** (meetings), **VoxConverse** (in-the-wild diarization),
  **DIHARD III** (hard diarization), **CALLHOME** (2-speaker telephone —
  classic ID baseline), **CHiME-6/7/8 DASR** (dinner-party, the cpWER home).
- **French**: **ESTER 1/2** (radio broadcast news, 100h/150h), **ETAPE** (36h TV
  + radio, prepared + spontaneous, *cross-show* diarization — closest to
  re-identification), **REPERE** (multimodal video, 2012-14). All via **ELDA**;
  these are evaluation-campaign corpora, expect licensing/registration, not a
  `wget`. **ALLIES** (ELDA) is the across-time/cross-session FR set — directly
  relevant to voice memory. Note: these are *broadcast*, not *roundtable* —
  useful for the diarizer/embedder, not for our intro-binding flow.

### The in-house FR+EN roundtable corpus (the one that actually fits)
Public corpora don't contain "moi c'est X" enrollment turns, so build a small
one, the same way the code-switch corpus was built:
- **Record 3-5 mock standups** (5-10 min each), 3-4 colleagues, real franglais,
  each opening with the intro ritual ("moi c'est X" / passphrase). Mixed
  genders, at least one non-French name and one ASR-hostile name (the "PLN"
  case). Re-record a subset *weeks later / different mic* → the cross-session
  set.
- **Annotate**: RTTM (who-spoke-when) + the ground-truth name per speaker + a
  reference transcript. This is the only annotation that lets you compute cpWER
  and name-ID together.
- **Regenerable scaffolding**: as with code-switch, store the corpus manifest +
  annotations in git; audio gitignored; a script reproduces the harness.
  Synthetic intros (piper/espeak, incl. the cross-lingual-voicing trick already
  in the repo) seed the corpus before the human recordings land.
- **"Good enough" bar**: wrong-name rate < ~2% on the in-house set (asymmetric
  gate), DER in the sibling's expected 17-22% band, cpWER reported as the
  trend line that #49/lexicon work must not regress. These are *starting*
  bars to ratchet, not absolutes — measure first, then set.

---

## 4. Biometric privacy & law — concrete product requirements

A voiceprint is biometric data. The law is friendlier to us than to the cloud
tools, *and our architecture is the reason* — so state it precisely rather than
hand-wave a "ban".

### GDPR — Article 9 special category, with the exact trigger
Biometric data becomes **special-category** under **Art. 9** *only* when
"processed **for the purpose of uniquely identifying a natural person**." A
voiceprint used to re-identify speakers is exactly that purpose, so **it
qualifies — no wiggle room.** Special category ⇒ a lawful basis under Art. 6
**plus** an Art. 9(2) exception; for a consumer tool that means **explicit
consent** (freely given, specific, informed, unambiguous — EDPB reaffirmed
2025). That is satisfiable here precisely because enrollment is an explicit,
spoken, opt-in act.

### EU AI Act — why we sit outside the red zones (don't overclaim a ban)
Regulation (EU) 2024/1689 (in force 1 Aug 2024; high-risk obligations apply from
2 Aug 2026):
- **The load-bearing discriminator: it is not "remote" biometric ID at all.**
  Art. 3 defines *remote* biometric identification as identification **"without
  the active involvement"** of the person. Our participants *actively speak*
  "moi c'est X" to enrol and to be recognised — active involvement by
  definition. That single fact takes the system out of "remote biometric
  identification" and therefore out of **both** Art. 5(1)(h) **and** the
  Annex III(1)(a) high-risk category in one move. (Don't lean on "it's 1:1
  verification" — cross-session voice memory is 1:many against the store, so the
  verification carve-out doesn't cleanly apply; the active-involvement argument
  does and is airtight.)
- **Prohibited (Art. 5(1)(h))**: *real-time* *remote* biometric ID in *publicly
  accessible spaces* for *law-enforcement*. Five **cumulative** conditions. We
  meet **none** — and fail "remote" first (above).
- **Prohibited (Art. 5(1)(g))**: biometric *categorization* to infer protected
  traits (race, politics, sexuality…). We assign a *name*, not a sensitive
  group. The distinction is explicit in EDPB/AI-Act guidance: sorting people
  into predefined sensitive categories ≠ recognising who someone is.

Honest framing for the README/blog: *"We're outside the AI Act's prohibited and
high-risk biometric zones by construction — the speaker actively introduces
themselves, so it is not remote biometric identification; it is local,
consent-based, and never categorizes."* True and stronger than a vague "it's
banned, we're not it."

### BIPA (Illinois, US) — the strictest baseline, worth meeting anyway
- **Voiceprints are explicitly named** biometric identifiers under BIPA
  (740 ILCS 14).
- Requires **informed consent + a written release** before collection (SB 2979,
  Aug 2024, clarified that an **electronic signature** suffices, and capped
  repeat-collection as a single violation).
- **Private right of action**: $1,000/negligent, $5,000/intentional per
  violation. The reason cloud voice tools sweat; the reason on-device + consent
  + delete is the safe posture even for a US user.

### The guardrails as product requirements (these become spec, not prose)
1. **Local-only, never uploaded.** Voiceprints live on the user's box; no
   network path off-device. This is the whole moat and the legal keystone.
2. **Consent ritual at enrollment.** A spoken/visible "everyone OK with name
   tagging?" gate before roundtable mode records voiceprints; the act of saying
   "moi c'est X" *is* the opt-in, but the table must be told it's happening.
   Default: ephemeral (no persistence) unless voice-memory is explicitly on.
3. **Easy delete = GDPR erasure, first-class.** "Forget Guillaume" must wipe the
   embedding(s) + provenance immediately and irreversibly; "forget this meeting"
   and "forget everyone" too. Deletion is a feature, not a buried setting —
   deletion-beats-addition applies to data, not just code.
4. **Transparency.** The user can see what voiceprints are stored, when enrolled,
   from which meeting. No silent biometric accumulation.
5. **Consent boundary = persistence toggle.** Per-meeting use without persistence
   is the low-stakes default; persisting is the explicit, reversible choice.

### Dovetail with the PII-firewall workstream
Voiceprints are the most sensitive PII the project will hold. The same doctrine
the firewall enforces for text PII — minimize, keep local, make deletion
trivial, never exfiltrate — extends one-to-one to voiceprints. The firewall's
delete/redact primitives and the voice-memory store should share the same
"forget" plumbing so there is **one erasure path**, audited once.

---

## 5. Top risks & open questions

- **Name extraction inherits ASR's worst case (proper nouns).** Mitigated by
  pattern-first + confirm-step, not solved. Open: do we keep a small per-user
  name lexicon (dict-seeding #54) so "PLN"/"Ngozi" survive on repeat meetings?
- **Threshold tuning is corpus-dependent.** EER thresholds from VoxCeleb-trained
  models may not transfer to our mic/room; the in-house corpus must set them,
  and they may drift per hardware (the CUDA/suspend memory shows hardware
  surprises are real here).
- **Overlap still bleeds** (sibling's caveat): when two people talk over the
  intro, binding is unreliable → abstain. The dual-channel capture (mic vs
  monitor) gives free me-vs-them; the hard case is multiple co-located people on
  one mic.
- **Cross-session merge/split is a UX minefield.** Auto-merge is tempting and
  dangerous (merging two real people). Recommend: *suggest, human confirms.*
- **No public corpus has the intro ritual.** The in-house corpus is the only
  ground truth for the binding step; it must exist before we trust the feature
  (measure-before-you-trust).
- **Consent for a *recorded* meeting vs a *persisted voiceprint* are different
  asks.** The ritual must distinguish "we're transcribing" from "we're storing
  your voice to recognise you next time." Open: how heavy should the persist
  consent be?

---

## Sources
See `SOURCES.md` (new "Roundtable / name-binding / biometric law" section) for
the consolidated link list.
