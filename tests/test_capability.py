"""Cross-env capability probe + fallback chains (#29). The xdotool-3.x miss
showed we must PROBE tool capabilities, not assume them. These pin the probe and
the documented fallback chains against fabricated environments — no real tools
touched, every box simulated by injecting `run` + `present`."""

from tuparles import capability


def _env(present_tools, *, xdo_subs=(), versions=None):
    """A fake (run, present) for `probe`. `present_tools` is the installed set;
    `xdo_subs` the xdotool subcommands this build knows; `versions` maps a tool to
    its --version line."""
    versions = versions or {}

    def present(name):
        return name in present_tools

    def run(cmd):
        if cmd[:2] == ["xdotool", "version"]:
            return (0, "xdotool version 3.20160805.1", "")
        if cmd[:2] == ["xdotool", "help"]:
            sub = cmd[2]
            if sub in xdo_subs:
                return (0, f"Available commands:\n  {sub}", "")
            return (1, "", f"xdotool: Unknown command: {sub}")
        return (0, versions.get(cmd[0], ""), "")

    return run, present


class TestXdotoolSubcommandProbe:
    def test_old_xdotool_lacks_getwindowclassname(self):
        # The exact box that caused the bug: getactivewindow/windowactivate exist,
        # getwindowclassname does not — so the class chain must NOT pick it.
        run, present = _env(
            {"xdotool", "xprop", "xsel"}, xdo_subs=("getactivewindow", "windowactivate")
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        assert "getwindowclassname" not in caps.tools["xdotool"].note
        assert caps.chain("window_class").resolved == "xprop"

    def test_newer_xdotool_class_used_only_without_xprop(self):
        run, present = _env(
            {"xdotool"}, xdo_subs=("getactivewindow", "getwindowclassname")
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        # xprop absent → fall to the newer xdotool subcommand, not straight to empty
        assert caps.chain("window_class").resolved == "xdotool-getwindowclassname"

    def test_version_parsed(self):
        run, present = _env({"xdotool"}, xdo_subs=("getactivewindow",))
        caps = capability.probe(run=run, present=present, wayland=False)
        assert caps.tools["xdotool"].version == "3.20160805.1"


class TestX11Chains:
    def test_full_x11_box_resolves_native_layers(self):
        run, present = _env(
            {"xdotool", "xprop", "xsel", "xclip"},
            xdo_subs=("getactivewindow", "windowactivate", "getwindowclassname"),
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        assert caps.chain("window_class").resolved == "xprop"
        assert caps.chain("paste").resolved == "xsel+xdotool"
        assert caps.chain("window_activate").resolved == "xdotool-windowactivate"
        assert not any(c.degraded for c in caps.chains)
        assert caps.warnings == []  # xclip present → type-probe works → no gaps

    def test_xclip_absent_warns_about_clipboard_restore(self):
        run, present = _env(
            {"xdotool", "xprop", "xsel"}, xdo_subs=("getactivewindow", "windowactivate")
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        assert not caps.clipboard_types_probeable
        assert any("clipboard restore" in w for w in caps.warnings)

    def test_bare_box_degrades_to_documented_fallbacks(self):
        # No window tools at all: every chain resolves to its fallback, none crash.
        run, present = _env({"xdotool"}, xdo_subs=())
        caps = capability.probe(run=run, present=present, wayland=False)
        for c in caps.chains:
            assert c.resolved == c.fallback
            assert c.degraded
        assert len(caps.warnings) >= 3  # one per dead chain + the clipboard note


class TestWaylandChains:
    def test_wayland_box_uses_wayland_layers(self):
        run, present = _env({"wl-copy", "wl-paste", "ydotool", "gdbus"})
        caps = capability.probe(run=run, present=present, wayland=True)
        assert caps.display_server == "wayland"
        assert caps.chain("paste").resolved == "wl-copy+ydotool"
        assert caps.chain("window_class").resolved == "gnome-extension"
        assert caps.clipboard_types_probeable  # wl-paste present

    def test_wayland_activate_is_not_yet_available(self):
        run, present = _env({"wl-copy", "ydotool", "gdbus"})
        caps = capability.probe(run=run, present=present, wayland=True)
        # ActivateById isn't implemented → always the documented fallback
        assert (
            caps.chain("window_activate").resolved
            == caps.chain("window_activate").fallback
        )


class TestVersionSanitizing:
    def test_error_lines_are_not_shown_as_versions(self):
        run, present = _env(
            {"xdotool", "xprop"},
            xdo_subs=("getactivewindow",),
            versions={"xprop": "xprop: unrecognized argument --version"},
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        assert caps.tools["xprop"].version == ""  # noise scrubbed

    def test_real_version_kept(self):
        run, present = _env(
            {"xdotool", "notify-send"},
            xdo_subs=("getactivewindow",),
            versions={"notify-send": "notify-send 0.8.3"},
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        assert caps.tools["notify-send"].version == "notify-send 0.8.3"


class TestReport:
    def test_one_liner_has_the_shape(self):
        run, present = _env(
            {"xdotool", "xprop", "xsel", "xclip"},
            xdo_subs=("getactivewindow", "windowactivate"),
        )
        caps = capability.probe(run=run, present=present, wayland=False)
        line = caps.report()
        assert line.startswith("capabilities: x11")
        assert "class=xprop" in line and "paste=xsel+xdotool" in line
        assert "gaps: none" in line
        assert "\n" not in line  # genuinely one line

    def test_verbose_lists_every_tool(self):
        run, present = _env({"xdotool", "xprop"}, xdo_subs=("getactivewindow",))
        caps = capability.probe(run=run, present=present, wayland=False)
        verbose = caps.report(verbose=True)
        assert "✓ xprop" in verbose
        assert "✗ xclip" in verbose
        assert verbose.count("\n") >= len(caps.tools)
