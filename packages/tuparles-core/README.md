# tuparles-core

The portable, stdlib-first heart of [TuParles](../../README.md): the
post-decode text pipeline (`pipeline.postprocess`), the local PII firewall
(`privacy/`), the voice-command grammar, settings, lexicon, languages,
telemetry and history.

It imports **no** GUI, microphone, or GPU dependency — that boundary is
enforced mechanically by `tests/test_core_boundary.py`. The same code runs
embedded on Android (Chaquopy) and inside the `/stt/` server, so nothing here
may reach for PySide6, sounddevice, faster-whisper, pynput, evdev, or numpy.

This is a [PEP 420](https://peps.python.org/pep-0420/) namespace package: it
shares the `tuparles` import namespace with the desktop distribution and so
intentionally has no `src/tuparles/__init__.py`.
