#!/usr/bin/env bash
# Drive the debug install from adb. Never touches pl.nech.tuparles.
# Usage: drive-debug.sh [seconds]
# Prints take log lines and a status count. No transcript text.
set -euo pipefail

PKG=pl.nech.tuparles.debug
SVC=$PKG/pl.nech.tuparles.record.RecordingService
SECONDS_REC="${1:-3}"

adb shell pm grant "$PKG" android.permission.RECORD_AUDIO || true
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true

echo "==> start ${SECONDS_REC}s"
adb shell am start-foreground-service -n "$SVC" -a pl.nech.tuparles.START
sleep "$SECONDS_REC"
echo "==> stop"
adb shell am start-foreground-service -n "$SVC" -a pl.nech.tuparles.STOP
sleep 2
echo "==> status"
adb shell am broadcast -a pl.nech.tuparles.debug.STATUS \
  -n "$PKG/pl.nech.tuparles.debug.DebugStatusReceiver"
echo "==> take lines"
adb logcat -d -s TuParles:I TuParles:W | awk '/take |mic:|salvage|arm failed/'
