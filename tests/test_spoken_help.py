"""Spoken help (#85): "que peux-tu faire" → the cheat-sheet, via notification.

Three layers, all no-GPU/no-Qt: the command recognizes a whitelist of help
phrases (structurally safe, never bare "aide"); cheatsheet.as_text renders the
sheet (the one renderer the CLI, this, and a future panel share); execute_command
pops it as a fire-and-forget desktop notification.
"""

from tuparles import cheatsheet, commands, delivery


class TestHelpCommand:
    def test_phrases_parse_to_help(self):
        for phrase in (
            "que peux-tu faire",
            "Que peux-tu faire ?",
            "what can you do",
            "liste des commandes",
            "aide tuparles",
        ):
            cmd = commands.parse(phrase)
            assert cmd is not None and cmd.action == "help", phrase

    def test_bare_aide_or_help_is_not_a_command(self):
        # collide with prose ("à l'aide", "help me out") → must stay text
        assert commands.parse("aide") is None
        assert commands.parse("help") is None
        assert commands.parse("à l'aide je suis bloqué") is None

    def test_help_phrase_in_a_long_take_is_text(self):
        long = "que peux-tu faire avec ce nouveau framework de test unitaire stp"
        assert commands.parse(long) is None  # over MAX_COMMAND_TOKENS


class TestAsText:
    def test_full_has_categories_and_triggers(self):
        text = cheatsheet.as_text()
        assert "Commandes" in text and "Ponctuation" in text and "Syntaxe" in text
        assert "·" in text  # trigger bullets rendered

    def test_brief_is_shorter_and_has_no_bullets(self):
        full = cheatsheet.as_text()
        brief = cheatsheet.as_text(brief=True)
        assert len(brief) < len(full)
        assert "·" not in brief

    def test_query_filters(self):
        assert "quotes" in cheatsheet.as_text("guillemets")
        assert cheatsheet.as_text("zzz-nope").startswith("Rien")


class TestExecuteHelp:
    def test_returns_label_and_pops_notification(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _x: "/usr/bin/notify-send")
        monkeypatch.setattr(
            delivery.subprocess, "Popen", lambda *a, **k: calls.append(a)
        )
        label = delivery.execute_command(commands.Command("help"))
        assert label == "aide affichée"
        assert calls, "notify-send was not launched"

    def test_no_notify_send_points_at_the_cli(self, monkeypatch):
        monkeypatch.setattr(delivery.shutil, "which", lambda _x: None)
        label = delivery.execute_command(commands.Command("help"))
        assert "cheatsheet" in label

    def test_notification_failure_never_raises(self, monkeypatch):
        monkeypatch.setattr(delivery.shutil, "which", lambda _x: "/usr/bin/notify-send")

        def boom(*a, **k):
            raise OSError("no session bus")

        monkeypatch.setattr(delivery.subprocess, "Popen", boom)
        # a help that can't notify must still return cleanly, like all delivery
        assert delivery.execute_command(commands.Command("help")) == "aide affichée"
