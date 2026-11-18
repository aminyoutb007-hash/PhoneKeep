"""S7: the activity record (docs/spec/04-security.md#s7-activity-log).

Done when: "Each backup, save, restore and write-to-phone action appears once with date and summary."
- a backup (the engine both the window and the menu bar helper use): once, with the phone's name and its lock state;
- saves from a phone window (a list of files, Save everything, one app, PDFs) and from the main window's archive:
  once each, counted, with the folder, never a file's name or anything from inside the backup;
- writes to the iPhone: through phone_write.run() (S1's test checks those lines and that no password is in them);
- restore isn't built yet (B6, 5.3), so it has nothing to record.
Also: kept on this computer only, 12 months (older lines are dropped at start-up), damaged lines skipped; Settings →
Activity lists it, newest first, and saves it as CSV that Excel can open safely.
"""
import csv, datetime as dt, json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
import activity

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
W = HERE / "work" / "s7"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
activity.ACTIVITY_FILE = W / "activity.jsonl"


def lines() -> list:
    return [json.loads(x) for x in activity.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()] \
        if activity.ACTIVITY_FILE.exists() else []


# -- the record itself -----------------------------------------------------------------------------------------
now = dt.datetime(2026, 11, 16, 20, 0)
old = [{"when": "2025-10-01T09:00:00", "kind": "backup", "phone": None, "summary": "Backed up an old phone"},
       {"when": "2026-03-04T21:04:00", "kind": "backup", "phone": None, "summary": "Backed up Sam's iPhone (encrypted)"}]
activity.ACTIVITY_FILE.write_text("".join(json.dumps(d) + "\n" for d in old) + "not json\n", encoding="utf-8")
es = activity.entries(now)
check([d["summary"] for d in es] == ["Backed up Sam's iPhone (encrypted)"],
      "the record shows the last 12 months; older and damaged lines are left out")
check(activity.line(es[0]) == "4 Mar 2026 21:04 · Backed up Sam's iPhone (encrypted)",
      f"each line in plain words, with its date: {activity.line(es[0])!r}")
check(activity.prune(now) == 2 and len(lines()) == 1, "older than 12 months (and damaged) is dropped from the file")
check(activity.prune(now) == 0, "  and nothing more the next time")
# the menu bar helper (another process) adds a line while the window trims: the line is never lost
activity.ACTIVITY_FILE.write_text(json.dumps(old[0]) + "\n" + json.dumps(old[1]) + "\n", encoding="utf-8")
_real_parse = activity._parse


def parse_while_helper_writes(rows, since):
    with open(activity.ACTIVITY_FILE, "a", encoding="utf-8") as f:     # not through log(): another process
        f.write(json.dumps({"when": "2026-11-16T19:59:00", "kind": "backup", "phone": None,
                            "summary": "Backed up by the helper"}) + "\n")
    return _real_parse(rows, since)


activity._parse = parse_while_helper_writes
dropped = activity.prune(now)
activity._parse = _real_parse
check(dropped == 0 and "Backed up by the helper" in activity.ACTIVITY_FILE.read_text(encoding="utf-8")
      and not activity.ACTIVITY_FILE.with_suffix(".tmp").exists(),
      "a line written by another process while trimming is kept (that trim waits for the next start-up)")
check(activity.prune(now) == 1 and [d["summary"] for d in lines()] == ["Backed up Sam's iPhone (encrypted)",
                                                                        "Backed up by the helper"],
      "  and the next trim drops only the old line")
activity.ACTIVITY_FILE.write_text(json.dumps(old[1]) + "\n", encoding="utf-8")      # back to one line
activity.saved(12, "photo", Path.home() / "Desktop", "Sam's iPhone")
activity.saved(1, "photo/video", W, plural="photos/videos")
activity.saved(3, "photo/video", W, plural="photos/videos")
activity.saved(0, "file", W)
got = [d["summary"] for d in lines()[1:]]
check(got[0] == f"Saved 12 photos to ~{os.sep}Desktop" and got[1].startswith("Saved 1 photo/video to ")
      and got[2].startswith("Saved 3 photos/videos to ") and len(got) == 3,
      f"a save is counted, with its folder (home as ~); nothing saved, nothing recorded: {got}")
check(lines()[1]["phone"] == "Sam's iPhone" and lines()[1]["kind"] == "save", "  with the phone, as a save")
check(activity.where(Path.home().as_posix() + "/Documents/Saved") == os.path.join("~", "Documents", "Saved")
      and activity.where(Path.home()) == "~" and activity.where(str(Path.home()) + "x") == str(Path.home()) + "x",
      "a folder typed with / (as Windows' folder box gives it) is shown under ~ too; a look-alike isn't")
activity.log("=HYPERLINK(\"http://x\")", kind="settings")
out = activity.save_csv(W / "activity.csv", now=dt.datetime.now())
with open(out, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.reader(f))
check(rows[0] == ["Date", "Time", "What", "iPhone", "Kind"] and rows[1][2] == "Backed up Sam's iPhone (encrypted)"
      and rows[1][:2] == ["2026-03-04", "21:04"] and len(rows) == 6,
      "saved as CSV, oldest first, with date, time, what, phone and kind")
check(rows[-1][2].startswith("'="), "  a line starting with = can't run as a formula in Excel")

# -- a backup: once, from the engine the window and the helper share -----------------------------------------
activity.ACTIVITY_FILE.unlink()
UD = "00008030-S7TEST0000000000"
stub = W / "stub_launcher.py"
stub.write_text(f'''
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 0")
elif args[0] == "--pk-backup":
    d = Path(args[1]) / "{UD}"
    shutil.copytree(r"{fake}", d, dirs_exist_ok=True)
    print("PKSTAGE started", flush=True)
    print("PKPCT 100.0", flush=True)
''', encoding="utf-8")
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
wv.phone_used_bytes = lambda udid: 1_000_000
# an invented phone only: nothing here may reach a real iPhone (reviewer, #84)
wv.list_devices = lambda: [{"DeviceName": "Test iPhone", "UniqueDeviceID": UD, "ConnectionType": "USB"}]
asked_phone = []
wv.device_overview = lambda *a, **k: asked_phone.append("overview")
wv.read_crash_reports = lambda *a, **k: asked_phone.append("crashes")
wv.read_security = lambda *a, **k: asked_phone.append("security")
path = wv.make_backup(W / "Backups", UD, log=lambda m: None)
backups = [d for d in lines() if d["kind"] == "backup"]
check(Path(path).exists() and len(backups) == 1
      and backups[0]["summary"] == f"Backed up {wv.backup_info(path)['name']} (not encrypted)",
      f"a backup is recorded once, with the phone's name and whether it's encrypted: {[d['summary'] for d in backups]}")
check(asked_phone == ["overview", "crashes", "security"], "  (the after-backup reads went to stand-ins, not a phone)")

# -- saves in a phone window -----------------------------------------------------------------------------------
import tkinter as tk
import app as appmod
from tkcompat import hide                                   # Tk 8.6 on a Mac: a withdrawn phone window hangs update()
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
appmod.SETTINGS_FILE = W / "settings.json"
with open(activity.ACTIVITY_FILE, "a", encoding="utf-8") as f:
    f.write(json.dumps({"when": "2024-01-01T09:00:00", "kind": "backup", "phone": None,
                        "summary": "Backed up a phone long ago"}) + "\n")
a = appmod.App()
a.withdraw()
a.after_cancel(a._timers.pop("first"))
a.s["backup_dir"] = str(W / "Backups")
a.s["archive_dir"] = str(W / "Archive")


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


check(pump(lambda: "long ago" not in activity.ACTIVITY_FILE.read_text(encoding="utf-8"), 10)
      and "Test iPhone (not encrypted)" in activity.ACTIVITY_FILE.read_text(encoding="utf-8"),
      "at start-up PhoneKeep drops lines older than 12 months and keeps the rest")
BK = W / "open" / "00008030-S7OPEN0000000000"
shutil.copytree(fake, BK)
activity.ACTIVITY_FILE.unlink()
check(a.open_backup(BK), "the invented backup opens in a phone window")
win = a.phone_windows[-1]
hide(win)
check(pump(lambda: win.data is not None), "  its backup is read")
lines_before = len(lines())

win.saved([W / "a.jpg", W / "b.jpg", None], W / "Saved", "photo/video")
new = lines()[lines_before:]
check(len(new) == 1 and new[0]["summary"] == f"Saved 2 photos/videos to {activity.where(W / 'Saved')}"
      and new[0]["phone"] == win.name and new[0]["kind"] == "save",
      f"a save in a phone window: once, counted, with its folder and the phone: {[d['summary'] for d in new]}")

n0 = len(lines())
win.export_section("notes", {"web"}, out=W / "Exports")
check(pump(lambda: len(lines()) > n0), "saving one app (Notes) ...")
check([d["summary"] for d in lines()[n0:]] == [f"Saved Notes to {activity.where(W / 'Exports')}"],
      "  is recorded once")

n0 = len(lines())
printed = []
win.export_section("notes", {"pdf"}, then=printed.append, out=W / "Print")
check(pump(lambda: printed) and len(lines()) == n0, "Print (a save into a temporary folder for printing) isn't a save")

n0 = len(lines())
win.save_everything(choice={"sections": ["notes", "calls"], "formats": ["web"], "dates": None, "search": ""},
                    folder=W / "Everything")
check(pump(lambda: len(lines()) > n0), "Save everything ...")
check([d["summary"] for d in lines()[n0:]] == [f"Saved everything to {activity.where(W / 'Everything')}"],
      "  is recorded once")

# the chats' PDF save: ticked chats, one PDF each, saved to the folder chosen
from tkinter import messagebox as _mb
import ui as _ui
n0 = len(lines())
win.open_app("messages")
check(pump(lambda: any(isinstance(w, _ui.ChatPanel) for w in win.content.winfo_children())), "Messages opens")
panel = next(w for w in win.content.winfo_children() if isinstance(w, _ui.ChatPanel))
panel.selected = {("messages", c["id"]) for _k, _l, c in panel.rows[:2]}
win.out_dir = lambda key: (W / "ChatPDFs").mkdir(exist_ok=True) or W / "ChatPDFs"     # as the folder dialog would
_mb.askyesnocancel = lambda *a, **k: False             # one PDF per chat
_open = sys.modules["phone"].reveal
sys.modules["phone"].reveal = lambda *a, **k: None     # don't open Finder in a test


def find_button(w, text):
    for c in w.winfo_children():
        if isinstance(c, _ui.RoundButton) and c.text == text:
            return c
        r = find_button(c, text)
        if r is not None:
            return r


find_button(panel, "Save ticked as PDF").command()
check(pump(lambda: len(lines()) > n0, 90), "saving ticked chats as PDF ...")
got = [d["summary"] for d in lines()[n0:]]
check(got == [f"Saved 2 PDFs to {activity.where(W / 'ChatPDFs')}"],
      f"  is recorded once, counted, never by the chats' names: {got}")
sys.modules["phone"].reveal = _open

# the iPhone's details, the battery history, Photo clean-up's summary
import deviceinfo as di, overview_ui, checkup_ui, cleanup_ui, cleanup as cl
n0 = len(lines())
(W / "Details").mkdir()
overview_ui.save_details(win, di.Overview(name="Test iPhone"), W / "Details" / "Test iPhone.json")
checkup_ui.save_battery_details(win, [], None, W / "Details" / "battery.csv")
got = [d["summary"] for d in lines()[n0:]]
check(got == [f"Saved the iPhone's details to {activity.where(W / 'Details')}",
              f"Saved the battery history to {activity.where(W / 'Details')}"],
      f"the iPhone's details and the battery history files: once each: {got}")
n0 = len(lines())


class _St:
    result = type("R", (), {"items": [], "cards": []})()
    runner = None


try:
    cleanup_ui.summary(win, _St(), cl.SaveResult(saved=[object(), object(), object()]), W / "Cleanup")
except Exception:                                       # the summary screen itself needs more than this stand-in
    pass
got = [d["summary"] for d in lines()[n0:]]
check(got == [f"Saved 3 photos and videos to {activity.where(W / 'Cleanup')}"],
      f"Photo clean-up's save: once, counted: {got}")

# never message text, never a password: the fixture's chats, notes and the backup password stay out
record = activity.ACTIVITY_FILE.read_text(encoding="utf-8")
check(not any(t in record for t in ("Dinner Friday?", "Milk", "Salam! WhatsApp test", "test-password")),
      "no message or note text and no password in the record")

# -- the main window's archive --------------------------------------------------------------------------------
n0 = len(lines())
a._reset_progress(appmod.EXPORT_STEPS, "Building your archive")
a._exported(str(W / "Archive" / "index.html"))
check([d["summary"] for d in lines()[n0:]] == [f"Saved the archive to {activity.where(W / 'Archive')}"],
      "the main window's archive is recorded once")

# -- Settings → Activity ------------------------------------------------------------------------------------------
sw = appmod.SettingsWindow(a)
sw.withdraw()
shown = sw.activity_lines.get("1.0", "end").strip().splitlines()
check(len(shown) == len(lines()) and shown[0].endswith(f"Saved the archive to {activity.where(W / 'Archive')}")
      and "Backed up" not in shown[0],
      f"Settings → Activity lists every line of the last 12 months, newest first ({len(shown)})")
p = sw.save_activity(W / "from-settings.csv")
with open(p, encoding="utf-8-sig", newline="") as f:
    check(len(list(csv.reader(f))) == len(lines()) + 1, "  and saves it as CSV")
sw.destroy()

win.close()
a.destroy()


print("\nS7 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
