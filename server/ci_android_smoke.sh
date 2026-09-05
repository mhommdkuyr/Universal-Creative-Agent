#!/usr/bin/env bash
set -euo pipefail

adb wait-for-device
adb install apk/app-debug.apk
# Give Accessibility a moment to bind after enabling it.
adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1
sleep 2
adb logcat -c || true
adb shell am force-stop com.ucoa.app || true
adb shell am start -W -n com.ucoa.app/.MainActivity
sleep 3
adb logcat -d -t 1200 > logcat.txt || true
if grep -Eqi 'FATAL EXCEPTION|AndroidRuntime' logcat.txt; then cat logcat.txt; exit 1; fi
adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
adb shell cat /sdcard/window.xml > window.xml 2>/dev/null || true
grep -q 'Universal Creative Agent' window.xml
grep -q 'تنفيذ عالمي' window.xml
grep -q 'إعداد عقل AI' window.xml
grep -q 'إرسال' window.xml
grep -q 'رفع الوسائط' window.xml
grep -q 'الصوت' window.xml
adb shell dumpsys activity activities | grep -Eqi 'mResumedActivity.*com\\.ucoa\\.app|topResumedActivity.*com\\.ucoa\\.app|ResumedActivity.*com\\.ucoa\\.app'

echo ANDROID_UI_SMOKE_OK

echo '--- Real agent smoke: Accessibility -> screenshot -> HF VLM -> reasoning -> action -> verifier ---'
adb shell am force-stop com.ucoa.app || true
adb shell am start -W -n com.ucoa.app/.UcoaSmokeActivity
# Render+VLM is a cold, networked path; allow up to 6 minutes.
for i in $(seq 1 180); do
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb shell cat /sdcard/window.xml > window.xml 2>/dev/null || true
  if grep -q 'UCOA_REAL_SMOKE_OK' window.xml; then
    echo UCOA_REAL_SMOKE_OK
    exit 0
  fi
  if grep -q 'UCOA_REAL_SMOKE_FAILED' window.xml; then
    cat window.xml
    adb logcat -d -t 2400 > real_smoke_logcat.txt || true
    cat real_smoke_logcat.txt
    exit 1
  fi
  sleep 2
done
cat window.xml || true
adb logcat -d -t 2400 > real_smoke_logcat.txt || true
cat real_smoke_logcat.txt
exit 1
