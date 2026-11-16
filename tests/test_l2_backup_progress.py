"""L2 (5.2): the backup progress screen in the Direction A layout (docs/spec/14-layouts.md#l2-backup-progress-screen).

A stand-in backup (a stub helper that prints the same lines the real one does; nothing talks to a phone) is started
from the main window's Back up now. Checks:
- the progress card takes the window's place: the phone's name, a big percentage, the bar, the time left;
- "Look at your iPhone" shows in the card while the stand-in phone waits for its passcode, and goes once copying starts;
- the steps follow what the backup reports: Get the iPhone ready, then Copy from the iPhone, then Save it as a snapshot;
- Cancel stops the backup, and the window comes back as it was, saying the backup was cancelled.
"""
import json, os, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
os.environ["PK_STUB_PASSCODE"] = "1"

import keychain
import phonekeep as wv

keychain.use_memory()
import applock

applock.use_backend(lambda: None, lambda reason: False)
W = HERE / "work" / "l2progress"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


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
    d = Path(args[1]) / "00008030-L2TEST"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Info.plist").write_bytes(b"x" * 1000)
    print("PKSTAGE started", flush=True)
    print("PKPASSCODE shown", flush=True)
    print("PKPCT 0.0", flush=True)
    time.sleep(2.5)
    print("PKPASSCODE done", flush=True)
    for p in range(10, 900):
        print(f"PKPCT {p/10:.1f}", flush=True); time.sleep(0.1)
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
wv.phone_used_bytes = lambda udid: 1_000_000
UD = "00008030-L2TEST"
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


def pump(until, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout and not until():
        a.update()
        time.sleep(0.02)
    if not until():
        print(f"     (timed out waiting for {what})", flush=True)
    return until()


pump(lambda: a.udid == UD, 10, "the stand-in phone")
check(a.udid == UD, "the main window sees the stand-in phone")
before = [w for w in a.body.winfo_children() if w.winfo_manager()]
check(not a.prog.winfo_manager(), "no progress card before the backup")

a.backup_and_export()
pump(lambda: a.prog.winfo_manager() and a.attn.winfo_manager(), 20, "the passcode notice")
up = [w for w in a.body.winfo_children() if w.winfo_manager()]
check(up == [a.prog], "while it runs, the progress card takes the window's place")
check(a.prog_kicker.cget("text") == "Backing up" and a.prog_name.cget("text") == "Test iPhone"
      and "iOS 26.5" in a.prog_line.cget("text"), "  it says Backing up, the phone's name, iOS and connection")
check(a.attn.winfo_manager() == "pack" and "passcode" in a.attn_text.cget("text"),
      f"\"Look at your iPhone\" shows in the card while the phone waits for its passcode ({a.attn_text.cget('text')!r})")
check(a.steps["ready"].state == "active" and a.steps["copy"].state == "pending", "  step: Get the iPhone ready")
check(not a.bar_frame.winfo_manager(), "  in the card, not as a banner at the top")

pump(lambda: a.steps["copy"].state == "active" and not a.attn.winfo_manager() and a.pct_lbl.cget("text"), 20, "copying")
check(not a.attn.winfo_manager(), "the notice goes once copying starts")
check(a.steps["ready"].state == "done" and a.steps["copy"].state == "active",
      "  step: Copy from the iPhone (Get the iPhone ready ticked)")
pump(lambda: a.pct_lbl.cget("text") not in ("", "0%", "1%"), 20, "the percentage")
pct = a.pct_lbl.cget("text")
check(pct.endswith("%") and 1 < float(pct[:-1]) < 100 and abs(a.bar.value - float(pct[:-1])) < 1.5,
      f"  the big percentage and the bar follow the backup ({pct}, bar {a.bar.value:.0f})")
check(a.eta_lbl.cget("text") != "", f"  the time left (or that it's being worked out): {a.eta_lbl.cget('text')!r}")
check(bool(a.cancel_btn.winfo_manager()) and a.cancel_btn.text == "Cancel backup" and a.cancel_btn.master.master.master is not a.body,
      "  Cancel backup is in the card")

a.cancel_btn.command()
pump(lambda: not a.busy, 30, "the backup to stop")
check(not a.busy and not wv.backup_running(), "Cancel stops the backup")
after = [w for w in a.body.winfo_children() if w.winfo_manager()]
check(after == before, "the window comes back as it was")
check(a.bar_frame.winfo_manager() and a.bar_text.cget("text").startswith("Backup cancelled."),
      f"  saying the backup was cancelled ({a.bar_text.cget('text')[:40]!r})")

# the last phase and building the archive, from what the backup reports (straight to the window's handlers)
a._reset_progress(appmod.STEPS, "Backing up")
a._backup_status("12 MB copied from the iPhone")
s1 = (a.steps["ready"].state, a.steps["copy"].state)
a._backup_status("Saving this backup as a snapshot…")
s2 = (a.steps["copy"].state, a.steps["snapshot"].state)
check(s1 == ("done", "active") and s2 == ("done", "active") and "snapshot" in a.now_lbl.cget("text"),
      f"steps: \"copied\" means copying, then Save it as a snapshot ({s1}, {s2})")
a.steps["choose"].set("active")            # as _export does first
a._progress_build(40)                     # posted to the window's queue, like every update from a worker
pump(lambda: a.pct_lbl.cget("text") == "40%", 10, "the archive's percentage")
check(a.steps["choose"].state == "done" and a.steps["build"].state == "active" and a.pct_lbl.cget("text") == "40%", "building the archive shows its own percentage")
a._end_progress()
check([w for w in a.body.winfo_children() if w.winfo_manager()] == before, "and the window comes back after")

a.destroy()
print("\nL2 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)
os._exit(1 if failures else 0)
