#!/usr/bin/env python3
"""PhoneKeep desktop window. Run: python app.py"""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import errors
import keychain
import phone_write
import phonekeep as wv
import sections as sx
import ui
from ui import AMBER, BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, font

SETTINGS_FILE = wv.DEFAULT_HOME / "settings.json"

PRESETS = {
    "chats": ("💬", "Chats", "WhatsApp (both apps)\nand Messages",
              ["whatsapp", "whatsappbusiness", "messages", "contacts"]),
    "chats_photos": ("📷", "Chats & photos", "Chats plus your\nphotos and videos",
                     ["whatsapp", "whatsappbusiness", "messages", "contacts", "photos"]),
    "everything": ("📱", "Everything", "Chats, photos, contacts,\ncalls, notes and more",
                   list(sx.DEFAULT_SECTIONS)),
    "custom": ("⚙", "Custom", "Pick exactly what\nto include", None),
}
STEPS = [("backup", "Back up iPhone"), ("choose", "Choose chats & photos"), ("build", "Build your archive")]


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return "under 2 min left"
    m = int(seconds // 60)
    return f"about {m} min left" if m < 90 else f"about {m // 60} h {m % 60:02d} min left"


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
        "start_at_login": False,     # E2: the helper starts at login (asked once in E1 step 5)
        "auto_backup_paused": False, # E2: Pause automatic backups
        "auto_backup_hour": 21,      # B2: "around 9 pm"
        "auto_backup_weekday": 6,    # B2: weekly on Sunday
        "auto_backup_charging": False,  # B2: only when charging
        "snapshots_keep": 10,        # B3: keep the last N snapshots (3-100)
        "snapshots_until_full": False,  # B3: or keep everything until the disk is 90% full
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
    def __init__(self, parent, bg):
        super().__init__(parent, width=64, height=104, bg=bg, highlightthickness=0)
        self.state = None
        self.set_state("searching")

    def set_state(self, state: str):
        if state == self.state:
            return
        self.state = state
        self.delete("all")
        body = {"ok": GREEN, "searching": "#9aa5ab", "none": "#c3cbcf"}[state]
        self._rr(6, 4, 58, 100, 12, body)
        self._rr(11, 12, 53, 88, 6, "#ffffff" if state != "ok" else "#e7f6f2")
        self.create_rectangle(26, 7, 38, 9, fill="#ffffff", outline="")
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
        self.detail.pack(fill="x")
        self.number, self.state, self.spin = number, "pending", 0
        self.set("pending")

    def set(self, state: str, detail: str = None, right: str = None):
        self.state = state
        if detail is not None:
            self.detail.configure(text=detail)
        if right is not None:
            self.right.configure(text=right)
        self.title.configure(fg=INK if state != "pending" else MUTED)
        self.draw()

    def draw(self):
        d = self.dot
        d.delete("all")
        if self.state == "done":
            d.create_oval(3, 3, 27, 27, fill=GREEN, outline=GREEN)
            d.create_text(15, 15, text="✓", fill="white", font=font(13, "bold"))
        elif self.state == "error":
            d.create_oval(3, 3, 27, 27, fill=RED, outline=RED)
            d.create_text(15, 15, text="!", fill="white", font=font(13, "bold"))
        elif self.state == "skipped":
            d.create_oval(3, 3, 27, 27, fill="#ffffff", outline=LINE, width=2)
            d.create_text(15, 15, text="–", fill=MUTED, font=font(13, "bold"))
        elif self.state == "active":
            d.create_oval(3, 3, 27, 27, outline="#d6efe8", width=3)
            d.create_arc(3, 3, 27, 27, start=self.spin, extent=110, style="arc", outline=GREEN, width=3)
        else:
            d.create_oval(3, 3, 27, 27, fill="#ffffff", outline=LINE, width=2)
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
        self.create_rectangle(0, 0, w, 8, fill="#e9edef", outline="")
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
        self.title(wv.APP_NAME)
        self._build_menu()
        self.geometry("820x860")
        self.minsize(720, 700)
        self.configure(bg=BG)
        ui.setup_styles(self)
        self.s = Settings()
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.device = None
        self.udid = None
        self.backups: list[dict] = []
        self.preset = tk.StringVar(value=self.s["preset"])
        self.fmt = {f: tk.BooleanVar(value=f in self.s["formats"]) for f in ("web", "excel", "csv")}
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
        self.after(1500, self.start_helper)

    # ------------------------------------------------------------------ layout
    def _build(self):
        head = tk.Frame(self, bg=GREEN)
        head.pack(fill="x")
        tk.Label(head, text="PhoneKeep", bg=GREEN, fg="white", font=font(21, "bold")).pack(side="left", padx=(22, 10), pady=14)
        tk.Label(head, text="Back up your iPhone to this computer", bg=GREEN, fg="#d7efe9",
                 font=font(13)).pack(side="left", pady=14)
        ui.RoundButton(head, "⚙  Settings", self.open_settings, "ghost", 130, 34, 13).pack(side="right", padx=16)
        ver = tk.Label(head, text=f"v{wv.full_version()}", bg=GREEN, fg="#d7efe9", font=font(11), cursor="hand2")
        ver.pack(side="right", padx=(0, 4))
        ver.bind("<Button-1>", lambda e: self.open_about())

        # problem banner (E3): one sentence, one button, Show details. Packed only when needed.
        self.bar_frame = tk.Frame(self, bg="#fdecea")
        self.bar_text = tk.Label(self.bar_frame, text="", bg="#fdecea", fg=INK, font=font(13), anchor="w",
                                 justify="left", wraplength=560)
        self.bar_text.pack(side="left", padx=16, pady=10, fill="x", expand=True)
        self.bar_btn = None
        self.bar_details = tk.Label(self.bar_frame, text="Show details", bg="#fdecea", fg=MUTED, font=font(11), cursor="hand2")
        self.bar_details_text = ""
        self.bar_details.bind("<Button-1>", lambda e: messagebox.showinfo("Details for support", self.bar_details_text, parent=self))

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=22, pady=16)

        # device card
        dc = ui.card(self.body)
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
        for w in (self.phone, self.dev_name):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e: self.open_phone())

        # what to keep
        wc = ui.card(self.body)
        wc.pack(fill="x", pady=14)
        tk.Label(wc, text="What do you want to keep?", bg=CARD, fg=INK, font=font(16, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(14, 8))
        tiles = tk.Frame(wc, bg=CARD)
        tiles.pack(fill="x", padx=14)
        self.tiles = {}
        for i, (key, (icon, title, sub, _secs)) in enumerate(PRESETS.items()):
            t = tk.Frame(tiles, bg=CARD, highlightthickness=2, highlightbackground=LINE, cursor="hand2")
            t.grid(row=0, column=i, sticky="nsew", padx=4)
            tiles.columnconfigure(i, weight=1, uniform="t")
            widgets = [t]
            for txt, fnt, fg in ((icon, font(22), INK), (title, font(14, "bold"), INK), (sub, font(11), MUTED)):
                lab = tk.Label(t, text=txt, bg=CARD, fg=fg, font=fnt, justify="center")
                lab.pack(pady=(8 if txt == icon else 0, 8 if txt == sub else 0))
                widgets.append(lab)
            for w in widgets:
                w.bind("<Button-1>", lambda e, k=key: self._choose_preset(k))
            self.tiles[key] = widgets
        opts = tk.Frame(wc, bg=CARD)
        opts.pack(fill="x", padx=18, pady=(12, 4))
        tk.Label(opts, text="Save chats as", bg=CARD, fg=MUTED, font=font(12)).pack(side="left", padx=(0, 8))
        for f, label in (("web", "Web pages"), ("excel", "Excel"), ("csv", "CSV")):
            ui.Chip(opts, label, self.fmt[f], bg=CARD).pack(side="left", padx=3)
        opts2 = tk.Frame(wc, bg=CARD)
        opts2.pack(fill="x", padx=18, pady=(6, 16))
        tk.Label(opts2, text="Let me choose", bg=CARD, fg=MUTED, font=font(12)).pack(side="left", padx=(0, 8))
        ui.Chip(opts2, "which chats", self.pick_chats, bg=CARD).pack(side="left", padx=3)
        ui.Chip(opts2, "which photos", self.pick_photos, bg=CARD).pack(side="left", padx=3)
        self._choose_preset(self.preset.get(), save=False)

        # main button
        self.go = ui.RoundButton(self.body, "Back up now", self.backup_and_export, "primary", 400, 54, 17)
        self.go.pack(fill="x")

        # progress
        self.prog = ui.card(self.body)
        pin = tk.Frame(self.prog, bg=CARD)
        pin.pack(fill="x", padx=18, pady=14)
        self.steps = {}
        for n, (key, title) in enumerate(STEPS, 1):
            r = StepRow(pin, n, title)
            r.pack(fill="x", pady=4)
            self.steps[key] = r
        self.bar = Bar(pin)
        self.bar.pack(fill="x", pady=(10, 4))
        row = tk.Frame(pin, bg=CARD)
        row.pack(fill="x")
        self.details_btn = tk.Label(row, text="Show details ▸", bg=CARD, fg=GREEN, font=font(12), cursor="hand2")
        self.details_btn.pack(side="left")
        self.details_btn.bind("<Button-1>", lambda e: self._toggle_details())
        self.log_frame = tk.Frame(pin, bg=CARD)
        self.log_box = tk.Text(self.log_frame, height=9, wrap="word", state="disabled", relief="flat",
                               bg="#f7f8f9", fg=INK, font=("Menlo" if sys.platform == "darwin" else "Consolas", 10),
                               highlightthickness=1, highlightbackground=LINE)
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))

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
        for k, widgets in self.tiles.items():
            on = k == key
            widgets[0].configure(highlightbackground=GREEN if on else LINE,
                                 bg=GREEN_SOFT if on else CARD)
            for w in widgets[1:]:
                w.configure(bg=GREEN_SOFT if on else CARD)
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
        for r in self.steps.values():
            if r.state == "active":
                r.set("active", detail=msg[:140])
                return

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

        def worker():
            result, err = None, None
            try:
                result = fn()
            except Exception as e:
                err = e
            self.call(lambda: self._finish(result, err, done, quiet, fn))
        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, result, err, done, quiet, fn=None):
        self.busy = False
        self.go.set_enabled(True)
        self.go.configure_text("Back up again" if not err and self.last_index else "Back up now")
        if err is not None:
            pr = self.problem_of(err)
            for r in self.steps.values():
                if r.state == "active":
                    r.set("error", detail=pr.message)
            self.log("ERROR: " + pr.message + (f"  [{pr.details}]" if pr.details else ""))
            if not quiet:
                self.show_problem(pr, retry=(lambda: self._run(fn, done)) if fn else None)
        else:
            self.hide_problem()
        if done:
            done(None if err is not None else result)

    # ------------------------------------------------------------------ problems (E3)
    @staticmethod
    def problem_of(err) -> errors.Problem:
        """Every error shown in this window comes through the one table in errors.py."""
        if isinstance(err, wv.PhoneKeepError) and err.button:
            return errors.Problem(err.key, str(err), err.button, err.action, err.details,
                                  failure=err.key not in ("drive_unavailable",))
        if isinstance(err, wv.PhoneKeepError):
            return errors.Problem("plain", str(err), "Try again", errors.TRY_AGAIN, err.details, failure=True)
        return errors.explain(err)

    def show_problem(self, pr: errors.Problem, retry=None):
        """Inline banner at the top: one sentence + one button; red only for real failures."""
        colour = "#fdecea" if pr.failure else "#fff4e0"
        self.bar_frame.configure(bg=colour)
        self.bar_text.configure(text=pr.message, bg=colour)
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
            cmd = lambda: messagebox.showinfo("Details for support", pr.details or pr.message, parent=self)
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
            self.bar_frame.pack(fill="x", before=self.body)

    def hide_problem(self):
        self.bar_frame.pack_forget()

    # ------------------------------------------------------------------ device
    def _auto_detect(self):
        if not self.busy:
            self.detect(silent=True)
        # the first-run guide waits for the phone, so look more often while it is up
        self._timers["detect"] = self.after(3000 if self.guide is not None else 15000, self._auto_detect)

    # ------------------------------------------------------------------ the menu and Open backup (B5)
    def _build_menu(self):
        bar = tk.Menu(self)
        filem = tk.Menu(bar, tearoff=0)
        filem.add_command(label="Open backup…", command=self.open_backup_dialog, accelerator="Cmd+O" if sys.platform == "darwin" else "Ctrl+O")
        filem.add_command(label="Open iPhone", command=self.open_phone)
        filem.add_separator()
        filem.add_command(label="Settings…", command=self.open_settings)
        if sys.platform != "darwin":
            filem.add_separator()
            filem.add_command(label="Quit", command=self.destroy)
        bar.add_cascade(label="File", menu=filem)
        helpm = tk.Menu(bar, tearoff=0)
        helpm.add_command(label=f"About {wv.APP_NAME}", command=self.open_about)
        bar.add_cascade(label="Help", menu=helpm)
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

    def open_backup(self, path: Path) -> bool:
        """Open any backup folder in a phone window (PhoneKeep snapshot, phone folder, Finder or iTunes backup)."""
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
        import phone
        win = phone.PhoneWindow(self, {}, None, backup=path)
        self.phone_windows = getattr(self, "phone_windows", []) + [win]
        phone_write.log_activity(f"Opened the backup {path}", kind="backup")
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

    def end_first_run(self):
        if self.guide is None:
            return
        self.guide.destroy()
        self.guide = None
        for w in self.main_cards:
            if w is self.prog or w is self.done:
                continue
            w.pack(fill="x", pady=(0, 0) if w is self.main_cards[0] else (14, 0))
        self.detect(silent=True)

    FEATURES = {"scheduler": True, "app_lock": False}   # flipped on by the PR that ships each feature

    def has_feature(self, name: str) -> bool:
        return bool(self.FEATURES.get(name))

    def has_touch_id(self) -> bool:
        """Best effort: Macs with Touch ID report a biometric sensor; used only to word a question."""
        if sys.platform != "darwin":
            return False
        try:
            out = subprocess.run(["bioutil", "-r"], capture_output=True, text=True, timeout=5).stdout
            return "Touch ID" in out or "fingerprint" in out.lower()
        except Exception:
            return False

    def detect(self, silent: bool = False):
        if self.busy or getattr(self, "detecting", False):
            return

        def work():
            return wv.list_devices()

        def done(devs, err=None):
            self.detecting = False
            self.detect_error = err
            if devs:
                d = devs[0]
                self.device = d
                self.udid = d.get("UniqueDeviceID") or d.get("Identifier")
                how = "USB cable" if d.get("ConnectionType") == "USB" else "Wi-Fi"
                self.phone.set_state("ok")
                self.dev_name.configure(text=d.get("DeviceName") or "iPhone")
                self.dev_line.configure(text=f"iOS {d.get('ProductVersion', '?')} · connected by {how}"
                                        + ("  (a cable is faster for the first backup)" if how == "Wi-Fi" else ""),
                                        fg=MUTED)
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
                self.dev_lock.configure(text=self.lock_badge(info))
                self.open_btn.set_enabled(True)
            else:
                self.device = self.udid = None
                self.phone.set_state("none")
                self.dev_name.configure(text="No iPhone found")
                self.dev_line.configure(text=err or "Plug in your iPhone (or use Wi-Fi sync), unlock it and tap “Trust”.",
                                        fg=RED if err else MUTED)
                self.dev_last.configure(text="")
                self.dev_lock.configure(text="")
                self.open_btn.set_enabled(False)
        if not silent:
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
        box, ev = {}, threading.Event()

        def show():
            self.steps["choose"].set("active", detail="Waiting for you: choose the chats to export…")
            p = ui.ChatPicker(self, lists, preview)
            self.wait_window(p)
            box["v"] = p.result
            ev.set()
        self.call(show)
        ev.wait()
        if box.get("v") is not None:
            n = sum(len(v) for k, v in box["v"].items() if k != "_dates")
            self.log(f"You selected {n} chat{'s' if n != 1 else ''}.")
            dates = box["v"].get("_dates")
            when = f" ({wv.describe_dates(dates)})" if dates else ""
            self.notes.append(f"{n} chat{'s' if n != 1 else ''}{when}")
        return box.get("v")

    def _choose_photos(self, source, items):
        box, ev = {}, threading.Event()

        def show():
            self.steps["choose"].set("active", detail="Waiting for you: choose the photos to keep…")
            p = ui.PhotoPicker(self, source, items)
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
        self._reset_progress(False)
        self.steps["backup"].set("active", detail=f"Moving backups to {new}…")
        self._run(work, done)

    def _progress_backup_simple(self, pct):
        self.call(lambda: (self.bar.set(pct), self.steps["backup"].set("active", right=f"{pct:.0f}%")))

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
        import phone
        self.phone_win = phone.PhoneWindow(self, self.device, self.udid)

    # ------------------------------------------------------------------ actions
    def _reset_progress(self, with_backup: bool = True):
        self.notes = []
        self.done.pack_forget()
        self.prog.pack(fill="x", pady=(14, 0))
        for k, r in self.steps.items():
            r.set("pending", detail="", right="")
        if not with_backup:
            self.steps["backup"].set("skipped", detail="Using an existing backup")
        self.bar.set(0)

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
        right = f"{pct:.0f}%" + (f" · {eta}" if eta else " · working out time left…")
        self.call(lambda: (self.bar.set(pct), self.steps["backup"].set("active", right=right)))

    def _progress_build(self, pct: float):
        def ui_update():
            if self.steps["choose"].state == "active":
                self.steps["choose"].set("done", detail="")
                self.steps["build"].set("active")
            self.bar.set(pct)
            self.steps["build"].set("active", right=f"{int(pct)}%")
        self.call(ui_update)

    def _export(self, path: Path) -> Path:
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
        self.call(lambda: self.steps["choose"].set(
            "active", detail="Reading your chats and photos…" if (wants_chats or wants_photos) else "Getting ready…"))
        direct = self.s["direct_photos"] and self.udid is not None and "photos" in secs
        index = sx.export_all(path, Path(self.s["archive_dir"]), pw, secs,
                              include_media=self.s["include_media"], log=self.log,
                              progress=self._progress_build,
                              chooser=self._choose_chats if wants_chats else None,
                              formats={f for f, v in self.fmt.items() if v.get()},
                              photo_source="device" if direct else None, udid=self.udid,
                              photo_chooser=self._choose_photos if wants_photos else None)
        return index

    def backup_and_export(self):
        if self.device is None and not messagebox.askyesno(
                wv.APP_NAME, "No iPhone is connected right now.\n\nTry anyway?"):
            return
        self._reset_progress(True)
        t0 = [None]

        def work():
            self.call(lambda: self.steps["backup"].set(
                "active", detail="Checking that your backups are encrypted…"))
            self.ensure_encryption()
            self.call(lambda: self.steps["backup"].set(
                "active", detail="Connecting… Keep your iPhone unlocked and nearby. If it asks for its "
                                 "passcode, enter it. Your chats appear for you to choose as soon as "
                                 "the backup finishes."))
            path = wv.make_backup(Path(self.s["backup_dir"]), self.udid, log=self.log,
                                  progress=lambda p: self._progress_backup(p, t0),
                                  status=lambda text: self.call(
                                      lambda: self.steps["backup"].set("active", detail=text)),
                                  keep=self.s["snapshots_keep"], until_disk_full=self.s["snapshots_until_full"])
            self.call(lambda: self.steps["backup"].set("done", detail="Backup complete", right=""))
            return self._export(path)
        self._run(work, self._exported)

    def export_existing(self, path: Path):
        self._reset_progress(False)
        self._run(lambda: self._export(path), self._exported)

    def _exported(self, index):
        if not index:
            return
        for k in ("choose", "build"):
            if self.steps[k].state in ("active", "pending"):
                self.steps[k].set("done", detail="", right="")
        self.bar.set(100)
        self.last_index = Path(index)
        fm = " + ".join(lbl for f, lbl in (("web", "web pages"), ("excel", "Excel"), ("csv", "CSV")) if self.fmt[f].get())
        notes = ["You chose " + " and ".join(self.notes) + "."] if self.notes else []
        where = self.s["archive_dir"].replace(str(Path.home()), "~", 1)
        self.done_sub.configure(text=f"Saved in {where}  ·  chats as {fm}"
                                + (f"\n{notes[0]}" if notes else ""))
        self.prog.pack_forget()  # the finished card replaces the step list
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
        lines += ["", "Backs up your iPhone to this computer.", "Encrypted · stays on this computer."]
        messagebox.showinfo(f"About {wv.APP_NAME}", "\n".join(lines), parent=self)

    def open_settings(self, focus: str = None):
        SettingsWindow(self, focus)

    # ------------------------------------------------------------------ encryption (S1)
    @staticmethod
    def lock_badge(info) -> str:
        if not info:
            return ""
        return "🔒 Encrypted · on this computer" if info.get("encrypted") else "⚠ Not encrypted"

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

    def password_for(self, path: Path, phone_name: str) -> str | None:
        """The password for an encrypted backup: silently from the keychain, otherwise asked once and offered
        to the keychain. Never logged."""
        pw = wv.password_for_backup(path)
        if pw:
            return pw
        pw = self._on_ui(lambda: ui.ask_password(self, "enter", phone_name, wv.RESET_PASSWORD_HELP))
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
                pw = self._on_ui(lambda: ui.ask_password(self, "enter", name, wv.RESET_PASSWORD_HELP))
                if pw:
                    keychain.set_password(self.udid, pw)
                    self.log("Backup password saved to the keychain.")
            return
        pw = self._on_ui(lambda: ui.ask_password(self, "choose", name))
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
        head = tk.Frame(self, bg=GREEN)
        head.pack(fill="x")
        tk.Label(head, text="Open a backup", bg=GREEN, fg="white", font=font(17, "bold")).pack(side="left", padx=18, pady=12)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)
        tk.Label(body, text="Backups on this computer. You can also drop a backup folder onto the main window.",
                 bg=BG, fg=MUTED, font=font(12), anchor="w", wraplength=600, justify="left").pack(fill="x")
        c = ui.card(body)
        c.pack(fill="both", expand=True, pady=(8, 8))
        self.lb = tk.Listbox(c, font=font(12), activestyle="none", height=10)
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


class SettingsWindow(tk.Toplevel):
    def __init__(self, app: App, focus: str = None):
        super().__init__(app, bg=BG)
        self.app, self.s = app, app.s
        self.title("PhoneKeep settings")
        self.geometry("680x760")
        self.minsize(600, 560)
        self.transient(app)
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        def section(title, sub=None):
            c = ui.card(body)
            c.pack(fill="x", padx=18, pady=(14, 0))
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
        sec = section("Security", status)
        tk.Label(sec, text=("🔒 Encrypted · on this computer" if (info and info["encrypted"]) else ""),
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

        # no network (S3)
        import netguard
        net = section("Internet",
                      "PhoneKeep never sends your data anywhere. It makes no internet connections"
                      + (" (refused by the app itself)" if netguard.installed() else "")
                      + ". The only exception is the button below, which fetches the release page once when you click it, "
                        "with no information about you or your iPhone.")
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
                     "(same Wi-Fi or cable) at or after the chosen time, and tries again every 30 minutes until midnight.")
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
        self.sched_line = tk.Label(ab, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.sched_line.pack(fill="x", pady=(4, 0))
        self.sched_line.configure(text=sch.Plan.from_settings(self.s.data).next_run_text(dt.datetime.now(), None).capitalize())

        # snapshots (B3)
        sp = section("Snapshots",
                     "Every backup is kept as a snapshot you can open from the phone window's timeline. "
                     "Unchanged files are stored once, so ten snapshots don't take ten times the space.")
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
                     "running when this window is closed.")
        self.login_var = tk.BooleanVar(value=bool(self.s["start_at_login"]))
        ui.Chip(hp, "Start at login", self.login_var, lambda: app.set_start_at_login(self.login_var.get()),
                size=12, bg=CARD).pack(anchor="w", pady=3)

        # location (B4)
        import location as loc
        lo = section("Location", "Where your backups are kept. Any disk, external drive or network drive will do (not FAT32).")
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
                     "Build the archive from a backup that's already on this computer, without connecting the iPhone.")
        self.combo = ttk.Combobox(ex, state="readonly")
        self.combo.pack(fill="x")
        row = tk.Frame(ex, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        ui.RoundButton(row, "Build archive from this backup", self._build_existing, "primary", 280, 38, 13,
                       bg=CARD).pack(side="left")
        ui.RoundButton(row, "Other folder…", self._other_folder, "secondary", 140, 38, 13, bg=CARD).pack(side="left", padx=8)
        self.backups: list[dict] = []
        self._refresh_backups()

        bottom = tk.Frame(body, bg=BG)
        bottom.pack(fill="x", padx=18, pady=16)
        ui.RoundButton(bottom, "Done", self.destroy, "primary", 120, 40).pack(side="right")
        if focus == "include":
            self.after(100, lambda: canvas.yview_moveto(0))

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
