"""Phone-window test against a simulated iPhone.

Opens the real PhoneWindow (phone.py) on the fake backup built by test_full_backup.py, with the live
iPhone replaced by a simulated device (wallpaper, music, books, apps and app files served from memory).
Checks that the home screen fills in its counts, that every app screen opens without an error, that a
save produces a file, and that the window closes cleanly.

Needs a display: on Mac and Windows there is one; on Linux run it under `xvfb-run`.
"""
import datetime as dt, io, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

W = HERE / "work"
UDID = "00008030-FULLTEST"
BACKUPS = W / "Backups"
if not (BACKUPS / UDID / "Manifest.db").exists():
    print("fake backup missing: building it with test_full_backup.py first", flush=True)
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

import faulthandler
faulthandler.dump_traceback_later(120, repeat=True)   # if this ever stalls in CI, show where

import tkinter as tk
from PIL import Image

import phonekeep as wv
import sections as sx
import device as devmod
import photos as ph
import phone
import keychain
from ui import RED

keychain.use_memory()   # never touch the real keychain from a test

# ---------------------------------------------------------------------------
# the simulated iPhone: same methods as device.LiveDevice, data from memory
# ---------------------------------------------------------------------------

SIM_DIR = W / "sim-phone"
shutil.rmtree(SIM_DIR, ignore_errors=True)
SIM_DIR.mkdir(parents=True)


class SimulatedDevice:
    def __init__(self, udid, cache_dir=None):
        self.udid = udid
        self.calls = []

    def wallpaper(self, which="homescreen"):
        self.calls.append(("wallpaper", which))
        p = SIM_DIR / f"{which}.png"
        Image.new("RGB", (390, 844), (40, 120, 90)).save(p)
        return p

    def music(self):
        self.calls.append(("music",))
        return [devmod.Track("Song One", "Artist A", "Album X", 201.0, "iTunes_Control/Music/F00/one.m4a", 4_000_000),
                devmod.Track("Song Two", "Artist B", "Album Y", 150.5, "iTunes_Control/Music/F01/two.m4a", 3_100_000)]

    def books(self):
        self.calls.append(("books",))
        return [devmod.Book("A Novel", "Writer", "Books/1.epub", "EPUB", 500_000, True),
                devmod.Book("Manual", "Maker", "Books/2.pdf", "PDF", 120_000, False)]

    def apps(self):
        self.calls.append(("apps",))
        return [devmod.AppInfo("org.videolan.vlc-ios", "VLC", "3.5", True),
                devmod.AppInfo("com.apple.Pages", "Pages", "14.0", True),
                devmod.AppInfo("com.spotify.client", "Spotify", "8.9", False)]

    def app_list(self, bundle_id, path="Documents"):
        self.calls.append(("app_list", bundle_id, path))
        return [devmod.Entry("Movies", "Documents/Movies", True),
                devmod.Entry("clip.mp4", "Documents/clip.mp4", False, 48_000_000, dt.datetime(2026, 3, 4, 10, 30))]

    def app_pull(self, bundle_id, path, dest_dir):
        self.calls.append(("app_pull", bundle_id, path))
        dest = Path(dest_dir) / Path(path).name
        dest.write_bytes(b"simulated")
        return True

    def copy_media(self, path, dest, is_dir=False):
        Path(dest).write_bytes(b"simulated")
        return True

    def close(self):
        self.calls.append(("close",))


class NoDevicePhotos:
    """Photos over the cable aren't simulated: the window must fall back to the backup's photos."""
    def __init__(self, udid, cache_dir):
        raise wv.PhoneKeepError("Photos on the iPhone aren't reachable (simulated).")


devmod.LiveDevice = SimulatedDevice
ph.DevicePhotoSource = NoDevicePhotos


class FakeApp(tk.Tk):
    """The bits of the main window that PhoneWindow uses (it is a Tk root, like app.App)."""
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(BACKUPS), "archive_dir": str(W / "Archive-phone-window")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:            # a console that can't show ✓ or ' (Windows cp1252)
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


def pump(root, until, timeout=60.0, what=""):
    """Run the Tk event loop until `until()` is true or the timeout passes."""
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    print(f"timed out waiting for {what}", flush=True)
    return False


def labels_in(widget):
    out = []
    for w in widget.winfo_children():
        if isinstance(w, tk.Label):
            out.append(w)
        out.extend(labels_in(w))
    return out


def error_labels(win):
    red = str(RED).lower()
    return [l for l in labels_in(win.content) if str(l.cget("fg")).lower() == red]


def still_loading(win):
    texts = [l.cget("text") for l in labels_in(win.content)]
    return any(t in ("Loading…", "Reading from the iPhone…") for t in texts)


# ---------------------------------------------------------------------------
# the test
# ---------------------------------------------------------------------------

app = FakeApp()
root = app
info = wv.backup_info(BACKUPS / UDID)
win = phone.PhoneWindow(app, {"DeviceName": info.get("name") or "Test iPhone"}, UDID)
# the window stays mapped: a withdrawn Toplevel behaves differently on macOS (geometry events), and the
# CI machines have a display

# window basics
check(info["name"] in win.title(), f"window title names the phone: {win.title()!r}")
check(tuple(win.minsize()) == (980, 640), "minimum window size is 980 x 640")

# home screen: counts fill in for every backup app
backup_apps = [k for k, *_r, where in phone.APPS if where == "backup"]
ok = pump(root, lambda: all(k in win.counts for k in backup_apps), 90, "home screen counts")
check(ok, "home screen counts filled in for every backup app")
expected_chats = len(sx.load_messages(win.data.ctx)) if win.data else -1
check(win.counts.get("messages") == f"{expected_chats:,} chats", f"Messages count matches the backup ({win.counts.get('messages')})")
present = [k for k in backup_apps if win.counts.get(k) not in (None, "nothing found")]
check(len(present) >= 8, f"{len(present)} apps have data in the fake backup")

# the simulated phone was used for the wallpaper
check(pump(root, lambda: win.live is not None, 30, "simulated device"), "simulated iPhone connected")
check(any(c[0] == "wallpaper" for c in win.live.calls), "wallpaper read from the simulated iPhone")

# every app screen opens: with content, or (for a kind of data the backup doesn't have) with a message
# that says so in plain words. Anything else shown in red is a failure.
for key, label, *_r in phone.APPS:
    win.open_app(key)
    pump(root, lambda: not still_loading(win), 90, f"{label} screen")
    errs = [l.cget("text") for l in error_labels(win)]
    has_data = win.counts.get(key, "") != "nothing found"
    empty_ok = (not has_data) and len(errs) == 1 and errs[0].startswith("No ") and "in this backup" in errs[0]
    check(not still_loading(win) and (not errs or empty_ok),
          f"{label} screen opens" + (" (empty state explained)" if empty_ok else "")
          + (f" (error: {errs[0][:80]})" if errs and not empty_ok else ""))
    check(len(win.content.winfo_children()) > 0, f"{label} screen shows content")

# photos came from the backup because the cable was 'unplugged'
check(isinstance(win.photo_src, ph.BackupPhotoSource), "Photos fell back to the backup when the iPhone wasn't reachable")

# saving: export one app through the window's own save path
out_dir = Path(app.s["archive_dir"])
shutil.rmtree(out_dir, ignore_errors=True)
win.export_section("messages", {"excel"})
ok = pump(root, lambda: str(win.bar_text.cget("text")).startswith("✓ Exported"), 120, "export banner")
check(ok, f"save shows a done banner: {win.bar_text.cget('text')!r}")
xlsx = list(out_dir.rglob("*.xlsx"))
check(bool(xlsx), f"save produced an Excel file ({len(xlsx)} found)")

# closing
# B3: renaming a snapshot from the timeline uses PhoneKeep's own text dialog (found on a Mac: Tk's
# simpledialog never appeared); the typed name lands in snapshots.json
import datetime as _dt, json as _json
from types import SimpleNamespace
import snapshots as _sn2
snap0 = SimpleNamespace(id="20261112-164026", when=_dt.datetime(2026, 11, 12, 16, 40), label=None, locked=False, title="Today")
typed = []
real_ask = phone.ui.ask_text
phone.ui.ask_text = lambda parent, title, prompt, initial="", ok="Save": typed.append((title, initial)) or "Before the holiday"
try:
    win._rename_snapshot(snap0)
finally:
    phone.ui.ask_text = real_ask
choices_file = _sn2.phone_dir(win.backup_dir, win.udid) / "snapshots.json"
saved = _json.loads(choices_file.read_text(encoding="utf-8")) if choices_file.exists() else {}
check(typed and typed[0][0] == "Rename snapshot", f"rename asks with the app's own dialog: {typed}")
check(saved.get(snap0.id, {}).get("label") == "Before the holiday", f"the new name is saved in snapshots.json: {saved}")
if choices_file.exists():
    choices_file.unlink()
d = phone.ui.TextDialog(win, "Rename snapshot", "A name:", initial="x")
root.update()
check(d.entry.get() == "x" and d.winfo_exists(), "the text dialog opens with the current name")
d._cancel()
check(d.result is None, "Cancel gives None")

# every transfer shows progress and a realistic time left (01-principles.md, 6a)
import ui as _ui2
e = _ui2.Eta(settle=0.0)
first = e.feed(1.0)
check(first.endswith("working out time left…"), f"no estimate from the first second: {first!r}")
e.points[0] = (e.points[0][0] - 60, e.points[0][1])          # a minute ago we were at 1%
t = e.feed(21.0)
check(t.startswith("21%") and "about 4 min left" in t, f"20% in a minute → about 4 min left: {t!r}")
check(_ui2.Eta.fmt(30) == "under 2 min left" and _ui2.Eta.fmt(2 * 3600 + 5 * 60) == "about 2 h 05 min left", "wording")
check(e.feed(100) == "100%", "done")

win.close()
root.update()
check(("close",) in win.live.calls, "closing the window disconnects the simulated iPhone")
root.destroy()

print("\nPHONE WINDOW TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
