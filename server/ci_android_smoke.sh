#!/usr/bin/env bash
set -euo pipefail
adb wait-for-device
APK_PATH="android/app/build/outputs/apk/debug/app-debug.apk"
test -s "$APK_PATH"
adb install -r "$APK_PATH"
adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1
sleep 2
adb logcat -c || true
adb shell am force-stop com.ucoa.app || true
adb shell am start -n com.ucoa.app/.MainActivity >/tmp/ucoa-main-start.txt 2>&1
for i in $(seq 1 30); do
  if adb shell dumpsys activity activities | grep -Eqi 'mResumedActivity.*com\.ucoa\.app|topResumedActivity.*com\.ucoa\.app|ResumedActivity.*com\.ucoa\.app'; then break; fi
  sleep 2
done
sleep 2
adb logcat -d -t 1600 > logcat.txt || true
if grep -Eqi 'FATAL EXCEPTION|AndroidRuntime' logcat.txt; then cat logcat.txt; exit 1; fi
adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
adb shell cat /sdcard/window.xml > window.xml 2>/dev/null || true
grep -q 'Universal Creative Agent' window.xml
grep -q 'تنفيذ عالمي' window.xml
grep -q 'إعداد عقل AI' window.xml
grep -q 'إرسال' window.xml
grep -q 'رفع الوسائط' window.xml
grep -q 'الصوت' window.xml
adb shell dumpsys activity activities | grep -Eqi 'mResumedActivity.*com\.ucoa\.app|topResumedActivity.*com\.ucoa\.app|ResumedActivity.*com\.ucoa\.app'
echo ANDROID_UI_SMOKE_OK

echo '--- Real execution smoke: local brain -> Accessibility -> app launch -> foreground verification ---'
adb shell am force-stop com.ucoa.app || true
adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1
adb logcat -c || true
adb shell am start -n com.ucoa.app/.MainActivity --es smoke_task 'افتح الإعدادات' --ez smoke_local_only true >/tmp/ucoa-exec-start.txt 2>&1
EXEC_OK=false
FG_OK=false
LOCAL_MODEL_OK=false
LOCAL_ROUTE_OK=false
for i in $(seq 1 120); do
  LOG=$(adb logcat -d || true)
  if printf '%s' "$LOG" | grep -q 'UCOA_LOCAL_EXECUTION_OK app='; then EXEC_OK=true; fi
  if printf '%s' "$LOG" | grep -q 'LOCAL_BRAIN.*bundled=true'; then LOCAL_MODEL_OK=true; fi
  if printf '%s' "$LOG" | grep -q 'LOCAL_BRAIN.*العقل المحلي فهم المهمة'; then LOCAL_ROUTE_OK=true; fi
  FG=$(adb shell dumpsys window windows | grep -m1 'mCurrentFocus' || true)
  if printf '%s' "$FG" | grep -q 'com\.android\.settings'; then FG_OK=true; fi
  if [ "$EXEC_OK" = true ] && [ "$FG_OK" = true ] && [ "$LOCAL_MODEL_OK" = true ] && [ "$LOCAL_ROUTE_OK" = true ]; then break; fi
  sleep 1
done
adb logcat -d > execution_smoke_logcat.txt || true
printf 'EXEC_OK=%s FG_OK=%s LOCAL_MODEL_OK=%s LOCAL_ROUTE_OK=%s\n' "$EXEC_OK" "$FG_OK" "$LOCAL_MODEL_OK" "$LOCAL_ROUTE_OK"
test "$EXEC_OK" = true
test "$FG_OK" = true
test "$LOCAL_MODEL_OK" = true
test "$LOCAL_ROUTE_OK" = true
echo UCOA_REAL_EXECUTION_SMOKE_OK
