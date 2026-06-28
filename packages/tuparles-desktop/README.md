# tuparles (desktop)

The desktop distribution of [TuParles](../../README.md) — the GUI, the
push-to-talk daemon, audio capture, the engine gradient (CUDA → qwen →
whisper.cpp), global hotkey, text delivery, and the optional `nlp/`
corpus-analysis layer.

It depends on [`tuparles-core`](../tuparles-core/README.md) for the portable
post-decode pipeline, privacy firewall, and settings, and adds everything that
needs a screen, a microphone, or a GPU. Both distributions populate the shared
`tuparles` namespace (PEP 420), so imports read `from tuparles.<module>`
regardless of which package a module ships in.

See the [repo README](../../README.md) for install and usage.
