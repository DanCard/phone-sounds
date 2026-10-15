#!/usr/bin/env bash
# List recent notifications that played the generic default sound, grouped by
# app channel (busiest first), with the command to open each channel's
# settings so you can give it a custom sound. Read-only.
#
# Usage:
#   ./generic-notifs.sh [serial] [--all]   # --all: include channels already customized
set -euo pipefail
cd "$(dirname "$0")"

SERIAL=""; ARGS=()
for a in "$@"; do
  case "$a" in --*) ARGS+=("$a") ;; *) SERIAL="$a" ;; esac
done
ADB=(adb); [[ -n "$SERIAL" ]] && ADB=(adb -s "$SERIAL")

{ "${ADB[@]}" shell dumpsys notification --noredact
  "${ADB[@]}" shell dumpsys usagestats; } \
  | python3 -I notif_report.py "${ARGS[@]}" \
  | sed "s/\\\$S/${SERIAL:-<serial>}/"
