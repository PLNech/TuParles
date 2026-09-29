"""The Analytics dashboard: a local mirror of what you say, do, and code.

Three tabs, rendered on demand in a worker so opening the dialog stays responsive:

* **Ton usage** — feature-usage counts + the discovery gap (which spoken-syntax
  features you have never reached). Pure sqlite, instant.
* **Ta voix** — a tag cloud + keyphrases over your dictation history, via the
  nlp engine at personal scale.
* **Ton code** — the last cached codebase EDA (read from disk, never computed
  live: a corpus build on the GUI thread would freeze the desktop, and the
  watchdog at daemon.py would say so).

Everything here is local. Nothing is uploaded; this window is the whole product
surface for "which features earn their place?".
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
)

from tuparles import syntax
from tuparles.telemetry import enabled, introspect


def _bar(n: int, peak: int, width: int = 16) -> str:
    return "█" * round(width * n / peak) if peak else ""


def _usage_html() -> str:
    s = introspect.usage_summary()
    if s["total"] == 0:
        return "<p>Aucune donnée d'usage pour l'instant. Dicte un peu — tout reste sur ta machine.</p>"
    out = [f"<h3>Ton usage</h3><p>{s['total']} évènements enregistrés, localement.</p>"]

    def _table(title: str, counts: dict) -> str:
        if not counts:
            return f"<p><b>{title}</b> — rien encore.</p>"
        peak = max(counts.values())
        rows = "".join(
            f"<tr><td><code>{k}</code></td><td align=right>{v}</td>"
            f"<td><tt>{_bar(v, peak)}</tt></td></tr>"
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
        )
        return f"<p><b>{title}</b></p><table width=100%>{rows}</table>"

    out.append(_table("Entrée (raccourci vs barre)", s["entry_split"]))
    out.append(_table("Commandes vocales", s["commands"]))
    out.append(_table("Syntaxe parlée", s["syntax_used"]))

    # The discovery gap: registered syntax features you have never triggered.
    used = set(s["syntax_used"])
    never = [name for name in syntax.registered() if name not in used]
    if never:
        items = "".join(f"<li><code>{n}</code></li>" for n in never)
        out.append(
            "<p><b>Jamais utilisé</b> — des fonctions de syntaxe que tu n'as "
            f"pas encore essayées :</p><ul>{items}</ul>"
        )
    return "".join(out)


def _voice_html() -> Iterator[str]:
    """Show the cloud before the slower keyphrase pass completes."""
    if not introspect.nlp_available():
        yield (
            "<p>L'analyse de la voix a besoin des extras <code>nlp</code>. "
            "Installe-les avec <code>poetry install --with nlp</code>.</p>"
        )
        return
    tags = introspect.utterance_tags(top=40)
    if not tags:
        yield "<p>Pas encore de dictées à analyser.</p>"
        return
    cloud = " ".join(
        f"<span style='font-size:{8 + round(w * 22)}px'>{surface}</span>"
        for surface, w in tags
    )
    out = [f"<h3>Ta voix</h3><p>{cloud}</p>"]
    yield "".join(out) + "<p>Chargement des expressions clés…</p>"
    phrases = introspect.utterance_keyphrases(top=12)
    if phrases:
        items = "".join(f"<li>{p}</li>" for p, _score in phrases)
        out.append(f"<p><b>Expressions clés</b></p><ul>{items}</ul>")
    yield "".join(out)


def _code_html() -> str:
    data = introspect.corpus_analysis()
    if data is None:
        return (
            "<p>Aucune analyse de code en cache. Lance "
            "<code>poetry run python scripts/nlp_eda.py</code> pour en générer "
            "une.</p>"
        )
    repos = ", ".join(data.get("repos", [])) or "?"
    out = [
        f"<h3>Ton code</h3><p><i>Dernière analyse — {repos} · "
        f"{data.get('n_terms', 0):,} termes, "
        f"{data.get('n_candidates', 0):,} candidats.</i></p>"
    ]
    seeds = data.get("top_seeds", [])[:20]
    if seeds:
        rows = "".join(
            f"<tr><td><code>{s['surface']}</code></td>"
            f"<td align=right>risque {s['risk']:.2f}</td></tr>"
            for s in seeds
        )
        out.append(
            "<p><b>Termes à amorcer</b> (les mots de ton code que la dictée "
            f"rate le plus) :</p><table width=100%>{rows}</table>"
        )
    clusters = data.get("clusters", [])
    if clusters:
        items = "".join(
            f"<li>{', '.join(c.get('theme', []))}</li>" for c in clusters[:8]
        )
        out.append(f"<p><b>Thèmes</b></p><ul>{items}</ul>")
    return "".join(out)


class _RenderSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(int, str, bool)


class _RenderTab(QRunnable):
    """Compute HTML without touching a widget from the worker thread."""

    def __init__(self, index: int, render: Callable[[], str | Iterator[str]]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.index = index
        self.render = render
        self.signals = _RenderSignals()

    def run(self) -> None:
        html = ""
        try:
            result = self.render()
            if isinstance(result, str):
                html = result
            else:
                for html in result:
                    self.signals.progress.emit(self.index, html)
            failed = False
        except Exception:
            failed = True
        self.signals.finished.emit(self.index, html, failed)


class AnalyticsDialog(QDialog):
    """Local introspection in one window. Opened from the tray (#101)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TuParles — Analytics")
        self.setMinimumSize(460, 560)
        layout = QVBoxLayout(self)
        if not enabled():
            banner = QLabel(
                "⚠ Le suivi d'usage est désactivé — « Ton usage » ne se "
                "remplira pas tant qu'il l'est (Réglages › Confidentialité)."
            )
            banner.setWordWrap(True)
            layout.addWidget(banner)
        self._tabs = QTabWidget()
        self._views = []
        self._loaded: set[int] = set()
        self._workers: dict[int, _RenderTab] = {}
        self._closed = False
        self._renderers = (_usage_html, _voice_html, _code_html)
        for title in ("Ton usage", "Ta voix", "Ton code"):
            view = QTextBrowser()
            view.setOpenExternalLinks(True)
            view.setHtml("<p>Chargement…</p>")
            self._tabs.addTab(view, title)
            self._views.append(view)
        self._tabs.currentChanged.connect(self._load_tab)
        layout.addWidget(self._tabs)
        QTimer.singleShot(0, self._load_current_tab)

    def _load_current_tab(self) -> None:
        if not self._closed:
            self._load_tab(self._tabs.currentIndex())

    @Slot(int)
    def _load_tab(self, index: int) -> None:
        if self._closed or index < 0 or index in self._loaded or index in self._workers:
            return
        worker = _RenderTab(index, self._renderers[index])
        self._workers[index] = worker  # keep the signal sender alive through delivery
        worker.signals.progress.connect(self._render_progress)
        worker.signals.finished.connect(self._render_finished)
        QThreadPool.globalInstance().start(worker)

    @Slot(int, str)
    def _render_progress(self, index: int, html: str) -> None:
        if not self._closed:
            self._views[index].setHtml(html)

    @Slot(int, str, bool)
    def _render_finished(self, index: int, html: str, failed: bool) -> None:
        self._workers.pop(index, None)
        if self._closed:
            return
        if failed:
            self._views[index].setHtml(
                html.replace("<p>Chargement des expressions clés…</p>", "")
                + "<p>Impossible de terminer cette analyse. Réessaie en rouvrant Analytics.</p>"
            )
        else:
            self._views[index].setHtml(html)
            self._loaded.add(index)

    def closeEvent(self, event) -> None:
        self._closed = True
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._closed = True
        super().done(result)
