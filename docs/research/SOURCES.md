# Sources

External links cited across the research briefs, grouped by topic. Kept
separately so a brief stays readable and the link-extract is reusable.

## CPU/edge ASR landscape (2026-07 fan-out)
### Models & runtimes
- NVIDIA Parakeet TDT 0.6B v3 (25 langs incl. FR, CC-BY-4.0): https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- parakeet.cpp (ggml port, MIT, v0.4.0 2026-07): https://github.com/mudler/parakeet.cpp — Show HN: https://news.ycombinator.com/item?id=47176239
- Qwen3-ASR (0.6B/1.7B, Apache 2.0, 2026-01): https://github.com/QwenLM/Qwen3-ASR — report: https://huggingface.co/papers/2601.21337
- Kyutai stt-1b-en_fr (native bilingual, word ts): https://kyutai.org/stt/ — https://huggingface.co/kyutai/stt-1b-en_fr
- Mistral Voxtral (Mini 3B / Realtime 4B 2026-02, Apache 2.0): https://mistral.ai/news/voxtral/ — realtime paper: https://arxiv.org/abs/2602.11298
- Moonshine v2 (2026-02, MIT, per-language doctrine): https://github.com/moonshine-ai/moonshine — community FR: https://huggingface.co/Cornebidouil/moonshine-tiny-fr
- SenseVoice / FunASR: https://github.com/FunAudioLLM/SenseVoice (⚠ FR support contested across sweeps — verify)
- IBM Granite Speech 4.1 (2026-04, Apache 2.0)
- distil-large-v3.5 (EN-only): https://huggingface.co/distil-whisper/distil-large-v3.5 — FR distils (2024, unrefreshed): https://huggingface.co/bofenghuang/whisper-large-v3-french-distil-dec16
- OpenVINO int8 Whisper (NNCF): https://blog.openvino.ai/blog-posts/optimizing-whisper-and-distil-whisper-for-speech-recognition-with-openvino-and-nncf
- onnx-asr unifying layer (OpenVoiceOS, 2026-02): https://blog.openvoiceos.org/posts/2026-02-16-onnx-asr

### faster-whisper / whisper.cpp CPU specifics
- CTranslate2 (v4.8.1 2026-07): https://github.com/OpenNMT/CTranslate2
- faster-whisper releases (1.1.0 VAD 3×, BatchedInferencePipeline; 1.2.0 distil-v3.5): https://github.com/SYSTRAN/faster-whisper/releases
- CPU batching bench (14.6× RT CPU batched): https://mobiusml.github.io/batched_whisper_blog/
- cpu_threads/num_workers contention: https://github.com/SYSTRAN/faster-whisper/pull/965 + issues #629, discussion #346
- AVX512 modest on small models: https://github.com/ggml-org/whisper.cpp/discussions/589
- Silero VAD v6.x (−11-16% errors vs v5): https://github.com/snakers4/silero-vad/releases
- sherpa-onnx Whisper ONNX accuracy drift: https://github.com/k2-fsa/sherpa-onnx/issues/2900 — FR zipformer weak on 4GB phone: https://github.com/k2-fsa/sherpa-onnx/issues/3144

### Mobile / NPU
- Qualcomm AI Hub Whisper-Small w8a16 per-chipset latency: https://huggingface.co/qualcomm/Whisper-Small-Quantized
- whisper.cpp Vulkan-on-Android still open: https://github.com/ggml-org/whisper.cpp/issues/2370
- Argmax Pro SDK on LiteRT (NPU-vendor unification, 2026-03): https://www.argmaxinc.com/blog/argmax-pro-sdk-for-android — WhisperKitAndroid archived 2026-01
- ExecuTorch Whisper/ASR on-device (2026-03): https://pytorch.org/blog/building-voice-agents-with-executorch-a-cross-platform-foundation-for-on-device-audio/ — https://github.com/pytorch/executorch/blob/main/examples/models/whisper/README.md
- Play on-device AI model delivery (beta): https://developer.android.com/google/play/on-device-ai
- Android 15/16 mic-FGS restrictions: https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start
- ML Kit GenAI speech (FR beta; advanced = Pixel-10-only): https://developers.google.com/ml-kit/genai/speech-recognition/android
- WhisperKit ANE techniques (ICML 2025): https://arxiv.org/html/2507.10860v1

### Papers (bibliography)
- Open ASR Leaderboard (SSOT for WER/RTFx): https://arxiv.org/abs/2510.06961 — blog: https://huggingface.co/blog/open-asr-leaderboard
- CS-FLEURS code-switch dataset (113 pairs — FR-EN membership TBC): https://arxiv.org/abs/2509.14161
- Adding robust code-switching to multilingual ASR (KIT, 2026-06): https://arxiv.org/abs/2606.21990
- Adapting language balance in code-switching (KIT, 2025-10): https://arxiv.org/abs/2510.18724
- CS generalization to unseen pairs (2026-06): https://arxiv.org/abs/2606.05846
- Quantizing Whisper-small: granularity & calibration dominate (2025-11): https://arxiv.org/abs/2511.08093
- BaldWhisper: shear+merge compression, code-switch-aware (2025-10): https://arxiv.org/abs/2510.08599
- Self-speculative decoding for LLM-ASR (IBM, 2026-03): https://arxiv.org/abs/2603.11243
- Compact streaming transducer for edge (NVIDIA, 2026-04): https://arxiv.org/pdf/2604.14493

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
