#!/usr/bin/env bash
# Generate a natural chipmunk-voice from a word/phrase and push it to one or all
# connected phones. By DEFAULT it builds BOTH:
#   - a NOTIFICATION sound (short, single) -> /sdcard/Notifications/
#   - a RINGTONE (word repeated with pauses, getting louder) -> /sdcard/Ringtones/
#
# Usage:
#   ./makevoice.sh "Sophia"                 # both; push to all connected phones
#   ./makevoice.sh "Sophia" --notif-only    # only the notification sound
#   ./makevoice.sh "Sophia" --ring-only     # only the ringtone
#   ./makevoice.sh "Sophia" <serial>        # push to one device only
#   ./makevoice.sh "Sophia" --make-only     # build files, don't push
#   (flags and a serial can be combined, in any order)
#
# Accent: TLD env var (com=US default, co.uk=UK, com.au=AU, co.in=India).
# Pitch:  PITCH env var (1.0=normal, 1.5=+50% chipmunk, the default).
# Ring shape: RING_LEN (target s, default 28), GAP (pause s, default 1.0),
#             VMIN/VMAX (crescendo start/end volume, default 0.2 / 1.0).
set -euo pipefail
cd "$(dirname "$0")"

PHRASE="${1:?usage: ./makevoice.sh \"Phrase\" [--notif-only|--ring-only] [--make-only] [serial]}"
shift || true
TLD="${TLD:-com}"
PITCH="${PITCH:-1.5}"
DO_NOTIF=1; DO_RING=1; MAKEONLY=0; TARGET=""
for a in "$@"; do
  case "$a" in
    --notif-only) DO_RING=0 ;;
    --ring-only)  DO_NOTIF=0 ;;
    --make-only)  MAKEONLY=1 ;;
    --ring|--both) : ;;            # accepted, no-op (both is the default)
    *) TARGET="$a" ;;
  esac
done

MP3="sounds/voice_mp3/${PHRASE}.mp3"
mkdir -p sounds/voice_mp3 notifications ringtones

# 1) Natural TTS (needs internet at generation time only). Shared by both builds.
.venv/bin/python - "$PHRASE" "$MP3" "$TLD" <<'PY'
import sys
from gtts import gTTS
phrase, mp3, tld = sys.argv[1], sys.argv[2], sys.argv[3]
gTTS(text=phrase, lang="en", tld=tld, slow=False).save(mp3)
PY
SR=$(ffprobe -v error -show_entries stream=sample_rate -of csv=p=0 "$MP3")  # gTTS=24000

# --- build the short notification clip ---
build_notif () {
  if [[ "$PITCH" == "1.0" || "$PITCH" == "1" ]]; then
    OUT_N="notifications/Voice - ${PHRASE} (Natural).ogg"
  else
    OUT_N="notifications/chipmunk ${PHRASE}.ogg"
  fi
  ffmpeg -nostdin -v error -y -i "$MP3" \
    -af "asetrate=${SR}*${PITCH},aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,areverse,afade=t=in:d=0.12,areverse" \
    -ar 48000 -c:a libvorbis -q:a 4 "$OUT_N"
  echo "built notification: $OUT_N ($(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT_N")s)"
}

# --- build the crescendo ringtone (word + pause, louder each repeat) ---
build_ring () {
  OUT_R="ringtones/ring ${PHRASE}.ogg"
  local RING_LEN="${RING_LEN:-28}" GAP="${GAP:-1.0}" VMIN="${VMIN:-0.2}" VMAX="${VMAX:-1.0}"
  local tmp; tmp=$(mktemp -d)
  ffmpeg -nostdin -v error -y -i "$MP3" \
    -af "asetrate=${SR}*${PITCH},aresample=48000" -ac 1 -ar 48000 "$tmp/word.wav"
  local wlen N total fst i lvl
  wlen=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$tmp/word.wav")
  ffmpeg -nostdin -v error -y -f lavfi -i anullsrc=r=48000:cl=mono -t "$GAP" "$tmp/sil.wav"
  N=$(awk -v t="$RING_LEN" -v w="$wlen" -v g="$GAP" 'BEGIN{n=int(t/(w+g)); if(n<2)n=2; print n}')
  : > "$tmp/list.txt"
  for ((i=1;i<=N;i++)); do
    lvl=$(awk -v i="$i" -v n="$N" -v a="$VMIN" -v b="$VMAX" 'BEGIN{printf "%.4f",(n==1)?b:a+(b-a)*(i-1)/(n-1)}')
    ffmpeg -nostdin -v error -y -i "$tmp/word.wav" -af "volume=${lvl}" "$tmp/w_${i}.wav"
    printf "file '%s/w_%d.wav'\nfile '%s/sil.wav'\n" "$tmp" "$i" "$tmp" >> "$tmp/list.txt"
  done
  total=$(awk -v n="$N" -v w="$wlen" -v g="$GAP" 'BEGIN{printf "%.3f", n*(w+g)}')
  fst=$(awk -v t="$total" 'BEGIN{printf "%.3f",(t-2.5>0)?t-2.5:0}')
  ffmpeg -nostdin -v error -y -f concat -safe 0 -i "$tmp/list.txt" \
    -af "afade=t=out:st=${fst}:d=2.5" -ar 48000 -c:a libvorbis -q:a 4 "$OUT_R"
  rm -rf "$tmp"
  echo "built ringtone:     $OUT_R ($(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT_R")s, ${N} reps, crescendo ${VMIN}->${VMAX})"
}

OUT_N=""; OUT_R=""
[[ "$DO_NOTIF" -eq 1 ]] && build_notif
[[ "$DO_RING"  -eq 1 ]] && build_ring

[[ "$MAKEONLY" -eq 1 ]] && exit 0

# Push a built file into its folder on a device and scan it so the picker lists
# it. is_notification / is_ringtone are derived from the Notifications/Ringtones
# folder; the scan_file call is REQUIRED or it won't appear.
push_one () { # <serial> <localfile> <destdir>
  local s="$1" f="$2" dest="$3" b; b=$(basename "$f")
  adb -s "$s" shell mkdir -p "/sdcard/$dest" >/dev/null 2>&1
  adb -s "$s" push "$f" "/sdcard/$dest/" >/dev/null
  adb -s "$s" shell "content call --uri content://media --method scan_file --arg '/storage/emulated/0/$dest/$b'" >/dev/null 2>&1
}
push_dev () { # <serial>
  local s="$1" m; m=$(adb -s "$s" shell getprop ro.product.model | tr -d '\r')
  local what=()
  # Some apps (e.g. Facebook) flag notification channels as USAGE_NOTIFICATION_RINGTONE,
  # making the system picker filter for is_ringtone=1; push notification clips to both.
  [[ -n "$OUT_N" ]] && { push_one "$s" "$OUT_N" "Notifications"; push_one "$s" "$OUT_N" "Ringtones"; what+=("notification"); }
  [[ -n "$OUT_R" ]] && { push_one "$s" "$OUT_R" "Ringtones";     what+=("ringtone"); }
  echo "pushed to $m ($s): ${what[*]}"
}

if [[ -n "$TARGET" ]]; then
  push_dev "$TARGET"
else
  # Read serials into an array FIRST — piping into a while loop lets the adb
  # calls inside eat the remaining device lines (only 1 phone gets it).
  mapfile -t SERIALS < <(adb devices | awk '/\tdevice$/{print $1}')
  for s in "${SERIALS[@]}"; do push_dev "$s"; done
fi
echo "Done. Notification: Settings > Sounds & vibration > Notification sound (or per-app channel)."
echo "      Ringtone:     Settings > Sounds & vibration > Ringtone (or per-contact ringtone)."
