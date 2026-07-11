"""The display-only partial preview seam (#132): `pipeline.preview()`.

Partials used to ship RAW decoder text, so "slash impeccable" painted literally
while the final correctly delivered "/impeccable". preview() runs the pure text
stages (punctuation, lexicon, spoken syntax, casing) so the bubble shows the
product's own features live — but NOT collapse_repeats (flaps on a sliding
window) and NEVER command parsing (partials are pixels, not intents)."""

from tuparles import pipeline
from tuparles.pipeline import preview


class TestPreviewRewrites:
    def test_slash_impeccable(self):
        # The reported defect: the live preview must show the "/" the final lands.
        assert preview("slash impeccable") == "/impeccable"

    def test_spoken_punctuation_lands_live(self):
        # "virgule" → "," is the fidelity the user actually watches.
        assert preview("bonjour virgule le monde") == "Bonjour, le monde"

    def test_multiword_slash_command_canonicalises(self):
        assert preview("slash code review") == "/code-review"

    def test_casing_default_is_line_head_only(self):
        # Default casing is "preserve" (identity); only the punctuation stage's
        # line-head capital applies — a wrong autocorrect is worse than a mishear.
        assert preview("on ajoute le fallback") == "On ajoute le fallback"

    def test_empty_is_empty(self):
        assert preview("") == ""


class TestPreviewExcludesRepeatCollapse:
    """collapse_repeats is sentence-level and needs the near-final text; on a
    sliding tail window it would flap. preview() must leave repeats alone even
    where postprocess would collapse them."""

    def test_repeats_survive_in_preview(self):
        text = "je pense je pense je pense que oui"
        # postprocess collapses the run; preview must NOT (proves they differ).
        assert pipeline.postprocess(text) != text  # guard: this text IS collapsible
        assert preview(text) == "Je pense je pense je pense que oui"


class TestPreviewNeverRunsCommands:
    """Safety by construction: the command layer lives in the daemon, not the
    pipeline, so a previewed partial cannot execute an edit — the interlocks are
    simply never reached on this path."""

    def test_pipeline_does_not_import_the_command_layer(self):
        # By construction, not by care: the command layer is simply not in the
        # pipeline's namespace, so preview() (and postprocess()) cannot reach it.
        # (Checks the module's bound names, not prose — the docstrings mention it.)
        for name in ("parse", "parse_command", "quickchat", "expand_active", "Command"):
            assert getattr(pipeline, name, None) is None
        assert "tuparles.commands" not in [
            getattr(v, "__module__", "") for v in vars(pipeline).values()
        ]

    def test_command_phrase_passes_through_as_text(self):
        # A whole-take edit trigger ("efface efface") is text to preview(), never
        # an action — it comes back as words, not an executed command.
        out = preview("efface efface")
        assert isinstance(out, str)
        assert "efface" in out.lower()

    def test_preview_is_telemetry_free(self, monkeypatch):
        # on_fire=None by construction: a firing syntax feature must not emit
        # telemetry from the preview path (final-only, no ~1 Hz double counting).
        from tuparles import telemetry

        events = []
        monkeypatch.setattr(telemetry, "event", lambda *a, **k: events.append(a))
        preview("slash impeccable virgule oui")  # fires syntax + punctuation
        assert events == []
