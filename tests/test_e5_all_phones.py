"""E5: all phones and backups in one list (docs/spec/05-ease-of-use.md#e5-all-phones-and-backups-in-one-list).

Done when: "Two phones show as two cards; each opens its own phone window, even when not connected."
  → two invented phones backed up here, none connected: two cards (and "Add another iPhone"); each opens a phone
    window for its own backup, with no live phone.
Also: a connected phone that was never backed up gets a card too; connected phones come first with a green
"connected" line; the card shows the model, last backup, size and lock badge; clicking a card again brings its
window back instead of opening a second; opening a connected phone that isn't the chosen one leaves the choice (B8)
as it was; with one phone the list stays hidden; "Add another iPhone" explains and looks for phones, writing nothing.
"""
import json, os, shutil, subprocess, sys, time
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
import snapshots as sn

W = HERE / "work" / "e5"
shutil.rmtree(W, ignore_errors=True)
BD = W / "Backups"
BD.mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

# phone A: PhoneKeep's snapshot layout; phone C: an older backup (one folder, no snapshots); phone B: never backed up
A, B, C = "00008030-E5AAAA", "00008030-E5BBBB", "00008030-E5CCCC"
shutil.copytree(fake, sn.current_dir(BD, A))
snap_a = sn.make_snapshot(BD, A)
shutil.copytree(fake, BD / C)
DA = {"DeviceName": "Test iPhone A", "UniqueDeviceID": A, "ConnectionType": "USB", "ProductVersion": "26.5",
      "ProductType": "iPhone15,3"}
DB = {"DeviceName": "Test iPhone B", "UniqueDeviceID": B, "ConnectionType": "Network", "ProductVersion": "18.6",
      "ProductType": "iPhone18,2"}

import app as appmod
import models

# -- the list itself -------------------------------------------------------------------------------------------
ps = appmod.phone_summaries(BD, [DB, DA])
check([p["udid"] for p in ps] == [A, B, C] or [p["udid"] for p in ps] == [B, A, C],
      f"every phone connected now or backed up here, once each, connected ones first: {[p['udid'] for p in ps]}")
pa = next(p for p in ps if p["udid"] == A)
pb = next(p for p in ps if p["udid"] == B)
pc = next(p for p in ps if p["udid"] == C)
check(pa["how"] == "cable" and pb["how"] == "Wi-Fi" and pc["how"] is None, "how each is connected (or not)")
check(pa["name"] == "Test iPhone A" and pa["model"] == "iPhone 14 Pro Max" and pa["size"] == snap_a.size
      and pa["last"] and pa["encrypted"] is not None,
      "a backed-up phone: its name and model, the last backup, the newest snapshot's size and its lock state")
check(pb["last"] is None and pb["encrypted"] is None and pb["size"] is None, "a phone never backed up: no backup facts")
check(pc["last"] and pc["size"] is None and pc["name"], "an older backup without snapshots still has its date and name")
check([p["udid"] for p in appmod.phone_summaries(BD, [])] == [A, C] or [p["udid"] for p in appmod.phone_summaries(BD, [])] == [C, A],
      "with nothing connected, the phones backed up here are still listed")

# -- the main window -------------------------------------------------------------------------------------------
import tkinter as tk
from tkinter import messagebox
import device as devmod
import phone


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
opened = []
real_pw = phone.PhoneWindow


class SpyWindow(real_pw):
    def __init__(self, app, device, udid, backup=None):
        opened.append((dict(device or {}).get("DeviceName"), udid, backup))
        super().__init__(app, device, udid, backup)
        self.withdraw()


phone.PhoneWindow = SpyWindow
reach = {"devs": []}
wv.list_devices = lambda: list(reach["devs"])
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(BD), "archive_dir": str(W / "Archive"),
                                            "first_run_done": True}), encoding="utf-8")
a = appmod.App()
a.withdraw()
a.after_cancel(a._timers.pop("first"))


def pump(until, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    a.update()
    return until()


def close_windows():
    """Close the phone windows as the close button does (it lets go of the backup's files: Windows can't delete
    an open Manifest.db), once a window's backup has finished loading."""
    for w in a.open_phone_windows():
        if w.backup_path is not None:
            pump(lambda: w.data is not None or w.data_error is not None, 30)
        w.close()
    a.update()


def detect():
    a.detecting = False
    gen = a._all_gen
    a.detect(silent=True)
    pump(lambda: not a.detecting and a._all_gen > gen)
    pump(lambda: False, 0.4)         # the list is read in the background


detect()
tiles = a.phone_tiles
check(set(tiles) == {A, C} and a.all_phones.winfo_manager() == "pack",
      f"Done when: two phones backed up, none connected: two cards ({len(tiles)})")
check(len(a.all_grid.winfo_children()) == 2 and a.add_link.winfo_manager() and "Add another iPhone" in a.add_link.cget("text")
      and a.add_link.bind("<Button-1>"), "  and 'Add another iPhone' at the end of the list's title line")
ta = tiles[A].texts()
check(ta[0] == pa["name"] == "Test iPhone A" or ta[0] == sn.list_snapshots(BD, A)[0].name, f"  with no phone connected, the name comes from its backup: {ta[0]!r}")
check(ta[1] == models.model_name(sn.list_snapshots(BD, A)[0].model) + " · under 1 MB"
      and ta[2].startswith("Backed up ") and ta[3] in ("🔒 Encrypted", "⚠ Not encrypted") and len(ta) == 4,
      f"  a card: name, model and size, when it was backed up, lock badge, no 'connected' mark: {ta}")
check(appmod.ui.PhoneTile.when("2026-11-10 22:00").startswith("Backed up ") and appmod.ui.PhoneTile.when(None) == "Not backed up yet",
      "  'Backed up 5 days ago', worded as the phone card says it")

tiles[C].click()
pump(lambda: len(opened) == 1)
check(len(opened) == 1 and opened[0][1] == C and Path(opened[0][2]) == BD / C,
      f"  clicking a phone that isn't connected opens its own backup: {opened}")
win_c = a.phone_windows[-1]
check(win_c.udid == C and win_c.live_wanted is False, "  in a phone window for that phone, with no live phone")
tiles[A].click()
pump(lambda: len(opened) == 2)
check(len(opened) == 2 and Path(opened[1][2]) == snap_a.path and a.phone_windows[-1].udid == A,
      "  the other card opens the other phone's own window (its newest snapshot)")
tiles[C].click()
pump(lambda: False, 0.3)
check(len(opened) == 2, "clicking a card again brings its window back; no second window")

# -- phones connected now ------------------------------------------------------------------------------------
a.s["chosen_udid"] = A
reach["devs"] = [DA, DB]
detect()
order = list(a.phone_tiles)
check(set(order) == {A, B, C} and order[-1] == C, f"a connected phone never backed up gets a card; connected first: {order}")
tb = a.phone_tiles[B].texts()
check("● Wi-Fi" in tb and "Not backed up yet" in tb and not any("ncrypted" in t for t in tb), f"  it says it's connected and not backed up: {tb}")
check("● Cable" in a.phone_tiles[A].texts(), "  the cable phone says so too")
close_windows()
check(a.udid == A, "phone A is the chosen one (B8)")
a.phone_tiles[B].click()
pump(lambda: len(opened) == 3)
check(len(opened) == 3 and opened[2][:2] == ("Test iPhone B", B) and opened[2][2] is None,
      f"  clicking the connected phone that isn't chosen opens it live: {opened[-1:]}")
check(a.udid == A and a.s["chosen_udid"] == A, "  and the phone chosen for backing up stays the same")

check(all(w.bind("<ButtonRelease-1>") for w in [a.phone_tiles[A]] + list(a.phone_tiles[A].winfo_children())
          + a.phone_tiles[A].lines), "a click anywhere on a card opens it")

# -- the first-run guide (E1) ----------------------------------------------------------------------------------
three = appmod.phone_summaries(BD, [DA, DB])
a.start_first_run()
a.update()
pumped = []
a._all_key = None                               # a list not shown before (e.g. the second phone just came)
a._show_all_phones(three)                       # two phones connected while the guide is up
a.call(lambda: pumped.append(1))
pump(lambda: pumped, 3)
check(pumped and a.all_phones.winfo_manager() == "", "two phones during the first-run guide: no list over the guide, and the window keeps working")
a.end_first_run()
pump(lambda: False, 0.3)
a._show_all_phones(three)
check(a.all_phones.winfo_manager() == "pack" and set(a.phone_tiles) == {A, B, C}, "  after the guide, the list shows")
a.start_first_run()
a.update()
a.end_first_run()
check(a.all_phones.winfo_manager() == "", "  when the guide ends, the list isn't put back by itself (the next search decides)")
a._show_all_phones(three[:1])
check(a.all_phones.winfo_manager() == "", "the guide ending with one phone: no empty 'Your iPhones' title")

# -- a phone whose backup went away ----------------------------------------------------------------------------
told = []
real_info = messagebox.showinfo
messagebox.showinfo = lambda title, text, **k: told.append(text)
before = len(opened)
a.open_phone_for("00008030-E5GONE")
messagebox.showinfo = real_info
check(told and len(opened) == before, "a phone with no backup left and not connected: it says so and opens nothing")

# -- one phone: no list --------------------------------------------------------------------------------------
close_windows()
shutil.rmtree(BD / C)
shutil.rmtree(BD / A)
reach["devs"] = [DA]
detect()
check(a.all_phones.winfo_manager() == "" and not a.phone_tiles, "with one phone the list stays hidden (the card above is that phone)")

# -- Add another iPhone ---------------------------------------------------------------------------------------
told = []
real_info = messagebox.showinfo
messagebox.showinfo = lambda title, text, **k: told.append((title, text))
looked = []
real_detect = a.detect
a.detect = lambda *x, **k: looked.append(1)
a.add_phone()
a.detect, messagebox.showinfo = real_detect, real_info
check(told and "cable" in told[0][1] and "Trust" in told[0][1] and looked,
      "'Add another iPhone' says how to connect it, then looks for phones")
src = (HERE.parent / "app.py").read_text(encoding="utf-8")
body = src[src.index("def add_phone"):src.index("# A phone on Wi-Fi comes and goes")]
check("phone_write" not in body and "phone_write" not in src[src.index("def phone_summaries"):src.index("class Settings")],
      "  nothing in the list or 'Add another' writes to a phone")

a.destroy()
print("\nE5 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
