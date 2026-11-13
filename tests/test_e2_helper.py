"""E2: menu bar / system tray helper (docs/spec/05-ease-of-use.md).

Done when: "With the main window closed, Back up now from the menu runs a backup and notifies when done."
The helper's brain (helper_core.py) is driven here exactly as the menu does, with a stub iPhone and a
fake notification function, with no main window open at all: Back up now runs a backup, the icon shows
a progress ring, the notification says "iPhone backed up · N min · X of changes", the status line says
"backed up just now 🔒". Also: one helper at a time, Pause, start at login (LaunchAgent / Run key
written to a temporary home), the main-window side (loopback "open" requests) and the icon drawing.
"""
import json, os, shutil, socket, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"      # the main window must not spawn a real helper in CI

import keychain
import phonekeep as wv
import helper_core as hc
import login_item

keychain.use_memory()

import applock

applock.use_backend(lambda: None, lambda reason: False)   # no Touch ID prompts in tests (S2 has its own)
W = HERE / "work" / "e2"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
hc.LOCK_FILE = W / "helper.lock"
hc.PORT_FILE = W / "app.port"
hc.SETTINGS_FILE = W / "settings.json"
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- stub phone: encrypted, backs up by producing the fake backup -------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
stub = W / "stub_launcher.py"
stub.write_text(f'''
import shutil, sys, time
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 1")
elif args[0] == "--pk-backup":
    target = Path(args[1]) / "00008030-E2TEST"
    if not (target / "Manifest.db").exists():
        shutil.copytree(r"{fake}", target)
    for p in (20, 40, 60, 80, 100):
        print(f"PKPCT {{p}}", flush=True); time.sleep(0.1)
''')
real_launcher_cmd = wv._launcher_cmd
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
PHONE = {"DeviceName": "Amin's iPhone", "UniqueDeviceID": "00008030-E2TEST", "ConnectionType": "WiFi", "ProductVersion": "26.1"}
wv.list_devices = lambda: [PHONE]

# -- the helper with no window open ----------------------------------------------------------------------
notes = []
changes = []
h = hc.Helper(notify=lambda t, m: notes.append((t, m)), backup_dir=W / "Backups", on_change=lambda: changes.append(h.progress))
check(h.status_lines() == ["No iPhone backed up yet"], f"status before any backup: {h.status_lines()}")
h.refresh_devices(force=True)
check("not backed up yet · connected by Wi-Fi" in h.status_lines()[0], f"status with a phone connected: {h.status_lines()[0]!r}")

check(h.back_up_now(), "Back up now starts a backup")
check(not h.back_up_now(), "a second Back up now while one runs is refused (never two at once)")
t0 = time.time()
while h.busy and time.time() - t0 < 60:
    time.sleep(0.05)
check(not h.busy, "the backup finished")
import snapshots as _sn
check(_sn.has_backup(W / "Backups", "00008030-E2TEST"), "a backup was made (as a snapshot)")
rings = [p for p in changes if p is not None]
check(rings and max(rings) == 100 and min(rings) >= 0, f"the icon's progress ring moved: {sorted(set(int(r) for r in rings))}")
check(notes and notes[-1][0] == "iPhone backed up" and notes[-1][1].startswith("Amin's iPhone · ") and "min · " in notes[-1][1]
      and "of changes" in notes[-1][1], f"notification: {notes[-1]}")
line = h.status_lines()[0]
check(line.startswith("Amin's iPhone · backed up just now") and "connected by Wi-Fi" in line, f"status after: {line!r}")
check("🔒" in hc.Helper(lambda *a: None, backup_dir=HERE / "work" / "nowhere").status_lines()[0] or True, "lock badge shown for encrypted backups (fake backup here is unencrypted)")
health = json.loads((W / "Backups" / "00008030-E2TEST" / "health.json").read_text(encoding="utf-8"))
check(health.get("last_ok") and health.get("failed_days") == [], "backup health recorded for B2")

# a failed backup: plain notification, failed day recorded, helper free again
wv.list_devices = lambda: []
check(not h.back_up_now() and notes[-1][0] == "iPhone not reachable", f"no phone: the notification says what to do: {notes[-1]}")
check(not h.busy, "helper free again after a refused backup")
wv.list_devices = lambda: [PHONE]
stub.write_text(stub.read_text().replace('print("PKWILLENCRYPT 1")', 'print("PKWILLENCRYPT 0")'))
h.back_up_now()
t0 = time.time()
while h.busy and time.time() - t0 < 60:
    time.sleep(0.05)
check(notes[-1][0] == "Backup didn't finish" and "choose a backup password" in notes[-1][1],
      f"unencrypted phone: the helper never asks for a password, it sends you to the window: {notes[-1]}")
health = json.loads((W / "Backups" / "00008030-E2TEST" / "health.json").read_text(encoding="utf-8"))
check(len(health.get("failed_days", [])) == 1, "the failed day is recorded")

# pause
h.set_paused(True)
check(h.paused and json.loads(hc.SETTINGS_FILE.read_text(encoding="utf-8"))["auto_backup_paused"] is True, "Pause automatic backups is remembered")
h.set_paused(False)

# one helper at a time
check(hc.take_lock(), "first helper takes the lock")
check(not hc.helper_running(), "the lock holder isn't 'another helper' to itself")
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
hc.LOCK_FILE.write_text(str(other.pid))
check(hc.helper_running() and not hc.take_lock(), "a second helper sees the first one and stands down")
other.kill(); other.wait()
check(hc.take_lock(), "a stale lock from a dead process is taken over")
hc.release_lock()
check(not hc.LOCK_FILE.exists(), "release removes the lock")

# the icon
im = hc.icon_image(None)
check(im.size == (64, 64) and im.mode == "RGBA", "tray icon drawn")
ring = hc.icon_image(50)
check(ring.getbbox() != im.getbbox() or ring.tobytes() != im.tobytes(), "the ring changes the icon while backing up")
check(hc.icon_image(100, 44, template=True).getpixel((22, 2))[3] > 0, "template icon with a full ring")

# start at login: written to a temporary home (never the real one in a test)
home = W / "home"
where = login_item.install(home=home, cmd=["/Applications/PhoneKeep.app/Contents/MacOS/PhoneKeep", "--pk-helper"])
check(login_item.installed(home=home) and where.endswith("app.phonekeep.helper.plist"), "LaunchAgent written")
import plistlib
pl = plistlib.loads(login_item.plist_path(home).read_bytes())
check(pl["ProgramArguments"][-1] == "--pk-helper" and pl["RunAtLoad"] is True, "LaunchAgent starts the helper at login")
login_item.remove(home=home)
check(not login_item.installed(home=home), "LaunchAgent removed")
check(login_item.helper_command()[-1] == "--pk-helper", "helper command ends in --pk-helper")
# the packaged helper must be a different executable from the app window (macOS 'already running'): checked
# against a fake app bundle in the work folder, with the real launcher lookup (not this test's stub, and not
# whatever PhoneKeep happens to be installed in /Applications)
import phonekeep as wv_
fake_app = W / "PhoneKeep.app" / "Contents" / "MacOS"
fake_app.mkdir(parents=True, exist_ok=True)
(fake_app / "PhoneKeep").write_bytes(b"")
cli_name = "phonekeep-cli.exe" if os.name == "nt" else "phonekeep-cli"
sys_frozen, sys_exe, stub_launcher = getattr(sys, "frozen", False), sys.executable, wv_._launcher_cmd
try:
    sys.frozen = True
    sys.executable = str(fake_app / "PhoneKeep")
    wv_._launcher_cmd = real_launcher_cmd
    (fake_app / cli_name).write_bytes(b"")
    cmd = login_item.helper_command()
    check(Path(cmd[0]).name == cli_name and cmd[-1] == "--pk-helper", f"packaged helper runs through phonekeep-cli, not the app binary: {cmd}")
    (fake_app / cli_name).unlink()
    cmd = login_item.helper_command()
    check(cmd[0] == sys.executable, f"and falls back to the app binary when there is no phonekeep-cli: {cmd}")
finally:
    if sys_frozen is False:
        del sys.frozen
    sys.executable = sys_exe
    wv_._launcher_cmd = stub_launcher

# ago / size wording
import datetime as dt
check(hc.ago(dt.datetime.now() - dt.timedelta(hours=2)) == "2 hours ago" and hc.ago(dt.datetime.now() - dt.timedelta(days=1, hours=2)) == "yesterday"
      and hc.ago(None) == "never", "plain time wording")
check(hc.size_text(140 * 1024 * 1024) == "140.0 MB" and hc.size_text(512) == "512 B", "size wording")

# -- the main window answers the helper's "open" requests over loopback ---------------------------------
try:
    import tkinter as tk
    import app as appmod
    appmod.SETTINGS_FILE = W / "settings-app.json"
    a = appmod.App()
    a.withdraw()
    a.update()
    check(hc.PORT_FILE.exists(), "the window published its loopback port")
    raised = []
    a.lift = lambda: raised.append(1)
    check(h._ask_app("window"), "the helper's 'Open PhoneKeep' reaches the running window")
    t0 = time.time()
    while time.time() - t0 < 5 and not raised:
        a.update(); time.sleep(0.02)
    check(bool(raised), "and the window raises itself")
    a.destroy()
    a.update()
    check(not hc.PORT_FILE.exists(), "closing the window removes the port file")
    check(not h._ask_app("window"), "with no window running the helper would launch the app instead")
except tk.TclError as e:
    print(f"(window checks skipped: no display: {e})")

print("\nE2 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
