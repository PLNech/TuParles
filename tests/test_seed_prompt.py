"""Dict-seed feed (#68) — the initial_prompt builder. Pure: glossary/seeds/gate
are all injectable, so no vocab.txt or EDA cache is touched.

The bias is advisory (Whisper context), so these tests pin the *merge contract*:
manual wins on dedup and rides at the tail (truncation-safe), seeds fill ahead
of it, and the whole thing is gated by the setting.
"""

from tuparles import seed_prompt


def test_none_when_empty():
    out = seed_prompt.initial_prompt(
        manual=[], seeds=[], commands=[], bias_enabled=True
    )
    assert out is None  # nothing to bias toward at all → no prompt


def test_manual_only_when_bias_off():
    out = seed_prompt.initial_prompt(
        manual=["RequestOptions"], seeds=["GeoRecord"], bias_enabled=False
    )
    assert out == "Glossaire : RequestOptions."


def test_seeds_precede_manual_at_tail():
    # manual at the tail survives Whisper's 224-token tail-keep
    out = seed_prompt.initial_prompt(
        manual=["mancurated"], seeds=["seedA", "seedB"], commands=[], bias_enabled=True
    )
    assert out == "Glossaire : seedA, seedB, mancurated."


def test_manual_wins_dedup_case_insensitive():
    out = seed_prompt.initial_prompt(
        manual=["GeoRecord"],
        seeds=["georecord", "Facet"],
        commands=[],
        bias_enabled=True,
    )
    # the seed dup of GeoRecord is dropped; manual's casing is kept, at the tail
    assert out == "Glossaire : Facet, GeoRecord."


def test_seeds_ignored_when_bias_off_even_if_passed():
    out = seed_prompt.initial_prompt(
        manual=["a"], seeds=["b", "c"], commands=["slash"], bias_enabled=False
    )
    assert out == "Glossaire : a."  # bias off drops seeds AND the command seed


def test_command_seed_rides_between_auto_seeds_and_manual():
    # The validated command seed sits just ahead of manual (both protected),
    # after the trimmable auto-seeds. 2026-06-28 take replay rescued take 16.
    out = seed_prompt.initial_prompt(
        manual=["MyName"],
        seeds=["seedA"],
        commands=["slash", "slash help"],
        bias_enabled=True,
    )
    assert out == "Glossaire : seedA, slash, slash help, MyName."


def test_command_seed_default_is_the_builtin():
    # Production passes commands=None → the built-in COMMAND_SEED is used.
    out = seed_prompt.initial_prompt(manual=[], seeds=[], bias_enabled=True)
    assert out is not None
    assert "slash precompact" in out  # the case that rescued take 16


def test_gate_reads_setting(monkeypatch):
    monkeypatch.setattr(seed_prompt.settings, "get", lambda key: True)
    out = seed_prompt.initial_prompt(manual=["m"], seeds=["s"], commands=[])
    assert out == "Glossaire : s, m."
    monkeypatch.setattr(seed_prompt.settings, "get", lambda key: False)
    assert seed_prompt.initial_prompt(manual=["m"], seeds=["s"]) == "Glossaire : m."


def test_budget_trims_auto_seeds_least_important_first():
    # ranked seeds: seed00 most important. With a small budget, the tail of the
    # seed list is dropped first; manual is always kept (2026-06-25 over-seeding
    # ablation — a stuffed prompt hallucinates).
    seeds = [f"seed{i:02d}" for i in range(80)]  # 80 * ~8 chars >> budget
    out = seed_prompt.initial_prompt(
        manual=["MyName"], seeds=seeds, commands=[], bias_enabled=True
    )
    assert out is not None
    assert len(out) <= seed_prompt._PROMPT_CHAR_BUDGET
    assert out.endswith("MyName.")  # manual survived, at the tail
    assert "seed00" in out  # most-important seed kept
    assert "seed79" not in out  # least-important seed trimmed


def test_command_seed_survives_budget_trim():
    # The command seed is protected like manual: a flood of auto-seeds trims
    # away but the command words and manual stay.
    seeds = [f"seed{i:02d}" for i in range(80)]
    out = seed_prompt.initial_prompt(
        manual=["MyName"], seeds=seeds, commands=["slash"], bias_enabled=True
    )
    assert out is not None
    assert len(out) <= seed_prompt._PROMPT_CHAR_BUDGET
    assert "slash, MyName." in out  # command seed + manual both at the tail
    assert "seed79" not in out


def test_budget_never_drops_manual_even_when_oversized():
    # a manual glossary alone larger than the budget is kept in full; only
    # auto-seeds are ever trimmed.
    big_manual = [f"Term{i:02d}" for i in range(80)]
    out = seed_prompt.initial_prompt(
        manual=big_manual, seeds=["dropme"], commands=[], bias_enabled=True
    )
    assert out is not None
    assert "dropme" not in out  # the auto-seed yields first
    assert "Term00" in out and "Term79" in out  # every manual term survives
