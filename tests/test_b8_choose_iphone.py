"""B8: choose which iPhone when several are reachable (docs/spec/03-backup.md#b8-choose-which-iphone-when-several-are-reachable).

Done when (checked here with stand-in phones; the real two-iPhone check is on the owner's Mac):
- "Two real iPhones, one on the cable and one on Wi-Fi: both listed with the right connection; picking either backs
  up that one."  → both listed in the device card with cable / Wi-Fi; choosing one makes the options (Open iPhone,
  Back up now) its own, and the choice is remembered.
- "Unplugging the chosen phone does not switch the window to the other phone."  → the card says it's no longer
  connected and lists the other; nothing is chosen for the owner.
- "With both ticked for automatic backups, the helper backs up both, one after the other."  → per-phone ticks in
  Settings; the helper skips an unticked phone; a backup of one phone waits for another phone's backup to finish.
Also: a phone seen on both cable and Wi-Fi is listed once, as cable; with one phone nothing changes.
"""
import datetime as dt, json, os, shutil, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)   # no Touch ID prompts in tests
import phonekeep as wv

W = HERE / "work" / "b8"
shutil.rmtree(W, ignore_errors=True)
(W / "Backups").mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


A = {"DeviceName": "Test iPhone A", "UniqueDeviceID": "00008030-B8AAAA", "ConnectionType": "USB", "ProductVersion": "26.5",
     "ProductType": "iPhone15,3"}
B = {"DeviceName": "Test iPhone B", "UniqueDeviceID": "00008030-B8BBBB", "ConnectionType": "Network", "ProductVersion": "18.6",
     "ProductType": "iPhone18,2"}

import models
check(models.model_name("iPhone15,3") == "iPhone 14 Pro Max" and models.model_name("iPhone18,2") == "iPhone 17 Pro Max"
      and models.model_name("iPhone18,4") == "iPhone Air" and models.model_name("iPhone99,9") == "iPhone"
      and models.model_name(None) == "iPhone", "model names from the phone's code; an unknown code says just 'iPhone'")

# -- one phone over cable and Wi-Fi is listed once, as cable -------------------------------------------------
real_pmd3, real_check = wv._pmd3, wv.check_pmd3
wv.check_pmd3 = lambda: None
wv._pmd3 = lambda args, **k: subprocess.CompletedProcess(args, 0, json.dumps(
    [dict(A, ConnectionType="Network"), A, B]), "")
devs = wv.list_devices()
check([(d["UniqueDeviceID"], d["ConnectionType"]) for d in devs] == [(A["UniqueDeviceID"], "USB"), (B["UniqueDeviceID"], "Network")],
      "a phone on both cable and Wi-Fi is listed once, as cable")
wv._pmd3, wv.check_pmd3 = real_pmd3, real_check

# the first backup of phone A exists (so it shows a last-backup date and can be ticked)
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
shutil.copytree(fake, W / "Backups" / A["UniqueDeviceID"])

try:
    import tkinter as tk
    import app as appmod
    reach = {"devs": [A, B]}
    wv.list_devices = lambda: list(reach["devs"])
    appmod.SETTINGS_FILE = W / "settings.json"
    appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups"), "first_run_done": True}), encoding="utf-8")
    a = appmod.App()
    a.withdraw()

    def detect():
        a.detecting = False
        a.detect(silent=True)
        end = time.time() + 10
        while time.time() < end and a.detecting:
            a.update(); time.sleep(0.02)
        a.update()

    check(a.s["auto_backup_phones"] == [A["UniqueDeviceID"]],
          "on first start, the phones already backed up stay ticked for automatic backups; nothing else is")
    detect()
    rows = getattr(a, "phone_rows", {})
    check(a.udid is None and a.dev_name.cget("text") == "2 iPhones nearby" and not a.open_btn.enabled,
          f"two iPhones and none chosen yet: the card says so and nothing is picked ({a.dev_name.cget('text')!r})")
    texts = {u: " ".join(r.itemcget(i, "text") for i in r.find_all() if r.type(i) == "text") for u, r in rows.items()}
    check(set(rows) == {A["UniqueDeviceID"], B["UniqueDeviceID"]} and "Cable" in texts[A["UniqueDeviceID"]]
          and "Wi-Fi" in texts[B["UniqueDeviceID"]] and "iPhone 14 Pro Max iOS 26.5" in texts[A["UniqueDeviceID"]]
          and "iPhone 17 Pro Max iOS 18.6" in texts[B["UniqueDeviceID"]],
          f"both are shown as phones with their name, model, iOS and connection: {list(texts.values())}")
    _pc = rows[A["UniqueDeviceID"]]
    from PIL import Image as _Im
    _Im.new("RGB", (300, 600), (40, 90, 160)).save(W / "wall.png")
    _pc.set_wallpaper(W / "wall.png")
    check(not any(":" in _pc.itemcget(i, "text") for i in _pc.find_all() if _pc.type(i) == "text"),
          "with the phone's own picture, no clock is drawn over it (it has its own)")
    _pc.set_battery({"level": 80, "charging": True})
    _t = [_pc.itemcget(i, "text") for i in _pc.find_all() if _pc.type(i) == "text"]
    check("80%" in _t and "⚡" in _t and not any("🔋" in t or "📶" in t or "🔌" in t for t in _t),
          "the battery level and charging show on the card, as drawn icons (no emoji)")
    _pc.update_idletasks()
    _boxes = sorted((_pc.bbox(i) for i in _pc.find_all() if _pc.type(i) == "text" and _pc.itemcget(i, "anchor") == "n"),
                    key=lambda b: b[1])
    check(len(_boxes) == 3 and all(b1[3] <= b2[1] + 1 for b1, b2 in zip(_boxes, _boxes[1:])),
          "the name, model and iOS lines never overlap")

    a.choose_phone(B["UniqueDeviceID"])
    a.update()
    check(a.udid == B["UniqueDeviceID"] and a.dev_name.cget("text") == "Test iPhone B" and a.open_btn.enabled
          and "Wi-Fi" in a.dev_line.cget("text"), "picking a phone makes the card and its buttons that phone's")
    check(a.s["chosen_udid"] == B["UniqueDeviceID"], "and the choice is remembered")
    detect()
    check(a.udid == B["UniqueDeviceID"], "looking for phones again keeps the chosen one")
    check(a.phone_rows[B["UniqueDeviceID"]].chosen and not a.phone_rows[A["UniqueDeviceID"]].chosen,
          "the chosen phone is highlighted (green outline and ✓)")

    # the chosen phone goes away: no switching by itself
    reach["devs"] = [A]
    detect()
    check(a.udid is None and "Test iPhone B is no longer connected" == a.dev_name.cget("text") and not a.open_btn.enabled,
          f"unplugging the chosen phone doesn't switch to the other one ({a.dev_name.cget('text')!r})")
    check(list(a.phone_rows) == [A["UniqueDeviceID"]], "the others are listed to pick from")
    a.choose_phone(A["UniqueDeviceID"])
    a.update()
    check(a.udid == A["UniqueDeviceID"] and a.s["chosen_udid"] == A["UniqueDeviceID"], "picking the other one works")
    detect()
    check(not a.phone_list.winfo_manager(), "with one phone reachable, no list: nothing changes from before")

    # Settings: a tick per phone for automatic backups
    reach["devs"] = [A, B]
    detect()
    sw = appmod.SettingsWindow(a)
    sw.withdraw()
    check(set(sw.phone_vars) == {A["UniqueDeviceID"], B["UniqueDeviceID"]} and sw.phone_vars[A["UniqueDeviceID"]].get()
          and not sw.phone_vars[B["UniqueDeviceID"]].get(), "Settings lists each phone; a new one is not ticked")
    sw.destroy()
    a.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

# -- the helper only backs up ticked phones -------------------------------------------------------------------
import helper_core as hc
hc.SETTINGS_FILE = W / "settings.json"
s = json.loads(hc.SETTINGS_FILE.read_text(encoding="utf-8"))
s.update(auto_backup="daily", auto_backup_hour=21, auto_backup_phones=[])
hc.SETTINGS_FILE.write_text(json.dumps(s), encoding="utf-8")
wv.list_devices = lambda: [A]
h = hc.Helper(notify=lambda t, m: None, backup_dir=W / "Backups")
h.clock = lambda: dt.datetime(2026, 11, 20, 21, 5)
h._refresh_at = 0
started = []
h.back_up_now = lambda udid=None: started.append(udid) or True
r = h.tick()
check(not started and f"skip:{A['UniqueDeviceID']}" in r, f"an unticked phone isn't backed up automatically ({r})")
s["auto_backup_phones"] = [A["UniqueDeviceID"]]
hc.SETTINGS_FILE.write_text(json.dumps(s), encoding="utf-8")
r = h.tick()
check(started == [A["UniqueDeviceID"]], f"once ticked, it is ({r})")

# -- never two backups at once: another phone's backup waits, and can be cancelled while waiting -----------
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
(W / "Backups" / "backup-running.lock").write_text(f"{other.pid}\n{A['UniqueDeviceID']}\nTest iPhone A", encoding="utf-8")
said, out = [], {}
t = threading.Thread(target=lambda: out.update(r=wv._wait_for_other_phone(W / "Backups", B["UniqueDeviceID"], said.append, poll=0.1)))
t.start()
time.sleep(0.6)
check(t.is_alive() and said and "Waiting for the backup of 'Test iPhone A' to finish" in said[0],
      f"a backup of another phone waits and says so: {said}")
other.kill(); other.wait()
t.join(5)
check(not t.is_alive(), "and starts as soon as the other one has finished")
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
(W / "Backups" / "backup-running.lock").write_text(f"{other.pid}\n{A['UniqueDeviceID']}\nTest iPhone A", encoding="utf-8")
t = threading.Thread(target=lambda: out.update(r=_safe()))


def _safe():
    try:
        wv._wait_for_other_phone(W / "Backups", B["UniqueDeviceID"], lambda m: None, poll=0.1)
        return "started"
    except wv.BackupCancelled:
        return "cancelled"


t = threading.Thread(target=lambda: out.update(r=_safe()))
t.start()
time.sleep(0.4)
check(wv.cancel_backup(), "Cancel works while waiting")
t.join(5)
check(out.get("r") == "cancelled", "and stops the waiting backup")
other.kill(); other.wait()
src = (HERE.parent / "phonekeep.py").read_text(encoding="utf-8")
check("_wait_for_other_phone(backup_root, udid" in src and "backup-running.lock" in src, "make_backup waits for another phone's backup")

print("\nB8 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
