"""The demo spine: hotkey → record → transcribe → punctuate → deliver.

Single-shot decode for now (no live partials yet) — tap to start, speak,
tap again, text lands in the focused window a few seconds later.
"""

import subprocess
import threading

from tuparles.audio import Recorder
from tuparles.delivery import deliver
from tuparles.engine import load_engine
from tuparles.punctuation import apply_spoken_punctuation


def _notify(msg: str, ms: int = 2000) -> None:
    # Fire-and-forget: notify-send blocks on the notification server's reply
    # and GNOME's daemon sometimes stalls for seconds. Never wait, never raise.
    try:
        subprocess.Popen(
            ["notify-send", "-a", "TuParles", "-t", str(ms), "TuParles", msg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


class Daemon:
    def __init__(self) -> None:
        self._recorder = Recorder()
        self._engine = load_engine()
        self._busy = threading.Lock()

    def toggle(self) -> None:
        if self._recorder.recording:
            audio = self._recorder.stop()
            seconds = len(audio) / 16_000
            _notify(f"⏳ Transcribing {seconds:.0f}s…")
            threading.Thread(
                target=self._finish, args=(audio,), daemon=True
            ).start()
        else:
            self._recorder.start()
            _notify("🎙️ Recording — tap again to stop")

    def _finish(self, audio) -> None:
        if not self._busy.acquire(blocking=False):
            _notify("⚠️ Still transcribing the previous take")
            return
        try:
            text = apply_spoken_punctuation(self._engine.transcribe(audio))
            if text:
                deliver(text)
                _notify(f"✅ {text[:80]}")
            else:
                _notify("🤷 Nothing heard")
        except Exception as exc:  # surface, never crash the daemon
            _notify(f"❌ {exc}", ms=5000)
        finally:
            self._busy.release()


def run() -> None:
    from tuparles.hotkey import HotkeyListener

    daemon = Daemon()
    listener = HotkeyListener(on_toggle=daemon.toggle)
    listener.start()
    print("TuParles daemon up — Right Ctrl + Right Alt to dictate. Ctrl-C quits.")
    try:
        listener.join()
    except KeyboardInterrupt:
        print("\nÀ la prochaine.")
