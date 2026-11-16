"""B9 (5.3): keep backing up after the window closes (docs/spec/03-backup.md#b9-keep-backing-up-after-the-window-closes).

A stand-in backup (a stub helper that prints the lines the real one does; nothing talks to a phone) runs from the main
window's Back up now. Notifications are recorded instead of shown. Checks:
- the line under the progress card says the window can be closed (only for a backup; an export keeps "Keep PhoneKeep open");
- closing the window while it runs hides it and the backup carries on; closing it with nothing running quits, as before;
- Quit while it runs asks first: Cancel keeps it going, OK stops the backup and quits;
- when the backup needs the user (the passcode) a notification says so and the window comes back;
- a backup that doesn't finish: a notification says why and the window comes back with the problem;
- a backup that finishes: a notification names the phone, then PhoneKeep quits (not while another of its windows is open).
"""
import json, os, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phonekeep as wv

keychain.use_memory()
import applock

applock.use_backend(lambda: None, lambda reason: False)
W = HERE / "work" / "b9close"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []
_exit = os._exit


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


stub = W / "stub_launcher.py"
stub.write_text('''
import os, sys, time
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 1")
elif args[0] == "--pk-backup":
    d = Path(args[1]) / "00008030-B9TEST"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Info.plist").write_bytes(b"x" * 1000)
    print("PKSTAGE started", flush=True)
    for p in range(10, 900):
        print(f"PKPCT {p/10:.1f}", flush=True); time.sleep(0.1)
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
wv.phone_used_bytes = lambda udid: 1_000_000
UD = "00008030-B9TEST"
keychain.set_password(UD, "test-password")
wv.list_devices = lambda: [{"DeviceName": "Test iPhone", "UniqueDeviceID": UD, "ConnectionType": "USB",
                            "ProductVersion": "26.5"}]
root = W / "Backups"

import app as appmod

appmod.SETTINGS_FILE = W / "settings-app.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(root)}), encoding="utf-8")
a = appmod.App()
a.s["backup_dir"] = str(root)
a.update()
a.detect(silent=True)

notes, quits, asked = [], [], []
a.notify = lambda title, text: notes.append((title, text))
a.quit_app = lambda: quits.append(1)       # the real one ends the process; checked on its own at the end
real_quit = lambda: appmod.App.quit_app(a)


def pump(until, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout and not until():
        a.update()
        time.sleep(0.02)
    if not until():
        print(f"     (timed out waiting for {what})", flush=True)
    return until()


def settle(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        a.update()
        time.sleep(0.02)


pump(lambda: a.udid == UD, 10, "the stand-in phone")
check(a.udid == UD, "the main window sees the stand-in phone")

check("close_window" in str(a.protocol("WM_DELETE_WINDOW")), "the window's close button is close_window")

# nothing running: the close button quits, as before
a.close_window()
check(quits == [1] and not a._window_away(), "with nothing running, closing the window quits PhoneKeep, as before")
quits.clear()

# an export's card keeps "Keep PhoneKeep open"; only a backup carries on
a._reset_progress(appmod.EXPORT_STEPS, "Building your archive")
check(a.prog_after.cget("text") == appmod.KEEP_OPEN, f"an export says {appmod.KEEP_OPEN!r}")
a._end_progress()

a.backup_and_export()
pump(lambda: a.steps["copy"].state == "active" and wv.backup_running(), 20, "copying")
check(a.prog_after.cget("text") == appmod.CLOSE_OK, f"a backup says {a.prog_after.cget('text')!r}")
a.close_window()
a.update()
check(a._window_away() and not quits, f"closing the window while it backs up hides it ({a.state()}) and doesn't quit")
settle(1.5)
check(a.busy and wv.backup_running(), "  the backup carries on with the window closed")

# Quit while it runs asks first; Cancel keeps it going
real_ask = appmod.messagebox.askokcancel
appmod.messagebox.askokcancel = lambda *x, **k: (asked.append(x[0]), False)[1]
destroyed = []
real_destroy = a.destroy
a.destroy = lambda: destroyed.append(1)
os._exit = lambda code=0: destroyed.append(("exit", code))
real_quit()
check(asked == ["Stop the backup and quit?"] and not destroyed and wv.backup_running(),
      f"Quit while it backs up asks first ({asked}); Cancel keeps it going")
check(not a._window_away(), "  the window comes back to ask")
os._exit = _exit
a.destroy = real_destroy
a.close_window()
a.update()

# the backup needs the user: a notification says so and the window comes back
notes.clear()
a.passcode_notice("Look at your iPhone: enter its passcode")
a.update()
check(notes == [("Look at your iPhone", "Enter its passcode")] and not a._window_away(),
      f"when it needs the user, a notification says so and the window comes back ({notes})")
a.passcode_notice(None)
a.close_window()
a.update()

# it doesn't finish (stopped here as a stand-in for a lost connection): a notification says why, the window comes back
notes.clear()
wv.cancel_backup()
pump(lambda: not a.busy, 30, "the backup to stop")
settle(1.5)
check(len(notes) == 1 and notes[0][0] == "Backup didn't finish" and notes[0][1],
      f"a backup that doesn't finish: one notification says why ({notes})")
check(not a._window_away() and a.bar_frame.winfo_manager() and not quits,
      "  the window comes back with the problem, and PhoneKeep doesn't quit")

# it finishes: a notification names the phone, then PhoneKeep quits
made = W / "made"
made.mkdir()
a.ensure_encryption = lambda: None
wv.make_backup = lambda *x, **k: (time.sleep(1.5), made)[1]
a._export = lambda path: None


def finished_run(other_window=False):
    notes.clear()
    quits.clear()
    a.backup_and_export()
    pump(lambda: a.prog.winfo_manager(), 10, "the card")
    extra = appmod.tk.Toplevel(a) if other_window else None
    a.close_window()
    pump(lambda: not a.busy, 20, "the stand-in backup to finish")
    settle(1.5)
    if extra is not None:
        extra.destroy()
    return notes[:], quits[:]


n, q = finished_run()
check(n == [("Backup finished", "Test iPhone is backed up.")], f"a backup that finishes: a notification names the phone ({n})")
if sys.platform == "win32":
    check(not q and not a._window_away(), "  Windows: the window comes back instead of quitting (no Windows notification yet)")
else:
    check(q == [1], "  then PhoneKeep quits, as the closed window asked")
a._come_back()
n, q = finished_run(other_window=True)
check(n == [("Backup finished", "Test iPhone is backed up.")] and not q,
      "  with another PhoneKeep window open, it notifies but doesn't quit")
a._come_back()

# the window brought back before the end: nothing extra happens
notes.clear()
quits.clear()
a.backup_and_export()
pump(lambda: a.prog.winfo_manager(), 10, "the card")
a.close_window()
a.update()
a._come_back()
pump(lambda: not a.busy, 20, "the stand-in backup to finish")
settle(1.5)
check(not notes and not quits, "the window brought back before the end: no notification, no quitting")

# Quit while it backs up, answered OK: the backup stops and PhoneKeep quits
appmod.messagebox.askokcancel = lambda *x, **k: True
stopped = []
real_cancel = wv.cancel_backup
wv.cancel_backup = lambda: (stopped.append(1), real_cancel())[1]
a.busy, a._card_for = True, (appmod.STEPS, "Backing up")      # a backup's card, shown by hand: no backup needed here
a.prog.pack(fill="x")
destroyed.clear()
a.destroy = lambda: destroyed.append(1)
os._exit = lambda code=0: destroyed.append(("exit", code))
real_quit()
os._exit = _exit
a.destroy = real_destroy
check(stopped == [1] and destroyed == [1, ("exit", 0)], f"Quit answered OK stops the backup and quits ({stopped}, {destroyed})")
a.busy = False
a.prog.pack_forget()
appmod.messagebox.askokcancel = real_ask

a.destroy()
print("\nB9 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)
_exit(1 if failures else 0)
