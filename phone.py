"""
PhoneKeep - the phone window: your iPhone's apps on your computer.

Click the iPhone in the main window and this opens: a picture of the phone with its own
wallpaper, and a home screen of app icons. Click an icon to browse what is in that app,
preview it, and save what you want.

Where the data comes from:
  * Photos, Music, Books, App Files and the wallpaper are read live from the iPhone;
  * Messages, WhatsApp, WhatsApp Business, Calls, Contacts, Notes, Voicemail, Voice Memos,
    Call Recordings, Calendar and Safari can only be read from a backup (Apple doesn't let apps read them
    any other way), so they come from the latest PhoneKeep backup. "Refresh from iPhone"
    makes a quick incremental backup to bring them up to date.
"""
from __future__ import annotations

import datetime as dt
import gc
import io
import os
import queue
import shutil
import subprocess
import sys
import time
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

import activity
import checkup_ui
import keychain
import deviceinfo as di
import overview_ui
import storage_map
import phoneapps
import protect
import protect_ui
import quicklook
import reconnect
import saveall_ui
import phonekeep as wv
import snapshots as sn
import tamper
import sections as sx
import theme
import ui
from ui import BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, RoundButton, card, font

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:  # Pillow missing: no wallpaper picture
    Image = None

# key, label, icon, tile colour, where the data lives
APPS = [
    ("photos", "Photos", "🌻", theme.APP_TILE["photos"], "live"),
    ("messages", "Messages", "💬", theme.APP_TILE["messages"], "backup"),
    ("whatsapp", "WhatsApp", "💬", theme.APP_TILE["whatsapp"], "backup"),
    ("whatsappbusiness", "WhatsApp Business", "💼", theme.APP_TILE["whatsappbusiness"], "backup"),
    ("calls", "Call History", "📞", theme.APP_TILE["calls"], "backup"),
    ("contacts", "Contacts", "👤", theme.APP_TILE["contacts"], "backup"),
    ("voicemail", "Voicemail", "📼", theme.APP_TILE["voicemail"], "backup"),
    ("notes", "Notes", "📝", theme.APP_TILE["notes"], "backup"),
    ("calendar", "Calendar", "📅", theme.APP_TILE["calendar"], "backup"),
    ("voicememos", "Voice Memos", "🎙", theme.APP_TILE["voicememos"], "backup"),
    ("callrecordings", "Call Recordings", "📞", theme.APP_TILE["callrecordings"], "backup"),   # D6
    ("safari", "Safari", "🧭", theme.APP_TILE["safari"], "backup"),
    ("music", "Music", "🎵", theme.APP_TILE["music"], "live"),
    ("books", "Books", "📚", theme.APP_TILE["books"], "live"),
    ("files", "App Files", "📁", theme.APP_TILE["files"], "live"),
    ("apps", "Apps", "📱", theme.APP_TILE["apps"], "backup"),
    ("allfiles", "All files", "🗂", theme.APP_TILE["allfiles"], "backup"),
    ("checkup", "Check-up", "🩺", theme.APP_TILE["checkup"], "checkup"),      # H1: from the phone, or as of the last backup
]
LABEL = {k: l for k, l, *_ in APPS}
ICON_DIR = ui.ICON_DIR
app_icon = ui.app_icon              # PhoneKeep's drawn icons (tools/make_app_icons.py)
CHAT_APPS = ("messages", "whatsapp", "whatsappbusiness")


def open_file(path: Path) -> None:
    """Open a file with the computer's default app (Photos/Preview, QuickTime, Books...)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror(wv.APP_NAME, f"Couldn't open {path.name}: {e}")


def reveal(path: Path) -> None:
    path = Path(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(path)] if path.is_file() else ["explorer", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
    except Exception:
        pass


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    k = 2
    while True:
        q = p.with_name(f"{p.stem} ({k}){p.suffix}")
        if not q.exists():
            return q
        k += 1


LIVE_KEYS = {"photos", "music", "books", "files"}     # the sections read live from the iPhone
WATCH_MS = 3000                                       # how often to ask whether the iPhone is still there (5.1.3)
STORAGE_TICK_MS = 3000          # 5.1.3: while the storage question has no answer, how often to look for a sign of life
STORAGE_AGAIN_S = 60            # ... and ask again anyway after this long (iOS doesn't say when it's unlocked)


class Runner:
    """One background thread; results come back on the UI thread. Errors go to on_err."""

    def __init__(self, widget: tk.Misc):
        self.widget = widget
        self.jobs: queue.Queue = queue.Queue()
        self.done: queue.Queue = queue.Queue()
        self.alive = True
        threading.Thread(target=self._run, daemon=True).start()
        self._poll()

    def submit(self, fn: Callable, ok: Callable = None, err: Callable = None):
        self.jobs.put((fn, ok, err))

    def on_ui(self, fn: Callable):
        """Run fn on the UI thread soon (safe to call from the worker: progress updates and the like)."""
        self.done.put((lambda _r: fn(), None, None, None))

    def stop(self):
        self.alive = False
        self.jobs.put(None)

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            fn, ok, err = job
            try:
                res, exc = fn(), None
            except Exception as e:  # noqa: BLE001 - shown to the user
                res, exc = None, e
            self.done.put((ok, err, res, exc))

    def _poll(self):
        if not self.alive:
            return
        try:
            while True:
                ok, err, res, exc = self.done.get_nowait()
                try:
                    if exc is None:
                        ok and ok(res)
                    elif err:
                        err(exc)
                except tk.TclError:
                    pass  # the view was closed meanwhile
        except queue.Empty:
            pass
        try:
            self.widget.after(80, self._poll)
        except tk.TclError:
            pass


def describe_error(e: Exception) -> str:
    """The one-sentence message for an error (E3): PhoneKeep's own are already plain; anything else goes
    through the errors table. Never a raw exception."""
    import errors
    if isinstance(e, wv.PhoneKeepError):
        return str(e)
    return errors.explain(e).message


# ---------------------------------------------------------------------------
# the backup side: everything read from the latest backup, loaded on demand and cached
# ---------------------------------------------------------------------------

class BackupData:
    def __init__(self, path: Path, password: Optional[str], log=lambda m: None):
        self.path = Path(path)
        self.password = password
        self.info = wv.backup_info(self.path)
        self.reader = wv.BackupReader(self.path, password, log)
        tmp = Path(self.reader._tmp.name)
        self.ctx = sx.Ctx(self.reader, tmp / "out", log, True, self.info)
        self.lock = threading.Lock()
        self.closed = threading.Event()     # set once the backup's files have been let go
        self._closing = False
        self._photos_lock = threading.Lock()   # one photo list at a time: they'd share library/Photos.sqlite
        # chat thumbnails, the large view and Save all (M6) read under the same lock, never a closed backup
        self.preview = sx.ChatPreview(self.ctx, self.lock, lambda: self._closing)
        self.contacts = []
        try:
            self.contacts = sx.load_contacts(self.ctx)   # also gives names to calls & chats
        except Exception:
            pass
        self.cache: dict = {}

    def get(self, key: str):
        if key == "photos":
            return self._photos()
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            if self._closing:
                raise wv.PhoneKeepError("This backup was closed.")
            c = self.ctx
            if key == "messages":
                v = sx.load_messages(c)
                c.cache["messages"] = v
            elif key in ("whatsapp", "whatsappbusiness"):
                v = wv.load_whatsapp(self.reader, key == "whatsappbusiness", True, c.name_for, lambda m: None)
                c.cache[key] = v
            elif key == "contacts":
                if not self.contacts:
                    raise wv.PhoneKeepError("No contacts in this backup.")
                try:
                    sx.load_contact_photos(c, self.contacts)     # D1: read once, when Contacts is first opened
                except Exception:
                    pass                                         # the list without photos
                v = self.contacts
            elif key == "calls":
                v = sx.load_calls(c)
            elif key == "notes":
                v = sx.load_notes(c)
            elif key == "calendar":
                v = sx.load_calendar(c)
            elif key == "voicemail":
                v = sx.load_voicemail(c)
            elif key == "voicememos":
                v = sx.load_voicememos(c)
            elif key == "callrecordings":
                v = sx.load_call_recordings(c)
            elif key == "safari":
                v = sx.load_safari(c)
            elif key == "apps":                 # with each app's file count, read here under the lock, in one query
                n = dict(self.reader.db.execute("SELECT domain, COUNT(*) FROM Files WHERE flags=1 "
                                                "AND domain LIKE 'AppDomain-%' GROUP BY domain"))
                v = [(a, n.get("AppDomain-" + a, 0)) for a in sx.load_apps(c)]
            elif key == "allfiles":
                v = self.reader.domains()
            else:
                raise wv.PhoneKeepError("Not in backups.")
            self.cache[key] = v
            return v

    def _photos(self):
        """The backup's photos: (source, items). The source reads the backup under this lock and never once it's
        closed; its list is made outside the lock, since making it reads the Photos library through that lock.
        A second caller waits for the first one's list instead of copying the library into the same folder."""
        import photos as ph
        with self._photos_lock:
            with self.lock:
                if "photos" in self.cache:
                    return self.cache["photos"]
                if self._closing:
                    raise wv.PhoneKeepError("This backup was closed.")
                src = ph.BackupPhotoSource(self.reader, Path(self.reader._tmp.name) / "photos", self.lock,
                                           lambda: self._closing)
            items = src.items()
            with self.lock:
                return self.cache.setdefault("photos", (src, items))

    def count(self, key: str) -> str:
        if key == "contacts":                     # the photos wait until Contacts is opened
            if not self.contacts:
                raise wv.PhoneKeepError("No contacts in this backup.")
            return f"{len(self.contacts):,}"
        v = self.get(key)
        if key in CHAT_APPS:
            chats = v if key == "messages" else v["chats"]
            return f"{len(chats):,} chat{'s' if len(chats) != 1 else ''}"
        if key == "safari":
            return f"{len(v[0]) + len(v[1]):,}"
        if key == "photos":
            return f"{len(v[1]):,}"
        if key == "allfiles":
            with self.lock:
                if self._closing:
                    raise wv.PhoneKeepError("This backup was closed.")
                n = self.reader.db.execute("SELECT COUNT(*) FROM Files WHERE flags=1").fetchone()[0]
            return f"{n:,} file{'s' if n != 1 else ''}"
        return f"{len(v):,}"

    def copy(self, domain: str, rel: str, dest: Path) -> bool:
        with self.lock:
            return False if self._closing else self.ctx.copy(domain, rel, dest)

    def read(self, domain: str, rel: str) -> Optional[bytes]:
        with self.lock:
            return None if self._closing else self.ctx.read(domain, rel)

    def file_meta(self, domain: str, prefix: str = "") -> dict:
        """The backup's file list under a folder (as BackupReader.file_meta), under the lock."""
        with self.lock:
            if self._closing:
                raise wv.PhoneKeepError("This backup was closed.")
            return self.reader.file_meta(domain, prefix)

    def close(self):
        """Let go of the backup's files. A read still running (the home screen's counts) finishes first: closing
        the database under it crashed PhoneKeep (16 Nov). The window never waits: if a read is running, the
        closing happens in the background as soon as it ends; `closed` is set when it's done."""
        def shut(wait: bool) -> bool:
            if not self.lock.acquire(blocking=wait):
                return False
            try:
                self._closing = True
                try:
                    self.reader.close()
                except Exception:
                    pass
            finally:
                self.lock.release()
            self.closed.set()
            return True
        if not shut(False):
            threading.Thread(target=shut, args=(True,), daemon=True).start()


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

def ask_save_folder(parent, title: str, start: Path):
    """The folder dialog for a save (one place, so tests can stand in for it)."""
    return filedialog.askdirectory(parent=parent, title=title, initialdir=str(start), mustexist=True)


class PhoneWindow(tk.Toplevel):
    def __init__(self, app, device: dict, udid: Optional[str], backup: Optional[Path] = None):
        """A phone window: for a connected phone (device + udid), or for any backup folder (B5: `backup`),
        PhoneKeep's own or one made by Finder / iTunes, with no phone connected at all."""
        super().__init__(app, bg=BG)
        if hasattr(app, "attach_menu"):
            app.attach_menu(self)
        self.app = app
        self.device = device or {}
        self.opened_backup = Path(backup) if backup else None
        if self.opened_backup is not None and not udid:
            udid = self.opened_backup.name if len(self.opened_backup.name) >= 24 else None   # Finder/iTunes folders are named by UDID
            if sn.is_snapshot(self.opened_backup):
                udid = self.opened_backup.parent.parent.name
        self.udid = udid
        self.live_wanted = backup is None or bool(self.device)
        if self.opened_backup is not None and not self.device:
            self.device = {"DeviceName": wv.backup_info(self.opened_backup).get("name") or "iPhone"}
        self.name = self.device.get("DeviceName") or "iPhone"
        self.title(f"{self.name} — PhoneKeep")
        self.geometry("1220x800")
        self.minsize(980, 640)
        self.backup_dir = Path(app.s["backup_dir"])
        self.snapshot: Optional[sn.Snapshot] = None            # B3: which snapshot is open (None = latest)
        if self.opened_backup is not None and not sn.is_snapshot(self.opened_backup):
            self.backup_path = self.opened_backup                  # a Finder / iTunes / other folder
        else:
            self.backup_path = (self.opened_backup if self.opened_backup is not None
                                else sn.latest_backup_path(self.backup_dir, udid) if udid else None)
        self.out_root = Path(app.s["archive_dir"]) / "From iPhone"
        self.data: Optional[BackupData] = None
        self.data_error: Optional[str] = None
        self.live = None
        self.live_error: Optional[str] = None
        self.backup_runner = Runner(self)
        self.live_runner = Runner(self)
        self.counts: dict[str, str] = {}
        self.photo_src = None
        self.current = None
        self.wall_img = None
        self.refreshing = False
        self.overview = None            # V1-V3: deviceinfo.Overview of the connected phone
        self.overview_problem = ""
        self.photos_bytes = self.messages_bytes = None
        self.info_runner = Runner(self)
        self.apps_runner = Runner(self)     # 5.1.3: the app list, read only when it's needed
        self._apps_state = ""               # "" / "loading" / "done"
        self._apps_failed = False           # the last ask failed: asked again only when Storage is opened again
        self._apps_list = None
        self._apps_shown_at = 0.0
        self.phone_here = True          # 5.1.3: False while the iPhone is unplugged / out of reach
        self.where = None               # asks whether this iPhone (by its UDID) is reachable now; set once connected
        self.watch_runner = Runner(self)
        self.storage_runner = Runner(self)  # 5.1.3: the second try at the storage question
        self.storage_state = ""             # "" / "waiting" (asked again) / "failed" (no answer, "Try again")
        self._storage_failed_at = 0.0
        self._storage_tick_id = None
        self._storage_for = None            # the overview the running second try is for
        self._connecting = False
        self._reload_when_connected = False
        self.find_q = tk.StringVar()        # E4: "Search everything", shared by the home screen and the results
        self.find_q.trace_add("write", self._find_typed)
        self._find_after = None
        self.searcher = None                # search.PhoneSearch for self.data, built on the first search
        self.search_runner = Runner(self)
        self.check_runner = Runner(self)    # S8: the tamper check, so a big backup's check never holds up the counts
        self.tamper_state: Optional[tamper.Result] = None
        self.tamper_when = None
        self.seal_backups = True            # S8: seal old snapshots when opened; real_check turns it off (read-only)
        self.find_hook = None               # (key, its search box's StringVar, select(ref)) of the open app view
        self.pending_find = None            # (key, query, ref): what to show once that app's view is up

        self._build()
        saved = wv.phone_picture(self.udid) if self.udid else None
        if saved is not None and saved.exists():
            self._set_wallpaper(saved)         # the saved home screen at once, replaced when a fresh one comes
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.show_home()
        self._connect_live()
        self._open_backup()

    # layout --------------------------------------------------------------------
    def _build(self):
        head = ui.header(self)
        head.pack(fill="x")
        # the buttons on the right are packed first, so a narrow window trims the text on the left instead of
        # drawing it over "Refresh from iPhone" (owner's Mac, 13 Nov)
        # L1 (Direction A): Save everything is the window's main button, at the right of the header
        self.save_all_btn = RoundButton(head, "Save everything…", self.save_everything, "primary", 180, 34, 12)
        self.save_all_btn.pack(side="right", padx=(6, 16))
        # S6: one switch for every save in this window; off by default and for each new window (the password is
        # asked at each save and never kept)
        self.protect_btn = RoundButton(head, self._protect_text(), self.toggle_protect, "ghost", 190, 34, 12)
        self.protect_btn.pack(side="right", padx=(6, 0))
        RoundButton(head, "📂  Saved files", lambda: (self.out_root.mkdir(parents=True, exist_ok=True),
                                                      reveal(self.out_root)), "ghost", 150, 34, 12).pack(side="right", padx=(6, 0))
        self.refresh_btn = RoundButton(head, "⟳  Refresh from iPhone", self.refresh, "ghost", 210, 34, 12)
        self.refresh_btn.pack(side="right")
        tk.Label(head, text=self.name, bg=theme.HEADER_BG, fg=theme.HEADER_TITLE, font=font(19, "bold")).pack(side="left", padx=(20, 10), pady=12)
        if self.opened_backup is not None and not self.live_wanted:
            info = wv.backup_info(self.opened_backup)
            sub_text = f"backup of {info.get('date') or '?'} · iOS {info.get('ios') or '?'} · no iPhone connected"
        else:
            sub_text = self._connected_text()
        self.sub = tk.Label(head, text=sub_text, bg=theme.HEADER_BG, fg=theme.HEADER_TEXT, font=font(12))
        self.sub.pack(side="left", pady=12)
        self.lock_badge = tk.Label(head, text="", bg=theme.HEADER_BG, fg=theme.HEADER_LINK, font=font(12, "bold"))
        self.lock_badge.pack(side="left", padx=(14, 0), pady=12)

        self.bar_frame = tk.Frame(self, bg=GREEN_SOFT)
        self.bar_text = tk.Label(self.bar_frame, text="", bg=GREEN_SOFT, fg=INK, font=font(12), anchor="w")
        self.bar_text.pack(side="left", fill="x", expand=True, padx=16, pady=6)
        self.bar_btn = None

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=14)
        left = tk.Frame(body, bg=BG, width=270)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.mock = tk.Canvas(left, width=250, height=500, bg=BG, highlightthickness=0, cursor="hand2")
        self.mock.pack(pady=(4, 8))
        self.mock.bind("<Button-1>", lambda e: self.show_home())
        self._draw_phone()
        self.src_line, self.src_text = None, ""          # L1: shown under the tiles on the home screen
        # B3: the snapshots, in the Snapshot card (L1). Choose one to see the phone as it was then; ⋯ for more.
        self.timeline = tk.Frame(left, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        self.timeline.pack(fill="x", pady=(10, 0))
        # "Viewing 3 Nov" (B3, Q5): a pill on the phone picture's screen, so it takes no room from the Snapshot card
        self.viewing = tk.Label(left, text="", bg=theme.WARN_BG, fg=theme.WARN_TEXT, font=font(11, "bold"),
                                padx=10, pady=2)
        self._build_timeline()
        self._update_src_line()

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True, padx=(14, 0))

    # snapshots (B3) ------------------------------------------------------------------------
    def _build_timeline(self, fresh: bool = True):
        """fresh=False: the snapshots listed a moment ago (Q5: opening one from the slider, a quarter second less)."""
        for w in self.timeline.winfo_children():
            w.destroy()
        snaps = (self.snaps if not fresh and getattr(self, "snaps", None) is not None
                 else sn.list_snapshots(self.backup_dir, self.udid) if self.udid else [])
        self.snaps = snaps
        tk.Label(self.timeline, text="SNAPSHOT", bg=CARD, fg=MUTED, font=font(11, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(12, 4))
        if not snaps:
            none = ("Only the latest backup so far." if self.udid and sn.has_backup(self.backup_dir, self.udid)
                    else "None yet: the first backup makes one.")
            tk.Label(self.timeline, text=none, bg=CARD, fg=MUTED, font=font(11),
                     anchor="w", wraplength=230, justify="left").pack(fill="x", padx=14, pady=(0, 12))
            return
        # one drop-down list of every snapshot, newest first, and ⋯ for keep forever / rename / delete
        # (owner, 13 Nov: "the snapshots should be a drop list")
        row = tk.Frame(self.timeline, bg=CARD)
        row.pack(fill="x", padx=14, pady=(2, 0))
        current = self.snapshot.id if self.snapshot else snaps[0].id
        titles = sn.timeline_titles(snaps)
        self.snap_choices = [("🔒 " if snap.locked else "") + t + ("  (latest)" if n == 0 else "")
                             for n, (snap, t) in enumerate(zip(snaps, titles))]
        self.snap_var = tk.StringVar(value=self.snap_choices[next(n for n, x in enumerate(snaps) if x.id == current)])
        self.snap_box = ttk.Combobox(row, textvariable=self.snap_var, values=self.snap_choices, state="readonly",
                                     width=18, height=min(15, len(snaps)))
        self.snap_box.pack(side="left")
        self.snap_box.bind("<<ComboboxSelected>>",
                           lambda e: self.open_snapshot(snaps[self.snap_choices.index(self.snap_var.get())]))
        more = tk.Label(row, text="⋯", bg=theme.SECONDARY_HOVER, fg=INK, font=font(14, "bold"), padx=8, cursor="hand2")
        more.pack(side="left", padx=(6, 0))
        sel = lambda: snaps[self.snap_choices.index(self.snap_var.get())]
        more.bind("<Button-1>", lambda e: self._snapshot_menu(e, sel()))
        if len(snaps) >= 2:
            self._build_slider(snaps, titles, current)
        tk.Label(self.timeline, text=f"{len(snaps)} snapshot{'s' if len(snaps) != 1 else ''} · ⋯ keep, rename, delete",
                 bg=CARD, fg=MUTED, font=font(10), anchor="w").pack(fill="x", padx=14, pady=(4, 0))
        detail = self.snapshot or snaps[0]
        size = f"{detail.size / 1e9:.1f} GB" if detail.size >= 1e9 else f"{detail.size / 1e6:.1f} MB"
        tk.Label(self.timeline, text=f"{detail.when.strftime('%d %b %Y %H:%M').lstrip('0')} · {size} · iOS {detail.ios or '?'} · "
                                     + ("🔒 encrypted" if detail.encrypted else "not encrypted"),
                 bg=CARD, fg=MUTED, font=font(10), anchor="w", wraplength=230, justify="left").pack(fill="x", padx=14, pady=(2, 12))

    def _build_slider(self, snaps: list, titles: list, current: str):
        """Q5: the snapshots on a slider, oldest on the left, the latest on the right, a tick for each. Dragging
        shows the date under the handle in the list above; the phone window changes to that snapshot once the
        handle stops (letting go of the mouse, or a short pause after the keys). The arrow keys move it one snapshot."""
        old_first = list(reversed(snaps))
        names = list(reversed(self.snap_choices))
        last = len(old_first) - 1
        at = tk.IntVar(value=next(n for n, x in enumerate(old_first) if x.id == current))
        H, PAD, Y = 32, 10, 9                             # height; room for the handle at each end; the line's y
        cv = tk.Canvas(self.timeline, height=H, bg=CARD, highlightthickness=0, takefocus=1, cursor="hand2")
        cv.pack(fill="x", padx=14, pady=(6, 0))
        wait = {"after": None, "down": False}           # down: the mouse button is held (a drag opens on letting go)

        def x_of(i, w):
            return PAD + (w - 2 * PAD) * i / last

        def draw(*_):
            cv.delete("all")
            w = max(cv.winfo_width(), 2 * PAD + 1)
            cv.create_line(PAD, Y, w - PAD, Y, fill=theme.BORDER, width=4, capstyle="round")
            cv.create_line(PAD, Y, x_of(at.get(), w), Y, fill=theme.ACCENT, width=4, capstyle="round")
            for i in range(last + 1):
                cv.create_oval(x_of(i, w) - 2, Y - 2, x_of(i, w) + 2, Y + 2, fill=MUTED, outline="")
            x = x_of(at.get(), w)
            cv.create_oval(x - 8, Y - 8, x + 8, Y + 8, fill=theme.ACCENT, outline=CARD, width=2)
            cv.create_text(PAD - 4, H - 2, text=titles[-1], anchor="sw", fill=MUTED, font=font(10))
            cv.create_text(w - PAD + 4, H - 2, text="Latest", anchor="se", fill=MUTED, font=font(10))

        def go():
            wait["after"] = None
            snap = old_first[at.get()]
            if snap.id != current:
                self.open_snapshot(snap)

        def moved(*_):
            draw()
            self.snap_var.set(names[at.get()])           # the date under the handle, in the list above
            if wait["after"]:
                self.after_cancel(wait["after"])
                wait["after"] = None
            if not wait["down"]:
                wait["after"] = self.after(250, go)      # the keys: the handle stopped (the mouse opens on letting go)

        def let_go(_e=None):
            wait["down"] = False
            if wait["after"]:
                self.after_cancel(wait["after"])
            go()

        def press(e):
            wait["down"] = True
            pointer(e)

        def pointer(e):
            cv.focus_set()
            w = max(cv.winfo_width(), 2 * PAD + 1)
            i = max(0, min(last, round((e.x - PAD) / (w - 2 * PAD) * last)))
            if i != at.get():
                at.set(i)

        def gone(_e=None):
            if wait["after"]:
                self.after_cancel(wait["after"])
                wait["after"] = None
            at.trace_remove("write", trace)

        trace = at.trace_add("write", moved)               # the mouse, the arrow keys or the tests: all move `at`
        cv.bind("<Configure>", draw)
        cv.bind("<Button-1>", press)
        cv.bind("<B1-Motion>", pointer)
        cv.bind("<ButtonRelease-1>", let_go)
        cv.bind("<Left>", lambda e: at.get() > 0 and at.set(at.get() - 1))
        cv.bind("<Right>", lambda e: at.get() < last and at.set(at.get() + 1))
        cv.bind("<Destroy>", gone)
        self.snap_slider = (cv, at, old_first, let_go)    # for the tests (Tk can't play a drag on a hidden window)

    def open_snapshot(self, snap: Optional[sn.Snapshot]):
        """Show the phone as it was at that snapshot (None = the latest)."""
        latest = self.snaps[0] if self.snaps else None
        self.snapshot = None if (snap is None or (latest and snap.id == latest.id)) else snap
        self.tamper_state = None
        self.backup_path = (self.snapshot.path if self.snapshot else sn.latest_backup_path(self.backup_dir, self.udid))
        if self.snapshot:
            self.viewing.configure(text=f"Viewing {self.snapshot.title}")
            self.viewing.place(in_=self.mock, relx=0.5, y=58, anchor="n")
            self.viewing.lift()
        else:
            self.viewing.place_forget()
        self._build_timeline(fresh=False)
        if self.data is not None:
            self.data.close()
            self.data = None
        self.counts = {}
        self.photo_src = None
        self._open_backup()

    # tamper check (S8) ----------------------------------------------------------------------
    def _tamper_banner(self, res: tamper.Result, when) -> None:
        self.tamper_state, self.tamper_when = res, when
        if res.state == "changed":
            self.banner("")                                 # banner() shows the tamper banner while it's "changed"

    def check_backup(self) -> None:
        """The fast check (sizes) of the snapshot that was just opened; the amber banner if it changed."""
        path, data = Path(self.backup_path), self.data
        if not sn.is_snapshot(path):
            return
        snap = next((x for x in self.snaps if Path(x.path) == path), None)
        when = snap.when if snap else dt.datetime.now()
        seal = self.seal_backups

        def run():
            res = tamper.check(path)
            if res.state == "no seal" and seal:         # made before S8: sealed now, checked from now on
                import json as _json
                tamper.make_seal(path, _json.loads((path / "files.json").read_text(encoding="utf-8")))
                tamper.note_made(path)
                res = tamper.check(path)
            elif res.ok and seal:
                tamper.sign_pending([path])                # the helper's seal, signed here (it has no keychain)
            return res
        self.check_runner.submit(run, lambda res: data is self.data and self._tamper_banner(res, when), lambda e: None)

    def check_backup_fully(self, snap: Optional[sn.Snapshot] = None) -> None:
        """Every file of a snapshot read again and compared with what it was (⋯ → Check for changes)."""
        snap = snap or self.snapshot or (self.snaps[0] if self.snaps else None)
        if snap is None:
            return
        path, data = Path(snap.path), self.data
        title = snap.when.strftime('%d %b %Y').lstrip('0')
        self.banner(f"Checking every file of the backup of {title}… This can take a few minutes.")

        def progress(pct):
            self.check_runner.on_ui(lambda: self.bar_text.winfo_exists() and self.bar_text.configure(
                text=f"Checking every file of the backup of {title}… {pct:.0f}%"))

        def ok(res: tamper.Result):
            opened = data is self.data and Path(self.backup_path) == path
            if opened and res.state in ("ok", "changed"):
                self.tamper_state, self.tamper_when = res, snap.when
            self.banner("")
            if res.state == "changed":
                messagebox.showwarning(wv.APP_NAME, tamper.banner_text(snap.when) + "\n\nWhat differs: "
                                       + "; ".join(res.changed) + ".", parent=self)
            elif res.state == "no seal":
                messagebox.showinfo(wv.APP_NAME, "This backup was made before PhoneKeep could check backups, "
                                    "so there's nothing to compare it with. Open it once to seal it.", parent=self)
            elif res.state == "can't check":
                messagebox.showinfo(wv.APP_NAME, f"PhoneKeep can't be sure about the backup of {title}: "
                                    + "; ".join(res.changed) + ". Its files match its seal.", parent=self)
            else:
                messagebox.showinfo(wv.APP_NAME, f"No changes: all {res.checked:,} files of the backup of {title} "
                                    "are as they were when it was made.", parent=self)
        # stops when the window closes (its runners stop): a stopped check says nothing
        self.check_runner.submit(lambda: tamper.check(path, full=True, progress=progress,
                                                      cancel=lambda: not self.check_runner.alive),
                                 lambda res: res.changed != ["the check was stopped"] and ok(res),
                                 lambda e: self.banner(f"Couldn't check the backup: {e}", color=theme.ERROR_BG))

    def _snapshot_menu(self, event, snap: sn.Snapshot):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Check for changes…", command=lambda: self.check_backup_fully(snap))
        m.add_command(label="Keep forever" if not snap.locked else "Don't keep forever",
                      command=lambda: (sn.set_locked(self.backup_dir, self.udid, snap.id, not snap.locked), self._build_timeline()))
        m.add_command(label="Rename…", command=lambda: self._rename_snapshot(snap))
        m.add_separator()
        m.add_command(label="Delete…", command=lambda: self._delete_snapshot(snap))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _rename_snapshot(self, snap: sn.Snapshot):
        name = ui.ask_text(self, "Rename snapshot", f"A name for the snapshot of {snap.when.strftime('%d %b %Y').lstrip('0')}:",
                           initial=snap.label or "")
        if name is not None:
            sn.set_label(self.backup_dir, self.udid, snap.id, name)
            self._build_timeline()

    def _delete_snapshot(self, snap: sn.Snapshot):
        if snap.locked:
            messagebox.showinfo("Kept forever", "This snapshot is kept forever. Choose \"Don't keep forever\" first.", parent=self)
            return
        if len(self.snaps) <= 1:
            messagebox.showinfo(wv.APP_NAME, "This is the only snapshot of this iPhone; make a new backup before deleting it.", parent=self)
            return
        if not messagebox.askokcancel(f"Delete the snapshot of {snap.title}?",
                                      f"The backup of {self.name} from {snap.when.strftime('%d %b %Y %H:%M').lstrip('0')} goes to the "
                                      + ("Trash" if sys.platform == "darwin" else "Recycle Bin") + ". Other snapshots are not affected.",
                                      icon="warning", parent=self):
            return
        sn.delete_snapshot(self.backup_dir, self.udid, snap.id)
        import phone_write
        phone_write.log_activity(f"Deleted the snapshot of {snap.when.strftime('%d %b %Y').lstrip('0')}", self.name, kind="backup")
        if self.snapshot and self.snapshot.id == snap.id:
            self.snaps = sn.list_snapshots(self.backup_dir, self.udid)   # without the one just deleted (Q5 reuses it)
            self.open_snapshot(None)
        else:
            self._build_timeline()

    def _draw_phone(self):
        c = self.mock
        c.delete("all")
        W, H = 250, 500

        def rr(x1, y1, x2, y2, r, fill, outline=""):
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
                   x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
            return c.create_polygon(pts, smooth=True, fill=fill, outline=outline)
        rr(4, 4, W - 4, H - 4, 44, theme.PHONE_BODY)
        rr(12, 12, W - 12, H - 12, 36, theme.PHONE_SCREEN)
        if self.wall_img is not None:
            # the phone's own picture already shows its time, date and island: nothing drawn over it (13 Nov)
            c.create_image(W // 2, H // 2, image=self.wall_img)
            return
        c.create_text(W // 2, H // 2 + 40, text="Your wallpaper\nshows here when the\niPhone is connected",
                      fill=theme.PHONE_SCREEN_TEXT, font=font(11), justify="center")
        rr(W // 2 - 44, 22, W // 2 + 44, 46, 12, theme.PHONE_ISLAND)             # Dynamic Island
        now = dt.datetime.now().strftime("%H:%M")
        c.create_text(46, 34, text=now, fill=theme.ON_DARK, font=font(12, "bold"))
        c.create_text(W // 2, H // 2 - 70, text=now, fill=theme.ON_DARK, font=font(44, "bold"))
        c.create_text(W // 2, H // 2 - 120, text=dt.datetime.now().strftime("%A %d %B"), fill=theme.ON_DARK, font=font(13))
        rr(W // 2 - 50, H - 30, W // 2 + 50, H - 25, 2, theme.PHONE_HOME_BAR)       # home bar

    def _set_wallpaper(self, path):
        if not path or Image is None:
            return
        try:
            im = Image.open(path).convert("RGB")
            im = ImageOps.fit(im, (226, 476))
            from PIL import ImageDraw
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), 34, fill=255)
            bg = Image.new("RGB", im.size, (28, 28, 30))
            bg.paste(im, (0, 0), mask)
            self.wall_img = ImageTk.PhotoImage(bg)
            self._draw_phone()
        except Exception:
            pass

    def _update_src_line(self):
        parts = []
        if self.data is not None:
            parts.append(f"Messages, chats, calls & notes: from the backup of {self.data.info.get('date') or '?'}")
        elif self.data_error:
            parts.append(self.data_error)
        else:
            parts.append("Opening the latest backup…")
        if self.live is not None:
            parts.append("Photos, music, books & files: live from the iPhone")
        elif self.live_error:
            parts.append("iPhone not reachable: photos come from the backup")
        # each part keeps its own ending ("…", "." from a message); one without gets a full stop
        self.src_text = " ".join(p.rstrip() if p.rstrip().endswith((".", "…", "!", "?")) else p.rstrip() + "."
                                 for p in parts if p.strip())
        try:
            if self.src_line is not None:
                self.src_line.configure(text=self.src_text)
        except tk.TclError:                    # the home screen isn't showing
            self.src_line = None

    def passcode_notice(self, text):
        """The iPhone waits for its passcode: say so big at the top and bring this window forward."""
        try:
            if text is None:
                self.banner("Backing up changes from the iPhone… keep it unlocked and nearby.")
                self.bar_text.configure(font=font(13))
                return
            self.banner("📱  " + text, color=theme.WARN_BG)
            self.bar_text.configure(font=font(16, "bold"))
            self.deiconify()
            self.lift()
            self.bell()
        except tk.TclError:
            pass

    def cover_locked(self):
        """S2: after the idle time, hide everything in this window behind one Unlock button."""
        if getattr(self, "_lock_cover", None) is not None:
            return
        cover = tk.Frame(self, bg=BG)
        cover.place(relx=0, rely=0, relwidth=1, relheight=1)
        box = tk.Frame(cover, bg=BG)
        box.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(box, text="🔒", bg=BG, font=font(48)).pack()
        tk.Label(box, text="PhoneKeep is locked", bg=BG, fg=INK, font=font(20, "bold")).pack(pady=(6, 2))
        tk.Label(box, text=f"{self.name} is hidden until you unlock.", bg=BG, fg=MUTED, font=font(13)).pack()
        self.unlock_btn = RoundButton(box, "Unlock", lambda: self.app.require_unlock(self.uncover, "show your iPhone's data again"),
                                      "primary", 160, 42, bg=BG)
        self.unlock_btn.pack(pady=(16, 0))
        cover.lift()
        self._lock_cover = cover

    def uncover(self):
        """Unlocked: show this window again, and every other covered phone window."""
        cover = getattr(self, "_lock_cover", None)
        if cover is not None:
            cover.destroy()
            self._lock_cover = None
        for w in (self.app.open_phone_windows() if hasattr(self.app, "open_phone_windows") else ()):
            if w is not self and getattr(w, "_lock_cover", None) is not None:
                w.uncover()

    def banner(self, text: str, button: Optional[tuple] = None, color=GREEN_SOFT):
        if not text and self.tamper_state is not None and self.tamper_state.state == "changed":
            # S8: the open snapshot changed after it was made: that stays said, whatever else came and went
            text, button, color = (tamper.banner_text(self.tamper_when), ("Check fully", self.check_backup_fully),
                                   theme.WARN_BG)
        if not text:
            self.bar_frame.pack_forget()
            return
        self.bar_frame.configure(bg=color)
        self.bar_text.configure(text=text, bg=color, fg=theme.WARN_TEXT if color == theme.WARN_BG else INK)
        if self.bar_btn is not None:
            self.bar_btn.destroy()
            self.bar_btn = None
        if button:
            self.bar_btn = RoundButton(self.bar_frame, button[0], button[1], "secondary", 170, 30, 12)
            self.bar_btn.pack(side="right", padx=12, pady=4)
        if not self.bar_frame.winfo_ismapped():
            self.bar_frame.pack(fill="x", after=self.winfo_children()[0])

    # connections --------------------------------------------------------------
    def _connect_live(self, overview: bool = True):
        if not self.udid or not self.live_wanted:
            self.live_error = "No iPhone connected"
            self._update_src_line()
            return
        import device as devmod
        self._connecting = True

        def go():
            return devmod.LiveDevice(self.udid)

        def ok(live):
            self._connecting = False
            self.live = live
            self.live_error = None
            self._update_src_line()
            if not self.wifi:                  # only over a cable; over Wi-Fi the saved copy stays (5.1.3)
                def wall():
                    p = live.wallpaper("homescreen") or live.wallpaper("lockscreen")
                    wv.keep_phone_picture(self.udid, p)
                    return p
                self.live_runner.submit(wall, self._set_wallpaper, lambda e: None)
            if self.where is None and callable(getattr(live, "where", None)):
                self.where = live.where              # only ever this iPhone's UDID
                self.after(WATCH_MS, self._watch)
            if self.current is None:
                self.show_home()
            elif self._reload_when_connected and self.current in LIVE_KEYS:
                self.open_app(self.current)          # back: reload the section that's open
            self._reload_when_connected = False

        def err(e):
            self._connecting = False
            self.live_error = describe_error(e)
            self._update_src_line()
        self.live_runner.submit(go, ok, err)
        if overview:
            self._read_overview()

    # 5.1.3: the iPhone unplugged and plugged back in ---------------------------------------------------------------
    def _watch(self):
        """Every few seconds, ask (read-only) whether this iPhone is still reachable, and how."""
        def again(*_a):
            try:
                if self.winfo_exists():
                    self.after(WATCH_MS, self._watch)
            except tk.TclError:
                pass

        def ok(how):
            try:
                self.phone_seen(how)
            finally:
                again()
        self.watch_runner.submit(self.where, ok, again)     # Apple's service couldn't be asked: nothing known

    def phone_seen(self, how: Optional[str]):
        """how: "USB" / "Network" when this iPhone is reachable, None when it's gone."""
        if how is None:
            if self.phone_here:
                self._phone_gone()
            return
        if self.phone_here and not self.device.get("ConnectionType"):
            self.device["ConnectionType"] = how     # not known when the window opened: just say how
            self.sub.configure(text=self._connected_text())
        elif not self.phone_here or how != self.device.get("ConnectionType"):
            self._phone_back(how)                  # back, or moved between the cable and Wi-Fi: a new connection
        elif self.live is None and not self._connecting:
            self._connect_live(overview=False)     # here, but the last try didn't connect (e.g. still locked)

    def _drop_live(self):
        """Let go of the dead connections (closed in the background: closing a dead one can take seconds)."""
        import photos as ph
        old = [self.live]
        if isinstance(self.photo_src, ph.DevicePhotoSource):
            old.append(self.photo_src)
            self.photo_src = None
        self.live = None

        def close_all():
            for x in old:
                try:
                    x and x.close()
                except Exception:
                    pass
        threading.Thread(target=close_all, daemon=True).start()

    def _phone_gone(self):
        import photos as ph
        self.phone_here = False
        showing_live = self.current in LIVE_KEYS and (self.current != "photos"
                                                      or isinstance(self.photo_src, ph.DevicePhotoSource))
        self._drop_live()
        self.live_error = reconnect.PLUG_BACK
        self.sub.configure(text=reconnect.GONE, fg=theme.WARN_TEXT)
        self._update_src_line()
        if showing_live:
            self.open_app(self.current)

    def _phone_back(self, how: str):
        self.phone_here = True
        self.device["ConnectionType"] = how
        self.sub.configure(text=self._connected_text(), fg=theme.HEADER_TEXT)
        self._drop_live()
        self.live_error = None
        self._reload_when_connected = True
        self._connect_live()

    def _connected_text(self) -> str:
        how = "USB cable" if self.device.get("ConnectionType") == "USB" else "Wi-Fi"
        return f"iOS {self.device.get('ProductVersion', '?')} · connected by {how}"

    def calm(self, holder, msg: str):
        """Not an error: something to do (plug the iPhone back in). Grey, no button."""
        for w in holder.winfo_children():
            w.destroy()
        tk.Label(holder, text=msg, bg=BG, fg=MUTED, font=font(14), wraplength=640, justify="center").pack(pady=(70, 12))

    @property
    def wifi(self) -> bool:
        return self.device.get("ConnectionType") == "Network"

    def _read_overview(self):
        """V1-V3: ask the phone about itself (read-only) in the background, then refresh the home strip. Battery,
        storage and the phone's details only: the app list is read when it's needed (load_apps, 5.1.3)."""
        def ok(ov):
            self.overview = ov
            self.overview_problem = "" if ov is not None else "The iPhone's details couldn't be read just now."
            if ov is not None:
                if self._apps_list is not None:
                    ov.apps, ov.apps_updating = self._apps_list, self._apps_state == "loading"
                else:
                    ov.apps, ov.apps_as_of = phoneapps.load_saved(self.udid)
            if ov is not None and "disk" in ov.problems:
                self.retry_storage(show=False)      # the rest shows now; storage is asked again on its own
            else:
                self.storage_state = ""
            if self.current is None:
                self.show_home()
        kw = {"wifi": True} if self.wifi else {}
        self.info_runner.submit(lambda: wv.device_overview(self.udid, apps=False, **kw), ok,
                                lambda e: ok(None))

    def retry_storage(self, show: bool = True):
        """5.1.3: the storage question had no answer (over Wi-Fi a locked or dozing iPhone can hold it back): ask it
        once more on its own, in the background, with a longer limit. Read-only. Meanwhile the card says it's
        waiting; if there's still no answer it says so, with "Try again"."""
        if self.overview is None or not self.udid:
            return
        if self.storage_state == "waiting" and self._storage_for is self.overview:
            return                                  # already asking for this read of the phone
        self._storage_tick_cancel()
        self.storage_state = "waiting"
        if show:
            self._storage_refresh()
        udid, ov = self.udid, self.overview
        self._storage_for = ov                      # a newer read of the phone (reconnected) gets its own try

        def ok(disk):
            if disk is None:
                return failed(None)
            di.with_disk(ov, disk)
            if self.overview is ov:
                self.storage_state = ""
                self._storage_refresh()

        def failed(_e):
            if self.overview is not ov:             # a newer read of the phone took over meanwhile
                return
            self.storage_state = "failed"
            self._storage_failed_at = time.time()
            self._storage_refresh()
            self._storage_tick_id = self.after(STORAGE_TICK_MS, self._storage_tick)
        self.storage_runner.submit(lambda: wv.storage_values(udid), ok, failed)

    def _storage_tick(self):
        """While the storage question has no answer: ask again as soon as the iPhone answers anything else (it's
        awake, or unlocked), or anyway after a minute."""
        self._storage_tick_id = None
        if self.storage_state != "failed":
            return
        answered = max([getattr(x, "answered_at", 0.0) or 0.0 for x in (self.live, self.photo_src)] + [0.0])
        if self.phone_here and (answered > self._storage_failed_at
                                or time.time() - self._storage_failed_at >= STORAGE_AGAIN_S):
            self.retry_storage()
        else:
            self._storage_tick_id = self.after(STORAGE_TICK_MS, self._storage_tick)

    def _storage_tick_cancel(self):
        if self._storage_tick_id is not None:
            try:
                self.after_cancel(self._storage_tick_id)
            except tk.TclError:
                pass
            self._storage_tick_id = None

    def _storage_refresh(self):
        try:
            if self.current is None:
                self.show_home()
            elif self.current == "storage" and self.overview is not None:
                overview_ui.storage_view(self, self.overview)
        except tk.TclError:
            pass

    def load_apps(self, again: bool = False):
        """5.1.3: the app list, in the background: the names at once, then the sizes a few apps at a time, each
        shown as it arrives; the full list is saved for next time. Once per window. After a failed ask it's asked
        again only with again=True (a screen opened, not redrawn): a quick failure redraws the screen, and a redraw
        that asked again would ask and redraw for ever."""
        if self._apps_state or self.live is None or (self._apps_failed and not again):
            return
        self._apps_state, self._apps_failed = "loading", False
        live, udid, wifi = self.live, self.udid, self.wifi
        known = list(self.overview.apps) if self.overview is not None else phoneapps.load_saved(udid)[0]
        if self.overview is not None:
            self.overview.apps_updating = True

        def work():
            apps = phoneapps.with_names(live.app_names(timeout=10 if wifi else 60), known)
            self.apps_runner.on_ui(lambda: self._apps_arrived(apps, True))
            for ids in phoneapps.chunks(apps):
                phoneapps.with_sizes(apps, live.app_sizes(ids, timeout=30 if wifi else 120))
                self.apps_runner.on_ui(lambda: self._apps_arrived(apps, True))
            phoneapps.save(udid, apps)
            return apps

        def ok(apps):
            self._apps_state = "done"
            self._apps_arrived(apps, False)

        def err(e):
            self._apps_state, self._apps_failed = "", True      # asked again the next time Storage is opened
            if self.overview is not None:
                self.overview.apps_updating = False
            self._apps_refresh(force=True)
        self.apps_runner.submit(work, ok, err)

    def _apps_arrived(self, apps, updating: bool):
        self._apps_list = apps
        ov = self.overview
        if ov is not None:
            ov.apps, ov.apps_updating = apps, updating
            if not updating:
                ov.apps_as_of = ""
        self._apps_refresh(force=not updating)

    def _apps_refresh(self, force: bool = False):
        """Show the latest app list in the section that's open; while sizes arrive, at most every 2 seconds."""
        if not force and time.time() - self._apps_shown_at < 2:
            return
        self._apps_shown_at = time.time()
        try:
            if self.current == "storage" and self.overview is not None:
                overview_ui.storage_view(self, self.overview)
            elif self.current == "storagemap" and self.overview is not None \
                    and getattr(self, "map_key", "top") in ("top", "apps"):       # the levels app sizes are on
                storage_map.view(self, self.overview, getattr(self, "map_key", "top"))
            elif self.current == "checkup:storage" and force:
                checkup_ui.details(self, "storage")
        except tk.TclError:
            pass

    @staticmethod
    def _backup_sizes(r):
        """V3: what Photos and Messages take, from the backup `r` (BackupData) (an estimate: iCloud-only photos
        aren't in it)."""
        import photos as ph
        photos = sum((m[2] or 0) for f in ph.CAMERA_FOLDERS for m in r.file_meta("CameraRollDomain", f).values())
        msgs = sum((m[2] or 0) for m in r.file_meta("HomeDomain", "Library/SMS/").values())
        msgs += sum((m[2] or 0) for m in r.file_meta("MediaDomain", "Library/SMS/Attachments/").values())
        return photos, msgs

    def _open_backup(self, password: Optional[str] = None, ask: bool = False):
        """ask=True: the stored password didn't open the backup last time, so ask for one now (the stored
        one is kept until a typed one works)."""
        if self.backup_path is None or not (Path(self.backup_path) / "Manifest.db").exists():
            self.data_error = "No backup yet. Messages, chats, calls & notes appear after the first backup."
            self._update_src_line()
            if wv.backup_incomplete(Path(self.app.s["backup_dir"]) / (self.udid or "-")):
                self.banner("The last backup didn't finish. Back up again to complete it; Photos, Music, Books and "
                            "App Files work now.", button=("Back up now", self.refresh))
                return
            self.banner("No backup of this iPhone yet. Photos, Music, Books and App Files work now; "
                        "make a backup to see Messages, WhatsApp, calls, notes and the rest.",
                        ("Back up now", self.refresh))
            return
        info = wv.backup_info(self.backup_path)
        self.lock_badge.configure(text=ui.PROTECTED_SHORT if info["encrypted"] else "")
        typed = False
        if info["encrypted"] and password is None:
            # silently from the keychain (S1); only ask if it isn't there yet
            password = None if ask else (keychain.get_password(self.udid or "") or getattr(self.app, "_backup_password", None))
            if not password:
                password = ui.ask_password(self, "enter", info["name"], wv.RESET_PASSWORD_HELP)
                typed = True
            if not password:
                self.data_error = "The backup is encrypted. Click Messages (or any app) to enter the password."
                self._update_src_line()
                return
        self.banner("Opening the latest backup…" + (" Unlocking an encrypted backup can take up to a minute."
                                                     if info["encrypted"] else ""))

        def ok(data):
            if self.data is not None:
                self.data.close()
            self.data, self.data_error = data, None
            if password:
                self.app._backup_password = password   # remembered until PhoneKeep is closed
                if typed and self.udid:
                    keychain.set_password(self.udid, password)   # it opened the backup, so keep it
            self.banner("")
            self._update_src_line()
            self.check_backup()
            self.counts = {}
            self._count_next([k for k, *_r, where in APPS if where == "backup"])
            self.backup_runner.submit(lambda: self._backup_sizes(data),
                                      lambda pm: data is self.data and (setattr(self, "photos_bytes", pm[0])
                                                                        or setattr(self, "messages_bytes", pm[1])),
                                      lambda e: None)
            if self.current is None:
                self.show_home()
            elif self.current in CHAT_APPS + ("calls", "contacts", "notes", "calendar", "voicemail", "allfiles",
                                               "voicememos", "callrecordings", "safari", "apps"):
                self.open_app(self.current)

        def err(e):
            msg = describe_error(e)
            if "password" in msg.lower():
                # Never remove the stored password here: it is the owner's only copy, and an open can fail for
                # other reasons (a snapshot still being written, a read refused by the keychain, a bad file).
                # The stored one is replaced only when a typed password opens the backup (S1).
                self.app._backup_password = None
                if messagebox.askretrycancel(wv.APP_NAME, msg, parent=self):
                    self._open_backup(ask=True)
                    return
            self.data_error = msg
            self.banner(msg, color=theme.ERROR_BG)
            self._update_src_line()
        # Q5: the screens shown before leave Tk pictures behind as garbage. Collected on a worker thread (as the
        # backup's reading makes garbage there), each one waits its turn on this thread to be deleted: after
        # Photos, Contacts and the rest, going back to the latest snapshot took 14 s. Collect them here first.
        gc.collect()
        self.backup_runner.submit(lambda: BackupData(self.backup_path, password), ok, err)

    def _count_next(self, keys: list):
        if not keys or self.data is None:
            return
        key, rest = keys[0], keys[1:]
        data = self.data

        def ok(n):
            if data is not self.data:
                return                      # another snapshot was opened meanwhile: its own counts are coming
            self.counts[key] = n
            self._paint_count(key)
            self._count_next(rest)

        def err(e):
            if data is not self.data:
                return
            self.counts[key] = "nothing found"
            self._paint_count(key)
            self._count_next(rest)
        self.backup_runner.submit(lambda: data.count(key), ok, err)

    # home screen --------------------------------------------------------------
    def _clear(self):
        self.find_hook = None               # E4: the view it belonged to is going
        for w in self.content.winfo_children():
            w.destroy()

    def show_home(self):
        """L1 (Direction A): the three cards, then "What's on this iPhone" as tiles in four columns, then where the
        data comes from."""
        self.current = None
        self._clear()
        if self.udid and self.live_wanted:          # V1-V3: about this iPhone, its battery and storage
            last = ""
            if self.backup_path is not None and (Path(self.backup_path) / "Manifest.db").exists():
                last = f"Last backup {wv.backup_info(self.backup_path).get('date') or '?'}"
            self.overview_strip = overview_ui.cards(self, self.content, self.overview, last, self.overview_problem)
            self.overview_strip.pack(fill="x", pady=(0, 18))
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text="What's on this iPhone", bg=BG, fg=INK, font=font(19, "bold"), anchor="w").pack(side="left")
        self._find_box(row).pack(side="right")
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="x")
        self.tile_count, self.tiles = {}, {}
        cols = 4
        for i, (key, label, icon, colour, where) in enumerate(APPS):
            t = tk.Frame(grid, bg=CARD, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
            t.grid(row=i // cols, column=i % cols, padx=5, pady=5, sticky="nsew")
            img = app_icon(key, size=48)
            if img is not None:
                ic = tk.Label(t, image=img, bg=CARD, cursor="hand2")
            else:
                ic = tk.Label(t, text=icon, bg=CARD, font=font(26), cursor="hand2")
            ic.pack(side="left", padx=(12, 10), pady=10)
            words = tk.Frame(t, bg=CARD, cursor="hand2")
            words.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Label(words, text=label, bg=CARD, fg=INK, font=font(13, "bold"), anchor="w", justify="left",
                     cursor="hand2").pack(fill="x")
            words.bind("<Configure>", lambda e, w=words: [c.configure(wraplength=max(60, e.width))
                                                          for c in w.winfo_children()], add="+")
            cl = tk.Label(words, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w", cursor="hand2")
            cl.pack(fill="x")
            self.tile_count[key], self.tiles[key] = cl, t
            for w in (t, ic, words, cl) + tuple(words.winfo_children()):
                w.bind("<Button-1>", lambda e, k=key: self.open_app(k))
                w.bind("<Enter>", lambda e, f=t: f.configure(highlightbackground=theme.BORDER_HOVER))
                w.bind("<Leave>", lambda e, f=t: f.configure(highlightbackground=LINE))
            self._paint_count(key)
        for c in range(cols):
            grid.columnconfigure(c, weight=1, uniform="tiles")
        self.src_line = tk.Label(self.content, text=self.src_text, bg=BG, fg=MUTED, font=font(11), anchor="w",
                                 justify="left", wraplength=760)
        self.src_line.pack(fill="x", pady=(12, 0))

    # one search across the phone (E4) --------------------------------------------------------------------------
    def _find_box(self, parent) -> tk.Frame:
        """The "Search everything" box: a magnifier, the shared search text and a grey hint while it's empty."""
        box = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        tk.Label(box, text="🔍", bg=CARD, fg=MUTED, font=font(12)).pack(side="left", padx=(10, 2))
        ent = tk.Entry(box, textvariable=self.find_q, width=26, relief="flat", bd=0, bg=CARD, fg=INK,
                       insertbackground=INK, highlightthickness=0, font=font(13))
        ent.pack(side="left", padx=(2, 10), pady=7)
        # the grey hint is packed after the entry while it's empty (not placed over it: Tk on Linux crashed when a
        # window placed inside the entry was torn down with it; #80 CI)
        hint = tk.Label(box, text="Search everything", bg=CARD, fg=MUTED, font=font(13), cursor="xterm")
        hint.bind("<Button-1>", lambda e: ent.focus_set())
        tid = None

        def show_hint(*_):
            if not hint.winfo_exists():
                self.find_q.trace_remove("write", tid)        # this box is gone
                return
            if self.find_q.get():
                hint.pack_forget()
                ent.configure(width=26)
            else:                           # an empty entry just wide enough for the cursor, the hint after it
                ent.configure(width=1)
                if not hint.winfo_manager():
                    hint.pack(side="left", after=ent, padx=(0, 10))
        tid = self.find_q.trace_add("write", show_hint)
        show_hint()
        box.entry = ent
        return box

    def _find_typed(self, *_):
        if self._find_after is not None:
            self.after_cancel(self._find_after)
        self._find_after = self.after(250, self._find_now)

    def _find_now(self):
        self._find_after = None
        import search
        q = search.fold(self.find_q.get()).strip()
        if len(q) >= search.MIN_CHARS:
            self.show_search()
        elif self.current == "search":
            self.show_home()
            self._focus_find()

    def _focus_find(self):
        for w in self.content.winfo_children():
            for box in w.winfo_children():
                if hasattr(box, "entry"):
                    box.entry.focus_set()
                    box.entry.icursor("end")
                    return

    def show_search(self):
        """The results of the search box, grouped by app; building the search first if it's the first time."""
        import search
        first = self.current != "search"
        self.current = "search"
        if first:
            self._clear()
            top = tk.Frame(self.content, bg=BG)
            top.pack(fill="x", pady=(0, 8))
            RoundButton(top, "‹  Home", self._leave_search, "secondary", 100, 32, 12).pack(side="left")
            self._find_box(top).pack(side="left", padx=(12, 0))
            self.find_status = tk.Label(top, text="", bg=BG, fg=MUTED, font=font(12), anchor="w")
            self.find_status.pack(side="left", padx=(12, 0))
            frame = card(self.content)
            frame.pack(fill="both", expand=True)
            self.find_text = tk.Text(frame, wrap="word", relief="flat", bg=CARD, fg=INK, font=font(13), padx=16,
                                     pady=12, highlightthickness=0, cursor="arrow")
            sb = ttk.Scrollbar(frame, orient="vertical", command=self.find_text.yview)
            self.find_text.configure(yscrollcommand=sb.set, state="disabled")
            self.find_text.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self._focus_find()
        if self.data is None:
            self.find_status.configure(text="Search looks through the backup: "
                                       + ("unlock it first." if self.data_error else "it's still opening… one moment."))
            return
        if self.searcher is None or self.searcher.get != self.data.get:
            self.searcher = search.PhoneSearch(self.data.get)
        s = self.searcher
        if not s.ready:
            if not getattr(self, "_find_building", False):
                self._find_building = True

                def progress(label):
                    self.search_runner.on_ui(lambda: self._find_status(f"Getting everything ready to search… {label}"))

                def built(_r=None):
                    self._find_building = False
                    if self.current == "search":
                        self.show_search()

                self.search_runner.submit(lambda: s.build(progress), built, built)
            return
        self._show_results(self.find_q.get())

    def _find_status(self, text):
        try:
            if self.current == "search":
                self.find_status.configure(text=text)
        except (AttributeError, tk.TclError):
            pass

    def _leave_search(self):
        self.find_q.set("")
        self.show_home()

    def _show_results(self, query: str):
        import search
        t0 = time.perf_counter()
        groups = self.searcher.find(query)
        self.find_seconds = time.perf_counter() - t0
        t = self.find_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for tag in t.tag_names():
            if tag.startswith("h"):
                t.tag_delete(tag)
        t.tag_configure("app", font=font(15, "bold"), spacing1=10, spacing3=4)
        t.tag_configure("title", font=font(13, "bold"))
        t.tag_configure("when", foreground=MUTED, font=font(11))
        t.tag_configure("snip", foreground=MUTED, lmargin1=0, spacing3=8)
        t.tag_configure("match", background=theme.HIT, foreground=INK)
        t.tag_configure("more", foreground=theme.LINK)
        total = sum(n for _k, n, _h in groups)
        if not groups:
            t.insert("end", f"Nothing found for “{query.strip()}”.", "snip")
        n = 0
        for key, count, hits in groups:
            t.insert("end", f"{search.LABELS[key]}  ", "app")
            t.insert("end", f"{count:,} result{'s' if count != 1 else ''}\n", ("app", "when"))
            for h in hits[:search.SHOWN]:
                tag = f"h{n}"
                n += 1
                before, match, after = search.snippet(h.text, query)
                t.insert("end", h.title, ("title", tag))
                t.insert("end", (f"   {h.when}" if h.when else "") + "\n", ("when", tag))
                t.insert("end", before, ("snip", tag))
                t.insert("end", match, ("snip", "match", tag))
                t.insert("end", after + "\n", ("snip", tag))
                t.tag_bind(tag, "<Button-1>", lambda e, h=h: self.open_hit(h, query))
                t.tag_bind(tag, "<Enter>", lambda e: t.configure(cursor="hand2"))
                t.tag_bind(tag, "<Leave>", lambda e: t.configure(cursor="arrow"))
            if count > search.SHOWN:
                tag = f"h{n}"
                n += 1
                t.insert("end", f"Show all {count:,} in {search.LABELS[key]}  ›\n", ("more", tag))
                t.tag_bind(tag, "<Button-1>", lambda e, k=key: self.open_hit(search.Hit(k, "", ""), query))
        t.configure(state="disabled")
        left = [search.LABELS[k] for k in self.searcher.missing]
        self._find_status((f"{total:,} result{'s' if total != 1 else ''}" if total else "")
                          + (f" · not in this backup: {', '.join(left)}" if left else ""))
        self.find_hits = groups

    def open_hit(self, hit, query: str):
        """Open the app with that item: its own search box shows the same words, and the item is chosen."""
        self.pending_find = (hit.key, query.strip(), hit.ref)
        self.open_app(hit.key)

    def card_for(self, addr) -> Optional[Callable]:
        """Q3: a way to open the card of the contact with this number or address, or None (not in Contacts)."""
        import people as pp
        data = self.data
        i = pp.person_for(data.contacts if data is not None else [], addr)
        if i is None:
            return None
        import search
        return lambda: self.open_hit(search.Hit("contacts", "", "", ref=i), "")

    def card_missing(self, addr) -> str:
        """Q3: why card_for(addr) found no card, as the end of a sentence about the number."""
        import people as pp
        data = self.data
        n = pp.contacts_with(data.contacts if data is not None else [], addr)
        if n > 1:
            return f"is on {n:,} contacts in the iPhone, so PhoneKeep can't tell whose card it is"
        return "isn't in the iPhone's Contacts"

    def open_card_for(self, addr, what: str = "") -> None:
        if addr is None:
            self.banner(f"Click a {what} first, then Contact card", color=theme.ACCENT_PALE)
            return
        go = self.card_for(addr)
        if go is None:
            self.banner(f"This number or address {self.card_missing(addr)}", color=theme.ACCENT_PALE)
        else:
            go()

    def _apply_find(self, key: str):
        pending, self.pending_find = self.pending_find, None
        hook = self.find_hook
        if not pending or pending[0] != key or not hook or hook[0] != key:
            return
        _k, query, ref = pending
        hook[1].set(query)
        if ref is not None:
            try:
                hook[2](ref)
            except (tk.TclError, LookupError):
                pass

    def _paint_count(self, key):
        lab = getattr(self, "tile_count", {}).get(key)
        if lab is None:
            return
        try:
            where = next(w for k, *_r, w in APPS if k == key)
            if key in self.counts:
                text = self.counts[key]
            elif where == "checkup":
                text = checkup_ui.tile_text(self)
            elif where == "live":
                text = "on the iPhone" if self.live is not None else ("from the backup" if key == "photos" else "connect iPhone")
            elif self.data is not None:
                text = "…"
            else:
                text = "needs a backup"
            lab.configure(text=text)
        except tk.TclError:
            pass

    # app views ----------------------------------------------------------------
    def view_header(self, key: str, sub: str = ""):
        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", pady=(0, 8))
        RoundButton(top, "‹  Home", self.show_home, "secondary", 100, 32, 12).pack(side="left")
        icon = next(i for k, _l, i, *_ in APPS if k == key)
        small = app_icon(key, small=True)
        if small is not None:
            tk.Label(top, image=small, text=f"  {LABEL[key]}", compound="left", bg=BG, fg=INK,
                     font=font(19, "bold")).pack(side="left", padx=12)
        else:
            tk.Label(top, text=f"{icon}  {LABEL[key]}", bg=BG, fg=INK, font=font(19, "bold")).pack(side="left", padx=12)
        self.view_sub = tk.Label(top, text=sub, bg=BG, fg=MUTED, font=font(12))
        self.view_sub.pack(side="left")
        return top

    def loading(self, text="Loading…"):
        f = tk.Frame(self.content, bg=BG)
        f.pack(fill="both", expand=True)
        tk.Label(f, text=text, bg=BG, fg=MUTED, font=font(14)).pack(pady=80)
        return f

    def failed(self, holder, msg, retry=None, details: str = ""):
        """Inline error (E3): one sentence, one button, and "Show details" for the technical text."""
        if isinstance(msg, BaseException):
            msg, retry, details = self._problem_parts(msg, retry)
        for w in holder.winfo_children():
            w.destroy()
        tk.Label(holder, text=msg, bg=BG, fg=RED, font=font(13), wraplength=640, justify="center").pack(pady=(70, 12))
        if retry:
            RoundButton(holder, retry[0], retry[1], "primary", 200, 38).pack()
        if details:
            lk = tk.Label(holder, text="Show details", bg=BG, fg=MUTED, font=font(11), cursor="hand2")
            lk.pack(pady=(10, 0))
            lk.bind("<Button-1>", lambda e, d=details: ui.show_details(self, d))

    def _problem_parts(self, e: BaseException, retry=None):
        """From an exception: (message, (button label, command), details) using the one errors table."""
        import errors
        if isinstance(e, wv.PhoneKeepError) and e.button:
            pr = errors.Problem(e.key, str(e), e.button, e.action, e.details)
        elif isinstance(e, wv.PhoneKeepError):
            pr = errors.Problem("plain", str(e), retry[0] if retry else "", errors.TRY_AGAIN if retry else "", e.details)
        else:
            pr = errors.explain(e)
        button = None
        if pr.action == errors.TRY_AGAIN and retry:
            button = (pr.button or retry[0], retry[1])
        elif pr.action == errors.ENTER_PASSWORD:
            button = (pr.button, self._open_backup)
        elif pr.action == errors.CHANGE_LOCATION:
            button = (pr.button, lambda: self.app.open_settings("backup_dir"))
        elif pr.action == errors.INSTALL_APPLE_DEVICES:
            button = (pr.button, lambda: __import__("webbrowser").open("https://apps.microsoft.com/detail/9NP83LWLPZ9K"))
        elif pr.action == errors.SHOW_DETAILS and pr.details:
            button = (pr.button, lambda d=pr.details: ui.show_details(self, d))
            return pr.message, button, ""
        elif retry:
            button = retry
        return pr.message, button, pr.details

    def open_app(self, key: str):
        if key == "checkup":
            checkup_ui.view(self)
            return
        self.current = key
        self._clear()
        self.view_header(key)
        if key == "apps":
            self.load_apps(again=True)      # 5.1.3: the phone's app list, in the background (always opened, never redrawn)
        where = next(w for k, *_r, w in APPS if k == key)
        if where == "backup":
            if self.data is None:
                holder = self.loading("")
                if self.data_error and "encrypted" in self.data_error:
                    self.failed(holder, "This backup is locked with a password.", ("Enter password", self._open_backup))
                elif self.data_error:
                    self.failed(holder, self.data_error, ("Back up now", self.refresh))
                else:
                    self.failed(holder, "Opening the latest backup… one moment.")
                return
            holder = self.loading()
            data = self.data
            self.backup_runner.submit(lambda: data.get(key), lambda v: self._show(key, holder, v),
                                      lambda e: self.failed(holder, e))
            return
        # live apps
        holder = self.loading("Reading from the iPhone…")
        if key == "photos":
            self._load_photos(holder)
            return
        if not self.phone_here:
            self.calm(holder, reconnect.PLUG_BACK)
            return
        if self.live is None:
            self.failed(holder, self.live_error or "Connecting to the iPhone… try again in a moment.",
                        ("Try again", lambda: (self._connect_live(), self.open_app(key))))
            return
        live = self.live
        fn = {"music": live.music, "books": live.books, "files": live.apps}[key]
        self.live_runner.submit(fn, lambda v: self._show(key, holder, v),
                                lambda e: self.failed(holder, e, ("Try again", lambda: self.open_app(key))))

    def _show(self, key, holder, value):
        if self.current != key:
            return
        holder.destroy()
        {"messages": self.v_chats, "whatsapp": self.v_chats, "whatsappbusiness": self.v_chats,
         "calls": self.v_calls, "contacts": self.v_contacts, "notes": self.v_notes,
         "calendar": self.v_calendar, "voicemail": self.v_voicemail, "voicememos": self.v_voicememos,
         "callrecordings": self.v_callrecordings,
         "safari": self.v_safari, "apps": self.v_apps, "allfiles": self.v_allfiles, "music": self.v_music, "books": self.v_books,
         "files": self.v_files, "photos": self.v_photos}[key](key, value)
        if self.pending_find:
            self._apply_find(key)

    # saving -------------------------------------------------------------------
    # S6: saves protected with a password ----------------------------------------
    protect_saves = False

    def _protect_text(self) -> str:
        return "🔒  Password: on" if self.protect_saves else "🔓  Password: off"

    def toggle_protect(self):
        self.protect_saves = not self.protect_saves
        self.protect_btn.configure_text(self._protect_text())
        self.banner("Password on: saves from this window are protected. It's asked each time and never kept."
                    if self.protect_saves else "Saves from this window are no longer protected with a password.")

    def _protect_begin(self, what: str, folder: Path) -> Path:
        """A private folder for one protected save into `folder` (asked for the password first). Returns the
        private folder to save into, or None if the owner cancelled."""
        password = protect_ui.ask_save_password(self, what)
        if not password:
            return None
        if not hasattr(self, "_protected"):
            self._protected = {}
        staging = Path(quicklook.private_dir()) / f"protect-{len(self._protected) + 1}-{int(time.time() * 1000)}"
        staging.mkdir(parents=True, exist_ok=True)
        self._protected[str(staging)] = {"folder": Path(folder), "password": password, "what": what}
        return staging

    def _protect_root(self, folder) -> Optional[str]:
        """The private folder of the protected save `folder` belongs to (it, or a folder inside it), or None."""
        if folder is None:
            return None
        jobs = getattr(self, "_protected", {})
        f = Path(folder)
        for p in (f, *f.parents):
            if str(p) in jobs:
                return str(p)
        return None

    def is_protected(self, folder) -> bool:
        return self._protect_root(folder) is not None

    def protect_abort(self, folder) -> None:
        """A protected save that failed or was cancelled: its private folder goes, and its password with it."""
        root = self._protect_root(folder)
        if root is None:
            return
        job = self._protected.pop(root)
        job["password"] = None
        shutil.rmtree(root, ignore_errors=True)

    def protect_finish(self, staging: Path, name: str, done, failed=None):
        """Protect what one save made in `staging` into the folder the owner chose (on the backup reader's
        thread, a ZIP of photos can take a while); done(paths, folder) on the window's thread."""
        job = self._protected.pop(str(staging))
        folder, password = job["folder"], job["password"]
        job["password"] = None
        self.banner(f"Protecting {job['what']} with the password…")

        def fail(e):
            shutil.rmtree(staging, ignore_errors=True)
            if failed:
                failed(e)
            else:
                self.banner(f"Couldn't save: {describe_error(e)}", color=theme.ERROR_BG)
        self.backup_runner.submit(lambda: protect.protect_folder(staging, folder, password, name),
                                  lambda paths: done(paths, folder), fail)

    def _protected_banner(self, paths: list, folder: Path, what: str):
        if not paths:
            messagebox.showwarning(wv.APP_NAME, "Nothing could be saved.", parent=self)
            return
        zipped = any(p.suffix.lower() == ".zip" for p in paths)
        activity.saved(len(paths), "protected file", folder, self.name)           # counted, never named (S7)
        first = paths[0].name if len(paths) == 1 else f"{len(paths):,} PDFs"
        self.banner(f"✓ Saved {what} with a password: {first} in {folder}"
                    + (". " + protect.ZIP_NOTE if zipped else ". It asks for the password when it opens."),
                    ("Show in Finder" if sys.platform == "darwin" else "Show folder", lambda: reveal(folder)))

    def out_dir(self, key: str, protectable: bool = True) -> Path:
        """Where a save goes. Asks the owner (a folder dialog, starting at the last folder they chose, or
        PhoneKeep's Saved files folder); raises Cancelled if they close the dialog. Usability test of 12 Nov:
        'save it to the Desktop' needs a choice, not a fixed folder. S6: with the window's password switch on,
        the password first, then the folder; the save goes into a private folder and saved() protects it into
        the one chosen."""
        password_first = protectable and self.protect_saves
        if password_first:
            what = LABEL.get(key, "files")
            staging = self._protect_begin(what, Path("."))
            if staging is None:
                return None
        default = self.out_root / LABEL[key]
        s = getattr(self.app, "s", None)
        last = None
        try:
            last = s["last_save_dir"] if s is not None else None
        except (KeyError, TypeError):
            last = None
        start = Path(last) if last else default
        if not start.exists():
            start = default
            start.mkdir(parents=True, exist_ok=True)
        chosen = ask_save_folder(self, f"Save {LABEL[key]} to…" + (" (with a password)" if password_first else ""),
                                 start)
        if not chosen:
            if password_first:
                self._protected.pop(str(staging), None)
                shutil.rmtree(staging, ignore_errors=True)
            return None                      # the owner closed the dialog: nothing to save, nothing to say
        d = Path(chosen)
        try:
            if s is not None:
                s["last_save_dir"] = str(d)
                if hasattr(self.app, "save"):
                    self.app.save()
        except Exception:
            pass
        d.mkdir(parents=True, exist_ok=True)
        if password_first:
            self._protected[str(staging)]["folder"] = d
            return staging
        return d

    def saved(self, paths: list, folder: Path, what: str = "file"):
        root = self._protect_root(folder)
        if root is not None:                 # S6: made in a private folder; now protected into the one chosen
            job = self._protected[root]
            stamp = dt.datetime.now().strftime("%Y-%m-%d %H%M")
            self.save_skipped = []
            self.protect_finish(Path(root), f"{job['what']} {stamp}",
                                lambda out, real: self._protected_banner(out, real, job["what"]))
            return
        n = len([p for p in paths if p])
        skipped, self.save_skipped = getattr(self, "save_skipped", []), []     # P2: songs the disk refused
        left = (f". {len(skipped):,} couldn't be saved ({skipped[0][0]}: {skipped[0][1]})" if skipped else "")
        if not n:
            messagebox.showwarning(wv.APP_NAME, "Nothing could be saved" + (left or "."), parent=self)
            return
        activity.saved(n, what, folder, self.name, plural="photos/videos" if what == "photo/video" else None)
        self.banner(f"✓ Saved {n:,} {what}{'s' if n != 1 else ''} to {folder}" + left,
                    ("Show in Finder" if sys.platform == "darwin" else "Show folder", lambda: reveal(folder)),
                    theme.ERROR_BG if skipped else GREEN_SOFT)

    def run_save(self, label: str, fn, folder: Path, what: str = "file", runner=None):
        self.banner(f"Saving {label}…")
        def err(e):
            self.protect_abort(folder)       # S6: a failed protected save leaves nothing (and drops its password)
            self.banner(f"Couldn't save: {describe_error(e)}", color=theme.ERROR_BG)
        (runner or self.backup_runner).submit(fn, lambda paths: self.saved(paths, folder, what), err)

    def save_everything(self, choice: Optional[dict] = None, folder: Optional[Path] = None):
        """D9: the Save everything sheet, then one export of every ticked kind into one new folder.
        choice / folder: given by the tests instead of the sheet and the folder dialog."""
        if self.data is None:
            messagebox.showinfo(wv.APP_NAME, "The backup is still opening. Try again in a moment.", parent=self)
            return
        if choice is None:
            data = self.data
            dlg = saveall_ui.SaveEverythingDialog(self, self.counts, lambda: saveall_ui.estimate_sizes(data, data.path, lambda: data.get("photos")))
            self.save_all_dialog = dlg
            dlg.grab_set()
            self.wait_window(dlg)
            choice = dlg.result
            if choice is None:
                return
        staging = None
        if folder is None:
            if self.protect_saves:           # S6: the password first, then where; made privately, then one ZIP
                staging = self._protect_begin("everything", self.out_root)
                if staging is None:
                    return
            base = ask_save_folder(self, "Save everything to…" + (" (with a password)" if staging else ""),
                                   self.out_root)
            if not base:
                if staging is not None:
                    self._protected.pop(str(staging), None)
                    shutil.rmtree(staging, ignore_errors=True)
                return
            folder = Path(base) / saveall_ui.folder_name(self.name)
            if staging is not None:
                self._protected[str(staging)]["folder"] = Path(base)
                folder = staging / saveall_ui.folder_name(self.name)
        folder.mkdir(parents=True, exist_ok=True)
        data = self.data
        eta = ui.Eta()
        state = {"finished": False}

        def progress(p):
            text = eta.feed(p)
            self.backup_runner.on_ui(lambda: None if state["finished"] else self.banner(f"Saving everything… {text}"))

        def go():
            return sx.export_all(data.path, folder, data.password, list(choice["sections"]), include_media=True,
                                 log=lambda m: None, formats=set(choice["formats"]), dates=choice["dates"],
                                 search=choice["search"], all_dates=True, progress=progress)

        def ok(index):
            state["finished"] = True
            if staging is not None:
                self.protect_finish(staging, folder.name,
                                    lambda out, real: self._protected_banner(out, real, "everything"), err)
                return
            self.last_save_all = Path(index)
            activity.log(f"Saved everything to {activity.where(folder)}", self.name, kind="save")
            self.banner(f"✓ Saved to {folder}", ("Open", lambda: open_file(Path(index))))

        def err(e):
            state["finished"] = True
            if staging is not None:
                self.protect_abort(staging)
            self.banner(f"Couldn't save everything: {describe_error(e)}", color=theme.ERROR_BG)
        self.banner("Saving everything…")
        self.backup_runner.submit(go, ok, err)

    def export_section(self, key: str, formats: set, chooser=None, dates=None, pdf_combined: bool = False,
                       then=None, out: Optional[Path] = None, quiet: bool = False, on_fail=None):
        """Full export of one app through the same code as the main 'Back up' button.
        then(index): called on the UI thread when done (Print uses it); out: another folder (Print: a temp one).
        S6: with the password switch on, a save that would go to Saved files asks for the password and where
        instead, and is made in a private folder, then protected there."""
        staging = None
        if out is None and then is None and self.protect_saves:
            staging = self.out_dir(key)
            if staging is None:
                return
        out = staging or out or self.out_root
        data = self.data

        eta = ui.Eta()
        state = {"finished": False}

        def progress(p):
            text = eta.feed(p)

            def show():
                if not state["finished"]:           # a late update must not cover the "✓ Exported" line
                    self.banner(f"Exporting {LABEL[key]}… {text}")
            self.backup_runner.on_ui(show)

        def go():
            return sx.export_all(data.path, out, data.password, [key], include_media=True,
                                 log=lambda m: None, chooser=chooser, formats=formats, dates=dates,
                                 progress=progress, pdf_combined=pdf_combined)

        def ok(index):
            state["finished"] = True
            if then is not None:
                then(index)
                return
            if staging is not None:
                self.saved([index], staging, LABEL[key])
                return
            pdfs = out / LABEL[key] / "PDF"
            activity.log(f"Saved {LABEL[key]} to {activity.where(out)}", self.name, kind="save")
            if formats == {"pdf"} and pdfs.exists():
                self.banner(f"✓ Saved PDF to {pdfs}", ("Show in Finder" if sys.platform == "darwin" else "Show folder",
                                                       lambda: reveal(pdfs)))
                return
            self.banner(f"✓ Exported {LABEL[key]} to {out}", ("Open", lambda: open_file(Path(index))))

        def err(e):
            state["finished"] = True
            if staging is not None:
                self.protect_abort(staging)
            if on_fail is not None:
                on_fail()
            self.banner(f"Couldn't export: {describe_error(e)}", color=theme.ERROR_BG)
        self.banner(f"Exporting {LABEL[key]}… working out time left…")
        self.backup_runner.submit(go, ok, err)

    # chats ----------------------------------------------------------------------
    def v_chats(self, key, value):
        chats = value if key == "messages" else value["chats"]
        lists = {key: (LABEL[key], [sx._chat_summary(c) for c in chats])}
        self.view_sub.configure(text=f"{len(chats):,} chat{'s' if len(chats) != 1 else ''} · "
                                     f"{sum(len(c['messages']) for c in chats):,} messages"
                                     f" · backup of {self.data.info.get('date') or '?'}")
        panel = ui.ChatPanel(self.content, lists, self.data.preview, select_all=False, preview_limit=600)
        panel.card_for = self.card_for                              # Q3: "Contact card" on a one-to-one chat
        panel.card_why = self.card_missing                          #     and why there's none (People window)
        panel.pack(fill="both", expand=True)
        self.find_hook = (key, panel.q, lambda ref: panel.show_chat(key, ref[0], ref[1]))

        def export(fmts):
            sel = panel.selection(confirm_empty=False)
            if sel is None:
                return
            if not any(v for k, v in sel.items() if not k.startswith("_")):
                messagebox.showinfo(wv.APP_NAME, "Tick the chats you want to save first (or Select all).", parent=self)
                return
            dates = sel.pop("_dates", None)
            self.export_section(key, fmts, chooser=lambda lists, pv: sel, dates=dates)
        def ticked():
            sel = panel.selection(confirm_empty=False)
            if sel is None:
                return None
            if not any(v for k, v in sel.items() if not k.startswith("_")):
                messagebox.showinfo(wv.APP_NAME, "Tick the chats you want first (or Select all).", parent=self)
                return None
            return sel

        def n_ticked(sel) -> int:
            return sum(len(v) if hasattr(v, "__len__") else 1 for k, v in sel.items() if not k.startswith("_"))

        def export_pdf():
            sel = ticked()
            if sel is None:
                return
            combined = False
            if n_ticked(sel) > 1:
                ans = messagebox.askyesnocancel(wv.APP_NAME, f"{n_ticked(sel):,} chats ticked.\n\nYes = one PDF with all of them\n"
                                                "No = one PDF for each chat", parent=self)
                if ans is None:
                    return
                combined = bool(ans)
            dates = sel.pop("_dates", None)
            folder = self.out_dir(key)              # ask where, like every other Save (usability test, 12 Nov)
            if folder is None:
                return
            # built in PhoneKeep's own Saved files folder, where photos copied out of the backup earlier are
            # reused (copying them again each time made Save/Print slow); then only the PDF goes to the folder.
            # S6: a protected save is built in the private folder instead, so no readable copy is left outside it
            started = time.time() - 1
            protected = self.is_protected(folder)
            build_root = (Path(quicklook.private_dir()) / f"build-{int(time.time() * 1000)}") if protected else None
            build = (build_root or self.out_root) / LABEL[key] / "PDF"

            def then(_index):
                made = sorted(p for p in build.glob("*.pdf") if p.stat().st_mtime >= started)
                if not made:
                    self.banner("Couldn't make the PDF.", color=theme.ERROR_BG)
                    return
                saved = []
                for f in made:
                    dest, k = folder / f.name, 2
                    while dest.exists():
                        dest, k = folder / f"{f.stem} ({k}){f.suffix}", k + 1
                    shutil.copy2(str(f), str(dest)) if folder.resolve() != build.resolve() else None
                    saved.append(dest if folder.resolve() != build.resolve() else f)
                if protected:
                    shutil.rmtree(build_root, ignore_errors=True)
                    self.saved(saved, folder, "PDF")
                    return
                what = saved[0].name if len(saved) == 1 else f"{len(saved):,} PDFs"
                activity.saved(len(saved), "PDF", folder, self.name)          # counted, never named (S7)
                self.banner(f"✓ Saved {what} to {folder}",
                            ("Open" if len(saved) == 1 else ("Show in Finder" if sys.platform == "darwin" else "Show folder"),
                             (lambda: open_file(saved[0])) if len(saved) == 1 else (lambda: reveal(folder))))
                reveal(saved[0] if len(saved) == 1 else folder)      # show it straight away: the result is visible
            self.export_section(key, {"pdf"}, chooser=lambda lists, pv: sel, dates=dates, pdf_combined=combined,
                                then=then, out=build_root,
                                on_fail=(lambda: (shutil.rmtree(build_root, ignore_errors=True),
                                                  self.protect_abort(folder))) if protected else None)

        def print_chats():
            """Print makes the same PDF (all ticked chats in one file) and opens the system print dialog."""
            sel = ticked()
            if sel is None:
                return
            dates = sel.pop("_dates", None)
            started = time.time() - 1
            build = self.out_root / LABEL[key] / "PDF"

            def then(_index):
                import chat_pdf
                pdfs = sorted((p for p in build.glob("*.pdf") if p.stat().st_mtime >= started),
                              key=lambda p: p.stat().st_mtime, reverse=True)
                if not pdfs:
                    self.banner("Couldn't make the PDF to print.", color=theme.ERROR_BG)
                    return
                try:
                    said = chat_pdf.print_pdf(pdfs[0])
                    self.banner(said, ("Show the PDF", lambda: reveal(pdfs[0])))
                except Exception as e:
                    self.banner(f"Couldn't print: {describe_error(e)}", color=theme.ERROR_BG)
            self.export_section(key, {"pdf"}, chooser=lambda lists, pv: sel, dates=dates, pdf_combined=True,
                                then=then)
        RoundButton(panel.foot, "Save as web page", lambda: export({"web"}), "secondary", 170, 38, 12).pack(side="right")
        RoundButton(panel.foot, "CSV", lambda: export({"csv"}), "secondary", 80, 38, 12).pack(side="right", padx=6)
        RoundButton(panel.foot, "Excel", lambda: export({"excel"}), "secondary", 90, 38, 12).pack(side="right")
        RoundButton(panel.foot, "Print", print_chats, "secondary", 90, 38, 12).pack(side="right", padx=6)
        RoundButton(panel.foot, "Save ticked as PDF", export_pdf, "primary", 180, 38, 12).pack(side="right")

    # photos ---------------------------------------------------------------------
    def _load_photos(self, holder):
        import photos as ph

        def from_device():
            src = self.photo_src
            if src is None or not isinstance(src, ph.DevicePhotoSource):
                src = ph.DevicePhotoSource(self.udid, quicklook.private_tmp("phonekeep-photos-"))
            return src, src.items()

        def from_backup():
            if self.data is None:
                raise wv.PhoneKeepError(self.data_error or "No backup yet, and the iPhone isn't reachable.")
            return self.data.get("photos")

        def ok(v):
            self.photo_src = v[0]
            self._show("photos", holder, v)

        def dev_err(e):
            if self.data is not None:
                self.backup_runner.submit(from_backup, ok, lambda e2: self.failed(holder, e2))
            elif not self.phone_here:
                self.calm(holder, reconnect.PLUG_BACK)
            else:
                self.failed(holder, e, ("Try again", lambda: self.open_app("photos")))
        if self.udid and self.live is not None:
            self.live_runner.submit(from_device, ok, dev_err)
        else:
            dev_err(wv.PhoneKeepError(self.live_error or "The iPhone isn't connected."))

    def v_photos(self, key, value):
        src, items = value
        nv = sum(1 for i in items if i.video)
        self.view_sub.configure(text=f"{len(items) - nv:,} photos · {nv:,} videos · from {src.label}")
        tmp = quicklook.private_dir()      # Q1: private, deleted when PhoneKeep closes

        def open_one(item):
            dest = tmp / item.name
            self.banner(f"Opening {item.name}…")
            self.live_runner.submit(lambda: src.copy(item.id, dest) and dest,
                                    lambda p: (self.banner(""), open_file(p)) if p else None,
                                    lambda e: self.banner(f"Couldn't open it: {describe_error(e)}", color=theme.ERROR_BG))
        def preview(shown, idx):
            def thumb(i):
                t = src.thumbnail(i)
                return t.read_bytes() if t else None
            quicklook.Viewer(self, [quicklook.Item(i.name + (" (only in iCloud: preview)" if i.cloud_only else ""),
                                                   read=(lambda i=i: thumb(i)) if i.cloud_only else (lambda i=i: src.read(i.id)),
                                                   to_file=lambda d, i=i: src.copy(i.id, d), size=i.size,
                                                   why=lambda: getattr(src, "last_error", None),
                                                   kind="video" if i.video else "")
                                    for i in shown], idx)
        panel = ui.PhotoPanel(self.content, src, items, select_all=False, on_open=open_one, on_preview=preview,
                              unlock=lambda go: self.app.confirm_private(go, "show your hidden photos"))
        panel.pack(fill="both", expand=True)

        def save():
            chosen = [i for i in items if i.id in panel.selected]
            if not chosen:
                messagebox.showinfo(wv.APP_NAME, "Click the photos you want to save first (or Select all).", parent=self)
                return
            compatible = ui.ask_photo_format(self, 1 if self.app.s.data.get("photos_jpg") else 0)
            if compatible is None:
                return
            self.app.s["photos_jpg"] = compatible               # remembered for next time
            folder = self.out_dir("photos")
            if folder is None:
                return

            def go():
                import photoconv
                done = []
                conv_tmp = quicklook.private_tmp("phonekeep-heic-")
                try:
                    for i in chosen:
                        month = i.when.strftime("%Y-%m") if i.when.year > 1970 else "Unknown date"
                        done += photoconv.save_item(src, i, folder / month, compatible, conv_tmp)
                finally:
                    shutil.rmtree(conv_tmp, ignore_errors=True)
                return done
            self.run_save(f"{len(chosen):,} photos & videos", go, folder, "photo/video",
                          self.live_runner if src.label == "the iPhone" else self.backup_runner)
        RoundButton(panel.foot, "Save selected", save, "primary", 170, 38, 12).pack(side="right")
        tk.Label(panel.foot, text="Space: preview", bg=BG, fg=MUTED,
                 font=font(11)).pack(side="right", padx=12)
        import cleanup_ui                                   # C1
        RoundButton(panel.foot, "Clean up", lambda: cleanup_ui.view(self, src, items), "secondary", 120, 38,
                    12).pack(side="left")
        card = getattr(self, "open_cleanup", None)          # asked for by the Storage card's suggestions (H2)
        if card is not None:
            self.open_cleanup = None
            self.after_idle(lambda: cleanup_ui.view(self, src, items, card or None))

    # tables -----------------------------------------------------------------------
    def table_view(self, key, headers: list, rows: list, widths: Optional[list] = None, actions=(),
                   on_double=None, multi=True, title_extra="", preview=None, find_row=lambda ref: ref):
        """A searchable, sortable table with Excel/CSV saving. actions: [(label, fn(selected rows))].
        preview(row) -> quicklook.Item: Space previews the selected row; the arrows go through the list (Q1)."""
        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="🔍", bg=BG, font=font(13)).pack(side="left")
        q = tk.StringVar()
        ttk.Entry(top, textvariable=q, width=32).pack(side="left", padx=(4, 10))
        count = tk.Label(top, text="", bg=BG, fg=MUTED, font=font(12))
        count.pack(side="left")
        frame = card(self.content)
        frame.pack(fill="both", expand=True)
        cols = [f"c{i}" for i in range(len(headers))]
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended" if multi else "browse")
        state = {"rows": list(rows), "sort": None}
        for i, (c, h) in enumerate(zip(cols, headers)):
            tree.heading(c, text=h, command=lambda i=i: sort(i))
            tree.column(c, width=(widths[i] if widths and i < len(widths) else 140), stretch=True, anchor="w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ncol = len(headers)

        import search

        def shown() -> list:
            t = search.fold(q.get()).strip()
            return [r for r in state["rows"] if not t or any(t in search.fold(str(x)) for x in r[:ncol])]

        def fill(*_):
            tree.delete(*tree.get_children())
            vis = shown()
            for n, r in enumerate(vis[:20000]):
                tree.insert("", "end", iid=str(id(r)), values=[str(x).replace("\n", " · ") for x in r[:ncol]])
            more = f" (showing first 20,000)" if len(vis) > 20000 else ""
            count.configure(text=f"{len(vis):,} of {len(state['rows']):,}{more}{title_extra}")

        def sort(i):
            rev = state["sort"] == i
            state["rows"].sort(key=lambda r: str(r[i]).lower(), reverse=rev)
            state["sort"] = None if rev else i
            fill()
        q.trace_add("write", fill)
        fill()
        by_id = {str(id(r)): r for r in state["rows"]}

        def pick(ref):                      # E4: a search result chose this row (find_row: its place in `rows`)
            iid = str(id(rows[find_row(ref)]))
            if tree.exists(iid):
                tree.selection_set(iid)
                tree.see(iid)
        self.find_hook = (key, q, pick)

        def selected() -> list:
            return [by_id[i] for i in tree.selection() if i in by_id]
        if on_double:
            tree.bind("<Double-1>", lambda e: on_double(selected()))
        if preview:
            def make():
                vis = shown()
                sel = selected()
                idx = next((n for n, r in enumerate(vis) if sel and r is sel[0]), 0)
                lo = max(0, idx - 1000)
                return [preview(r) for r in vis[lo:idx + 1000]], idx - lo
            quicklook.bind_space(tree, make)
            self.table_preview = tree.quick_preview        # also reachable for the tests

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(10, 0))

        def save(kind):
            vis = selected() or shown()
            folder = self.out_dir(key)
            if folder is None:
                return
            stamp = dt.datetime.now().strftime("%Y-%m-%d %H%M")
            path = unique_path(folder / f"{LABEL[key]} {stamp}.{'xlsx' if kind == 'excel' else 'csv'}")

            def go():
                import tables as tb
                clean = [[str(x) for x in r[:ncol]] for r in vis]
                if kind == "excel":
                    tb.write_table_xlsx(path, LABEL[key], headers, clean)
                else:
                    tb.write_csv_rows(path, headers, clean)
                return [path]
            self.run_save(f"{len(vis):,} rows", go, folder, "file")
        RoundButton(foot, "Save as Excel", lambda: save("excel"), "primary", 150, 38, 12).pack(side="right")
        RoundButton(foot, "CSV", lambda: save("csv"), "secondary", 80, 38, 12).pack(side="right", padx=6)
        tk.Label(foot, text="Saves the selected rows, or everything shown", bg=BG, fg=MUTED,
                 font=font(11)).pack(side="right", padx=8)
        for label, fn in actions:
            RoundButton(foot, label, lambda fn=fn: fn(selected()), "secondary", 170, 38, 12).pack(side="left", padx=(0, 6))
        return tree, selected

    def v_calls(self, key, rows):
        missed = sum(1 for r in rows if r[1] == "Missed")
        self.view_sub.configure(text=f"{len(rows):,} calls · {missed:,} missed")
        self.table_view(key, sx.CALL_HEADERS, rows, [150, 80, 180, 140, 110, 70, 120],
                        actions=[("Contact card", lambda sel: self.open_card_for(sel[0][3] if sel else None, "call"))])

    def v_contacts(self, key, people):
        import contacts_ui
        contacts_ui.ContactsView(self, key, people)          # D1: photos, the phone's Lists, a contact card

    def v_calendar(self, key, events):
        self.view_sub.configure(text=f"{len(events):,} events")
        rows = [[sx.fmt(x["start"], not x["all_day"]), sx.fmt(x["end"], not x["all_day"]), x["title"], x["loc"],
                 x["cal"], x["desc"]] for x in events]
        self.table_view(key, ["Start", "End", "Event", "Location", "Calendar", "Notes"], rows,
                        [140, 140, 220, 160, 120, 200],
                        actions=[("Save as .ics calendar", lambda sel: self.export_section("calendar", {"web"}))])

    def v_safari(self, key, value):
        bm, hist = value
        self.view_sub.configure(text=f"{len(bm):,} bookmarks · {len(hist):,} history visits")
        rows = [["Bookmark", f, t, u] for f, t, u in bm] + [["Visited " + a, "", b, u] for a, b, u in hist]

        def open_url(sel):
            for r in sel[:5]:
                import webbrowser
                if str(r[3]).startswith(("http://", "https://")):
                    webbrowser.open(r[3])
        self.table_view(key, ["Kind", "Folder", "Title", "Address"], rows, [150, 120, 260, 360],
                        on_double=open_url, actions=[("Open in browser", open_url)],
                        find_row=lambda ref: ref[1] if ref[0] == "bookmark" else len(bm) + ref[1])

    def v_apps(self, key, apps):
        self.view_sub.configure(text=f"{len(apps):,} apps")
        rows = [[a, f"{n:,} files in backup"] for a, n in apps]
        self.table_view(key, ["App ID", "Data in backup"], rows, [380, 200])

    # all files (B5) -------------------------------------------------------------------
    DOMAIN_NAMES = {"HomeDomain": "Home (Messages, Contacts, Calendar, Notes…)", "CameraRollDomain": "Camera Roll (Photos & videos)",
                    "MediaDomain": "Media (attachments, voicemail, recordings)", "WirelessDomain": "Cellular & Wi-Fi",
                    "SystemPreferencesDomain": "System settings", "KeychainDomain": "Keychain", "HealthDomain": "Health",
                    "RootDomain": "Root", "DatabaseDomain": "Databases", "KeyboardDomain": "Keyboard", "ManagedPreferencesDomain": "Managed preferences",
                    "MobileDeviceDomain": "Mobile device", "InstallDomain": "Install", "TonesDomain": "Ringtones", "BooksDomain": "Books",
                    "HomeKitDomain": "HomeKit", "NetworkDomain": "Network", "ProtectedDomain": "Protected", "SysSharedContainerDomain": "Shared containers"}

    def domain_title(self, domain: str) -> str:
        if domain in self.DOMAIN_NAMES:
            return self.DOMAIN_NAMES[domain]
        for prefix, label in (("AppDomain-", "App: "), ("AppDomainGroup-", "App group: "), ("AppDomainPlugin-", "App plug-in: "),
                              ("SysContainerDomain-", "System container: "), ("SysSharedContainerDomain-", "System shared: ")):
            if domain.startswith(prefix):
                return label + domain[len(prefix):]
        return domain

    def v_allfiles(self, key, domains):
        total = self.counts.get("allfiles", "")
        self.view_sub.configure(text=f"{len(domains):,} areas · {total} · this backup as folders")
        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="🔍", bg=BG, font=font(13)).pack(side="left")
        q = tk.StringVar()
        ttk.Entry(top, textvariable=q, width=32).pack(side="left", padx=4)
        tk.Label(top, text="F3: a name, or * for anything (*.pdf, invoice*) · Double-click or Space to preview · "
                           "click, then Save", bg=BG, fg=MUTED, font=font(11)).pack(side="left", padx=10)
        box = card(self.content)
        box.pack(fill="both", expand=True)
        tree = ttk.Treeview(box, columns=("size", "date"), selectmode="extended")
        tree.heading("#0", text="Folder / file")
        tree.heading("size", text="Size")
        tree.heading("date", text="Modified")
        tree.column("#0", width=520, stretch=True)
        tree.column("size", width=100, anchor="e", stretch=False)
        tree.column("date", width=150, stretch=False)
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        sb.pack(side="left", fill="y", pady=4)
        # F3: while there's a search, its results replace the folders: where, path, size, date
        hits = ttk.Treeview(box, columns=("area", "path", "size", "date"), show="headings", selectmode="extended")
        for c, h, w in (("area", "Area", 200), ("path", "Path", 440), ("size", "Size", 90), ("date", "Modified", 140)):
            hits.heading(c, text=h)
            hits.column(c, width=w, stretch=(c == "path"), anchor="e" if c == "size" else "w")
        hmeta: dict = {}      # iid -> ("file", domain, rel, size, mtime), as `meta` has for the folders' files
        self.allfiles_hits = hits                 # for the tests
        meta: dict = {}       # iid -> (domain, rel, size, mtime) for files
        loaded: set = set()
        import device as devmod

        order = sorted(domains, key=lambda d: (d not in self.DOMAIN_NAMES, self.domain_title(d).lower()))
        for d in order:
            iid = tree.insert("", "end", text="📁 " + self.domain_title(d), values=("", ""), open=False)
            meta[iid] = ("domain", d)
            tree.insert(iid, "end", text="…")          # placeholder so the arrow shows

        def add_folder_tree(parent_iid, domain, files: dict):
            """files: rel -> (fid, mtime, size). Builds nested folders lazily into the tree."""
            folders: dict = {}
            for rel, (fid, mtime, size) in sorted(files.items()):
                parts = rel.split("/")
                node = parent_iid
                path = ""
                for part in parts[:-1]:
                    path = f"{path}/{part}" if path else part
                    k = (node, path)
                    if k not in folders:
                        folders[k] = tree.insert(node, "end", text="📁 " + part, values=("", ""), open=False)
                        meta[folders[k]] = ("folder", domain, path)
                    node = folders[k]
                fiid = tree.insert(node, "end", text="📄 " + parts[-1],
                                   values=(devmod.human_size(size or 0), dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""))
                meta[fiid] = ("file", domain, rel, size or 0, mtime)

        def on_open(_e):
            iid = tree.focus()
            if iid in loaded or meta.get(iid, ("",))[0] != "domain":
                return
            loaded.add(iid)
            for ch in tree.get_children(iid):
                tree.delete(ch)
            domain = meta[iid][1]
            files = self.data.reader.file_meta(domain)
            add_folder_tree(iid, domain, files)
            if not files:
                tree.insert(iid, "end", text="(no files)")
        tree.bind("<<TreeviewOpen>>", on_open)

        def selected_files() -> list:
            if searching():
                return [hmeta[i] for i in hits.selection() if i in hmeta]
            out = []

            def walk(iid):
                m = meta.get(iid)
                if m and m[0] == "file":
                    out.append(m)
                elif m and m[0] == "domain" and iid not in loaded:
                    for rel, (fid, mtime, size) in self.data.reader.file_meta(m[1]).items():
                        out.append(("file", m[1], rel, size or 0, mtime))
                else:
                    for ch in tree.get_children(iid):
                        walk(ch)
            for iid in tree.selection():
                walk(iid)
            return out

        def preview(_e=None):
            """Q1: Space, Return or double-click previews the file; the arrows go through its folder (or, F3,
            through the search's results)."""
            if searching():
                sel = [i for i in hits.selection() if i in hmeta]
                siblings, where, view = list(hits.get_children("")), hmeta, hits
            else:
                sel = [i for i in tree.selection() if meta.get(i, ("",))[0] == "file"]
                siblings = [i for i in tree.get_children(tree.parent(sel[0])) if meta.get(i, ("",))[0] == "file"] \
                    if sel else []
                where, view = meta, tree
            if not sel:
                return "break"
            siblings = [i for i in siblings if i in where][:2000]
            if sel[0] not in siblings:
                siblings = [sel[0]] + siblings
            items = []
            for i in siblings:
                _k, domain, rel, size, _mtime = where[i]
                items.append(quicklook.Item(Path(rel).name, read=lambda d=domain, r=rel: self.data.read(d, r),
                                            why=lambda: getattr(self.data.reader, "last_error", None),
                                            to_file=lambda dest, d=domain, r=rel: self.data.copy(d, r, dest), size=size))
            self.allfiles_viewer = quicklook.Viewer(self, items, siblings.index(sel[0]),
                                                    on_close=lambda: view.focus_set())
            return "break"
        for w in (tree, hits):
            w.bind("<Double-Button-1>", preview)
            w.bind("<space>", preview)
            w.bind("<Return>", preview)
        self.allfiles_preview = preview           # also reachable for the tests

        import filesearch
        look = {"gen": 0, "after": None}

        def searching() -> bool:
            return bool(hits.winfo_manager())

        def show_folders():
            if searching():
                hits.pack_forget()
                tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4, before=sb)
                sb.configure(command=tree.yview)
            foot_count.configure(text="")

        def search(*_):
            """F3: the backup's file names (or paths) that match, found on the backup reader's thread a moment
            after the typing stops; a newer search makes an older one's results go unshown."""
            if look["after"]:
                self.after_cancel(look["after"])
            look["after"] = self.after(300, run_search)

        def run_search():
            look["after"] = None
            if not hits.winfo_exists():           # the view was left while the typing pause ran
                return
            look["gen"] += 1
            gen = look["gen"]
            pat = filesearch.Pattern(q.get())
            if not pat:
                show_folders()
                return
            foot_count.configure(text="Searching…")
            data = self.data                      # its file_meta holds the backup's lock (closing the window can't
            doms = [meta[i][1] for i in tree.get_children("") if meta.get(i, ("",))[0] == "domain"]   # pull it away)
            self.backup_runner.submit(
                lambda: filesearch.in_backup(data.file_meta, doms, pat, stop=lambda: gen != look["gen"]),
                lambda res: show_hits(gen, *res), lambda e: foot_count.configure(text=f"Couldn't search: {describe_error(e)}"))

        def show_hits(gen, found, total):
            if gen != look["gen"]:
                return
            if not searching():
                tree.pack_forget()
                hits.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4, before=sb)
                sb.configure(command=hits.yview)
                hits.configure(yscrollcommand=sb.set)
            hits.delete(*hits.get_children())
            hmeta.clear()
            for n, (domain, rel, size, mtime) in enumerate(found):
                iid = f"h{n}"
                hmeta[iid] = ("file", domain, rel, size, mtime)
                hits.insert("", "end", iid=iid, values=(
                    self.domain_title(domain), rel, devmod.human_size(size or 0),
                    dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""))
            more = f" (the first {len(found):,} shown)" if total > len(found) else ""
            foot_count.configure(text=(f"{total:,} file{'s' if total != 1 else ''} match{'' if total != 1 else 'es'}"
                                       f"{more}" if total else "No file matches. * matches anything: *.pdf, invoice*"))
        q.trace_add("write", search)
        hits.bind("<Destroy>", lambda e: look["after"] and self.after_cancel(look["after"]))
        self.allfiles_search = run_search         # the tests run it at once instead of waiting for the typing pause
        self.allfiles_q = q

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(6, 0))
        foot_count = tk.Label(foot, text="", bg=BG, fg=MUTED, font=font(12))
        foot_count.pack(side="left")

        def update_count(_e=None):
            if searching():
                files, folders = [hmeta[i] for i in hits.selection() if i in hmeta], []
            else:
                files = [m for m in (meta.get(i) for i in tree.selection()) if m and m[0] == "file"]
                folders = [i for i in tree.selection() if meta.get(i, ("",))[0] in ("domain", "folder")]
            size = sum(m[3] for m in files)
            foot_count.configure(text=(f"{len(files):,} file{'s' if len(files) != 1 else ''} · {devmod.human_size(size)}" if files else "")
                                 + (f" · {len(folders)} folder{'s' if len(folders) != 1 else ''}" if folders else ""))
        tree.bind("<<TreeviewSelect>>", update_count)
        hits.bind("<<TreeviewSelect>>", update_count)

        def save():
            items = selected_files()
            if not items:
                messagebox.showinfo(wv.APP_NAME, "Click a file or a folder first (Cmd/Ctrl-click for several).", parent=self)
                return
            out = self.out_dir("allfiles")
            if out is None:
                return
            data = self.data

            def go():
                paths = []
                for _k, domain, rel, size, mtime in items:
                    dest = wv.safe_join(out / self.domain_title(domain).split(" (")[0].replace(": ", "-"), rel)
                    if dest is None:
                        continue
                    paths.append(dest if data.copy(domain, rel, dest) else None)
                return paths
            self.run_save(f"{len(items):,} files", go, out, "file")
        RoundButton(foot, "Save selected", save, "primary", 170, 38, 12).pack(side="right")
        tree.focus_set()

    # notes ------------------------------------------------------------------------
    def v_notes(self, key, notes):
        self.view_sub.configure(text=f"{len(notes):,} notes")
        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="🔍", bg=BG, font=font(13)).pack(side="left")
        q = tk.StringVar()
        ttk.Entry(top, textvariable=q, width=32).pack(side="left", padx=4)
        pane = tk.PanedWindow(self.content, orient="horizontal", sashwidth=6, bg=BG, bd=0)
        pane.pack(fill="both", expand=True)
        # D4: the phone's folders (Pinned first, Recently Deleted last), the notes in the one chosen, the note
        ff = card(pane)
        folders = tk.Listbox(ff, activestyle="none", relief="flat", highlightthickness=0, bd=0, exportselection=False,
                             bg=CARD, fg=INK, selectbackground=theme.ACCENT_PALE, selectforeground=INK, font=font(13))
        folders.pack(fill="both", expand=True, padx=4, pady=6)
        pane.add(ff, minsize=150, width=190)
        lf = card(pane)
        tree = ttk.Treeview(lf, columns=("t", "m"), show="headings", selectmode="browse")
        for c, h, w in (("t", "Title", 230), ("m", "Edited", 120)):
            tree.heading(c, text=h)
            tree.column(c, width=w, stretch=(c == "t"))
        tree.pack(fill="both", expand=True)
        pane.add(lf, minsize=300, width=360)
        rf = card(pane)
        title = tk.Label(rf, text="", bg=CARD, fg=INK, font=font(16, "bold"), anchor="w")
        title.pack(fill="x", padx=14, pady=(10, 0))
        meta = tk.Label(rf, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        meta.pack(fill="x", padx=14)
        txt = tk.Text(rf, wrap="word", relief="flat", font=font(13), padx=12, pady=8, bg=theme.NOTE_BG,
                      fg=INK, insertbackground=INK, highlightthickness=0)
        txt.pack(fill="both", expand=True, padx=2, pady=6)
        pane.add(rf, minsize=320)

        import search
        import notes_ui

        def open_attachment(a):
            dom, rel = a["file"]
            quicklook.Viewer(self, [quicklook.Item(a.get("name") or Path(rel).name,
                                                   read=lambda: self.data.read(dom, rel) if self.data else None,
                                                   to_file=lambda dest: bool(self.data) and self.data.copy(dom, rel, dest),
                                                   why=lambda: getattr(self.data.reader, "last_error", None)
                                                   if self.data else None)], 0)
        view = notes_ui.NoteView(txt, lambda d, r: self.data.read(d, r) if self.data else None, open_attachment,
                                 lambda fn, ok: self.backup_runner.submit(fn, ok, lambda e: ok(None)))
        self.note_view = view                                    # for the tests

        live = [n for n in notes if not n.get("deleted")]
        places = [("all", "All notes", len(live))]
        if any(n.get("pinned") for n in live):
            places.append(("pinned", "📌 Pinned", sum(1 for n in live if n.get("pinned"))))
        for name in sorted({n["folder"] for n in live}, key=str.lower):
            places.append(("folder:" + name, name, sum(1 for n in live if n["folder"] == name)))
        if len(live) < len(notes):
            places.append(("deleted", "🗑 " + sx.RECENTLY_DELETED, len(notes) - len(live)))
        for _k, label, n in places:
            folders.insert("end", f"{label}  ({n:,})")
        place = {"key": "all"}

        def in_place(n) -> bool:
            k = place["key"]
            if k == "deleted":
                return bool(n.get("deleted"))
            if n.get("deleted"):
                return False
            return k == "all" or (k == "pinned" and n.get("pinned")) or k == "folder:" + n["folder"]

        def fill(*_):
            t = search.fold(q.get()).strip()
            tree.delete(*tree.get_children())
            rows = [(i, n) for i, n in enumerate(notes) if in_place(n)]
            rows.sort(key=lambda r: not r[1].get("pinned"))         # pinned first, as on the phone
            for i, n in rows:
                if t and t not in search.fold(n["title"] + " " + (n["text"] or "")):
                    continue
                tree.insert("", "end", iid=str(i), values=(("🔒 " if n["locked"] else "📌 " if n.get("pinned") else "")
                                                           + n["title"], sx.fmt(n["modified"])))
            kids = tree.get_children()
            if kids and not tree.selection():
                tree.selection_set(kids[0])
            elif not kids:
                view.clear()
                txt.configure(state="disabled")
                title.configure(text="")
                meta.configure(text="")

        def choose(idx: int):
            folders.selection_clear(0, "end")
            folders.selection_set(idx)
            folders.see(idx)
            place["key"] = places[idx][0]
            fill()

        def on_folder(_e=None):
            s = folders.curselection()
            if s and places[s[0]][0] != place["key"]:
                choose(s[0])

        def show(*_):
            s = tree.selection()
            if not s:
                return
            n = notes[int(s[0])]
            title.configure(text=n["title"])
            meta.configure(text=f"{n['folder']} · created {sx.fmt(n['created'])} · edited {sx.fmt(n['modified'])}")
            view.show(n)

        def jump(ref):
            n = notes[int(ref)]
            want = "deleted" if n.get("deleted") else "all"
            if place["key"] != want or (q.get() and str(ref) not in tree.get_children()):
                choose(next(i for i, p in enumerate(places) if p[0] == want))
            if str(ref) in tree.get_children():
                tree.selection_set(str(ref))
                tree.see(str(ref))
        q.trace_add("write", fill)
        tree.bind("<<TreeviewSelect>>", show)
        folders.bind("<<ListboxSelect>>", on_folder)
        folders.selection_set(0)
        fill()
        self.find_hook = (key, q, jump)
        self.notes_folders = (folders, places, choose)            # for the tests

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(10, 0))

        def chosen():
            s = tree.selection()
            return notes[int(s[0])] if s else None

        def save_one():
            n = chosen()
            if n is None:
                return
            if n["locked"]:
                messagebox.showinfo(wv.APP_NAME, "This note is locked with your Notes password.", parent=self)
                return
            folder = self.out_dir("notes")
            if folder is None:
                return
            p = unique_path(folder / (sx.safe_name(n["title"], 80) + ".txt"))
            p.write_text(n["text"] or "", encoding="utf-8")
            self.saved([p], folder, "note")

        def save_pdf(which: list, name: str):
            if not which:
                return
            which = [n for n in which if not n["locked"]]
            if not which:
                messagebox.showinfo(wv.APP_NAME, "Nothing to save: these notes are locked with your Notes password.",
                                    parent=self)
                return
            folder = self.out_dir("notes")
            if folder is None:
                return
            import notes_pdf
            dest = unique_path(folder / (sx.safe_name(name, 80) + ".pdf"))
            read = (lambda d, r: self.data.read(d, r) if self.data else None)

            def write():
                notes_pdf.write_notes_pdf(which, dest, read, name)
                return [dest] * len(which)                      # "Saved 3 notes": one PDF holds them all
            self.run_save(dest.name, write, folder, "note")
        self.notes_save_pdf = save_pdf                            # for the tests

        def save_one_pdf():
            n = chosen()
            if n is None:
                return
            if n["locked"]:
                messagebox.showinfo(wv.APP_NAME, "This note is locked with your Notes password.", parent=self)
                return
            save_pdf([n], n["title"])

        def save_shown_pdf():
            shown = [notes[int(i)] for i in tree.get_children()]
            save_pdf(shown, places[folders.curselection()[0]][1].lstrip("📌🗑 ") if folders.curselection()
                     else "Notes")
        RoundButton(foot, "Save all notes", lambda: self.export_section("notes", {"web"}), "primary", 160, 38, 12).pack(side="right")
        RoundButton(foot, "Save these as PDF", save_shown_pdf, "secondary", 170, 38, 12).pack(side="right", padx=6)
        RoundButton(foot, "Save this note (.txt)", save_one, "secondary", 190, 38, 12).pack(side="right")
        RoundButton(foot, "Save this note as PDF", save_one_pdf, "secondary", 200, 38, 12).pack(side="right", padx=6)

    # audio ----------------------------------------------------------------------
    @staticmethod
    def _preview_from(getter):
        """Q1 for lists of recordings, songs and books: Space shows the item with a Play / Open button."""
        def item(r):
            copy, name = getter(r)[:2]
            return quicklook.Item(name, to_file=copy)
        return item

    def _audio_actions(self, key, getter):
        """getter(row) -> (copy function(dest) -> bool, file name[, where Save puts it inside the chosen folder,
        e.g. Artist/Album/01 Song.m4a, and the copy function Save uses]). Returns Play/Save actions."""
        tmp = quicklook.private_dir()      # Q1: private, deleted when PhoneKeep closes

        def play(sel):
            if not sel:
                messagebox.showinfo(wv.APP_NAME, "Select something to play first.", parent=self)
                return
            copy, name = getter(sel[0])[:2]
            dest = tmp / name
            runner = self.live_runner if key in ("music", "books") else self.backup_runner
            self.banner(f"Opening {name}…")
            runner.submit(lambda: copy(dest) and dest, lambda p: (self.banner(""), open_file(p)) if p else
                          self.banner("That file isn't available.", color=theme.ERROR_BG),
                          lambda e: self.banner(f"Couldn't open it: {describe_error(e)}", color=theme.ERROR_BG))

        def save(sel):
            if not sel:
                messagebox.showinfo(wv.APP_NAME, "Select what to save first (Cmd/Ctrl-click for several, "
                                    "Cmd/Ctrl-A for all).", parent=self)
                return
            folder = self.out_dir(key)
            if folder is None:
                return

            def go():
                done = []
                for r in sel:
                    copy, name, *more = getter(r)
                    if len(more) > 1:
                        copy = more[1]
                    dest = unique_path(folder / (more[0] if more else name))
                    try:
                        if copy(dest):
                            done.append(dest)
                    except OSError as e:          # this one's name or place the disk refuses: save the others
                        if not more:
                            raise
                        skipped.append((name, describe_error(e)))
                return done
            skipped: list = []
            self.save_skipped = skipped
            self.run_save(f"{len(sel):,} item(s)", go, folder, "file",
                          self.live_runner if key in ("music", "books") else self.backup_runner)
        return play, save

    def v_voicemail(self, key, items):
        self.view_sub.configure(text=f"{len(items):,} voicemails")
        rows = [[sx.fmt(v["when"]), v["name"], v["number"], sx.dur(v["length"]), "deleted" if v["deleted"] else "",
                 v] for v in items]

        def getter(r):
            v = r[5]
            name = sx.safe_name(f"{sx.fmt(v['when'])} {v['name']}", 80).replace(":", ".") + Path(v["rel"] or ".amr").suffix
            return (lambda dest: bool(v["rel"]) and self.data.copy(sx.HOME, v["rel"], dest)), name
        play, save = self._audio_actions(key, getter)
        self.table_view(key, ["Date", "From", "Number", "Length", "Status"], [r for r in rows],
                        [150, 200, 150, 80, 80], on_double=play, preview=self._preview_from(getter),
                        actions=[("▶  Play", play), ("Save selected", save),
                                 ("Contact card", lambda sel: self.open_card_for(sel[0][5]["number"] if sel else None,
                                                                   "voicemail"))])

    def v_voicememos(self, key, items):
        self.view_sub.configure(text=f"{len(items):,} recordings")
        rows = [[sx.fmt(m["when"]), m["title"], sx.dur(m["length"]), m] for m in items]

        def getter(r):
            m = r[3]
            when = m["when"].strftime("%Y-%m-%d %H%M ") if m["when"] else ""
            name = sx.safe_name(when + m["title"], 100) + Path(m["rel"]).suffix
            return (lambda dest: self.data.copy(m["domain"], m["rel"], dest)), name
        play, save = self._audio_actions(key, getter)
        self.table_view(key, ["Date", "Title", "Length"], rows, [160, 360, 90], on_double=play,
                        preview=self._preview_from(getter),
                        actions=[("▶  Play", play), ("Save selected", save)])

    def v_callrecordings(self, key, items):
        """D6: who, when, how long; Play; the selected call's transcript under the list; Save puts the audio and,
        when the phone made one, the transcript (.txt) side by side."""
        self.view_sub.configure(text=f"{len(items):,} recording{'s' if len(items) != 1 else ''}")
        rows = [[sx.fmt(c["when"]), c["title"], sx.dur(c["length"]) if c["length"] else "",
                 "yes" if c["transcript"] else "", c] for c in items]

        def getter(r):
            c = r[4]
            name = c["base"] + (Path(c["file"][1]).suffix if c["file"] else ".m4a")      # its own, one per recording

            def audio(dest):
                return bool(c["file"]) and self.data.copy(*c["file"], dest)

            def with_text(dest):
                if not audio(dest):
                    return False
                if c["transcript"]:
                    unique_path(dest.with_suffix(".txt")).write_text(c["transcript"] + "\n", encoding="utf-8")
                return True
            return audio, name, name, with_text
        play, save = self._audio_actions(key, getter)
        tree, selected = self.table_view(key, ["Date", "Call", "Length", "Transcript"], rows, [160, 340, 80, 90],
                                         on_double=play, preview=self._preview_from(getter),
                                         actions=[("▶  Play", play), ("Save selected", save)])
        box = card(self.content)
        box.pack(fill="x", pady=(10, 0))
        tk.Label(box, text="Transcript", bg=CARD, fg=INK, font=font(13, "bold"), anchor="w").pack(fill="x", padx=12,
                                                                                               pady=(10, 2))
        said = tk.Text(box, height=6, wrap="word", bg=CARD, fg=INK, relief="flat", font=font(12),
                       highlightthickness=0, padx=12, pady=4)
        said.pack(fill="x", padx=0, pady=(0, 10))
        self.call_transcript = said                        # for the tests

        def show(_e=None):
            sel = selected()
            text = ("Select a recording to see its transcript." if not sel else
                    sel[0][4]["transcript"] or "The iPhone made no transcript of this call.")
            said.configure(state="normal")
            said.delete("1.0", "end")
            said.insert("1.0", text)
            said.configure(state="disabled")
        tree.bind("<<TreeviewSelect>>", show, add="+")
        show()

    def v_music(self, key, tracks):
        import device as devmod
        import music_tags
        total = sum(t.size for t in tracks)
        self.view_sub.configure(text=f"{len(tracks):,} items on the iPhone · {devmod.human_size(total)}")
        n = getattr(tracks, "streaming", 0)      # P2: in the library, but no file on the phone
        self.music_note = (f"{n:,} more song{'s' if n != 1 else ''} in the Music library "
                           f"{'are' if n != 1 else 'is'} not listed: only songs stored on the iPhone can be copied, "
                           "and these stream from Apple Music or iCloud." if n else "")
        if not tracks:
            holder = self.loading("")
            self.failed(holder, "No music is stored on this iPhone. Songs that only stream from Apple Music "
                                "aren't on the phone, so they can't be copied."
                        + (f" ({n:,} song{'s' if n != 1 else ''} in the library stream{'' if n != 1 else 's'} "
                           "this way.)" if n else ""))
            return
        rows = [[t.title, t.artist, t.album, sx.dur(t.seconds) if t.seconds else "", t.kind,
                 devmod.human_size(t.size), t] for t in tracks]

        def getter(r):
            t = r[6]
            name = sx.safe_name(" - ".join(x for x in (t.artist, t.title) if x) or Path(t.path).stem, 120) + Path(t.path).suffix
            return ((lambda dest: self.live.copy_media(t.path, dest)), name, music_tags.save_path(t),
                    lambda dest: self.live.copy_song(t, dest))
        play, save = self._audio_actions(key, getter)
        # P2: the chosen song's artwork and details, on the right
        side = card(self.content)
        side.pack(side="right", fill="y", padx=(10, 0))
        art = tk.Label(side, text="🎵", bg=theme.TILE_BG, fg=MUTED, font=font(54), width=4, height=2)
        art.pack(padx=14, pady=(14, 8))
        info = tk.Label(side, text="Choose a song to see its artwork.", bg=CARD, fg=INK, font=font(12),
                        justify="left", anchor="nw", wraplength=200)
        info.pack(fill="x", padx=14)
        for text in ([self.music_note] if self.music_note else []) + [
                "Save selected puts each song in an Artist / Album folder, with its title, artist, album and "
                "artwork written into the file."]:
            tk.Label(side, text=text, bg=CARD, fg=MUTED, font=font(11), justify="left", anchor="nw",
                     wraplength=200).pack(fill="x", padx=14, pady=(12, 0))
        covers: dict = {}
        self.music_art, self.music_info, self.music_shown = art, info, None

        def show_art(t, data):
            covers[t.artwork] = data
            if self.music_shown is not t or not art.winfo_exists():
                return
            img = None
            if data:
                try:
                    from PIL import Image, ImageTk
                    with Image.open(io.BytesIO(data)) as im:
                        im = im.convert("RGB")
                        im.thumbnail((200, 200))
                        img = ImageTk.PhotoImage(im)
                except Exception:
                    img = None
            if img is not None:
                art.configure(image=img, text="", width=img.width(), height=img.height())
            else:
                art.configure(image="", text="🎵", width=4, height=2)
            art.image = img

        def picked(_e=None):
            sel = selected()
            if not sel:
                return
            t = sel[0][6]
            self.music_shown = t
            info.configure(text="\n".join(x for x in (t.title, t.artist, t.album, " · ".join(
                y for y in (t.genre, str(t.year) if t.year else "") if y)) if x))
            if not t.artwork or t.artwork in covers:
                show_art(t, covers.get(t.artwork))
            else:
                self.live_runner.submit(lambda: self.live.artwork(t), lambda d: show_art(t, d),
                                        lambda e: show_art(t, None))
        tree, selected = self.table_view(key, ["Title", "Artist", "Album", "Length", "Kind", "Size"], rows,
                                         [240, 170, 170, 70, 90, 80], on_double=play,
                                         preview=self._preview_from(getter),
                                         actions=[("▶  Play", play), ("Save selected", save)],
                                         title_extra=" · purchased songs may only play on your own devices")
        tree.bind("<<TreeviewSelect>>", picked, add="+")

    def v_books(self, key, books):
        import device as devmod
        self.view_sub.configure(text=f"{len(books):,} books & PDFs on the iPhone")
        if not books:
            holder = self.loading("")
            self.failed(holder, "No books or PDFs are stored on this iPhone (books kept only in iCloud aren't on the phone).")
            return
        rows = [[b.title, b.author, b.kind, devmod.human_size(b.size) if b.size and not b.is_dir else "", b] for b in books]

        def getter(r):
            b = r[4]
            ext = ".epub" if b.kind == "EPUB" else Path(b.path).suffix
            name = sx.safe_name(" - ".join(x for x in (b.author, b.title) if x), 120) + ext
            return (lambda dest: self.live.copy_media(b.path, dest, b.is_dir)), name
        play, save = self._audio_actions(key, getter)
        self.table_view(key, ["Title", "Author", "Kind", "Size"], rows, [320, 220, 90, 90], on_double=play,
                        preview=self._preview_from(getter),
                        actions=[("Open", play), ("Save selected", save)])

    # app files ------------------------------------------------------------------------
    def v_files(self, key, apps):
        sharing = [a for a in apps if a.shares_files]
        self.view_sub.configure(text=f"{len(sharing):,} apps share files · {len(apps):,} apps installed")
        # F3: one search across every app that shares files (their Documents on the phone, read-only)
        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="🔍", bg=BG, font=font(13)).pack(side="left")
        fq = tk.StringVar()
        fent = ttk.Entry(top, textvariable=fq, width=32)
        fent.pack(side="left", padx=4)
        tk.Label(top, text="Search all apps' files: a name, or * for anything (*.pdf, invoice*), then Return",
                 bg=BG, fg=MUTED, font=font(11)).pack(side="left", padx=10)
        pane = tk.PanedWindow(self.content, orient="horizontal", sashwidth=6, bg=BG, bd=0)
        pane.pack(fill="both", expand=True)
        lf = card(pane)
        alist = ttk.Treeview(lf, columns=("n",), show="", selectmode="browse")
        alist.column("n", width=230)
        alist.pack(fill="both", expand=True)
        for a in apps:
            alist.insert("", "end", iid=a.id, values=(("📁 " if a.shares_files else "   ") + a.name,),
                         tags=() if a.shares_files else ("dim",))
        alist.tag_configure("dim", foreground=MUTED)
        pane.add(lf, minsize=220, width=270)
        rf = card(pane)
        crumbs = tk.Label(rf, text="Choose an app on the left", bg=CARD, fg=INK, font=font(13, "bold"), anchor="w")
        crumbs.pack(fill="x", padx=12, pady=(10, 4))
        files = ttk.Treeview(rf, columns=("n", "s", "d"), show="headings", selectmode="extended")
        for c, h, w in (("n", "Name", 320), ("s", "Size", 90), ("d", "Modified", 150)):
            files.heading(c, text=h)
            files.column(c, width=w, stretch=(c == "n"))
        files.pack(fill="both", expand=True, padx=4, pady=4)
        pane.add(rf, minsize=420)
        state = {"app": None, "path": "Documents", "entries": {}, "hit_app": {}, "gen": 0}
        by_id = {a.id: a for a in apps}
        import device as devmod

        def load(app_id, path):
            a = by_id[app_id]
            state["gen"] += 1                       # a search still running is no longer shown
            state["hit_app"] = {}
            state["app"], state["path"] = app_id, path
            crumbs.configure(text=f"{a.name}  ›  " + "  ›  ".join(path.split("/")))
            files.delete(*files.get_children())
            if not a.shares_files:
                files.insert("", "end", values=("This app doesn't share its files with computers.", "", ""))
                return
            files.insert("", "end", iid="__loading", values=("Loading…", "", ""))
            self.live_runner.submit(lambda: self.live.app_list(app_id, path), lambda es: show(app_id, path, es),
                                    lambda e: show_err(e))

        def show(app_id, path, entries):
            if (state["app"], state["path"]) != (app_id, path):
                return
            files.delete(*files.get_children())
            state["entries"] = {}
            if "/" in path:
                files.insert("", "end", iid="__up", values=("⬆  ..", "", ""))
            for e in entries:
                iid = f"e{len(state['entries'])}"
                state["entries"][iid] = e
                files.insert("", "end", iid=iid, values=(("📁 " if e.is_dir else "📄 ") + e.name,
                                                         "" if e.is_dir else devmod.human_size(e.size),
                                                         e.when.strftime("%Y-%m-%d %H:%M") if e.when else ""))
            if not entries:
                files.insert("", "end", values=("(empty)", "", ""))

        def show_err(e):
            files.delete(*files.get_children())
            files.insert("", "end", values=(describe_error(e)[:120], "", ""))

        def app_of(iid):
            return state["hit_app"].get(iid, state["app"])

        def find(_e=None):
            """F3: every sharing app's files whose name (or path) matches, walked on the phone's own thread."""
            import filesearch
            pat = filesearch.Pattern(fq.get())
            if not pat:
                return
            state["gen"] += 1
            gen = state["gen"]
            alist.selection_remove(*alist.selection())
            state["app"], state["entries"], state["hit_app"] = None, {}, {}
            crumbs.configure(text=f"Searching the apps' files for “{pat.query}”…")
            files.delete(*files.get_children())
            files.insert("", "end", iid="__loading", values=("Searching…", "", ""))

            def progress(i, n, name):
                self.live_runner.on_ui(lambda: gen == state["gen"] and crumbs.configure(
                    text=f"Searching the apps' files for “{pat.query}”… {name} ({i + 1} of {n})"))
            stop = lambda: gen != state["gen"]
            self.live_runner.submit(
                lambda: filesearch.in_apps(lambda b: self.live.app_walk(b, stop=stop), apps, pat, stop=stop,
                                           progress=progress),
                lambda res: show_hits(gen, pat, *res), lambda e: gen == state["gen"] and show_err(e))

        def show_hits(gen, pat, found, total, failed):
            if gen != state["gen"]:
                return
            files.delete(*files.get_children())
            state["entries"], state["hit_app"] = {}, {}
            for a, e in found:
                iid = f"e{len(state['entries'])}"
                state["entries"][iid] = e
                state["hit_app"][iid] = a.id
                where = e.path[len("Documents/"):] if e.path.startswith("Documents/") else e.path
                files.insert("", "end", iid=iid, values=(f"📄 {a.name}  ›  {where}", devmod.human_size(e.size),
                                                         e.when.strftime("%Y-%m-%d %H:%M") if e.when else ""))
            more = f", the first {len(found):,} shown" if total > len(found) else ""
            left = f" · couldn't read {', '.join(failed[:3])}" if failed else ""
            crumbs.configure(text=(f"{total:,} file{'s' if total != 1 else ''} match “{pat.query}”{more}{left}"
                                   if total else f"No file matches “{pat.query}”. * matches anything: *.pdf{left}"))
        fent.bind("<Return>", find)
        self.files_search = (fq, find)            # for the tests

        def dbl(_e=None):
            s = files.selection()
            if not s:
                return
            if s[0] == "__up":
                load(state["app"], state["path"].rsplit("/", 1)[0])
                return
            e = state["entries"].get(s[0])
            if e is not None and e.is_dir:
                load(app_of(s[0]), e.path)
            elif e is not None:
                tmp = quicklook.private_tmp("phonekeep-file-")
                self.banner(f"Opening {e.name}…")
                owner = app_of(s[0])
                self.live_runner.submit(lambda: self.live.app_pull(owner, e.path, tmp) and tmp / e.name,
                                        lambda p: (self.banner(""), open_file(p)) if p else None,
                                        lambda err: self.banner(f"Couldn't open it: {describe_error(err)}", color=theme.ERROR_BG))
        alist.bind("<<TreeviewSelect>>", lambda e: alist.selection() and load(alist.selection()[0], "Documents"))
        files.bind("<Double-1>", dbl)
        # F3: leaving App Files stops a search still walking the phone (it holds the phone for Music and Books)
        files.bind("<Destroy>", lambda e: state.__setitem__("gen", state["gen"] + 1), add="+")
        self.files_open = dbl                     # for the tests (Tk can't make a double-click)

        def pull_to(app_id, entry, dest: Path) -> bool:
            """An app's file from the phone into the preview's private folder (Q1)."""
            box = dest.parent / (dest.name + ".d")
            box.mkdir(exist_ok=True)
            if not self.live.app_pull(app_id, entry.path, box):
                return False
            shutil.move(str(box / entry.name), str(dest))
            shutil.rmtree(box, ignore_errors=True)
            return True

        def read(app_id, entry):
            dest = quicklook.private_dir() / f"read-{entry.name}"
            try:
                return dest.read_bytes() if pull_to(app_id, entry, dest) else None
            finally:
                dest.unlink(missing_ok=True)

        def make():
            sel = files.selection()
            ents = [(i, e) for i, e in state["entries"].items() if not e.is_dir]
            if not ents:
                return None
            idx = next((n for n, (i, _e) in enumerate(ents) if sel and i == sel[0]), 0)
            return [quicklook.Item(e.name, read=lambda e=e, b=app_of(i): read(b, e),
                                   to_file=lambda d, e=e, b=app_of(i): pull_to(b, e, d),
                                   size=getattr(e, "size", None)) for i, e in ents], idx
        quicklook.bind_space(files, make)

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(10, 0))

        def save():
            sel = [(app_of(i), state["entries"][i]) for i in files.selection() if i in state["entries"]]
            if not sel:
                messagebox.showinfo(wv.APP_NAME, "Select files or folders to save first.", parent=self)
                return
            base = self.out_dir("files")
            if base is None:
                return
            owners = {b for b, _e in sel}
            # each into its app's folder (F3: a search's results can come from several apps)
            folder = base / sx.safe_name(by_id[next(iter(owners))].name, 60) if len(owners) == 1 else base

            def go():
                out = []
                for b, e in sel:
                    into = base / sx.safe_name(by_id[b].name, 60)
                    if self.live.app_pull(b, e.path, into):
                        out.append(into / e.name)
                return out
            # S6: a protected save is finished from its private folder (base), each app's folder inside it zipped
            self.run_save(f"{len(sel):,} item(s)", go, base if self.is_protected(base) else folder, "item",
                          self.live_runner)
        RoundButton(foot, "Save selected", save, "primary", 160, 38, 12).pack(side="right")
        tk.Label(foot, text="Double-click a folder to open it, or a file to view it", bg=BG, fg=MUTED,
                 font=font(11)).pack(side="right", padx=10)
        first = next((a for a in apps if a.shares_files), None)
        if first:
            alist.selection_set(first.id)

    # refresh (incremental backup) --------------------------------------------------
    def refresh(self):
        if self.refreshing:
            return
        if not self.udid:
            messagebox.showinfo(wv.APP_NAME, "Connect the iPhone first.", parent=self)
            return
        if getattr(self.app, "busy", False):
            messagebox.showinfo(wv.APP_NAME, "PhoneKeep is already backing up in the main window. "
                                "Wait for it to finish, then try again.", parent=self)
            return
        self.refreshing = True
        self.app.busy = True
        self.refresh_btn.set_enabled(False)
        self.banner("Backing up changes from the iPhone… keep it unlocked and nearby.")
        state = {"pct": None, "status": ""}

        def progress(p):
            state["pct"] = p
            self.after(0, paint)

        def status(t):
            state["status"] = t
            self.after(0, paint)

        def paint():
            pct = f"{state['pct']:.0f}% · " if state["pct"] is not None else ""
            try:
                self.bar_text.configure(text=f"Backing up changes… {pct}{state['status']}")
            except tk.TclError:
                pass

        def work():
            return wv.make_backup(Path(self.app.s["backup_dir"]), self.udid, log=lambda m: None,
                                  progress=progress, status=status,
                                  keep=self.app.s["snapshots_keep"], until_disk_full=self.app.s["snapshots_until_full"],
                                  attention=lambda text: self.after(0, lambda: self.passcode_notice(text)))

        def done(path=None, err=None):
            self.refreshing = False
            self.app.busy = False
            try:
                self.refresh_btn.set_enabled(True)
            except tk.TclError:
                return
            if err:
                self.banner(f"Backup didn't finish: {err}", ("Try again", self.refresh), color=theme.ERROR_BG)
                return
            self.banner("✓ Up to date. Reloading…")
            self.snapshot = None
            self.backup_path = Path(path)
            self.viewing.place_forget()
            self._build_timeline()
            if self.data is not None:
                self.data.close()
                self.data = None
            self._open_backup(getattr(self.app, "_backup_password", None))
            try:
                self.app.detect(silent=True)
            except Exception:
                pass

        def worker():
            try:
                p = work()
                self.after(0, lambda: done(p))
            except Exception as e:
                msg = describe_error(e)
                self.after(0, lambda: done(err=msg))
        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        if self.refreshing and not messagebox.askyesno(
                wv.APP_NAME, "A backup is still running. Close anyway? It will carry on next time.", parent=self):
            return
        for r in (self.backup_runner, self.live_runner, self.info_runner, self.apps_runner, self.watch_runner,
                  self.storage_runner, self.search_runner, self.check_runner):
            r.stop()
        self._storage_tick_cancel()
        if quicklook.Viewer.current is not None:
            quicklook.Viewer.current.close()
        for x in (self.data, self.live, self.photo_src):
            try:
                x and x.close()
            except Exception:
                pass
        self.destroy()
