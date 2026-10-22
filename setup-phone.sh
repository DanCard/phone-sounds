#!/usr/bin/env bash
# Set up a phone with all custom sounds in one go, from phone-config.txt:
#   1. push notifications/ + ringtones/ (and media-scan them)
#   2. turn on app notifications (enable lines)
#   3. per-contact ringtones (contact lines)
#   4. per-app notification channel sounds, by driving the Settings UI
#      (Samsung and Pixel pickers both supported). Keep the phone unlocked and
#      don't touch it while this runs; it taps through Settings.
# Safe to re-run: anything already correct is skipped.
#
# Usage:
#   ./setup-phone.sh <serial>              # everything
#   ./setup-phone.sh <serial> --dry-run    # show what would change
#   ./setup-phone.sh <serial> --only channel|contact|enable|push
#   ./setup-phone.sh --list                # connected phones
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == "--list" || -z "${1:-}" ]]; then adb devices -l; exit 0; fi
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python setup_phone.py "$@"
else
  exec python3 -I setup_phone.py "$@"
fi
