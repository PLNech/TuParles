"""First-launch macOS permission gate (TCC).

Rebuilding TuParles.app swaps the executable, and macOS TCC keys its grants
to that binary: every reinstall can silently reset "Moniteur d'entrée"
(Input Monitoring, what pynput needs to hear the chord) and Microphone.
So the daemon probes at every boot, not just the first. The probes are
cheap preflights; the system dialogs appear only when a grant is missing,
and a request blocks until the dialog is answered — run before the
hotkey listener starts, so a grant given on the spot is used immediately.

The chord is checked through CoreGraphics (listen access), the mic through
AVFoundation: the old CG mic symbols are gone from recent macOS, and
pyobjc's Quartz never bound them — hence the darwin-only
pyobjc-framework-AVFoundation dependency.
"""

import sys
import threading

# Labels the user sees, in the order Réglages Système lists the panes.
_LISTEN = "Moniteur d'entrée (le raccourci)"
_MIC = "Micro"
_AX = "Accessibilité (le collage auto)"

# AVCaptureDevice.authorizationStatusForMediaType_: 3 = authorized,
# 2 = denied, 1 = restricted, 0 = not determined.
_AUTHORIZED, _NOT_DETERMINED = 3, 0


def missing_macos_permissions(prompt: bool = True) -> list[str]:
    """Labels of the grants TuParles is missing on this Mac.

    With `prompt`, missing grants trigger the system dialog. Empty list =
    all good (or not macOS, or bindings absent — the gate then assumes
    granted and never nags on a hunch; takes still self-report a dead mic
    with "Micro indisponible").
    """
    if sys.platform != "darwin":
        return []
    missing: list[str] = []
    if not _listen_granted(prompt):
        missing.append(_LISTEN)
    if not _mic_granted(prompt):
        missing.append(_MIC)
    if not _accessibility_granted():
        missing.append(_AX)
    return missing


def _accessibility_granted() -> bool:
    """Silent preflight only: AX has no not-determined state, so a prompt
    here would nag every boot. A missing grant still degrades gracefully —
    the paste falls back to the clipboard + manual Cmd+V — and the tray
    note names it."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
    except ImportError:
        return True
    return bool(AXIsProcessTrustedWithOptions({}))


def _listen_granted(prompt: bool) -> bool:
    try:
        from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
    except ImportError:
        return True  # no bindings: assume good rather than nag on a hunch
    if CGPreflightListenEventAccess():
        return True
    if prompt:
        CGRequestListenEventAccess()  # the system dialog; blocks until answered
    return CGPreflightListenEventAccess()


def _mic_granted(prompt: bool) -> bool:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except ImportError:
        return True
    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    if status == _AUTHORIZED:
        return True
    if status != _NOT_DETERMINED:
        return False  # denied or restricted: the user said no, don't re-ask
    if not prompt:
        return False
    done = threading.Event()
    granted: list[bool] = []

    def _answered(ok: bool) -> None:
        granted.append(ok)
        done.set()

    # requestAccess is asynchronous (private queue); block the boot until
    # the dialog is answered so the gate stays an honest gate.
    AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVMediaTypeAudio, _answered
    )
    done.wait(timeout=120)
    return bool(granted and granted[0])
