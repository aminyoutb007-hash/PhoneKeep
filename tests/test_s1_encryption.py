"""S1: encrypted backups by default, password in the keychain (docs/spec/04-security.md).

Automated parts of its "Done when":
  - the password never appears on a command line, in logs or in the settings/activity files;
  - the keychain stores one password per phone and gives it back silently;
  - writing to the phone only happens through phone_write, only when confirmed, and is logged;
  - a backup is opened with the stored password without asking;
  - the password dialog: strength hint, show/hide, cancel, and the "Turn on encryption" button
    being the confirmation.
The phone itself is a stub: a fake launcher that records what it was asked and what came on stdin.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

W = HERE / "work" / "s1"
W.mkdir(parents=True, exist_ok=True)

import phonekeep as wv
import keychain
import phone_write

keychain.use_memory()
phone_write.ACTIVITY_FILE = W / "activity.jsonl"
phone_write.ACTIVITY_FILE.unlink(missing_ok=True)

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


SECRET = "Correct-Horse-7!"
UDID = "00008030-S1TEST"

# -- keychain ----------------------------------------------------------------------------------
check(keychain.get_password(UDID) is None, "no password stored to begin with")
check(keychain.set_password(UDID, SECRET), "password stored")
check(keychain.get_password(UDID) == SECRET, "password read back silently")
check(keychain.get_password("other-phone") is None, "one entry per phone")
keychain.delete_password(UDID)
check(keychain.get_password(UDID) is None, "password deleted")

# -- strength hint -----------------------------------------------------------------------------
check(keychain.strength("")[1] == "", "empty: no hint")
check(keychain.strength("abc")[0] == 0, "short password: too short")
check(keychain.strength("abcdefgh")[0] == 1, "8 lowercase letters: weak")
check(keychain.strength(SECRET)[0] == 4, "long mixed password: strong")

# -- a stub phone: fake launcher recording argv and stdin --------------------------------------
stub = W / "stub_launcher.py"
stub.write_text('''
import sys, json
from pathlib import Path
rec = Path(sys.argv[0]).with_name("calls.jsonl")
args = sys.argv[1:]
stdin = sys.stdin.read() if args and args[0] in ("--pk-encryption", "--pk-change-password") else ""
with open(rec, "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": args, "stdin": stdin}) + "\\n")
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT " + ("1" if Path(sys.argv[0]).with_name("encrypted.flag").exists() else "0"))
elif args[0] == "--pk-change-password":
    print("PKDONE")
''')
calls = W / "calls.jsonl"
calls.unlink(missing_ok=True)
flag = W / "encrypted.flag"
flag.unlink(missing_ok=True)
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
logs = []
log = logs.append

# will-encrypt is read without any password involved
check(wv.backup_will_encrypt(UDID) is False, "stub phone reports encryption off")
flag.write_text("1")
check(wv.backup_will_encrypt(UDID) is True, "stub phone reports encryption on")
flag.unlink()

# -- phone_write: refuses unconfirmed, runs confirmed, logs once ---------------------------------
try:
    phone_write.turn_on_encryption(UDID, "Test iPhone", SECRET, confirmed=False, log=log)
    check(False, "unconfirmed write refused")
except phone_write.NotConfirmed:
    check(True, "unconfirmed write refused")
def writes():
    return [json.loads(l) for l in calls.read_text(encoding="utf-8").splitlines()
            if "--pk-will-encrypt" not in l] if calls.exists() else []


check(not writes(), "nothing was sent to the phone when not confirmed")

phone_write.turn_on_encryption(UDID, "Test iPhone", SECRET, confirmed=True, log=log)
phone_write.change_password(UDID, "Test iPhone", SECRET, "New-Pass-99!", confirmed=True, log=log)
phone_write.turn_off_encryption(UDID, "Test iPhone", "New-Pass-99!", confirmed=True, log=log)
recorded = writes()
check(len(recorded) == 3, f"three writes reached the stub phone ({len(recorded)})")
check(all(SECRET not in " ".join(r["argv"]) and "New-Pass-99!" not in " ".join(r["argv"]) for r in recorded),
      "no password on any command line")
check(recorded[0]["stdin"].strip() == SECRET, "the password travelled through stdin")
check(recorded[1]["stdin"].splitlines() == [SECRET, "New-Pass-99!"], "old and new password through stdin")
check(all(SECRET not in m and "New-Pass-99!" not in m for m in logs), "no password in the log lines")

acts = [json.loads(l) for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()]
check([a["summary"] for a in acts] == ["Turned on backup encryption", "Changed the backup password",
                                        "Turned off backup encryption"], "activity log has one line per write")
check(all(SECRET not in l and "New-Pass-99!" not in l for l in phone_write.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()),
      "no password in the activity log")
check(all(a["phone"] == "Test iPhone" and a["when"] for a in acts), "activity lines carry the phone and the time")

# -- opening a backup uses the stored password without asking ---------------------------------
backup = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (backup / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
keychain.set_password(backup.name, SECRET)
check(wv.password_for_backup(backup) == SECRET, "password_for_backup finds the phone's entry by folder name")
check(wv.password_for_backup(backup.with_name("00008030-UNKNOWN")) is None, "unknown phone: no password")


class A:  # CLI argument stand-in
    password = None


os.environ.pop("PHONEKEEP_PASSWORD", None)
check(wv._password_for(backup, A()) is None, "unencrypted backup: the CLI asks nothing")

# -- the CLI has no --password option --------------------------------------------------------------
r = subprocess.run([sys.executable, str(HERE.parent / "phonekeep.py"), "export", "--help"], capture_output=True, text=True)
check("--password" not in r.stdout, "export --help shows no --password option")
r = subprocess.run([sys.executable, str(HERE.parent / "phonekeep.py"), "encryption", "--help"], capture_output=True, text=True)
check("change-password" in r.stdout, "encryption command offers change-password")

# -- settings file never holds the password -----------------------------------------------------
import app as appmod
with tempfile.TemporaryDirectory() as td:
    appmod.SETTINGS_FILE = Path(td) / "settings.json"
    st = appmod.Settings()
    st["backup_dir"] = str(backup.parent)
    check(SECRET not in appmod.SETTINGS_FILE.read_text(encoding="utf-8"), "settings file holds no password")

# -- the password dialog ---------------------------------------------------------------------
try:
    import tkinter as tk
    import ui
    root = tk.Tk()
    root.withdraw()

    d = ui.PasswordDialog(root, "choose", "Test iPhone", True)
    d.withdraw()
    root.update()
    check(d.ok_btn.text == "Turn on encryption", "choose: main button is the confirmation 'Turn on encryption'")
    d.vars[0].set("abc")
    root.update()
    check("Too short" in d.hint.cget("text"), "strength hint says Too short")
    d._ok()
    root.update()
    check(d.result is None and d.winfo_exists(), "too-short password is not accepted")
    d.vars[0].set(SECRET)
    root.update()
    check("Strong" in d.hint.cget("text"), "strength hint says Strong")
    ent = d.entry_first
    eye = [w for w in ent.master.winfo_children() if isinstance(w, tk.Label)][0]
    d._toggle(ent, eye)
    check(ent.cget("show") == "" and eye.cget("text") == "Hide", "Show reveals the password")
    d._ok()
    root.update()
    check(d.result == SECRET, "dialog returns the chosen password")

    d = ui.PasswordDialog(root, "enter", "Test iPhone", True, wv.RESET_PASSWORD_HELP)
    d.withdraw()
    root.update()
    d._cancel()
    root.update()
    check(d.result is None, "cancel returns nothing")

    d = ui.PasswordDialog(root, "change", "Test iPhone", True)
    d.withdraw()
    root.update()
    d.vars[0].set("old-one"); d.vars[1].set(SECRET)
    d._ok()
    root.update()
    check(d.result == ("old-one", SECRET), "change dialog returns old and new")
    root.destroy()
except tk.TclError as e:
    print(f"(dialog checks skipped: no display: {e})")

print("\nS1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
