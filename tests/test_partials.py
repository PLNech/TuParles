"""Sticky partial language (2026-07-15): the translation-flip guard.

With 2+ selected languages, one short/noisy partial window mis-picking the
language flips Whisper into genuine translation. These pin the pure hysteresis
logic (`StickyLanguage`) and the candidate restriction (`pick_language`) —
headless, no model, like the sanity filter in test_partials_sanity.py.
"""

from tuparles.partials import StickyLanguage, pick_language


class TestPickLanguage:
    def test_restricts_to_selected_languages(self):
        # A spurious global winner outside the selection can never win.
        probs = [("nl", 0.45), ("fr", 0.35), ("en", 0.15)]
        assert pick_language(probs, ["en", "fr"]) == ("fr", 0.35)

    def test_unrestricted_when_no_selection(self):
        probs = [("nl", 0.45), ("fr", 0.35)]
        assert pick_language(probs, []) == ("nl", 0.45)

    def test_falls_back_to_global_best_when_selection_absent(self):
        # Defensive: detection returned a probs list without any selected
        # language at all (shouldn't happen — fw lists every language).
        probs = [("nl", 0.9)]
        assert pick_language(probs, ["en", "fr"]) == ("nl", 0.9)

    def test_empty_input(self):
        assert pick_language(None, ["en"]) == (None, 0.0)
        assert pick_language([], ["en"]) == (None, 0.0)

    def test_raw_probability_not_renormalized(self):
        # 0.3/0.3 en/fr is genuine ambiguity — restricting to {en, fr} must not
        # inflate it into fake certainty (the confidence gate reads raw mass).
        probs = [("en", 0.31), ("fr", 0.30), ("de", 0.39)]
        lang, prob = pick_language(probs, ["en", "fr"])
        assert lang == "en" and prob == 0.31


class TestStickyLanguage:
    def test_first_confident_window_locks(self):
        t = StickyLanguage(confidence=0.6, stable=2)
        assert t.update("fr", 0.9) == "fr"

    def test_first_unconfident_window_stays_none(self):
        # Below the floor we condition on nothing (language=None downstream)
        # rather than bias the decode with a low-confidence token.
        t = StickyLanguage(confidence=0.6, stable=2)
        assert t.update("fr", 0.4) is None
        assert t.language is None

    def test_single_flaky_window_does_not_switch(self):
        # THE bug: one mis-picked window mid-take flipped partials into
        # translation. Sticky now: en stays en.
        t = StickyLanguage(confidence=0.6, stable=2)
        t.update("en", 0.9)
        assert t.update("fr", 0.95) == "en"  # confident but not yet stable
        assert t.update("en", 0.9) == "en"  # back home; streak broken

    def test_two_consecutive_confident_windows_switch(self):
        # A deliberate mid-take language change lands after ~a sentence.
        t = StickyLanguage(confidence=0.6, stable=2)
        t.update("en", 0.9)
        assert t.update("fr", 0.8) == "en"
        assert t.update("fr", 0.8) == "fr"  # stable → switch

    def test_unconfident_window_breaks_the_streak(self):
        t = StickyLanguage(confidence=0.6, stable=2)
        t.update("en", 0.9)
        t.update("fr", 0.8)  # streak 1
        t.update("fr", 0.4)  # unconfident: consecutive means consecutive
        assert t.update("fr", 0.8) == "en"  # streak restarted at 1
        assert t.update("fr", 0.8) == "fr"

    def test_candidate_change_restarts_streak(self):
        t = StickyLanguage(confidence=0.6, stable=2)
        t.update("en", 0.9)
        t.update("fr", 0.8)  # candidate fr, streak 1
        assert t.update("de", 0.8) == "en"  # different candidate → streak 1
        assert t.update("de", 0.8) == "de"

    def test_reset_clears_everything(self):
        t = StickyLanguage(confidence=0.6, stable=2)
        t.update("en", 0.9)
        t.reset()
        assert t.language is None
        assert t.update("fr", 0.9) == "fr"  # fresh take, fresh lock

    def test_none_detection_is_unconfident(self):
        t = StickyLanguage(confidence=0.6, stable=2)
        t.update("en", 0.9)
        assert t.update(None, None) == "en"
