#!/usr/bin/env bash
set -euo pipefail

adb wait-for-device
APK="$(find /home/runner/work -type f -path '*/android/app/build/outputs/apk/debug/app-debug.apk' -print -quit 2>/dev/null || true)"
if [ -z "$APK" ] || [ ! -s "$APK" ]; then
  APK="$PWD/android/app/build/outputs/apk/debug/app-debug.apk"
fi
test -s "$APK"

adb install -r "$APK"
adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1
adb shell am force-stop com.ucoa.app || true
adb shell am force-stop com.android.settings || true
adb shell am start -n com.ucoa.app/.MainActivity --es smoke_task "افتح الإعدادات"

PLAN_OK=false
APPROVAL_OK=false
REAL_OK=false

for i in $(seq 1 150); do
  LOG=$(adb logcat -d || true)
  if printf '%s' "$LOG" | grep -q 'استلمت خطة من Cloud Brain'; then PLAN_OK=true; fi
  if [ "$PLAN_OK" = true ] && [ "$APPROVAL_OK" = false ]; then
    adb shell uiautomator dump /sdcard/ucoa.xml >/dev/null 2>&1 || true
    XML=$(adb shell cat /sdcard/ucoa.xml 2>/dev/null || true)
    NODE=$(printf '%s' "$XML" | grep -o 'text="تنفيذ عالمي"[^>]\+' | head -1 || true)
    if [ -n "$NODE" ]; then
      BOUNDS=$(printf '%s' "$NODE" | sed -n 's/.*bounds="\[\([0-9,]*\)\]\[\([0-9,]*\)\]".*/\1 \2/p')
      if [ -n "$BOUNDS" ]; then
        X1=$(printf '%s' "$BOUNDS" | cut -d, -f1); Y1=$(printf '%s' "$BOUNDS" | cut -d, -f2)
        X2=$(printf '%s' "$BOUNDS" | cut -d' ' -f2 | cut -d, -f1); Y2=$(printf '%s' "$BOUNDS" | cut -d' ' -f2 | cut -d, -f2)
        adb shell input tap "$(( (X1 + X2) / 2 ))" "$(( (Y1 + Y2) / 2 ))"
        APPROVAL_OK=true
      fi
    fi
  fi
  if printf '%s' "$LOG" | grep -q 'UCOA_REAL_SMOKE_OK'; then REAL_OK=true; break; fi
  if printf '%s' "$LOG" | grep -q 'UCOA_REAL_SMOKE_FAILED'; then break; fi
  sleep 1
done

FG=$(adb shell dumpsys window windows | grep -m1 'mCurrentFocus' || true)
FG_OK=false
if printf '%s' "$FG" | grep -q 'com.android.settings'; then FG_OK=true; fi

mkdir -p "${GITHUB_WORKSPACE:-/tmp}/smoke-diagnostics"
adb logcat -d -v threadtime | tail -n 5000 > "${GITHUB_WORKSPACE:-/tmp}/smoke-diagnostics/ucoa_logcat.txt" || true
adb shell dumpsys accessibility > "${GITHUB_WORKSPACE:-/tmp}/smoke-diagnostics/ucoa_accessibility.txt" || true
adb shell dumpsys window windows > "${GITHUB_WORKSPACE:-/tmp}/smoke-diagnostics/ucoa_windows.txt" || true

echo "PLAN_OK=$PLAN_OK APPROVAL_OK=$APPROVAL_OK REAL_OK=$REAL_OK FG_OK=$FG_OK"
test "$PLAN_OK" = true
test "$APPROVAL_OK" = true
test "$REAL_OK" = true
test "$FG_OK" = true
echo 'UCOA_REAL_EXECUTION_SMOKE_OK'
