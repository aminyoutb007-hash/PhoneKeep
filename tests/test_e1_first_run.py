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
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phone_write
import phonekeep as wv

keychain.use_memory()

import applock

applock.use_backend(lambda: None, lambda reason: False)   # no Touch ID prompts in tests (S2 has its own)
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
    if (here / "wififail.flag").exists():
        print("Could not connect to the device")
        sys.exit(1)
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
# a fresh install's settings, pointing at the test's own empty folders from the start (never this computer's
# real backup folder: on a Mac with backups, the guide would rightly not appear)
import json
appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups"), "archive_dir": str(W / "Archive")}), encoding="utf-8")
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
check(a.guide.skip.cget("text") == "Skip for now" and isinstance(a.guide.skip, tk.Label), "Skip for now exists but is a plain link, not a highlighted button")
# E1 refresh (5.2): the four steps on the left, the current one marked, "Step 1 of 4" on the right
check([r[3].cget("text") for r in a.guide.rows] == ["Connect your iPhone", "Tap Trust", "Choose a backup password", "Back up now"]
      and a.guide.rows[0][0].cget("bg") == appmod.theme.ACCENT_PALE and a.guide.kicker.cget("text") == "Step 1 of 4",
      "the four steps on the left, the current one marked; 'Step 1 of 4'")

# no phone: three fixes after the wait
a.detect(silent=True)
check(pump(lambda: any("Three things" in t for t in labels()), 15, "the three fixes"), "no phone after the wait: three likely fixes shown")
fixes = next((t for t in labels() if "1." in t), "")
check("cable" in fixes and "Unlock" in fixes and ("Apple Devices" in fixes or "Trust" in fixes), f"fixes are the three from the spec: {fixes!r}")

# phone plugged in but not trusted: step 2 appears by itself
state["mode"] = "untrusted"
a.detect(silent=True)
check(pump(lambda: a.guide.step == 1, 10, "step 2"), "untrusted phone: 'Tap Trust' step appears by itself")

# trusted: the Trust step says so and offers Wi-Fi, switched off; nothing is written to the phone
state["mode"] = "trusted"
a.detect(silent=True)
check(pump(lambda: a.guide.step == 1 and a.guide.trusted and a.guide.continue_btn.enabled, 15, "trusted"),
      "trusted: the Trust step says so, with Continue")


def wifi_calls():
    if not (W / "calls.jsonl").exists():
        return []
    return [c for c in (json.loads(l) for l in (W / "calls.jsonl").read_text(encoding="utf-8").splitlines())
            if c["argv"][0] == "--pk-wifi"]


check(a.guide.wifi_box.winfo_manager() and a.guide.wifi_var.get() is False and not wifi_calls(),
      "  'Use this iPhone over Wi-Fi' is offered, off by default, and nothing is written")
check(any("never looks for other phones" in t for t in labels()), "  it explains that only phones paired by cable show up over Wi-Fi")
from tkinter import messagebox as mb
asked = []
mb.askokcancel = lambda title, *x, **k: (asked.append(title), False)[1]          # Cancel
a.guide.wifi_var.set(True); a.guide.wifi_switched()
a.update()
check(asked == [f"Turn on Wi-Fi backups for {a.device['DeviceName']}?"] and a.guide.wifi_var.get() is False and not wifi_calls(),
      f"  switching it on asks first, by the phone's name; Cancel turns it back off and writes nothing ({asked})")
a.guide.wifi_var.set(False); a.guide.wifi_switched()
check(not wifi_calls() and len(asked) == 1, "  switching it off writes nothing and asks nothing")
# reviewer, #75: the write only ever goes to the phone that's connected and trusted, and still is after OK
real_udid = a.udid
a.udid = None                                   # unplugged, the box not yet gone
a.guide.wifi_var.set(True); a.guide.wifi_switched()
check(len(asked) == 1 and a.guide.wifi_var.get() is False and not wifi_calls(),
      "  with no phone connected, switching on asks nothing and writes nothing")
a.udid = real_udid
a.guide.trusted = False                         # connected but not trusted (yet, or any more)
a.guide.wifi_var.set(True); a.guide.wifi_switched()
check(len(asked) == 1 and a.guide.wifi_var.get() is False and not wifi_calls(),
      "  with the phone connected but not trusted, switching on asks nothing and writes nothing")
a.guide.trusted = True
mb.askokcancel = lambda title, *x, **k: (asked.append(title), setattr(a.guide, "trusted", False), True)[2]
a.guide.wifi_var.set(True); a.guide.wifi_switched()
check(len(asked) == 2 and a.guide.wifi_var.get() is False and not wifi_calls(),
      "  if the phone stops trusting while asking, OK writes nothing")
a.guide.trusted = True
asked.pop()
mb.askokcancel = lambda title, *x, **k: (asked.append(title), setattr(a, "udid", "00008030-OTHER"), True)[2]
a.guide.wifi_var.set(True); a.guide.wifi_switched()
a.update()
check(len(asked) == 2 and a.guide.wifi_var.get() is False and not wifi_calls() and "changed" in a.guide.wifi_note.cget("text"),
      "  if the phone changes while asking, OK writes nothing")
a.udid = real_udid
# a failing write: shown next to the switch, not as the banner (whose Try again would repeat it without the OK)
(W / "wififail.flag").write_text("1")
mb.askokcancel = lambda title, *x, **k: (asked.append(title), True)[1]
a.guide.wifi_var.set(True); a.guide.wifi_switched()
check(not a.guide.continue_btn.enabled, "  while the Wi-Fi write runs, Continue waits")
a.guide._show_trusted(True)                    # a replug mid-write
check(not a.guide.continue_btn.enabled, "  even if the phone is seen again mid-write")
pump(lambda: a.guide.wifi_note.cget("text").startswith("Not done"), 20, "the failed write")
acts_now = [json.loads(l) for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()] \
    if phone_write.ACTIVITY_FILE.exists() else []
check(a.guide.wifi_note.cget("text").startswith("Not done") and a.guide.wifi_var.get() is False
      and not a.bar_frame.winfo_manager() and len(wifi_calls()) == 1
      and not any(x["summary"] == "Turned on Wi-Fi backups" for x in acts_now) and a.guide.continue_btn.enabled,
      f"  a failed write: 'Not done' by the switch, switch off, no banner, one attempt, nothing logged as done, Continue back ({a.guide.wifi_note.cget('text')!r})")
(W / "wififail.flag").unlink()
fails = len(wifi_calls())
asked.clear(); asked.append("x")
mb.askokcancel = lambda title, *x, **k: (asked.append(title), True)[1]           # OK
a.guide.wifi_var.set(True); a.guide.wifi_switched()
check(pump(lambda: "are on" in a.guide.wifi_note.cget("text"), 20, "wifi"), "  OK: Wi-Fi backups turned on")
check(len(wifi_calls()) == fails + 1 and wifi_calls()[-1]["argv"][:2] == ["--pk-wifi", "on"],
      f"  exactly one write to the phone ({len(wifi_calls()) - fails})")
argv = wifi_calls()[-1]["argv"]
check("--udid" in argv and argv[argv.index("--udid") + 1] == real_udid, f"  to this phone, by its ID ({argv})")
acts = [json.loads(l) for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()]
check(sum(x["summary"] == "Turned on Wi-Fi backups" for x in acts) == 1, "  the write is in the activity log")
check(a.guide.wifi_var.get() is True, "  the switch shows on")
a.udid = "00008030-OTHER"                      # another iPhone in its place: not shown as on, and can be asked
a.guide.show_step(1); a.guide._show_trusted(True)
check(a.guide.wifi_var.get() is False and "are on" not in a.guide.wifi_note.cget("text"),
      "  'on' belongs to the phone it was written for, not to another iPhone plugged in after")
a.udid = real_udid
a.guide.show_step(1); a.guide._show_trusted(True)
check(a.guide.wifi_var.get() is True and "are on" in a.guide.wifi_note.cget("text"), "  and shows on again for that phone")
clicks.append("Continue"); a.guide.start_password_step()
check(pump(lambda: a.guide.step == 2 and a.guide.pw_btn.enabled, 15, "step 3"), "Continue: 'Choose a backup password', step 3 of 4")
check(a.guide.kicker.cget("text") == "Step 3 of 4" and a.guide.rows[1][1].find_all() and a.guide.rows[2][0].cget("bg") == appmod.theme.ACCENT_PALE,
      "  the list marks Trust done and the password step as now")
a.guide.back_btn.command()
a.update()
check(a.guide.step == 1 and a.guide.wifi_var.get() and "are on" in a.guide.wifi_note.cget("text") and len(wifi_calls()) == fails + 1,
      "Back: the Trust step again, Wi-Fi still on, nothing written again")
a.guide.start_password_step()
check(pump(lambda: a.guide.step == 2 and a.guide.pw_btn.enabled, 15, "step 3 again"), "  and Continue again")
check(a.guide.pw_btn.text == "Turn on encryption", "the main button is 'Turn on encryption' (the confirmation)")
a.guide.pw_var.set("Correct-Horse-7!")
a.update()
check("Strong" in a.guide.hint.cget("text") and len(a.guide.meter.find_all()) == 4, "strength shown (word and bar)")
a.guide.pw2_var.set("Correct-Horse-8!")
a.guide.do_password()
check(a.guide.step == 2 and "aren't the same" in a.guide.hint.cget("text"), "two different passwords: asked to type it again, nothing done")
a.guide.pw2_var.set("Correct-Horse-7!")
clicks.append("Turn on encryption"); a.guide.do_password()
check(not a.guide.back_btn.enabled and not a.guide.pw_btn.enabled, "  while the encryption write runs, Back and the button can't be clicked")
check(pump(lambda: a.guide.step == 3, 20, "step 4"), "after the click, the backup step appears")
calls = [json.loads(l) for l in (W / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
enc = [c for c in calls if c["argv"][0] == "--pk-encryption"]
check(len(enc) == 1 and enc[0]["argv"][1] == "on" and enc[0]["stdin"].strip() == "Correct-Horse-7!"
      and "Correct-Horse-7!" not in " ".join(enc[0]["argv"]), "encryption turned on through the phone (password on stdin only)")
check(keychain.get_password("00008030-E1TEST") == "Correct-Horse-7!", "password in the keychain")
acts = [json.loads(l) for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()]
check(sum(x["summary"] == "Turned on backup encryption" for x in acts) == 1, "activity log has the write")

# back up now
check(any("keep PhoneKeep open" in t for t in labels()) and a.guide.kicker.cget("text") == "Step 4 of 4",
      "step 4 of 4 says to keep PhoneKeep open")
clicks.append("Back up now"); a.guide.do_backup()
check(pump(lambda: a.guide.step == 4, 60, "done step"), "backup runs and the done step appears")
import snapshots as _sn
check(_sn.has_backup(W / "Backups", "00008030-E1TEST"), "a backup exists (as a snapshot)")
check(any("safely backed up" in t for t in labels()), "done screen says 'Your iPhone is safely backed up'")
asks_daily = any("automatically every day" in t for t in labels())
check(asks_daily == appmod.App.FEATURES["scheduler"] and not any("Wi-Fi" in t for t in labels()),
      f"done screen asks about daily backups when the scheduler exists ({asks_daily}); Wi-Fi was asked once, at Trust")
check(a.guide.kicker.cget("text") == "All done" and a.guide.skip.cget("text") == "Finish", "  'All done', with Finish")
check(len(clicks) == 3, f"reached Back up now in {len(clicks)} clicks plus the password (target: 3 + password)")

# the questions
check(("auto_daily" in a.guide.choices) == appmod.App.FEATURES["scheduler"] and "app_lock" not in a.guide.choices,
      "questions for features not in this build are hidden")
if "auto_daily" in a.guide.choices:
    a.guide.answer("auto_daily", True, a.guide.choices["auto_daily"])
    check(a.s["auto_backup"] == "daily", "'Yes' to daily backups is remembered for the scheduler")
check("wifi" not in a.guide.choices and len(wifi_calls()) == fails + 1, "no second Wi-Fi question, and still just the one write")

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
appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups"), "archive_dir": str(W / "Archive")}), encoding="utf-8")
c = appmod.App()
c.withdraw()
c.s["backup_dir"] = str(W / "Backups")
check(c.guide is not None, "fresh settings: guide again")
state["mode"] = "trusted"
c.detect(silent=True)
a = c
check(pump(lambda: c.guide.step == 1 and c.guide.trusted, 15, "trusted"), "  Trust step, trusted")
c.guide.start_password_step()
check(pump(lambda: c.guide.step == 2 and c.guide.pw_btn.enabled, 15, "enter step"), "phone already encrypted: step 3 appears")
check(c.guide.pw_btn.text == "Continue" and any("already encrypts" in t for t in labels()),
      "already encrypted: 'Enter your backup password' with Continue, and the 'I don't know the password' help")
c.end_first_run()
c.update()
c.destroy()

print("\nE1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
