# Local Meeting Transcript → Notes on an RTX 4080 (2025-2026)

*Researched 2026-06-23. Verbatim research brief.*

## TL;DR — recommended stack

| Layer | Pick | Why |
|---|---|---|
| **Serving** | **Ollama** (llama.cpp under the hood) | Simplest headless Python path; OpenAI-compatible API at `:11434/v1`; enforced JSON-schema via `format=` |
| **Default model (FR)** | **Mistral Small 3.2 24B @ Q4_K_M** (~13-14 GB) | Paris-built, most French-native; 128k context; best quality/VRAM ratio |
| **Long-transcript model** | **Qwen3 14B @ Q5_K_M + q8_0 KV cache** (~10-11 GB) | Most KV headroom for 32k+, best instruction-following, quantization-tolerant |
| **Multilingual fallback** | **Gemma 3 12B @ Q4/Q5** | 140+ languages, comfortable long-context margin on 16 GB |
| **Faithfulness check** | **MiniCheck (770M)** local | Near-GPT-4 entailment at ~1/400th cost; fits trivially alongside |

Avoid: **Gemma 3 27B** (weights ~16 GB, no KV room) and **Qwen3 30B-A3B** (MoE saves compute not memory; needs 24 GB+). **vLLM** is wrong for single-user serial batch.

## 1. The Granola pattern — augment notes, don't auto-summarize

Granola is an "AI notepad," not an "AI note-taker": works *alongside* you. User types sparse fragments ("Wants SSO by June"); app captures system audio (no bot), transcribes in background, then an LLM rewrites the user's notes using **three inputs**: (1) user's raw notes, (2) transcript, (3) calendar metadata. AI text renders gray below user's black text, each bullet hyperlinked to the transcript span it came from.

**Why it beats pure auto-summary (documented thesis):**
- **Intent signal.** User's notes tell the model *what mattered* — it weights those topics, fills detail from transcript, instead of treating all content equally.
- **Less hallucination.** Output anchored to human ground-truth + transcript provenance; every claim traceable.
- **Personalization & structure.** Notes are the scaffold; transcript is RAG-style grounding. "You write the structure, AI fills the details."

**Caveat:** the exact enhancement prompt is NOT public. Reverse-engineering cracked the API/auth layer only.

**Replication design:**
- Assemble the triad: user notes first (steering skeleton), transcript as reference appendix, plus metadata.
- System prompt encodes the contract: *"You are enhancing the user's own notes. The notes define what mattered and the structure to follow. Use the transcript ONLY to expand and support points the user raised. Every added detail must be grounded in the transcript — if it isn't there, don't add it. Keep the user's text verbatim; cite the transcript span for each addition."*
- Preserve provenance (cite timestamps/speaker) — doubles as anti-hallucination.
- Swappable templates for output structure.

OSS local clones: **Meetily** (Tauri + Whisper.cpp + Ollama), **OpenWhispr**.

## 2. Models for 16 GB, FR+EN

VRAM rule: `≈ (params_B × bits) / 8` + KV cache.

| Model | Q4_K_M weights | +KV @ 32k | 16 GB verdict |
|---|---|---|---|
| Llama 3.1 8B | ~5 GB | +4 GB | Tons of room (runs Q8); weaker |
| Qwen3 8B | ~5 GB | +3-4 GB | Easy |
| **Qwen3 14B** | ~9 GB | +4-5 GB | **~13-14 GB; best long-context pick** |
| **Mistral Small 24B** | ~13.4 GB | tight | **Fits at Q4; best French pick** |
| Gemma 3 12B | ~7-8 GB | +4 GB | Comfortable |
| Gemma 3 27B | ~16-17 GB | overflow | Marginal/no |

- **French nativeness:** Mistral Small (Paris) > Qwen3 / Gemma 3 > Llama 3.1 8B. **Skip Phi-4** (English-centric).
- **Code-switching:** no isolating benchmark; broad-tokenizer (Gemma 3, Qwen3) + French-native Mistral are safe inference.
- **Quantization:** Q4_K_M standard; Q5_K_M/Q6 when ≤14B. **Qwen unusually KV-quant-tolerant** (q8_0 KV → most usable long context).
- All four candidates have **128k context**.

## 3. Serving — Ollama wins

All four (Ollama, llama.cpp, vLLM, LM Studio) expose OpenAI-compatible REST.
- **Ollama** — easiest: auto-pulls GGUF, GPU automatic, headless scripting. Enforced JSON via `format=Model.model_json_schema()`. `temperature=0`.
- **llama.cpp `llama-server`** — runner-up for exact quant/KV/GBNF control. Bugs: rejects `json_schema`+`grammar` together; GBNF chokes on `\d \w \s`.
- **vLLM** — heaviest, aggressive VRAM pre-alloc, throughput needs concurrency.
- **LM Studio** — GUI-first.

## 4. Long-transcript strategy

**Stuff when you can, hierarchical when you must — don't trust the advertised window.**
- A typical meeting (<1 hr) fits well under 128k — **just stuff it**.
- But **effective context << advertised**, and **lost-in-the-middle** (U-shaped recall) is real.
- Oversized transcripts: **map-reduce with collapse** (`LLM×MapReduce`, ACL 2025); **refine chain** (sequential, slow); prefer **Context-Aware Hierarchical Merging** (CAHM, arXiv 2502.00977).
- **Chunking:** fixed-window-with-overlap beat semantic chunking (Vectara 2025). Chunk by **speaker turn** or fixed window + ~500-token overlap. Quality cliff ~2,500 tokens.
- **QMSum lesson:** select-relevant-spans-then-summarize, not summarize-everything.

## 5. Structured extraction (action items / decisions / questions / topics)

- **Enforce structure with constrained decoding:** XGrammar, llama.cpp GBNF, Ollama `format=schema`. In Python, **Instructor** (Pydantic, validate-and-retry).
- **One-pass multi-field** for speed; **decompose per-field + verify** for accuracy.
- **Owner attribution requires speaker labels.** Emit per-speaker arrays.
- **Reason BEFORE you constrain.** Forcing structure before reasoning finishes → **10-30% reasoning degradation** ("structure snowballing"). Let the model reason free-form, then constrain only the final JSON block.
- **CoT + assistant-turn prefill** (`<action_items>` opening tag) to lock format.

## 6. Hallucination mitigation

- **Prompt-time:** "only use information in the transcript; do not infer." Extractive-first. **Cite timestamp/line/speaker per claim** (Granola's jump-to-transcript links).
- **Post-hoc:** **MiniCheck (770M, arXiv 2404.10774)** — 74.7% balanced acc vs GPT-4's 75.3%, ~400× cheaper, runs locally. Atomic-fact decomposition gave near-zero benefit — skip it.

## 7. Verbatim vs cleaned

**Clean disfluencies before extraction, but don't over-strip.**
- Some production notetakers feed raw transcript (LLMs robust to filler).
- But **research (DRES, arXiv 2509.20321) says disfluencies measurably hurt** speech summarization.
- **Counter:** fillers carry paralinguistic signal for stance/confidence (arXiv 2009.11340); LLMs store context in function-words/punctuation. So **keep punctuation + function words**, strip only vocal disfluencies (euh/um, false starts, verbatim repeats).
- **DRES gotchas:** segment first; reasoning models over-delete.
- **Keep speaker labels through the whole pipeline.**

## Concrete pipeline for TuParles

1. Transcribe locally (faster-whisper, GPU) → keep speaker labels.
2. Light cleanup (small model or rules): strip euh/um/false-starts, keep punctuation + speaker tags. Segment by turn.
3. Serve via Ollama. Default **Mistral Small 3.2 24B Q4_K_M**; **Qwen3 14B Q5_K_M + q8_0 KV** for long.
4. Enhance (Granola-style): prompt = user notes (scaffold) + transcript (grounding) + metadata; grounded-only expansion with citations.
5. Extract action items/decisions/questions as one-pass JSON (Ollama `format=schema`); reason free-form first, constrain final block; per-speaker owner arrays.
6. Verify with local MiniCheck-style NLI; flag unentailed bullets.

### Open contradictions (flagged)
- Gemma 3 27B on 16 GB: sources split "fits at Q4" vs "needs 20 GB." Prefer Gemma 3 12B.
- Constrained decoding: +4% vs −10-30% — variable is whether structure forced before reasoning completes.
