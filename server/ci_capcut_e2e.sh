#!/usr/bin/env bash
set -euo pipefail

CAPCUT_APK_URL="https://sf16-sg.tiktokcdn.com/obj/eden-sg/nupkuhs_yvojuh_jj/ljhwZthlaukjlkulzlp/capcut_apk/cc_website_download.apk"
curl -L --fail --retry 3 --max-time 180 "$CAPCUT_APK_URL" -o /tmp/capcut.apk

aapt dump badging /tmp/capcut.apk | head -n 5 || true
CAPCUT_PACKAGE="$(aapt dump badging /tmp/capcut.apk | sed -n "s/^package: name='\([^']*\)'.*/\1/p" | head -n1)"
CAPCUT_LABEL="$(aapt dump badging /tmp/capcut.apk | sed -n "s/.*application-label='\([^']*\)'.*/\1/p" | head -n1)"
[ -n "$CAPCUT_PACKAGE" ]
echo "CAPCUT_PACKAGE=$CAPCUT_PACKAGE CAPCUT_LABEL=$CAPCUT_LABEL"

adb install -r /tmp/capcut.apk
adb install -r apk/app-debug.apk

# Seed a harmless test video so the agent can reach an editor workspace without
# depending on external media. If ffmpeg is unavailable, CapCut's empty state is
# still a valid target for the GUI agent, but the preferred path includes media.
mkdir -p /tmp/ucoa_media
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -y -f lavfi -i "color=c=black:s=360x640:d=2" -vf "drawtext=text='UCOA E2E':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2" -c:v libx264 -pix_fmt yuv420p /tmp/ucoa_media/ucoa_e2e.mp4 >/tmp/ffmpeg.log 2>&1 || true
  adb push /tmp/ucoa_media/ucoa_e2e.mp4 /sdcard/Movies/ucoa_e2e.mp4 >/tmp/adb_push.log 2>&1 || true
fi

adb shell settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService
adb shell settings put secure accessibility_enabled 1
sleep 3
adb shell am force-stop com.ucoa.app || true
adb shell am start -n com.ucoa.app/.UcoaCapCutSmokeActivity --es capcut_label "${CAPCUT_LABEL:-CapCut}" >/tmp/ucoa-capcut-start.txt 2>&1

rm -f /tmp/ucoa-capcut-log.txt
for i in $(seq 1 300); do
  adb logcat -d -s UCOA_CAPCUT:I UCOA_CAPCUT:E '*:S' > /tmp/ucoa-capcut-log.txt || true
  if grep -q 'UCOA_CAPCUT_SMOKE_OK' /tmp/ucoa-capcut-log.txt; then
    cat /tmp/ucoa-capcut-log.txt
    echo CAPCUT_E2E_OK
    exit 0
  fi
  if grep -q 'UCOA_CAPCUT_SMOKE_FAILED' /tmp/ucoa-capcut-log.txt; then
    cat /tmp/ucoa-capcut-log.txt
    echo CAPCUT_E2E_FAILED
    exit 1
  fi
  sleep 2
done
cat /tmp/ucoa-capcut-log.txt || true
adb logcat -d -t 4000 > /tmp/capcut_full_logcat.txt || true
cat /tmp/capcut_full_logcat.txt
exit 1
