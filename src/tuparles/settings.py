"""User settings: tiny JSON in XDG config. Hand-editable, restart-proof."""

import json
import os
from pathlib import Path

_DEFAULTS: dict[str, object] = {
    # full = whole wrapped take (grows live) | minimal = one-line discreet pill.
    # Default full: for a dictation tool, seeing your whole take is the point —
    # a long take elided to ~5 words starves you of context. Minimal stays the
    # opt-in "discreet pill".
    "view": "full",
    "languages": [],  # ISO codes; empty = auto-detect among all 100
    "input_device": None,  # mic name; None/empty = system default
    "telemetry_enabled": True,  # LOCAL usage introspection; opt-out, never leaves the box
    # PII firewall (#102) — minimize before persist / analyze. Block-tier only
    # (checksum-validated IBAN/NIR/card + known secret prefixes): ~100% precision,
    # so auto-redaction destroys ~zero false positives. Alert-tier is never
    # auto-redacted. The denylist editor + operator profiles live in #107.
    "pii_redact_history": True,  # redact block-tier spans before they hit history.db
    "pii_denylist_block": [],  # user terms always redacted from the stored record
    "pii_denylist_alert": [],  # user terms surfaced but never auto-redacted
    "pii_analytics_min_count": 1,  # k-floor for the tag cloud; raise for k-anonymity
    # Update check (#86): opt-IN — a network call to GitHub reveals you run the
    # tool, so default off (local-first). `tuparles update` always works manually.
    "update_check_enabled": False,
    # Dict-seed bias (#68): fold codebase seed terms into Whisper's initial_prompt
    # so it spells your symbols right. Advisory only (never forces a decode), so
    # default on; the conservative post-correct is a separate gated step (#69).
    "dictseed_bias": True,
    # Spoken slashes (#53): every spoken "slash" → "/" (a path separator), with a
    # command ontology that canonicalises known names ("slash pré compact" →
    # "/pre-compact"). `slash_commands` extends that ontology with your own (a
    # flat list of names). The family as a whole toggles via settings["syntax"].
    "slash_commands": [],
    # Quick-chat / voice macros (#89): expand an anchored spoken trigger into a
    # canned text. Safe-on — an empty/absent phrasepack.json is a no-op, so it
    # can't fire until you write a macro. Structural match only (never fuzzy).
    "quickchat_enabled": True,
    # Personalized casing (#119/#120): re-case final text to your natural style.
    # "preserve" (default) = identity, ships dark — a wrong autocorrect is worse
    # than a visible mishear. Other styles: "lower" (lowkey all-lowercase),
    # "sentence" (Capitalize sentence starts only), "upper". The engine protects
    # URLs/identifiers/ALL-CAPS acronyms, but until smart proper-noun detection
    # (#122) lands, "lower" also lowercases names ("paris") and plural acronyms
    # ("apis") — that's the lowkey aesthetic, opt-in, not a bug.
    "casing_style": "preserve",
    # « Comment Tu Parles ? » onboarding (#80): first-launch / post-update perso
    # card. `onboarding_done` flips True once it runs; `onboarding_axes_seen`
    # records which perso axes the user has been offered, so a later release that
    # adds an axis re-surfaces only the new one. `role` (#90) is chosen here and
    # consumed by the quick-chat role packs once they exist.
    "onboarding_done": False,
    "onboarding_axes_seen": [],
    "role": "none",
    # Which screen the bubble appears on (multi-monitor). "primary" pins it to
    # the primary screen (default — deterministic, and identical to before on a
    # single monitor); "cursor" follows the screen under the mouse; "focus"
    # follows the active window's screen (X11; degrades to the cursor's screen on
    # native Wayland, where the focused window's geometry isn't queryable — never
    # a silent no-op); "all" mirrors the bubble on every monitor; any other value
    # is a QScreen.name() to pin to that monitor. Resolved fresh each take (see
    # ui.resolve_screens + BubbleGroup), so every mode — mirror included —
    # applies live, no restart.
    "bubble_screen": "primary",
    # Tray "breathing creature": the menubar glyph gently animates (a calm
    # breath at rest, livelier while recording, a travelling pulse while
    # decoding) for an alive feel. ~10 Hz icon updates travel over DBus on SNI
    # trays (GNOME/KDE) — default on, but a knob so a desktop that chokes on the
    # churn (or a battery-minded user) can fall back to a static glyph.
    "tray_animation": True,
    # Start cue (SPEC: "feedback que la dictée a démarré"): a soft tick the
    # instant capture goes live, so you know to speak. Opt-IN — a quiet local
    # tool shouldn't beep by default; the visual cue (bubble + livelier bars +
    # engine-coloured tray) is always on.
    "start_cue_sound": False,
    # Live partials on the CPU backend (#127). qwen can't stream, so the preview
    # comes from a separate small whisper on CPU — opt-out for a low-power box,
    # and `cpu_partials_model` picks size/quality ("base" default, "tiny" lighter).
    # GPU partials are unaffected (they ride the main model). If the small model
    # can't load, the CPU bubble degrades to waveform-only.
    "cpu_partials_enabled": True,
    "cpu_partials_model": "base",
    # CPU partials decode only this tail of the take (#3 follow-up). Shorter than
    # the GPU window (PARTIAL_WINDOW_S=20) on purpose: the small `base` model
    # picks ONE language per window, so a long French-dominant tail Frenchifies
    # the English you just switched into. A short window lets the *current*
    # language dominate, so the preview tracks what you're saying now. Trade-off:
    # less back-context shown + a brief lag flipping at a switch. GPU is untouched
    # (large-v3-turbo handles code-switch). Tune to taste; the captured-take
    # replay (#7) is how we settle the value on real audio.
    "cpu_partials_window_s": 6,
    # Onset context-carryover (#18): the first words of a take are the least
    # reliable (beam search has no left-context at the start — "on vient" →
    # "rien"). When a new take starts soon after the previous one landed, feed
    # that tail into the decode's initial_prompt so Whisper has the missing
    # left-context — exactly what helps a re-dictation after a delete. Advisory
    # only (never forces a decode, like dict-seed bias), so default on; GPU-only
    # in practice (qwen takes no prompt). Tune the recency window + cap.
    "context_carryover": True,
    "context_carryover_window_s": 25,
    "context_carryover_max_chars": 160,
    # How a dictated newline ("à la ligne") reaches the target (#5). A pasted
    # lone LF is SWALLOWED by submit-on-Enter inputs (Claude Code, chat apps) —
    # we said the line break, none appears. "auto" (default) pastes literal LF
    # everywhere except known GUI chat apps (which get Shift+Enter); "lf" forces
    # literal (editors/terminals/shells); "shift-enter" forces a soft newline;
    # "enter" sends Return. We can't tell a chat-TUI-in-a-terminal (Claude Code)
    # from a shell by window class — so dictating into Claude Code, set
    # "shift-enter" here. It's a setting: safe default, total override.
    "newline_mode": "auto",
    # Where a take pastes once decode runs off the capture thread (#14). With the
    # FIFO queue a take can finish decoding AFTER focus moved on (you spoke into
    # A, switched to B, A's decode lands). "origin" (default) refocuses the
    # window the take was dictated into, pastes, then returns focus to where you
    # were — so each take lands where it was spoken without stranding you.
    # "current" pastes into whatever holds focus at delivery (the pre-queue
    # behaviour). The dance only fires when focus ACTUALLY moved; a take with no
    # overlap pastes in place either way. X11 only — Wayland clients can't be
    # refocused by id. It's a setting: safe default, total override.
    "deliver_to": "origin",
    # How many takes may be decoding/queued before a new take is refused with a
    # toast (#14). The structural backstop: a wedged engine can't pile up audio
    # buffers unbounded. Five is generous for back-to-back dictation; raise it if
    # you routinely out-run the decoder.
    "queue_depth_cap": 5,
    # Show a small row of chips above the bubble, one per take still decoding in
    # the queue (#15) — so when takes overlap (#14) you can see how many are
    # still cooking and watch each flash as it lands. Cosmetic; the queue works
    # the same with them off. It's a setting: on by default, hide if you find the
    # extra motion noisy.
    "queue_chips": True,
    # One-time toast "Passé sur CPU — un peu plus lent" the first time the engine
    # falls back from GPU to CPU mid-session (#27). The bars already go green→blue,
    # but a colour shift alone can read as a bug; this names it so the change reads
    # as honest, not broken. Sticky for the session (the fallback is), shown once.
    # It's a setting: on by default, silence it if you know what blue means.
    "backend_toast": True,
    # Preserve and restore the user's clipboard around a take (#28). TuParles
    # pastes via the clipboard, which clobbers whatever you had copied. With this
    # on, we snapshot the clipboard before delivery and put it back after the paste
    # settles — your copy buffer survives a dictation. The tradeoff: the dictated
    # text is no longer left on the clipboard for a manual re-paste (and an app
    # that reads the clipboard unusually late could, rarely, paste the restored
    # value). Default OFF — the safe choice keeps the current re-paste behaviour
    # and never risks the core paste. It's a setting: opt in if you copy-paste
    # heavily between takes.
    "clipboard_restore": False,
    # Dev raw-audio capture (#8): write every take's UNREDACTED audio to disk
    # (takes/<id>.wav) so a fix can be replayed across engines/seeds — forensics
    # as infra. This is your literal voice on disk, not the PII-stripped
    # transcript, so it is OFF by default and, while armed, the tray shows a
    # steady red dot so it never runs silently. The TUPARLES_DEV env var
    # overrides this (set = wins). Local-only, self-pruning by byte budget.
    "dev_recording": False,
}


def config_dir() -> Path:
    # The injectable seam (core-extraction step 2): a frontend that doesn't live
    # under XDG — Android (Chaquopy surfaces getFilesDir()), a server container,
    # a test — points TUPARLES_CONFIG_DIR straight at its config dir. Unset =
    # the unchanged desktop behaviour ($XDG_CONFIG_HOME/tuparles, else ~/.config).
    # Shared by every per-user file (settings.json, vocab) so they can never land
    # in two different places.
    override = os.environ.get("TUPARLES_CONFIG_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tuparles"


def _path() -> Path:
    return config_dir() / "settings.json"


def get(key: str):
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data.get(key, _DEFAULTS.get(key))


def put(key: str, value) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
