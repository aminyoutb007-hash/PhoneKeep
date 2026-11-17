#!/usr/bin/env python3
"""PhoneKeep desktop window. Run: python app.py"""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Optional
from tkinter import filedialog, messagebox, simpledialog, ttk

import applock
import errors

try:
    from PIL import Image, ImageOps, ImageTk          # the phone's home screen in the main window (5.1.3)
except Exception:
    Image = ImageOps = ImageTk = None
import keychain
import activity
import phone_write
import phonekeep as wv
import sections as sx
import theme
import ui
from ui import AMBER, BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, font

SETTINGS_FILE = wv.DEFAULT_HOME / "settings.json"

PRESETS = {
    "chats": ("💬", "Chats", "WhatsApp and Messages",
              ["whatsapp", "whatsappbusiness", "messages", "contacts"]),
    "chats_photos": ("📷", "Chats & photos", "Plus photos and videos",
                     ["whatsapp", "whatsappbusiness", "messages", "contacts", "photos"]),
    "everything": ("📱", "Everything", "Contacts, calls, notes and more",
                   list(sx.DEFAULT_SECTIONS)),
    "custom": ("⚙", "Custom", "Pick exactly what to include", None),
}
KEEP_OPEN = "Keep PhoneKeep open until it's done."
# B9 (5.3): a backup carries on with the window closed
CLOSE_OK = ("You can close this window: it waits in the taskbar and comes back when it's done." if sys.platform == "win32"
            else "You can close this window. You'll get a notification when it's done.")
# L2: the steps are the phases a backup can tell apart (it can't tell chats from photos while it copies)
STEPS = [("ready", "Get the iPhone ready"), ("copy", "Copy from the iPhone"), ("snapshot", "Save it as a snapshot"),
         ("choose", "Choose chats & photos"), ("build", "Build your archive")]
EXPORT_STEPS = [("choose", "Choose chats & photos"), ("build", "Build your archive")]
MOVE_STEPS = [("backup", "Move your backups")]


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return "under 2 min left"
    m = int(seconds // 60)
    return f"about {m} min left" if m < 90 else f"about {m // 60} h {m % 60:02d} min left"


def about_lines() -> list:
    """The About box under the name and version: what PhoneKeep does, and its licence with where the source is."""
    return ["", "Backs up your iPhone to this computer.", "Encrypted with your backup password; never sent online.",
            "", wv.LICENCE_LINE]


def reveal(path: Path) -> None:
    """Show a file or folder in Finder / Explorer."""
    path = Path(path)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path if path.is_dir() else path.parent))  # noqa
        else:
            subprocess.run(["xdg-open", str(path if path.is_dir() else path.parent)])
    except Exception:
        pass


def sn_has(backup_dir: Path, udid: str) -> bool:
    import snapshots as _snaps
    return bool(_snaps.latest_backup_path(backup_dir, udid))


def known_backed_up_phones(backup_dir: Path) -> list:
    """UDIDs of the phones that have a PhoneKeep backup in this backup folder."""
    import snapshots as _snaps
    try:
        return sorted(p.name for p in backup_dir.iterdir() if p.is_dir() and _snaps.latest_backup_path(backup_dir, p.name))
    except OSError:
        return []


def phone_summaries(backup_dir: Path, devices: list) -> list:
    """E5: every phone connected now and every phone with a backup in this backup folder, one dict each: udid, name,
    model, last (the last backup's date), size (of the newest snapshot, if known), encrypted, how (cable / Wi-Fi /
    None) and picture (its saved home screen or wallpaper). Connected phones first, then the newest backup.
    Reads only files on this computer."""
    import models
    import snapshots as _snaps
    here = {(d.get("UniqueDeviceID") or d.get("Identifier")): d for d in devices or []}
    out = []
    for udid in dict.fromkeys(list(here) + known_backed_up_phones(backup_dir)):
        d = here.get(udid) or {}
        snaps = _snaps.list_snapshots(backup_dir, udid)
        latest = snaps[0].path if snaps else _snaps.latest_backup_path(backup_dir, udid)
        info = wv.backup_info(latest) if latest else {}
        pictures = [wv.phone_picture(udid), wv.phone_cache(udid) / "wallpaper.png"]
        out.append({"udid": udid, "name": d.get("DeviceName") or info.get("name") or "iPhone",
                    "model": models.model_name(d.get("ProductType") or (snaps[0].model if snaps else None)
                                               or info.get("product")),
                    "last": info.get("date"), "size": snaps[0].size if snaps else None,
                    "encrypted": info.get("encrypted") if latest else None,
                    "how": None if not d else "cable" if d.get("ConnectionType") == "USB" else "Wi-Fi",
                    "picture": next((p for p in pictures if p.exists()), None)})
    out.sort(key=lambda x: x["last"] or "", reverse=True)
    out.sort(key=lambda x: x["how"] is None)                # stable: connected first, each part newest first
    return out


class Settings:
    DEFAULTS = {
        "preset": "chats",
        "custom_sections": list(sx.DEFAULT_SECTIONS),
        "formats": ["web", "excel"],
        "pick_chats": True,
        "pick_photos": True,
        "include_media": True,
        "direct_photos": True,
        "backup_dir": str(wv.DEFAULT_BACKUP_DIR),
        "archive_dir": str(wv.DEFAULT_ARCHIVE_DIR),
        "first_run_done": False,     # E1: the guide was finished or skipped
        "auto_backup": "off",        # E1 step 5 / B2: "daily" | "weekly" | "off"
        "wifi_sync": False,          # E1 step 5: the owner turned on Wi-Fi backups
        "app_lock": None,            # E1 step 5 / S2: None = decide by hardware
        "photos_jpg": False,         # P1: last "Save photos as" choice (False = original HEIC)
        "lock_idle_minutes": 10,     # S2: hide phone windows after this many idle minutes
        "start_at_login": False,     # E2: the helper starts at login (asked once in E1 step 5)
        "auto_backup_paused": False, # E2: Pause automatic backups
        "auto_backup_phones": None,  # B8: UDIDs backed up automatically (None = not set up yet: see migrate)
        "auto_backup_hour": 21,      # B2: "around 9 pm"
        "auto_backup_weekday": 6,    # B2: weekly on Sunday
        "auto_backup_charging": False,  # B2: only when charging
        "snapshots_keep": 10,        # B3: keep the last N snapshots (3-100)
        "snapshots_until_full": False,  # B3: or keep everything until the disk is 90% full
        "appearance": "system",      # E6: "system" (the computer's light/dark setting), "light" or "dark"
    }

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        try:
            self.data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    def save(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except Exception:
            pass

    def sections(self) -> list[str]:
        p = self.data["preset"]
        return list(PRESETS[p][3] if PRESETS.get(p) and PRESETS[p][3] else self.data["custom_sections"])


class PhoneIcon(tk.Canvas):
    """The main window's small phone. With a saved home screen (5.1.3) it shows that picture in a dark frame, like the
    phone window: dimmed with a small spinner while searching, dimmed with a "not connected" badge when the phone isn't
    there. Without one, the drawn phone with a tick (or … / ?)."""
    SCREEN = (10, 8, 54, 96)              # the picture's place inside the frame

    def __init__(self, parent, bg):
        super().__init__(parent, width=64, height=104, bg=bg, highlightthickness=0)
        self.state = None
        self.picture = None               # the saved home screen's file
        self._imgs = {}                   # "full" / "dim" PhotoImages of it
        self._spin = 0
        self._spinning = False
        self.set_state("searching")

    def set_picture(self, path) -> None:
        """Show this home screen (None: the drawn phone). A fresh copy of the same file replaces it quietly."""
        imgs = {}
        if path is not None and Image is not None:
            try:
                from PIL import ImageDraw
                x0, y0, x1, y1 = self.SCREEN
                size = (x1 - x0, y1 - y0)
                with Image.open(path) as im:
                    full = ImageOps.fit(im.convert("RGB"), size)
                mask = Image.new("L", size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), 7, fill=255)
                from PIL import ImageColor
                dim = Image.blend(full, Image.new("RGB", size, ImageColor.getrgb(theme.CARD)), 0.55)
                for key, img in (("full", full), ("dim", dim)):
                    out = Image.new("RGBA", size, (0, 0, 0, 0))
                    out.paste(img, (0, 0), mask)
                    imgs[key] = ImageTk.PhotoImage(out)
            except Exception:
                imgs = {}
        self.picture = path if imgs else None
        self._imgs = imgs
        self._draw()
        self._start_spin()          # searching before the picture came: the spinner turns now

    def set_state(self, state: str):
        if state == self.state:
            return
        self.state = state
        self._draw()
        self._start_spin()

    def _start_spin(self):
        if self.state == "searching" and self._imgs and not self._spinning:
            self._spinning = True
            self.after(90, self._turn)

    def _turn(self):
        if self.state != "searching" or not self._imgs:
            self._spinning = False
            return
        self._spin = (self._spin - 30) % 360
        self._draw()
        try:
            self.after(90, self._turn)
        except tk.TclError:
            self._spinning = False

    def _draw(self):
        self.delete("all")
        state = self.state
        if self._imgs:
            x0, y0, x1, y1 = self.SCREEN
            self._rr(6, 4, 58, 100, 12, theme.PHONE_BODY)
            self.create_image(x0, y0, anchor="nw", image=self._imgs["full" if state == "ok" else "dim"], tags=("picture",))
            self.create_rectangle(26, 10, 38, 12, fill=theme.PHONE_BODY, outline="")       # the camera notch
            if state == "searching":
                cx, cy = 32, 52
                self.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, outline=theme.CARD, width=3, tags=("spinner",))
                self.create_arc(cx - 10, cy - 10, cx + 10, cy + 10, start=self._spin, extent=110, style="arc",
                                outline=GREEN, width=3, tags=("spinner",))
            elif state == "none":
                self._rr(4, 78, 60, 92, 6, theme.WARN_BG)
                self.create_text(32, 85, text="not connected", fill=theme.WARN_TEXT, font=font(8, "bold"),
                                 tags=("badge",))
            return
        body = theme.PHONE_ICON[state]
        self._rr(6, 4, 58, 100, 12, body)
        self._rr(11, 12, 53, 88, 6, theme.CARD if state != "ok" else theme.ACCENT_PALE)
        self.create_rectangle(26, 7, 38, 9, fill=theme.CARD, outline="")
        mark = {"ok": ("✓", GREEN), "searching": ("…", MUTED), "none": ("?", MUTED)}[state]
        self.create_text(32, 50, text=mark[0], fill=mark[1], font=font(26, "bold"))

    def _rr(self, x1, y1, x2, y2, r, fill):
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)
        for (cx, cy) in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
            self.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline=fill)


class StepRow(tk.Frame):
    def __init__(self, parent, number: int, title: str):
        super().__init__(parent, bg=CARD)
        self.dot = tk.Canvas(self, width=30, height=30, bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 10))
        col = tk.Frame(self, bg=CARD)
        col.pack(side="left", fill="x", expand=True)
        top = tk.Frame(col, bg=CARD)
        top.pack(fill="x")
        self.title = tk.Label(top, text=title, bg=CARD, fg=MUTED, font=font(14, "bold"), anchor="w")
        self.title.pack(side="left")
        self.right = tk.Label(top, text="", bg=CARD, fg=MUTED, font=font(12), anchor="e")
        self.right.pack(side="right")
        self.detail = tk.Label(col, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w", justify="left",
                               wraplength=560)
        self.number, self.state, self.spin = number, "pending", 0
        self.set("pending")

    def set(self, state: str, detail: str = None, right: str = None):
        self.state = state
        if detail is not None:
            self.detail.configure(text=detail)
            if detail and not self.detail.winfo_manager():       # a line only when there is something to say
                self.detail.pack(fill="x")
            elif not detail and self.detail.winfo_manager():
                self.detail.pack_forget()
        if right is not None:
            self.right.configure(text=right)
        self.title.configure(fg=INK if state != "pending" else MUTED)
        self.draw()

    def draw(self):
        d = self.dot
        d.delete("all")
        if self.state == "done":
            d.create_oval(3, 3, 27, 27, fill=GREEN, outline=GREEN)
            d.create_text(15, 15, text="✓", fill=theme.ON_ACCENT, font=font(13, "bold"))
        elif self.state == "error":
            d.create_oval(3, 3, 27, 27, fill=RED, outline=RED)
            d.create_text(15, 15, text="!", fill=theme.ON_ACCENT, font=font(13, "bold"))
        elif self.state == "skipped":
            d.create_oval(3, 3, 27, 27, fill=theme.CARD, outline=LINE, width=2)
            d.create_text(15, 15, text="–", fill=MUTED, font=font(13, "bold"))
        elif self.state == "active":
            d.create_oval(3, 3, 27, 27, outline=theme.PHONE_ICON_RING, width=3)
            d.create_arc(3, 3, 27, 27, start=self.spin, extent=110, style="arc", outline=GREEN, width=3)
        else:
            d.create_oval(3, 3, 27, 27, fill=theme.CARD, outline=LINE, width=2)
            d.create_text(15, 15, text=str(self.number), fill=MUTED, font=font(12))

    def tick(self):
        if self.state == "active":
            self.spin = (self.spin - 18) % 360
            self.draw()


class Bar(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, height=8, bg=CARD, highlightthickness=0)
        self.value = 0.0
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, v: float):
        self.value = max(0.0, min(100.0, v))
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        self.create_rectangle(0, 0, w, 8, fill=theme.TILE_BG, outline="")
        self.create_rectangle(0, 0, int(w * self.value / 100), 8, fill=GREEN, outline="")


def _dnd_root():
    """tk.Tk with drag-and-drop when tkinterdnd2 is available (B5: drop a backup folder onto the window)."""
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk
    except Exception:
        return tk.Tk


class App(_dnd_root()):
    def __init__(self):
        super().__init__()
        import quicklook
        quicklook.cleanup_stale()    # Q1: what PhoneKeeps no longer running left in the private folder
        threading.Thread(target=activity.prune, daemon=True).start()     # S7: the record keeps 12 months
        import tamper                       # S8: snapshot seals are signed with a key in the keychain (window only;
        if keychain.available() and not os.environ.get("PHONEKEEP_HOME"):     # tests bring their own key)
            tamper.key_source = tamper.keychain_key
        ui.use_light_appearance(self)
        self.title(wv.APP_NAME)
        self._build_menu()
        self.geometry("820x860")
        self.minsize(720, 700)
        self.configure(bg=BG)
        ui.setup_styles(self)
        self.s = Settings()
        if self.s.data.get("auto_backup_phones") is None:
            # B8: until now every backed-up phone was backed up automatically; keep exactly those ticked. A phone
            # seen from now on is only backed up automatically once it's ticked in Settings.
            self.s["auto_backup_phones"] = known_backed_up_phones(Path(self.s["backup_dir"]))
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.device = None
        self.udid = None
        self.backups: list[dict] = []
        self.preset = tk.StringVar(value=self.s["preset"])
        self.fmt = {f: tk.BooleanVar(value=f in self.s["formats"]) for f in ("web", "excel", "csv", "pdf")}
        self.pick_chats = tk.BooleanVar(value=self.s["pick_chats"])
        self.pick_photos = tk.BooleanVar(value=self.s["pick_photos"])
        for name, var in (("pick_chats", self.pick_chats), ("pick_photos", self.pick_photos)):
            var.trace_add("write", lambda *_, n=name, v=var: self.s.__setitem__(n, v.get()))
        for f, var in self.fmt.items():
            var.trace_add("write", lambda *_: self._formats_changed())
        self.last_index: Path | None = None
        self.notes: list[str] = []
        self._build()
        self._timers = {}
        self._timers["pump"] = self.after(100, self._pump)
        self._timers["spin"] = self.after(120, self._spin)
        self.guide = None
        import firstrun
        if firstrun.wanted(self):
            self.start_first_run()
        self._timers["first"] = self.after(300, self.detect)
        self.after(15000, self._auto_detect)
        self._start_listener()
        for seq in ("<Any-KeyPress>", "<Motion>", "<Button>", "<MouseWheel>"):     # S2: idle time
            self.bind_all(seq, self._touch, add="+")
        self._activity = time.time()
        self.after(20000, self._idle_check)
        self.after(500, lambda: self.log("App lock: " + (f"on ({applock.describe(self.lock_kind())}), locks after "
                                                         f"{self.s['lock_idle_minutes']} idle minutes" if self.lock_on()
                                                         else "off" if self.lock_kind() else "not available on this computer"
                                                         + (f" [{applock.last_problem}]" if applock.last_problem else "")) + "."))
        self.after(1500, self.start_helper)

    # ------------------------------------------------------------------ layout
    def _build(self):
        head = ui.header(self)
        head.pack(fill="x")
        tk.Label(head, text="PhoneKeep", bg=theme.HEADER_BG, fg=theme.HEADER_TITLE, font=font(21, "bold")).pack(side="left", padx=(22, 10), pady=14)
        # right-hand items first, so a narrow window trims the tagline instead of overlapping it; a test build
        # shows "· test build" here and its full label in About (13 Nov: the long label ran over the tagline)
        ui.RoundButton(head, "⚙  Settings", self.open_settings, "ghost", 130, 34, 13).pack(side="right", padx=16)
        ver = tk.Label(head, text=f"v{wv.VERSION}" + (" · test build" if wv.BUILD_LABEL else ""), bg=theme.HEADER_BG,
                       fg=theme.HEADER_TEXT, font=font(11), cursor="hand2")
        ver.pack(side="right", padx=(0, 4))
        ver.bind("<Button-1>", lambda e: self.open_about())
        tk.Label(head, text="Back up your iPhone to this computer", bg=theme.HEADER_BG, fg=theme.HEADER_TEXT,
                 font=font(13)).pack(side="left", pady=14)

        # problem banner (E3): one sentence, one button, Show details. Packed only when needed.
        self.bar_frame = tk.Frame(self, bg=theme.ERROR_BG)
        self.bar_text = tk.Label(self.bar_frame, text="", bg=theme.ERROR_BG, fg=INK, font=font(13), anchor="w",
                                 justify="left", wraplength=560)
        self.bar_text.pack(side="left", padx=16, pady=10, fill="x", expand=True)
        self.bar_btn = None
        self.bar_details = tk.Label(self.bar_frame, text="Show details", bg=theme.ERROR_BG, fg=MUTED, font=font(11), cursor="hand2")
        self.bar_details_text = ""
        self.bar_details.bind("<Button-1>", lambda e: ui.show_details(self, self.details_for_support(self.bar_details_text)))

        # the main window scrolls when it's taller than the screen (owner, 16 Nov: two phones nearby and the list of
        # phones pushed Back up now off a laptop screen); the scrollbar shows only then
        self.scroll_box = tk.Frame(self, bg=BG)
        self.scroll_box.pack(fill="both", expand=True)
        self.scroller = tk.Canvas(self.scroll_box, bg=BG, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self.scroll_box, orient="vertical", command=self.scroller.yview)
        self.scroller.configure(yscrollcommand=self.vbar.set)
        self.scroller.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.scroller, bg=BG)
        self._body_item = self.scroller.create_window(22, 16, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._fit_body())
        self.scroller.bind("<Configure>", lambda e: self._fit_body())
        ui.wheel_scroll(self.scroller)

        # device card
        dc = self.device_card = ui.card(self.body)
        dc.pack(fill="x")
        inner = tk.Frame(dc, bg=CARD)
        inner.pack(fill="x", padx=18, pady=14)
        self.phone = PhoneIcon(inner, CARD)
        self.phone.pack(side="left")
        info = tk.Frame(inner, bg=CARD)
        info.pack(side="left", fill="x", expand=True, padx=16)
        self.dev_name = tk.Label(info, text="Looking for your iPhone…", bg=CARD, fg=INK, font=font(19, "bold"), anchor="w")
        self.dev_name.pack(fill="x")
        self.dev_line = tk.Label(info, text="", bg=CARD, fg=MUTED, font=font(13), anchor="w", justify="left")
        self.dev_line.pack(fill="x", pady=(2, 0))
        self.dev_last = tk.Label(info, text="", bg=CARD, fg=MUTED, font=font(13), anchor="w")
        self.dev_last.pack(fill="x")
        self.dev_lock = tk.Label(info, text="", bg=CARD, fg=GREEN, font=font(12, "bold"), anchor="w")
        self.dev_lock.pack(fill="x", pady=(2, 0))
        btns = tk.Frame(inner, bg=CARD)
        btns.pack(side="right", anchor="n", before=info)
        self.open_btn = ui.RoundButton(btns, "Open iPhone  ›", self.open_phone, "primary", 160, 38, 13)
        self.open_btn.pack(anchor="e")
        ui.RoundButton(btns, "Refresh", self.detect, "secondary", 100, 30, 12).pack(anchor="e", pady=(8, 0))
        self.open_btn.set_enabled(False)
        # B8: every reachable iPhone, when there's more than one (or the chosen one went away)
        self.phone_list = tk.Frame(dc, bg=CARD)
        for w in (self.phone, self.dev_name):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e: self.open_phone())

        # E5: every phone backed up here or connected now, when there's more than one; each opens its own window
        self.all_phones = tk.Frame(self.body, bg=BG)
        top = tk.Frame(self.all_phones, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="Your iPhones · click one to open it", bg=BG, fg=MUTED, font=font(11, "bold"),
                 anchor="w").pack(side="left")
        self.add_link = tk.Label(top, text="+ Add another iPhone", bg=BG, fg=GREEN, font=font(12), cursor="hand2")
        self.add_link.pack(side="right")
        self.add_link.bind("<Button-1>", lambda e: self.add_phone())
        self.all_grid = tk.Frame(self.all_phones, bg=BG)
        self.all_grid.pack(fill="x", pady=(6, 0))
        self.phone_tiles = {}
        self._all_key = None
        self._all_gen = 0

        # what to keep
        wc = ui.card(self.body)
        wc.pack(fill="x", pady=14)
        tk.Label(wc, text="What do you want to keep?", bg=CARD, fg=INK, font=font(16, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(14, 8))
        tiles = tk.Frame(wc, bg=CARD)
        tiles.pack(fill="x", padx=14)
        self.tiles = {}
        for i, (key, (icon, title, sub, _secs)) in enumerate(PRESETS.items()):
            img = ui.app_icon(f"keep_{key}", size=48)
            card = ui.ChoiceCard(tiles, img, title, sub if img is not None else f"{icon}  {sub}",
                                 lambda k=key: self._choose_preset(k), bg=CARD)
            card.grid(row=0, column=i, sticky="ew", padx=5)
            tiles.columnconfigure(i, weight=1, uniform="t")
            self.tiles[key] = card
        # the options, aligned: labels in one column, small even pills beside them
        opts = tk.Frame(wc, bg=CARD)
        opts.pack(fill="x", padx=19, pady=(14, 16))
        for r, (label, chips) in enumerate((
                ("Save chats as", [(lab, self.fmt[f]) for f, lab in (("web", "Web pages"), ("pdf", "PDF"),
                                                                       ("excel", "Excel"), ("csv", "CSV"))]),
                ("Let me choose", [("which chats", self.pick_chats), ("which photos", self.pick_photos)]))):
            tk.Label(opts, text=label, bg=CARD, fg=MUTED, font=font(12), anchor="w").grid(
                row=r, column=0, sticky="w", padx=(0, 14), pady=4)
            row = tk.Frame(opts, bg=CARD)
            row.grid(row=r, column=1, sticky="w", pady=4)
            for text, var in chips:
                ui.Chip(row, text, var, size=12, bg=CARD, height=28).pack(side="left", padx=(0, 6))
        self._choose_preset(self.preset.get(), save=False)

        # main button
        self.go = ui.RoundButton(self.body, "Back up now", self.backup_and_export, "primary", 400, 50, 16)
        self.go.pack(fill="x")
        # progress (L2, 5.2): while a job runs, one card takes the window's place: the phone, the big percentage,
        # the bar and time left, what is happening now, "Look at your iPhone" when it needs the user, the steps
        # and Cancel (docs/spec/14-layouts.md#l2-backup-progress-screen)
        self.prog = tk.Frame(self.body, bg=BG)
        card = ui.card(self.prog)
        card.pack(fill="x")
        pin = tk.Frame(card, bg=CARD)
        pin.pack(fill="x", padx=26, pady=(22, 16))
        top = tk.Frame(pin, bg=CARD)
        top.pack(fill="x")
        self.prog_phone = PhoneIcon(top, CARD)
        self.prog_phone.pack(side="left")
        who = tk.Frame(top, bg=CARD)
        who.pack(side="left", fill="x", expand=True, padx=16)
        self.prog_kicker = tk.Label(who, text="Backing up", bg=CARD, fg=theme.ACCENT, font=font(13), anchor="w")
        self.prog_kicker.pack(fill="x")
        self.prog_name = tk.Label(who, text="", bg=CARD, fg=INK, font=font(22, "bold"), anchor="w")
        self.prog_name.pack(fill="x")
        self.prog_line = tk.Label(who, text="", bg=CARD, fg=MUTED, font=font(13), anchor="w")
        self.prog_line.pack(fill="x")
        nums = tk.Frame(pin, bg=CARD)
        nums.pack(fill="x", pady=(16, 0))
        self.pct_lbl = tk.Label(nums, text="", bg=CARD, fg=INK, font=font(34, "bold"), anchor="w")
        self.pct_lbl.pack(side="left")
        self.eta_lbl = tk.Label(nums, text="", bg=CARD, fg=MUTED, font=font(13), anchor="e")
        self.eta_lbl.pack(side="right", anchor="s", pady=(0, 6))
        self.bar = Bar(pin)
        self.bar.pack(fill="x", pady=(6, 4))
        self.now_lbl = tk.Label(pin, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w", justify="left",
                                wraplength=560)
        self.now_lbl.pack(fill="x")
        self.now_lbl.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(200, e.width - 4)))
        # "Look at your iPhone": amber, inside the card, while the phone waits for its passcode
        self.attn = tk.Frame(pin, bg=theme.WARN_BG, highlightthickness=1, highlightbackground=theme.WARN_TEXT)
        tk.Label(self.attn, text="📱", bg=theme.WARN_BG, fg=theme.WARN_TEXT, font=font(18)).pack(
            side="left", padx=(14, 8), pady=10, anchor="n")
        aw = tk.Frame(self.attn, bg=theme.WARN_BG)
        aw.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 14))
        tk.Label(aw, text="Look at your iPhone", bg=theme.WARN_BG, fg=theme.WARN_TEXT, font=font(14, "bold"),
                 anchor="w").pack(fill="x")
        self.attn_text = tk.Label(aw, text="", bg=theme.WARN_BG, fg=theme.WARN_TEXT, font=font(13), anchor="w",
                                  justify="left", wraplength=520)
        self.attn_text.pack(fill="x")
        self.steps_box = tk.Frame(pin, bg=CARD)
        self.steps_box.pack(fill="x", pady=(14, 0))
        self.steps = {}
        self._show_steps(STEPS)
        row = tk.Frame(pin, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        self.details_btn = tk.Label(row, text="Show details ▸", bg=CARD, fg=GREEN, font=font(12), cursor="hand2")
        self.details_btn.pack(side="left")
        self.details_btn.bind("<Button-1>", lambda e: self._toggle_details())
        self.log_frame = tk.Frame(pin, bg=CARD)
        self.log_box = tk.Text(self.log_frame, height=9, wrap="word", state="disabled", relief="flat",
                               bg=theme.SUBTLE, fg=INK, font=("Menlo" if sys.platform == "darwin" else "Consolas", 10),
                               highlightthickness=1, highlightbackground=LINE)
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))
        tk.Frame(pin, bg=LINE, height=1).pack(fill="x", pady=(14, 12))
        foot = tk.Frame(pin, bg=CARD)
        foot.pack(fill="x")
        tk.Label(foot, text="🔒  Stays on this computer · never sent online", bg=CARD, fg=theme.ACCENT,
                 font=font(13), anchor="w").pack(side="left")
        # Cancel is always available for a long job (01-principles.md, 6); shown only while a backup runs
        self.cancel_btn = ui.RoundButton(foot, "Cancel backup", self.cancel_backup, "secondary", 150, 40, 14, bg=CARD)
        self.prog_after = tk.Label(self.prog, text=KEEP_OPEN, bg=BG, fg=MUTED, font=font(12))
        self.prog_after.pack(pady=(10, 0))

        # done
        self.done = ui.card(self.body)
        din = tk.Frame(self.done, bg=CARD)
        din.pack(fill="x", padx=18, pady=16)
        self.done_title = tk.Label(din, text="✅  Your archive is ready", bg=CARD, fg=INK, font=font(17, "bold"), anchor="w")
        self.done_title.pack(fill="x")
        self.done_sub = tk.Label(din, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w", justify="left", wraplength=640)
        self.done_sub.pack(fill="x", pady=(2, 10))
        brow = tk.Frame(din, bg=CARD)
        brow.pack(fill="x")
        ui.RoundButton(brow, "Open my archive", self.open_archive, "primary", 190, 42).pack(side="left")
        ui.RoundButton(brow, "Show in Finder" if sys.platform == "darwin" else "Open folder",
                       lambda: reveal(Path(self.s["archive_dir"])), "secondary", 160, 42).pack(side="left", padx=10)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", side="bottom", padx=22, pady=(0, 12))
        for text, cmd in (("Use an existing backup instead…", self.open_settings),
                          ("Open my archive", self.open_archive)):
            lab = tk.Label(foot, text=text, bg=BG, fg=GREEN, font=font(12), cursor="hand2")
            lab.pack(side="left" if "existing" in text else "right")
            lab.bind("<Button-1>", lambda e, c=cmd: c())

    def _choose_preset(self, key: str, save: bool = True):
        self.preset.set(key)
        for k, card in self.tiles.items():
            card.set(k == key)
        if save:
            self.s["preset"] = key
            if key == "custom":
                self.open_settings(focus="include")

    def _formats_changed(self):
        chosen = [f for f, v in self.fmt.items() if v.get()]
        if not chosen:  # always keep at least one format
            self.fmt["web"].set(True)
            return
        self.s["formats"] = chosen

    def _toggle_details(self):
        if self.log_frame.winfo_ismapped():
            self.log_frame.pack_forget()
            self.details_btn.configure(text="Show details ▸")
        else:
            self.log_frame.pack(fill="both", expand=True)
            self.details_btn.configure(text="Hide details ▾")

    # ------------------------------------------------------------------ plumbing
    def log(self, msg: str):
        self.q.put(("log", msg))

    def call(self, fn):
        self.q.put(("call", fn))

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", val + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                    self._friendly(val)
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self._timers["pump"] = self.after(80, self._pump)

    def destroy(self):
        for job in list(getattr(self, "_timers", {}).values()):
            try:
                self.after_cancel(job)
            except Exception:
                pass
        import quicklook
        quicklook.cleanup()          # Q1: copies made to play a video or song go when PhoneKeep closes
        super().destroy()

    def _spin(self):
        for r in getattr(self, "steps", {}).values():
            r.tick()
        self._timers["spin"] = self.after(60, self._spin)

    def _friendly(self, msg: str):
        """Show the latest meaningful log line under the active step."""
        msg = msg.strip()
        if not msg or msg.startswith("==") or msg.startswith("Traceback") or msg.startswith("File "):
            return
        if self.prog.winfo_manager():
            self.now_lbl.configure(text=msg[:140])

    def _ask(self, prompt: str) -> str | None:
        box, ev = {}, threading.Event()

        def ask():
            box["v"] = simpledialog.askstring(wv.APP_NAME, prompt, show="•", parent=self)
            ev.set()
        self.call(ask)
        ev.wait()
        return box.get("v")

    def _run(self, fn, done=None, quiet=False):
        if self.busy:
            if not quiet:
                messagebox.showinfo(wv.APP_NAME, "PhoneKeep is already working. Please wait for it to finish.")
            return
        self.busy = True
        self.go.set_enabled(False)
        self.go.configure_text("Working…")
        self._watch_cancel()

        def worker():
            result, err = None, None
            try:
                result = fn()
            except Exception as e:
                err = e
            self.call(lambda: self._finish(result, err, done, quiet, fn))
        threading.Thread(target=worker, daemon=True).start()

    def _watch_cancel(self):
        """Show the Cancel button while the backup helper runs, hide it otherwise."""
        if not self.winfo_exists():
            return
        exporting = self.busy and getattr(self, "_exporting", False)
        running = (wv.backup_running() or exporting) and bool(self.prog.winfo_manager())   # the guide has its own Cancel
        if running and not self.cancel_btn.winfo_manager():
            self.cancel_btn.configure_text("Cancel backup" if wv.backup_running() else "Cancel export")
            self.cancel_btn.set_enabled(True)
            self.cancel_btn.pack(side="right")
        elif not running and self.cancel_btn.winfo_manager():
            self.cancel_btn.pack_forget()
        if self.busy:
            self.after(500, self._watch_cancel)

    def cancel_backup(self):
        if wv.cancel_backup():
            self.cancel_btn.configure_text("Cancelling…")
            self.cancel_btn.set_enabled(False)
            self.log("Cancelling the backup…")
        elif getattr(self, "_exporting", False):
            self._export_cancel = True
            self.cancel_btn.configure_text("Cancelling…")
            self.cancel_btn.set_enabled(False)
            self.log("Cancelling the export…")

    def _finish(self, result, err, done, quiet, fn=None):
        closed = getattr(self, "_closed_while_busy", False) and self._window_away()    # B9
        self._closed_while_busy = False
        self.busy = False
        self.go.set_enabled(True)
        self.cancel_btn.pack_forget()
        self.go.configure_text("Back up again" if not err and self.last_index else "Back up now")
        self.passcode_notice(None)
        card = self._end_progress()    # L2: the window comes back; a problem shows in the banner at the top
        if err is not None:
            pr = self.problem_of(err)
            for r in self.steps.values():
                if r.state == "active":
                    r.set("error", detail=pr.message)
            self.log("ERROR: " + pr.message + (f"  [{pr.details.splitlines()[0]}]" if pr.details else ""))   # full text: Show details
            if not quiet:
                self.show_problem(pr, retry=(lambda: self._retry(fn, done, card)) if fn else None)
        else:
            self.hide_problem()
        if done:
            done(None if err is not None else result)
        if closed:
            self._after_closed_job(err)

    def _retry(self, fn, done, card):
        """The banner's Try again (or Back up now after a cancel): the same job, with its progress card back if it
        had one, so the retry shows its percentage and Cancel (reviewer, #73)."""
        if card is not None and not self._reset_progress(*card):
            return
        self._run(fn, done)

    # ------------------------------------------------------------------ problems (E3)
    @staticmethod
    def problem_of(err) -> errors.Problem:
        """Every error shown in this window comes through the one table in errors.py."""
        if isinstance(err, wv.PhoneKeepError) and err.button:
            return errors.Problem(err.key, str(err), err.button, err.action, err.details,
                                  failure=err.key not in ("drive_unavailable", "cancelled"))
        if isinstance(err, wv.PhoneKeepError):
            return errors.Problem("plain", str(err), "Try again", errors.TRY_AGAIN, err.details, failure=True)
        return errors.explain(err)

    def passcode_notice(self, text):
        """The iPhone is waiting for its passcode: say so at the top in big amber, bring the window to the
        front and ring once (13 Nov: a line in the activity text was easy to miss). text=None hides it."""
        if text is None:
            if getattr(self, "_passcode_up", False):
                self._passcode_up = False
                if self.attn.winfo_manager():
                    self.attn.pack_forget()
                else:
                    self.hide_problem()
            return
        self._passcode_up = True
        what = text.split(":", 1)[1].strip() if text.startswith("Look at your iPhone:") else text
        self._need_user("Look at your iPhone", what[:1].upper() + what[1:])    # B9: the window was closed while backing up
        if self.prog.winfo_manager():                     # L2: in the progress card
            self.attn_text.configure(text=what[:1].upper() + what[1:])
            self.attn.pack(fill="x", pady=(14, 0), before=self.steps_box)
        else:
            self.show_problem(errors.Problem("passcode", "📱  " + text, "", "", failure=False))
            self.bar_text.configure(font=font(16, "bold"))
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(1500, lambda: self.attributes("-topmost", False))
            self.bell()
        except tk.TclError:
            pass

    def details_for_support(self, details: str) -> str:
        """The error itself, then what PhoneKeep was doing (the activity panel's lines), for one Copy."""
        try:
            activity = self.log_box.get("1.0", "end").strip()
        except tk.TclError:
            activity = ""
        about = f"{wv.APP_NAME} {wv.VERSION}" + (f" (build {wv.BUILD_LABEL})" if wv.BUILD_LABEL else "") + f" · {sys.platform}"
        return f"{details}\n\n--- what PhoneKeep was doing ---\n{activity}\n\n--- {about} ---" if activity else f"{details}\n\n--- {about} ---"

    def show_problem(self, pr: errors.Problem, retry=None):
        """Inline banner at the top: one sentence + one button; red only for real failures."""
        colour = theme.ERROR_BG if pr.failure else theme.WARN_BG
        self.bar_frame.configure(bg=colour)
        self.bar_text.configure(text=pr.message, bg=colour, fg=INK if pr.failure else theme.WARN_TEXT, font=font(13))
        self.bar_details.configure(bg=colour)
        if self.bar_btn is not None:
            self.bar_btn.destroy()
            self.bar_btn = None
        cmd = None
        if pr.action == errors.TRY_AGAIN and retry:
            cmd = lambda: (self.hide_problem(), retry())
        elif pr.action == errors.CHANGE_LOCATION:
            cmd = lambda: self.open_settings("backup_dir")
        elif pr.action == errors.INSTALL_APPLE_DEVICES:
            cmd = lambda: webbrowser.open("https://apps.microsoft.com/detail/9NP83LWLPZ9K")
        elif pr.action == errors.SHOW_DETAILS:
            cmd = lambda: ui.show_details(self, self.details_for_support(pr.details or pr.message))
        elif pr.action == errors.ENTER_PASSWORD and retry:
            cmd = lambda: (self.hide_problem(), retry())
        if cmd:
            self.bar_btn = ui.RoundButton(self.bar_frame, pr.button, cmd, "secondary", 170, 32, 12, bg=colour)
            self.bar_btn.pack(side="right", padx=12, pady=6)
        self.bar_details_text = pr.details
        self.bar_details.pack_forget()
        if pr.details and pr.action != errors.SHOW_DETAILS:
            self.bar_details.pack(side="right", padx=(0, 6))
        if not self.bar_frame.winfo_ismapped():
            self.bar_frame.pack(fill="x", before=self.scroll_box)

    def hide_problem(self):
        self.bar_frame.pack_forget()

    # ------------------------------------------------------------------ device
    def _auto_detect(self):
        if not self.busy:
            self.detect(silent=True)
        # the first-run guide waits for the phone, so look more often while it is up
        self._timers["detect"] = self.after(3000 if self.guide is not None else 15000, self._auto_detect)

    # ------------------------------------------------------------------ the menu and Open backup (B5)
    def attach_menu(self, win) -> None:
        """Give a PhoneKeep window the app's menu bar. On macOS every window shows its own menu, and a
        Toplevel without one shows Tk's default File menu ("Source…", "Run Widget Demo") — seen 12 Nov."""
        bar = getattr(self, "menubar", None)
        if bar is not None:
            try:
                win.configure(menu=bar)
            except tk.TclError:
                pass

    def quit_app(self):
        """Quit from the menu (Cmd+Q), the red button or the Dock: close every window and end the process.
        Background threads (phone readers, a helper being watched) must never keep a windowless PhoneKeep
        alive — macOS would then 'open' the invisible one instead of starting the app (found 12 Nov).
        B9: while a backup runs, quitting asks first, and stops the backup if the answer is yes."""
        if self._backing_up():
            self._come_back()
            if not messagebox.askokcancel(
                    "Stop the backup and quit?",
                    "A backup is running. If you quit now, it stops; the next backup carries on from where it "
                    "stopped.\n\nTo let it finish, close the window instead: PhoneKeep tells you when it's done.",
                    icon="warning", parent=self):
                return
            wv.cancel_backup()
        try:
            self.destroy()
        finally:
            os._exit(0)

    # ------------------------------------------------------------------ B9: closing the window while a backup runs
    def _backing_up(self) -> bool:
        """A backup (with its progress card) is running: the job closing the window lets carry on."""
        return self.busy and bool(self.prog.winfo_manager()) and getattr(self, "_card_for", (None,))[0] is STEPS

    def _window_away(self) -> bool:
        """The window was closed while backing up and hasn't come back. PhoneKeep's own flag, not the window's
        state: without a window manager (or with one that ignores minimising) the state stays "normal"."""
        return getattr(self, "_away", False)

    def _mapped(self, e):
        if e.widget is self:            # the window itself is back on the screen (Dock click, taskbar)
            self._away = False

    def close_window(self):
        """The window's close button. While a backup runs the window goes away and the backup carries on
        (Mac: the Dock icon brings it back; Windows and Linux: it waits in the taskbar). Otherwise PhoneKeep
        quits, as before."""
        try:
            self.update()               # window events still queued from before (e.g. it just came back) go first
        except tk.TclError:
            pass
        if not self._backing_up():      # checked after that: the backup may have ended inside it
            self.quit_app()
            return
        self._closed_while_busy = True
        self._away = True
        self.log("The window was closed; the backup carries on.")
        if sys.platform == "darwin":
            self.withdraw()
        else:
            self.iconify()

    def notify(self, title: str, text: str) -> None:
        """The computer's own notification (local only, S3)."""
        import helper_ui
        helper_ui.notify_system(title, text)

    def _come_back(self):
        self._away = False
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _need_user(self, title: str, text: str):
        """The backup carrying on with the window closed needs the user: say so and bring the window back."""
        if getattr(self, "_closed_while_busy", False) and self._window_away():
            self.notify(title, text)
            self._come_back()

    def _after_closed_job(self, err):
        """The backup that carried on with the window closed has ended: a notification says how. Done: PhoneKeep
        quits, as the closed window asked (unless another PhoneKeep window is open). Not done: the window
        comes back with the problem and its button."""
        name = (self.device or {}).get("DeviceName") or "Your iPhone"
        if err is not None:
            self.notify("Backup didn't finish", self.problem_of(err).message)
            self._come_back()
            return
        self.notify("Backup finished", f"{name} is backed up.")
        if sys.platform == "win32":
            self._come_back()     # the main window can't show a Windows notification yet, so it comes back instead
            return
        others = [w for w in self.winfo_children() if isinstance(w, tk.Toplevel) and w.state() != "withdrawn"]   # minimised counts
        if not others:
            self.after(1000, self.quit_app)

    def show_all_windows(self):
        """Bring back every PhoneKeep window (minimised, hidden behind other apps or off the screen)."""
        self._away = False
        wins = [self] + [w for w in self.winfo_children() if isinstance(w, tk.Toplevel)]
        for w in wins:
            try:
                # deiconify whatever Tk says the state is: on Tk 9 a window minimised to the Dock doesn't
                # always report "iconic". Only dialogs PhoneKeep withdrew on purpose stay hidden.
                if w is self or w.state() != "withdrawn":
                    w.deiconify()
                x, y = w.winfo_x(), w.winfo_y()
                sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
                if x > sw - 80 or y > sh - 80 or x + w.winfo_width() < 80 or y < 0:
                    w.geometry(f"+{max(0, (sw - w.winfo_width()) // 2)}+{max(30, (sh - w.winfo_height()) // 3)}")
                w.lift()
            except tk.TclError:
                pass
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _build_menu(self):
        if sys.platform == "darwin":
            self.createcommand("tk::mac::Quit", self.quit_app)
            # a click on the Dock icon brings PhoneKeep's windows back, even minimised or behind others
            self.createcommand("tk::mac::ReopenApplication", self.show_all_windows)
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.bind("<Map>", self._mapped, add="+")
        bar = tk.Menu(self)
        filem = tk.Menu(bar, tearoff=0)
        filem.add_command(label="Open backup…", command=self.open_backup_dialog, accelerator="Cmd+O" if sys.platform == "darwin" else "Ctrl+O")
        filem.add_command(label="Open iPhone", command=self.open_phone)
        filem.add_separator()
        filem.add_command(label="Settings…", command=self.open_settings)
        if sys.platform != "darwin":
            filem.add_separator()
            filem.add_command(label="Quit", command=self.quit_app)
        bar.add_cascade(label="File", menu=filem)
        helpm = tk.Menu(bar, tearoff=0)
        helpm.add_command(label=f"About {wv.APP_NAME}", command=self.open_about)
        bar.add_cascade(label="Help", menu=helpm)
        self.menubar = bar
        self.configure(menu=bar)
        self.bind_all("<Command-o>" if sys.platform == "darwin" else "<Control-o>", lambda e: self.open_backup_dialog())
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        """A folder dropped onto the window: open it as a backup if it is one."""
        paths = self.tk.splitlist(event.data)
        for p in paths:
            if self.open_backup(Path(p)):
                return

    def open_backup(self, path: Path, udid: str = None) -> bool:
        """Open any backup folder in a phone window (PhoneKeep snapshot, phone folder, Finder or iTunes backup).
        `udid`: the phone it belongs to, when known (else the window works it out from the folder)."""
        import snapshots as _snaps
        path = Path(path)
        if path.is_dir() and not (path / "Manifest.db").exists():
            latest = _snaps.latest_backup_path(path.parent, path.name) if (path / "format.json").exists() or (path / "snapshots").is_dir() else None
            if latest is None and (path / "Manifest.db").exists() is False and path.name == "snapshots":
                latest = None
            path = latest or path
        if not (path / "Manifest.db").exists():
            self.show_problem(errors.Problem("not_a_backup", "That folder isn't an iPhone backup.", "Choose a backup…", errors.TRY_AGAIN),
                              retry=self.open_backup_dialog)
            return False
        def go():
            import phone
            win = phone.PhoneWindow(self, {}, udid, backup=path)
            self.phone_windows = getattr(self, "phone_windows", []) + [win]
            phone_write.log_activity(f"Opened the backup {path}", kind="backup")
        self.require_unlock(go, "open this backup in PhoneKeep")
        return True

    def open_backup_dialog(self):
        OpenBackupDialog(self)

    # ------------------------------------------------------------------ first run (E1)
    def start_first_run(self):
        import firstrun
        self.main_cards = [w for w in self.body.winfo_children()]
        for w in self.main_cards:
            w.pack_forget()
        self.guide = firstrun.FirstRunGuide(self)
        self.guide.pack(fill="both", expand=True)
        self.after_idle(self._fit_body)

    def end_first_run(self):
        if self.guide is None:
            return
        self.guide.destroy()
        self.guide = None
        self.after_idle(self._fit_body)
        self._all_key = None
        for w in self.main_cards:
            if w is self.prog or w is self.done or w is self.all_phones:
                continue                            # "Your iPhones" comes back with the next search, if it's wanted
            w.pack(fill="x", pady=(0, 0) if w is self.main_cards[0] else (14, 0))
        self.detect(silent=True)

    FEATURES = {"scheduler": True, "app_lock": True}   # flipped on by the PR that ships each feature

    def has_feature(self, name: str) -> bool:
        return bool(self.FEATURES.get(name))

    def has_touch_id(self) -> bool:
        return self.lock_kind() == "touch_id"

    # ------------------------------------------------------------------ app lock (S2)
    def lock_kind(self):
        """What this computer locks PhoneKeep with ("touch_id" | "password" | "hello"), or None. Asked once."""
        if not hasattr(self, "_lock_kind"):
            kind = applock.available()
            # once Touch ID has been seen on this Mac, it stays a Touch ID Mac: with the lid closed macOS reports
            # only the password, which would otherwise turn the lock's default off (owner's MacBook, 13 Nov)
            if kind == "touch_id" and not self.s.data.get("touch_id_seen"):
                self.s["touch_id_seen"] = True
            elif kind == "password" and self.s.data.get("touch_id_seen"):
                kind = "touch_id"
            self._lock_kind = kind
        return self._lock_kind

    def lock_on(self) -> bool:
        kind = self.lock_kind()
        if kind is None:
            return False
        v = self.s["app_lock"]
        return applock.default_on(kind) if v is None else bool(v)

    def is_unlocked(self) -> bool:
        return not self.lock_on() or getattr(self, "_unlocked", False)

    def require_unlock(self, then, reason: str = "open your iPhone's data in PhoneKeep"):
        """Run `then` now if PhoneKeep is unlocked, else after Touch ID / the computer password / Windows Hello.
        Cancelling does nothing (the window stays closed). Scheduled backups never come through here."""
        if self.is_unlocked():
            self._activity = time.time()
            then()
            return
        if getattr(self, "_asking_unlock", False):
            return

        def ask():
            ok = applock.authenticate(reason)
            self.call(lambda: done(ok))

        def done(ok):
            self._asking_unlock = False
            if ok:
                self._unlocked = True
                self._activity = time.time()
                self.log("PhoneKeep unlocked.")
                then()
        self._asking_unlock = True
        threading.Thread(target=ask, daemon=True).start()

    def confirm_private(self, then, reason: str = "show your hidden photos"):
        """P1 Hidden: always asks, even when PhoneKeep is unlocked: Touch ID / the computer's password when the
        app lock is on, otherwise a confirmation. Cancelling does nothing."""
        if self.lock_on():
            def ask():
                ok = applock.authenticate(reason)
                if ok:
                    self.call(then)
            threading.Thread(target=ask, daemon=True).start()
        elif messagebox.askyesno("Show hidden photos?", "These are the photos you hid on the iPhone. Show them here?",
                                 parent=self.focus_get() or self):
            then()

    def unlock_blocking(self, reason: str = "show your chats and photos") -> bool:
        """From a worker thread (the export's chooser step): wait for the unlock. True if unlocked."""
        if self.is_unlocked():
            return True
        box, ev = {"ok": False}, threading.Event()
        self.call(lambda: self.require_unlock(lambda: (box.update(ok=True), ev.set()), reason))
        # if the person cancels, require_unlock never calls back: give up when the prompt has closed
        while not ev.wait(0.5):
            if not getattr(self, "_asking_unlock", False) and not self.is_unlocked():
                return False
        return box["ok"]

    def _touch(self, e=None):
        """Activity counts only while PhoneKeep is the app in front: the pointer passing over a PhoneKeep
        window while the owner works in another app kept it unlocked forever (owner's Mac, 13 Nov)."""
        try:
            if self.focus_get() is None:
                return
        except (tk.TclError, KeyError):
            return
        self._activity = time.time()

    def _idle_check(self):
        """Every 20 s: after the chosen idle minutes, lock again and cover every phone window."""
        try:
            if self.lock_on() and getattr(self, "_unlocked", False):
                idle = time.time() - getattr(self, "_activity", time.time())
                if idle >= 60 * int(self.s["lock_idle_minutes"]):
                    self.lock_now()
        finally:
            self.after(20000, self._idle_check)

    def lock_now(self):
        self._unlocked = False
        for win in self.open_phone_windows():
            try:
                win.cover_locked()
            except tk.TclError:
                pass
        self.log("PhoneKeep locked after being idle.")

    def open_phone_windows(self) -> list:
        wins = list(getattr(self, "phone_windows", [])) + [getattr(self, "phone_win", None)]
        out = []
        for w in wins:
            try:
                if w is not None and w.winfo_exists() and w not in out:
                    out.append(w)
            except tk.TclError:
                pass
        return out

    def _show_device(self, d: dict):
        self.device = d
        self.udid = d.get("UniqueDeviceID") or d.get("Identifier")
        if self.s.data.get("chosen_udid") != self.udid:
            self.s["chosen_udid"] = self.udid
        if self.s.data.get("chosen_name") != (d.get("DeviceName") or "iPhone"):
            self.s["chosen_name"] = d.get("DeviceName") or "iPhone"
        how = "USB cable" if d.get("ConnectionType") == "USB" else "Wi-Fi"
        self._show_phone_picture(self.udid)
        self.phone.set_state("ok")
        if d.get("ConnectionType") == "USB":
            self._read_home_screen(self.udid)
        self.dev_name.configure(text=d.get("DeviceName") or "iPhone")
        self.dev_line.configure(text=f"iOS {d.get('ProductVersion', '?')} · connected by {how}"
                                + ("  (a cable is faster for the first backup)" if how == "Wi-Fi" else ""), fg=MUTED)
        import snapshots as _snaps
        latest = _snaps.latest_backup_path(Path(self.s["backup_dir"]), self.udid)
        info = wv.backup_info(latest) if latest else None
        half = (not info) and (wv.backup_incomplete(Path(self.s["backup_dir"]) / self.udid)
                               or wv.backup_incomplete(_snaps.current_dir(Path(self.s["backup_dir"]), self.udid)))
        state, line = self.health_line(info)
        if half:
            state, line = "amber", "The last backup didn't finish. Back up again to complete it."
        self.dev_last.configure(text=line or ("Not backed up with PhoneKeep yet" if not info else f"Last backup: {info['date']}"),
                                fg=AMBER if state == "amber" else MUTED)
        self.dev_lock.configure(text=self.lock_badge(info),
                                fg=GREEN if not info or info.get("encrypted") else theme.WARN_TEXT)   # a warning
        self.open_btn.set_enabled(True)

    # 5.1.3: the phone's own home screen in the small phone picture ------------------------------------------------
    HOME_RETRY = 60

    def _show_phone_picture(self, udid) -> None:
        """The saved home screen of this phone (None / not saved yet: the drawn phone). Redrawn only when it changed."""
        p = wv.phone_picture(udid) if udid else None
        key = (str(p), p.stat().st_mtime) if p is not None and p.exists() else None
        if key != getattr(self, "_picture_key", "unset"):
            self._picture_key = key
            self.phone.set_picture(p if key else None)

    def _read_home_screen(self, udid: str) -> None:
        """Over a cable, a fresh home screen once per session (again after a minute if it didn't come), read-only,
        in the background; it quietly replaces the saved one."""
        tried = getattr(self, "_home_read", {})
        self._home_read = tried
        if self.busy or tried.get(udid) == "done" or time.time() - tried.get(udid, 0) < self.HOME_RETRY:
            return
        tried[udid] = time.time()

        def work():
            try:
                import device as devmod
                live = devmod.LiveDevice(udid)
                try:
                    p = live.wallpaper("homescreen") or live.wallpaper("lockscreen")
                finally:
                    live.close()
                if wv.keep_phone_picture(udid, p):
                    tried[udid] = "done"
                    self.call(lambda: self._show_phone_picture(self.udid))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def choose_phone(self, udid: str):
        """B8: the owner picked a phone from the list; the options below are now for it."""
        if self.busy:
            return
        d = next((x for x in getattr(self, "devices", []) if (x.get("UniqueDeviceID") or x.get("Identifier")) == udid), None)
        if d is None:
            return
        if getattr(self, "phone_win", None) is not None:
            try:
                if self.phone_win.winfo_exists() and self.phone_win.udid != udid:
                    self.phone_win.destroy()             # the phone window was for the other phone
            except tk.TclError:
                pass
            self.phone_win = None
        self._show_device(d)
        self._fill_phone_list()
        self.log(f"Chose {d.get('DeviceName') or 'iPhone'}.")

    def _fill_phone_list(self):
        """B8: the reachable iPhones side by side as phones (wallpaper, name, model · iOS, cable / Wi-Fi, battery),
        shown when there's a choice to make. Wallpapers and battery are read in the background, again until they come back."""
        import models
        for w in self.phone_list.winfo_children():
            w.destroy()
        self._fill_all_phones()
        devs = getattr(self, "devices", [])
        if len(devs) < 2 and (len(devs) == 0 or self.udid is not None):
            self.phone_list.pack_forget()
            return
        self.phone_list.pack(fill="x", padx=18, pady=(0, 14))
        self.after_idle(self._fit_height)
        tk.Label(self.phone_list, text="iPhones nearby · click one to back it up", bg=CARD, fg=MUTED,
                 font=font(11, "bold"), anchor="w").pack(fill="x")
        row = tk.Frame(self.phone_list, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        self.phone_rows = {}
        self._phone_extra = getattr(self, "_phone_extra", {})          # udid -> {"wall": path, "battery": dict}
        for d in devs:
            udid = d.get("UniqueDeviceID") or d.get("Identifier")
            how = "cable" if d.get("ConnectionType") == "USB" else "Wi-Fi"
            card = ui.PhoneCard(row, d.get("DeviceName") or "iPhone", models.model_name(d.get("ProductType")),
                                d.get("ProductVersion", "?"), how, lambda u=udid: self.choose_phone(u), bg=CARD)
            card.pack(fill="x", pady=(0, 4))            # one line per phone (owner, 16 Nov)
            card.set(udid == self.udid)
            self.phone_rows[udid] = card
            extra = self._phone_extra.get(udid) or {}
            card.set_wallpaper(extra.get("wall") or self._saved_wallpaper(udid))
            card.set_battery(extra.get("battery"))
            if self._should_read_extra(udid):
                self._phone_extra.setdefault(udid, {})["reading"] = time.time()
                threading.Thread(target=self._read_phone_extra, args=(udid,), daemon=True).start()

    # E5: all phones in one list -------------------------------------------------------------------------------
    def _fill_all_phones(self):
        """Read the list in the background (the backup folder may be on a slow disk); the newest read wins."""
        self._all_gen += 1
        gen, devs, bdir = self._all_gen, list(getattr(self, "devices", [])), Path(self.s["backup_dir"])

        def work():
            try:
                phones = phone_summaries(bdir, devs)
            except Exception:
                return
            self.call(lambda: gen == self._all_gen and self._show_all_phones(phones))
        threading.Thread(target=work, daemon=True).start()

    def _show_all_phones(self, phones: list):
        if len(phones) < 2:
            self.all_phones.pack_forget()
        if self.prog.winfo_manager() or self.guide is not None:
            self._all_key = None                    # a job's card or the first-run guide fills the window: the next
            return                                  # search after it shows the list
        key = repr(phones)
        if key == self._all_key:
            return                                  # nothing changed: no flicker on every search for phones
        self._all_key = key
        for w in self.all_grid.winfo_children():
            w.destroy()
        self.phone_tiles = {}
        if len(phones) < 2:
            return
        for i, p in enumerate(phones):
            tile = ui.PhoneTile(self.all_grid, p, lambda u=p["udid"]: self.open_phone_for(u))
            tile.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else 6, 0), pady=(0, 6))
            self.phone_tiles[p["udid"]] = tile
        for col in (0, 1, 2):
            self.all_grid.columnconfigure(col, weight=1, uniform="p")
        self.all_phones.pack(fill="x", pady=(14, 0), after=self.device_card)
        self._fit_height()

    def _fit_body(self):
        """The main window's contents fill its width; taller than the window, they scroll (scrollbar shown)."""
        try:
            # only the width is set: the body keeps its own height, so it hears (<Configure>) every card that comes
            # or goes and the scroll area follows it (reviewer, #83)
            cw, ch = self.scroller.winfo_width(), self.scroller.winfo_height()
            need = self.body.winfo_reqheight() + 32
            # the first-run guide fills what's visible (its step list and footer sit at the bottom); 0 = own height
            fill = max(self.body.winfo_reqheight(), ch - 32) if self.guide is not None else 0
            self.scroller.itemconfigure(self._body_item, width=max(1, cw - 44), height=fill)
            self.scroller.configure(scrollregion=(0, 0, cw, max(need, ch)))
            if need > ch > 1:
                if not self.vbar.winfo_ismapped():
                    self.vbar.pack(side="right", fill="y", before=self.scroller)
            elif self.vbar.winfo_ismapped():
                self.vbar.pack_forget()
                self.scroller.yview_moveto(0)
        except tk.TclError:
            pass

    def _fit_height(self):
        """Grow the window when a list makes it taller than it is (never past the screen), so Back up now stays in
        view; past the screen the body scrolls (_fit_body)."""
        try:
            self.update_idletasks()
            have = self.winfo_height()
            # the header and any problem bar, plus everything in the (scrolling) body
            need = have - self.scroller.winfo_height() + self.body.winfo_reqheight() + 32
            if need <= getattr(self, "_fitted", 0):
                return                              # grown for this much once: the user's own size wins after that
            self._fitted = need
            if self.state() == "normal" and 1 < have < need:
                self.geometry(f"{self.winfo_width()}x{min(need, self.winfo_screenheight() - 80)}")
        except tk.TclError:
            pass

    def open_phone_for(self, udid: str):
        """E5: a phone's own window: the open one if there is one, else live when it's connected, else its latest
        backup on this computer (as B5 opens any backup). Choosing which phone to back up (B8) doesn't change."""
        for w in self.open_phone_windows():
            if getattr(w, "udid", None) == udid:
                w.deiconify()
                w.lift()
                w.focus_force()
                return
        d = next((x for x in getattr(self, "devices", []) if (x.get("UniqueDeviceID") or x.get("Identifier")) == udid), None)
        if d is not None and udid == self.udid:
            self.open_phone()
        elif d is not None:
            def go():
                import phone
                self.phone_windows = getattr(self, "phone_windows", []) + [phone.PhoneWindow(self, d, udid)]
            self.require_unlock(go)
        else:
            import snapshots as _snaps
            latest = _snaps.latest_backup_path(Path(self.s["backup_dir"]), udid)
            if latest is None:
                messagebox.showinfo(wv.APP_NAME, "This iPhone's backup isn't in the backup folder any more. "
                                    "Connect the iPhone to open it.", parent=self)
            else:
                self.open_backup(latest, udid)

    def add_phone(self):
        """E5: "Add another iPhone": how to connect it, then look for it. Nothing is written to any phone."""
        messagebox.showinfo("Add another iPhone", "Plug the other iPhone into this computer with a cable, unlock it "
                            "and tap Trust on it. It shows up here; choose it above to back it up.", parent=self)
        self.detect()

    # A phone on Wi-Fi comes and goes from the computer's list as it dozes, so a read can find nothing.
    # Read again (at most every 20 s) until both the picture and the battery came back, and keep the last
    # picture on disk so the card shows it straight away next time.
    EXTRA_RETRY = 20

    def _should_read_extra(self, udid: str) -> bool:
        extra = self._phone_extra.get(udid) or {}
        if self.busy or ((extra.get("wall") or extra.get("no_wall")) and extra.get("battery")):
            return False
        return time.time() - extra.get("reading", 0) >= self.EXTRA_RETRY

    @staticmethod
    def _wallpaper_file(udid: str) -> Path:
        return wv.phone_cache(udid) / "wallpaper.png"

    def _saved_wallpaper(self, udid: str):
        f = self._wallpaper_file(udid)
        return f if f.exists() else None

    def _read_phone_extra(self, udid: str):
        """Wallpaper (lock screen, else home screen) and battery of one phone, for its card."""
        extra = dict(self._phone_extra.get(udid) or {})
        d = next((x for x in getattr(self, "devices", []) if (x.get("UniqueDeviceID") or x.get("Identifier")) == udid), {})
        try:
            if d.get("ConnectionType") == "Network":      # the wallpaper only comes over a cable: the saved copy
                extra["wall"], extra["no_wall"] = self._saved_wallpaper(udid), True
                raise LookupError("over Wi-Fi")
            import device as devmod
            live = devmod.LiveDevice(udid)
            try:
                wall = live.wallpaper("lockscreen") or live.wallpaper("homescreen")
            finally:
                live.close()
            if wall:
                keep = self._wallpaper_file(udid)
                keep.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(wall, keep)
                extra["wall"] = keep
        except Exception:
            pass
        battery = (wv.battery_state(udid, timeout=wv.WIFI_TIMEOUT // 3) if d.get("ConnectionType") == "Network"
                   else wv.battery_state(udid))
        # a read that got no answer keeps what's known, including what a newer read found meanwhile (it would
        # otherwise blank the battery a later read had just shown)
        now = self._phone_extra.get(udid) or {}
        extra["battery"] = battery or now.get("battery") or extra.get("battery")
        extra["wall"] = extra.get("wall") or now.get("wall")
        self._phone_extra[udid] = extra

        def show():
            card = getattr(self, "phone_rows", {}).get(udid)
            if card is not None:
                try:
                    card.set_wallpaper(extra.get("wall"))
                    card.set_battery(extra.get("battery"))
                except tk.TclError:
                    pass
        self.call(show)

    def detect(self, silent: bool = False):
        if self.busy or getattr(self, "detecting", False):
            return

        def work():
            return wv.list_devices()

        def done(devs, err=None):
            self.detecting = False
            self.detect_error = err
            self.devices = devs or []
            ids = [d.get("UniqueDeviceID") or d.get("Identifier") for d in self.devices]
            chosen = self.s.data.get("chosen_udid")
            pick = None
            if chosen in ids:
                pick = self.devices[ids.index(chosen)]
            elif not chosen and len(self.devices) == 1:
                pick = self.devices[0]
            if pick is not None:
                self._show_device(pick)
            elif self.devices:
                # several phones and none chosen yet, or the chosen one went away: never switch by itself (B8)
                self.device = self.udid = None
                gone = chosen and chosen not in ids
                self._show_phone_picture(chosen if gone else None)
                self.phone.set_state("none")
                self.dev_name.configure(text=(f"{self.s.data.get('chosen_name') or 'Your iPhone'} is no longer connected"
                                              if gone else f"{len(self.devices)} iPhones nearby"))
                self.dev_line.configure(text="Choose the iPhone to back up below.", fg=MUTED)
                self.dev_last.configure(text="")
                self.dev_lock.configure(text="")
                self.open_btn.set_enabled(False)
            else:
                self.device = self.udid = None
                self._show_phone_picture(chosen)            # the last phone, dimmed, "not connected"
                self.phone.set_state("none")
                self.dev_name.configure(text="No iPhone found")
                self.dev_line.configure(text=err or "Plug in your iPhone (or use Wi-Fi sync), unlock it and tap “Trust”.",
                                        fg=RED if err else MUTED)
                self.dev_last.configure(text="")
                self.dev_lock.configure(text="")
                self.open_btn.set_enabled(False)
            self._fill_phone_list()
        if not silent:
            if self.udid is None:
                self._show_phone_picture(self.s.data.get("chosen_udid"))
            self.phone.set_state("searching")
            self.dev_name.configure(text="Looking for your iPhone…")

        def worker():
            try:
                devs = work()
                msg = None
            except wv.PhoneKeepError as e:
                devs, msg = None, str(e)
            self.call(lambda: done(devs, msg))
        self.detecting = True
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ pickers
    def _choose_chats(self, lists, preview):
        if not any(chats for _l, chats in lists.values()):
            return {}
        if not self.unlock_blocking("show your chats"):
            return None
        box, ev = {}, threading.Event()

        def show():
            self.steps["choose"].set("active", detail="Waiting for you: choose the chats to export…")
            self._need_user("Your backup is done", "Choose the chats to keep.")
            p = ui.ChatPicker(self, lists, preview)
            self.wait_window(p)
            box["v"] = p.result
            ev.set()
        self.call(show)
        ev.wait()
        if box.get("v") is not None:
            n = sum(len(v) for k, v in box["v"].items() if not k.startswith("_"))
            self.log(f"You selected {n} chat{'s' if n != 1 else ''}.")
            dates = box["v"].get("_dates")
            when = f" ({wv.describe_dates(dates)})" if dates else ""
            self.notes.append(f"{n} chat{'s' if n != 1 else ''}{when}")
        return box.get("v")

    def _choose_photos(self, source, items):
        if not self.unlock_blocking("show your photos"):
            return set()
        box, ev = {}, threading.Event()

        def show():
            self.steps["choose"].set("active", detail="Waiting for you: choose the photos to keep…")
            self._need_user("Your backup is done", "Choose the photos to keep.")
            p = ui.PhotoPicker(self, source, items, unlock=lambda go: self.confirm_private(go, "show your hidden photos"))
            self.wait_window(p)
            box["v"] = p.result
            ev.set()
        self.call(show)
        ev.wait()
        n = len(box.get("v") or ())
        self.log(f"You selected {n:,} photos & videos." if n else "Photos skipped.")
        self.notes.append(f"{n:,} photos & videos" if n else "no photos")
        return box.get("v")

    # ------------------------------------------------------------------ location (B4)
    def change_location(self, settings):
        """Settings → Location → Change…: pick a folder; offer to move the existing backups there."""
        import location as loc
        import snapshots as _snaps
        old = Path(self.s["backup_dir"])
        d = filedialog.askdirectory(title="Where should backups be kept?", initialdir=str(old if old.exists() else Path.home()), parent=settings)
        if not d:
            return
        new = Path(d)
        if new.resolve() == old.resolve():
            return
        try:
            _snaps.check_filesystem(new)
        except _snaps.FileSystemRefused as e:
            self.show_problem(errors.Problem("fat32", str(e), "Choose another", errors.TRY_AGAIN), retry=lambda: self.change_location(settings))
            return
        u = loc.usage(old)
        has_backups = u["used"] > 0
        move = False
        if has_backups:
            move = messagebox.askyesno(f"Move my existing backups to {loc.drive_name(new) if loc.drive_name(new) != 'this disk' else new.name}?",
                                       f"Your backups use {loc.human(u['used'])}. Move them to the new folder? "
                                       "They are copied and checked first; the old copy is removed only when everything matches.\n\n"
                                       "No = start fresh in the new folder (the old backups stay where they are).", parent=settings)
        messagebox.showinfo("Your backup password", "Your backup password lives in this computer's keychain. If you ever open these "
                            "backups on another computer, you'll need to type it there. If you forget it, the backup can't be opened.",
                            parent=settings)
        if not move:
            self.s["backup_dir"] = str(new)
            phone_write.log_activity(f"Backup location changed to {new}", kind="settings")
            settings.refresh_location()
            self.detect(silent=True)
            return

        def work():
            return loc.move_backups(old, new, log=self.log, progress=self._progress_backup_simple)

        def done(r):
            if r is not None:
                self.s["backup_dir"] = str(new)
                phone_write.log_activity(f"Backups moved to {new} ({r['files']:,} files)", kind="settings")
                if settings.winfo_exists():
                    settings.refresh_location()
                msg = f"Moved {r['files']:,} files ({loc.human(r['bytes'])}) to {new}."
                if r.get("left_behind"):
                    msg += ("\n\nThe old copy couldn't be removed from the old drive; it's still there and can be deleted "
                            "by hand: " + ", ".join(r["left_behind"]))
                messagebox.showinfo(wv.APP_NAME, msg, parent=self)
                self.detect(silent=True)
        if not self._reset_progress(MOVE_STEPS, "Moving your backups"):
            return
        self.steps["backup"].set("active")
        self.now_lbl.configure(text=f"To {new}")
        self._run(work, done)

    def _progress_backup_simple(self, pct):
        if not hasattr(self, "_simple_eta") or pct < 1:
            self._simple_eta = ui.Eta()
        right = self._simple_eta.feed(pct)
        self.call(lambda: self._set_pct(pct, right))

    # ------------------------------------------------------------------ automatic backups (B2)
    def set_schedule(self, mode: str, hour_text: str, day_text: str):
        hours = [f"{(h % 12) or 12} {'am' if h < 12 else 'pm'}" for h in range(24)]
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        self.s["auto_backup"] = mode
        if hour_text in hours:
            self.s["auto_backup_hour"] = hours.index(hour_text)
        if day_text in days:
            self.s["auto_backup_weekday"] = days.index(day_text)
        if mode != "off" and not self.s["start_at_login"]:
            self.set_start_at_login(True)          # the schedule runs from the helper, which must be there after a restart
        self.detect(silent=True)

    def health_line(self, info) -> tuple[str, str]:
        """("ok" | "amber" | "none", line) for the phone card (B2): last backup, next backup, or the amber fix."""
        import scheduler as sch
        if not self.udid:
            return "none", ""
        plan = sch.Plan.from_settings(self.s.data)
        health = sch.Health.load(Path(self.s["backup_dir"]) / self.udid)
        if health.last_ok is None and info and info.get("date"):
            try:
                health.last_ok = dt.datetime.strptime(info["date"], "%Y-%m-%d %H:%M")
            except ValueError:
                pass
        return sch.card_state(plan, health, dt.datetime.now())

    # ------------------------------------------------------------------ the helper (E2)
    def set_start_at_login(self, on: bool):
        import login_item
        import phone_write
        self.s["start_at_login"] = bool(on)
        try:
            if on:
                login_item.install()
                phone_write.log_activity("Helper set to start at login", kind="settings")
            else:
                login_item.remove()
                phone_write.log_activity("Helper no longer starts at login", kind="settings")
        except Exception as e:
            self.show_problem(self.problem_of(e))

    def start_helper(self):
        """Make sure the menu bar / tray helper is running (it keeps going after this window closes)."""
        import helper_core as hc
        import login_item
        if hc.helper_running() or os.environ.get("PHONEKEEP_NO_HELPER"):
            return
        try:
            subprocess.Popen(login_item.helper_command(), close_fds=True, **wv._NOWIN)
        except OSError:
            pass

    def _start_listener(self):
        """A loopback port the helper uses to say "open the window" / "open the phone" (netguard allows it)."""
        import helper_core as hc
        import socket
        try:
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(2)
            hc.PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            hc.PORT_FILE.write_text(str(srv.getsockname()[1]))
        except OSError:
            return
        self.listener = srv

        def serve():
            while True:
                try:
                    conn, _ = srv.accept()
                    with conn:
                        what = conn.recv(64).decode(errors="replace").strip()
                        if what == "phone":
                            self.call(self.open_phone_when_ready)
                        else:
                            self.call(lambda: (self.deiconify(), self.lift(), self.focus_force()))
                        conn.sendall(b"ok\n")
                except OSError:
                    return
        threading.Thread(target=serve, daemon=True).start()
        self.bind("<Destroy>", lambda e: e.widget is self and self._stop_listener(), add="+")

    def _stop_listener(self):
        import helper_core as hc
        try:
            self.listener.close()
            if hc.PORT_FILE.exists():
                hc.PORT_FILE.unlink()
        except Exception:
            pass

    def open_phone_when_ready(self, tries: int = 10):
        """Open the phone window as soon as the phone has been detected (used by the helper's Open iPhone)."""
        self.deiconify()
        self.lift()
        if self.device is not None:
            self.open_phone()
        elif tries > 0:
            if not getattr(self, "detecting", False):
                self.detect(silent=True)
            self.after(800, lambda: self.open_phone_when_ready(tries - 1))
        else:
            self.open_phone()

    # ------------------------------------------------------------------ phone window
    def open_phone(self):
        if self.device is None:
            messagebox.showinfo(wv.APP_NAME, "Connect your iPhone first (cable or Wi-Fi), unlock it and tap Trust.")
            return
        win = getattr(self, "phone_win", None)
        try:
            if win is not None and win.winfo_exists() and win.udid == self.udid:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        def go():
            import phone
            self.phone_win = phone.PhoneWindow(self, self.device, self.udid)
        self.require_unlock(go)

    # ------------------------------------------------------------------ actions
    def _show_steps(self, rows):
        for w in self.steps_box.winfo_children():
            w.destroy()
        self.steps = {}
        for n, (key, title) in enumerate(rows, 1):
            r = StepRow(self.steps_box, n, title)
            r.pack(fill="x", pady=1)
            self.steps[key] = r

    def _reset_progress(self, rows=STEPS, kicker: str = "Backing up"):
        """L2: the progress card takes the window's place until the job ends (_finish puts the window back).
        Returns False, changing nothing, while a job runs: its steps must stay as they are (reviewer, #73)."""
        if self.busy:
            messagebox.showinfo(wv.APP_NAME, "PhoneKeep is already working. Please wait for it to finish.", parent=self)
            return False
        self.notes = []
        self.done.pack_forget()
        self.hide_problem()
        self._show_steps(rows)
        self._card_for = (rows, kicker)          # a retry from the banner brings back the same card
        d = self.device or {}
        self.prog_kicker.configure(text=kicker)
        self.prog_after.configure(text=CLOSE_OK if rows is STEPS else KEEP_OPEN)     # B9: only a backup carries on
        self.prog_name.configure(text=d.get("DeviceName") or ("Your iPhone" if rows is not EXPORT_STEPS else "Your backup"))
        self.prog_line.configure(text=self.dev_line.cget("text") if d else "")
        self.prog_phone.set_picture(self.phone.picture)
        self.prog_phone.set_state(self.phone.state or "searching")
        self.attn.pack_forget()
        self.now_lbl.configure(text="")
        self._set_pct(None, "")
        if not self.prog.winfo_manager():
            self._hidden = [(w, w.pack_info()) for w in self.body.winfo_children()
                            if w.winfo_manager() == "pack" and w is not self.prog]
            for w, _i in self._hidden:
                w.pack_forget()
            self.prog.pack(fill="x", padx=30, pady=(4, 0))
        return True

    def _end_progress(self):
        """Put the window back as it was before the job (the finished card, if any, goes under it).
        Returns the card's (rows, kicker) if it was up, else None."""
        if not self.prog.winfo_manager():
            return None
        self.prog.pack_forget()
        self.attn.pack_forget()
        for w, info in getattr(self, "_hidden", []):
            info.pop("in", None)
            w.pack(**info)
        self._hidden = []
        return getattr(self, "_card_for", None)

    def _set_pct(self, pct, right: str):
        """The big percentage, the bar and the time left (None: nothing to show yet)."""
        self.bar.set(pct or 0)
        self.pct_lbl.configure(text="" if pct is None else f"{pct:.0f}%")
        self.eta_lbl.configure(text=right)

    def _backup_phase(self, key: str):
        """Move the backup's steps on to this one (ready → copy → snapshot); earlier ones are done."""
        order = [k for k, _t in STEPS[:3]]
        if key not in order or key not in self.steps:
            return
        for k in order[:order.index(key)]:
            if self.steps[k].state != "done":
                self.steps[k].set("done", detail="", right="")
        if self.steps[key].state != "active":
            self.steps[key].set("active")

    def _backup_status(self, text: str):
        if text.startswith("Saving this backup as a snapshot"):
            self._backup_phase("snapshot")
        elif "copied from the iPhone" in text:
            self._backup_phase("copy")
        self.now_lbl.configure(text=text)

    def _progress_backup(self, pct: float, t0: list):
        # The time left is estimated from the speed over the last few minutes, so it settles
        # quickly and follows changes (e.g. many small files, then big videos).
        now = time.time()
        if pct > 0.5:
            t0.append((now, pct))
            while len(t0) > 2 and now - t0[1][0] > 300:   # t0[0] is kept for the overall start
                t0.pop(1)
        eta = ""
        pts = [x for x in t0[1:] if x]
        if len(pts) >= 2 and pct > pts[0][1] + 0.5 and now - pts[0][0] > 20:
            rate = (pct - pts[0][1]) / (now - pts[0][0])
            eta = _fmt_eta((100 - pct) / rate) if rate > 0 else ""
        right = eta[:1].upper() + eta[1:] if eta else "Working out the time left…"

        def show():
            if pct >= 0.5 and pct < 100:
                self._backup_phase("copy")
            self._set_pct(pct, right)
        self.call(show)

    def _export_progress(self, pct: float):
        """Progress of the archive build; raising here is how Cancel stops the export."""
        if getattr(self, "_export_cancel", False):
            raise sx.ExportCancelled()
        self._progress_build(pct)

    def _progress_build(self, pct: float):
        if not hasattr(self, "_build_eta") or pct < 1:
            self._build_eta = ui.Eta()
        right = self._build_eta.feed(pct)

        def ui_update():
            if self.steps["choose"].state == "active":
                self.steps["choose"].set("done", detail="")
                self.steps["build"].set("active")
            self._set_pct(pct, right)
        self.call(ui_update)

    def _export(self, path: Path) -> Path:
        self._exporting, self._export_cancel = True, False
        try:
            return self._export_inner(path)
        finally:
            self._exporting = False

    def _export_inner(self, path: Path) -> Path:
        info = wv.backup_info(path)
        pw = None
        if info["encrypted"]:
            pw = self.password_for(path, info["name"])
            if not pw:
                raise wv.PhoneKeepError("Cancelled: the backup password is needed to read an encrypted backup.")
        secs = self.s.sections()
        if not secs:
            raise wv.PhoneKeepError("Nothing is selected to keep. Choose a preset or tick items in Settings.")
        wants_chats = self.pick_chats.get() and any(k in secs for k, _l in sx.CHAT_SECTIONS)
        wants_photos = self.pick_photos.get() and "photos" in secs and self.s["include_media"]
        self.call(lambda: (self.prog_kicker.configure(text="Building your archive"), self._set_pct(None, ""),
                           self.steps["choose"].set("active"),
                           self.now_lbl.configure(text="Reading your chats and photos…" if (wants_chats or wants_photos)
                                                  else "Getting ready…")))
        direct = self.s["direct_photos"] and self.udid is not None and "photos" in secs
        index = sx.export_all(path, Path(self.s["archive_dir"]), pw, secs,
                              include_media=self.s["include_media"], log=self.log,
                              progress=self._export_progress,
                              chooser=self._choose_chats if wants_chats else None,
                              formats={f for f, v in self.fmt.items() if v.get()},
                              photo_source="device" if direct else None, udid=self.udid,
                              photo_chooser=self._choose_photos if wants_photos else None)
        return index

    def backup_and_export(self):
        if self.device is None and not messagebox.askyesno(
                wv.APP_NAME, "No iPhone is connected right now.\n\nTry anyway?"):
            return
        if not self._reset_progress(STEPS, "Backing up"):
            return
        t0 = [None]

        def work():
            self.call(lambda: (self._backup_phase("ready"),
                               self.now_lbl.configure(text="Checking that your backups are encrypted…")))
            self.ensure_encryption()
            self.call(lambda: self.now_lbl.configure(
                text="Connecting… Keep your iPhone unlocked and nearby. If it asks for its passcode, enter it. "
                     "Your chats appear for you to choose as soon as the backup finishes."))
            d = self.device or {}
            self.log(f"Backing up {d.get('DeviceName') or 'your iPhone'} "
                     f"({'cable' if d.get('ConnectionType') == 'USB' else 'Wi-Fi'})…")     # B8: names the phone
            path = wv.make_backup(Path(self.s["backup_dir"]), self.udid, log=self.log,
                                  progress=lambda p: self._progress_backup(p, t0),
                                  status=lambda text: self.call(lambda: self._backup_status(text)),
                                  keep=self.s["snapshots_keep"], until_disk_full=self.s["snapshots_until_full"],
                                  attention=lambda text: self.call(lambda: self.passcode_notice(text)))
            self.call(lambda: (self._backup_phase("snapshot"), self.steps["snapshot"].set("done", detail="", right=""),
                               self.now_lbl.configure(text="Backup complete")))
            return self._export(path)
        self._run(work, self._exported)

    def export_existing(self, path: Path):
        if not self._reset_progress(EXPORT_STEPS, "Building your archive"):
            return
        self._run(lambda: self._export(path), self._exported)

    def _exported(self, index):
        self.detect(silent=True)          # the phone card: a backup may have been made even if the export stopped
        if not index:
            return
        for k in ("choose", "build"):
            if self.steps[k].state in ("active", "pending"):
                self.steps[k].set("done", detail="", right="")
        self._set_pct(100, "")
        self.last_index = Path(index)
        activity.log(f"Saved the archive to {activity.where(self.s['archive_dir'])}",
                     (self.device or {}).get("DeviceName"), kind="save")
        fm = " + ".join(lbl for f, lbl in (("web", "web pages"), ("pdf", "PDF"), ("excel", "Excel"), ("csv", "CSV")) if self.fmt[f].get())
        notes = ["You chose " + " and ".join(self.notes) + "."] if self.notes else []
        where = self.s["archive_dir"].replace(str(Path.home()), "~", 1)
        self.done_sub.configure(text=f"Saved in {where}  ·  chats as {fm}"
                                + (f"\n{notes[0]}" if notes else ""))
        self._end_progress()     # the window comes back, with the finished card under it
        self.done.pack(fill="x", pady=(14, 0))
        self.go.configure_text("Back up again")
        self.detect(silent=True)

    def open_archive(self):
        index = Path(self.s["archive_dir"]) / "index.html"
        if index.exists():
            webbrowser.open(index.resolve().as_uri())
        else:
            messagebox.showinfo(wv.APP_NAME, "There's no archive yet. Click “Back up now” first.")

    def check_updates(self, settings):
        """Opt-in (S3): one request to the release page, only when this button is clicked."""
        settings.update_line.configure(text="Checking the release page…", fg=MUTED)

        def work():
            return wv.check_for_updates()

        def done(r):
            if not settings.winfo_exists():
                return
            if r["error"]:
                settings.update_line.configure(text=r["error"] + f"  ({r.get('detail', '')[:80]})", fg=RED)
            elif r["newer"]:
                settings.update_line.configure(text=f"Version {r['latest']} is available (you have {r['current']}).", fg=INK)
                if messagebox.askyesno(wv.APP_NAME, f"Version {r['latest']} is available. Open the download page?", parent=settings):
                    webbrowser.open(r["page"])
            else:
                settings.update_line.configure(text=f"You have the latest version ({r['current']}).", fg=GREEN)
        threading.Thread(target=lambda: self.call(lambda r=work(): done(r)), daemon=True).start()

    def open_about(self):
        """About box: name, version and (on a test build) the build label, so you know which build this is."""
        lines = [f"{wv.APP_NAME} {wv.VERSION}"]
        if wv.BUILD_LABEL:
            lines.append(f"Test build {wv.BUILD_LABEL}")
        messagebox.showinfo(f"About {wv.APP_NAME}", "\n".join(lines + about_lines()), parent=self)

    def open_settings(self, focus: str = None):
        SettingsWindow(self, focus)

    # ------------------------------------------------------------------ encryption (S1)
    @staticmethod
    def lock_badge(info) -> str:
        if not info:
            return ""
        return ui.PROTECTED if info.get("encrypted") else "⚠ Not encrypted"

    def _on_ui(self, fn):
        """Run fn on the UI thread and wait for its result (for dialogs opened from a worker)."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        box, ev = {}, threading.Event()

        def go():
            try:
                box["v"] = fn()
            finally:
                ev.set()
        self.call(go)
        ev.wait()
        return box.get("v")

    def _ask_password(self, kind, name, *more):
        """ui.ask_password, bringing the window back first if it was closed while backing up (B9)."""
        self._need_user("PhoneKeep needs you", "Type your backup password to carry on.")
        return ui.ask_password(self, kind, name, *more)

    def password_for(self, path: Path, phone_name: str) -> str | None:
        """The password for an encrypted backup: silently from the keychain, otherwise asked once and offered
        to the keychain. Never logged."""
        pw = wv.password_for_backup(path)
        if pw:
            return pw
        pw = self._on_ui(lambda: self._ask_password("enter", phone_name, wv.RESET_PASSWORD_HELP))
        if pw:
            keychain.set_password(Path(path).name, pw)
        return pw

    def ensure_encryption(self):
        """Before a backup: make sure the iPhone encrypts its backups and that the password is in the keychain.
        Runs on the worker thread; dialogs are shown on the UI thread. Writes to the phone only through
        phone_write, and only after the owner clicked the dialog's "Turn on encryption" button."""
        if not self.udid:
            return
        name = (self.device or {}).get("DeviceName") or "your iPhone"
        on = wv.backup_will_encrypt(self.udid)
        if on is None:
            self.log("Couldn't check whether backups are encrypted; carrying on.")
            return
        if on:
            if not keychain.get_password(self.udid):
                pw = self._on_ui(lambda: self._ask_password("enter", name, wv.RESET_PASSWORD_HELP))
                if pw:
                    keychain.set_password(self.udid, pw)
                    self.log("Backup password saved to the keychain.")
            return
        pw = self._on_ui(lambda: self._ask_password("choose", name))
        if not pw:
            raise wv.PhoneKeepError("Backups are encrypted by default. Choose a backup password to continue.")
        self.log("Turning on backup encryption. Your iPhone may ask for its passcode.")
        phone_write.turn_on_encryption(self.udid, name, pw, confirmed=True, log=self.log)
        keychain.set_password(self.udid, pw)
        self.log("Backup encryption is on; the password is in the keychain.")

    def encryption_off(self, parent):
        if not self.udid:
            messagebox.showinfo(wv.APP_NAME, "Connect your iPhone first.", parent=parent)
            return
        name = (self.device or {}).get("DeviceName") or "your iPhone"
        ok = messagebox.askokcancel(
            f"Turn off encryption for {name}?",
            "Unencrypted backups leave out saved passwords, Health data, Wi-Fi networks and call history, "
            "and anyone who can use this computer can read everything in them.\n\n"
            "Turn encryption off?", icon="warning", parent=parent)
        if not ok:
            return
        pw = keychain.get_password(self.udid) or ui.ask_password(parent, "confirm", name, wv.RESET_PASSWORD_HELP)
        if not pw:
            return
        self.log("Turning off backup encryption. Your iPhone may ask for its passcode.")

        def done(r):
            if r is not None:
                keychain.delete_password(self.udid)
                messagebox.showinfo(wv.APP_NAME, "Backup encryption is off.", parent=parent)
                self.detect(silent=True)
        self._run(lambda: (phone_write.turn_off_encryption(self.udid, name, pw, confirmed=True, log=self.log), True)[1], done)

    def encryption_on(self, parent):
        if not self.udid:
            messagebox.showinfo(wv.APP_NAME, "Connect your iPhone first.", parent=parent)
            return
        name = (self.device or {}).get("DeviceName") or "your iPhone"
        pw = ui.ask_password(parent, "choose", name)
        if not pw:
            return
        self.log("Turning on backup encryption. Your iPhone may ask for its passcode.")

        def done(r):
            if r is not None:
                keychain.set_password(self.udid, pw)
                messagebox.showinfo(wv.APP_NAME, "Backup encryption is on. The password is in your keychain.", parent=parent)
                self.detect(silent=True)
        self._run(lambda: (phone_write.turn_on_encryption(self.udid, name, pw, confirmed=True, log=self.log), True)[1], done)

    def change_password(self, parent):
        if not self.udid:
            messagebox.showinfo(wv.APP_NAME, "Connect your iPhone first.", parent=parent)
            return
        name = (self.device or {}).get("DeviceName") or "your iPhone"
        res = ui.ask_password(parent, "change", name, wv.RESET_PASSWORD_HELP)
        if not res:
            return
        old, new = res
        if not messagebox.askokcancel(f"Change the backup password on {name}?",
                                      f"{name} will use the new password for all its backups from now on. "
                                      "Older backups keep the old password.", parent=parent):
            return
        self.log("Changing the backup password. Your iPhone may ask for its passcode.")

        def done(r):
            if r is not None:
                keychain.set_password(self.udid, new)
                messagebox.showinfo(wv.APP_NAME, "Backup password changed and saved to your keychain.", parent=parent)
        self._run(lambda: (phone_write.change_password(self.udid, name, old, new, confirmed=True, log=self.log), True)[1], done)


class OpenBackupDialog(tk.Toplevel):
    """File → Open backup…: the backups PhoneKeep can see (its own, Finder's, iTunes's), or any folder."""

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self.app = app
        self.title("Open a backup")
        self.geometry("640x460")
        self.transient(app)
        head = ui.header(self)
        head.pack(fill="x")
        tk.Label(head, text="Open a backup", bg=theme.HEADER_BG, fg=theme.HEADER_TITLE, font=font(17, "bold")).pack(side="left", padx=18, pady=12)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)
        tk.Label(body, text="Backups on this computer. You can also drop a backup folder onto the main window.",
                 bg=BG, fg=MUTED, font=font(12), anchor="w", wraplength=600, justify="left").pack(fill="x")
        c = ui.card(body)
        c.pack(fill="both", expand=True, pady=(8, 8))
        self.lb = tk.Listbox(c, font=font(12), activestyle="none", height=10, bg=CARD, fg=INK,
                             selectbackground=theme.ACCENT_PALE, selectforeground=INK)
        self.lb.pack(fill="both", expand=True, padx=6, pady=6)
        self.lb.bind("<Double-Button-1>", lambda e: self._open())
        self.note = tk.Label(body, text="", bg=BG, fg=AMBER, font=font(11), anchor="w", wraplength=600, justify="left")
        self.note.pack(fill="x")
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(8, 0))
        ui.RoundButton(row, "Open", self._open, "primary", 110, 38).pack(side="right")
        ui.RoundButton(row, "Other folder…", self._other, "secondary", 140, 38).pack(side="right", padx=8)
        ui.RoundButton(row, "Cancel", self.destroy, "secondary", 100, 38).pack(side="left")
        self.backups = []
        self.lb.insert("end", "Looking for backups…")
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        msgs = []
        found = wv.find_backups(msgs.append)
        self.app.call(lambda: self._show(found, msgs))

    def _show(self, found, msgs):
        if not self.winfo_exists():
            return
        self.backups = found
        self.lb.delete(0, "end")
        home = Path.home()
        for b in found:
            p = Path(b["path"])
            where = "PhoneKeep" if str(p).startswith(str(Path(self.app.s["backup_dir"]))) or (p.parent / "snapshot.json").exists() or (p / "snapshot.json").exists() \
                else "Finder / iTunes" if "MobileSync" in str(p) else str(p.parent).replace(str(home), "~", 1)
            self.lb.insert("end", f"{b['name']} · {b['date'] or '?'} · iOS {b['ios'] or '?'}{' · 🔒' if b['encrypted'] else ''} · {where}")
        if not found:
            self.lb.insert("end", "No backups found. Use \"Other folder…\" to pick one.")
        if msgs and sys.platform == "darwin":
            self.note.configure(text="Some Finder backups couldn't be read. To include them, give PhoneKeep Full Disk Access in "
                                     "System Settings → Privacy & Security → Full Disk Access, then open this list again.")
        if found:
            self.lb.selection_set(0)

    def _open(self):
        sel = self.lb.curselection()
        if not sel or sel[0] >= len(self.backups):
            return
        path = Path(self.backups[sel[0]]["path"])
        self.destroy()
        self.app.open_backup(path)

    def _other(self):
        d = filedialog.askdirectory(title="Choose a backup folder", parent=self)
        if d:
            self.destroy()
            self.app.open_backup(Path(d))


SETTINGS_GROUPS = ["Backups", "Automatic backups", "Security", "Saving", "Appearance", "Activity", "About"]


def activity_summary(n: Optional[int] = None) -> str:
    """The activity record (S7) of the last 12 months, newest first, one line each, in plain words."""
    lines = [activity.line(d) for d in activity.entries()][:n]
    return "\n".join(lines) if lines else "Nothing recorded yet."


class SettingsWindow(tk.Toplevel):
    def set_appearance(self, value: str) -> None:
        """E6: saved now, used the next time PhoneKeep opens (every window takes its colours as it's built)."""
        self.s["appearance"] = value
        will = ("dark" if theme.system_is_dark() else "light") if value == "system" else value
        self.appearance_note.configure(text="" if will == theme.MODE else f"PhoneKeep will be {will} the next time it opens.")

    def __init__(self, app: App, focus: str = None):
        super().__init__(app, bg=BG)
        app.attach_menu(self)
        self.app, self.s = app, app.s
        self.title("PhoneKeep settings")
        self.geometry("900x760")
        self.minsize(780, 560)
        self.transient(app)
        # L3 (5.2): a list on the left; each item scrolls to its cards on the right
        # (docs/spec/14-layouts.md#l3-settings-layout)
        side = tk.Frame(self, bg=theme.SUBTLE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=theme.BORDER, width=1).pack(side="left", fill="y")
        tk.Label(side, text="Settings", bg=theme.SUBTLE, fg=INK, font=font(20, "bold"), anchor="w").pack(
            fill="x", padx=18, pady=(20, 12))
        self.nav = {}
        for g in SETTINGS_GROUPS:
            item = tk.Label(side, text=g, bg=theme.SUBTLE, fg=INK, font=font(13), anchor="w", padx=12, pady=7,
                            cursor="hand2")
            item.pack(fill="x", padx=8, pady=1)
            item.bind("<Button-1>", lambda e, g=g: self.go_to(g))
            self.nav[g] = item
        self.cards = []                    # (group, card, title) in the order they're built
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)

        def scrolled(lo, hi):
            vbar.set(lo, hi)
            self._mark_current()
        canvas.configure(yscrollcommand=scrolled)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.canvas = canvas
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        ui.wheel_scroll(canvas)            # Settings scrolled only with its scrollbar

        def section(title, sub=None, group="Saving"):
            c = ui.card(body)
            c.pack(fill="x", padx=24, pady=(14, 0))
            self.cards.append((group, c, title))
            tk.Label(c, text=title, bg=CARD, fg=INK, font=font(15, "bold"), anchor="w").pack(fill="x", padx=16, pady=(12, 0))
            if sub:
                tk.Label(c, text=sub, bg=CARD, fg=MUTED, font=font(11), anchor="w", justify="left",
                         wraplength=560).pack(fill="x", padx=16)
            inner = tk.Frame(c, bg=CARD)
            inner.pack(fill="x", padx=16, pady=(8, 14))
            return inner

        # what to include (custom)
        inc = section("What to include (Custom)",
                      "Used when “Custom” is chosen on the main screen.")
        self.picks = {k: tk.BooleanVar(value=k in self.s["custom_sections"]) for k, *_ in sx.SECTIONS}
        grid = tk.Frame(inc, bg=CARD)
        grid.pack(fill="x")
        for i, (k, label, *_r) in enumerate(sx.SECTIONS):
            ui.Chip(grid, label + (" (large)" if k == "files" else ""), self.picks[k], self._save_custom,
                    size=12, bg=CARD).grid(row=i // 3, column=i % 3, sticky="w", padx=3, pady=3)
        self.include_frame = inc

        # options
        op = section("Options")
        self.media = tk.BooleanVar(value=self.s["include_media"])
        self.direct = tk.BooleanVar(value=self.s["direct_photos"])
        ui.Chip(op, "Include photos, videos & voice notes from chats", self.media,
                lambda: self.s.__setitem__("include_media", self.media.get()), size=12, bg=CARD).pack(anchor="w", pady=3)
        ui.Chip(op, "Copy photos straight from the iPhone (works with iCloud Photos)", self.direct,
                lambda: self.s.__setitem__("direct_photos", self.direct.get()), size=12, bg=CARD).pack(anchor="w", pady=3)

        # security (S1)
        info = None
        import snapshots as _snaps
        latest = _snaps.latest_backup_path(Path(self.s["backup_dir"]), app.udid) if app.udid else None
        if latest:
            info = wv.backup_info(latest)
        stored = bool(app.udid and keychain.get_password(app.udid))
        where = "your Keychain" if sys.platform == "darwin" else "Windows Credential Manager"
        status = ("Backups are encrypted. The password is in " + where + "." if info and info["encrypted"] and stored
                  else "Backups are encrypted. The password isn't in " + where + " yet; you'll be asked for it once."
                  if info and info["encrypted"]
                  else "Backups are not encrypted." if info
                  else "Encryption is turned on with your first backup.")
        sec = section("Security", status, "Security")
        tk.Label(sec, text=(ui.PROTECTED if (info and info["encrypted"]) else ""),
                 bg=CARD, fg=GREEN, font=font(12, "bold")).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(sec, bg=CARD)
        row.pack(anchor="w")
        if info and not info["encrypted"]:
            ui.RoundButton(row, "🔒  Turn encryption on…", lambda: app.encryption_on(self), "primary",
                           220, 38, 13, bg=CARD).pack(side="left")
        else:
            ui.RoundButton(row, "Change password…", lambda: app.change_password(self), "secondary",
                           180, 38, 13, bg=CARD).pack(side="left")
            ui.RoundButton(row, "Turn encryption off…", lambda: app.encryption_off(self), "secondary",
                           200, 38, 13, bg=CARD).pack(side="left", padx=8)

        # app lock (S2)
        kind = app.lock_kind()
        lk = tk.Frame(sec, bg=CARD)
        lk.pack(fill="x", pady=(14, 0))
        if kind is None:
            tk.Label(lk, text="Lock PhoneKeep: not available on this computer (it needs Touch ID, a Mac password "
                              "or Windows Hello).", bg=CARD, fg=MUTED, font=font(12), wraplength=560,
                     justify="left", anchor="w").pack(fill="x")
        else:
            self.lock_var = tk.BooleanVar(value=app.lock_on())

            def set_lock():
                on = self.lock_var.get()
                if on or app.is_unlocked():
                    app.s["app_lock"] = on
                    app.log("App lock " + ("on." if on else "off."))
                    return
                # turning it off asks first, so someone at an unlocked computer can't just switch it off
                self.lock_var.set(True)
                app.require_unlock(lambda: (app.s.__setitem__("app_lock", False), self.lock_var.set(False),
                                            app.log("App lock off.")), "turn off the PhoneKeep lock")
            self.set_lock = set_lock
            ttk.Checkbutton(lk, text=f"Lock PhoneKeep with {applock.describe(kind)}", variable=self.lock_var,
                            command=set_lock).pack(anchor="w")
            tk.Label(lk, text="Opening your iPhone's data asks first. Automatic backups still run while it's locked.",
                     bg=CARD, fg=MUTED, font=font(11), anchor="w", justify="left", wraplength=560).pack(fill="x", padx=(22, 0))
            irow = tk.Frame(lk, bg=CARD)
            irow.pack(anchor="w", padx=(22, 0), pady=(6, 0))
            tk.Label(irow, text="Lock again after", bg=CARD, fg=INK, font=font(12)).pack(side="left")
            self.idle_var = tk.StringVar(value=str(app.s["lock_idle_minutes"]))
            cb = ttk.Combobox(irow, textvariable=self.idle_var, values=["5", "10", "15", "30", "60"],
                              state="readonly", width=4)
            cb.pack(side="left", padx=6)
            cb.bind("<<ComboboxSelected>>", lambda e: app.s.__setitem__("lock_idle_minutes", int(self.idle_var.get())))
            tk.Label(irow, text="minutes without using PhoneKeep", bg=CARD, fg=INK, font=font(12)).pack(side="left")

        # no network (S3)
        import netguard
        net = section("Internet",
                      "PhoneKeep never sends your data anywhere. It makes no internet connections"
                      + (" (refused by the app itself)" if netguard.installed() else "")
                      + ". The only exception is the button below, which fetches the release page once when you click it, "
                        "with no information about you or your iPhone.", "Security")
        nrow = tk.Frame(net, bg=CARD)
        nrow.pack(anchor="w")
        tk.Label(nrow, text="Internet use: Off", bg=CARD, fg=GREEN, font=font(12, "bold")).pack(side="left", padx=(0, 14))
        self.update_line = tk.Label(net, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w", wraplength=560, justify="left")
        ui.RoundButton(nrow, "Check for updates…", lambda: app.check_updates(self), "secondary", 190, 38, 13, bg=CARD).pack(side="left")
        self.update_line.pack(fill="x", pady=(6, 0))

        # automatic backups (B2)
        import scheduler as sch
        ab = section("Automatic backups",
                     "PhoneKeep backs up by itself from the menu bar helper when your iPhone is nearby "
                     "(same Wi-Fi or cable) at or after the chosen time, and tries again every 30 minutes until midnight.",
                     "Automatic backups")
        self.mode_var = tk.StringVar(value=self.s["auto_backup"])
        mrow = tk.Frame(ab, bg=CARD)
        mrow.pack(anchor="w", pady=(0, 6))
        for val, label in (("daily", "Daily"), ("weekly", "Weekly"), ("off", "Off")):
            ttk.Radiobutton(mrow, text=label, value=val, variable=self.mode_var,
                            command=lambda: app.set_schedule(self.mode_var.get(), self.hour_var.get(), self.day_var.get())
                            ).pack(side="left", padx=(0, 14))
        trow = tk.Frame(ab, bg=CARD)
        trow.pack(anchor="w", pady=3)
        tk.Label(trow, text="At around", bg=CARD, fg=INK, font=font(12)).pack(side="left", padx=(0, 8))
        hours = [f"{(h % 12) or 12} {'am' if h < 12 else 'pm'}" for h in range(24)]
        self.hour_var = tk.StringVar(value=hours[int(self.s["auto_backup_hour"]) % 24])
        hb = ttk.Combobox(trow, textvariable=self.hour_var, values=hours, width=7, state="readonly")
        hb.pack(side="left")
        hb.bind("<<ComboboxSelected>>", lambda e: app.set_schedule(self.mode_var.get(), self.hour_var.get(), self.day_var.get()))
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        self.day_var = tk.StringVar(value=days[int(self.s["auto_backup_weekday"]) % 7])
        tk.Label(trow, text="   on", bg=CARD, fg=INK, font=font(12)).pack(side="left", padx=(8, 8))
        db = ttk.Combobox(trow, textvariable=self.day_var, values=days, width=10, state="readonly")
        db.pack(side="left")
        db.bind("<<ComboboxSelected>>", lambda e: app.set_schedule(self.mode_var.get(), self.hour_var.get(), self.day_var.get()))
        tk.Label(trow, text="(weekly)", bg=CARD, fg=MUTED, font=font(11)).pack(side="left", padx=(6, 0))
        self.charging_var = tk.BooleanVar(value=bool(self.s["auto_backup_charging"]))
        ui.Chip(ab, "Only when charging", self.charging_var,
                lambda: self.s.__setitem__("auto_backup_charging", self.charging_var.get()), size=12, bg=CARD).pack(anchor="w", pady=3)
        # B8: which phones are backed up automatically
        phones = {}
        for udid in known_backed_up_phones(Path(self.s["backup_dir"])):
            import snapshots as _snaps
            info = wv.backup_info(_snaps.latest_backup_path(Path(self.s["backup_dir"]), udid))
            phones[udid] = info.get("name") or "iPhone"
        for d in getattr(app, "devices", []):
            phones.setdefault(d.get("UniqueDeviceID") or d.get("Identifier"), d.get("DeviceName") or "iPhone")
        self.phone_vars = {}
        if phones:
            tk.Label(ab, text="Back up automatically:", bg=CARD, fg=INK, font=font(12), anchor="w").pack(fill="x", pady=(8, 2))
            for udid, name in phones.items():
                v = tk.BooleanVar(value=udid in (self.s.data.get("auto_backup_phones") or []))
                self.phone_vars[udid] = v

                def toggle(u=udid, var=v):
                    cur = [x for x in (self.s.data.get("auto_backup_phones") or []) if x != u]
                    self.s["auto_backup_phones"] = cur + ([u] if var.get() else [])
                ttk.Checkbutton(ab, text=name + ("" if sn_has(Path(self.s["backup_dir"]), udid) else "  (after its first backup)"),
                                variable=v, command=toggle).pack(anchor="w", padx=(12, 0))
        self.sched_line = tk.Label(ab, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.sched_line.pack(fill="x", pady=(4, 0))
        self.sched_line.configure(text=sch.Plan.from_settings(self.s.data).next_run_text(dt.datetime.now(), None).capitalize())

        # snapshots (B3)
        sp = section("Snapshots",
                     "Every backup is kept as a snapshot you can open from the phone window's timeline. "
                     "Unchanged files are stored once, so ten snapshots don't take ten times the space.", "Backups")
        srow = tk.Frame(sp, bg=CARD)
        srow.pack(anchor="w", pady=3)
        self.keep_mode = tk.StringVar(value="full" if self.s["snapshots_until_full"] else "keep")
        ttk.Radiobutton(srow, text="Keep the last", value="keep", variable=self.keep_mode,
                        command=lambda: self.s.__setitem__("snapshots_until_full", False)).pack(side="left")
        self.keep_var = tk.IntVar(value=int(self.s["snapshots_keep"]))
        sb = ttk.Spinbox(srow, from_=3, to=100, textvariable=self.keep_var, width=5,
                         command=lambda: self.s.__setitem__("snapshots_keep", max(3, min(100, self.keep_var.get()))))
        sb.pack(side="left", padx=6)
        sb.bind("<FocusOut>", lambda e: self.s.__setitem__("snapshots_keep", max(3, min(100, self.keep_var.get() or 10))))
        tk.Label(srow, text="snapshots (3 to 100)", bg=CARD, fg=INK, font=font(12)).pack(side="left")
        ttk.Radiobutton(sp, text="Keep everything until the disk is 90% full", value="full", variable=self.keep_mode,
                        command=lambda: self.s.__setitem__("snapshots_until_full", True)).pack(anchor="w", pady=3)
        tk.Label(sp, text="Snapshots marked \"Keep forever\" are never removed automatically; the oldest unlocked one goes first.",
                 bg=CARD, fg=MUTED, font=font(11), anchor="w", wraplength=560, justify="left").pack(fill="x", pady=(4, 0))

        # the helper (E2)
        import login_item
        hp = section("Menu bar helper" if sys.platform == "darwin" else "System tray helper",
                     "A small PhoneKeep icon that shows your last backup, backs up with one click and keeps "
                     "running when this window is closed.", "Automatic backups")
        self.login_var = tk.BooleanVar(value=bool(self.s["start_at_login"]))
        ui.Chip(hp, "Start at login", self.login_var, lambda: app.set_start_at_login(self.login_var.get()),
                size=12, bg=CARD).pack(anchor="w", pady=3)

        # location (B4)
        import location as loc
        lo = section("Where backups are kept",
                     "Any disk, external drive or network drive will do (not FAT32).", "Backups")
        self.loc_line = tk.Label(lo, text="", bg=CARD, fg=INK, font=font(12), anchor="w", justify="left", wraplength=560)
        self.loc_line.pack(fill="x")
        self.loc_space = tk.Label(lo, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.loc_space.pack(fill="x", pady=(2, 6))
        lrow = tk.Frame(lo, bg=CARD)
        lrow.pack(anchor="w")
        ui.RoundButton(lrow, "Change…", lambda: app.change_location(self), "secondary", 110, 34, 12, bg=CARD).pack(side="left")
        ui.RoundButton(lrow, "Show in Finder" if sys.platform == "darwin" else "Show folder",
                       lambda: (Path(self.s["backup_dir"]).mkdir(parents=True, exist_ok=True), reveal(Path(self.s["backup_dir"]))),
                       "secondary", 130, 34, 12, bg=CARD).pack(side="left", padx=8)
        tk.Label(lo, text="🔒 Encrypted · stays on this computer" + ("" if loc.drive_name(Path(self.s["backup_dir"])) == "this disk"
                                                                       else f" (on {loc.drive_name(Path(self.s['backup_dir']))})"),
                 bg=CARD, fg=GREEN, font=font(12, "bold"), anchor="w").pack(fill="x", pady=(8, 0))
        self.refresh_location()

        # folders
        fo = section("Folders")
        for key, label in (("archive_dir", "Archive"),):
            row = tk.Frame(fo, bg=CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=CARD, fg=INK, font=font(12), width=8, anchor="w").pack(side="left")
            var = tk.StringVar(value=self.s[key])
            ent = ttk.Entry(row, textvariable=var)
            ent.pack(side="left", fill="x", expand=True, padx=6)
            var.trace_add("write", lambda *_, k=key, v=var: self.s.__setitem__(k, v.get()))
            ui.RoundButton(row, "Browse", lambda v=var: self._browse(v), "secondary", 90, 30, 12, bg=CARD).pack(side="left")

        # existing backups
        ex = section("Use an existing backup",
                     "Build the archive from a backup that's already on this computer, without connecting the iPhone.",
                     "Backups")
        self.combo = ttk.Combobox(ex, state="readonly")
        self.combo.pack(fill="x")
        row = tk.Frame(ex, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        ui.RoundButton(row, "Build archive from this backup", self._build_existing, "primary", 280, 38, 13,
                       bg=CARD).pack(side="left")
        ui.RoundButton(row, "Other folder…", self._other_folder, "secondary", 140, 38, 13, bg=CARD).pack(side="left", padx=8)
        self.backups: list[dict] = []
        self._refresh_backups()

        # activity (S7): the record PhoneKeep keeps on this computer of what it changed; read here, never sent
        ac = section("Activity", "What PhoneKeep did, on this computer only: each backup, each save, each change it "
                                 "made to your iPhone and settings like where backups are kept. Never your messages or "
                                 "passwords. Kept 12 months.", "Activity")
        box = tk.Frame(ac, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill="x")
        text = activity_summary()
        self.activity_lines = tk.Text(box, height=min(10, max(2, text.count("\n") + 1)), wrap="word", bg=CARD,
                                      fg=INK, font=font(12), relief="flat", bd=0, highlightthickness=0, padx=8, pady=6)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.activity_lines.yview)
        self.activity_lines.configure(yscrollcommand=sb.set)
        self.activity_lines.insert("1.0", text)
        self.activity_lines.configure(state="disabled")
        sb.pack(side="right", fill="y")
        self.activity_lines.pack(side="left", fill="x", expand=True)
        row = tk.Frame(ac, bg=CARD)
        row.pack(anchor="w", pady=(8, 0))
        ui.RoundButton(row, "Save as CSV…", self.save_activity, "secondary", 140, 34, 12, bg=CARD).pack(side="left")
        ui.RoundButton(row, "Show in Finder" if sys.platform == "darwin" else "Show folder",
                       lambda: reveal(activity.ACTIVITY_FILE if activity.ACTIVITY_FILE.exists()
                                      else activity.ACTIVITY_FILE.parent),
                       "secondary", 140, 34, 12, bg=CARD).pack(side="left", padx=(8, 0))

        # appearance (E6): read once as PhoneKeep starts (theme.py), so a change shows the next time it opens
        ap = section("Appearance", "Light or dark. With “Same as this computer”, PhoneKeep follows the computer's own "
                     "setting each time it opens.", "Appearance")
        self.appearance_var = tk.StringVar(value=self.s["appearance"])
        arow = tk.Frame(ap, bg=CARD)
        arow.pack(anchor="w", pady=(0, 6))
        self.appearance_note = tk.Label(ap, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w", justify="left",
                                        wraplength=560)
        for val, label in (("system", "Same as this computer"), ("light", "Light"), ("dark", "Dark")):
            ttk.Radiobutton(arow, text=label, value=val, variable=self.appearance_var,
                            command=lambda: self.set_appearance(self.appearance_var.get())).pack(side="left", padx=(0, 14))
        self.appearance_note.pack(fill="x")

        # about
        abt = section("About", f"{wv.APP_NAME} {wv.VERSION}" + (f" · test build {wv.BUILD_LABEL}" if wv.BUILD_LABEL else ""),
                      "About")
        ui.RoundButton(abt, f"About {wv.APP_NAME}…", app.open_about, "secondary", 170, 34, 12, bg=CARD).pack(anchor="w")

        # the cards in the list's order (each card's content is built above, as before)
        for _g, c, _t in self.cards:
            c.pack_forget()
        first = ("Where backups are kept", "Snapshots")          # as in the mockup; the rest keep their order
        self.cards.sort(key=lambda x: (SETTINGS_GROUPS.index(x[0]), first.index(x[2]) if x[2] in first else len(first)))
        for _g, c, _t in self.cards:
            c.pack(fill="x", padx=24, pady=(14, 0))
        bottom = tk.Frame(body, bg=BG)
        bottom.pack(fill="x", padx=24, pady=16)
        ui.RoundButton(bottom, "Done", self.destroy, "primary", 120, 40).pack(side="right")
        self._current = None
        self._mark_current()
        if focus == "include":
            self.after(100, lambda: self.go_to("Saving"))

    def save_activity(self, path: Optional[Path] = None) -> Optional[Path]:
        """S7: the record as CSV, where the owner chooses. path: given by the tests instead of the dialog."""
        if path is None:
            p = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="PhoneKeep activity.csv",
                                             filetypes=[("CSV", "*.csv")])
            if not p:
                return None
            path = Path(p)
        try:
            return activity.save_csv(path)
        except OSError as e:
            messagebox.showerror(wv.APP_NAME, f"Couldn't save the activity record: {e}", parent=self)
            return None

    def go_to(self, group: str):
        """Scroll so the group's first card is at the top (as far as the page goes)."""
        self.update_idletasks()
        first = next(c for g, c, _t in self.cards if g == group)
        total = max(1, first.master.winfo_height())
        self.canvas.yview_moveto(max(0, first.winfo_y() - 14) / total)
        # the clicked item stays lit while the page stays put (near the end it can't scroll its cards to the top)
        self._clicked = (group, self.canvas.yview()[0])
        self._mark_current(group)

    def _mark_current(self, group: str = None):
        """Highlight the list item of the cards in view (or the one just clicked)."""
        if not getattr(self, "cards", None) or not hasattr(self, "nav"):
            return
        clicked = getattr(self, "_clicked", None)
        try:
            now = self.canvas.yview()[0]
        except tk.TclError:                 # the window is going away
            return
        if group is None and clicked and abs(now - clicked[1]) < 0.001:
            group = clicked[0]
        if group is None:
            self._clicked = None
            try:
                top = self.canvas.canvasy(0) + 30
                lo, hi = self.canvas.yview()
            except tk.TclError:
                return
            group = SETTINGS_GROUPS[0]
            for g, c, _t in self.cards:
                if c.winfo_y() <= top:
                    group = g
            if hi >= 0.999 and lo > 0:            # at the bottom: the last group's cards are the ones in view
                group = self.cards[-1][0]
        if group == getattr(self, "_current", None):
            return
        self._current = group
        for g, item in self.nav.items():
            on = g == group
            item.configure(bg=theme.ACCENT_PALE if on else theme.SUBTLE, fg=theme.ACCENT if on else INK,
                           font=font(13, "bold" if on else "normal"))

    def _save_custom(self):
        self.s["custom_sections"] = [k for k, v in self.picks.items() if v.get()]

    def _browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()), parent=self)
        if d:
            var.set(d)

    def refresh_location(self):
        import location as loc
        p = Path(self.s["backup_dir"])
        self.loc_line.configure(text=str(p).replace(str(Path.home()), "~", 1))
        if not loc.is_available(p):
            self.loc_space.configure(text=loc.connect_message(p), fg=AMBER)
            return

        def work():
            return loc.usage(p)

        def show(u):
            if self.winfo_exists():
                self.loc_space.configure(text=f"Backups use {loc.human(u['used'])} · {loc.human(u['free'])} free on {u['drive']}", fg=MUTED)
        threading.Thread(target=lambda: self.app.call(lambda u=work(): show(u)), daemon=True).start()

    def _refresh_backups(self):
        msgs = []
        self.backups = wv.find_backups(msgs.append)
        labels = [f"{b['name']} – {b['date']}{'  🔒' if b['encrypted'] else ''}" for b in self.backups]
        self.combo["values"] = labels
        if labels:
            self.combo.current(0)
        else:
            self.combo.set("No backups found yet")

    def _other_folder(self):
        d = filedialog.askdirectory(title="Choose an iPhone backup folder (it contains Manifest.db)", parent=self)
        if not d:
            return
        if not (Path(d) / "Manifest.db").exists():
            messagebox.showerror(wv.APP_NAME, "That folder isn't an iPhone backup (no Manifest.db).", parent=self)
            return
        info = wv.backup_info(Path(d))
        self.backups.insert(0, info)
        self.combo["values"] = [f"{info['name']} – {info['date']}"] + list(self.combo["values"])
        self.combo.current(0)

    def _build_existing(self):
        i = self.combo.current()
        if i < 0 or i >= len(self.backups):
            messagebox.showinfo(wv.APP_NAME, "No backup selected.", parent=self)
            return
        path = Path(self.backups[i]["path"])
        self.destroy()
        self.app.export_existing(path)


if __name__ == "__main__":
    App().mainloop()
