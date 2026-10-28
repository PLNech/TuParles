# Apple Silicon rung: mlx-whisper, same weights as the 4080

*2026-10-28. The desktop daemon was Linux-shaped: CUDA wheels and `evdev` were
hard dependencies, paste spoke X11 or Wayland, and the chord was Right Ctrl +
Right Alt. A MacBook dictation session needs a Metal rung and a chord the
built-in keyboard can press.*

## Why MLX, and why this model

The CUDA rung is faster-whisper `large-v3-turbo`. The point of the Mac rung is
that a code-switched take hears the **same model**, not a smaller cousin that
frenchifies the English tokens. mlx-community ships that weight converted for
MLX (`mlx-community/whisper-large-v3-turbo`), and `mlx-whisper` runs it on
Metal. The package is an optional group, imported only when `load_engine` is
on darwin and the import succeeds. A Mac without the group, or a load that
fails, lands on the existing CPU rung.

mlx-whisper's loop detects **one language per buffer**, not per segment the
way faster-whisper's `multilingual=True` does. The engine detects, then feeds
that language to every window of the same call, with the same sticky tracker
the CUDA partial path uses so one noisy window cannot flip the preview into
translator mode. Word timings come back without a probability; the doubt UI
already treats a missing score as "dim nothing".

## The chord

Right Ctrl + Right Alt cannot be pressed on a built-in Mac keyboard: there is
no right Control. Right Option + Right Command sit in the same corner, and
pynput reports them as `alt_r` and `cmd_r`. Linux is untouched.

Paste is `pbcopy` plus Cmd+V through System Events. Both the listener and the
keystroke need Accessibility. Without it the text still reaches the pasteboard
and the log says so.

## The synthetic bench (2026-10-28, M5 Max)

`scripts/bench_mlx.py`, macOS `say` (Thomas for FR and the blends, Samantha
for EN) resampled to 16 kHz. Four clips, 3.6–5.1 s. Times are warm: one silent
call pays for the download and the compile first. Full rows in
`docs/research/data/2026-10-28-mlx-bench.json`.

| Model | Warm decode | Blend ("fan out" / "ship") |
|---|---|---|
| whisper-tiny | 0.03 s | mangled ("fana ouc", "chiepe") |
| whisper-small-mlx | 0.06–0.09 s | mangled ("Fanaoute", "Chyp") |
| whisper-medium-mlx | 0.16–0.20 s | "fan-out" kept, "ship" kept, "feature" lost |
| whisper-large-v3-turbo | 0.17–0.18 s | "fan out" and "ship" kept; "feature" → "féature" |

Turbo is both the most faithful and as fast as medium on this chip, so it
stays the default. The 5-bit turbo (`whisper-large-v3-turbo-asr-5bit`)
downloads but its config carries `activation_dropout`, which mlx-whisper
0.4.3's `ModelDimensions` rejects. Not a candidate until the package catches
up.

This is a floor. A French TTS voice reading English tokens is the right
shape of trap and the wrong acoustics; the number that matters is a dictated
take.
