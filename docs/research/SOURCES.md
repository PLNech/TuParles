# Sources

External links cited across the research briefs, grouped by topic. Kept
separately so a brief stays readable and the link-extract is reusable.

## Linux audio capture (PipeWire / PulseAudio)
- PipeWire — module-combine-stream: https://docs.pipewire.org/page_module_combine_stream.html
- PipeWire — module-loopback: https://docs.pipewire.org/page_module_loopback.html
- ArchWiki — PipeWire/Examples: https://wiki.archlinux.org/title/PipeWire/Examples
- Recording audio on Linux (monitor sources, parec): https://ro-che.info/articles/2017-07-21-record-audio-linux
- Fedora — PulseAudio monitor equivalent in PipeWire: https://discussion.fedoraproject.org/t/what-is-the-equivalent-of-pulseaudios-monitor-sources-in-pipewire/68939

## ASR chunking / alignment
- WhisperX (time-accurate long-form, VAD chunking ~30s, overlap), arXiv: https://arxiv.org/html/2303.00747
- Whisper audio chunking (2-3s overlap): https://www.saytowords.com/en/blogs/Whisper-Audio-Chunking/

## Diarization
- WhisperX repo (m-bain) — bundles align + pyannote diarize + assign
- pyannote.audio — `speaker-diarization-community-1` + `segmentation-3.0` (HF, gated; MIT / CC-BY-4.0)
- whisper-diarization (MahmoudAshraf97) — Demucs + faster-whisper + NeMo MSDD
- NVIDIA NeMo — `diar_sortformer_4spk-v1` (CC-BY-NC, ≤4 speakers)
- diart (juanmc2005) — online/streaming, MIT
- DiariZen (BUT) — WavLM-based, SOTA meeting DER, CC-BY-NC weights

## Local LLM summarization
- LLM×MapReduce (long-context map-reduce + collapse), ACL 2025
- Context-Aware Hierarchical Merging (CAHM), arXiv: 2502.00977
- DRES — disfluency removal helps speech summarization, arXiv: 2509.20321
- Fillers carry paralinguistic stance signal, arXiv: 2009.11340
- MiniCheck — local NLI faithfulness ~GPT-4 at 1/400 cost, arXiv: 2404.10774
- QMSum — query-based meeting summarization (select-spans-then-summarize)
- Vectara 2025 — fixed-window-with-overlap beats semantic chunking
- Granola reverse-engineering (API/auth only): getprobo, granola-cli
- Local clones: Hyprnote/anarlog, Meetily, OpenWhispr

## Roundtable / name-binding / speaker ID / biometric law
### Name assignment in commercial meeting tools (prior art)
- Otter.ai — Speaker Identification Overview (manual tag-after-the-fact, workspace profiles auto-apply): https://help.otter.ai/hc/en-us/articles/21665587209367-Speaker-Identification-Overview
- Otter.ai — Best Practices to Maximize Speaker Identification: https://help.otter.ai/hc/en-us/articles/37817241040535-Best-Practices-to-Maximize-Speaker-Identification
- Fireflies — speaker labels: actual names on Meet/Zoom (roster), "Speaker N" elsewhere; how diarization works: https://summarizemeeting.com/en/faq/fireflies-speaker-diarization-how-it-works
- Fireflies — edit speaker labels: https://guide.fireflies.ai/articles/4994477228-how-to-edit-speaker-labels-or-names-in-a-transcript

### Name extraction (FR NER weakness)
- spaCy French models (fr_core_news_*): https://spacy.io/models/fr
- spaCy FR person-name extraction issues (mis-tags PER as ORG): https://github.com/explosion/spaCy/issues/1906

### Speaker verification / open-set ID (the abstain mechanism)
- ECAPA-TDNN (Desplanques et al.), arXiv: https://arxiv.org/pdf/2005.07143
- VoxWatch — open-set speaker recognition benchmark on VoxCeleb, arXiv: https://arxiv.org/html/2307.00169

### Evaluation metrics & datasets
- cpWER + CHiME-6 Track 2 (concatenated min-permutation WER): https://www.isca-archive.org/chime_2020/watanabe20b_chime.pdf
- CHiME-7/8 DASR (DA-WER evolution), arXiv: https://arxiv.org/pdf/2407.16447
- DIHARD II — JER (Jaccard Error Rate) introduced, eval plan: https://dihardchallenge.github.io/dihard2/docs/second_dihard_eval_plan_v1.1.pdf
- DIHARD III overview, arXiv: https://arxiv.org/pdf/2012.01477
- dscore — diarization scoring tools (DER + JER): https://github.com/nryant/dscore
- French corpora: ETAPE (TV/radio, cross-show diar): https://www.researchgate.net/publication/235744802 ; ESTER (FR broadcast news rich transcription) ; REPERE (multimodal video) ; ALLIES (ELDA, across-time/cross-session diar): https://www.mail-archive.com/mt-list@lists.eamt.org/msg00467.html

### Biometric privacy & law
- GDPR Art. 9 — biometric special category only "for the purpose of uniquely identifying": https://summitnotes.app/blog/gdpr-voice-recordings-biometric-data/
- IAPP — Biometrics in the EU: navigating GDPR + AI Act: https://iapp.org/news/a/biometrics-in-the-eu-navigating-the-gdpr-ai-act
- EU AI Act Art. 5 — prohibited practices (official): https://artificialintelligenceact.eu/article/5/
- FPF — Art. 5(1)(h) real-time remote biometric ID for law enforcement (five cumulative conditions): https://fpf.org/blog/red-lines-under-the-eu-ai-act-restricting-real-time-remote-biometric-identification-systems-for-law-enforcement-purposes/
- FPF — Art. 5(1)(g) biometric categorization of sensitive traits (vs identification): https://fpf.org/blog/red-lines-under-the-eu-ai-act-understanding-the-prohibition-of-biometric-categorization-for-certain-sensitive-characteristics/
- BIPA (740 ILCS 14) + SB 2979 (Aug 2024 amendments, e-signature, damages cap): https://www.gtlaw.com/en/insights/2024/8/bipa-update-illinois-limits-liability-and-clarifies-electronic-consent-for-biometric-data-collection

## Voice UI command-and-control
- Nuance Dragon — command vs dictation, "pause before/after commands," Scratch That N Times
- Talon Voice — modes, `say` literal escape, mouth-pop/hiss noises, command chaining
- Serenade, VoiceCode, Cursorless — voice-coding command grammars
- Apple Voice Control / Windows Voice Access ("Type"/"Dictate" escape) / Google Voice Access
- W3C SRGS — speech recognition grammar specification
- Raskin, *The Humane Interface* — quasimodes; Tesler, "Don't Mode Me In"
- Sarter & Woods — automation surprise / mode confusion
