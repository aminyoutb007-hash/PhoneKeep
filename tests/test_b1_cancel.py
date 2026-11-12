"""B1 (keep it working): a running backup can be cancelled (docs/spec/00-user-experience.md, Progress:
"+ Cancel"; 01-principles.md, 6: "a cancel button is always available for long jobs").

Found missing on a real Mac (12 Nov): a backup to a slow drive could only be stopped by quitting.
A stub helper that copies slowly is cancelled from the engine, then from the main window's button
and from the first-run guide's; the result is a quiet "cancelled" state, not a red failure, no failed
day is recorded by the helper, and the next backup carries on.
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phonekeep as wv

keychain.use_memory()
W = HERE / "work" / "b1cancel"
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


# a helper that takes a long time: writes a little, then waits (never finishes on its own)
stub = W / "stub_launcher.py"
stub.write_text('''
import sys, time
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 1")
elif args[0] == "--pk-backup":
    d = Path(args[1]) / "00008030-CANCEL"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Info.plist").write_bytes(b"x" * 1000)
    print("PKSTAGE started", flush=True)
    for p in range(1, 400):
        print(f"PKPCT {p/10:.1f}", flush=True); time.sleep(0.25)
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
wv.phone_used_bytes = lambda udid: 1_000_000
UD = "00008030-CANCEL"
keychain.set_password(UD, "test-password")      # the window's pre-backup check finds the password
wv.list_devices = lambda: [{"DeviceName": "Amin's iPhone", "UniqueDeviceID": UD, "ConnectionType": "USB"}]
root = W / "Backups"

# -- the engine ----------------------------------------------------------------------------------------
import threading
out = {}


def run():
    try:
        out["r"] = wv.make_backup(root, UD, log=lambda m: None, progress=lambda p: None)
    except Exception as e:
        out["e"] = e


t = threading.Thread(target=run); t.start()
t0 = time.time()
while not wv.backup_running() and time.time() - t0 < 20:
    time.sleep(0.05)
check(wv.backup_running(), "a backup is running")
time.sleep(1)
check(wv.cancel_backup(), "cancel_backup() stops it")
t.join(30)
check(not t.is_alive() and isinstance(out.get("e"), wv.BackupCancelled), f"make_backup ends with BackupCancelled: {out}")
e = out["e"]
check(e.key == "cancelled" and e.button == "Back up now" and str(e).startswith("Backup cancelled."), f"wording: {e} / {e.button}")
check(not wv.backup_running() and not wv.cancel_backup(), "nothing left running; a second cancel is a no-op")
check(wv.backup_incomplete(root / UD / "current" / UD) or not (root / UD / "current" / UD / "Manifest.db").exists(),
      "the half backup is left as 'didn't finish' (the next backup completes it)")

# one backup of a phone at a time, across processes: a live marker from another process refuses plainly
marker = root / UD / "backup.lock"
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
marker.write_text(str(other.pid), encoding="utf-8")
try:
    wv.make_backup(root, UD, log=lambda m: None)
    check(False, "a second backup while another process backs up is refused")
except wv.PhoneKeepError as e2:
    check(e2.key == "busy" and str(e2).startswith("A backup of this iPhone is already running"), f"refused plainly: {e2}")
other.kill(); other.wait()
check(wv._marker_owner(marker) is None, "a marker from a dead process is ignored")
marker.unlink()

# the helper (E2/B2) treats a cancel like waiting, not a failed day
import helper_core as hc
hc.LOCK_FILE, hc.PORT_FILE, hc.SETTINGS_FILE = W / "helper.lock", W / "app.port", W / "settings.json"
notes = []
h = hc.Helper(notify=lambda t_, m: notes.append((t_, m)), backup_dir=root, on_change=lambda: None)
h.refresh_devices(force=True)
h.back_up_now()
t0 = time.time()
while not wv.backup_running() and time.time() - t0 < 20:
    time.sleep(0.05)
time.sleep(0.5)
wv.cancel_backup()
t0 = time.time()
while h.busy and time.time() - t0 < 30:
    time.sleep(0.05)
import json
health = json.loads((root / UD / "health.json").read_text(encoding="utf-8")) if (root / UD / "health.json").exists() else {}
check(not notes and not health.get("failed_days"), f"helper: no 'didn't finish' notification, no failed day: {notes} {health}")

# -- the windows -----------------------------------------------------------------------------------------
try:
    import tkinter as tk
    import app as appmod
    appmod.SETTINGS_FILE = W / "settings-app.json"
    appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(root)}), encoding="utf-8")
    a = appmod.App()
    a.withdraw()
    a.s["backup_dir"] = str(root)
    a.update()
    a.detect(silent=True)
    t0 = time.time()
    while time.time() - t0 < 10 and not a.udid:
        a.update(); time.sleep(0.02)
    check(a.udid == UD, f"main window sees the stub phone: {a.udid}")
    check(not a.cancel_btn.winfo_manager(), "no Cancel button while idle")
    a.backup_and_export()
    t0 = time.time()
    while time.time() - t0 < 20 and not a.cancel_btn.winfo_manager():
        a.update(); time.sleep(0.02)
    check(bool(a.cancel_btn.winfo_manager()) and a.cancel_btn.text == "Cancel backup", "Cancel backup appears under the button while it runs")
    a.cancel_backup()
    a.update()
    check(a.cancel_btn.text == "Cancelling…", "the button says Cancelling…")
    t0 = time.time()
    while time.time() - t0 < 30 and a.busy:
        a.update(); time.sleep(0.02)
    a.update()
    check(not a.busy and not a.cancel_btn.winfo_manager(), "the job ends and the Cancel button goes away")
    check(a.bar_frame.winfo_manager() == "pack" and a.bar_text.cget("text").startswith("Backup cancelled.")
          and a.bar_frame.cget("bg") != "#fdecea", f"amber (not red) banner: {a.bar_text.cget('text')!r}")
    a.destroy()

    # the first-run guide's backup step
    import firstrun
    appmod.SETTINGS_FILE = W / "settings-guide.json"
    a = appmod.App()
    a.withdraw()
    a.s["backup_dir"] = str(root)
    a.detect(silent=True)
    t0 = time.time()
    while time.time() - t0 < 10 and not a.udid:
        a.update(); time.sleep(0.02)
    g = firstrun.FirstRunGuide(a)
    g.show_step(3)
    a.update()
    check(not g.cancel_btn.winfo_manager(), "guide: no Cancel before the backup starts")
    g.do_backup()
    a.update()
    check(bool(g.cancel_btn.winfo_manager()), "guide: Cancel next to Back up now while it runs")
    t0 = time.time()
    while time.time() - t0 < 20 and not wv.backup_running():
        a.update(); time.sleep(0.02)
    g.cancel_backup()
    t0 = time.time()
    while time.time() - t0 < 30 and a.busy:
        a.update(); time.sleep(0.02)
    a.update()
    check(not g.cancel_btn.winfo_manager() and g.backup_btn.enabled, "guide: after cancelling, Back up now is offered again")
    check(not g.backup_done, "guide: the step is not marked done")
    g.destroy(); a.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

print("\nB1 CANCEL TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
