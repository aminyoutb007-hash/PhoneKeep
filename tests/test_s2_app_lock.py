"""S2: app lock (docs/spec/04-security.md#s2-app-lock).

Done when:
- "Opening the phone window asks for Touch ID; cancelling keeps it closed."  → with a stand-in for the system
  check (Touch ID can't be pressed in a test), opening the phone window and a backup asks first; cancel opens
  nothing; confirm opens it; a second window in the same session doesn't ask again.
- "After the idle time the content is hidden until unlocked."  → after the idle minutes every phone window is
  covered by one Unlock button; Unlock asks again and uncovers them all.
Also: on by default with Touch ID / Windows Hello, off on a Mac with only a password (the first-run guide offers
it there), not offered without either; the export's chooser asks too; switching the lock off asks first;
scheduled backups don't go through the lock at all.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import applock
import keychain
import phonekeep as wv

keychain.use_memory()
W = HERE / "work" / "s2"
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


# -- the system check, and what it means -----------------------------------------------------------------
if sys.platform.startswith("linux"):
    check(applock.available() is None and applock.authenticate("x") is False,
          "with no Touch ID / Windows Hello (Linux), the lock isn't available and never lets anyone in")
check(applock.default_on("touch_id") and applock.default_on("hello") and not applock.default_on("password")
      and not applock.default_on(None), "on by default with Touch ID or Windows Hello; off with only a password")
check(applock.describe("touch_id") == "Touch ID or your Mac's password" and applock.describe("hello") == "Windows Hello",
      "Settings names what it uses")
src = (HERE.parent / "applock.py").read_text(encoding="utf-8")
check("LAPolicyDeviceOwnerAuthentication" in src and "UserConsentVerifier" in src and "keychain" not in src,
      "uses the system's own check (LocalAuthentication / Windows Hello); no PhoneKeep password")

answers = []        # what the stand-in "Touch ID" answers next (True = confirmed, False = cancelled)
asked = []


def fake_auth(reason):
    asked.append(reason)
    time.sleep(0.1)
    return answers.pop(0) if answers else False


kind = {"v": "touch_id"}
applock.use_backend(lambda: kind["v"], fake_auth)

fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

try:
    import tkinter as tk
    import app as appmod
    import device as devmod

    class NoDevice:
        def __init__(self, *a, **k):
            raise wv.PhoneKeepError("no phone")
    devmod.LiveDevice = NoDevice
    wv.list_devices = lambda: []
    appmod.SETTINGS_FILE = W / "settings.json"
    appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups"), "archive_dir": str(W / "Archive"),
                                                "first_run_done": True}), encoding="utf-8")
    a = appmod.App()
    a.withdraw()

    def pump(until, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            a.update()
            if until():
                return True
            time.sleep(0.02)
        return False

    check(a.lock_on() and not a.is_unlocked(), "Touch ID: the lock is on by default and starts locked")

    # opening a backup asks; cancelling keeps it closed
    answers[:] = [False]
    a.open_backup(fake)
    pump(lambda: not a._asking_unlock)
    check(len(asked) == 1 and not a.open_phone_windows(), "opening a backup asks first; cancelling keeps it closed")

    # confirming opens it; the next window doesn't ask again
    answers[:] = [True]
    a.open_backup(fake)
    check(pump(lambda: a.open_phone_windows()), "confirming opens the backup")
    win = a.open_phone_windows()[0]
    n = len(asked)
    a.open_backup(fake)
    pump(lambda: len(a.open_phone_windows()) == 2)
    check(len(asked) == n and len(a.open_phone_windows()) == 2, "a second window in the same session doesn't ask again")

    # the phone window (connected phone) goes through the same gate
    a._unlocked = False
    a.device, a.udid = {"DeviceName": "Test iPhone"}, "00008030-S2TEST"
    answers[:] = [False]
    a.open_phone()
    pump(lambda: not a._asking_unlock)
    check(getattr(a, "phone_win", None) is None, "the phone window asks too; cancel keeps it closed")
    a._unlocked = True

    # idle: every phone window is covered until unlocked
    a.s["lock_idle_minutes"] = 5
    a._activity = time.time() - 6 * 60
    a._idle_check()
    a.update()
    wins = a.open_phone_windows()
    check(not a.is_unlocked() and all(getattr(w, "_lock_cover", None) is not None for w in wins),
          f"after 5 idle minutes every phone window is hidden ({len(wins)} windows)")
    check(all(w._lock_cover.winfo_manager() == "place" for w in wins), "behind a cover over the whole window")
    answers[:] = [False]
    wins[0].unlock_btn.invoke() if hasattr(wins[0].unlock_btn, "invoke") else wins[0].app.require_unlock(wins[0].uncover)
    pump(lambda: not a._asking_unlock)
    check(all(w._lock_cover is not None for w in wins), "Unlock, then cancel: still hidden")
    answers[:] = [True]
    a.require_unlock(wins[0].uncover)
    check(pump(lambda: all(getattr(w, "_lock_cover", 1) is None for w in wins)), "Unlock, confirmed: all windows show again")

    # the pointer moving over a PhoneKeep window while another app is in front doesn't count as use
    a._activity = time.time() - 6 * 60
    real_focus = a.focus_get
    a.focus_get = lambda: None
    a._touch(None)
    a.focus_get = real_focus
    check(time.time() - a._activity > 5 * 60, "moving the pointer over PhoneKeep while using another app isn't 'use'")

    # activity keeps it unlocked
    a._activity = time.time() - 60
    a._idle_check()
    check(a.is_unlocked(), "using PhoneKeep within the idle time keeps it unlocked")

    # the export's chooser asks too (from the export's worker thread)
    import threading
    a._unlocked = False
    answers[:] = [False]
    box = {}
    threading.Thread(target=lambda: box.update(r=a._choose_chats({"messages": ("Messages", [{"id": 1}])}, None))).start()
    pump(lambda: "r" in box)
    check(box.get("r") is None, "the export's chat chooser asks first; cancelled, nothing is shown or exported")

    # switching the lock off asks first when locked
    a.s["app_lock"] = True
    sw = appmod.SettingsWindow(a)
    sw.withdraw()
    a._unlocked = False
    answers[:] = [False]
    sw.lock_var.set(False)
    sw.set_lock()
    pump(lambda: not a._asking_unlock)
    check(a.s["app_lock"] is True and sw.lock_var.get() is True, "switching the lock off asks first; cancelled, it stays on")
    answers[:] = [True]
    sw.lock_var.set(False)
    sw.set_lock()
    pump(lambda: not a._asking_unlock)
    check(a.s["app_lock"] is False and not a.lock_on(), "confirmed, it's off")
    a.s["lock_idle_minutes"] = 10
    sw.destroy()
    a.destroy()

    # Mac with only a password: off by default, and the first-run guide offers it
    kind["v"] = "password"
    appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups2")}), encoding="utf-8")
    b = appmod.App()
    b.withdraw()
    check(not b.lock_on(), "Mac without Touch ID: off by default")
    b.destroy()
    # a Touch ID Mac with its lid closed reports only the password: once Touch ID was seen, the lock stays on
    kind["v"] = "touch_id"
    appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups2")}), encoding="utf-8")
    t1 = appmod.App(); t1.withdraw(); t1.lock_kind(); t1.destroy()
    kind["v"] = "password"
    b = appmod.App(); b.withdraw()
    check(b.lock_kind() == "touch_id" and b.lock_on(), "a Touch ID Mac with its lid closed keeps the lock on (asks for the password)")
    b.destroy()
    appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups2")}), encoding="utf-8")
    b = appmod.App(); b.withdraw()
    qs = []
    import firstrun
    src_fr = (HERE.parent / "firstrun.py").read_text(encoding="utf-8")
    check('lock_kind", lambda: None)() == "password"' in src_fr and b.lock_kind() == "password",
          "the first-run guide offers it on a Mac with only a password")
    b.destroy()

    # no Touch ID, no password, no Windows Hello: not offered, and nothing is locked
    kind["v"] = None
    c = appmod.App()
    c.withdraw()
    check(not c.lock_on() and c.is_unlocked(), "without any system check, there's no lock")
    sw = appmod.SettingsWindow(c)
    sw.withdraw()
    texts = []

    def walk(w):
        for ch in w.winfo_children():
            if isinstance(ch, tk.Label):
                texts.append(ch.cget("text"))
            walk(ch)
    walk(sw)
    check(any("not available on this computer" in t for t in texts), "and Settings says it isn't available")
    sw.destroy()
    c.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

# scheduled backups never go through the lock (the menu bar helper doesn't use applock)
helper_src = (HERE.parent / "helper_core.py").read_text(encoding="utf-8") + (HERE.parent / "helper_ui.py").read_text(encoding="utf-8")
check("applock" not in helper_src and "require_unlock" not in helper_src, "automatic backups run while PhoneKeep is locked")

print("\nS2 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
