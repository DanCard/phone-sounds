#!/usr/bin/env bash
# Push nature notification sounds to an Android phone over ADB.
#
# Usage:
#   ./push.sh                 # push to the only connected device
#   ./push.sh <serial>        # push to a specific device (see: adb devices)
#   ./push.sh --list          # list connected devices and exit
#
# Files in ./notifications/ land in /sdcard/Notifications/ and then show up
# in the system notification-sound picker. We also trigger a media scan so
# they appear without a reboot.
set -euo pipefail
cd "$(dirname "$0")"

SRC_DIR="notifications"
DEST="/sdcard/Notifications"

if [[ "${1:-}" == "--list" ]]; then
  adb devices -l
  exit 0
fi

SERIAL="${1:-}"
ADB=(adb)
if [[ -n "$SERIAL" ]]; then
  ADB=(adb -s "$SERIAL")
else
  # If more than one device is attached, require an explicit serial.
  count=$(adb devices | grep -cw "device" || true)
  if [[ "$count" -gt 1 ]]; then
    echo "Multiple devices attached. Pass a serial:" >&2
    adb devices -l >&2
    exit 1
  fi
fi

model=$("${ADB[@]}" shell getprop ro.product.model | tr -d '\r')
echo "Target: ${SERIAL:-<single device>} ($model)"

"${ADB[@]}" shell mkdir -p "$DEST"
shopt -s nullglob
for f in "$SRC_DIR"/*.ogg "$SRC_DIR"/*.mp3 "$SRC_DIR"/*.m4a; do
  echo "  push: $(basename "$f")"
  "${ADB[@]}" push "$f" "$DEST/" >/dev/null
done

# Make the new files visible to the sound picker right away.
# NOTE: the old MEDIA_SCANNER_SCAN_FILE broadcast only creates a *stub* row
# (is_notification=NULL), so the file never shows up in the picker. The
# MediaStore "scan_file" content-call runs the full scan and derives
# is_notification=1 from the Notifications/ path. This is the part that matters.
for f in "$SRC_DIR"/*.ogg "$SRC_DIR"/*.mp3 "$SRC_DIR"/*.m4a; do
  base=$(basename "$f")
  "${ADB[@]}" shell "content call --uri content://media --method scan_file --arg '/storage/emulated/0/Notifications/$base'" >/dev/null 2>&1 || true
done

echo "Done. On the phone: Settings > Sounds & vibration > Notification sound"
echo "(or per-app: Settings > Apps > <app> > Notifications > channel > Sound)."
