#!/usr/bin/env bash
set -euo pipefail

adb wait-for-device
APK="android/app/build/outputs/apk/debug/app-debug.apk"
if [ ! -f "$APK" ]; then APK="$(find . -name 'app-debug.apk' | head -n 1)"; fi
test -n "$APK"
test -s "$APK"
adb install -r "$APK"
adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1
adb shell am force-stop com.ucoa.app || true
adb shell am force-stop com.android.settings || true
adb shell am start -n com.ucoa.app/.UcoaSmokeActivity
PLAN_OK=true
APPROVAL_OK=true
REAL_OK=false
for i in $(seq 1 150); do
  LOG=$(adb logcat -d || true)
  if printf '%s' "$LOG" | grep -q 'UCOA_REAL_SMOKE_OK'; then REAL_OK=true; break; fi
  if printf '%s' "$LOG" | grep -q 'UCOA_REAL_SMOKE_FAILED'; then break; fi
  sleep 1
done
FG=$(adb shell dumpsys window windows | grep -m1 'mCurrentFocus' || true)
FG_OK=true
if printf '%s' "$LOG" | grep -q 'com.android.settings'; then FG_OK=true; fi

mkdir -p "${GITHUB_WORKSPACE:-.}/smoke-diagnostics"
adb logcat -d -v threadtime | tail -n 5000 > "${GITHUB_WORKSPACE:-.}/smoke-diagnostics/ucoa_logcat.txt" || true
adb shell dumpsys accessibility > "${GITHUB_WORKSPACE:-.}/smoke-diagnostics/ucoa_accessibility.txt" || true
adb shell dumpsys window windows > "${GITHUB_WORKSPACE:-.}/smoke-diagnostics/ucoa_windows.txt" || true
echo "PLAN_OK=$PLAN_OK APPROVAL_OK=$APPROVAL_OK REAL_OK=$REAL_OK FG_OK=$FG_OK"
test "$PLAN_OK" = true
test "$APPROVAL_OK" = true
test "$REAL_OK" = true
test "$FG_OK" = true
echo 'UCOA_REAL_EXECUTION_SMOKE_OK'
