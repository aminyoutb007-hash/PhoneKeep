"""
PhoneKeep - shared look & feel and the two pickers (chats, photos).

Built on plain tkinter so it runs everywhere Python does. Custom widgets (rounded buttons,
toggle chips) are drawn on canvases because native macOS buttons ignore custom colours.
"""
from __future__ import annotations

import datetime as dt
import queue
import sys
from pathlib import Path
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from typing import Callable, Optional

try:
    from PIL import Image, ImageTk
except Exception:  # previews need Pillow; everything else works without it
    Image = ImageTk = None

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
GREEN = "#008069"
GREEN_DARK = "#006a57"
SELECT_BLUE = "#0a84ff"          # selected photos (the system's blue)
GREEN_SOFT = "#e7f6f2"
BG = "#f0f2f5"
CARD = "#ffffff"
INK = "#111b21"
MUTED = "#667781"
LINE = "#e2e6e9"
ME = "#d9fdd3"
RED = "#c5221f"
AMBER = "#b06000"

FONT_FAMILY = None


def font(size: int = 13, weight: str = "normal"):
    global FONT_FAMILY
    if FONT_FAMILY is None:
        try:
            FONT_FAMILY = tkfont.nametofont("TkDefaultFont").actual("family")
        except Exception:
            FONT_FAMILY = "Helvetica"
    if sys.platform != "darwin":
        size = max(9, size - 3)  # Windows/Linux points render larger than macOS
    return (FONT_FAMILY, size, weight)


def setup_styles(root: tk.Misc) -> None:
    st = ttk.Style(root)
    if sys.platform != "darwin":
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
    st.configure("Treeview", rowheight=28, font=font(13))
    st.configure("Treeview.Heading", font=font(12, "bold"))



# where the data is and how it is protected, in one line (usability task 5, 13 Nov): the same everywhere
PROTECTED = "🔒 Encrypted with your backup password · never sent online"

class RoundButton(tk.Canvas):
    """A pill-shaped button: kind = primary | secondary | ghost | light."""

    COLORS = {
        "primary": (GREEN, GREEN_DARK, "#ffffff", "#9fd3c7"),
        "secondary": ("#ffffff", "#eef1f3", INK, "#f4f5f6"),
        "ghost": (GREEN, GREEN_DARK, "#ffffff", GREEN),
        "light": (GREEN_SOFT, "#d6efe8", GREEN_DARK, "#f0f7f5"),
    }

    def __init__(self, parent, text: str, command: Callable = None, kind: str = "primary",
                 width: int = 160, height: int = 40, size: int = 14, bg: str = None):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0,
                         bg=bg or parent.cget("bg"), cursor="hand2")
        self.text, self.command, self.kind = text, command, kind
        self.w, self.h, self.size = width, height, size
        self.enabled, self.hover = True, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", self._resize)
        self._draw()

    def _resize(self, e):
        if e.width != self.w:
            self.w = e.width
            self._draw()

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def configure_text(self, text: str):
        self.text = text
        self._draw()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _click(self, _e):
        if self.enabled and self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        fill, hover, fg, disabled = self.COLORS[self.kind]
        color = disabled if not self.enabled else (hover if self.hover else fill)
        r, w, h = self.h // 2, self.w, self.h
        outline = LINE if self.kind == "secondary" else color
        self.create_oval(1, 1, 2 * r - 1, h - 1, fill=color, outline=outline)
        self.create_oval(w - 2 * r + 1, 1, w - 1, h - 1, fill=color, outline=outline)
        self.create_rectangle(r, 1, w - r, h - 1, fill=color, outline=color)
        if self.kind == "secondary":
            self.create_line(r, 1, w - r, 1, fill=LINE)
            self.create_line(r, h - 1, w - r, h - 1, fill=LINE)
        tc = fg if self.enabled else ("#ffffff" if self.kind == "primary" else MUTED)
        self.create_text(w // 2, h // 2, text=self.text, fill=tc,
                         font=font(self.size, "bold" if self.kind == "primary" else "normal"))


ICON_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "icons"
_ICON_CACHE: dict = {}


def app_icon(key: str, small: bool = False, size: int = 0):
    """PhoneKeep's own drawn icon for an app (tools/make_app_icons.py), or None (then the emoji is shown).
    small = the 28 px version; size=48 the main screen's choice icons."""
    k = (key, small, size)
    if _ICON_CACHE.get(k) is not None:
        try:
            _ICON_CACHE[k].width()          # still belongs to a live window (a closed one invalidates it)
            ok = _ICON_CACHE[k].tk is tk._default_root.tk if tk._default_root else True
        except (tk.TclError, RuntimeError):
            ok = False
        if not ok:
            del _ICON_CACHE[k]
    if k not in _ICON_CACHE:
        img = None
        p = ICON_DIR / (f"{key}-28.png" if small else f"{key}-{size}.png" if size else f"{key}.png")
        if p.exists():
            try:
                from PIL import Image as _Image, ImageTk as _itk
                img = _itk.PhotoImage(_Image.open(p))
            except Exception:
                img = None
        _ICON_CACHE[k] = img
    return _ICON_CACHE[k]


class ChoiceCard(tk.Canvas):
    """One of the "What do you want to keep?" choices: a soft rounded card with PhoneKeep's drawn icon,
    a title and one line of detail; chosen = green outline, light green fill and a ✓ badge
    (owner, 13 Nov: the old boxes with emoji looked messy)."""

    H = 138

    def __init__(self, parent, icon, title: str, sub: str, command: Callable, bg: str = None):
        super().__init__(parent, height=self.H, highlightthickness=0, bd=0, bg=bg or parent.cget("bg"), cursor="hand2")
        self.icon, self.title, self.sub, self.chosen, self.hover = icon, title, sub, False, False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonRelease-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        self.hover = on
        self._draw()

    def set(self, chosen: bool):
        self.chosen = chosen
        self._draw()

    def _round(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 120), self.H
        fill = GREEN_SOFT if self.chosen else "#ffffff"
        line = GREEN if self.chosen else ("#b9c3c9" if self.hover else LINE)
        self._round(2, 2, w - 2, h - 2, 16, fill=fill, outline=line, width=2 if self.chosen else 1)
        if self.icon is not None:
            self.create_image(w // 2, 38, image=self.icon)
        self.create_text(w // 2, 82, text=self.title, fill=INK, font=font(14, "bold"))
        self.create_text(w // 2, 108, text=self.sub, fill=MUTED, font=font(11), width=w - 24, justify="center")
        if self.chosen:
            self.create_oval(w - 30, 10, w - 10, 30, fill=GREEN, outline=GREEN)
            self.create_text(w - 20, 20, text="✓", fill="#ffffff", font=font(11, "bold"))


class Chip(tk.Canvas):
    """A toggle chip: rounded, green with a tick when on, outlined when off."""

    def __init__(self, parent, text: str, variable: tk.BooleanVar, command: Callable = None,
                 size: int = 13, bg: str = None, height: int = 32):
        f = tkfont.Font(font=font(size))
        self.text, self.var, self.command, self.size = text, variable, command, size
        self.w = f.measure("✓ " + text) + 28
        self.h = height
        super().__init__(parent, width=self.w, height=self.h, highlightthickness=0, bd=0,
                         bg=bg or parent.cget("bg"), cursor="hand2")
        self.bind("<ButtonRelease-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        on = self.var.get()
        fill, fg, outline = (GREEN, "#ffffff", GREEN) if on else ("#ffffff", INK, "#c9d1d6")
        r, w, h = self.h // 2, self.w, self.h
        self.create_oval(1, 1, 2 * r - 1, h - 1, fill=fill, outline=outline)
        self.create_oval(w - 2 * r + 1, 1, w - 1, h - 1, fill=fill, outline=outline)
        self.create_rectangle(r, 1, w - r, h - 1, fill=fill, outline=fill)
        self.create_line(r, 1, w - r, 1, fill=outline)
        self.create_line(r, h - 1, w - r, h - 1, fill=outline)
        self.create_text(w // 2, h // 2, text=("✓ " if on else "") + self.text, fill=fg, font=font(self.size))


def card(parent, **kw) -> tk.Frame:
    return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, **kw)


class BgWorker:
    """Runs small jobs (thumbnails) in one background thread and hands results to the UI thread."""

    def __init__(self, widget: tk.Misc):
        self.widget = widget
        self.jobs: queue.Queue = queue.Queue()
        self.done: queue.Queue = queue.Queue()
        self.alive = True
        threading.Thread(target=self._run, daemon=True).start()
        self._poll()

    def submit(self, fn, callback):
        self.jobs.put((fn, callback))

    def clear(self):
        try:
            while True:
                self.jobs.get_nowait()
        except queue.Empty:
            pass

    def stop(self):
        self.alive = False
        self.clear()
        self.jobs.put(None)

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None or not self.alive:
                return
            fn, cb = job
            try:
                res = fn()
            except Exception:
                res = None
            self.done.put((cb, res))

    def _poll(self):
        if not self.alive:
            return
        try:
            while True:
                cb, res = self.done.get_nowait()
                try:
                    cb(res)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        try:
            self.widget.after(60, self._poll)
        except tk.TclError:
            pass


def load_photo(path, max_px: int, square: bool = False) -> Optional["ImageTk.PhotoImage"]:
    if not path or Image is None:
        return None
    try:
        from PIL import ImageOps
        im = Image.open(path)
        if square:
            im = ImageOps.fit(im.convert("RGB"), (max_px, max_px))
        else:
            im.thumbnail((max_px, max_px))
        return ImageTk.PhotoImage(im)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Chat picker with preview
# ---------------------------------------------------------------------------
TYPE_LABEL = {"image": "📷 Photo", "video": "🎬 Video", "audio": "🎤 Voice note", "document": "📄 Document",
              "sticker": "Sticker", "gif": "GIF", "location": "📍 Location", "contact": "👤 Contact",
              "deleted": "🚫 Deleted message", "system": "Group update", "link": "🔗 Link"}


DATE_PRESETS = ["All dates", "Today", "Last 7 days", "Last 30 days", "Last 3 months",
                "Last 12 months", "This year", "Last year", "Custom dates"]


def preset_range(name: str, today: Optional[dt.date] = None):
    """(from, to) dates for a preset name; (None, None) for all dates."""
    t = today or dt.date.today()
    days = {"Today": 0, "Last 7 days": 6, "Last 30 days": 29, "Last 3 months": 91, "Last 12 months": 364}
    if name in days:
        return t - dt.timedelta(days=days[name]), t
    if name == "This year":
        return dt.date(t.year, 1, 1), t
    if name == "Last year":
        return dt.date(t.year - 1, 1, 1), dt.date(t.year - 1, 12, 31)
    return None, None


def parse_day(text: str) -> Optional[dt.date]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def count_in_range(days: list, lo: Optional[dt.date], hi: Optional[dt.date]) -> int:
    """days: sorted 'YYYY-MM-DD' strings."""
    import bisect
    a = bisect.bisect_left(days, lo.isoformat()) if lo else 0
    b = bisect.bisect_right(days, hi.isoformat()) if hi else len(days)
    return max(0, b - a)


class ChatPanel(tk.Frame):
    """Chats from WhatsApp, WhatsApp Business and/or Messages: search, dates, tick boxes and a
    conversation preview. Used by the export picker and by the phone window."""

    def __init__(self, parent, lists: dict, preview=None, select_all: bool = True, preview_limit: int = 80):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        self.preview = preview
        self.preview_limit = preview_limit
        self.rows = [(k, label, c) for k, (label, chats) in lists.items() for c in chats]
        self.selected = {(k, c["id"]) for k, _l, c in self.rows} if select_all else set()
        self.apps = [label for _k, (label, _c) in lists.items()]
        self.images = []
        self.worker = BgWorker(self)
        self.bind("<Destroy>", lambda e: self.worker.stop() if e.widget is self else None)
        self.current = None
        self.lo = self.hi = None   # date range (None = open)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(bar, text="🔍", bg=BG, font=font(14)).pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._fill())
        ent = ttk.Entry(bar, textvariable=self.q, width=28)
        ent.pack(side="left", padx=(4, 10))
        self.search_hint = tk.Label(bar, text="", bg=BG, fg=MUTED, font=font(11))
        self.app_var = tk.StringVar(value="All apps")
        if len(self.apps) > 1:
            cb = ttk.Combobox(bar, textvariable=self.app_var, values=["All apps"] + self.apps,
                              state="readonly", width=18)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        self.search_hint.pack(side="left", padx=(10, 0))

        dbar = tk.Frame(self, bg=BG)
        dbar.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(dbar, text="📅  Messages from", bg=BG, fg=INK, font=font(13)).pack(side="left")
        self.preset = tk.StringVar(value="All dates")
        pc = ttk.Combobox(dbar, textvariable=self.preset, values=DATE_PRESETS, state="readonly", width=15)
        pc.pack(side="left", padx=(8, 12))
        pc.bind("<<ComboboxSelected>>", lambda e: self._preset())
        tk.Label(dbar, text="From", bg=BG, fg=MUTED, font=font(12)).pack(side="left")
        self.d_from = tk.StringVar()
        self.d_to = tk.StringVar()
        e1 = ttk.Entry(dbar, textvariable=self.d_from, width=11)
        e1.pack(side="left", padx=(4, 8))
        tk.Label(dbar, text="to", bg=BG, fg=MUTED, font=font(12)).pack(side="left")
        e2 = ttk.Entry(dbar, textvariable=self.d_to, width=11)
        e2.pack(side="left", padx=(4, 8))
        for e in (e1, e2):
            e.bind("<Return>", lambda ev: self._typed_dates())
            e.bind("<FocusOut>", lambda ev: self._typed_dates())
        self.date_hint = tk.Label(dbar, text="e.g. 2024-01-31", bg=BG, fg=MUTED,
                                  font=font(11))
        self.date_hint.pack(side="left", padx=6)
        self.hide_empty = tk.BooleanVar(value=True)
        ttk.Checkbutton(dbar, text="Hide empty", variable=self.hide_empty,
                        command=self._fill).pack(side="right")

        body = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bg=BG, bd=0)
        body.pack(fill="both", expand=True, padx=16)
        left = tk.Frame(body, bg=BG)
        # ticking controls sit right above the list they act on (owner, 13 Nov)
        tbar = tk.Frame(left, bg=BG)
        tbar.pack(side="top", fill="x", pady=(0, 6))
        RoundButton(tbar, "Select all", lambda: self._set_all(True), "secondary", 110, 30, 12, bg=BG).pack(side="left")
        RoundButton(tbar, "Select none", lambda: self._set_all(False), "secondary", 120, 30, 12, bg=BG).pack(side="left", padx=6)
        self.tick_count = tk.Label(tbar, text="", bg=BG, fg=MUTED, font=font(12))
        self.tick_count.pack(side="left", padx=(8, 0))
        cols = ("tick", "name") + (("app",) if len(self.apps) > 1 else ()) + ("messages", "last")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        heads = {"tick": ("✓", 36), "name": ("Chat", 230), "app": ("App", 130),
                 "messages": ("Messages", 80), "last": ("Last", 92)}
        for c in cols:
            self.tree.heading(c, text=heads[c][0])
            self.tree.column(c, width=heads[c][1], stretch=(c == "name"),
                             anchor="center" if c in ("tick", "messages") else "w")
        self.tree.heading("tick", command=lambda: self._set_all(not self._all_shown_ticked()))   # ✓ ticks/unticks all shown
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<ButtonRelease-1>", self._click)
        self.tree.bind("<space>", lambda e: (self._toggle(self.tree.focus()), "break")[1])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show(self.tree.focus()))
        body.add(left, minsize=420, width=560)

        right = card(body)
        self.pv_title = tk.Label(right, text="Preview", bg=CARD, fg=INK, font=font(15, "bold"), anchor="w")
        self.pv_title.pack(fill="x", padx=14, pady=(10, 0))
        self.pv_sub = tk.Label(right, text="Click a chat on the left to see its latest messages.",
                               bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.pv_sub.pack(fill="x", padx=14, pady=(0, 6))
        tf = tk.Frame(right, bg="#efeae2")
        tf.pack(fill="both", expand=True)
        # fg must be set: in macOS dark mode Tk's default text colour is white, which vanished on the light
        # bubbles (owner, 12 Nov: "all messages look empty")
        self.text = tk.Text(tf, bg="#efeae2", fg=INK, insertbackground=INK, selectforeground=INK,
                            relief="flat", wrap="word", font=font(13), padx=10, pady=8,
                            cursor="arrow", highlightthickness=0)
        tsb = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=tsb.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.text.tag_configure("them", foreground=INK, lmargin1=6, lmargin2=6, rmargin=70, background="#ffffff",
                                spacing1=6, spacing3=2)
        self.text.tag_configure("me", foreground=INK, lmargin1=70, lmargin2=70, rmargin=6, background=ME,
                                spacing1=6, spacing3=2)
        self.text.tag_configure("sender", foreground=GREEN, font=font(11, "bold"))
        self.text.tag_configure("meta", foreground=MUTED, font=font(10))
        self.text.tag_configure("day", justify="center", foreground=MUTED, font=font(11, "bold"),
                                spacing1=12, spacing3=4)
        self.text.tag_configure("sys", justify="center", foreground=AMBER, font=font(11), spacing1=6)
        self.text.tag_configure("hit", background="#ffe58f", foreground=INK)
        self.text.tag_raise("hit")
        body.add(right, minsize=300)

        self.foot = tk.Frame(self, bg=BG)
        self.foot.pack(side="bottom", fill="x", padx=16, pady=12, before=body)
        self.count = tk.Label(self.foot, bg=BG, fg=INK, font=font(13))
        self.count.pack(side="left")
        self._fill()
        ent.focus_set()
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.focus(kids[0])

    # list ---------------------------------------------------------------
    def _fill(self):
        q = self.q.get().strip().lower()
        app = self.app_var.get()
        self.tree.delete(*self.tree.get_children())
        # the search finds chats by name AND by what was said in them (usability test, 12 Nov:
        # "find a message containing 'merci'" found nothing)
        self.hits = {}
        if q and self.preview is not None and len(q) >= 2:
            for key in {k for k, _l, _c in self.rows}:
                for cid, n in self.preview.matching(key, q).items():
                    self.hits[(key, cid)] = n
        n_hit_chats = 0
        for i, (key, label, c) in enumerate(self.rows):
            if q and q not in c["name"].lower() and (key, c["id"]) not in self.hits:
                continue
            if (key, c["id"]) in self.hits:
                n_hit_chats += 1
            if app != "All apps" and label != app:
                continue
            n_in = self._n_in(c)
            if n_in == 0 and self.hide_empty.get() and (self.lo or self.hi):
                continue
            vals = ("☑" if (key, c["id"]) in self.selected else "☐",
                    ("👥 " if c["group"] else "") + c["name"])
            if len(self.apps) > 1:
                vals += (label,)
            vals += (f"{n_in:,}", c["last"])
            self.tree.insert("", "end", iid=str(i), values=vals, tags=("dim",) if n_in == 0 else ())
        self.tree.tag_configure("dim", foreground=MUTED)
        if hasattr(self, "search_hint"):
            total = sum(self.hits.values())
            self.search_hint.configure(text=(f"“{self.q.get().strip()}” is in {total:,} message{'s' if total != 1 else ''} "
                                             f"across {n_hit_chats:,} chat{'s' if n_hit_chats != 1 else ''}") if q and total
                                       else (f"No message contains “{self.q.get().strip()}”" if q and len(q) >= 2 and not
                                             any(q in c['name'].lower() for _k, _l, c in self.rows) else ""))
        self.current = None
        self._update_count()

    def _toggle(self, iid):
        if not iid:
            return
        key, _label, c = self.rows[int(iid)]
        k = (key, c["id"])
        self.selected.symmetric_difference_update({k})
        self.tree.set(iid, "tick", "☑" if k in self.selected else "☐")
        self._update_count()

    def _click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if self.tree.identify_column(event.x) == "#1":  # the tick column
            self._toggle(iid)

    def _all_shown_ticked(self) -> bool:
        kids = self.tree.get_children()
        return bool(kids) and all((self.rows[int(i)][0], self.rows[int(i)][2]["id"]) in self.selected for i in kids)

    def _set_all(self, on: bool):
        for iid in self.tree.get_children():
            key, _l, c = self.rows[int(iid)]
            (self.selected.add if on else self.selected.discard)((key, c["id"]))
        self._fill()

    def _n_in(self, c) -> int:
        if not (self.lo or self.hi):
            return c["messages"]
        days = c.get("days")
        if days is None:
            return c["messages"]
        return count_in_range(days, self.lo, self.hi)

    def _update_count(self):
        sel = [c for k, _l, c in self.rows if (k, c["id"]) in self.selected]
        msgs = sum(self._n_in(c) for c in sel)
        text = f"{len(sel):,} of {len(self.rows):,} chats ticked · {msgs:,} messages"
        if self.lo or self.hi:
            f = lambda d: d.strftime("%d %b %Y")
            when = (f"{f(self.lo)} – {f(self.hi)}" if self.lo and self.hi else
                    f"from {f(self.lo)}" if self.lo else f"up to {f(self.hi)}")
            with_msgs = sum(1 for c in sel if self._n_in(c) > 0)
            text += f" in {with_msgs:,} chat{'s' if with_msgs != 1 else ''} · {when}"
        self.count.configure(text=text)
        shown = len(self.tree.get_children())
        ticked = sum(1 for i in self.tree.get_children() if (self.rows[int(i)][0], self.rows[int(i)][2]["id"]) in self.selected)
        self.tick_count.configure(text=f"{ticked:,} of {shown:,} shown are ticked")

    # dates --------------------------------------------------------------
    def _preset(self):
        name = self.preset.get()
        if name == "Custom dates":
            self.date_hint.configure(text="Type the dates, then press Return", fg=GREEN)
            return
        lo, hi = preset_range(name)
        self.d_from.set(lo.isoformat() if lo else "")
        self.d_to.set(hi.isoformat() if hi else "")
        self._apply_dates(lo, hi)

    def _typed_dates(self):
        try:
            lo, hi = parse_day(self.d_from.get()), parse_day(self.d_to.get())
        except ValueError as e:
            self.date_hint.configure(text=f"“{e}” isn't a date. Use 2024-01-31.", fg=RED)
            return
        if lo and hi and lo > hi:
            self.date_hint.configure(text="The ‘from’ date is after the ‘to’ date.", fg=RED)
            return
        if (lo, hi) != (self.lo, self.hi):
            self.preset.set("Custom dates" if (lo or hi) else "All dates")
        self._apply_dates(lo, hi)

    def _apply_dates(self, lo, hi):
        self.lo, self.hi = lo, hi
        self.date_hint.configure(text="Only these dates are saved" if (lo or hi)
                                 else "e.g. 2024-01-31", fg=MUTED)
        self._fill()

    # preview ------------------------------------------------------------
    def _show(self, iid):
        if not iid or self.preview is None:
            return
        key, label, c = self.rows[int(iid)]
        if self.current == (key, c["id"]):
            return
        self.current = (key, c["id"])
        self.worker.clear()
        q = self.q.get().strip()
        around = q if (key, c["id"]) in getattr(self, "hits", {}) else None
        msgs, total = self.preview.messages(key, c["id"], self.preview_limit, around=around)
        self.pv_title.configure(text=c["name"])
        shown = f"latest {len(msgs)} of {total:,} messages" if total > len(msgs) else f"{total:,} messages"
        self.pv_sub.configure(text=f"{label} · {shown}" + (" · group" if c["group"] else ""))
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        self.images.clear()
        last_day = None
        for i, m in enumerate(msgs):
            when = dt.datetime.fromisoformat(m["time"]) if m.get("time") else None
            day = when.strftime("%A %d %B %Y") if when else ""
            if day != last_day:
                t.insert("end", day + "\n", "day")
                last_day = day
            if m.get("type") == "system":
                t.insert("end", (m.get("text") or "Group update") + "\n", "sys")
                continue
            tag = "me" if m.get("from_me") else "them"
            if c["group"] and not m.get("from_me"):
                t.insert("end", (m.get("sender") or "") + "\n", (tag, "sender"))
            if m.get("type") in ("image", "sticker", "gif"):
                mark = f"img{i}"
                t.mark_set(mark, "end-1c")
                t.mark_gravity(mark, "left")
                t.insert("end", "📷 Photo", (tag, mark + "ph"))
                t.insert("end", "\n", tag)
                self.worker.submit(lambda m=m: self.preview.thumbnail(key, m),
                                   lambda path, mark=mark, cur=self.current: self._put_image(path, mark, cur))
            body = m.get("text") or ""
            if m.get("caption") and m.get("type") not in ("image",):
                body = (body + "\n" + m["caption"]).strip()
            if not body and m.get("type") not in ("image", "sticker", "gif"):
                body = TYPE_LABEL.get(m.get("type"), m.get("type", ""))
            if body:
                t.insert("end", body + "\n", tag)
            t.insert("end", (when.strftime("%H:%M") if when else "") + "\n", (tag, "meta"))
        if not msgs:
            t.insert("end", "No messages to show.\n", "day")
        t.tag_remove("hit", "1.0", "end")
        first = None
        if around:
            pos = "1.0"
            while True:
                pos = t.search(around, pos, stopindex="end", nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(around)}c"
                t.tag_add("hit", pos, end)
                first = first or pos
                pos = end
        t.configure(state="disabled")
        t.see(first or "end")

    def _put_image(self, path, mark, cur):
        if cur != self.current or not path:
            return
        img = load_photo(path, 220)
        if img is None:
            return
        self.images.append(img)
        t = self.text
        t.configure(state="normal")
        try:
            rng = t.tag_ranges(mark + "ph")
            if rng:
                t.delete(rng[0], rng[1])
            t.image_create(mark, image=img, padx=4, pady=4)
        except tk.TclError:
            pass
        t.configure(state="disabled")
        t.see("end")

    # result -------------------------------------------------------------
    def selection(self, confirm_empty: bool = True):
        """{app key: set(chat ids)} plus "_dates": (from, to) when a range is set; None if not ready."""
        out = {key: set() for key, _l, _c in self.rows}
        for key, cid in self.selected:
            out[key].add(cid)
        if confirm_empty and not self.selected and not messagebox.askyesno(
                "PhoneKeep", "No chats are ticked, so no chats will be exported. Continue?", parent=self):
            return None
        self._typed_dates()
        if self.date_hint.cget("fg") == RED:
            return None
        if self.lo or self.hi:
            out["_dates"] = (self.lo, self.hi)
            for key, _l, c in self.rows:   # ticked chats with nothing in these dates are left out
                if self._n_in(c) == 0:
                    out[key].discard(c["id"])
            if self.selected and not any(out[k] for k in out if k != "_dates"):
                if not messagebox.askyesno("PhoneKeep", "The ticked chats have no messages in these dates, "
                                           "so nothing will be exported from them. Continue?", parent=self):
                    return None
        return out


class Eta:
    """Progress → 'NN% · about M min left'. The time left comes from the speed over the last few minutes
    (settles quickly, follows changes such as many small files then big videos); until there is enough to
    go on it says 'working out time left…'. Used by every transfer PhoneKeep shows (01-principles.md)."""

    def __init__(self, window: float = 300.0, settle: float = 10.0):
        import time as _t
        self._t, self.window, self.settle = _t, window, settle
        self.points: list = []

    @staticmethod
    def fmt(seconds: float) -> str:
        if seconds < 90:
            return "under 2 min left"
        m = int(seconds // 60)
        return f"about {m} min left" if m < 90 else f"about {m // 60} h {m % 60:02d} min left"

    def feed(self, pct: float) -> str:
        """Record a percentage and return the text to show."""
        now = self._t.time()
        pct = max(0.0, min(100.0, float(pct)))
        self.points.append((now, pct))
        while len(self.points) > 2 and now - self.points[0][0] > self.window:
            self.points.pop(0)
        if pct >= 100:
            return "100%"
        first = self.points[0]
        eta = ""
        if pct > first[1] + 0.5 and now - first[0] >= self.settle:
            rate = (pct - first[1]) / (now - first[0])
            if rate > 0:
                eta = self.fmt((100 - pct) / rate)
        return f"{pct:.0f}%" + (f" · {eta}" if eta else " · working out time left…")


def touchpad_deltas(delta: int) -> tuple[int, int]:
    """Tk 9's <TouchpadScroll> packs the horizontal and vertical pixel deltas in one number (what
    tk::PreciseScrollDeltas unpacks): the high 16 bits are x, the low 16 bits y, both signed."""
    dx = delta >> 16
    dy = ((delta & 0xFFFF) ^ 0x8000) - 0x8000
    if dx >= 0x8000:
        dx -= 0x10000
    return dx, dy


def wheel_scroll(canvas: tk.Canvas) -> None:
    """Scroll `canvas` with a mouse wheel, Linux's buttons 4/5, and a Mac trackpad's two-finger scroll
    (Tk 9 sends that as <TouchpadScroll>, not <MouseWheel>; owner, 13 Nov: two-finger scroll did nothing in
    Photos), wherever the pointer is inside it, including over the tiles and labels it holds."""
    canvas.configure(yscrollincrement=1)                 # scroll in pixels, so a trackpad moves smoothly
    top = canvas.winfo_toplevel()

    def inside(w) -> bool:
        while w is not None:
            if w is canvas:
                return True
            w = getattr(w, "master", None)
        return False

    def pixels(n: float):
        if canvas.winfo_exists() and n:
            canvas.yview_scroll(int(n), "units")

    def on_wheel(e):
        if inside(e.widget):
            d = e.delta
            steps = d / 120 if abs(d) >= 120 else d      # Windows/Tk 9 notches are 120; Tk 8.6 on a Mac sends small ints
            pixels(-steps * 40)

    def on_touchpad(e):
        if inside(e.widget):
            _dx, dy = touchpad_deltas(int(e.delta))
            pixels(-dy)

    top.bind("<MouseWheel>", on_wheel, add="+")
    top.bind("<Button-4>", lambda e: inside(e.widget) and pixels(-120), add="+")
    top.bind("<Button-5>", lambda e: inside(e.widget) and pixels(120), add="+")
    try:
        top.bind("<TouchpadScroll>", on_touchpad, add="+")
    except tk.TclError:                                  # Tk 8.6 has no such event
        pass


def use_light_appearance(win) -> bool:
    """PhoneKeep is drawn in light colours; on a Mac in dark mode the standard controls (lists, text boxes,
    drop-downs) would otherwise turn black (owner, 13 Nov: "the chats in black look untidy"). Until a real
    dark mode exists (E6), every PhoneKeep window uses macOS's light appearance. Returns True if applied."""
    if sys.platform != "darwin":
        return False
    done = False
    try:                                   # the whole app at once
        from AppKit import NSApplication, NSAppearance
        NSApplication.sharedApplication().setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))
        done = True
    except Exception:
        pass
    try:                                   # and this window (works without pyobjc, Tk 8.6.10+)
        win.tk.call("::tk::unsupported::MacWindowStyle", "appearance", win, "aqua")
        done = True
    except Exception:
        pass
    return done


def _attach_app_menu(win: tk.Toplevel) -> None:
    """Give a dialog the app's menu bar (macOS shows Tk's default File menu otherwise), and the light look."""
    if isinstance(win, tk.Toplevel):
        use_light_appearance(win)
    w = win.master
    while w is not None and not hasattr(w, "attach_menu"):
        w = getattr(w, "master", None)
    if w is not None:
        w.attach_menu(win)


class ChatPicker(tk.Toplevel):
    """Pick chats from WhatsApp, WhatsApp Business and Messages before an export."""

    def __init__(self, parent, lists: dict, preview=None):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        self.title("Choose chats to export")
        self.geometry("1040x660")
        self.minsize(820, 480)
        self.transient(parent)
        self.result = None
        head = tk.Frame(self, bg=GREEN)
        head.pack(fill="x")
        tk.Label(head, text="Choose the chats to export", bg=GREEN, fg="white",
                 font=font(17, "bold")).pack(side="left", padx=18, pady=12)
        tk.Label(head, text="Click a chat to preview it · tick the box to keep it", bg=GREEN, fg="#d7efe9",
                 font=font(12)).pack(side="left", pady=12)
        self.panel = ChatPanel(self, lists, preview)
        self.panel.pack(fill="both", expand=True)
        RoundButton(self.panel.foot, "Export selected", self._ok, "primary", 180, 40).pack(side="right")
        RoundButton(self.panel.foot, "Cancel", self._cancel, "secondary", 110, 40).pack(side="right", padx=10)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()

    # handy for tests and older callers
    def __getattr__(self, name):
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)

    def _ok(self):
        out = self.panel.selection()
        if out is None:
            return
        self.result = out
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self.worker.stop()
        self.destroy()


# ---------------------------------------------------------------------------
# Photo picker
# ---------------------------------------------------------------------------
class PhotoPanel(tk.Frame):
    """Photos month by month as thumbnails; click to select. Double-click opens a photo when
    on_open is given. Used by the export picker and by the phone window."""

    TILE = 128
    PAGE = 240

    def __init__(self, parent, source, items: list, select_all: bool = True, on_open=None):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        from photos import human_size
        self.human_size = human_size
        self.on_open = on_open
        self.source, self.items = source, items
        self.selected = {i.id for i in items} if select_all else set()
        self.images: dict = {}          # (item id, tile size) -> image
        self.paths: dict = {}           # item id -> its thumbnail file
        self.tiles: dict = {}
        self.worker = BgWorker(self)
        self.bind("<Destroy>", lambda e: self.worker.stop() if e.widget is self else None)
        self.months: dict[str, list] = {}
        for i in items:
            self.months.setdefault(i.month, []).append(i)
        self.month_keys = sorted(self.months, reverse=True)
        self.shown = 0
        self._more_btn = None

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(12, 6))
        RoundButton(bar, "Select all", lambda: self._set_all(True), "secondary", 110, 32, 12).pack(side="left")
        RoundButton(bar, "Select none", lambda: self._set_all(False), "secondary", 120, 32, 12).pack(side="left", padx=6)
        RoundButton(bar, "Select this month", lambda: self._set_month(True), "light", 160, 32, 12).pack(side="left", padx=(18, 0))
        RoundButton(bar, "Clear this month", lambda: self._set_month(False), "light", 150, 32, 12).pack(side="left", padx=6)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16)
        side = card(body)
        side.pack(side="left", fill="y")
        tk.Label(side, text="Months", bg=CARD, fg=MUTED, font=font(11, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        st = ttk.Style(self)                 # PhoneKeep's own colours (macOS dark mode drew this list black)
        st.configure("Months.Treeview", background=CARD, fieldbackground=CARD, foreground=INK, rowheight=28,
                     font=font(12))
        st.map("Months.Treeview", background=[("selected", GREEN_SOFT)], foreground=[("selected", INK)])
        st.configure("Months.Treeview", rowheight=26)
        self.mlist = ttk.Treeview(side, columns=("m", "n"), show="", selectmode="browse", height=18,
                                  style="Months.Treeview")
        self.mlist.column("m", width=128)
        self.mlist.column("n", width=64, anchor="e")
        self.mlist.tag_configure("year", font=font(12, "bold"), foreground=INK)
        self.mlist.tag_configure("month", foreground=INK)
        self.mlist.pack(fill="y", expand=True, padx=4, pady=4)
        self.mlist.bind("<<TreeviewSelect>>", lambda e: self._on_select())

        grid_frame = card(body)
        grid_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.canvas = tk.Canvas(grid_frame, bg=CARD, highlightthickness=0)
        gsb = ttk.Scrollbar(grid_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=gsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.gridf = tk.Frame(self.canvas, bg=CARD)
        self.canvas.create_window((0, 0), window=self.gridf, anchor="nw")
        self.gridf.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._laid_out = None          # (month, cols, shown) of the last layout: re-grid only when it changes,
        self.canvas.bind("<Configure>", lambda e: self._relayout())   # or a Configure storm can loop (macOS)
        wheel_scroll(self.canvas)          # wheel, Linux buttons and the Mac trackpad, over tiles too

        self.foot = tk.Frame(self, bg=BG)
        self.foot.pack(side="bottom", fill="x", padx=16, pady=12, before=body)
        self.count = tk.Label(self.foot, bg=BG, fg=INK, font=font(13))
        self.count.pack(side="left")

        self._fill_months()
        if self.month_keys:
            self.mlist.selection_set(self.month_keys[0])
        self._update_count()

    def _fill_months(self):
        """A line per year, its months under it by name, each with "selected/total" (owner, 13 Nov: "September 20…"
        was cut off). Rows are updated in place: deleting and re-inserting them re-selected the open month,
        which emptied the photo grid (13 Nov: Select none, then Select this month)."""
        years: dict = {}
        for m in self.month_keys:
            years.setdefault("Unknown" if m == "1970-01" else m[:4], []).append(m)
        for y, months in years.items():
            items = [i for m in months for i in self.months[m]]
            n_sel = sum(1 for i in items if i.id in self.selected)
            yid = f"year-{y}"
            yv = (y if y != "Unknown" else "Unknown date", f"{n_sel}/{len(items)}")
            if self.mlist.exists(yid):
                self.mlist.item(yid, values=yv)
            else:
                self.mlist.insert("", "end", iid=yid, values=yv, tags=("year",), open=True)
            for m in months:
                its = self.months[m]
                k = sum(1 for i in its if i.id in self.selected)
                label = "   " + (dt.datetime.strptime(m, "%Y-%m").strftime("%B") if m != "1970-01" else "No date")
                values = (label, f"{k}/{len(its)}")
                if self.mlist.exists(m):
                    self.mlist.item(m, values=values)
                else:
                    self.mlist.insert(yid, "end", iid=m, values=values, tags=("month",))

    def _on_select(self):
        sel = self.mlist.selection()
        if sel and sel[0].startswith("year-"):          # a year line opens its newest month
            kids = self.mlist.get_children(sel[0])
            if kids:
                self.mlist.selection_set(kids[0])
            return
        self._open_month()

    def _month(self) -> Optional[str]:
        s = self.mlist.selection()
        return s[0] if s and not s[0].startswith("year-") else None

    def _open_month(self):
        self.worker.clear()
        for w in self.gridf.winfo_children():
            w.destroy()
        self.tiles.clear()
        self.shown = 0
        self._laid_out = None          # new tiles: always place them
        self.canvas.yview_moveto(0)
        self._more()

    GAP = 6

    def _cols(self) -> int:
        return max(3, (self.canvas.winfo_width() - self.GAP) // (self.TILE + self.GAP))

    def _tile_size(self, cols: int) -> int:
        """Tiles grow so the columns fill the width exactly (owner, 13 Nov: white space on the right)."""
        return max(self.TILE, (self.canvas.winfo_width() - self.GAP * (cols + 1)) // cols)

    def _more(self):
        m = self._month()
        if not m:
            return
        items = self.months[m]
        start, end = self.shown, min(len(items), self.shown + self.PAGE)
        more_btn = getattr(self, "_more_btn", None)
        if more_btn is not None:
            more_btn.destroy()
            self._more_btn = None
        for item in items[start:end]:
            self._tile(item)
        self.shown = end
        if end < len(items):
            self._more_btn = RoundButton(self.gridf, f"Show {min(self.PAGE, len(items) - end)} more",
                                         self._more, "light", 200, 34, 12)
        self._relayout()

    def _tile(self, item):
        t = getattr(self, "tile", self.TILE)
        c = tk.Canvas(self.gridf, width=t, height=t, bg="#e9edef", highlightthickness=0, cursor="hand2")
        c.bind("<ButtonRelease-1>", lambda e, i=item: self._toggle(i))
        if self.on_open:
            c.bind("<Double-Button-1>", lambda e, i=item: self.on_open(i))
        self.tiles[item.id] = c
        self._draw_tile(item)
        if item.id in self.paths:
            return
        self.worker.submit(lambda i=item: self.source.thumbnail(i),
                           lambda path, i=item, m=self._month(): self._thumb_ready(i, path, m))

    def _thumb_ready(self, item, path, month):
        self.paths[item.id] = path
        if month == self._month() and item.id in self.tiles:
            self._draw_tile(item)

    def _draw_tile(self, item):
        c = self.tiles.get(item.id)
        if c is None:
            return
        c.delete("all")
        T = getattr(self, "tile", self.TILE)
        img = self.images.get((item.id, T))
        if img is None and self.paths.get(item.id):
            img = load_photo(self.paths[item.id], T, square=True)
            if img is not None:
                self.images[(item.id, T)] = img
        if img is not None:
            c.create_image(T // 2, T // 2, image=img)
        else:
            c.create_text(T // 2, T // 2 - 8, text="🎬" if item.video else "🖼", font=font(26))
            c.create_text(T // 2, T - 34 if item.video else T - 18, text=item.name[:16], fill=MUTED, font=font(9))
        if item.video:
            c.create_rectangle(4, T - 20, 30, T - 4, fill="#000000", outline="")
            c.create_text(17, T - 12, text="▶", fill="white", font=font(10))
        if item.live_video:
            c.create_rectangle(4, 4, 36, 20, fill="#000000", outline="")
            c.create_text(20, 12, text="LIVE", fill="white", font=font(8, "bold"))
        # selected: a blue frame, nothing else (owner, 13 Nov: no tick circle)
        if item.id in self.selected:
            c.create_rectangle(2, 2, T - 2, T - 2, outline=SELECT_BLUE, width=5)

    def _relayout(self):
        cols = self._cols()
        m = self._month()
        if not m:
            return
        tile = self._tile_size(cols)
        if tile != getattr(self, "tile", None):
            self.tile = tile
            self.images = {k: v for k, v in self.images.items() if k[1] == tile}     # drop other sizes
            for item in self.months[m][:self.shown]:
                c = self.tiles.get(item.id)
                if c is not None:
                    c.configure(width=tile, height=tile)
                    self._draw_tile(item)
        key = (m, cols, tile, self.shown, len(self.tiles))
        if key == getattr(self, "_laid_out", None):
            return
        self._laid_out = key
        r = 0
        for n, item in enumerate(self.months[m][:self.shown]):
            c = self.tiles.get(item.id)
            if c is not None:
                r, col = divmod(n, cols)
                c.grid(row=r, column=col, padx=(self.GAP, 0), pady=(self.GAP, 0))
        btn = getattr(self, "_more_btn", None)
        if btn is not None:
            btn.grid(row=r + 1, column=0, columnspan=cols, pady=12)

    def _toggle(self, item):
        self.selected.symmetric_difference_update({item.id})
        self._draw_tile(item)
        self._fill_months()
        self._update_count()

    def _set_all(self, on: bool):
        self.selected = {i.id for i in self.items} if on else set()
        for i in self.months.get(self._month(), []):
            self._draw_tile(i)
        self._fill_months()
        self._update_count()

    def _set_month(self, on: bool):
        for i in self.months.get(self._month(), []):
            (self.selected.add if on else self.selected.discard)(i.id)
            self._draw_tile(i)
        self._fill_months()
        self._update_count()

    def _update_count(self):
        chosen = [i for i in self.items if i.id in self.selected]
        size = sum(i.size for i in chosen)
        nv = sum(1 for i in chosen if i.video)
        n_p = len(chosen) - nv
        self.count.configure(text=f"{n_p:,} photo{'s' if n_p != 1 else ''} and {nv:,} video{'s' if nv != 1 else ''} "
                                  f"selected of {len(self.items):,} · about {self.human_size(size)}")


class PhotoPicker(tk.Toplevel):
    """Browse photos month by month as thumbnails and pick which to copy."""

    def __init__(self, parent, source, items: list):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        self.title("Choose photos & videos")
        self.geometry("1040x700")
        self.minsize(820, 520)
        self.transient(parent)
        self.result = None
        head = tk.Frame(self, bg=GREEN)
        head.pack(fill="x")
        tk.Label(head, text="Choose the photos & videos to keep", bg=GREEN, fg="white",
                 font=font(17, "bold")).pack(side="left", padx=18, pady=12)
        tk.Label(head, text=f"from {source.label} · click a photo to select or unselect it", bg=GREEN,
                 fg="#d7efe9", font=font(12)).pack(side="left", pady=12)
        self.panel = PhotoPanel(self, source, items)
        self.panel.pack(fill="both", expand=True)
        RoundButton(self.panel.foot, "Continue", self._ok, "primary", 160, 40).pack(side="right")
        RoundButton(self.panel.foot, "Skip photos", self._skip, "secondary", 130, 40).pack(side="right", padx=10)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.grab_set()

    def __getattr__(self, name):
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)

    def _ok(self):
        self.result = set(self.panel.selected)
        self._close()

    def _skip(self):
        self.result = set()
        self._close()

    def _close(self):
        self.worker.stop()
        self.destroy()


# ---------------------------------------------------------------------------
# Password dialogs (S1): choose a backup password, or enter the one the iPhone already uses
# ---------------------------------------------------------------------------

class PasswordDialog(tk.Toplevel):
    """One field with show/hide, a strength hint, and the line about the keychain.

    mode = "choose"  : a new password for a phone whose backups aren't encrypted yet.
                       The main button is the confirmation for writing to the phone ("Turn on encryption").
    mode = "enter"   : the password the iPhone already uses; offers the Reset All Settings help.
    mode = "confirm" : the current password, needed before turning encryption off.
    mode = "change"  : current + new password.
    Result: self.result = password (str), or (old, new) for "change", or None if cancelled.
    """

    TEXT = {
        "choose": ("Choose a backup password", "Turn on encryption",
                   "Your iPhone will encrypt its backups with this password."),
        "enter": ("Enter your backup password", "Continue",
                  "This iPhone already encrypts its backups. PhoneKeep needs the password once."),
        "confirm": ("Enter your backup password", "Turn off encryption",
                    "The iPhone needs the current password to turn encryption off."),
        "change": ("Change the backup password", "Change password",
                   "Your iPhone will switch its backups to the new password."),
    }

    def __init__(self, parent, mode: str = "choose", phone_name: str = "your iPhone",
                 keychain_available: bool = True, help_text: str = ""):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        import keychain as kc
        self.kc, self.mode, self.result = kc, mode, None
        title, verb, sub = self.TEXT[mode]
        self.title(f"{title} — {phone_name}")
        self.resizable(False, False)
        self.transient(parent)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(body, text="🔒", bg=CARD, font=font(28)).pack()
        tk.Label(body, text=title, bg=CARD, fg=INK, font=font(17, "bold")).pack(pady=(2, 4))
        tk.Label(body, text=sub, bg=CARD, fg=MUTED, font=font(12), wraplength=400, justify="center").pack()

        self.vars = []
        labels = ["Current password", "New password"] if mode == "change" else [""]
        for lab in labels:
            if lab:
                tk.Label(body, text=lab, bg=CARD, fg=INK, font=font(12), anchor="w").pack(fill="x", pady=(12, 2))
            row = tk.Frame(body, bg=CARD)
            row.pack(fill="x", pady=(14 if not lab else 0, 0))
            var = tk.StringVar()
            ent = ttk.Entry(row, textvariable=var, show="•", font=font(14), width=28)
            ent.pack(side="left", fill="x", expand=True, ipady=4)
            eye = tk.Label(row, text="Show", bg=CARD, fg=GREEN, font=font(11), cursor="hand2")
            eye.pack(side="left", padx=(8, 0))
            eye.bind("<Button-1>", lambda e, en=ent, ey=eye: self._toggle(en, ey))
            self.vars.append(var)
        self.entry_first = body.winfo_children()[-1].winfo_children()[0]

        self.hint = tk.Label(body, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.hint.pack(fill="x", pady=(4, 0))
        if mode in ("choose", "change"):
            self.vars[-1].trace_add("write", lambda *_: self._strength())
        note = ("Saved in your Keychain. You won't need to type it again.\nIf you forget it, the backup can't be opened."
                if sys.platform == "darwin" else
                "Saved in Windows Credential Manager. You won't need to type it again.\nIf you forget it, the backup can't be opened.")
        if not keychain_available:
            note = "This computer has no keychain, so PhoneKeep will ask for the password when it needs it.\nIf you forget it, the backup can't be opened."
        tk.Label(body, text=note, bg=CARD, fg=MUTED, font=font(11), justify="left", anchor="w").pack(fill="x", pady=(10, 0))
        if help_text:
            lk = tk.Label(body, text="I don't know the password", bg=CARD, fg=GREEN, font=font(11), cursor="hand2", anchor="w")
            lk.pack(fill="x", pady=(8, 0))
            lk.bind("<Button-1>", lambda e: messagebox.showinfo("Forgotten backup password", help_text, parent=self))

        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(18, 0))
        self.ok_btn = RoundButton(btns, verb, self._ok, "primary", 190, 40, bg=CARD)
        self.ok_btn.pack(side="right")
        RoundButton(btns, "Cancel", self._cancel, "secondary", 100, 40, bg=CARD).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.entry_first.focus_set()
        self.grab_set()

    def _toggle(self, ent, eye):
        showing = ent.cget("show") == ""
        ent.configure(show="•" if showing else "")
        eye.configure(text="Show" if showing else "Hide")

    def _strength(self):
        score, word = self.kc.strength(self.vars[-1].get())
        colour = {0: MUTED, 1: RED, 2: AMBER, 3: GREEN, 4: GREEN}[score]
        self.hint.configure(text=f"Strength: {word}" if word else "", fg=colour)

    def _ok(self):
        values = [v.get() for v in self.vars]
        if any(not v for v in values):
            self.hint.configure(text="Please type a password.", fg=RED)
            return
        if self.mode in ("choose", "change") and self.kc.strength(values[-1])[0] < 1:
            self.hint.configure(text="Use at least 8 characters.", fg=RED)
            return
        self.result = tuple(values) if self.mode == "change" else values[0]
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class TextDialog(tk.Toplevel):
    """One line of text with OK/Cancel, in PhoneKeep's own style (Tk's simpledialog misbehaves on macOS:
    it can come up behind the window, or not at all from a popup menu). Result: str, or None if cancelled."""

    def __init__(self, parent, title: str, prompt: str, initial: str = "", ok: str = "Save"):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(body, text=title, bg=CARD, fg=INK, font=font(17, "bold")).pack(pady=(2, 4))
        tk.Label(body, text=prompt, bg=CARD, fg=MUTED, font=font(12), wraplength=400, justify="center").pack()
        self.var = tk.StringVar(value=initial or "")
        self.entry = ttk.Entry(body, textvariable=self.var, font=font(14), width=32)
        self.entry.pack(fill="x", pady=(14, 0), ipady=4)
        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(18, 0))
        RoundButton(btns, ok, self._ok, "primary", 150, 40, bg=CARD).pack(side="right")
        RoundButton(btns, "Cancel", self._cancel, "secondary", 100, 40, bg=CARD).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.lift()
        self.grab_set()

    def _ok(self):
        self.result = self.var.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class DetailsDialog(tk.Toplevel):
    """'Show details': the technical text for support, in a window that is big enough to read and can be
    resized, scrolled and copied (13 Nov: the old message box was too small to show a traceback)."""

    def __init__(self, parent, text: str, title: str = "Details for support"):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        self.title(title)
        self.geometry("780x460")
        self.minsize(420, 240)
        self.transient(parent)
        top = tk.Frame(self, bg=CARD)
        top.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(top, text=title, bg=CARD, fg=INK, font=font(16, "bold")).pack(side="left")
        btns = tk.Frame(self, bg=CARD)
        btns.pack(side="bottom", fill="x", padx=20, pady=(8, 16))
        RoundButton(btns, "Close", self.destroy, "primary", 110, 36, bg=CARD).pack(side="right")
        self.copy_btn = RoundButton(btns, "Copy all", self.copy, "secondary", 120, 36, bg=CARD)
        self.copy_btn.pack(side="right", padx=8)
        box = tk.Frame(self, bg=CARD)
        box.pack(fill="both", expand=True, padx=20)
        bar = ttk.Scrollbar(box, orient="vertical")
        self.text = tk.Text(box, wrap="word", font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10),
                            bg="#f7f8fa", fg=INK, relief="flat", padx=10, pady=8, yscrollcommand=bar.set,
                            highlightthickness=1, highlightbackground=LINE)
        bar.configure(command=self.text.yview)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", text or "")
        self.text.configure(state="disabled")      # read-only, but text can still be selected and copied
        self.content = text or ""
        self.bind("<Escape>", lambda e: self.destroy())
        self.lift()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.content)
        self.copy_btn.configure_text("Copied ✓")


def show_details(parent, text: str):
    """Open the details window (not modal: the main window stays usable)."""
    return DetailsDialog(parent, text)


def ask_text(parent, title: str, prompt: str, initial: str = "", ok: str = "Save"):
    """Open a TextDialog and wait for it. Returns the text, or None if cancelled."""
    d = TextDialog(parent, title, prompt, initial, ok)
    parent.wait_window(d)
    return d.result


def ask_password(parent, mode: str, phone_name: str, help_text: str = ""):
    """Open a PasswordDialog and wait for it. Returns the result (see PasswordDialog)."""
    import keychain as kc
    d = PasswordDialog(parent, mode, phone_name, kc.available(), help_text)
    parent.wait_window(d)
    return d.result
