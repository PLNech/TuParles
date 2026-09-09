# Lending the GPU back: "free the resource" ≠ "don't take the resource"

The ask was small and the reasoning behind it was the interesting part: a
housemate wants the 4080 to train a model, so dictation should get off the
card. TuParles was holding **2316 MiB** while doing nothing at all.

## The fallback path was already there, and useless

The engine has fallen back to CPU since the beginning — that is the house
doctrine (*GPU-or-CPU, never GPU-or-nothing*), and `ResilientEngine` will drop
to the CPU rung when CUDA dies mid-session. The instinct is therefore to
trigger that existing path. It does not help, and the reason is worth writing
down:

```python
class GpuEngine:
    def __init__(self):
        _preload_cuda_libs()
        self._model = WhisperModel("large-v3-turbo", device="cuda", ...)
```

The VRAM is taken **in the constructor**. A fallback happens *after* the
object exists, so "build it and then stand down" leaves the memory exactly
where it was. The lever was never the decode; it was construction.

Which makes the discriminating test easy to state and easy to get wrong:

```python
assert calls == [], "prefer_cpu built a CUDA engine anyway"
```

Not `assert engine.transcribe(...).text == "cpu"` — a GPU that was built and
then abandoned passes that one, VRAM and all.

## Measured, because the clean sentence was not the true one

| when the preference is set | VRAM held | CUDA libs mapped |
|---|---|---|
| before launch | **0 MiB** | no |
| toggled mid-session | 2266 → **186 MiB** | yes |

The mid-session number is the honest surprise. Dropping the last reference and
collecting does return the model weights — ~2.1 GB of the 2.27 GB — but 186 MiB
stays, and no library call reclaims it: that is the CUDA *primary context*,
created when the libs initialised, destroyed when the process exits. So the
sentence we can actually stand behind is "the weights come back from the next
take, the last ~190 MB at the next restart", and setting the preference before
launch is the only way to hold literally nothing.

That is still a good feature. It is just not the frictionless one the first
draft of the changelog claimed.

## Where it lives, and why not where it looked like it should

The obvious spot is `load_engine()`: read the setting, return the CPU rung. It
is wrong, and subtly so — `_cpu_fallback_factory()` hands back a bare
`WhisperCppEngine`, an object with no reason to ever consult the setting again.
The toggle would have been one-way: off the GPU until a restart, no matter how
many times you unticked the box.

So the preference lives inside `ResilientEngine`, which already owns the
"which silicon is live" state machine, with the GPU simply left unbuilt
(`self._gpu = None if prefer else gpu_factory()`). Toggling on rides the exact
sticky-fallback path suspend/resume already exercises, so the bubble colour,
telemetry and partials all follow with no second mechanism to keep in step.

One piece of state had to be added: **why** we are on CPU.

```python
self._on_cpu_reason = "preference" | "failure" | None
```

Without it, unticking the box on a session whose GPU had genuinely died would
try to resurrect a dead card, and every take after would pay ~1.6 s to
rediscover that. A preference can be undone; a dead card cannot.

## A test-isolation bug this uncovered

`settings.get` re-reads `$XDG_CONFIG_HOME/tuparles/settings.json` on every
call, and the suite had no `conftest.py`. That was survivable while no engine
read a setting at construction time. The moment `prefer_cpu` reached
`ResilientEngine.__init__`, ticking a box in Réglages could turn a green suite
red — the worst kind of flake, because it presents as a code failure on a
machine where nothing changed but a config file. There is now an autouse
fixture pointing both `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` at a tmp dir.

A feature that reads user state at construction time makes every test that
constructs it a test of the developer's own settings.
