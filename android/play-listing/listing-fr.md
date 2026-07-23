# Play store listing — source of truth for graphics + text (uploaded via `tools/play.py`)

This directory holds the canonical Google Play store-listing assets for TuParles
Android (`pl.nech.tuparles`): the two graphics below and the fr-FR listing text.
Edit here, then push to Play with `tools/play.py set-listing` / `upload-image`.

## Graphics

| Asset | File | Dimensions | Composition |
|-------|------|-----------|-------------|
| Store icon | `icon.png` | 512×512 PNG | Full-bleed navy (`#1B2A4A`); the app's real white microphone glyph centered, ~41% wide × ~53% tall, inside the central 66% safe zone. No text. |
| Feature graphic | `feature-graphic.png` | 1024×500 PNG | Navy background; centered block — white mic glyph (~300px tall) on the left, then the bold white wordmark "TuParles" with the tagline "Dictaphone local et privé" in `#9FB3D9` beneath it. ~126px side margins. |

Both derive from the real adaptive-icon foreground
(`android/app/src/main/res/drawable/ic_launcher_foreground.xml`) so the store
brand and the on-device icon stay identical.

## Listing text (fr-FR)

- **Title**: `TuParles`
- **Short description** (≤80): `Dictaphone local et privé`
- **Full description** (≤4000):

> TuParles, c'est un dictaphone 100% Open-Source, Libre, et Privé. Ta voix reste sur ton appareil, et tu peux exporter les audios ou le texte de tes notes vocales.

## Notes

- Phone screenshots are provided separately by a human and are not tracked here.
- Publishing is human-gated for Data-safety / declarations in the Play Console.
