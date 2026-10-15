#!/usr/bin/env bash
# Walk through assigning the chipmunk notification sounds to each app channel,
# one at a time. For each step it prints the command, waits for a keypress,
# then runs it (opening the right Settings screen on the phone). You then tap
# "Sound" and pick the named chipmunk sound, and press a key for the next one.
#
# There is no ADB command to SET a channel's sound — Android requires that
# final pick in the UI. This script just jumps you straight to each screen.
#
# Usage: ./assign-sounds.sh
set -u

SAMSUNG="RFCT70G352Y"
PIXEL="2A191FDH300PPW"

# Each step: "SERIAL|TYPE|LABEL|PACKAGE|CHANNEL_ID|PICK"
#   TYPE=app    -> opens app-level notification settings (CHANNEL_ID ignored)
#   TYPE=chan   -> opens a specific channel's settings
STEPS=(
  "$SAMSUNG|app |Tesla: turn ON the master 'All Tesla notifications' toggle|com.teslamotors.tesla||(enable notifications)"
  "$SAMSUNG|chan|Tesla notifications|com.teslamotors.tesla|default_channel|chipmunk Tesla"
  "$SAMSUNG|chan|Signal messages|org.thoughtcrime.securesms|messages_2|chipmunk Signal"
  "$SAMSUNG|chan|Messenger (Chats)|com.facebook.orca|messenger_orca_050_messaging@579c5f03-8d39-4595-a73d-9db79a3088b6|chipmunk Messenger"
  "$SAMSUNG|chan|Garage / Aladdin|com.geniecompany.AladdinConnect|832|chipmunk Garage Door"
  "$SAMSUNG|chan|Google Voice Messages #1|com.google.android.apps.googlevoice|1TXT|chipmunk SMS"
  "$SAMSUNG|chan|Google Voice Messages #2|com.google.android.apps.googlevoice|2TXT|chipmunk SMS"

  "$PIXEL|chan|Garage / Aladdin|com.geniecompany.AladdinConnect|832|chipmunk Garage Door"
  "$PIXEL|chan|Google Voice Messages|com.google.android.apps.googlevoice|2TXT|chipmunk SMS"
  "$PIXEL|chan|Tesla notifications|com.teslamotors.tesla|default_channel|chipmunk Tesla"
  "$PIXEL|chan|Messenger (Chats)|com.facebook.orca|messenger_orca_050_messaging@1d57aad7-5645-452b-afbe-3679162bb469|chipmunk Messenger"
)

total=${#STEPS[@]}
i=0
for step in "${STEPS[@]}"; do
  i=$((i+1))
  IFS='|' read -r serial type label pkg cid pick <<<"$step"
  type=$(echo "$type" | tr -d ' ')

  model=$(adb -s "$serial" shell getprop ro.product.model 2>/dev/null | tr -d '\r')
  [ -z "$model" ] && model="NOT CONNECTED"

  if [ "$type" = "app" ]; then
    cmd="adb -s $serial shell am start -a android.settings.APP_NOTIFICATION_SETTINGS --es android.provider.extra.APP_PACKAGE $pkg"
  else
    cmd="adb -s $serial shell am start -a android.settings.CHANNEL_NOTIFICATION_SETTINGS --es android.provider.extra.APP_PACKAGE $pkg --es android.provider.extra.CHANNEL_ID '$cid'"
  fi

  echo
  echo "==================== Step $i/$total ===================="
  echo "  Phone : $model  ($serial)"
  echo "  Set   : $label"
  if [ "$type" = "app" ]; then
    echo "  Do    : toggle ON 'All <app> notifications' at the top"
  else
    echo "  Do    : tap 'Sound'  ->  pick  \"$pick\""
  fi
  echo "  Command:"
  echo "    $cmd"
  echo "--------------------------------------------------------"

  if [ "$model" = "NOT CONNECTED" ]; then
    read -n1 -rsp "  Phone not connected — press any key to SKIP this step..." _; echo
    continue
  fi

  read -n1 -rsp "  Press any key to open this screen (or 's' to skip, 'q' to quit)... " key; echo
  case "$key" in
    q|Q) echo "Quit."; exit 0 ;;
    s|S) echo "  (skipped)"; continue ;;
  esac

  eval "$cmd" >/dev/null 2>&1 \
    && echo "  -> Opened. Now on the phone: tap Sound -> \"$pick\", then come back." \
    || echo "  !! Failed to open (channel id may have changed). Skipping."
done

echo
echo "All steps done. Run the verify check next:  say \"verify\" to Claude,"
echo "or:  adb -s <serial> shell dumpsys notification --noredact | grep -i chipmunk"
