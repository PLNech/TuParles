"""The macOS permission gate: preflight when granted, prompt when missing,
honest about what is still missing after the dialog. Fake Quartz and
AVFoundation, forced darwin — the logic runs (and is tested) on every
platform the repo builds."""

import sys
import types

from tuparles import permissions

# authorizationStatusForMediaType_ vocabulary.
_AUTHORIZED, _DENIED, _NOT_DETERMINED = 3, 2, 0


def _fake_quartz(monkeypatch, *, listen: bool):
    state = {"listen": listen}
    quartz = types.ModuleType("Quartz")
    quartz.CGPreflightListenEventAccess = lambda: state["listen"]

    def _request():
        state["listen"] = True  # user answered OK

    quartz.CGRequestListenEventAccess = _request
    monkeypatch.setitem(sys.modules, "Quartz", quartz)


def _fake_avfoundation(monkeypatch, *, mic: int, grant_on_request: bool):
    calls = {"requests": 0}
    av = types.ModuleType("AVFoundation")
    av.AVMediaTypeAudio = "soun"

    class _CaptureDevice:
        @classmethod
        def authorizationStatusForMediaType_(cls, media):
            return mic

        @classmethod
        def requestAccessForMediaType_completionHandler_(cls, media, handler):
            calls["requests"] += 1
            handler(grant_on_request)

    av.AVCaptureDevice = _CaptureDevice
    monkeypatch.setitem(sys.modules, "AVFoundation", av)
    return calls


def _fake_appservices(monkeypatch, *, trusted: bool = True):
    ax = types.ModuleType("ApplicationServices")
    ax.AXIsProcessTrustedWithOptions = lambda options: trusted
    monkeypatch.setitem(sys.modules, "ApplicationServices", ax)


def _force_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


def test_all_granted_never_prompts(monkeypatch):
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=True)
    _fake_avfoundation(monkeypatch, mic=_AUTHORIZED, grant_on_request=False)
    _fake_appservices(monkeypatch, trusted=True)
    assert permissions.missing_macos_permissions(prompt=True) == []


def test_missing_chord_prompted_and_recovered(monkeypatch):
    # User answers the Input Monitoring dialog with OK: no labels out.
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=False)
    _fake_avfoundation(monkeypatch, mic=_AUTHORIZED, grant_on_request=False)
    _fake_appservices(monkeypatch, trusted=True)
    assert permissions.missing_macos_permissions(prompt=True) == []


def test_denied_mic_is_named_not_reasked(monkeypatch):
    # The user said no before: the label comes back, no dialog again.
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=True)
    _fake_appservices(monkeypatch, trusted=True)
    calls = _fake_avfoundation(
        monkeypatch, mic=_DENIED, grant_on_request=True
    )
    assert permissions.missing_macos_permissions(prompt=True) == ["Micro"]
    assert calls["requests"] == 0  # a denial is final; never nag on a hunch


def test_untrusted_accessibility_is_named_without_prompt(monkeypatch):
    # AX has no dialog of its own here: named in the tray note, never nagged.
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=True)
    _fake_avfoundation(monkeypatch, mic=_AUTHORIZED, grant_on_request=False)
    _fake_appservices(monkeypatch, trusted=False)
    assert permissions.missing_macos_permissions(prompt=True) == [
        "Accessibilité (le collage auto)"
    ]


def test_undetermined_mic_prompts_and_grants(monkeypatch):
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=True)
    _fake_avfoundation(monkeypatch, mic=_NOT_DETERMINED, grant_on_request=True)
    _fake_appservices(monkeypatch, trusted=True)
    assert permissions.missing_macos_permissions(prompt=True) == []


def test_undetermined_mic_prompts_and_is_denied(monkeypatch):
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=True)
    _fake_avfoundation(monkeypatch, mic=_NOT_DETERMINED, grant_on_request=False)
    _fake_appservices(monkeypatch, trusted=True)
    assert permissions.missing_macos_permissions(prompt=True) == ["Micro"]


def test_silent_probe_prompts_nothing(monkeypatch):
    # prompt=False (headless probe): missing grants are reported, no dialogs.
    _force_darwin(monkeypatch)
    _fake_quartz(monkeypatch, listen=False)
    _fake_avfoundation(monkeypatch, mic=_NOT_DETERMINED, grant_on_request=True)
    _fake_appservices(monkeypatch, trusted=True)
    assert permissions.missing_macos_permissions(prompt=False) == [
        "Moniteur d'entrée (le raccourci)",
        "Micro",
    ]


def test_missing_bindings_degrade_to_noop(monkeypatch):
    _force_darwin(monkeypatch)
    monkeypatch.setitem(sys.modules, "Quartz", None)  # ImportError path
    monkeypatch.setitem(sys.modules, "AVFoundation", None)
    monkeypatch.setitem(sys.modules, "ApplicationServices", None)
    assert permissions.missing_macos_permissions(prompt=True) == []
