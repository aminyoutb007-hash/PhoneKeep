"""Real-iPhone check: drives PhoneKeep's own phone window against the iPhone on the cable, the way a person would,
and prints a pass/fail list with counts only (no names, no message text, no photos).

    .venv/bin/python tools/real_check.py

What it does, all read-only for the phone:
  * opens the phone window for the iPhone on the cable and its latest backup (password from the keychain);
  * opens every app screen and looks for an error;
  * Photos: counts, scrolls to the end of the biggest collection, previews a photo and a video (Space);
  * saves 3 photos as JPG into a temporary folder and checks each keeps its date and location;
  * Stability (H4): the crash reports of the last 30 days read twice into the temporary folder: all still on the
    phone after the first read;
  * Security (H5): the security checks' reads (profiles, apps, version, jailbreak signs), into the temporary folder;
    the phone-write gate's log stays unchanged;
  * Photo clean-up (C1): the six cards from the phone's photos, twice (the second visit from the cache), nothing
    offered that's a favourite, in an album, hidden or only in iCloud; 3 of them saved and checked by checksum
    (its cache and record go to the temporary folder too, not next to the real backups);
  * All files: previews a PDF from the backup; Voice Memos / Music: copies one to play;
  * Save everything: notes and calls of the last 30 days, and checks the contents page; D9: the last 30 days
    mentioning "invoice" saves exactly the matching messages, notes and files (worked out from the backup on its own).
Everything it saves goes to a temporary folder that is deleted at the end. Nothing is written to the phone,
and PhoneKeep's own folder and settings aren't changed.
"""
from __future__ import annotations

import csv
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
win.crashes_read = True     # the check-up reads crash reports into the phone's real folder: the H4 step reads them
                            # into the temporary folder instead
try:
    # -- 5.1.3: filled in fast (all but the app list), and the app list in two passes ---------------------------
    t_open = time.time()
    pump(app, lambda: win.overview is not None and win.wall_img is not None, 60)
    filled = time.time() - t_open
    check(win.overview is not None and win.wall_img is not None and filled < 5,
          f"the window fills in (details, battery, storage, wallpaper) without the app list ({filled:.1f} s)")
    import overview_ui
    t_apps = time.time()
    overview_ui.storage_view(win, win.overview)
    pump(app, lambda: win._apps_list is not None or not win._apps_state, 30)
    names_s = time.time() - t_apps
    pump(app, lambda: win._apps_state != "loading", 300)
    check(win._apps_list and names_s < 3 and win._apps_state == "done" and all(x.sized for x in win.overview.apps),
          f"Storage: the app names first ({names_s:.1f} s), then every size ({time.time() - t_apps:.0f} s)")
    import phoneapps
    check(len(phoneapps.load_saved(win.udid)[0]) == len(win.overview.apps),
          "the app list with sizes is saved for next time (in the temporary folder here)")
    # 5.1.3: the storage question on its own (the second try when the overview's one timed out), read-only
    t_st = time.time()
    disk = wv.storage_values(win.udid)
    check(disk and disk.get("TotalDataAvailable") is not None and win.storage_state == "" and win.overview.free is not None,
          f"storage answers on its own within its limit ({time.time() - t_st:.1f} s), and the card isn't waiting")
    win.show_home()

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
        errs = [e for e in red(win) if "nothing" not in e.lower() and "in this backup" not in e
                and not e.startswith("No ")]          # "no data of this kind" is an answer, not an error
        check(done and not errs, f"{label} opens ({time.time() - t:.0f} s)" + (f": {errs[0][:120]}" if errs else ""))

    # -- H1: the check-up ------------------------------------------------------------------------------------
    pump(app, lambda: win.overview is not None or win.overview_problem, 120)
    win.open_app("checkup")
    r = getattr(win, "checkup_report", None)
    check(r is not None and len(getattr(win, "checkup_cards", {})) == 4 and getattr(win, "checkup_ms", 1e9) < 1000,
          f"the check-up shows four cards in under 1 second ({getattr(win, 'checkup_ms', 0):.0f} ms)")
    if r is not None:
        note(f"{r.as_of()}: " + ", ".join(f"{c.title} {c.level}" for c in r.cards) + f"; {r.summary()}")
        # H2: the Storage details, with the suggestions worked out from the backup and the phone
        import checkup, checkup_ui
        checkup_ui.details(win, "storage")
        pump(app, lambda: getattr(win, "storage_suggestions", None) is not None, 600)
        sg = getattr(win, "storage_suggestions", None)
        check(sg is not None and all(s.size >= 500 * 1000 ** 2                 # C1's own say "Review them in Photo clean-up"
                                     and s.steps.startswith(("On the iPhone: ", "Review them in Photo clean-up")) for s in sg)
              and [s.size for s in sg] == sorted((s.size for s in sg), reverse=True),
              "Storage details: suggestions largest first, each 500 MB or more with steps on the phone or in Photo clean-up")
        note(f"{len(sg or [])} suggestions: " + ", ".join(s.key for s in sg or [])
             + ("; a forecast is shown" if getattr(win, "storage_forecast", None) else "; no forecast (needs 4+ backups)"))
        # H3: the Battery details, with one point per recorded backup and tips for this model
        checkup_ui.details(win, "battery")
        app.update()
        hist = [e for e in checkup.load(checkup_ui.phone_dir(win))["history"] if e.get("health") is not None]
        check(getattr(win, "battery_today", "").startswith("Today: ") and len(getattr(win, "battery_points", [])) == len(hist)
              and getattr(win, "battery_tips", None),
              "Battery details: today's figures from the phone, one point per recorded backup, tips for this model")
        note(f"{len(hist)} backups recorded so far; " + ("chart shown" if getattr(win, "battery_chart", None) else
                                                         "chart waits for a second backup"))

    # -- H4: the phone's crash reports, read-only --------------------------------------------------------------
    import crashes as cr
    import subprocess as sp

    def pk_crashes(folder):
        out = sp.run(wv._launcher_cmd() + ["--pk-crashes", str(folder), "--days", "30", "--udid", win.udid],
                     capture_output=True, text=True, timeout=300).stdout.splitlines()
        done = next((int(l.split()[1]) for l in out if l.startswith("PKDONE")), None)
        return done, sum(l.startswith("PKCRASH") for l in out)
    cdir = WORK / "h4" / cr.FOLDER
    n1, copied1 = pk_crashes(cdir)
    n2, copied2 = pk_crashes(cdir)
    check(n1 is not None and n2 is not None and n2 >= n1 and copied2 <= n2 - n1 and copied1 == n1,
          "Stability: the crash reports are read, and after the check they're all still on the phone")
    ev = cr.read_folder(cdir)
    c7, r7 = cr.counts(cr.summary(ev, dt.datetime.now()), 7)
    note(f"{n1} reports in 30 days; this week {sum(c7.values())} app crashes in {len(c7)} apps, {r7} unexpected restarts")

    # -- H5: the security checks, read-only ---------------------------------------------------------------------
    import activity, checkup as cku5, phone_write, security as sx
    log_before = activity.ACTIVITY_FILE.read_text() if activity.ACTIVITY_FILE.exists() else ""
    raw = wv.read_security(win.udid, WORK / "h5", timeout=60)
    cs = cku5.security_checks(cku5.load(WORK / "h5")) if raw else []
    log_after = activity.ACTIVITY_FILE.read_text() if activity.ACTIVITY_FILE.exists() else ""
    check(raw is not None and not raw.get("problems") and len(cs) == 6 and log_after == log_before,
          "Security: every check's read works, and the phone-write gate's log is unchanged")
    note("; ".join(f"{c.key} {c.state}" for c in cs) + f"; locked at this read: {raw.get('password_protected') if raw else None}")

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
            # 5.1.3, read-only and without unplugging: the watcher finds this iPhone by its UDID, and a dropped
            # connection (stood in for) reconnects to the same iPhone and the read works
            import reconnect as rc
            pump(app, lambda: False, 2 * phone.WATCH_MS / 1000 + 1)
            check(rc.where(win.udid) == "USB" and win.phone_here and win.sub.cget("text").endswith("connected by USB cable"),
                  "the iPhone on the cable is found by its UDID and the header says so")
            (src.cache / "full" / photo.id).unlink(missing_ok=True)
            gen, src.afc = src.generation, rc.NotConnected()
            data = src.read(photo.id)
            gen_l, win.live.lockdown = win.live.generation, rc.NotConnected()
            apps_back = win.live.apps()
            check(bool(data) and src.generation == gen + 1 and src.udid == win.udid and apps_back
                  and win.live.generation == gen_l + 1 and win.live.udid == win.udid,
                  "a dropped connection reconnects to the same iPhone by itself: the photo and the app list read again")
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

        # -- C1: Photo clean-up --------------------------------------------------------------------------------
        import checkup_ui as cku, cleanup as cl, cleanup_ui
        real_dir = cku.phone_dir
        cku.phone_dir = lambda w: WORK / "c1"                 # its cache and record: in the temporary folder
        try:
            t = time.time()
            cleanup_ui.view(win, src, items)
            pump(app, lambda: win.current == "cleanup", 3600)
            first = time.time() - t
            r = getattr(win, "cleanup_result", None)
            looked = sum(1 for i in items if not i.hidden and not i.cloud_only)   # iCloud-only ones aren't read
            per = first / max(1, looked)
            check(r is not None and per * 10_000 < 300,
                  f"Photo clean-up: {looked:,} photos on the phone looked at in {first:.0f} s (10,000 would take "
                  f"about {per * 10_000 / 60:.1f} min; under 5 min needed)")
            if r is not None:
                note(", ".join(f"{c.title} {c.count}" for c in r.cards) + f"; left out {r.left_out}; iCloud Photos "
                     + {True: "on", None: "not known"}.get(r.icloud, "off"))
                lib = src.library()
                xs = [i for i in items if not i.hidden and not i.cloud_only]
                note(f"library: knows the saving app {bool(getattr(lib, 'knows_app', False))}, "
                     f"{sum(bool(i.saved_by) for i in xs)} saved by an app, {sum(i.screen_recording for i in xs)} screen "
                     f"recordings, {sum(bool(i.burst) for i in xs)} in bursts, {sum(i.edited for i in xs)} edited")
                offered = [i for c in r.cards for i in c.candidates()]
                check(not any(i.favorite or i.albums or i.hidden or i.cloud_only for i in offered),
                      "nothing offered is a favourite, in an album, hidden or only in iCloud")
                t = time.time()
                cleanup_ui.view(win, src, items)
                pump(app, lambda: win.current == "cleanup", 60)
                second = time.time() - t
                check(win.cleanup_result.measured == 0 and second < 2,
                      f"a second visit opens in under 2 seconds ({second:.2f} s)")
                pick = sorted({i.id: i for i in offered}.values(), key=lambda i: i.size or 0)[:3]
                if pick:
                    res = cl.save(src, pick, WORK / "c1-archive", WORK / "c1")
                    rec = cl.load(WORK / "c1")
                    check(len(res.verified) == len(pick) and all(cl.in_archive(rec["saved"][i.id]) for i in pick),
                          f"saved {len(res.verified)} of {len(pick)}, each in the archive with a matching checksum")
                else:
                    note("nothing to offer, so nothing to save")
        finally:
            cku.phone_dir = real_dir

    # -- All files: a PDF from the backup ---------------------------------------------------------------------
    if win.data is not None:
        pdf = None
        for domain, rel, fid in win.data.reader.db.execute(
                "SELECT domain, relativePath, fileID FROM Files WHERE flags = 1 AND lower(relativePath) LIKE '%.pdf' LIMIT 1"):
            pdf = (domain, rel)
        if pdf:
            v = viewer_shows(app, [quicklook.Item(Path(pdf[1]).name, read=lambda: win.data.read(*pdf),
                                                  to_file=lambda d: win.data.copy(pdf[0], pdf[1], d),
                                                  why=lambda: getattr(win.data.reader, "last_error", None))], 0)
            want = "pdf" if sys.platform == "darwin" else "play"
            why = " ".join(l.cget("text") for l in labels(v.body)) if v.shown_kind == "error" else ""
            check(v.shown_kind == want, f"Space on a PDF from the backup shows its pages ({v.shown_kind})"
                  + (f": {why[:200]}" if why else ""))
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

    # -- D9: "Last 30 days, mentioning invoice" keeps only matching messages, notes and files ----------------------
    # Saved into this check's own temporary folder (removed at the end). What should be kept is worked out here on
    # its own, straight from the backup, and compared with what was saved; only pass/fail and counts are printed.
    # A kind counts as tested only when, in that run, the word matches items inside the 30 days AND outside them
    # (so the range is shown to cut) and items inside the 30 days don't mention it (so the search is shown to cut).
    import sections as sx
    ctx = sx.Ctx(win.data.reader, WORK / "d9-read", lambda m: None, False, {})
    try:
        sx.load_contacts(ctx)                      # chat names and senders as the app shows them (export_all does too)
    except Exception:
        pass

    def day(when):
        if isinstance(when, (int, float)):
            return dt.datetime.fromtimestamp(when).date()
        if isinstance(when, dt.datetime):
            return when.date()
        try:
            return dt.date.fromisoformat(str(when)[:10]) if when else None
        except ValueError:
            return None
    items = {}                                     # kind -> [(day, [texts the search looks at])]
    try:
        items["messages"] = [(day(m.get("time")), [c.get("name")] + [v for k, v in m.items() if isinstance(v, str)
                              and k not in ("time", "type", "media_rel", "media")])
                             for c in sx.load_messages(ctx) for m in c["messages"]]
    except wv.PhoneKeepError:
        items["messages"] = []
    try:
        items["notes"] = [(day(n["modified"]), [n["title"], n["text"], n["folder"]]) for n in sx.load_notes(ctx)]
    except wv.PhoneKeepError:
        items["notes"] = []
    items["files"] = [(day(win.data.reader.file_mtime(fid)), [dom + "/" + rel]) for dom, rel, fid in
                      win.data.reader.db.execute("SELECT domain, relativePath, fileID FROM Files WHERE flags=1")]

    def tally(kind, word, lo, hi):
        """(kept, matching outside the dates, not matching inside the dates)"""
        kept = outside = other = 0
        for d, texts in items[kind]:
            hit = any(word in str(t).casefold() for t in texts if t)
            inside = d is not None and lo <= d <= hi
            kept += hit and inside
            outside += hit and not inside
            other += inside and not hit
        return kept, outside, other
    tested, runs = set(), [0]

    def d9(word, kinds, lo, hi):
        runs[0] += 1
        dest = WORK / f"everything-{runs[0]}"
        win.last_save_all = None
        win.bar_text.configure(text="")            # a "Couldn't" left by an earlier run mustn't end this wait
        win.save_everything({"sections": kinds, "dates": (lo, hi), "search": word, "formats": {"web", "csv"}}, dest)
        pump(app, lambda: win.last_save_all is not None or "Couldn't" in win.bar_text.cget("text"), 900)
        saved = {}
        try:
            saved = json.loads((dest / "assets" / "sections.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        t = {k: tally(k, word, lo, hi) for k in kinds}
        want = {k: t[k][0] for k in kinds}
        got = {k: (saved.get(k) or {}).get("count", -1) for k in kinds}
        hub = dest / "index.html"
        check(hub.exists() and "mentioning" in hub.read_text(encoding="utf-8") and got == want,
              f"Save everything, {lo} to {hi} mentioning '{word}': saves exactly the matching {', '.join(kinds)}"
              f" (saved {got}, worked out from the backup {want})")
        if "files" in kinds:
            stray = [p for p in (dest / "All files").rglob("*") if p.is_file() and p.name != "README.txt"
                     and word not in p.relative_to(dest / "All files").as_posix().casefold()]
            check(not stray, f"  every saved file mentions '{word}' in its name or folder ({len(stray)} don't)")
        if "messages" in kinds:
            every = dest / "Messages" / "CSV" / "_All chats.csv"
            rows = []
            if every.exists():
                with every.open(encoding="utf-8-sig") as f:
                    rows = list(csv.reader(f))[1:]
            off = sum(1 for r in rows if not (len(r) > 4 and (d := day(r[1])) and lo <= d <= hi
                                              and any(word in x.casefold() for x in (r[0], r[3], r[4]))))
            check(len(rows) == want["messages"] and not off,
                  f"  every saved message is from those dates and mentions it, or is in a chat whose name does"
                  f" ({off} of {len(rows)} don't)")
        for k in kinds:
            if all(t[k]) and got == want:
                tested.add(k)
            note(f"  {k}: kept {t[k][0]}, left out by the dates {t[k][1]}, left out by the word {t[k][2]}")

    d9("invoice", ["messages", "notes", "files"], today - dt.timedelta(days=29), today)
    # a kind the literal run couldn't test (too little recent): the 30 days with the most of that kind in the
    # backup, with the first common word that matches inside and outside those days (and not everything inside)
    words = {"messages": ("the", "and", "you", "de", "la", "a"), "notes": ("the", "and", "de", "la", "a"),
             "files": ("invoice", "receipt", "photo", "document", "media", "cache")}
    for kind in ("messages", "notes", "files"):
        if kind in tested:
            continue
        dates = sorted(d for d, _t in items[kind] if d)
        if not dates:
            note(f"D9: no dated {kind} in this backup to test with")
            continue
        first, busiest = 0, (0, dates[0])            # (how many, last day) of the fullest 30 days
        for i, d in enumerate(dates):
            while dates[first] < d - dt.timedelta(days=29):
                first += 1
            busiest = max(busiest, (i - first + 1, d))
        hi = busiest[1]
        lo = hi - dt.timedelta(days=29)
        word = next((w for w in words[kind] if all(tally(kind, w, lo, hi)) and tally(kind, w, lo, hi)[0] <= 300), None)
        if word is None:
            note(f"D9: no common word cuts both ways in the fullest 30 days of {kind}; not tested on real data")
            continue
        d9(word, [kind], lo, hi)
    check(tested == {"messages", "notes", "files"},
          f"D9 on real data: the dates and the word both left things out, for {', '.join(sorted(tested)) or 'nothing'}")
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
