# App → notification-sound assignments

> **Superseded for setup by `phone-config.txt` + `./setup-phone.sh`**, which match
> channels by name and handle the per-phone IDs below automatically. This file
> keeps the history and gotchas.

Final mapping of chipmunk voices to app notification channels, verified
2026-05-24 on both phones. Re-run `./assign-sounds.sh` to redo these (e.g. after
an app update changes a channel, or if a sound file gets renamed/deleted and the
assignment breaks).

## Devices

| Phone | Serial |
|-------|--------|
| Samsung Galaxy Z Fold4 (SM-F936U1) | `RFCT70G352Y` |
| Pixel 7 Pro | `2A191FDH300PPW` |

## Mapping (chipmunk sound → app channel)

| Sound | App | Package | Channel ID | Samsung | Pixel |
|-------|-----|---------|------------|:------:|:-----:|
| chipmunk Tesla | Tesla | `com.teslamotors.tesla` | `default_channel` | ✅ | ✅ |
| chipmunk Signal | Signal | `org.thoughtcrime.securesms` | `messages_2` (Fold) | ✅ | (not installed) |
| chipmunk Messenger | Messenger | `com.facebook.orca` | `messenger_orca_050_messaging@<uuid>` | ✅ | ✅ |
| chipmunk Garage Door | Genie Aladdin Connect | `com.geniecompany.AladdinConnect` | `832` | ✅ | ✅ |
| chipmunk gvoice text | Google Voice | `com.google.android.apps.googlevoice` | `1TXT`, `2TXT`, `4TXT` (one per GV number) | ✅ | ✅ |

### Notes / gotchas

- **Signal rotates its channel ID** (`messages_1` → `messages_2` → …) whenever
  the sound is changed in system settings: it deletes the old channel and makes
  a new one. If the sound doesn't stick, find the live one with
  `dumpsys notification --noredact | grep -E "mId='messages_[0-9]+'.*mDeleted=false"`
  and set the sound on that.

- **Messenger channel ID differs per phone** (the `@<uuid>` suffix is
  device-specific and can change if the app recreates the channel):
  - Samsung: `messenger_orca_050_messaging@579c5f03-8d39-4595-a73d-9db79a3088b6`
  - Pixel:   `messenger_orca_050_messaging@1d57aad7-5645-452b-afbe-3679162bb469`
  - To re-discover after an update:
    `adb -s <serial> shell dumpsys notification --noredact | grep -i orca_050_messaging`
- **Tesla on the Samsung had its master "All Tesla notifications" toggle OFF.**
  A channel sound does nothing until that app-level toggle is on
  (`Settings > Apps > Tesla > Notifications`, top switch). It's on now.
- **Google Voice has one "Messages" channel per GV number** (`1TXT`, `2TXT`).
  Set every one you use. Samsung has two numbers; Pixel has `2TXT`.
- **Pixel Messenger** has per-conversation overrides set separately
  (one conversation → Cricket); these are independent of the Chats channel.

## How to re-verify

Dump and parse both phones (parser kept at `/tmp/parse_notif.py` during the
session; logic: track `AppSettings: <pkg>` headers, read each
`NotificationChannel{... mSound=...}`):

```bash
adb -s RFCT70G352Y shell dumpsys notification --noredact | grep -i chipmunk
adb -s 2A191FDH300PPW shell dumpsys notification --noredact | grep -i chipmunk
```

Each app channel's `mSound` should be a
`content://media/external/audio/media/<id>?title=chipmunk%20<Name>` URI.

## IMPORTANT: don't break assignments

A channel stores the sound as a MediaStore **content URI with a numeric id**.
If you rename or delete the underlying `.ogg`, that id changes/disappears and
the assignment silently falls back to default. Safe operation: re-push a file
with the **same name** (id is preserved). Renaming = must re-assign in the UI.

## Ringtones (Fold, set 2026-10-15)

Phone numbers live in the git-ignored `phone-config.local.txt`.
Built with `./makevoice.sh "<phrase>" --ring-only <serial>` → `ringtones/ring <phrase>.ogg`.

| Ringtone | Where | How it's set |
|----------|-------|--------------|
| ring Mom is calling | Contact "Grandma" (mom) | contact `custom_ringtone` |
| ring Sophia is calling | Contact "Sophia" (daughter) | contact `custom_ringtone` |
| ring Denken is calling | Contact "Denken" (son) | contact `custom_ringtone` |
| ring Messenger call | All Messenger calls | Messenger › Menu › Settings › Notifications & sounds › Ringtone |

- Messenger has **one** ringtone for all calls, with no per-chat option. Its "Incoming
  calls" channel has `mSound=null`; the app plays the ringtone itself.
- Contact ringtones can be set over ADB (escape the colon in the URI):
  `adb -s <serial> shell 'content update --uri content://com.android.contacts/contacts/<id> --bind custom_ringtone:s:content\\://media/external/audio/media/<media_id>'`
