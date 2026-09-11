#!/usr/bin/env bash
set -euo pipefail

# Final release gate trigger: hosted x86_64 validates the UCOA client harness; ARM-only CapCut is diagnostic-only.
CAPCUT_APK_URL="${CAPCUT_APK_URL:-https://sf16-sg.tiktokcdn.com/obj/eden-sg/nupkuhs_yvojuh_jj/ljhwZthlaukjlkulzlp/capcut_apk/cc_website_download.apk}"
CAPCUT_APK_PATH="${CAPCUT_APK_PATH:-/tmp/capcut.apk}"
UCOA_APK_PATH="${UCOA_APK_PATH:-android/app/build/outputs/apk/debug/app-debug.apk}"
CAPCUT_PACKAGE="${CAPCUT_PACKAGE:-}"
CAPCUT_APK_SHA256="${CAPCUT_APK_SHA256:-}"
CAPCUT_OPTIONAL="${CAPCUT_OPTIONAL:-false}"

mkdir -p "$(dirname "$CAPCUT_APK_PATH")"
if [ ! -s "$CAPCUT_APK_PATH" ]; then
  echo "Downloading CapCut APK..."
  curl -L --fail --retry 3 --connect-timeout 8 --max-time 180 "$CAPCUT_APK_URL" -o "$CAPCUT_APK_PATH"
else
  echo "Using cached CapCut APK: $CAPCUT_APK_PATH"
fi

[ -s "$UCOA_APK_PATH" ]
AAPT_BIN="${AAPT_BIN:-$(command -v aapt || true)}"
if [ -z "$AAPT_BIN" ]; then AAPT_BIN="$(command -v aapt2 || true)"; fi
if [ -z "$AAPT_BIN" ]; then AAPT_BIN="$(find "${ANDROID_HOME:-$HOME/Android/Sdk}/build-tools" -type f \( -name aapt -o -name aapt2 \) 2>/dev/null | sort -V | tail -n 1)"; fi
[ -x "$AAPT_BIN" ]

echo "UCOA_APK_PATH=$UCOA_APK_PATH"
echo "AAPT_BIN=$AAPT_BIN"
"$AAPT_BIN" dump badging "$CAPCUT_APK_PATH" | head -n 5 || true
if [ -z "$CAPCUT_PACKAGE" ]; then CAPCUT_PACKAGE="$("$AAPT_BIN" dump badging "$CAPCUT_APK_PATH" | sed -n "s/^package: name='\\([^']*\\)'.*/\\1/p" | head -n1)"; fi
CAPCUT_LABEL="$("$AAPT_BIN" dump badging "$CAPCUT_APK_PATH" | sed -n "s/.*application-label='\\([^']*\\)'.*/\\1/p" | head -n1)"
CAPCUT_NATIVE_ABIS="$("$AAPT_BIN" dump badging "$CAPCUT_APK_PATH" | sed -n "s/^native-code: //p" | head -n1 || true)"
[ -n "$CAPCUT_PACKAGE" ]
echo "CAPCUT_PACKAGE=$CAPCUT_PACKAGE CAPCUT_LABEL=$CAPCUT_LABEL CAPCUT_NATIVE_ABIS=${CAPCUT_NATIVE_ABIS:-none}"

START_MS="$(date +%s%3N)"
CAPCUT_INSTALLED=true
CAPCUT_ABI_COMPATIBLE=true
if [ -n "$CAPCUT_NATIVE_ABIS" ] && ! printf '%s\n' "$CAPCUT_NATIVE_ABIS" | grep -Eq 'x86_64|x86'; then CAPCUT_ABI_COMPATIBLE=false; fi
if [ "$CAPCUT_OPTIONAL" = "true" ] && [ "$CAPCUT_ABI_COMPATIBLE" = "false" ]; then
  CAPCUT_INSTALLED=false
  echo "CAPCUT_INSTALL_SKIPPED_ABI_OR_DEVICE_INCOMPATIBLE=true"
elif ! timeout 60 adb install -r "$CAPCUT_APK_PATH"; then
  CAPCUT_INSTALLED=false
  if [ "$CAPCUT_OPTIONAL" != "true" ]; then echo "CAPCUT_INSTALL_FAILED"; exit 1; fi
  echo "CAPCUT_INSTALL_SKIPPED_ABI_OR_DEVICE_INCOMPATIBLE=true"
fi
adb install -r "$UCOA_APK_PATH"
INSTALL_MS="$(date +%s%3N)"
echo "UCOA_INSTALL_DURATION_MS=$((INSTALL_MS-START_MS))"

if [ -f server/ci_seed_media.sh ]; then bash server/ci_seed_media.sh || true; fi
mkdir -p /tmp/ucoa_media
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -y -f lavfi -i "color=c=black:s=360x640:d=2" -vf "drawtext=text='UCOA E2E':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2" -c:v libx264 -pix_fmt yuv420p /tmp/ucoa_media/ucoa_e2e.mp4 >/tmp/ffmpeg.log 2>&1 || true
  adb push /tmp/ucoa_media/ucoa_e2e.mp4 /sdcard/Movies/ucoa_e2e.mp4 >/tmp/adb_push.log 2>&1 || true
fi

adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1

if [ "$CAPCUT_INSTALLED" = true ]; then
  adb shell am force-stop "$CAPCUT_PACKAGE" || true
  adb shell am force-stop com.ucoa.app || true
  LAUNCH_MS="$(date +%s%3N)"
  adb shell am start -n com.ucoa.app/.UcoaCapCutSmokeActivity --es capcut_label "${CAPCUT_LABEL:-CapCut}" >/tmp/ucoa-capcut-start.txt 2>&1
  rm -f /tmp/ucoa-capcut-log.txt
  for i in $(seq 1 240); do
    adb logcat -d -s UCOA_CAPCUT:I UCOA_CAPCUT:E '*:S' > /tmp/ucoa-capcut-log.txt || true
    if grep -q 'UCOA_CAPCUT_SMOKE_OK' /tmp/ucoa-capcut-log.txt; then END_MS="$(date +%s%3N)"; cat /tmp/ucoa-capcut-log.txt; echo "CAPCUT_LAUNCH_AND_TASK_DURATION_MS=$((END_MS-LAUNCH_MS))"; echo CAPCUT_E2E_OK; exit 0; fi
    if grep -q 'UCOA_CAPCUT_SMOKE_FAILED' /tmp/ucoa-capcut-log.txt; then cat /tmp/ucoa-capcut-log.txt; echo CAPCUT_E2E_FAILED; exit 1; fi
    sleep 2
  done
  cat /tmp/ucoa-capcut-log.txt || true
  adb logcat -d -t 4000 > /tmp/capcut_full_logcat.txt || true
  cat /tmp/capcut_full_logcat.txt
  exit 1
fi

adb shell am force-stop com.ucoa.app || true
adb shell am start -n com.ucoa.app/.UcoaSmokeActivity >/tmp/ucoa-smoke-start.txt 2>&1
rm -f /tmp/ucoa-smoke-log.txt
for i in $(seq 1 240); do
  adb logcat -d -s UCOA_REAL_SMOKE_OK:I UCOA_REAL_SMOKE_FAILED:E '*:S' > /tmp/ucoa-smoke-log.txt || true
  if grep -q 'UCOA_REAL_SMOKE_OK' /tmp/ucoa-smoke-log.txt; then cat /tmp/ucoa-smoke-log.txt; echo CAPCUT_COMPATIBILITY_DIAGNOSTIC_ONLY; echo UCOA_EMULATOR_CLOUD_SMOKE_OK; exit 0; fi
  if grep -q 'UCOA_REAL_SMOKE_FAILED' /tmp/ucoa-smoke-log.txt; then cat /tmp/ucoa-smoke-log.txt; echo UCOA_EMULATOR_CLOUD_SMOKE_FAILED; exit 1; fi
  sleep 2
done
cat /tmp/ucoa-smoke-log.txt || true
adb logcat -d -t 4000 > /tmp/ucoa_full_logcat.txt || true
cat /tmp/ucoa_full_logcat.txt
exit 1
