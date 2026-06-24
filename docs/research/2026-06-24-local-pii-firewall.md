# The local PII firewall: sanitize before any byte leaves the box

*Research synthesis, 2026-06-24. Seeds the blog (#42). Three parallel research
angles (detection / firewall architecture / classification + eval) folded into
one design. No code yet - this is the landscape and the build-vs-rent verdict.*

## Why

TuParles' whole pitch is "your voice never leaves your machine." Today that is
true by *absence* - we simply don't send anything anywhere. The moment we add a
cloud-LLM cleanup pass (Granola-style notes, #38), or even just store
transcripts, that guarantee needs a *mechanism*, not a promise. A local
PII-minimization step turns the privacy story from marketing into engineering:
nothing personal is persisted, surfaced in analytics, seeded into a dictionary,
or sent to an LLM unless it has passed a filter that runs on your own silicon.

This is also a genuine product edge. The enterprise tools that do this (Skyflow,
Private AI, Protecto) are SaaS vaults built for fleet-scale governance. A
single-user, local-only firewall is a different, simpler, and more trustworthy
animal - and nobody ships it for code-switching developers who dictate code.

## The shape: own the spine, rent the algorithms

Same doctrine as the nlp engine. We **rent** the solved parts (entity detection,
anonymizer operators) and **own** the thin spine no library models for a
single-user local tool: the policy router, the in-RAM map lifecycle, the
fail-closed interlock, and - the real differentiator - the code-symbol
allowlist.

```
        TuParles box (RTX 4080 + CPU)                    │  cloud (optional)
 speech ─► whisper ─► postprocess(text)                  │
                          │                              │
                   ┌──────▼───────┐                      │
                   │  DETECT      │ structural (µs) + NER │
                   └──────┬───────┘                      │
                   ┌──────▼───────┐  per-context profile  │
                   │ POLICY ROUTER│  + PII-density check   │
                   └──────┬───────┘                      │
        fail-closed ◄─────┤ too much PII / low confidence │
        (local only)      ▼  → DON'T SEND                 │
                   ┌──────────────┐                       │
                   │ ANONYMIZE    │ <PERSON_1>…           │
                   │ map in RAM   │ {<PERSON_1>:"Awa"}    │
                   └──────┬───────┘ sanitized text only ──┼─► LLM
                          │ ◄──── response w/ <PERSON_1> ─┼──┘
                   ┌──────▼───────┐                       │
                   │ REHYDRATE    │ swap back from map    │
                   └──────┬───────┘                       │
                   DISCARD MAP (zeroize) ◄ lifetime = 1 round-trip
```

**The map never touches disk.** It is built at anonymize time, used once at
rehydrate, then dropped. With no map at rest there is no new secret to leak -
which is exactly why we *reject* the persistent-vault model. The enterprise
tools persist it because they must detokenize across sessions and users; we have
one user and one round-trip, so we don't.

## Three layers, three safety semantics (the doctrine reconciliation)

The sharpest finding: this is **three problems**, and the command-vs-text rule
("never gate on a confidence score") survives only if we bind each to the right
authority.

| Track | Catches | Tool | Authority |
|---|---|---|---|
| **Deterministic terms** | named clients/projects, user blocklist | denylist (trie + normalization) | **may BLOCK/REDACT** |
| **Secrets** | API keys, tokens, private keys | regex prefixes + Shannon entropy | **may BLOCK/REDACT** |
| **Statistical** | "is this about health/finance/legal?"; free-form names/emails | embedding-to-prototype / NER | **ALERT only, never block on a score** |

Deterministic layers carry block authority (a miss is a rule bug, fixable);
statistical layers may only warn. And the asymmetric bias **flips** relative to
command-vs-text: there it is "when in doubt, it's text"; here it is **"when in
doubt, protect"** - recall-weighted. Stating the flip explicitly matters so we
don't mis-port the old bias.

## Detection: rent two, own one

- **Rent `python-stdnum`** for all checksummable structured PII: French **NIR**
  (`stdnum.fr.nir`, mod-97 control key, Corsica 2A/2B), **IBAN** (ISO 7064),
  **NIF**, **Luhn** for cards. Pure-Python, no torch, microsecond latency,
  ~100% precision when the checksum validates. The high-precision interlock.
- **Rent GLiNER multilingual PII** (`urchade/gliner_multi_pii-v1`) served via
  **`gliner2-onnx`** (onnxruntime-only, **no torch** - consistent with our
  fastembed posture) for free-text names/addresses/orgs, FR+EN, zero-shot label
  set. *Open question: do we even need it?* (see threat model below).
- **Secrets** via gitleaks-style high-signal regexes (`AKIA`, `ghp_`,
  `sk_live_`, `eyJ` JWTs, PEM headers) + entropy. Deterministic, `re`-only.
- **Own the code-symbol allowlist** - the part no rented library can do. A token
  matching a known code identifier (`getUserById`, a project symbol) is never
  PII, even if NER flags it. Source the negative filter from the **dict-seed AST
  / typed-term engine we already own**. Rent the detection; own the code-aware
  precision recovery. This is where the existing moat compounds.

**Keep NER off the paste hot-path.** Structural validators (µs) run inline
always; the ~0.9s/paragraph CPU GLiNER pass only gates *storage*,
*analytics-scrub*, and *cloud egress* - never the instant paste. On the 4080
it's sub-100ms anyway, but the deletion-beats-addition win is *not needing* it
on the hot path.

## Transformation: placeholder default, faker override, fail-closed

Rent **Presidio's** `AnonymizerEngine`/`DeanonymizerEngine` + the
`InstanceCounterAnonymizer` recipe (consistent `<PERSON_1>` per document, so
coreference survives and rehydration is unambiguous). LangChain's
`PresidioReversibleAnonymizer` is the reference impl (but it can persist the map
- we deliberately won't).

| Strategy | Reversible | LLM-usefulness | Verdict |
|---|---|---|---|
| redact / mask / hash | no | low | analytics only |
| **encrypt** (Presidio's only *crypto*-reversible op) | yes (key) | **very low** (ciphertext) | avoid |
| **placeholder `<PERSON_1>`** | yes (map) | **high** | **DEFAULT** |
| **faker surrogate** ("Marie Leroy") | yes (map) | **highest** | **override** |
| generalization / bucketing | no | medium | analytics / dicts |

Two reversibilities, don't conflate: *cryptographic* (encrypt - reversible but
useless to the LLM) vs *mapping-based* (placeholder/faker - human-readable, map
dies with the request). We want mapping-based. Placeholder is self-documenting
(our "visible mishear > silent rewrite" principle); faker buys grammatical
fidelity (FR agreement around a name) but hides the substitution and still needs
the map - so it's the Réglages override, not the default.

**Fail-closed interlock**: if text can't be confidently sanitized, or PII
density exceeds a threshold, don't send to the cloud at all - process locally.
Structural, not a score. "Send less when in doubt," made an interlock.

## The three data layers share the spine, not the operator

| Layer | Reversible? | Operator profile |
|---|---|---|
| **live utterances → LLM** | yes | placeholder / faker, request-scoped RAM map |
| **analytics aggregates** | no | irreversible suppression + **frequency floor** (drop count < k) |
| **seeded dict** | no | same frequency-floor profile |

For one user, k-anonymity = a rare-term frequency floor, not the full
generalization lattice. A name said once must not surface in a tag cloud or get
memorized as "vocabulary." This is the **#93 denoising idea wearing a privacy
hat** - the same suppression of the long tail serves both quality and privacy.
Differential privacy (noise on counts) is out of scope: proportionate to a
multi-user warehouse, not one person introspecting their own box.

## Evaluation: the load-bearing part

**No model alone clears a privacy bar.** Presidio recall is 57-73% on real text;
GLiNER strict-F1 ~0.37 on `ai4privacy/pii-masking-400k` (much of the gap is
tokenizer-offset drift, not real misses - boundary-F1 ~0.42). This is the
empirical argument *for* the deterministic denylist+secrets layer carrying the
high-assurance load, with the model as the recall net for the unknown.

- **Datasets**: `ai4privacy/pii-masking-200k/300k` (multilingual incl. French,
  FinPII covers finance classes) is the anchor; `WikiNER-fr-gold` (700k FR
  tokens, gold) for FR person/loc/org; **QUAERO French Medical** for the health
  topic; borrow `presidio-research`'s synthetic generator methodology.
- **Metrics**: entity-level (not token) with **partial/boundary** scoring;
  **Fβ with β=2** (recall-weighted - a leaked SSN costs far more than a redacted
  false positive); per-category breakdown; **leakage rate = 1 − recall** on a
  held-out red-team set.
- **Build the FR+EN code-switch corpus first** (our discipline). Reuse
  `tests/data/codeswitch/`; inject PII via Faker/Presidio templates + a held-out
  set of fake client/project names and secret tokens; add **Scunthorpe hard
  negatives** (legit words containing banned substrings) and topic-boundary
  negatives ("I paid for coffee" must not trip "finance"). Store under
  `tests/data/sensitive/`, add `tests/test_sensitive_eval.py` parallel to
  `test_codeswitch_eval.py`. A release that raises red-team leakage fails CI.
- **"Good enough"**: deterministic layers → ~0 leakage on the red-team set (any
  miss is a fixable rule bug); topic alerts → recall > precision, accept
  moderate precision because they only alert.

## Denylist & UX specifics

- User-editable YAML, `block`/`alert` tiers, per-entry match mode
  (`exact-word` | `substring` | `fuzzy`). Normalize (lowercase, NFKD
  accent-strip, leetspeak map) then **Aho-Corasick / trie** for O(L) scan.
  Default **word-boundary** match (the canonical Scunthorpe fix); fuzzy is
  opt-in per entry.
- Ship a tiny conservative default (secret-prefix rules as code); the term
  denylist is **user-owned, empty by default** ("it's a setting"). Never
  auto-expand it from model output (that's a silent rewrite).
- **Block vs alert**: deterministic hits → redact silently or block-with-confirm
  (high precision earns it); statistical hits → passive tray/toast alert, never
  block the paste (blocking on ~0.5-0.78 recall nags and erodes trust). DLP
  industry consensus: monitor → warn → enforce, coaching over hard blocks.

## Decisions & open questions

1. **Threat-model question that sizes the whole build**: do secrets-regex +
   user-denylist + topic-alert cover the real threat, or do we need GLiNER for
   free-form third-party names/emails at all? Cheapest path ships *without*
   GLiNER; add it only if the eval shows an unacceptable leak gap. **Decide via
   the eval, not taste.**
2. `gliner2-onnx` is experimental ("API may change") and needs a spike to
   confirm the UINT8 ONNX export runs under our pinned onnxruntime without
   dragging torch.
3. FR-isolated recall and code-identifier false-positive rates are **unmeasured
   in the literature** - genuine gaps. Write the corpus first; trust nothing
   published on clean monolingual text for our code-switched reality.
4. Embedding-prototype topic thresholds need per-topic, per-language tuning - a
   setting, calibrated on the dev split.
5. Redact-silently vs alert for the denylist block tier - "it's a setting,"
   redact-default the likely answer.

## Proposed shape (for elicitation, not yet built)

A `privacy/` package mirroring `nlp/` and `telemetry/`: `detect` (rent +
code-allowlist), `transform` (rent Presidio + RAM-map spine), `policy` (router +
fail-closed + the three profiles), `denylist`, plus `tests/data/sensitive/` and
`test_sensitive_eval.py`. Phase 1 could ship deterministic-only (secrets +
denylist + frequency-floor for analytics/dicts) - high assurance, no model, no
torch - and earn the statistical layers against the eval afterward.

## Sources

Detection: [Presidio](https://github.com/microsoft/presidio) ·
[GLiNER](https://github.com/urchade/GLiNER) ·
[gliner_multi_pii-v1](https://huggingface.co/urchade/gliner_multi_pii-v1) ·
[gliner2-onnx](https://pypi.org/project/gliner2/) ·
[python-stdnum fr.nir](https://arthurdejong.org/python-stdnum/doc/1.20/stdnum.fr.nir) ·
[GLiNER vs OpenAI privacy-filter shootout](https://heyneo.com/blog/pii-filter-model-eval)

Firewall: [Presidio anonymizer](https://microsoft.github.io/presidio/anonymizer/) ·
[reversible pseudonymization sample](https://microsoft.github.io/presidio/samples/python/pseudonymization/) ·
[LangChain PresidioReversibleAnonymizer](https://python.langchain.com/api_reference/experimental/data_anonymizer/langchain_experimental.data_anonymizer.presidio.PresidioReversibleAnonymizer.html) ·
[MS PII Shield privacy proxy](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/introducing-pii-shield-a-privacy-proxy-for-every-llm-call/4514726) ·
[Operationalizing Data Minimization for LLM prompting](https://arxiv.org/pdf/2510.03662) ·
[GDPR Art. 5](https://gdpr.algolia.com/gdpr-article-5)

Classification & eval: [ai4privacy/pii-masking-200k](https://huggingface.co/datasets/ai4privacy/pii-masking-200k) ·
[Presidio evaluation methodology](https://microsoft.github.io/presidio/evaluation/) ·
[presidio-research](https://github.com/microsoft/presidio-research) ·
[Protecto PII benchmark (57-73% recall)](https://protecto.ai/wp-content/uploads/2024/07/6646f1564c513545cbf9d2f9_Quantitative-Benchmark-Study-PII-Identification-1.pdf) ·
[mDeBERTa-v3 multilingual NLI](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7) ·
[WikiNER-fr-gold](https://arxiv.org/abs/2411.00030) ·
[QUAERO French Medical](https://quaerofrenchmed.limsi.fr/) ·
[CleanSpeak on Scunthorpe](https://cleanspeak.com/blog/2016/04/06/facebook-fail-properly-filter-scunthorpe) ·
[Gitleaks](https://github.com/gitleaks/gitleaks)

> *"The one who builds the fence decides where the gate is."* - Akan drum-proverb,
> via the research. Block where you're certain, whisper where you're guessing,
> and measure the leaks before you trust the wall.
