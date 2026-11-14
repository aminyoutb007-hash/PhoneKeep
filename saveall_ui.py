"""D9: "Save everything…" in the phone window (docs/spec/08-personal-data.md#d9-export-everything).

One sheet: a tick for each kind of data, one date range, one optional search, the formats for chats and an
estimated size. It saves into one new folder with a contents page (index.html) that states the phone, the
backup's date and the filters used. The filtering itself is in exportfilter.py and sections.py.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

import exportfilter
import phonekeep as wv
import sections as sx
import ui
from ui import BG, CARD, GREEN, INK, LINE, MUTED, RED, RoundButton, font

ON_BY_DEFAULT = [k for k, *_ in sx.SECTIONS if k != "files"]
FORMATS = [("web", "Web page"), ("pdf", "PDF"), ("excel", "Excel"), ("csv", "CSV")]
SMALL = 2 * 1000 ** 2       # what a kind without media roughly takes once saved (tables and text)


def estimate_sizes(reader, backup_path: Path) -> dict[str, int]:
    """Roughly what each kind takes when saved with its media, from the backup's own file list."""
    def total(domain, prefix=""):
        try:
            return sum((m[2] or 0) for m in reader.file_meta(domain, prefix).values())
        except Exception:
            return 0
    out = {k: SMALL for k, *_ in sx.SECTIONS}
    out["messages"] = total(sx.HOME, "Library/SMS/") + total(sx.MEDIA, "Library/SMS/Attachments/")
    for key, domain in (("whatsapp", getattr(wv, "WA_DOMAIN", "")), ("whatsappbusiness", getattr(wv, "WA_BUSINESS_DOMAIN", ""))):
        out[key] = total(domain) if domain else SMALL
    out["photos"] = total("CameraRollDomain", "Media/DCIM/")
    out["voicememos"] = max(SMALL, total(sx.MEDIA, "Recordings/"))
    out["voicemail"] = max(SMALL, total(sx.HOME, "Library/Voicemail/"))
    try:
        out["files"] = sum(f.stat().st_size for f in Path(backup_path).rglob("*") if f.is_file())
    except OSError:
        out["files"] = 0
    return out


def human(n: int) -> str:
    for unit, size in (("GB", 1000 ** 3), ("MB", 1000 ** 2)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return "under 1 MB"


class SaveEverythingDialog(tk.Toplevel):
    """result: {"sections", "dates", "search", "formats"} when the owner pressed Save, else None."""

    def __init__(self, parent, counts: dict, sizes_fn: Optional[Callable[[], dict]] = None):
        super().__init__(parent, bg=BG)
        self.title("Save everything")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        self.sizes: dict = {}
        pad = dict(padx=22)
        tk.Label(self, text="Save everything", bg=BG, fg=INK, font=font(18, "bold"), anchor="w").pack(fill="x", pady=(18, 2), **pad)
        tk.Label(self, text="Everything you tick is saved into one folder, with a contents page that opens in "
                            "your browser.", bg=BG, fg=MUTED, font=font(12), anchor="w", wraplength=560,
                 justify="left").pack(fill="x", **pad)

        box = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill="x", pady=(12, 0), **pad)
        self.vars: dict[str, tk.BooleanVar] = {}
        grid = tk.Frame(box, bg=CARD)
        grid.pack(fill="x", padx=12, pady=10)
        labels = dict((k, l) for k, l, *_ in sx.SECTIONS)
        labels["files"] = "All files (raw)"
        for n, (key, label, *_r) in enumerate(sx.SECTIONS):
            v = tk.BooleanVar(value=key in ON_BY_DEFAULT)
            v.trace_add("write", lambda *a: self._update())
            self.vars[key] = v
            extra = counts.get(key) or ""
            text = f"{labels[key]}" + (f"  ·  {extra}" if extra and extra != "nothing found" else "")
            cb = tk.Checkbutton(grid, text=text, variable=v, bg=CARD, fg=INK, activebackground=CARD,
                                highlightthickness=0, bd=0, font=font(12), anchor="w")
            cb.grid(row=n // 2, column=n % 2, sticky="w", padx=(0, 24), pady=2)
            if extra == "nothing found":
                v.set(False)
                cb.configure(state="disabled")

        f = tk.Frame(self, bg=BG)
        f.pack(fill="x", pady=(14, 0), **pad)
        tk.Label(f, text="📅  Dates", bg=BG, fg=INK, font=font(13, "bold"), width=12, anchor="w").pack(side="left")
        self.preset = tk.StringVar(value="All dates")
        pc = ttk.Combobox(f, textvariable=self.preset, values=ui.DATE_PRESETS, state="readonly", width=15)
        pc.pack(side="left")
        pc.bind("<<ComboboxSelected>>", lambda e: self._preset())
        self.d_from, self.d_to = tk.StringVar(), tk.StringVar()
        tk.Label(f, text="from", bg=BG, fg=MUTED, font=font(12)).pack(side="left", padx=(12, 4))
        e1 = ttk.Entry(f, textvariable=self.d_from, width=11)
        e1.pack(side="left")
        tk.Label(f, text="to", bg=BG, fg=MUTED, font=font(12)).pack(side="left", padx=4)
        e2 = ttk.Entry(f, textvariable=self.d_to, width=11)
        e2.pack(side="left")
        for e in (e1, e2):
            e.bind("<KeyRelease>", lambda ev: (self.preset.set("Custom dates"), self._update()))

        s = tk.Frame(self, bg=BG)
        s.pack(fill="x", pady=(10, 0), **pad)
        tk.Label(s, text="🔍  Only things\nmentioning", bg=BG, fg=INK, font=font(13, "bold"), width=12, anchor="w",
                 justify="left").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self._update())
        se = ttk.Entry(s, textvariable=self.search, width=34)
        se.pack(side="left")
        tk.Label(s, text="(optional: a name, a word, a number)", bg=BG, fg=MUTED, font=font(11)).pack(side="left", padx=8)

        fm = tk.Frame(self, bg=BG)
        fm.pack(fill="x", pady=(10, 0), **pad)
        tk.Label(fm, text="💬  Chats as", bg=BG, fg=INK, font=font(13, "bold"), width=12, anchor="w").pack(side="left")
        self.fvars = {}
        for key, label in FORMATS:
            v = tk.BooleanVar(value=key == "web")
            v.trace_add("write", lambda *a: self._update())
            self.fvars[key] = v
            tk.Checkbutton(fm, text=label, variable=v, bg=BG, fg=INK, activebackground=BG, highlightthickness=0, bd=0,
                           font=font(12)).pack(side="left", padx=(0, 12))

        self.note = tk.Label(self, text="", bg=BG, fg=MUTED, font=font(12), anchor="w", wraplength=560, justify="left")
        self.note.pack(fill="x", pady=(14, 0), **pad)
        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", pady=16, **pad)
        RoundButton(btns, "Save…", self._ok, "primary", 130, 38, 13).pack(side="right")
        RoundButton(btns, "Cancel", self.destroy, "secondary", 110, 38, 13).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self._update()
        if sizes_fn is not None:
            def work():
                try:
                    got = sizes_fn()
                except Exception:
                    got = {}
                self._sizes_ready = got
            self._sizes_ready = None
            threading.Thread(target=work, daemon=True).start()
            self._wait_sizes()

    def _wait_sizes(self):
        if not self.winfo_exists():
            return
        if self._sizes_ready is None:
            self.after(150, self._wait_sizes)
            return
        self.sizes = self._sizes_ready
        self._update()

    # reading the sheet ----------------------------------------------------------------------------------------
    def _preset(self):
        lo, hi = ui.preset_range(self.preset.get())
        if self.preset.get() != "Custom dates":
            self.d_from.set(lo.isoformat() if lo else "")
            self.d_to.set(hi.isoformat() if hi else "")
        self._update()

    def chosen(self) -> dict:
        """What the sheet says now; raises ValueError for a date that isn't one."""
        lo, hi = ui.parse_day(self.d_from.get()), ui.parse_day(self.d_to.get())
        if lo and hi and lo > hi:
            raise ValueError("The ‘from’ date is after the ‘to’ date.")
        return {"sections": [k for k, v in self.vars.items() if v.get()],
                "dates": (lo, hi) if (lo or hi) else None,
                "search": self.search.get().strip(),
                "formats": {k for k, v in self.fvars.items() if v.get()} or {"web"}}

    def _update(self):
        if not hasattr(self, "note"):          # still building the sheet
            return
        try:
            c = self.chosen()
        except ValueError as e:
            msg = str(e) if "after" in str(e) else f"“{e}” isn't a date. Use 2026-01-31."
            self.note.configure(text=msg, fg=RED)
            return
        flt = exportfilter.Filter(c["dates"], c["search"])
        parts = []
        if not c["sections"]:
            self.note.configure(text="Tick at least one kind of data.", fg=RED)
            return
        if flt.on:
            parts.append(f"Only what's {flt.describe()}.")
        if c["search"] and "photos" in c["sections"]:
            parts.append("Photos and videos have no text to search, so they're left out while searching.")
        if self.sizes:
            n = sum(self.sizes.get(k, SMALL) for k in c["sections"])
            parts.append(("At most about " if flt.on else "About ") + human(n) + " (estimate).")
        else:
            parts.append("Working out the size…")
        self.note.configure(text="  ".join(parts), fg=MUTED)

    def _ok(self):
        try:
            c = self.chosen()
        except ValueError:
            self._update()
            return
        if not c["sections"]:
            return
        self.result = c
        self.destroy()


def folder_name(device_name: str, when: Optional[dt.datetime] = None) -> str:
    when = when or dt.datetime.now()
    return sx.safe_name(f"{device_name} - everything {when:%Y-%m-%d %H%M}", 100)
