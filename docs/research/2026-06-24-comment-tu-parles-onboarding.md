# « Comment Tu Parles ? » — the personalization front door

*2026-06-24. The pun is the product: TuParles → comment tu parles ? ("how do you
talk?", and playfully "mind your language"). A tiny, sleek, skippable card that,
on first launch, asks a few personalization questions — each with a smart default
already chosen — and turns the moats we have been building (casing #120, role
packs #90, languages) into something a new user meets in the first 30 seconds.*

## Why now

The re-case engine (#120) shipped with **no UI that writes `casing_style`** — it
is dark by design. The onboarding card is the natural first writer: it is the
moment a user picks "minuscules" or "Phrase" and the engine wakes up. Same for
role packs and languages. The personalization layer needed a front door; this is
it. (Coupling worth remembering: once this card can write a non-`preserve`
casing style, the #59 voice-caps × #120 composition stops being latent — that is
the #121 work. Region all-caps already composes for free; next-word single caps
is the piece #121/#126 must handle.)

## The shape (elicited with the user)

Four perso axes, in carousel order, each "it's a setting" with a conservative
default and total override in Réglages after:

| Axis | Question | Choices | Default |
|------|----------|---------|---------|
| **Ton style** | Comment tu écris ? | Préservé / minuscules / Phrase | Préservé |
| **Ton rôle** | Tu fais quoi ? | Aucun / Eng / Product / Design / Marketing / Strategy | Aucun |
| **Tes langues** | Tu parles quoi ? | FR+EN / FR / EN / Auto | FR+EN |
| **Ta vue** | Comment tu vois ? | Pilule / Texte complet | Pilule |

**Animation:** an auto-cycling carousel that *defiles* on its own, **plus a live
preview and a live input demo** — the user can type/dictate into a sample box and
watch their choices apply in real time. The preview must run the **real**
pipeline (`casing.recase`, the quick-chat pack) so it can never show a style the
engine would not actually produce. Honesty over flash.

**Triggers (all three):** first launch; first run after an update that *added* an
axis (only the new one is surfaced, alongside what's-new #82); and a manual
"Rejouer l'intro" from Réglages so it is never a one-shot you miss.

## Architecture — core then view (the house pattern)

`onboarding.py` is the **pure, testable core** (shipped): the trigger logic
(`axes(force=)`, tracked by `onboarding_done` + `onboarding_axes_seen`), the
axes as data, `preview(key, value)` over the real engine, and `apply_choices`
writing each choice to settings. No Qt, no GPU, no heavy deps.

Views ride on top, and there are **two** — graceful degradation made literal
(the standing doctrine: every feature GPU-or-CPU, and here Qt-or-terminal):
- the **Qt carousel** (the sleek animated card) — the rich view;
- a **no-Qt text mode** (`tuparles onboarding`, numbered choices) — the fallback
  that still works headless / on a minimal install.

Both are thin renders of the same core, so they cannot diverge — the same
discipline as the cheat-sheet core/panel (#83) and what's-new (#82).

## Honest gaps

- **Ton rôle** records the choice (`role` setting) but has no effect until the
  role phrase packs (#90) exist; its preview names the role rather than faking a
  macro. When #90 lands, the preview upgrades to a real sample expansion.
- The animated carousel + live-input demo (the view) is the next build; the core
  is ready for it.

> *« On reconnaît l'arbre à ses fruits, et l'outil à sa première poignée de
> main. »* — the first handshake is the onboarding; make it feel like you.
