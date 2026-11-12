"""
PhoneKeep - the phone window: your iPhone's apps on your computer.

Click the iPhone in the main window and this opens: a picture of the phone with its own
wallpaper, and a home screen of app icons. Click an icon to browse what is in that app,
preview it, and save what you want.

Where the data comes from:
  * Photos, Music, Books, App Files and the wallpaper are read live from the iPhone;
  * Messages, WhatsApp, WhatsApp Business, Calls, Contacts, Notes, Voicemail, Voice Memos,
    Calendar and Safari can only be read from a backup (Apple doesn't let apps read them
    any other way), so they come from the latest PhoneKeep backup. "Refresh from iPhone"
    makes a quick incremental backup to bring them up to date.
"""
from __future__ import annotations

import datetime as dt
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

import keychain
import phonekeep as wv
import snapshots as sn
import sections as sx
import ui
from ui import BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, RoundButton, card, font

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:  # Pillow missing: no wallpaper picture
    Image = None

# key, label, icon, tile colour, where the data lives
APPS = [
    ("photos", "Photos", "🌻", "#fff4e0", "live"),
    ("messages", "Messages", "💬", "#34c759", "backup"),
    ("whatsapp", "WhatsApp", "💬", "#25d366", "backup"),
    ("whatsappbusiness", "WhatsApp Business", "💼", "#0f7c6c", "backup"),
    ("calls", "Call History", "📞", "#30d158", "backup"),
    ("contacts", "Contacts", "👤", "#9a9aa0", "backup"),
    ("voicemail", "Voicemail", "📼", "#0a84ff", "backup"),
    ("notes", "Notes", "📝", "#ffd60a", "backup"),
    ("calendar", "Calendar", "📅", "#ffffff", "backup"),
    ("voicememos", "Voice Memos", "🎙", "#3a3a3c", "backup"),
    ("safari", "Safari", "🧭", "#0a84ff", "backup"),
    ("music", "Music", "🎵", "#fa2d48", "live"),
    ("books", "Books", "📚", "#ff9500", "live"),
    ("files", "App Files", "📁", "#1e90ff", "live"),
    ("apps", "Apps", "📱", "#5e5ce6", "backup"),
    ("allfiles", "All files", "🗂", "#8e8e93", "backup"),
]
LABEL = {k: l for k, l, *_ in APPS}
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
        self.preview = sx.ChatPreview(self.ctx)
        self.contacts = []
        try:
            self.contacts = sx.load_contacts(self.ctx)   # also gives names to calls & chats
        except Exception:
            pass
        self.cache: dict = {}
        self.lock = threading.Lock()

    def get(self, key: str):
        with self.lock:
            if key in self.cache:
                return self.cache[key]
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
            elif key == "safari":
                v = sx.load_safari(c)
            elif key == "apps":
                v = sx.load_apps(c)
            elif key == "allfiles":
                v = self.reader.domains()
            elif key == "photos":
                import photos as ph
                src = ph.BackupPhotoSource(self.reader, Path(self.reader._tmp.name) / "photos")
                v = (src, src.items())
            else:
                raise wv.PhoneKeepError("Not in backups.")
            self.cache[key] = v
            return v

    def count(self, key: str) -> str:
        v = self.get(key)
        if key in CHAT_APPS:
            chats = v if key == "messages" else v["chats"]
            return f"{len(chats):,} chat{'s' if len(chats) != 1 else ''}"
        if key == "safari":
            return f"{len(v[0]) + len(v[1]):,}"
        if key == "photos":
            return f"{len(v[1]):,}"
        if key == "allfiles":
            n = self.reader.db.execute("SELECT COUNT(*) FROM Files WHERE flags=1").fetchone()[0]
            return f"{n:,} file{'s' if n != 1 else ''}"
        return f"{len(v):,}"

    def copy(self, domain: str, rel: str, dest: Path) -> bool:
        with self.lock:
            return self.ctx.copy(domain, rel, dest)

    def close(self):
        try:
            self.reader.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

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

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.show_home()
        self._connect_live()
        self._open_backup()

    # layout --------------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=GREEN)
        head.pack(fill="x")
        tk.Label(head, text=self.name, bg=GREEN, fg="white", font=font(19, "bold")).pack(side="left", padx=(20, 10), pady=12)
        how = "USB cable" if self.device.get("ConnectionType") == "USB" else "Wi-Fi"
        if self.opened_backup is not None and not self.live_wanted:
            info = wv.backup_info(self.opened_backup)
            sub_text = f"backup of {info.get('date') or '?'} · iOS {info.get('ios') or '?'} · no iPhone connected"
        else:
            sub_text = f"iOS {self.device.get('ProductVersion', '?')} · connected by {how}"
        self.sub = tk.Label(head, text=sub_text, bg=GREEN, fg="#d7efe9", font=font(12))
        self.sub.pack(side="left", pady=12)
        self.lock_badge = tk.Label(head, text="", bg=GREEN, fg="#d7efe9", font=font(12, "bold"))
        self.lock_badge.pack(side="left", padx=(14, 0), pady=12)
        RoundButton(head, "📂  Saved files", lambda: (self.out_root.mkdir(parents=True, exist_ok=True),
                                                      reveal(self.out_root)), "ghost", 150, 34, 12).pack(side="right", padx=(6, 16))
        self.refresh_btn = RoundButton(head, "⟳  Refresh from iPhone", self.refresh, "ghost", 210, 34, 12)
        self.refresh_btn.pack(side="right")

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
        self.src_line = tk.Label(left, text="", bg=BG, fg=MUTED, font=font(11), justify="center", wraplength=250)
        self.src_line.pack()
        # B3: the timeline of snapshots. Click one to see the phone as it was then; right-click for more.
        self.timeline = tk.Frame(left, bg=BG)
        self.timeline.pack(fill="x", pady=(10, 0))
        self.viewing = tk.Label(left, text="", bg="#fff4e0", fg="#b06000", font=font(11, "bold"))
        self._build_timeline()
        self._update_src_line()

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True, padx=(14, 0))

    # snapshots (B3) ------------------------------------------------------------------------
    def _build_timeline(self):
        for w in self.timeline.winfo_children():
            w.destroy()
        snaps = sn.list_snapshots(self.backup_dir, self.udid) if self.udid else []
        self.snaps = snaps
        if not snaps:
            return
        tk.Label(self.timeline, text="Snapshots", bg=BG, fg=INK, font=font(12, "bold"), anchor="w").pack(fill="x")
        row = tk.Frame(self.timeline, bg=BG)
        row.pack(fill="x")
        current = self.snapshot.id if self.snapshot else snaps[0].id
        for i, snap in enumerate(snaps[:8]):
            lab = tk.Label(row, text=(("🔒 " if snap.locked else "") + snap.title), bg=GREEN if snap.id == current else CARD,
                           fg="white" if snap.id == current else INK, font=font(11), padx=8, pady=3, cursor="hand2")
            lab.pack(side="left", padx=(0, 4), pady=2)
            lab.bind("<Button-1>", lambda e, s_=snap: self.open_snapshot(s_))
            lab.bind("<Button-3>", lambda e, s_=snap: self._snapshot_menu(e, s_))
            lab.bind("<Button-2>", lambda e, s_=snap: self._snapshot_menu(e, s_))
            lab.bind("<Control-Button-1>", lambda e, s_=snap: self._snapshot_menu(e, s_))
        if len(snaps) > 8:
            more = tk.Label(self.timeline, text=f"+ {len(snaps) - 8} older…", bg=BG, fg=GREEN, font=font(11), cursor="hand2", anchor="w")
            more.pack(fill="x")
            more.bind("<Button-1>", lambda e: self._all_snapshots())
        detail = self.snapshot or snaps[0]
        size = f"{detail.size / 1e9:.1f} GB" if detail.size >= 1e9 else f"{detail.size / 1e6:.1f} MB"
        tk.Label(self.timeline, text=f"{detail.when.strftime('%d %b %Y %H:%M').lstrip('0')} · {size} · iOS {detail.ios or '?'} · "
                                     + ("🔒 encrypted" if detail.encrypted else "not encrypted"),
                 bg=BG, fg=MUTED, font=font(10), anchor="w", wraplength=250, justify="left").pack(fill="x", pady=(2, 0))

    def open_snapshot(self, snap: Optional[sn.Snapshot]):
        """Show the phone as it was at that snapshot (None = the latest)."""
        latest = self.snaps[0] if self.snaps else None
        self.snapshot = None if (snap is None or (latest and snap.id == latest.id)) else snap
        self.backup_path = (self.snapshot.path if self.snapshot else sn.latest_backup_path(self.backup_dir, self.udid))
        if self.snapshot:
            self.viewing.configure(text=f"Viewing {self.snapshot.title}")
            self.viewing.pack(fill="x", before=self.timeline, pady=(6, 0))
        else:
            self.viewing.pack_forget()
        self._build_timeline()
        if self.data is not None:
            self.data.close()
            self.data = None
        self.counts = {}
        self.photo_src = None
        self._open_backup()

    def _snapshot_menu(self, event, snap: sn.Snapshot):
        m = tk.Menu(self, tearoff=0)
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
            self.open_snapshot(None)
        else:
            self._build_timeline()

    def _all_snapshots(self):
        win = tk.Toplevel(self, bg=CARD)
        win.title("All snapshots")
        win.transient(self)
        lb = tk.Listbox(win, width=48, height=min(20, len(self.snaps)), font=font(12), activestyle="none")
        lb.pack(padx=12, pady=12)
        for s_ in self.snaps:
            lb.insert("end", f"{'🔒 ' if s_.locked else ''}{s_.title}  ·  {s_.when.strftime('%d %b %Y %H:%M').lstrip('0')}")
        lb.bind("<Double-Button-1>", lambda e: (self.open_snapshot(self.snaps[lb.curselection()[0]]), win.destroy()) if lb.curselection() else None)

    def _draw_phone(self):
        c = self.mock
        c.delete("all")
        W, H = 250, 500

        def rr(x1, y1, x2, y2, r, fill, outline=""):
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
                   x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
            return c.create_polygon(pts, smooth=True, fill=fill, outline=outline)
        rr(4, 4, W - 4, H - 4, 44, "#1c1c1e")
        rr(12, 12, W - 12, H - 12, 36, "#2f6f63")
        if self.wall_img is not None:
            c.create_image(W // 2, H // 2, image=self.wall_img)
        else:
            c.create_text(W // 2, H // 2 + 40, text="Your wallpaper\nshows here when the\niPhone is connected",
                          fill="#d7efe9", font=font(11), justify="center")
        rr(W // 2 - 44, 22, W // 2 + 44, 46, 12, "#000000")             # Dynamic Island
        now = dt.datetime.now().strftime("%H:%M")
        c.create_text(46, 34, text=now, fill="white", font=font(12, "bold"))
        c.create_text(W // 2, H // 2 - 70, text=now, fill="white", font=font(44, "bold"))
        c.create_text(W // 2, H // 2 - 120, text=dt.datetime.now().strftime("%A %d %B"), fill="white", font=font(13))
        rr(W // 2 - 50, H - 30, W // 2 + 50, H - 25, 2, "#ffffff")       # home bar

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
        self.src_line.configure(text="\n\n".join(parts))

    def banner(self, text: str, button: Optional[tuple] = None, color=GREEN_SOFT):
        if not text:
            self.bar_frame.pack_forget()
            return
        self.bar_frame.configure(bg=color)
        self.bar_text.configure(text=text, bg=color)
        if self.bar_btn is not None:
            self.bar_btn.destroy()
            self.bar_btn = None
        if button:
            self.bar_btn = RoundButton(self.bar_frame, button[0], button[1], "secondary", 170, 30, 12)
            self.bar_btn.pack(side="right", padx=12, pady=4)
        if not self.bar_frame.winfo_ismapped():
            self.bar_frame.pack(fill="x", after=self.winfo_children()[0])

    # connections --------------------------------------------------------------
    def _connect_live(self):
        if not self.udid or not self.live_wanted:
            self.live_error = "No iPhone connected"
            self._update_src_line()
            return
        import device as devmod

        def go():
            return devmod.LiveDevice(self.udid)

        def ok(live):
            self.live = live
            self._update_src_line()
            self.live_runner.submit(lambda: live.wallpaper("homescreen") or live.wallpaper("lockscreen"),
                                    self._set_wallpaper, lambda e: None)
            if self.current is None:
                self.show_home()

        def err(e):
            self.live_error = describe_error(e)
            self._update_src_line()
        self.live_runner.submit(go, ok, err)

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
        self.lock_badge.configure(text="🔒 Encrypted · on this computer" if info["encrypted"] else "")
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
            self.counts = {}
            self._count_next([k for k, *_r, where in APPS if where == "backup"])
            if self.current is None:
                self.show_home()
            elif self.current in CHAT_APPS + ("calls", "contacts", "notes", "calendar", "voicemail", "allfiles",
                                               "voicememos", "safari", "apps"):
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
            self.banner(msg, color="#fdecea")
            self._update_src_line()
        self.backup_runner.submit(lambda: BackupData(self.backup_path, password), ok, err)

    def _count_next(self, keys: list):
        if not keys or self.data is None:
            return
        key, rest = keys[0], keys[1:]
        data = self.data

        def ok(n):
            self.counts[key] = n
            self._paint_count(key)
            self._count_next(rest)

        def err(e):
            self.counts[key] = "nothing found"
            self._paint_count(key)
            self._count_next(rest)
        self.backup_runner.submit(lambda: data.count(key), ok, err)

    # home screen --------------------------------------------------------------
    def _clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    def show_home(self):
        self.current = None
        self._clear()
        tk.Label(self.content, text="Your iPhone", bg=BG, fg=INK, font=font(20, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(self.content, text="Click an app to see what's in it, preview it and save what you want.",
                 bg=BG, fg=MUTED, font=font(13), anchor="w").pack(fill="x", pady=(2, 12))
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="both", expand=True)
        self.tile_count = {}
        cols = 5
        for i, (key, label, icon, colour, where) in enumerate(APPS):
            t = tk.Frame(grid, bg=BG, cursor="hand2")
            t.grid(row=i // cols, column=i % cols, padx=10, pady=10, sticky="n")
            cv = tk.Canvas(t, width=92, height=92, bg=BG, highlightthickness=0, cursor="hand2")
            cv.pack()
            pts = [8 + 22, 8, 84 - 22, 8, 84, 8, 84, 8 + 22, 84, 84 - 22, 84, 84, 84 - 22, 84,
                   8 + 22, 84, 8, 84, 8, 84 - 22, 8, 8 + 22, 8, 8]
            cv.create_polygon(pts, smooth=True, fill=colour, outline=LINE if colour == "#ffffff" else "")
            cv.create_text(46, 46, text=icon, font=font(34))
            tk.Label(t, text=label, bg=BG, fg=INK, font=font(12, "bold"), wraplength=120).pack()
            cl = tk.Label(t, text="", bg=BG, fg=MUTED, font=font(11))
            cl.pack()
            self.tile_count[key] = cl
            for w in (t, cv, cl) + tuple(x for x in t.winfo_children() if isinstance(x, tk.Label)):
                w.bind("<Button-1>", lambda e, k=key: self.open_app(k))
            self._paint_count(key)
        for c in range(cols):
            grid.columnconfigure(c, weight=1)

    def _paint_count(self, key):
        lab = getattr(self, "tile_count", {}).get(key)
        if lab is None:
            return
        try:
            where = next(w for k, *_r, w in APPS if k == key)
            if key in self.counts:
                text = self.counts[key]
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
            lk.bind("<Button-1>", lambda e, d=details: messagebox.showinfo("Details for support", d, parent=self))

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
            button = (pr.button, lambda d=pr.details: messagebox.showinfo("Details for support", d, parent=self))
            return pr.message, button, ""
        elif retry:
            button = retry
        return pr.message, button, pr.details

    def open_app(self, key: str):
        self.current = key
        self._clear()
        self.view_header(key)
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
         "safari": self.v_safari, "apps": self.v_apps, "allfiles": self.v_allfiles, "music": self.v_music, "books": self.v_books,
         "files": self.v_files, "photos": self.v_photos}[key](key, value)

    # saving -------------------------------------------------------------------
    def out_dir(self, key: str) -> Path:
        d = self.out_root / LABEL[key]
        d.mkdir(parents=True, exist_ok=True)
        return d

    def saved(self, paths: list, folder: Path, what: str = "file"):
        n = len([p for p in paths if p])
        if not n:
            messagebox.showwarning(wv.APP_NAME, "Nothing could be saved.", parent=self)
            return
        self.banner(f"✓ Saved {n:,} {what}{'s' if n != 1 else ''} to {folder}", ("Show in Finder" if sys.platform == "darwin"
                    else "Show folder", lambda: reveal(folder)))

    def run_save(self, label: str, fn, folder: Path, what: str = "file", runner=None):
        self.banner(f"Saving {label}…")
        (runner or self.backup_runner).submit(fn, lambda paths: self.saved(paths, folder, what),
                                              lambda e: self.banner(f"Couldn't save: {describe_error(e)}", color="#fdecea"))

    def export_section(self, key: str, formats: set, chooser=None, dates=None):
        """Full export of one app through the same code as the main 'Back up' button."""
        out = self.out_root
        data = self.data

        eta = ui.Eta()

        def progress(p):
            text = eta.feed(p)
            self.after(0, lambda: self.banner(f"Exporting {LABEL[key]}… {text}"))

        def go():
            return sx.export_all(data.path, out, data.password, [key], include_media=True,
                                 log=lambda m: None, chooser=chooser, formats=formats, dates=dates,
                                 progress=progress)

        def ok(index):
            self.banner(f"✓ Exported {LABEL[key]} to {out}", ("Open", lambda: open_file(Path(index))))
        self.banner(f"Exporting {LABEL[key]}… working out time left…")
        self.backup_runner.submit(go, ok, lambda e: self.banner(f"Couldn't export: {describe_error(e)}",
                                                                 color="#fdecea"))

    # chats ----------------------------------------------------------------------
    def v_chats(self, key, value):
        chats = value if key == "messages" else value["chats"]
        lists = {key: (LABEL[key], [sx._chat_summary(c) for c in chats])}
        self.view_sub.configure(text=f"{len(chats):,} chat{'s' if len(chats) != 1 else ''} · "
                                     f"{sum(len(c['messages']) for c in chats):,} messages"
                                     f" · backup of {self.data.info.get('date') or '?'}")
        panel = ui.ChatPanel(self.content, lists, self.data.preview, select_all=False, preview_limit=600)
        panel.pack(fill="both", expand=True)

        def export(fmts):
            sel = panel.selection(confirm_empty=False)
            if sel is None:
                return
            if not any(v for k, v in sel.items() if k != "_dates"):
                messagebox.showinfo(wv.APP_NAME, "Tick the chats you want to save first (or Select all).", parent=self)
                return
            dates = sel.pop("_dates", None)
            self.export_section(key, fmts, chooser=lambda lists, pv: sel, dates=dates)
        RoundButton(panel.foot, "Save as web page", lambda: export({"web"}), "secondary", 170, 38, 12).pack(side="right")
        RoundButton(panel.foot, "CSV", lambda: export({"csv"}), "secondary", 80, 38, 12).pack(side="right", padx=6)
        RoundButton(panel.foot, "Save ticked as Excel", lambda: export({"excel"}), "primary", 190, 38, 12).pack(side="right")

    # photos ---------------------------------------------------------------------
    def _load_photos(self, holder):
        import photos as ph

        def from_device():
            src = self.photo_src
            if src is None or not isinstance(src, ph.DevicePhotoSource):
                src = ph.DevicePhotoSource(self.udid, Path(tempfile.mkdtemp(prefix="phonekeep-photos-")))
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
        tmp = Path(tempfile.mkdtemp(prefix="phonekeep-view-"))

        def open_one(item):
            dest = tmp / item.name
            self.banner(f"Opening {item.name}…")
            self.live_runner.submit(lambda: src.copy(item.id, dest) and dest,
                                    lambda p: (self.banner(""), open_file(p)) if p else None,
                                    lambda e: self.banner(f"Couldn't open it: {describe_error(e)}", color="#fdecea"))
        panel = ui.PhotoPanel(self.content, src, items, select_all=False, on_open=open_one)
        panel.pack(fill="both", expand=True)

        def save():
            chosen = [i for i in items if i.id in panel.selected]
            if not chosen:
                messagebox.showinfo(wv.APP_NAME, "Click the photos you want to save first (or Select all).", parent=self)
                return
            folder = self.out_dir("photos")

            def go():
                done = []
                for i in chosen:
                    month = i.when.strftime("%Y-%m") if i.when.year > 1970 else "Unknown date"
                    dest = folder / month / i.name
                    if src.copy(i.id, dest):
                        done.append(dest)
                    if i.live_video:
                        src.copy(i.live_video, folder / month / Path(i.live_video).name)
                return done
            self.run_save(f"{len(chosen):,} photos & videos", go, folder, "photo/video",
                          self.live_runner if src.label == "the iPhone" else self.backup_runner)
        RoundButton(panel.foot, "Save selected", save, "primary", 170, 38, 12).pack(side="right")
        tk.Label(panel.foot, text="Double-click to open", bg=BG, fg=MUTED, font=font(11)).pack(side="right", padx=12)

    # tables -----------------------------------------------------------------------
    def table_view(self, key, headers: list, rows: list, widths: Optional[list] = None, actions=(),
                   on_double=None, multi=True, title_extra=""):
        """A searchable, sortable table with Excel/CSV saving. actions: [(label, fn(selected rows))]."""
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

        def shown() -> list:
            t = q.get().strip().lower()
            return [r for r in state["rows"] if not t or any(t in str(x).lower() for x in r[:ncol])]

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

        def selected() -> list:
            return [by_id[i] for i in tree.selection() if i in by_id]
        if on_double:
            tree.bind("<Double-1>", lambda e: on_double(selected()))

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(10, 0))

        def save(kind):
            vis = selected() or shown()
            folder = self.out_dir(key)
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
        self.table_view(key, sx.CALL_HEADERS, rows, [150, 80, 180, 140, 110, 70, 120])

    def v_contacts(self, key, people):
        self.view_sub.configure(text=f"{len(people):,} contacts")
        rows = [[p["name"], "\n".join(v for _l, v in p["phones"]), "\n".join(v for _l, v in p["emails"]),
                 " · ".join(x for x in (p["org"], p["title"]) if x), p["birthday"], p["note"]] for p in people]
        self.table_view(key, ["Name", "Phone", "Email", "Company", "Birthday", "Note"], rows,
                        [200, 160, 200, 160, 90, 200],
                        actions=[("Save as vCard (.vcf)", lambda sel: self.export_section("contacts", {"web"}))])

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
                        on_double=open_url, actions=[("Open in browser", open_url)])

    def v_apps(self, key, apps):
        self.view_sub.configure(text=f"{len(apps):,} apps")
        rows = [[a, f"{len(self.data.ctx.files('AppDomain-' + a)):,} files in backup"] for a in apps]
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
        tk.Label(top, text="Double-click or Space to preview · tick with a click, then Save", bg=BG, fg=MUTED, font=font(11)).pack(side="left", padx=10)
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
            sel = [meta[i] for i in tree.selection() if meta.get(i, ("",))[0] == "file"]
            if not sel:
                return
            _k, domain, rel, size, mtime = sel[0]
            tmp = Path(tempfile.mkdtemp(prefix="phonekeep-view-"))
            dest = tmp / Path(rel).name
            if self.data.copy(domain, rel, dest):
                open_file(dest)
        tree.bind("<Double-Button-1>", preview)
        tree.bind("<space>", preview)
        tree.bind("<Return>", preview)
        self.allfiles_preview = preview           # also reachable for the tests

        def search(*_):
            text = q.get().strip().lower()
            if not text:
                return
            # search every domain's file names (loads them as needed)
            for iid in list(tree.get_children("")):
                if iid not in loaded:
                    loaded.add(iid)
                    for ch in tree.get_children(iid):
                        tree.delete(ch)
                    add_folder_tree(iid, meta[iid][1], self.data.reader.file_meta(meta[iid][1]))
            hits = [i for i, m in meta.items() if m[0] == "file" and text in m[2].lower()]
            tree.selection_set(hits[:500])
            if hits:
                tree.see(hits[0])
            foot_count.configure(text=f"{len(hits):,} match{'es' if len(hits) != 1 else ''}")
        q.trace_add("write", search)

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(6, 0))
        foot_count = tk.Label(foot, text="", bg=BG, fg=MUTED, font=font(12))
        foot_count.pack(side="left")

        def update_count(_e=None):
            files = [m for m in (meta.get(i) for i in tree.selection()) if m and m[0] == "file"]
            folders = [i for i in tree.selection() if meta.get(i, ("",))[0] in ("domain", "folder")]
            size = sum(m[3] for m in files)
            foot_count.configure(text=(f"{len(files):,} file{'s' if len(files) != 1 else ''} · {devmod.human_size(size)}" if files else "")
                                 + (f" · {len(folders)} folder{'s' if len(folders) != 1 else ''}" if folders else ""))
        tree.bind("<<TreeviewSelect>>", update_count)

        def save():
            items = selected_files()
            if not items:
                messagebox.showinfo(wv.APP_NAME, "Click a file or a folder first (Cmd/Ctrl-click for several).", parent=self)
                return
            out = self.out_dir("allfiles")
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
        lf = card(pane)
        tree = ttk.Treeview(lf, columns=("t", "f", "m"), show="headings", selectmode="browse")
        for c, h, w in (("t", "Title", 230), ("f", "Folder", 110), ("m", "Edited", 120)):
            tree.heading(c, text=h)
            tree.column(c, width=w, stretch=(c == "t"))
        tree.pack(fill="both", expand=True)
        pane.add(lf, minsize=360, width=470)
        rf = card(pane)
        title = tk.Label(rf, text="", bg=CARD, fg=INK, font=font(16, "bold"), anchor="w")
        title.pack(fill="x", padx=14, pady=(10, 0))
        meta = tk.Label(rf, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        meta.pack(fill="x", padx=14)
        txt = tk.Text(rf, wrap="word", relief="flat", font=font(13), padx=12, pady=8, bg="#fffdf3",
                      highlightthickness=0)
        txt.pack(fill="both", expand=True, padx=2, pady=6)
        pane.add(rf, minsize=320)

        def fill(*_):
            t = q.get().strip().lower()
            tree.delete(*tree.get_children())
            for i, n in enumerate(notes):
                if t and t not in (n["title"] + " " + (n["text"] or "")).lower():
                    continue
                tree.insert("", "end", iid=str(i), values=(("🔒 " if n["locked"] else "") + n["title"],
                                                           n["folder"], sx.fmt(n["modified"])))

        def show(*_):
            s = tree.selection()
            if not s:
                return
            n = notes[int(s[0])]
            title.configure(text=n["title"])
            meta.configure(text=f"{n['folder']} · created {sx.fmt(n['created'])} · edited {sx.fmt(n['modified'])}")
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", n["text"] or "")
            txt.configure(state="disabled")
        q.trace_add("write", fill)
        tree.bind("<<TreeviewSelect>>", show)
        fill()
        kids = tree.get_children()
        if kids:
            tree.selection_set(kids[0])

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(10, 0))

        def save_one():
            s = tree.selection()
            if not s:
                return
            n = notes[int(s[0])]
            if n["locked"]:
                messagebox.showinfo(wv.APP_NAME, "This note is locked with your Notes password.", parent=self)
                return
            folder = self.out_dir("notes")
            p = unique_path(folder / (sx.safe_name(n["title"], 80) + ".txt"))
            p.write_text(n["text"] or "", encoding="utf-8")
            self.saved([p], folder, "note")
        RoundButton(foot, "Save all notes", lambda: self.export_section("notes", {"web"}), "primary", 160, 38, 12).pack(side="right")
        RoundButton(foot, "Save this note (.txt)", save_one, "secondary", 190, 38, 12).pack(side="right", padx=6)

    # audio ----------------------------------------------------------------------
    def _audio_actions(self, key, getter):
        """getter(row) -> (copy function(dest) -> bool, file name). Returns Play/Save actions."""
        tmp = Path(tempfile.mkdtemp(prefix="phonekeep-play-"))

        def play(sel):
            if not sel:
                messagebox.showinfo(wv.APP_NAME, "Select something to play first.", parent=self)
                return
            copy, name = getter(sel[0])
            dest = tmp / name
            runner = self.live_runner if key in ("music", "books") else self.backup_runner
            self.banner(f"Opening {name}…")
            runner.submit(lambda: copy(dest) and dest, lambda p: (self.banner(""), open_file(p)) if p else
                          self.banner("That file isn't available.", color="#fdecea"),
                          lambda e: self.banner(f"Couldn't open it: {describe_error(e)}", color="#fdecea"))

        def save(sel):
            if not sel:
                messagebox.showinfo(wv.APP_NAME, "Select what to save first (Cmd/Ctrl-click for several, "
                                    "Cmd/Ctrl-A for all).", parent=self)
                return
            folder = self.out_dir(key)

            def go():
                done = []
                for r in sel:
                    copy, name = getter(r)
                    dest = unique_path(folder / name)
                    if copy(dest):
                        done.append(dest)
                return done
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
                        [150, 200, 150, 80, 80], on_double=play,
                        actions=[("▶  Play", play), ("Save selected", save)])

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
                        actions=[("▶  Play", play), ("Save selected", save)])

    def v_music(self, key, tracks):
        import device as devmod
        total = sum(t.size for t in tracks)
        self.view_sub.configure(text=f"{len(tracks):,} items on the iPhone · {devmod.human_size(total)}")
        if not tracks:
            holder = self.loading("")
            self.failed(holder, "No music is stored on this iPhone. Songs that only stream from Apple Music "
                                "aren't on the phone, so they can't be copied.")
            return
        rows = [[t.title, t.artist, t.album, sx.dur(t.seconds) if t.seconds else "", t.kind,
                 devmod.human_size(t.size), t] for t in tracks]

        def getter(r):
            t = r[6]
            name = sx.safe_name(" - ".join(x for x in (t.artist, t.title) if x) or Path(t.path).stem, 120) + Path(t.path).suffix
            return (lambda dest: self.live.copy_media(t.path, dest)), name
        play, save = self._audio_actions(key, getter)
        self.table_view(key, ["Title", "Artist", "Album", "Length", "Kind", "Size"], rows,
                        [240, 170, 170, 70, 90, 80], on_double=play,
                        actions=[("▶  Play", play), ("Save selected", save)],
                        title_extra=" · purchased songs may only play on your own devices")

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
                        actions=[("Open", play), ("Save selected", save)])

    # app files ------------------------------------------------------------------------
    def v_files(self, key, apps):
        sharing = [a for a in apps if a.shares_files]
        self.view_sub.configure(text=f"{len(sharing):,} apps share files · {len(apps):,} apps installed")
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
        state = {"app": None, "path": "Documents", "entries": {}}
        by_id = {a.id: a for a in apps}
        import device as devmod

        def load(app_id, path):
            a = by_id[app_id]
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

        def dbl(_e=None):
            s = files.selection()
            if not s:
                return
            if s[0] == "__up":
                load(state["app"], state["path"].rsplit("/", 1)[0])
                return
            e = state["entries"].get(s[0])
            if e is not None and e.is_dir:
                load(state["app"], e.path)
            elif e is not None:
                tmp = Path(tempfile.mkdtemp(prefix="phonekeep-file-"))
                self.banner(f"Opening {e.name}…")
                self.live_runner.submit(lambda: self.live.app_pull(state["app"], e.path, tmp) and tmp / e.name,
                                        lambda p: (self.banner(""), open_file(p)) if p else None,
                                        lambda err: self.banner(f"Couldn't open it: {describe_error(err)}", color="#fdecea"))
        alist.bind("<<TreeviewSelect>>", lambda e: alist.selection() and load(alist.selection()[0], "Documents"))
        files.bind("<Double-1>", dbl)

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", pady=(10, 0))

        def save():
            sel = [state["entries"][i] for i in files.selection() if i in state["entries"]]
            if not sel:
                messagebox.showinfo(wv.APP_NAME, "Select files or folders to save first.", parent=self)
                return
            a = by_id[state["app"]]
            folder = self.out_dir("files") / sx.safe_name(a.name, 60)
            app_id = state["app"]

            def go():
                return [folder / e.name for e in sel if self.live.app_pull(app_id, e.path, folder)]
            self.run_save(f"{len(sel):,} item(s)", go, folder, "item", self.live_runner)
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
                                  keep=self.app.s["snapshots_keep"], until_disk_full=self.app.s["snapshots_until_full"])

        def done(path=None, err=None):
            self.refreshing = False
            self.app.busy = False
            try:
                self.refresh_btn.set_enabled(True)
            except tk.TclError:
                return
            if err:
                self.banner(f"Backup didn't finish: {err}", ("Try again", self.refresh), color="#fdecea")
                return
            self.banner("✓ Up to date. Reloading…")
            self.snapshot = None
            self.backup_path = Path(path)
            self.viewing.pack_forget()
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
        for r in (self.backup_runner, self.live_runner):
            r.stop()
        for x in (self.data, self.live, self.photo_src):
            try:
                x and x.close()
            except Exception:
                pass
        self.destroy()
