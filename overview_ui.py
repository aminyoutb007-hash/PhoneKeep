"""V1 / V2 / V3 in the phone window: the strip of three cards on the home screen (this iPhone, battery,
storage) and the Battery and Storage screens they open. The values come from deviceinfo.Overview."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Optional

import deviceinfo as di
import ui
from ui import BG, CARD, INK, LINE, MUTED, RoundButton, font

GOOD, WARN, BAD = "#1f9d55", "#c77700", "#c0392b"


def _health_colour(h: Optional[int]) -> str:
    if h is None:
        return MUTED
    return GOOD if h >= 80 else WARN if h >= 70 else BAD


def _card(parent, title: str, on_click=None) -> tk.Frame:
    f = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, cursor="hand2" if on_click else "")
    tk.Label(f, text=title, bg=CARD, fg=MUTED, font=font(11, "bold"), anchor="w").pack(fill="x", padx=14, pady=(10, 2))
    if on_click:
        f.bind("<Button-1>", lambda e: on_click())
    return f


def _bind_all(w, fn):
    w.bind("<Button-1>", lambda e: fn())
    for c in w.winfo_children():
        _bind_all(c, fn)


def storage_bar(parent, ov: di.Overview, cats=None, width=300, height=12, bg=CARD) -> tk.Canvas:
    """Used / free as one bar; with categories, one coloured piece per category."""
    c = tk.Canvas(parent, width=width, height=height, bg=bg, highlightthickness=0)
    c.create_rectangle(0, 0, width, height, fill=di.CATEGORY_COLOURS["Free"], outline="")
    if ov.total:
        x = 0.0
        parts = cats if cats else [("Used", ov.used or 0, True)]
        for name, n, _exact in parts:
            if name == "Free":
                continue
            w = width * n / ov.total
            c.create_rectangle(x, 0, x + w, height, fill=di.CATEGORY_COLOURS.get(name, "#4f7cff"), outline="", tags=(name,))
            x += w
    return c


def cards(win, parent, ov: Optional[di.Overview], last_backup: str = "", problem: str = "") -> tk.Frame:
    """The strip on the phone window's home screen. ov=None: still reading (or `problem` says why not)."""
    strip = tk.Frame(parent, bg=BG)
    strip.columnconfigure((0, 1, 2), weight=1, uniform="ov")
    if ov is None:
        tk.Label(strip, text=problem or "Reading the iPhone's details…", bg=BG, fg=MUTED, font=font(12),
                 anchor="w").grid(row=0, column=0, columnspan=3, sticky="w")
        return strip

    # V1: this iPhone
    a = _card(strip, "THIS IPHONE")
    a.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    tk.Label(a, text=ov.model, bg=CARD, fg=INK, font=font(15, "bold"), anchor="w").pack(fill="x", padx=14)
    bits = [b for b in (ov.capacity_label(), ov.colour, f"iOS {ov.ios}" if ov.ios else "") if b]
    row = tk.Frame(a, bg=CARD)
    row.pack(fill="x", padx=14)
    if ov.colour_hex:
        sw = tk.Canvas(row, width=12, height=12, bg=CARD, highlightthickness=0)
        sw.create_oval(1, 1, 11, 11, fill=ov.colour_hex, outline=LINE)
        sw.pack(side="left", padx=(0, 6))
    tk.Label(row, text=" · ".join(bits), bg=CARD, fg=MUTED, font=font(12), anchor="w").pack(side="left")
    if ov.serial:
        s = tk.Label(a, text=f"Serial {ov.serial}  ⧉", bg=CARD, fg=MUTED, font=font(11), anchor="w", cursor="hand2")
        s.pack(fill="x", padx=14)
        s.bind("<Button-1>", lambda e: copy_serial(win, ov.serial, s))
        win.serial_label = s
    tk.Label(a, text=last_backup or "Not backed up yet", bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(
        fill="x", padx=14, pady=(0, 10))

    # V2: battery
    b = ov.battery
    bc = _card(strip, "BATTERY", lambda: battery_view(win, ov))
    bc.grid(row=0, column=1, sticky="nsew", padx=4)
    big = f"about {b.health}%" if b.health is not None else "—"
    tk.Label(bc, text=big, bg=CARD, fg=_health_colour(b.health), font=font(15, "bold"), anchor="w").pack(fill="x", padx=14)
    tk.Label(bc, text="health" + (f" · {b.cycles} charge cycles" if b.cycles is not None else ""), bg=CARD, fg=MUTED,
             font=font(12), anchor="w").pack(fill="x", padx=14)
    now = (f"Charge now {b.level}%" + (" · charging" if b.charging else "")) if b.level is not None else ""
    tk.Label(bc, text=now, bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(fill="x", padx=14)
    tk.Label(bc, text="Details ›", bg=CARD, fg=ui.SELECT_BLUE, font=font(11, "bold"), anchor="w").pack(fill="x", padx=14, pady=(0, 10))
    _bind_all(bc, lambda: battery_view(win, ov))

    # V3: storage
    sc = _card(strip, "STORAGE", lambda: storage_view(win, ov))
    sc.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
    tk.Label(sc, text=f"{di.human(ov.free)} free" if ov.free is not None else "—", bg=CARD, fg=INK,
             font=font(15, "bold"), anchor="w").pack(fill="x", padx=14)
    tk.Label(sc, text=f"{di.human(ov.used)} used of {ov.capacity_label() or di.human(ov.total)}" if ov.total else "",
             bg=CARD, fg=MUTED, font=font(12), anchor="w").pack(fill="x", padx=14)
    storage_bar(sc, ov, width=220, height=10).pack(anchor="w", padx=14, pady=(4, 2))
    tk.Label(sc, text="What's using it ›", bg=CARD, fg=ui.SELECT_BLUE, font=font(11, "bold"), anchor="w").pack(fill="x", padx=14, pady=(0, 10))
    _bind_all(sc, lambda: storage_view(win, ov))
    return strip


def copy_serial(win, serial: str, label=None):
    win.clipboard_clear()
    win.clipboard_append(serial)
    if label is not None:
        label.configure(text=f"Serial {serial}  ✓ copied")
        label.after(2000, lambda: label.winfo_exists() and label.configure(text=f"Serial {serial}  ⧉"))


def _header(win, title: str, sub: str = ""):
    top = tk.Frame(win.content, bg=BG)
    top.pack(fill="x", pady=(0, 10))
    RoundButton(top, "‹  Home", win.show_home, "secondary", 100, 32, 12).pack(side="left")
    tk.Label(top, text=title, bg=BG, fg=INK, font=font(19, "bold")).pack(side="left", padx=12)
    tk.Label(top, text=sub, bg=BG, fg=MUTED, font=font(12)).pack(side="left")


def _line(parent, label: str, value: str):
    r = tk.Frame(parent, bg=CARD)
    r.pack(fill="x", padx=18, pady=3)
    tk.Label(r, text=label, bg=CARD, fg=MUTED, font=font(12), width=22, anchor="w").pack(side="left")
    tk.Label(r, text=value, bg=CARD, fg=INK, font=font(12, "bold"), anchor="w").pack(side="left")


def battery_view(win, ov: di.Overview):
    win.current = "battery"
    win._clear()
    b = ov.battery
    _header(win, "Battery", ov.model)
    c = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    c.pack(fill="x")
    tk.Label(c, text=b.verdict(), bg=CARD, fg=_health_colour(b.health), font=font(17, "bold"), anchor="w",
             wraplength=640, justify="left").pack(fill="x", padx=18, pady=(16, 2))
    tk.Label(c, text=b.advice(), bg=CARD, fg=MUTED, font=font(12), anchor="w", wraplength=640,
             justify="left").pack(fill="x", padx=18, pady=(0, 10))
    _line(c, "Health", f"about {b.health}%" if b.health is not None else "not reported")
    _line(c, "Charge cycles", str(b.cycles) if b.cycles is not None else "not reported")
    _line(c, "Charge now", (f"{b.level}%" + ("  (charging)" if b.charging else "")) if b.level is not None else "not reported")
    if b.design_mah and b.full_mah:
        _line(c, "Full charge holds", f"{b.full_mah} mAh of {b.design_mah} mAh when new")
    if b.temperature is not None:
        _line(c, "Temperature", f"{b.temperature:.1f} °C")
    tk.Label(c, text="Settings → Battery → Battery Health works this out the same way; the two can differ by a point or two.",
             bg=CARD, fg=MUTED, font=font(11), anchor="w", wraplength=640, justify="left").pack(fill="x", padx=18, pady=(10, 4))
    RoundButton(c, "Save details…", lambda: save_details(win, ov), "secondary", 150, 34, 12).pack(anchor="w", padx=18, pady=(6, 16))


def save_details(win, ov: di.Overview, path: Optional[Path] = None) -> Optional[Path]:
    if path is None:
        p = filedialog.asksaveasfilename(parent=win, defaultextension=".json", initialfile=f"{ov.name} battery.json",
                                         filetypes=[("JSON", "*.json")])
        if not p:
            return None
        path = Path(p)
    path.write_text(di.details_json(ov), encoding="utf-8")
    return path


TIPS = {
    "Photos": "Open Photos to see what's there by month. Save what you want to keep before freeing space.",
    "Messages": "Big chats are usually the photos and videos in them. Open Messages to save them first.",
    "Apps": "The biggest are listed below. The iPhone can offload an app and keep its data.",
    "System": "iOS itself and its caches. This part can't be cleared from a computer.",
    "Other": "Caches, downloads and files kept by apps that aren't counted elsewhere.",
}


def storage_view(win, ov: di.Overview):
    win.current = "storage"
    win._clear()
    _header(win, "Storage", f"{ov.model} · {ov.capacity_label()}")
    cats = di.categories(ov, getattr(win, "photos_bytes", None), getattr(win, "messages_bytes", None))
    c = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    c.pack(fill="x")
    tk.Label(c, text=f"{di.human(ov.used)} used · {di.human(ov.free)} free", bg=CARD, fg=INK, font=font(17, "bold"),
             anchor="w").pack(fill="x", padx=18, pady=(16, 6))
    bar = storage_bar(c, ov, cats, width=640, height=16)
    bar.pack(anchor="w", padx=18)
    win.storage_rows = {}
    legend = tk.Frame(c, bg=CARD)
    legend.pack(fill="x", padx=18, pady=(10, 4))
    for name, n, exact in cats:
        r = tk.Frame(legend, bg=CARD, cursor="hand2" if name in ("Photos", "Messages") else "")
        r.pack(fill="x", pady=1)
        dot = tk.Canvas(r, width=12, height=12, bg=CARD, highlightthickness=0)
        dot.create_oval(1, 1, 11, 11, fill=di.CATEGORY_COLOURS[name], outline=LINE)
        dot.pack(side="left", padx=(0, 8))
        tk.Label(r, text=name, bg=CARD, fg=INK, font=font(12, "bold"), width=10, anchor="w").pack(side="left")
        tk.Label(r, text=("" if exact else "about ") + di.human(n), bg=CARD, fg=INK, font=font(12), width=14,
                 anchor="w").pack(side="left")
        tip = tk.Label(r, text=TIPS.get(name, ""), bg=CARD, fg=MUTED, font=font(11), anchor="w")
        tip.pack(side="left", fill="x", expand=True)
        if name in ("Photos", "Messages"):
            key = name.lower()
            r.open = lambda k=key: win.open_app(k)
            _bind_all(r, r.open)
        win.storage_rows[name] = r
    tk.Label(c, text="Free and the total are exact, from the iPhone. The rest are estimates: Apps from the sizes each app "
                     "reports, Photos and Messages from the latest backup.",
             bg=CARD, fg=MUTED, font=font(11), anchor="w", wraplength=640, justify="left").pack(fill="x", padx=18, pady=(6, 14))

    apps = ov.largest_apps(20)
    if apps:
        tk.Label(win.content, text="Largest apps", bg=BG, fg=INK, font=font(15, "bold"), anchor="w").pack(fill="x", pady=(14, 4))
        lst = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        lst.pack(fill="x")
        top = apps[0].total or 1
        win.app_rows = []
        lst.columnconfigure((0, 1), weight=1, uniform="apps")
        half = (len(apps) + 1) // 2                     # two columns of ten, so all 20 fit without scrolling
        for i, a in enumerate(apps):
            r = tk.Frame(lst, bg=CARD)
            r.grid(row=i % half, column=i // half, sticky="w", padx=14, pady=2)
            tk.Label(r, text=a.name, bg=CARD, fg=INK, font=font(12), width=20, anchor="w").pack(side="left")
            cv = tk.Canvas(r, width=90, height=8, bg=CARD, highlightthickness=0)
            cv.create_rectangle(0, 0, max(2, 90 * a.total / top), 8, fill=di.CATEGORY_COLOURS["Apps"], outline="")
            cv.pack(side="left", padx=8)
            tk.Label(r, text=di.human(a.total), bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(side="left")
            win.app_rows.append(a.name)
