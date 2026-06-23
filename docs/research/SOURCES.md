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

## Voice UI command-and-control
- Nuance Dragon — command vs dictation, "pause before/after commands," Scratch That N Times
- Talon Voice — modes, `say` literal escape, mouth-pop/hiss noises, command chaining
- Serenade, VoiceCode, Cursorless — voice-coding command grammars
- Apple Voice Control / Windows Voice Access ("Type"/"Dictate" escape) / Google Voice Access
- W3C SRGS — speech recognition grammar specification
- Raskin, *The Humane Interface* — quasimodes; Tesler, "Don't Mode Me In"
- Sarter & Woods — automation surprise / mode confusion
