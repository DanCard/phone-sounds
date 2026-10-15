#!/usr/bin/env python3
"""Apply phone-config.txt to an Android phone over ADB. See setup-phone.sh."""
import argparse
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEP = "-" * 60


class Phone:
    def __init__(self, serial):
        self.serial = serial
        self.maker = self.sh("getprop ro.product.manufacturer").strip().lower()
        self.model = self.sh("getprop ro.product.model").strip()
        w, h = re.search(r"(\d+)x(\d+)", self.sh("wm size").splitlines()[-1]).groups()
        self.w, self.h = int(w), int(h)
        self.samsung = self.maker == "samsung"

    # --- adb -------------------------------------------------------------
    def adb(self, *args, check=False):
        r = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        if check and r.returncode:
            raise RuntimeError(f"adb {' '.join(args)}: {r.stderr.strip()}")
        return r.stdout

    def sh(self, cmd):
        return self.adb("shell", cmd)

    def installed(self, pkg):
        return f"package:{pkg}\n" in self.sh(f"pm list packages {pkg}") + "\n"

    # --- media -----------------------------------------------------------
    def push_folder(self, local, remote):
        files = sorted(p for p in (HERE / local).iterdir() if p.suffix in (".ogg", ".mp3", ".m4a", ".wav"))
        self.sh(f"mkdir -p /sdcard/{remote}")
        for f in files:
            self.adb("push", "--sync", str(f), f"/sdcard/{remote}/")
            # scan_file is what sets is_notification / is_ringtone (see README).
            self.sh(f"content call --uri content://media --method scan_file "
                    f"--arg '/storage/emulated/0/{remote}/{f.name}'")
        return len(files)

    def media_id(self, title, kind="notification"):
        """MediaStore id of a pushed sound; kind picks the Notifications/ or Ringtones/ copy."""
        out = self.sh("content query --uri content://media/external/audio/media "
                      f"--projection _id --where \"_display_name LIKE '{title}.%' AND is_{kind}=1\"")
        m = re.search(r"_id=(\d+)", out)
        return m.group(1) if m else None

    # --- notification channels --------------------------------------------
    def channels(self, pkg):
        """Live channels of pkg: list of dicts (id, name, importance, sound)."""
        dump = self.sh("dumpsys notification --noredact")
        out, app_on, cur = [], None, None
        for line in dump.splitlines():
            m = re.match(r"\s*AppSettings: (\S+) \(\d+\) importance=(\S+)", line)
            if m:
                cur = m.group(1)
                if cur == pkg:
                    app_on = m.group(2) != "NONE"
                continue
            if cur != pkg:
                continue
            m = re.search(r"NotificationChannel\{mId='([^']*)', mName=([^,]*),.*?mImportance=(-?\d+),"
                          r".*?mSound=([^,]*),.*?mDeleted=(\w+)", line)
            if m and m.group(5) == "false" and not any(c["id"] == m.group(1) for c in out):
                out.append({"id": m.group(1), "name": m.group(2), "importance": int(m.group(3)),
                            "sound": m.group(4)})
        return out, app_on

    @staticmethod
    def has_sound(ch, title):
        return f"title={urllib.parse.quote(title)}&" in ch["sound"] + "&"

    # --- UI automation ------------------------------------------------------
    def nodes(self):
        self.sh("uiautomator dump /sdcard/ui.xml")
        xml = self.sh("cat /sdcard/ui.xml")
        res = []
        for n in re.findall(r"<node [^>]*>", xml):
            g = lambda k: (re.search(k + r'="([^"]*)"', n) or [None, ""])[1]
            b = list(map(int, re.findall(r"\d+", g("bounds"))))
            res.append({"text": (g("text") or g("content-desc")).replace("&amp;", "&"),
                        "cls": g("class").split(".")[-1], "checked": g("checked") == "true",
                        "checkable": g("checkable") == "true", "b": b})
        return res

    def find(self, text, cls=None, nodes=None):
        for n in nodes if nodes is not None else self.nodes():
            if n["text"] == text and (cls is None or n["cls"] in cls) and n["b"][3] - n["b"][1] > 30:
                return n
        return None

    def tap(self, n):
        b = n["b"]
        self.sh(f"input tap {(b[0] + b[2]) // 2} {(b[1] + b[3]) // 2}")

    def tap_text(self, text, cls=None, wait=2.5):
        n = self.find(text, cls)
        if not n:
            return False
        self.tap(n)
        time.sleep(wait)
        return True

    def scroll_to(self, text, cls=None, tries=25):
        """Scroll down in small steps until text is fully on screen and still.

        Pickers open scrolled to the current selection (Samsung puts the
        Custom section at the TOP), so first scroll all the way up."""
        x = self.w * 6 // 10
        prev = None
        for _ in range(40):
            if self.find(text, cls):
                break
            for _ in range(4):
                self.sh(f"input swipe {x} {self.h * 2 // 5} {x} {self.h * 3 // 4} 150")
            time.sleep(1)
            top = [(n["text"], n["b"][1]) for n in self.nodes() if n["text"]][:8]
            if top == prev:
                break
            prev = top
        for _ in range(tries):
            ns = self.nodes()
            n = self.find(text, cls, ns)
            if n and n["b"][3] < self.h * 0.92:
                time.sleep(1)  # a fling may still be moving the list: wait until stable
                again = self.find(text, cls)
                if again and again["b"] == n["b"]:
                    return n
                continue
            self.sh(f"input swipe {x} {self.h * 3 // 4} {x} {self.h * 2 // 5} 700")
            time.sleep(1)
        return None

    def key(self, k, wait=1.5):
        self.sh(f"input keyevent {k}")
        time.sleep(wait)

    def open_channel(self, pkg, cid):
        # Start clean: a leftover Settings/picker screen would otherwise be
        # brought to the front instead of the channel we asked for.
        for p in ("com.android.settings", "com.google.android.soundpicker"):
            self.sh(f"am force-stop {p}")
        self.sh("am start -a android.settings.CHANNEL_NOTIFICATION_SETTINGS "
                f"--es android.provider.extra.APP_PACKAGE {pkg} "
                f"--es android.provider.extra.CHANNEL_ID '{cid}'")
        time.sleep(3)

    def turn_on_switch_near(self, labels):
        ns = self.nodes()
        for lab in labels:
            row = self.find(lab, nodes=ns)
            if not row:
                continue
            for n in ns:  # the switch sharing the label's row
                if n["cls"] == "Switch" and n["b"][1] < row["b"][3] and n["b"][3] > row["b"][1]:
                    if not n["checked"]:
                        self.tap(n)
                        time.sleep(2)
                    return True
        return False

    def open_sound_settings(self):
        self.sh("am force-stop com.android.settings")
        self.sh("am start -a android.settings.SOUND_SETTINGS")
        time.sleep(3)

    def samsung_default_summary(self, label):
        """Text under 'Ringtone' / 'Notification sound' in Sounds and vibration."""
        self.open_sound_settings()
        ns = self.nodes()
        for i, n in enumerate(ns):
            if n["text"] == label and n["cls"] == "TextView":
                nxt = [m for m in ns[i + 1:] if m["cls"] == "TextView"]
                self.key("KEYCODE_HOME", 1)
                return nxt[0]["text"] if nxt else ""
        self.key("KEYCODE_HOME", 1)
        return ""

    def samsung_set_default(self, label, title):
        self.open_sound_settings()
        if not self.tap_text(label, ("TextView",), wait=3):
            return f"no '{label}' row"
        n = self.scroll_to(title, ("CheckedTextView",), tries=40)
        if not n:
            self.key("KEYCODE_HOME", 1)
            return f"'{title}' not in the list"
        self.tap(n)
        time.sleep(1.5)
        self.key("KEYCODE_BACK", 2)
        self.key("KEYCODE_HOME", 1)
        return None

    def pick_sound(self, title):
        """On a channel settings screen: Sound -> choose title -> save/back."""
        if not self.tap_text("Sound", ("TextView",), wait=3):
            return "no 'Sound' row on the channel screen"
        if self.samsung:
            n = self.scroll_to(title, ("CheckedTextView",))
            if not n:
                self.key("KEYCODE_BACK")
                return f"'{title}' not in the sound list"
            self.tap(n)
            time.sleep(1.5)
            self.key("KEYCODE_BACK", 2.5)  # Samsung saves on leaving the picker
        else:  # Pixel / Google sound picker
            self.tap_text("My Sounds", wait=3)
            n = self.scroll_to(title, ("TextView",))
            if not n:
                self.key("KEYCODE_BACK")
                self.key("KEYCODE_BACK")
                return f"'{title}' not in My Sounds"
            # The selected row's description becomes "Sound, <title>"; confirm before saving.
            for _ in range(3):
                self.tap(n)
                time.sleep(1.5)
                if self.find(f"Sound, {title}", ("LinearLayout",)):
                    break
                n = self.scroll_to(title, ("TextView",)) or n
            else:
                self.key("KEYCODE_BACK")
                self.key("KEYCODE_BACK")
                return f"could not select '{title}'"
            if not self.tap_text("Save", ("Button",), wait=2.5):
                return "no Save button in the picker"
            if self.find("Save", ("Button",)):  # picker still open
                self.key("KEYCODE_BACK")
        return None


def load_config(path):
    rules = []
    for ln, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("manual") else line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        only = None
        if parts[-1].startswith("only:"):
            only = parts.pop()[5:].strip().lower()
        rules.append((ln, parts[0], parts[1:], only))
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial")
    ap.add_argument("--config", default=str(HERE / "phone-config.txt"))
    ap.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    ap.add_argument("--no-push", action="store_true", help="skip pushing sound files")
    ap.add_argument("--only", choices=["push", "enable", "default", "contact", "channel"], help="run one step")
    a = ap.parse_args()

    ph = Phone(a.serial)
    ident = f"{ph.serial} {ph.maker} {ph.model}".lower()
    loaded = load_config(a.config)
    local = Path(a.config).with_name("phone-config.local.txt")  # private rules, git-ignored
    if local.exists():
        loaded += load_config(local)
    rules = [(ln, k, f) for ln, k, f, only in loaded if not only or only in ident]
    step = lambda s: a.only in (None, s)
    pending, failed, manual = [], [], []
    print(f"Phone: {ph.model} ({ph.serial}), {'Samsung' if ph.samsung else 'Pixel/AOSP'} UI"
          + ("  [DRY RUN]" if a.dry_run else ""))

    # 1. sound files
    if step("push") and not a.no_push and not a.dry_run:
        print(SEP + "\nPushing sounds")
        print(f"  notifications: {ph.push_folder('notifications', 'Notifications')} files")
        print(f"  ringtones:     {ph.push_folder('ringtones', 'Ringtones')} files")

    # 2. app-level notifications on
    if step("enable"):
        print(SEP + "\nApp notifications")
        for ln, kind, f in rules:
            if kind != "enable":
                continue
            pkg = f[0]
            if not ph.installed(pkg):
                pending.append(f"{pkg}: not installed")
                continue
            _, on = ph.channels(pkg)
            if on is not False:
                print(f"  ok       {pkg}")
                continue
            print(f"  {'would enable' if a.dry_run else 'enable'}   {pkg}")
            if not a.dry_run:
                ph.sh(f"pm grant {pkg} android.permission.POST_NOTIFICATIONS")
                if ph.channels(pkg)[1] is False:
                    failed.append(f"{pkg}: still blocked; turn on in Settings > Apps > {pkg} > Notifications")

    # 3. phone-wide default notification sound / ringtone
    if step("default"):
        print(SEP + "\nDefault sounds")
        for ln, kind, f in rules:
            if kind != "default":
                continue
            what, title = f
            mid = ph.media_id(title, what)
            if not mid:
                failed.append(f"default {what}: '{title}' not on phone (push first)")
                continue
            if ph.samsung:
                # Samsung restores these settings from its own *_CONSTANT_PATH copies,
                # so `settings put` doesn't stick; go through Sounds and vibration.
                label = "Notification sound" if what == "notification" else "Ringtone"
                cur = ph.samsung_default_summary(label)
                if cur.endswith(title):
                    print(f"  ok       {label} -> {title}")
                    continue
                print(f"  {'would set' if a.dry_run else 'set'}      {label} -> {title}  (was: {cur})")
                if not a.dry_run:
                    err = ph.samsung_set_default(label, title)
                    if err or not ph.samsung_default_summary(label).endswith(title):
                        failed.append(f"default {label}: {err or 'did not stick'}; "
                                      f"Settings > Sounds and vibration > {label}")
                continue
            uri = f"content://media/external/audio/media/{mid}"
            keys = ["notification_sound"] if what == "notification" else ["ringtone", "ringtone_2"]
            for key in keys:
                cur = ph.sh(f"settings get system {key}").strip()
                if key == "ringtone_2" and cur == "null":
                    continue  # single-SIM phone
                if cur.split("?")[0] == uri:
                    print(f"  ok       {key} -> {title}")
                    continue
                print(f"  {'would set' if a.dry_run else 'set'}      {key} -> {title}")
                if not a.dry_run:
                    ph.sh(f"settings put system {key} '{uri}?title={urllib.parse.quote(title)}&canonical=1'")
                    if ph.sh(f"settings get system {key}").strip().split("?")[0] != uri:
                        failed.append(f"default {key}: could not set; Settings > Sounds > {what}")

    # 4. contact ringtones
    if step("contact"):
        print(SEP + "\nContact ringtones")
        for ln, kind, f in rules:
            if kind != "contact":
                continue
            num, title = f
            out = ph.sh(f"content query --uri content://com.android.contacts/phone_lookup/"
                        f"{urllib.parse.quote(num)} --projection _id:display_name:custom_ringtone")
            m = re.search(r"_id=(\d+), display_name=(.*?), custom_ringtone=(\S+?),", out)
            if not m:
                pending.append(f"contact {num}: no contact with this number")
                continue
            cid, name, cur = m.groups()
            mid = ph.media_id(title, "ringtone")
            if not mid:
                failed.append(f"contact {name}: ringtone '{title}' not on phone (push first)")
                continue
            uri = f"content://media/external/audio/media/{mid}"
            if cur == uri:
                print(f"  ok       {name} -> {title}")
                continue
            print(f"  {'would set' if a.dry_run else 'set'}      {name} -> {title}")
            if not a.dry_run:
                ph.sh(f"content update --uri content://com.android.contacts/contacts/{cid} "
                      f"--bind custom_ringtone:s:{uri.replace(':', chr(92) + ':', 1)}")

    # 5. channel sounds (UI automation)
    if step("channel"):
        print(SEP + "\nNotification channel sounds")
        for ln, kind, f in rules:
            if kind != "channel":
                continue
            pkg, match, title = f
            mkey, mval = match.split(":", 1)
            if not ph.installed(pkg):
                pending.append(f"{pkg}: not installed")
                continue
            if not ph.media_id(title):
                failed.append(f"{pkg}: sound '{title}' not on phone (push first)")
                continue
            done_ids = set()
            for _round in range(3):  # re-check: some apps (Signal) replace the channel on change
                chans, _ = ph.channels(pkg)
                todo = [c for c in chans if c[mkey] == mval]
                if not todo:
                    if not done_ids:
                        pending.append(f"{pkg} [{match}]: channel not created yet; open the app, "
                                       f"sign in or wait for a notification, then re-run")
                    break
                todo = [c for c in todo if not ph.has_sound(c, title) or c["importance"] == 0]
                if not todo:
                    for c in chans:
                        if c[mkey] == mval and c["id"] not in done_ids:
                            print(f"  ok       {pkg} [{c['name']}] {c['id']} -> {title}")
                    break
                for c in todo:
                    label = f"{pkg} [{c['name']}] {c['id']}"
                    if a.dry_run:
                        print(f"  would set {label} -> {title}" + ("  (+turn on)" if c["importance"] == 0 else ""))
                        done_ids.add(c["id"])
                        continue
                    print(f"  set      {label} -> {title}")
                    ph.open_channel(pkg, c["id"])
                    if c["importance"] == 0:
                        ph.turn_on_switch_near(["Allow notifications", "Show notifications"])
                    err = ph.pick_sound(title)
                    ph.key("KEYCODE_HOME", 1)
                    if err:
                        failed.append(f"{label}: {err}")
                    done_ids.add(c["id"])
                if a.dry_run:
                    break
                time.sleep(2)
            else:
                failed.append(f"{pkg} [{match}]: sound keeps reverting")
        if not a.dry_run:  # final verification
            for ln, kind, f in rules:
                if kind == "channel" and ph.installed(f[0]):
                    mkey, mval = f[1].split(":", 1)
                    for c in ph.channels(f[0])[0]:
                        if c[mkey] == mval and not ph.has_sound(c, f[2]):
                            failed.append(f"{f[0]} [{c['name']}] {c['id']}: verify failed, sound={c['sound']}")

    manual = [f[0] for _, k, f in rules if k == "manual"]
    print(SEP)
    for title, items in (("PENDING (re-run later)", pending), ("FAILED", failed), ("DO BY HAND", manual)):
        if items:
            print(title + ":")
            for i in dict.fromkeys(items):
                print("  - " + i)
    if not pending and not failed:
        print("All automatic steps done.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
