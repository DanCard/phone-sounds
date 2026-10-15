# phone-sounds

Custom Android notification sounds **and ringtones**, pushed to phones over ADB.
Two families:

- **Nature sounds** — short ambient clips (Wind, Rain, Thunder, …) trimmed from
  Wikimedia Commons source files.
- **Chipmunk voices** — a word/name spoken by a natural TTS voice, pitched up
  +50%. Used both as notification tones and as crescendo ringtones.

## Layout

- `notifications/` — finished notification clips (`.ogg`). Pushed to a phone's
  `/sdcard/Notifications/` (flagged `is_notification`).
- `ringtones/` — finished ringtone clips (`.ogg`). Pushed to `/sdcard/Ringtones/`
  (flagged `is_ringtone`).
- `sounds/src_*.ogg` — original nature source files (untrimmed).
- `sounds/voice_mp3/` — raw gTTS output per word (pre-pitch).
- `.venv/` — Python venv with gTTS installed.
- `makevoice.sh` — make a chipmunk word as notification + ringtone, push it.
- `setup-phone.sh` / `setup_phone.py` / `phone-config.txt` — full phone setup (see below).
  Private rules (contact ringtones with phone numbers) go in the git-ignored
  `phone-config.local.txt`; see `phone-config.local.example.txt`.
- `push.sh` — push everything in `notifications/` to a phone.
- `assign-sounds.sh` — interactive walkthrough to assign sounds to app channels.
- `generic-notifs.sh` — list recent notifications that still play the default sound
  (by app channel, busiest first), with the command to open each channel. Uses
  `notif_report.py`.
- `ASSIGNMENTS.md` — the app → sound channel mapping (with channel IDs).

## New phone? One command

```bash
./setup-phone.sh --list                 # find the serial
./setup-phone.sh <serial> --dry-run     # see what would change
./setup-phone.sh <serial>               # do it (keep phone unlocked, hands off)
```

Applies `phone-config.txt`: pushes `notifications/` + `ringtones/`, turns on app
notifications, sets default sounds, contact ringtones and every app channel
sound by driving the Settings UI (Samsung and Pixel pickers). Channels are
matched by **name**, so per-phone IDs (Messenger `@uuid`, Signal `messages_N`,
Google Voice `nTXT`, Google Chat per account) don't matter. Idempotent: re-run
any time; it skips what's already right, lists PENDING channels (app not opened
or signed in yet) and the few DO BY HAND steps (Messenger's call ringtone).
To add a sound for a new app: add a `channel` line and re-run.

## Make a chipmunk word (notification + ringtone)

```bash
./makevoice.sh "Sophia"               # build BOTH, push to all connected phones
./makevoice.sh "Sophia" --notif-only  # only the short notification sound
./makevoice.sh "Sophia" --ring-only   # only the crescendo ringtone
./makevoice.sh "Sophia" <serial>      # push to one device
./makevoice.sh "Sophia" --make-only   # build files, don't push
```

- **Notification** = the word once, ~0.5–1s, volume-normalized.
- **Ringtone** = the word repeated with pauses, getting louder each time
  (crescendo), ~28s, fades out. Tunable via env vars:
  `RING_LEN` (target seconds, 28), `GAP` (pause seconds, 1.0),
  `VMIN`/`VMAX` (start/end volume, 0.2 / 1.0).
- Accent: `TLD=co.uk ./makevoice.sh "Sophia"` (com=US, co.uk=UK, com.au=AU, co.in=IN).
- Pitch: `PITCH=1.0` for a normal-pitch natural voice instead of chipmunk.

## Push nature sounds

```bash
./push.sh --list            # show connected devices
./push.sh <serial>          # push notifications/ to a specific phone
./push.sh                   # push to the only connected device
```

## Find notifications still using the generic sound

```bash
./generic-notifs.sh <serial>         # audible default-sound channels, busiest first
./generic-notifs.sh <serial> --all   # include channels already customized
```

Source: `dumpsys usagestats` NOTIFICATION_INTERRUPTION events (about the last day,
with the channel ID) plus `dumpsys notification` history/archive. Run it every day
or two. On the phone itself: Settings > Notifications > Advanced settings >
Notification history (last 24h, tap an entry to open that app's settings).

## Select on the phone

- **Notification, system default:** Settings > Sounds & vibration > Notification sound
- **Notification, per app:** Settings > Apps > <app> > Notifications > <channel> > Sound
  (or use `assign-sounds.sh`)
- **Ringtone, default:** Settings > Sounds & vibration > Ringtone
- **Ringtone, per contact:** Contacts > <person> > ⋮ > Set ringtone

## How classification works (important)

A file only shows in a picker if MediaStore has flagged it: `is_notification`
for files in `Notifications/`, `is_ringtone` for files in `Ringtones/`. Those
flags are derived **only by a real media scan**, which `makevoice.sh`/`push.sh`
trigger via:

```bash
adb -s <serial> shell "content call --uri content://media --method scan_file \
  --arg '/storage/emulated/0/<Notifications|Ringtones>/<file>'"
```

Just copying the file (or the old `MEDIA_SCANNER_SCAN_FILE` broadcast) leaves the
flag NULL and the file invisible in the picker.

**Don't rename/delete a sound after assigning it.** A channel/contact stores the
sound as a MediaStore content URI with a numeric id; renaming or deleting changes
that id, silently breaking the assignment. Re-pushing the **same filename** keeps
the id and is safe.

## Nature sound sources & licenses (Wikimedia Commons)

| Clip | Source file | License |
|------|-------------|---------|
| Wind | Howling wind.ogg | CC0 |
| Rain | Sound of light rainfall.ogg | CC BY-SA 4.0 |
| Thunder | Thunder 01.ogg | (verify on Commons) |
| Forest Birds | Birds forest.ogg | (verify on Commons) |
| Ocean Waves | Oceanwavescrushing.ogg | (verify on Commons) |
| Babbling Brook | Brook sound.ogg | (verify on Commons) |
| Crickets | Field cricket Gryllus pennsylvanicus.ogg | (verify on Commons) |
| Songbird | Een koolmees zingt het avondlied van de lente | (verify on Commons) |

All for personal use. Check each file's page on commons.wikimedia.org for exact
attribution requirements before any redistribution.
