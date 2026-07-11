"""The ribbon (#132): the "full" view grows WIDE first, then to at most
`bubble_lines`, with a compressed history register above the live tail.

Every layout DECISION is a pure function (measurement injected as a str->px
callable), so growth stages, the register split and the char budget are tested
headless with a fake measurer — no paint pass, like chip_color/state_color. One
offscreen widget test pins the wiring (skipped where Qt is absent)."""

import pytest


def _px_per_char(n: int):
    """A fake measurer: `n` px per character (spaces included). Deterministic, so
    the geometry maths is exact without a font."""
    return lambda s: len(s) * n


class TestCeilingWidth:
    def test_fraction_of_screen(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_ceiling_width

        assert ribbon_ceiling_width(1920, 0.92, 460) == round(1920 * 0.92)

    def test_never_below_the_fixed_pill(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_ceiling_width

        # A tiny screen fraction can't shrink below the 460 px pill floor.
        assert ribbon_ceiling_width(400, 0.5, 460) == 460

    def test_zero_fraction_is_the_fixed_pill(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_ceiling_width

        # The total override: 0 → the fixed 460 px footprint, no widening.
        assert ribbon_ceiling_width(3840, 0.0, 460) == 460


class TestWiden:
    def test_grows_with_content_between_bounds(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_widen

        assert ribbon_widen(600, 460, 960) == 600  # content-sized, mid-range

    def test_floors_at_fixed_width(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_widen

        assert ribbon_widen(120, 460, 960) == 460  # a short take stays a pill

    def test_caps_at_ceiling(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_widen

        assert ribbon_widen(5000, 460, 960) == 960  # a monologue caps at the screen


class TestCharBudget:
    def test_under_budget_is_untouched(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_budget

        assert ribbon_budget("court", 50) == "court"

    def test_over_budget_drops_oldest_behind_ellipsis(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import ribbon_budget

        out = ribbon_budget("a" * 100, 50)
        assert len(out) == 50
        assert out.startswith("…")
        assert out.endswith("a")  # the freshest tail is what's kept


class TestFitTrailingWords:
    """The register split core: longest suffix that fits, live = tail, rest =
    history. Bisection is monotone, so the answer is exact."""

    def test_longest_fitting_suffix(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import fit_trailing_words

        words = ["a", "b", "c", "d"]
        # avail 3 chars: "c d" (3) fits, "b c d" (5) doesn't → start=2.
        start, tail = fit_trailing_words(words, _px_per_char(1), 3)
        assert (start, tail) == (2, "c d")

    def test_all_words_fit(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import fit_trailing_words

        words = ["a", "b", "c"]
        start, tail = fit_trailing_words(words, _px_per_char(1), 10_000)
        assert (start, tail) == (0, "a b c")

    def test_never_returns_an_empty_tail(self):
        pytest.importorskip("PySide6")
        from tuparles.ui import fit_trailing_words

        # Even when nothing fits, keep the last word (it elides in paint).
        start, tail = fit_trailing_words(["a", "b", "c"], _px_per_char(1), 0)
        assert (start, tail) == (2, "c")


class TestPlanRibbon:
    """The growth stages: pill → widened single line → two registers."""

    def _plan(self, text, **over):
        from tuparles.ui import plan_ribbon

        kw = {
            "measure_live": _px_per_char(10),
            "measure_hist": _px_per_char(8),
            "screen_w": 1920,
            "max_frac": 0.5,  # ceiling 960
            "fixed_w": 460,
            "chrome_px": 100,
            "max_lines": 2,
        }
        kw.update(over)
        return plan_ribbon(text, **kw)

    def test_short_take_is_the_pill_single_line(self):
        pytest.importorskip("PySide6")
        layout = self._plan("hi")  # 20 px
        assert layout.single_line is True
        assert layout.width == 460  # floored at the pill
        assert layout.live == "hi" and layout.history == ""

    def test_medium_take_widens_but_stays_one_line(self):
        pytest.importorskip("PySide6")
        text = "a" * 50  # 500 px, fits one line inside the 960 ceiling
        layout = self._plan(text)
        assert layout.single_line is True
        assert layout.width == 600  # 100 chrome + 500 text, wide-first
        assert layout.live == text and layout.history == ""

    def test_long_take_splits_into_two_registers_at_the_ceiling(self):
        pytest.importorskip("PySide6")
        text = " ".join(["mot"] * 60)  # far wider than one 960-px line
        layout = self._plan(text)
        assert layout.single_line is False
        assert layout.width == 960  # capped at the ceiling
        assert layout.history and layout.live  # both registers populated
        # The split is a clean partition of the words (order preserved).
        assert (layout.history + " " + layout.live).split() == text.split()

    def test_single_line_setting_never_splits(self):
        pytest.importorskip("PySide6")
        text = " ".join(["mot"] * 60)
        layout = self._plan(text, max_lines=1)
        assert layout.single_line is True  # a 1-line strip elides, never splits
        assert layout.history == "" and layout.live == text

    def test_char_budget_trims_oldest_on_a_very_long_take(self):
        pytest.importorskip("PySide6")
        text = " ".join(["mot"] * 500)  # ~2000 chars, well past the budget
        layout = self._plan(text, max_chars=120)
        # The budget caps total visible chars; the oldest are dropped ("…").
        assert len(layout.history) + len(layout.live) <= 122
        assert layout.history.startswith("…")


class TestBubbleRibbonWiring:
    """Offscreen: setting a long take in the full view widens the widget and
    grows it to two lines; a short take stays the pill."""

    def _bubble(self, tmp_path, monkeypatch):
        pytest.importorskip("PySide6")
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        from tuparles.ui import Bubble

        b = Bubble(level_source=lambda: 0.0, view="full")

        # Pin a known screen so the ceiling is deterministic regardless of the
        # offscreen platform's default geometry.
        class _Screen:
            def availableGeometry(self):
                return QRect(0, 0, 1920, 1200)

        monkeypatch.setattr(b, "_target_screen", lambda: _Screen())
        b.start_recording()  # partials only paint while recording
        return b

    def test_short_take_stays_the_pill(self, tmp_path, monkeypatch):
        pytest.importorskip("PySide6")
        from tuparles.ui import HEIGHT, WIDTH

        b = self._bubble(tmp_path, monkeypatch)
        b.set_partial("salut")
        assert b.width() == WIDTH
        assert b.height() == HEIGHT

    def test_long_take_widens_and_grows_to_two_lines(self, tmp_path, monkeypatch):
        pytest.importorskip("PySide6")
        from tuparles.ui import HEIGHT, WIDTH

        b = self._bubble(tmp_path, monkeypatch)
        b.set_partial("mot " * 300)  # a long take
        assert b.width() > WIDTH  # widened along the bottom edge
        assert b.width() <= round(1920 * 0.92)  # never past the ceiling
        assert b.height() > HEIGHT  # a second (history) line appeared
        layout = b._ribbon_layout()
        assert layout.single_line is False
        assert layout.history and layout.live

    def test_width_setting_zero_pins_the_pill(self, tmp_path, monkeypatch):
        pytest.importorskip("PySide6")
        from tuparles import settings
        from tuparles.ui import WIDTH

        b = self._bubble(tmp_path, monkeypatch)
        settings.put("bubble_max_width", 0.0)  # the total override
        b.set_partial("mot " * 300)
        assert b.width() == WIDTH  # never widens past the fixed pill
