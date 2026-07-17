# Android dictaphone : rebuild propre en Kotlin moderne

*2026-07-17 — décision de design. Contexte : le flow « voice note Signal → copier →
transcrire sur PC » a fait ses preuves ce matin même — en prouvant surtout qu'il
faut une vraie appli. Décision opérateur : full vision (record + STT on-device +
full-text search), codebase Kotlin fraîche, le POC sert d'inspiration sauf
exception méritée.*

## Ce qu'on garde du POC (audit du 2026-07-17)

Le POC (`android-poc-0.1`, préservé par son tag git) est mort en tant qu'app :
il monte le code Python desktop via Chaquopy (`../../src` en live), ce qui était
parfait pour valider le moteur et ne l'est pour rien d'autre. Mais l'audit a
trouvé du solide :

- **Le module gradle `whisper` est gardé tel quel** (l'exception méritée) :
  whisper.cpp vendored, CMake avec le fix `-O3`/NEON sur les targets ggml
  (`whisper/src/main/jni/whisper/CMakeLists.txt`), JNI `LibWhisper.kt`/`jni.c`
  avec `language="auto"` par défaut. Les deux bugs historiques (#2 POC) y sont
  corrigés *dans le code*.
- **Miné comme référence, pas copié** : `Audio.kt` (capture micro),
  `DictationService.kt` (foreground service), `fetch-android-model.sh`
  (modèles gitignorés : base 142MB / large-v3-turbo-q5_0 547MB).
- **Jeté** : tout le module `app` Chaquopy, la fonctionnalité debug/samples
  (« c'est passé, on n'en a plus trop l'utilité »).

Le rebuild se fait **en place** dans `android/` — pas de dossier `-v2`, git est
la couche de versioning, le POC vit dans son tag.

## Architecture cible

Single-activity **Compose**, ViewModel + StateFlow, **Hilt** (DI standard, pas
d'exotisme), **Room + FTS4** pour les notes, DataStore pour les réglages.
Toolchain déjà sur la machine : AGP 8.9, Kotlin 2.0, JDK 21, NDK 27, SDK 36 ;
minSdk remonte à 26 (plus de plancher Chaquopy).

Le cœur s'aligne sur le contrat portable esquissé dans l'issue #2 — c'est le
même geste : séparer le noyau (session, événements, capacités) des adaptateurs
de plateforme :

```
RecorderSession           # start/stop/cancel, émet Level + State
TranscriptionEngine       # suspend transcribe(wav) -> Transcript ; impl whisper.cpp
NotesRepository           # Room : Note(audio path, transcript?, date, durée)
```

L'appli est un *premier host* de ce contrat, pas une impasse de plus : quand
l'extraction en librairie (#2) viendra, ces interfaces sont la frontière.

## Doctrine appliquée

- **Dictaphone d'abord** : l'audio est TOUJOURS gardé (retranscriptible sur PC
  avec large-v3 — le téléphone décode en base/small, le desktop repasse derrière
  en qualité). C'est la dégradation gracieuse version mobile : le décode
  on-device peut échouer ou être médiocre, la note n'est jamais perdue.
- **Local-only structurel** : pas de permission `INTERNET` en release (héritage
  POC, conservé). Le partage sort par sharing intent (FileProvider pour l'audio,
  texte brut pour le transcript) — c'est l'utilisateur qui pousse, jamais l'app.
- **Whisper on-device** : modèle fetché par script au build (jamais commité),
  asset non compressé, singleton process-scoped, `language=auto` — les trois
  leçons du POC.

## Phases

- **A — squelette + record/save/share** : foreground service d'enregistrement
  (PCM16 16kHz mono → WAV), liste des notes, partage audio. APK utilisable pour
  la marche du matin : c'est la barre.
- **B — STT on-device** : brancher le module `whisper` derrière
  `TranscriptionEngine`, décode post-enregistrement (pas de streaming en phase B),
  modèle base/small quantisé (le sweet spot qualité/vitesse = issue #13).
- **C — recherche** : FTS sur les transcripts, recherche par mots-clés, partage
  du texte.

## Vérification

Pas d'AVD sur la machine (disque à 98% — pas d'image système avant nettoyage) :
build + tests JVM en CI locale, validation réelle sur le Fairphone 6 branché.
La barre de la phase A : « j'enregistre ma marche de demain matin avec ».
