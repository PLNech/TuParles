"""Dict-seed feed (#68) — the initial_prompt builder. Pure: glossary/seeds/gate
are all injectable, so no vocab.txt or EDA cache is touched.

The bias is advisory (Whisper context), so these tests pin the *merge contract*:
manual wins on dedup and rides at the tail (truncation-safe), seeds fill ahead
of it, and the whole thing is gated by the setting.
"""

from tuparles import seed_prompt


def test_none_when_empty():
    assert seed_prompt.initial_prompt(manual=[], seeds=[], bias_enabled=True) is None


def test_manual_only_when_bias_off():
    out = seed_prompt.initial_prompt(
        manual=["RequestOptions"], seeds=["GeoRecord"], bias_enabled=False
    )
    assert out == "Glossaire : RequestOptions."


def test_seeds_precede_manual_at_tail():
    # manual at the tail survives Whisper's 224-token tail-keep
    out = seed_prompt.initial_prompt(
        manual=["mancurated"], seeds=["seedA", "seedB"], bias_enabled=True
    )
    assert out == "Glossaire : seedA, seedB, mancurated."


def test_manual_wins_dedup_case_insensitive():
    out = seed_prompt.initial_prompt(
        manual=["GeoRecord"], seeds=["georecord", "Facet"], bias_enabled=True
    )
    # the seed dup of GeoRecord is dropped; manual's casing is kept, at the tail
    assert out == "Glossaire : Facet, GeoRecord."


def test_seeds_ignored_when_bias_off_even_if_passed():
    out = seed_prompt.initial_prompt(manual=["a"], seeds=["b", "c"], bias_enabled=False)
    assert out == "Glossaire : a."


def test_gate_reads_setting(monkeypatch):
    monkeypatch.setattr(seed_prompt.settings, "get", lambda key: True)
    out = seed_prompt.initial_prompt(manual=["m"], seeds=["s"])
    assert out == "Glossaire : s, m."
    monkeypatch.setattr(seed_prompt.settings, "get", lambda key: False)
    assert seed_prompt.initial_prompt(manual=["m"], seeds=["s"]) == "Glossaire : m."
