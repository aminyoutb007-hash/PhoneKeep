#!/usr/bin/env python3
"""PhoneKeep desktop window. Run: python app.py"""
from __future__ import annotations

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

import phonekeep as wv
import sections as sx
import ui
from ui import BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, font

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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(wv.APP_NAME)
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
        self.after(100, self._pump)
        self.after(120, self._spin)
        self.after(300, self.detect)
        self.after(15000, self._auto_detect)

    # ------------------------------------------------------------------ layout
    def _build(self):
        head = tk.Frame(self, bg=GREEN)
        head.pack(fill="x")
        tk.Label(head, text="PhoneKeep", bg=GREEN, fg="white", font=font(21, "bold")).pack(side="left", padx=(22, 10), pady=14)
        tk.Label(head, text="Back up your iPhone to this computer", bg=GREEN, fg="#d7efe9",
                 font=font(13)).pack(side="left", pady=14)
        ui.RoundButton(head, "⚙  Settings", self.open_settings, "ghost", 130, 34, 13).pack(side="right", padx=16)

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
        self.after(80, self._pump)

    def _spin(self):
        for r in getattr(self, "steps", {}).values():
            r.tick()
        self.after(60, self._spin)

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
            except wv.PhoneKeepError as e:
                err = str(e)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            self.call(lambda: self._finish(result, err, done, quiet))
        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, result, err, done, quiet):
        self.busy = False
        self.go.set_enabled(True)
        self.go.configure_text("Back up again" if not err and self.last_index else "Back up now")
        if err:
            for r in self.steps.values():
                if r.state == "active":
                    r.set("error", detail=err)
            self.log("ERROR: " + err)
            if not quiet:
                messagebox.showerror(wv.APP_NAME, err)
        if done:
            done(None if err else result)

    # ------------------------------------------------------------------ device
    def _auto_detect(self):
        if not self.busy:
            self.detect(silent=True)
        self.after(15000, self._auto_detect)

    def detect(self, silent: bool = False):
        if self.busy or getattr(self, "detecting", False):
            return

        def work():
            return wv.list_devices()

        def done(devs, err=None):
            self.detecting = False
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
                info = wv.backup_info(Path(self.s["backup_dir"]) / self.udid) \
                    if (Path(self.s["backup_dir"]) / self.udid / "Manifest.db").exists() else None
                self.dev_last.configure(text=f"Last backup: {info['date']}" if info else "Not backed up with PhoneKeep yet")
                self.open_btn.set_enabled(True)
            else:
                self.device = self.udid = None
                self.phone.set_state("none")
                self.dev_name.configure(text="No iPhone found")
                self.dev_line.configure(text=err or "Plug in your iPhone (or use Wi-Fi sync), unlock it and tap “Trust”.",
                                        fg=RED if err else MUTED)
                self.dev_last.configure(text="")
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
            pw = self._ask(f"The backup of “{info['name']}” is encrypted.\nEnter the backup password:")
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
                "active", detail="Connecting… Keep your iPhone unlocked and nearby. If it asks for its "
                                 "passcode, enter it. Your chats appear for you to choose as soon as "
                                 "the backup finishes."))
            path = wv.make_backup(Path(self.s["backup_dir"]), self.udid, log=self.log,
                                  progress=lambda p: self._progress_backup(p, t0),
                                  status=lambda text: self.call(
                                      lambda: self.steps["backup"].set("active", detail=text)))
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

    def open_settings(self, focus: str = None):
        SettingsWindow(self, focus)

    # ------------------------------------------------------------------ encryption
    def encryption(self, parent):
        on = messagebox.askyesnocancel(
            wv.APP_NAME,
            "Encrypted backups are protected by a password and also include call history, "
            "Safari history, Health data and saved Wi-Fi networks.\n\n"
            "Yes = turn encryption ON (choose a new password)\nNo = turn encryption OFF (needs the current password)",
            parent=parent)
        if on is None:
            return
        if on:
            pw = simpledialog.askstring(wv.APP_NAME, "New backup password:", show="•", parent=parent)
            if not pw:
                return
            if pw != simpledialog.askstring(wv.APP_NAME, "Type the password again:", show="•", parent=parent):
                messagebox.showerror(wv.APP_NAME, "The passwords don't match.", parent=parent)
                return
            messagebox.showinfo(wv.APP_NAME, "Write this password down. If you lose it, encrypted backups "
                                             "can't be opened and Apple can't recover it.", parent=parent)
        else:
            pw = simpledialog.askstring(wv.APP_NAME, "Current backup password:", show="•", parent=parent)
            if not pw:
                return
        self.log("Changing backup encryption. Your iPhone may ask for its passcode.")
        self._run(lambda: wv.set_backup_encryption(bool(on), pw, self.udid, self.log),
                  lambda r: r is None or messagebox.showinfo(wv.APP_NAME, "Backup encryption updated."))


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

        # security
        sec = section("Backup encryption",
                      "Protects your backups with a password. Encrypted backups also include call history, "
                      "Safari history and Wi-Fi networks. Apple can't recover a lost password.")
        ui.RoundButton(sec, "🔒  Turn encryption on or off…", lambda: app.encryption(self), "secondary",
                       280, 38, 13, bg=CARD).pack(anchor="w")

        # folders
        fo = section("Folders")
        for key, label in (("backup_dir", "Backups"), ("archive_dir", "Archive")):
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
