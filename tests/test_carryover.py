"""Onset context-carryover (#18) — pure decision + prompt composition. Bias-only:
a recent take's tail rides the next decode's initial_prompt to fix cold-start
onset ("on vient" → "rien")."""

from tuparles.engine import _compose_prompt, carryover_context

OPTS = {"enabled": True, "window_s": 25.0, "max_chars": 160}


def test_recent_take_carries_its_tail():
    out = carryover_context("On veut sécuriser le DNS.", age_s=3.0, **OPTS)
    assert out == "On veut sécuriser le DNS."


def test_stale_take_does_not_carry():
    assert carryover_context("trop vieux", age_s=99.0, **OPTS) is None


def test_disabled_never_carries():
    assert (
        carryover_context("x", age_s=1.0, enabled=False, window_s=25, max_chars=160)
        is None
    )


def test_empty_history_is_none():
    assert carryover_context("", age_s=1.0, **OPTS) is None


def test_caps_to_the_tail():
    long = "mot " * 100  # 400 chars
    out = carryover_context(long, age_s=1.0, enabled=True, window_s=25, max_chars=20)
    assert out is not None and len(out) <= 20


class TestComposePrompt:
    def test_context_rides_the_tail(self):
        # closest to the decode = strongest bias (Whisper keeps the last tokens)
        assert _compose_prompt("Glossaire : DNS", "phrase d'avant") == (
            "Glossaire : DNS phrase d'avant"
        )

    def test_no_context_keeps_vocab_prompt(self):
        assert _compose_prompt("Glossaire : DNS", None) == "Glossaire : DNS"

    def test_context_only_when_no_vocab(self):
        assert _compose_prompt(None, "phrase d'avant") == "phrase d'avant"

    def test_both_none(self):
        assert _compose_prompt(None, None) is None
