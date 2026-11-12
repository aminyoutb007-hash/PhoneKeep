"""E1: first-run guide (docs/spec/05-ease-of-use.md), driven end to end with a stub iPhone.

Done when (automated part): "A fresh install reaches Back up now in 3 clicks plus the password."
Here the guide is walked exactly as a new owner would: no phone (the three fixes appear after the
wait), phone plugged in but not trusted (step 2 appears by itself), trusted (step 3 appears by itself),
password typed + "Turn on encryption" (click 1, written to the phone through phone_write), "Back up now"
(click 2), done screen with its questions, "Open iPhone". Clicks are counted. The usability-test point
is checked on real people by the owner.
"""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phone_write
import phonekeep as wv

keychain.use_memory()
W = HERE / "work" / "e1"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
phone_write.ACTIVITY_FILE = W / "activity.jsonl"
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- stub phone -------------------------------------------------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
stub = W / "stub_launcher.py"
stub.write_text(f'''
import json, shutil, sys
from pathlib import Path
here = Path(sys.argv[0]).parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({{"argv": args, "stdin": sys.stdin.read() if args[0] in ("--pk-encryption", "--pk-change-password") else ""}}) + "\\n")
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT " + ("1" if (here / "encrypted.flag").exists() else "0"))
elif args[0] == "--pk-encryption":
    (here / "encrypted.flag").write_text("1")
elif args[0] in ("--pk-wifi",):
    print("PKDONE")
elif args[0] == "--pk-backup":
    target = Path(args[1]) / "00008030-E1TEST"
    if not (target / "Manifest.db").exists():
        shutil.copytree(r"{fake}", target)
    for p in (25, 50, 75, 100):
        print(f"PKPCT {{p}}", flush=True)
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
PHONE = {"DeviceName": "Amin's iPhone", "UniqueDeviceID": "00008030-E1TEST", "ConnectionType": "USB", "ProductVersion": "26.1"}
state = {"mode": "none"}   # none | untrusted | trusted


def list_devices():
    if state["mode"] == "none":
        return []
    if state["mode"] == "untrusted":
        raise wv.PhoneKeepError.from_problem("NotPairedError: pairing dialog response pending, tap Trust")
    return [PHONE]


wv.list_devices = list_devices

# -- the app on a fresh install ----------------------------------------------------------------
import tkinter as tk
import app as appmod
import firstrun

firstrun.NO_PHONE_SECONDS = 2
appmod.SETTINGS_FILE = W / "settings.json"
a = appmod.App()
a.withdraw()
a.s["backup_dir"] = str(W / "Backups")
a.s["archive_dir"] = str(W / "Archive")
clicks = []


def pump(until, timeout=30, what=""):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    print(f"timed out waiting for {what}", flush=True)
    return False


def labels():
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                out.append(c.cget("text"))
            walk(c)
    walk(a.guide.inner)
    return out


check(a.guide is not None and a.guide.step == 0, "fresh install: the guide is up, step 1 'Connect your iPhone'")
check(not any(w.winfo_manager() for w in a.main_cards), "the normal cards are hidden while the guide runs")
check(a.guide.skip.cget("text") == "Skip" and isinstance(a.guide.skip, tk.Label), "Skip exists but is a plain link, not a highlighted button")

# no phone: three fixes after the wait
a.detect(silent=True)
check(pump(lambda: any("Three things" in t for t in labels()), 15, "the three fixes"), "no phone after the wait: three likely fixes shown")
fixes = next((t for t in labels() if "1." in t), "")
check("cable" in fixes and "Unlock" in fixes and ("Apple Devices" in fixes or "Trust" in fixes), f"fixes are the three from the spec: {fixes!r}")

# phone plugged in but not trusted: step 2 appears by itself
state["mode"] = "untrusted"
a.detect(silent=True)
check(pump(lambda: a.guide.step == 1, 10, "step 2"), "untrusted phone: 'Tap Trust' step appears by itself")

# trusted: step 3 appears by itself, in 'choose' form because the stub phone isn't encrypted yet
state["mode"] = "trusted"
a.detect(silent=True)
check(pump(lambda: a.guide.step == 2 and a.guide.pw_btn.enabled, 15, "step 3"), "trusted: 'Choose a backup password' step appears by itself")
check(a.guide.pw_btn.text == "Turn on encryption", "the main button is 'Turn on encryption' (the confirmation)")
a.guide.pw_var.set("Correct-Horse-7!")
a.update()
check("Strong" in a.guide.hint.cget("text"), "strength hint shown")
clicks.append("Turn on encryption"); a.guide.do_password()
check(pump(lambda: a.guide.step == 3, 20, "step 4"), "after the click, the backup step appears")
calls = [json.loads(l) for l in (W / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
enc = [c for c in calls if c["argv"][0] == "--pk-encryption"]
check(len(enc) == 1 and enc[0]["argv"][1] == "on" and enc[0]["stdin"].strip() == "Correct-Horse-7!"
      and "Correct-Horse-7!" not in " ".join(enc[0]["argv"]), "encryption turned on through the phone (password on stdin only)")
check(keychain.get_password("00008030-E1TEST") == "Correct-Horse-7!", "password in the keychain")
acts = [json.loads(l) for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()]
check(acts and acts[0]["summary"] == "Turned on backup encryption", "activity log has the write")

# back up now
check(any("close this window" in t for t in labels()), "step 4 says the window can be closed")
clicks.append("Back up now"); a.guide.do_backup()
check(pump(lambda: a.guide.step == 4, 60, "done step"), "backup runs and the done step appears")
import snapshots as _sn
check(_sn.has_backup(W / "Backups", "00008030-E1TEST"), "a backup exists (as a snapshot)")
check(any("safely backed up" in t for t in labels()), "done screen says 'Your iPhone is safely backed up'")
asks_daily = any("automatically every day" in t for t in labels())
check(asks_daily == appmod.App.FEATURES["scheduler"] and any("over Wi-Fi" in t for t in labels()),
      f"done screen asks about Wi-Fi, and about daily backups only when the scheduler exists ({asks_daily})")
check(len(clicks) == 2, f"reached Back up now in {len(clicks)} clicks plus the password (target: 3 + password)")

# the questions
check(("auto_daily" in a.guide.choices) == appmod.App.FEATURES["scheduler"] and "app_lock" not in a.guide.choices,
      "questions for features not in this build are hidden")
if "auto_daily" in a.guide.choices:
    a.guide.answer("auto_daily", True, a.guide.choices["auto_daily"])
    check(a.s["auto_backup"] == "daily", "'Yes' to daily backups is remembered for the scheduler")
from tkinter import messagebox as mb
mb.askokcancel = lambda *x, **k: True
a.guide.answer("wifi", True, a.guide.choices["wifi"])
check(pump(lambda: a.guide.choices["wifi"].cget("text") == "Yes", 20, "wifi"), "Wi-Fi backups turned on through phone_write after a named confirmation")
calls = [json.loads(l) for l in (W / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
check(any(c["argv"][:2] == ["--pk-wifi", "on"] for c in calls), "the phone was asked to enable Wi-Fi sync")
acts = [json.loads(l) for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()]
check(any(x["summary"] == "Turned on Wi-Fi backups" for x in acts), "Wi-Fi write in the activity log")

# open iPhone ends the guide and restores the window
opened = []
a.open_phone = lambda: opened.append(1)
a.guide.do_open()
a.update()
check(opened and a.guide is None, "Open iPhone ends the guide and opens the phone window")
check(all(w.winfo_manager() for w in a.main_cards[:2]), "the normal cards are back")
check(a.s["first_run_done"] and json.loads(appmod.SETTINGS_FILE.read_text(encoding="utf-8"))["first_run_done"], "first run recorded")
a.destroy()

# second launch: no guide
b = appmod.App()
b.withdraw()
check(b.guide is None, "second launch: the guide doesn't show again")
b.destroy()

# the already-encrypted path: the step asks for the existing password instead
keychain.delete_password("00008030-E1TEST")
appmod.SETTINGS_FILE = W / "settings2.json"
shutil.rmtree(W / "Backups", ignore_errors=True)
c = appmod.App()
c.withdraw()
c.s["backup_dir"] = str(W / "Backups")
check(c.guide is not None, "fresh settings: guide again")
state["mode"] = "trusted"
c.detect(silent=True)
a = c
check(pump(lambda: c.guide.step == 2 and c.guide.pw_btn.enabled, 15, "enter step"), "phone already encrypted: step 3 appears")
check(c.guide.pw_btn.text == "Continue" and any("already encrypts" in t for t in labels()),
      "already encrypted: 'Enter your backup password' with Continue, and the 'I don't know the password' help")
c.end_first_run()
c.update()
c.destroy()

print("\nE1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
