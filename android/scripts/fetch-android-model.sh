#!/usr/bin/env bash
# Fetch the GGML model bundled into the experimental APK. It's gitignored (>100MB,
# over GitHub's file limit), so fetch it before building a self-contained APK.
#
#   ./scripts/fetch-android-model.sh         # base (142MB, fast, default bundle)
#   ./scripts/fetch-android-model.sh large   # large-v3-turbo (547MB, flawless, slow)
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
