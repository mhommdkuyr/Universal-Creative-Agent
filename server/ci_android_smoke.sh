#!/usr/bin/env bash
set -euo pipefail
adb install apk/app-debug.apk
adb logcat -c || true
adb shell am force-stop com.ucoa.app || true
adb shell am start -W -n com.ucoa.app/.MainActivity
sleep 2
adb logcat -d -t 800 > logcat.txt || true
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
echo ANDROID_SMOKE_OK
