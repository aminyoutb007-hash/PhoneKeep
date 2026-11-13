"""S3: no network (docs/spec/04-security.md).

Done when: "A full backup + export + phone-window session shows zero outbound internet connections."
This test installs the in-process guard (netguard.py, as launcher.py does for the real app), then runs
a full backup (the phone is a stub launcher that produces the fake backup), a full export, and a
phone-window session with the simulated iPhone, and fails if any connection went anywhere other than
the phone or this computer. It also proves the guard refuses the internet and that the one opt-in
request (Check for updates) is the only thing allowed through, and only while it runs.
"""
import json, os, shutil, socket, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import netguard
netguard.install()

import phonekeep as wv
import sections as sx
import keychain

keychain.use_memory()

import applock

applock.use_backend(lambda: None, lambda reason: False)   # no Touch ID prompts in tests (S2 has its own)

W = HERE / "work" / "s3"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- the guard itself ---------------------------------------------------------------------------
check(netguard.installed(), "guard installed")
try:
    s = socket.socket()
    s.settimeout(3)
    s.connect(("93.184.216.34", 443))
    s.close()
    check(False, "internet connection refused")
except netguard.NetworkRefused as e:
    check("doesn't connect to the internet" in str(e), f"internet connection refused with a plain message: {e}")
except OSError as e:
    check(False, f"internet connection refused by PhoneKeep, not by the network ({e})")
check(socket.socket().connect_ex(("8.8.8.8", 53)) == 111, "connect_ex refuses too")
check(netguard._is_local("127.0.0.1") and netguard._is_local("192.168.1.20") and netguard._is_local("fe80::1")
      and netguard._is_local("Amins-iPhone.local"), "the phone's addresses (loopback, Wi-Fi, Bonjour) are allowed")
check(not netguard._is_local("93.184.216.34") and not netguard._is_local("2606:2800:220:1:248:1893:25c8:1946"),
      "public addresses are not")

# the opt-in update check is the only exception, and only while it runs
before = len(netguard.EVENTS)
r = wv.check_for_updates(timeout=5)
opt_in = [e for e in netguard.EVENTS[before:] if e["why"] == "Check for updates"]
check(all(e["allowed"] for e in opt_in), "Check for updates is allowed through the guard while it runs")
check(r["current"] == wv.VERSION and (r["latest"] or r["error"] or "404" in r.get("detail", "")),
      f"update check returns a version, 'no release yet' or a plain error ({r.get('latest') or r.get('error') or 'no release yet'})")
check(wv._version_tuple("5.0.1") > wv._version_tuple("4.0.1") and not wv._version_tuple("4.0.1") > wv._version_tuple("4.0.1"),
      "version comparison")
try:
    socket.socket().connect(("93.184.216.34", 443))
    check(False, "after the update check the internet is refused again")
except netguard.NetworkRefused:
    check(True, "after the update check the internet is refused again")
netguard.EVENTS.clear()

# -- a stub phone: the launcher 'backs up' by producing the fake backup -----------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
stub = W / "stub_launcher.py"
stub.write_text(f'''
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-backup":
    target = Path(args[1]) / "00008030-S3TEST"
    if not (target / "Manifest.db").exists():
        shutil.copytree(r"{fake}", target)
    for p in (10, 50, 100):
        print(f"PKPCT {{p}}", flush=True)
elif args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 0")
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.list_devices = lambda: [{"DeviceName": "S3 iPhone", "UniqueDeviceID": "00008030-S3TEST", "ConnectionType": "USB",
                            "ProductVersion": "26.1"}]
wv.check_pmd3 = lambda: None

# 1. full backup
path = wv.make_backup(W / "Backups", "00008030-S3TEST", log=lambda m: None)
check((path / "Manifest.db").exists(), "full backup made (stub phone)")

# 2. full export
index = sx.export_all(path, W / "Archive", None, list(sx.DEFAULT_SECTIONS), include_media=True, log=lambda m: None)
check(Path(index).exists(), "full export made")

# 3. phone-window session with the simulated iPhone
import tkinter as tk
import device as devmod
import photos as ph
import phone


class SimDevice:
    def __init__(self, udid, cache_dir=None):
        self.udid = udid

    def wallpaper(self, which="homescreen"):
        return None

    def music(self):
        return []

    def books(self):
        return []

    def apps(self):
        return [devmod.AppInfo("org.videolan.vlc-ios", "VLC", "3.5", True)]

    def app_list(self, bundle_id, path="Documents"):
        return []

    def close(self):
        pass


class NoPhotos:
    def __init__(self, *a):
        raise wv.PhoneKeepError("no live photos in this test")


devmod.LiveDevice = SimDevice
ph.DevicePhotoSource = NoPhotos


class FakeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(W / "Backups"), "archive_dir": str(W / "Archive-window")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass


import time
app = FakeApp()
win = phone.PhoneWindow(app, {"DeviceName": "S3 iPhone"}, "00008030-S3TEST")
win.withdraw()
end = time.time() + 90
backup_apps = [k for k, *_r, where in phone.APPS if where == "backup"]
while time.time() < end and not all(k in win.counts for k in backup_apps):
    app.update(); time.sleep(0.02)
for key in ("messages", "whatsapp", "contacts", "notes", "safari", "files", "photos"):
    win.open_app(key)
    t = time.time() + 30
    while time.time() < t:
        app.update(); time.sleep(0.02)
        if not any(l.cget("text") in ("Loading…", "Reading from the iPhone…") for l in win.content.winfo_children()
                   if isinstance(l, tk.Label)):
            break
win.export_section("messages", {"excel", "web", "csv"})
t = time.time() + 60
while time.time() < t and not str(win.bar_text.cget("text")).startswith("✓"):
    app.update(); time.sleep(0.02)
check(str(win.bar_text.cget("text")).startswith("✓"), "phone-window session: an app export completed")
win.close()
app.update()
app.destroy()

# -- the verdict ------------------------------------------------------------------------------------
internet = netguard.internet_events()
check(not internet, f"zero outbound internet connections during backup + export + phone window ({len(internet)} found)")
for e in internet:
    print("   ", json.dumps(e))
refused = [e for e in netguard.EVENTS if not e["allowed"]]
check(not refused, f"and nothing even tried ({len(refused)} refused attempts)")

print("\nS3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
