#!/usr/bin/env bash
# Fetch a GGML model into app/src/main/assets/models/ for a DEV bundled build. It's
# gitignored (>100MB, over GitHub's file limit).
#
# NOTE (lean APK, #13): the app no longer bundles a model — it downloads one at first
# run, and the build EXCLUDES assets/models from packaging (app/build.gradle.kts:
# `ignoreAssetsPatterns += "models"`). So a plain build stays lean (~45MB) even if this
# script has run. To make an offline demo APK that ships a model, fetch it here AND drop
# that one exclusion line; the engine keeps the asset-load path. For everyday testing,
# just run the app and download a model in Réglages.
#
#   ./scripts/fetch-android-model.sh         # base (fast, light)
#   ./scripts/fetch-android-model.sh large   # large-v3-turbo (flawless, slow)
set -euo pipefail

variant="${1:-base}"
case "$variant" in
  base)  name="ggml-base.bin" ;;
  large) name="ggml-large-v3-turbo-q5_0.bin" ;;
  *) echo "usage: $0 [base|large]"; exit 1 ;;
esac

here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$here/app/src/main/assets/models/$name"
mkdir -p "$(dirname "$dest")"

if [ -f "$dest" ]; then
  echo "already present: $dest"
  exit 0
fi

echo "fetching $name → $dest"
curl -L -o "$dest" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$name"
echo "done. Set MODEL_NAME in MainActivity.kt to \"$name\" if you bundled a non-default."
