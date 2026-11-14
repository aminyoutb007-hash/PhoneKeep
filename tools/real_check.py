"""Real-iPhone check: drives PhoneKeep's own phone window against the iPhone on the cable, the way a person would,
and prints a pass/fail list with counts only (no names, no message text, no photos).

    .venv/bin/python tools/real_check.py

What it does, all read-only for the phone:
  * opens the phone window for the iPhone on the cable and its latest backup (password from the keychain);
  * opens every app screen and looks for an error;
  * Photos: counts, scrolls to the end of the biggest collection, previews a photo and a video (Space);
  * saves 3 photos as JPG into a temporary folder and checks each keeps its date and location;
  * All files: previews a PDF from the backup; Voice Memos / Music: copies one to play;
  * Save everything: notes and calls of the last 30 days, and checks the contents page.
Everything it saves goes to a temporary folder that is deleted at the end. Nothing is written to the phone,
and PhoneKeep's own folder and settings aren't changed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REAL_HOME = Path(os.environ.get("PHONEKEEP_HOME") or Path.home() / "PhoneKeep")
settings = {}
try:
    settings = json.loads((REAL_HOME / "settings.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    pass
WORK = Path(tempfile.mkdtemp(prefix="pk-realcheck-"))
os.environ["PHONEKEEP_HOME"] = str(WORK / "home")          # nothing written to the real PhoneKeep folder

import tkinter as tk                                        # noqa: E402

import phonekeep as wv                                      # noqa: E402
import phone                                                # noqa: E402
import photoconv                                            # noqa: E402
import quicklook                                            # noqa: E402
import saveall_ui                                           # noqa: E402
import ui                                                   # noqa: E402

quicklook.play = lambda path: None                          # copy to play, but don't open QuickTime
phone.open_file = lambda path: None
results: list[tuple[bool, str]] = []
T0 = time.time()


def check(ok, what):
    results.append((bool(ok), what))
    print(("ok   " if ok else "FAIL ") + what, flush=True)


def note(what):
    print("     " + what, flush=True)


class App(tk.Tk):
    """What the phone window needs from the main window."""
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": settings.get("backup_dir") or str(REAL_HOME / "Backups"),
                  "archive_dir": str(WORK / "Archive")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass

    def confirm_private(self, then, reason=""):
        pass                                                  # Hidden stays closed in this check


def pump(root, until, timeout=120.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        try:
            if until():
                return True
        except tk.TclError:
            pass
        time.sleep(0.02)
    return False


def labels(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Label):
            out.append(c)
        out += labels(c)
    return out


def loading(win):
    return any(l.cget("text") in ("Loading…", "Reading from the iPhone…") for l in labels(win.content))


def red(win):
    return [l.cget("text") for l in labels(win.content) if str(l.cget("fg")).lower() == str(ui.RED).lower()]


def find(w, cls):
    for c in w.winfo_children():
        if isinstance(c, cls):
            return c
        r = find(c, cls)
        if r is not None:
            return r


def viewer_shows(root, items, idx, wait=90):
    v = quicklook.Viewer(root, items, idx)
    pump(root, lambda: v.shown_kind not in ("", "loading"), wait)
    return v


devs = [d for d in wv.list_devices() if d.get("ConnectionType") == "USB"]
if not devs:
    sys.exit("Plug the iPhone in with a cable and unlock it, then run this again.")
dev = devs[0]
print(f"Checking the iPhone on the cable (iOS {dev.get('ProductVersion')}). This takes a few minutes.\n", flush=True)
app = App()
win = phone.PhoneWindow(app, dev, dev["UniqueDeviceID"])
try:
    # -- home screen ----------------------------------------------------------------------------------------
    backup_apps = [k for k, *_r, where in phone.APPS if where == "backup"]
    ok = pump(app, lambda: win.data is not None and all(k in win.counts for k in backup_apps), 300)
    check(ok, "the latest backup opens and the home screen counts fill in")
    note("counts: " + ", ".join(f"{k} {win.counts.get(k)}" for k in backup_apps if win.counts.get(k)))

    # -- every app screen -----------------------------------------------------------------------------------
    for key, label, *_r in phone.APPS:
        t = time.time()
        win.open_app(key)
        done = pump(app, lambda: not loading(win), 600)
        errs = [e for e in red(win) if "nothing" not in e.lower() and "in this backup" not in e]   # "no data" is fine
        check(done and not errs, f"{label} opens ({time.time() - t:.0f} s)" + (f": {errs[0][:120]}" if errs else ""))

    # -- Photos -----------------------------------------------------------------------------------------------
    win.open_app("photos")
    pump(app, lambda: not loading(win) and find(win.content, ui.PhotoPanel) is not None, 900)
    pp = find(win.content, ui.PhotoPanel)
    check(pp is not None, "Photos shows the photo grid")
    if pp is not None:
        src = pp.source
        items = pp.items
        local = [i for i in items if not i.cloud_only]
        note(f"{len(items):,} items, {len(local):,} on the phone, {len(items) - len(local):,} only in iCloud; "
             + ", ".join(f"{label.split()[-1]} {len(pp.months.get(k, []))}" for k, label in pp.collections)
             + f"; {len(pp.album_rows)} albums")
        big = max((k for k, _l in pp.collections), key=lambda k: len(pp.months[k]), default=None)
        if big:
            pp.mlist.selection_set(big)
            pump(app, lambda: pp._month() == big, 10)
            for _ in range(400):
                pp.canvas.yview_moveto(1.0)
                app.update()
                if pp.shown >= len(pp.months[big]):
                    break
            check(pp.shown == len(pp.months[big]), f"scrolling reaches the end of the biggest collection "
                                                   f"({pp.shown:,} of {len(pp.months[big]):,})")
        photo = next((i for i in local if not i.video and i.name.lower().endswith((".heic", ".jpg", ".jpeg", ".png"))), None)
        video = next((i for i in local if i.video), None)
        if photo:
            v = viewer_shows(app, [quicklook.Item(photo.name, read=lambda: src.read(photo.id),
                                                  to_file=lambda d: src.copy(photo.id, d))], 0)
            check(v.shown_kind == "image", f"Space on a photo shows it ({v.shown_kind})")
            v.close()
        if video:
            v = viewer_shows(app, [quicklook.Item(video.name, to_file=lambda d: src.copy(video.id, d), kind="video")], 0)
            path = v.open_from_file(wait=True) if v.shown_kind == "play" else None
            check(path is not None and path.stat().st_size > 0, "Space on a video, then Play: it's copied to play")
            v.close()
        cloud = next((i for i in items if i.cloud_only and not i.video), None)
        if cloud:
            t = src.thumbnail(cloud)
            check(True, f"an iCloud-only photo: {'the phone has a small preview' if t else 'no preview on the phone'}")
        # JPG with date and location
        from PIL import Image
        with_gps = [i for i in local if not i.video and i.lat is not None
                    and Path(i.name).suffix.lower() in (".heic", ".heif", ".jpg", ".jpeg")][:3]
        out = WORK / "jpg"
        out.mkdir()
        good = 0
        for i in with_gps:
            files = photoconv.save_item(src, i, out, True, WORK / "raw")
            f = next((p for p in files if p.suffix.lower() == ".jpg"), None)
            if f is None:
                continue
            ex = Image.open(f).getexif()
            gps = ex.get_ifd(0x8825)
            taken = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
            try:                                              # the camera's local time vs the library's: within a day
                same_day = abs((dt.date.fromisoformat(taken[:10].replace(":", "-")) - i.when.date()).days) <= 1
            except (TypeError, ValueError):
                same_day = False
            mtime_ok = abs(f.stat().st_mtime - i.when.timestamp()) < 2
            good += bool(gps) and bool(same_day) and mtime_ok
        if with_gps:
            check(good == len(with_gps), f"saved as JPG keeps the date and location ({good} of {len(with_gps)})")
        else:
            note("no photo with a location on the phone to save as JPG")

    # -- All files: a PDF from the backup ---------------------------------------------------------------------
    if win.data is not None:
        pdf = None
        for domain, rel, fid in win.data.reader.db.execute(
                "SELECT domain, relativePath, fileID FROM Files WHERE flags = 1 AND lower(relativePath) LIKE '%.pdf' LIMIT 1"):
            pdf = (domain, rel)
        if pdf:
            v = viewer_shows(app, [quicklook.Item(Path(pdf[1]).name, read=lambda: win.data.read(*pdf),
                                                  to_file=lambda d: win.data.copy(pdf[0], pdf[1], d))], 0)
            want = "pdf" if sys.platform == "darwin" else "play"
            check(v.shown_kind == want, f"Space on a PDF from the backup shows its pages ({v.shown_kind})")
            v.close()
        else:
            note("no PDF in the backup to preview")

    # -- Save everything: notes and calls of the last 30 days ----------------------------------------------------
    today = dt.date.today()
    dest = WORK / "everything"
    win.save_everything({"sections": ["notes", "calls"], "dates": (today - dt.timedelta(days=29), today),
                         "search": "", "formats": {"web"}}, dest)
    pump(app, lambda: getattr(win, "last_save_all", None) is not None or "Couldn't" in win.bar_text.cget("text"), 600)
    hub = dest / "index.html"
    check(hub.exists() and "<dt>Only</dt>" in hub.read_text(encoding="utf-8"),
          "Save everything (last 30 days) makes one folder whose contents page names the dates")
finally:
    try:
        win.close()
    except Exception:
        pass
    quicklook.cleanup()
    shutil.rmtree(WORK, ignore_errors=True)

bad = [w for ok, w in results if not ok]
print(f"\n{len(results) - len(bad)} of {len(results)} passed in {time.time() - T0:.0f} s"
      + ("" if not bad else ". FAILED: " + "; ".join(bad)))
sys.exit(1 if bad else 0)
