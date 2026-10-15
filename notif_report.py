#!/usr/bin/env python3
"""Report recent notifications that played the GENERIC (default) sound.

Reads `dumpsys notification --noredact` + `dumpsys usagestats` from stdin
(see generic-notifs.sh), joins the recent notifications (usagestats
NOTIFICATION_INTERRUPTION events, archive, Samsung history, currently showing)
against each app channel's sound setting, and prints the audible channels that
still use the default sound, busiest first. Those are the ones to give a
custom sound.

Usage: ./generic-notifs.sh [serial] [--all]
  --all   also list channels that already have a custom sound
"""
import re
import sys
from collections import defaultdict

DEFAULT_SOUNDS = ("content://settings/system/notification_sound",)
# Things that are never worth a sound: our own tooling, system chatter.
IGNORE_PKGS = {"android", "com.android.systemui", "com.android.shell"}

text = sys.stdin.read()
show_all = "--all" in sys.argv

# --- channel config: (pkg, channel_id) -> {name, importance, sound} ---------
channels = {}
app_blocked = set()
pkg = None
for line in text.splitlines():
    m = re.match(r"\s*AppSettings: (\S+) \(\d+\) importance=(\S+)", line)
    if m:
        pkg = m.group(1)
        if m.group(2) == "NONE":
            app_blocked.add(pkg)
        continue
    m = re.search(r"NotificationChannel\{mId='([^']*)', mName=([^,]*),.*?mImportance=(-?\d+),.*?mSound=([^,]*),.*?mDeleted=(\w+)", line)
    if m and pkg and m.group(5) == "false":
        channels[(pkg, m.group(1))] = {
            "name": m.group(2), "importance": int(m.group(3)), "sound": m.group(4)}

# --- recent notifications: (pkg, channel_id, title or None) -----------------
seen = []
# usagestats: every notification that alerted (sound/vibrate/peek), ~last day+
for m in re.finditer(r"type=NOTIFICATION_INTERRUPTION package=(\S+) channelId=(\S+)", text):
    seen.append((m.group(1), m.group(2), None))
# archive + active records: StatusBarNotification(pkg=... Notification(channel=...
for m in re.finditer(r"StatusBarNotification\(pkg=(\S+) .*?Notification\(channel=(\S+)", text):
    seen.append((m.group(1), m.group(2), None))
# Samsung history: key =0|pkg|..., mExtraTitle = X, mChannelName='..', mChannelId='..'
for m in re.finditer(r"HistoricalNotification\{.*?key =\d+\|([^|]+)\|.*?mExtraTitle = (.*?), mChannelName='([^']*)', mChannelId='([^']*)'", text):
    p, title, cname, cid = m.groups()
    if cid.endswith("..."):  # long ids are truncated; resolve by channel name
        cid = next((c for (pp, c), v in channels.items() if pp == p and v["name"] == cname), cid)
    seen.append((p, cid, title))

stats = defaultdict(lambda: {"count": 0, "titles": set()})
for p, cid, title in seen:
    if p in IGNORE_PKGS:
        continue
    s = stats[(p, cid)]
    s["count"] += 1
    if title:
        s["titles"].add(title.strip())

rows = []
for (p, cid), s in stats.items():
    ch = channels.get((p, cid))
    if not ch or p in app_blocked:
        continue
    audible = ch["importance"] >= 3 and ch["sound"] not in ("null", "")
    generic = ch["sound"] in DEFAULT_SOUNDS
    if not audible or (not generic and not show_all):
        continue
    sound = "DEFAULT" if generic else re.sub(r".*title=([^&]*).*", r"\1", ch["sound"]).replace("%20", " ")
    rows.append((s["count"], p, cid, ch["name"], sound, ", ".join(sorted(s["titles"]))[:60]))

rows.sort(key=lambda r: (-r[0], r[1]))
if not rows:
    print("No recent audible notifications on a default-sound channel.")
for count, p, cid, name, sound, titles in rows:
    print(f"{count:3d}  {p}  [{name}]  sound={sound}")
    print(f"     channel: {cid}" + (f"   e.g. {titles}" if titles else ""))
    print(f"     open:    adb -s $S shell am start -a android.settings.CHANNEL_NOTIFICATION_SETTINGS "
          f"--es android.provider.extra.APP_PACKAGE {p} --es android.provider.extra.CHANNEL_ID '{cid}'")
