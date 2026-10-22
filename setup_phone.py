#!/usr/bin/env python3
"""Apply phone-config.txt to an Android phone over ADB. See setup-phone.sh."""
import argparse
from contextlib import contextmanager
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = HERE / ".venv" / "bin" / "python"
if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])

try:
    import uiautomator2 as u2
except ImportError:
    u2 = None

SEP = "-" * 60
IGNORE_PICKER_TEXTS = {
    "Save", "My Sounds", "Ringtone volume", "Notification volume",
    "None", "Sound", "Custom", "Galaxy", "Silent", "Ringtone", "Notification sound"
}


class Phone:
    def __init__(self, serial):
        self.serial = serial
        info = self.sh("getprop ro.product.manufacturer; echo ===; "
                       "getprop ro.product.model; echo ===; "
                       "wm size; echo ===; pm list packages")
        mfg, model, wmsize, pkgs = info.split("===\n", 3)
        self.maker = mfg.strip().lower()
        self.model = model.strip()
        w, h = re.search(r"(\d+)x(\d+)", wmsize.strip().splitlines()[-1]).groups()
        self.w, self.h = int(w), int(h)
        self.samsung = self.maker == "samsung"
        self._installed_pkgs = {
            line[8:].strip() for line in pkgs.splitlines() if line.startswith("package:")
        }
        self._media_cache = None
        self._channels_cache = None
        self._u2 = None

    @property
    def u2(self):
        if self._u2 is None and u2 is not None:
            self._u2 = u2.connect(self.serial)
            self._u2.jsonrpc.setConfigurator({
                "waitForIdleTimeout": 0,
                "waitForSelectorTimeout": 0,
                "actionAcknowledgmentTimeout": 50,
                "scrollAcknowledgmentTimeout": 50,
                "keyInjectionDelay": 0,
            })
        return self._u2

    # --- adb -------------------------------------------------------------
    def adb(self, *args, check=False):
        r = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        if check and r.returncode:
            raise RuntimeError(f"adb {' '.join(args)}: {r.stderr.strip()}")
        return r.stdout

    def sh(self, cmd):
        return self.adb("shell", cmd)

    @contextmanager
    def fast_ui(self):
        """Temporarily disable transition/window animations for fast UI automation."""
        keys = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")
        orig = self.sh("; ".join(f"settings get global {k}" for k in keys)).splitlines()
        saved = [v.strip() if v.strip() not in ("", "null") else "1.0" for v in orig]
        while len(saved) < 3:
            saved.append("1.0")
        self.sh("am force-stop com.android.settings; "
                "am force-stop com.google.android.soundpicker; " +
                "; ".join(f"settings put global {k} 0" for k in keys))
        try:
            yield
        finally:
            restore = "; ".join(f"settings put global {k} {v}" for k, v in zip(keys, saved))
            self.sh(f"{restore}; input keyevent KEYCODE_HOME")

    def snapshot(self, why):
        """Save a screenshot + UI dump of the current screen for diagnosing a failure."""
        d = HERE / "debug"
        d.mkdir(exist_ok=True)
        stamp = f"{time.strftime('%H%M%S')}-{self.serial}-{re.sub(r'[^A-Za-z0-9]+', '_', why)[:40]}"
        png = subprocess.run(["adb", "-s", self.serial, "exec-out", "screencap", "-p"],
                             capture_output=True, stdin=subprocess.DEVNULL).stdout
        (d / f"{stamp}.png").write_bytes(png)
        xml = self._dump_xml()
        (d / f"{stamp}.xml").write_text(xml)
        focus = re.search(r"mCurrentFocus=.*", self.sh("dumpsys window | grep mCurrentFocus"))
        print(f"  debug    {why}: saved debug/{stamp}.png/.xml  focus={focus.group(0) if focus else '?'}")

    def installed(self, pkg):
        return pkg in self._installed_pkgs

    # --- media -----------------------------------------------------------
    def push_folder(self, local, remote, extra_files=()):
        files = sorted(p for p in (HERE / local).iterdir() if p.suffix in (".ogg", ".mp3", ".m4a", ".wav"))
        by_name = {f.name: f for f in files}
        for ef in extra_files:
            by_name.setdefault(ef.name, ef)
        all_files = [by_name[k] for k in sorted(by_name)]

        # Check which files are already on the phone with identical byte size
        ls_out = self.sh(f"mkdir -p /sdcard/{remote} && ls -ln /sdcard/{remote}")
        remote_sizes = {}
        for line in ls_out.splitlines():
            m = re.match(r"^-\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+(.+)$", line.strip())
            if m:
                remote_sizes[m.group(2)] = int(m.group(1))

        to_scan = []
        for f in all_files:
            if remote_sizes.get(f.name) != f.stat().st_size:
                self.adb("push", "--sync", str(f), f"/sdcard/{remote}/")
                to_scan.append(f.name)

        if to_scan:
            # scan_file is what sets is_notification / is_ringtone (see README).
            cmds = [
                f"content call --uri content://media --method scan_file "
                f"--arg '/storage/emulated/0/{remote}/{name}' >/dev/null 2>&1"
                for name in to_scan
            ]
            self.sh("; ".join(cmds))
            self._media_cache = None
        return len(all_files)

    def _load_media_cache(self):
        if self._media_cache is not None:
            return
        self._media_cache = {}
        out = self.sh("content query --uri content://media/external/audio/media "
                      "--projection _id:_display_name:is_notification:is_ringtone")
        for line in out.splitlines():
            m = re.search(r"_id=(\d+),\s*_display_name=(.*?),\s*is_notification=(\S+?),\s*is_ringtone=(\S+)", line)
            if not m:
                continue
            mid, dname, is_notif, is_ring = m.groups()
            stem = dname.rsplit(".", 1)[0]
            if is_notif in ("1", "true"):
                self._media_cache[(stem, "notification")] = mid
            if is_ring in ("1", "true"):
                self._media_cache[(stem, "ringtone")] = mid

    def media_id(self, title, kind="notification"):
        """MediaStore id of a pushed sound; kind picks the Notifications/ or Ringtones/ copy."""
        self._load_media_cache()
        return self._media_cache.get((title, kind)) or self._media_cache.get((title, "ringtone"))

    # --- notification channels --------------------------------------------
    def invalidate_channels(self):
        self._channels_cache = None

    def _load_channels_cache(self):
        if self._channels_cache is not None:
            return
        dump = self.sh("dumpsys notification --noredact")
        cache = {}
        cur = None
        for line in dump.splitlines():
            m = re.match(r"\s*AppSettings: (\S+) \(\d+\) importance=(\S+)", line)
            if m:
                cur = m.group(1)
                entry = cache.setdefault(cur, {"channels": [], "seen_ids": set(), "app_on": None})
                entry["app_on"] = m.group(2) != "NONE"
                continue
            if not cur:
                continue
            m = re.search(r"NotificationChannel\{mId='([^']*)', mName=([^,]*),.*?mImportance=(-?\d+),"
                          r".*?mSound=([^,]*),.*?mDeleted=(\w+)", line)
            if m and m.group(5) == "false":
                entry = cache[cur]
                cid = m.group(1)
                if cid not in entry["seen_ids"]:
                    entry["seen_ids"].add(cid)
                    entry["channels"].append({
                        "id": cid, "name": m.group(2),
                        "importance": int(m.group(3)), "sound": m.group(4),
                    })
        self._channels_cache = cache

    def channels(self, pkg):
        """Live channels of pkg: list of dicts (id, name, importance, sound)."""
        self._load_channels_cache()
        entry = self._channels_cache.get(pkg)
        if not entry:
            return [], None
        return entry["channels"], entry["app_on"]

    @staticmethod
    def has_sound(ch, title):
        return f"title={urllib.parse.quote(title)}&" in ch["sound"] + "&"

    # --- UI automation ------------------------------------------------------
    def _dump_xml(self):
        if self.u2 is not None:
            try:
                return self.u2.jsonrpc.dumpWindowHierarchy(False, 50)
            except Exception:
                pass
        self.sh("uiautomator dump /sdcard/ui.xml")
        return self.sh("cat /sdcard/ui.xml")

    def nodes(self):
        xml = self._dump_xml()
        res = []
        for n in re.findall(r"<node [^>]*>", xml):
            g = lambda k: (re.search(k + r'="([^"]*)"', n) or [None, ""])[1]
            b = list(map(int, re.findall(r"\d+", g("bounds"))))
            if len(b) == 4:
                res.append({"text": (g("text") or g("content-desc")).replace("&amp;", "&"),
                            "cls": g("class").split(".")[-1], "checked": g("checked") == "true",
                            "checkable": g("checkable") == "true", "b": b})
        return res

    def find(self, text, cls=None, nodes=None):
        for n in nodes if nodes is not None else self.nodes():
            if n["text"] == text and (cls is None or n["cls"] in cls) and n["b"][3] - n["b"][1] > 30:
                return n
        return None

    def wait_for(self, text, cls=None, timeout=3.5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            n = self.find(text, cls)
            if n:
                return n
            time.sleep(0.06)
        return None

    def tap(self, n):
        b = n["b"]
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        if self.u2 is not None:
            try:
                self.u2.click(cx, cy)
                return
            except Exception:
                pass
        self.sh(f"input tap {cx} {cy}")

    def tap_text(self, text, cls=None, wait=0.25, timeout=3.0):
        n = self.wait_for(text, cls, timeout=timeout) if timeout > 0 else self.find(text, cls)
        if not n:
            return False
        self.tap(n)
        if wait > 0:
            time.sleep(wait)
        return True

    def scroll_to(self, text, cls=None, tries=18):
        """Scroll directly toward text using alphabetical order of sound rows."""
        x = self.w * 6 // 10
        target_low = text.lower()

        if self.samsung:
            # On Samsung, Custom sounds are at the very top above Galaxy sounds.
            ns = self.nodes()
            n = self.find(text, cls, ns)
            if n and self.h * 0.12 < n["b"][1] and n["b"][3] < self.h * 0.92:
                return n
            prev = None
            for _ in range(5):
                if self.find(text, cls, ns) or self.find("Custom", nodes=ns) or self.find("Silent", nodes=ns):
                    break
                self.sh(f"input swipe {x} {self.h * 1 // 4} {x} {self.h * 4 // 5} 180")
                time.sleep(0.3)
                ns = self.nodes()
                top = [(m["text"], m["b"][1]) for m in ns if m["text"]][:4]
                if top == prev:
                    break
                prev = top

        direction = 1  # 1 = scroll down (swipe up), -1 = scroll up (swipe down)
        prev_sig = None
        for _ in range(tries):
            ns = self.nodes()
            n = self.find(text, cls, ns)
            if n and self.h * 0.12 < n["b"][1] and n["b"][3] < self.h * 0.92:
                return n
            if not self.samsung:
                items = [
                    m["text"] for m in ns
                    if (cls is None or m["cls"] in cls)
                    and m["text"] and m["text"] not in IGNORE_PICKER_TEXTS
                    and not m["text"].startswith("Default (")
                    and not m["text"].endswith(" available")
                    and self.h * 0.15 < m["b"][1] < self.h * 0.90
                ]
                if items:
                    if target_low < items[0].lower():
                        direction = -1
                    elif target_low > items[-1].lower():
                        direction = 1
                sig = tuple(items[:4])
                if sig and sig == prev_sig:
                    direction = -direction
                prev_sig = sig
            if direction == 1:
                self.sh(f"input swipe {x} {self.h * 3 // 4} {x} {self.h * 1 // 4} 280")
            else:
                self.sh(f"input swipe {x} {self.h * 1 // 4} {x} {self.h * 3 // 4} 280")
            time.sleep(0.32)
        return None

    def key(self, k, wait=0.4):
        self.sh(f"input keyevent {k}")
        if wait > 0:
            time.sleep(wait)

    def open_channel(self, pkg, cid, reset_picker=False):
        # Reset com.android.settings so the requested channel opens cleanly;
        # keep com.google.android.soundpicker warm unless recovering from an error.
        stop = "am force-stop com.android.settings; "
        if reset_picker:
            stop += "am force-stop com.google.android.soundpicker; "
        self.sh(f"{stop}am start -a android.settings.CHANNEL_NOTIFICATION_SETTINGS "
                f"--es android.provider.extra.APP_PACKAGE {pkg} "
                f"--es android.provider.extra.CHANNEL_ID '{cid}'")

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
                        time.sleep(0.4)
                    return True
        return False

    def open_sound_settings(self):
        self.sh("am force-stop com.android.settings; am start -a android.settings.SOUND_SETTINGS")
        self.wait_for("Ringtone", ("TextView",), timeout=3.0)

    def samsung_default_summary(self, label):
        """Text under 'Ringtone' / 'Notification sound' in Sounds and vibration."""
        self.open_sound_settings()
        ns = self.nodes()
        for i, n in enumerate(ns):
            if n["text"] == label and n["cls"] == "TextView":
                nxt = [m for m in ns[i + 1:] if m["cls"] == "TextView"]
                self.key("KEYCODE_HOME", 0.3)
                return nxt[0]["text"] if nxt else ""
        self.key("KEYCODE_HOME", 0.3)
        return ""

    def samsung_set_default(self, label, title):
        self.open_sound_settings()
        if not self.tap_text(label, ("TextView",), wait=0.4, timeout=3.0):
            self.snapshot(f"no {label} row")
            return f"no '{label}' row"
        n = self.scroll_to(title, ("CheckedTextView",), tries=25)
        if not n:
            self.key("KEYCODE_HOME", 0.3)
            return f"'{title}' not in the list"
        self.tap(n)
        time.sleep(0.4)
        self.key("KEYCODE_BACK", 0.6)
        self.key("KEYCODE_HOME", 0.3)
        return None

    def pick_sound(self, title):
        """On a channel settings screen: Sound -> choose title -> save/back."""
        if not self.tap_text("Sound", ("TextView",), wait=0.25, timeout=4.0):
            self.snapshot("no Sound row")
            return "no 'Sound' row on the channel screen"
        if self.samsung:
            n = self.scroll_to(title, ("CheckedTextView",))
            if not n:
                self.key("KEYCODE_BACK")
                return f"'{title}' not in the sound list"
            self.tap(n)
            time.sleep(0.4)
            self.key("KEYCODE_BACK", 0.6)  # Samsung saves on leaving the picker
        else:  # Pixel / Google sound picker
            if not self.tap_text("My Sounds", wait=0.25, timeout=3.5):
                if not self.find("Save", ("Button",)):
                    self.snapshot("no My Sounds")
                    return "no 'My Sounds' row in sound picker"
            n = self.scroll_to(title, ("TextView",))
            if not n:
                self.sh("am force-stop com.google.android.soundpicker")
                return f"'{title}' not in My Sounds"
            # The selected row's description becomes "Sound, <title>"; confirm before saving.
            for _ in range(3):
                self.tap(n)
                time.sleep(0.25)
                ns = self.nodes()
                if self.find(f"Sound, {title}", ("LinearLayout",), ns):
                    break
                n = self.find(title, ("TextView",), ns) or n
            else:
                self.sh("am force-stop com.google.android.soundpicker")
                return f"could not select '{title}'"
            save_btn = self.find("Save", ("Button",), ns) or self.wait_for("Save", ("Button",), timeout=1.5)
            if not save_btn:
                self.sh("am force-stop com.google.android.soundpicker")
                return "no Save button in the picker"
            self.tap(save_btn)
            time.sleep(0.35)
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
        notif_chips = sorted((HERE / "notifications").glob("chipmunk *.ogg"))
        print(f"  notifications: {ph.push_folder('notifications', 'Notifications')} files")
        # Also include chipmunk notification clips in Ringtones so channels with
        # USAGE_NOTIFICATION_RINGTONE (e.g. Facebook) list them in the picker.
        print(f"  ringtones:     {ph.push_folder('ringtones', 'Ringtones', extra_files=notif_chips)} files")

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
                ph.invalidate_channels()
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
            who, title = f
            if who.startswith("+") or who[:1].isdigit():
                out = ph.sh(f"content query --uri content://com.android.contacts/phone_lookup/"
                            f"{urllib.parse.quote(who)} --projection _id:display_name:custom_ringtone")
            else:
                q = who.replace("'", "''")
                out = ph.sh("content query --uri content://com.android.contacts/contacts "
                            f"--projection _id:display_name:custom_ringtone --where \"display_name='{q}'\"")
            rows = list(dict.fromkeys(re.findall(r"_id=(\d+), display_name=(.*?), custom_ringtone=([^\s,]+)", out)))
            if not rows:
                pending.append(f"contact {who}: no matching contact")
                continue
            mid = ph.media_id(title, "ringtone")
            if not mid:
                failed.append(f"contact {who}: ringtone '{title}' not on phone (push first)")
                continue
            uri = f"content://media/external/audio/media/{mid}"
            for cid, name, cur in rows:
                label = f"{name} (#{cid})" if len(rows) > 1 else name
                if cur == uri:
                    print(f"  ok       {label} -> {title}")
                    continue
                print(f"  {'would set' if a.dry_run else 'set'}      {label} -> {title}")
                if not a.dry_run:
                    esc = uri.replace(":", r"\:", 1)
                    res = ph.sh(f"content update --uri content://com.android.contacts/contacts/{cid} "
                                f"--bind 'custom_ringtone:s:{esc}'")
                    if "ERROR" in res:
                        failed.append(f"contact {label}: {res.strip().splitlines()[-1]}")

    # 5. channel sounds (UI automation)
    if step("channel"):
        print(SEP + "\nNotification channel sounds")
        from contextlib import nullcontext
        ctx = nullcontext() if a.dry_run else ph.fast_ui()
        with ctx:
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
                for _round in range(4):  # up to 3 attempts + 1 post-check
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
                    if _round == 3:
                        failed.append(f"{pkg} [{match}]: sound keeps reverting")
                        break
                    for c in todo:
                        label = f"{pkg} [{c['name']}] {c['id']}"
                        if a.dry_run:
                            print(f"  would set {label} -> {title}" + ("  (+turn on)" if c["importance"] == 0 else ""))
                            done_ids.add(c["id"])
                            continue
                        print(f"  set      {label} -> {title}", flush=True)
                        ph.open_channel(pkg, c["id"], reset_picker=(_round > 0))
                        if c["importance"] == 0:
                            ph.turn_on_switch_near(["Allow notifications", "Show notifications"])
                        err = ph.pick_sound(title)
                        if err and _round == 2:
                            failed.append(f"{label}: {err}")
                        done_ids.add(c["id"])
                    if a.dry_run:
                        break
                    ph.invalidate_channels()
        if not a.dry_run:  # final verification
            ph.invalidate_channels()
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
