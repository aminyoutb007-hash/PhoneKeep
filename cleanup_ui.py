"""C1 in the phone window: Photo clean-up (docs/spec/13-phone-health.md#c1-photo-clean-up-find-and-save).

Photos → Clean up: one screen of six cards, each with a count and the space it would free; a card's photos in
groups (Duplicates and Similar shots side by side, the suggested keeper marked Keep); Save to computer; then the
summary and the steps to remove them on the iPhone. What's found comes from cleanup.py; this only draws it.
"""
from __future__ import annotations

import datetime as dt
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional

import checkup_ui
import cleanup as cl
import quicklook
import theme
import ui
from ui import BG, CARD, GREEN, INK, LINE, MUTED, RED, SELECT_BLUE, RoundButton, font

TILE = 132
PAGE = 120                            # groups (or photos) shown at a time in a card
GROUPED = ("duplicates", "similar")   # cards shown as groups side by side


def size_text(n: float) -> str:
    """'8.4 GB', '640 MB': exact sizes of the files, in the units the iPhone uses."""
    if n >= 1000 ** 3:
        return f"{n / 1000 ** 3:.1f} GB"
    return f"{max(1, round(n / 1000 ** 2)):.0f} MB" if n else "0 MB"


def items_text(n: int) -> str:
    return f"{n:,} item{'s' if n != 1 else ''}"


class State:
    """One visit to Photo clean-up: the source, what was found, and what's ticked."""

    def __init__(self, win, src, items):
        self.win, self.src, self.items = win, src, items
        self.result: Optional[cl.Result] = None
        self.ticked: set = set()
        self.days = cl.SCREENSHOT_DAYS
        self.saved_ids = set(cl.load(checkup_ui.phone_dir(win))["saved"])
        self.runner = win.live_runner if getattr(src, "label", "") == "the iPhone" else win.backup_runner

    def totals(self) -> tuple:
        return self.result.total(self.ticked) if self.result else (0, 0)


def _top(win, back_text: str, back, title: str, sub: str = "") -> tk.Frame:
    top = tk.Frame(win.content, bg=BG)
    top.pack(fill="x", pady=(0, 10))
    RoundButton(top, back_text, back, "secondary", 130, 32, 12).pack(side="left")
    tk.Label(top, text=title, bg=BG, fg=INK, font=font(19, "bold")).pack(side="left", padx=12)
    win.view_sub = tk.Label(top, text=sub, bg=BG, fg=MUTED, font=font(12))
    win.view_sub.pack(side="left")
    return top


def back_to_photos(win, st: State):
    win.cleanup_cancel = None
    win._clear()
    win.current = "photos"
    win.view_header("photos")
    win.v_photos("photos", (st.src, st.items))


# -- 1. working it out ---------------------------------------------------------------------------------------------
def view(win, src, items, card: Optional[str] = None, st: Optional[State] = None):
    """Open Photo clean-up for these photos (card: open that card straight away, e.g. "videos" from the Storage
    card). The analysis runs in the background with a progress line and Cancel."""
    st = st or State(win, src, items)
    win.cleanup = st
    win.current = "cleanup:working"
    win._clear()
    _top(win, "‹  Photos", lambda: (cancel.set(), back_to_photos(win, st)), "Photo clean-up")
    box = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    box.pack(fill="x")
    line = tk.Label(box, text=f"Looking at {len(items):,} photos and videos…", bg=CARD, fg=INK, font=font(14),
                    anchor="w")
    line.pack(fill="x", padx=18, pady=(18, 6))
    bar = ttk.Progressbar(box, mode="determinate", maximum=1, length=520)
    bar.pack(anchor="w", padx=18)
    tk.Label(box, text="Everything is worked out on this computer. Nothing is sent anywhere.", bg=CARD, fg=MUTED,
             font=font(11), anchor="w").pack(fill="x", padx=18, pady=(8, 0))
    cancel = threading.Event()
    win.cleanup_cancel = cancel
    RoundButton(box, "Cancel", lambda: (cancel.set(), back_to_photos(win, st)), "secondary", 100, 34, 12).pack(
        anchor="w", padx=18, pady=(12, 18))
    last = [0.0]

    def progress(done, total):                    # from the worker threads: hand over to the window, now and then
        if done == total or done - last[0] >= max(1, total // 200):
            last[0] = done
            st.runner.on_ui(lambda: show_progress(done, total))

    def show_progress(done, total):
        if win.current == "cleanup:working" and line.winfo_exists():
            line.configure(text=f"Looking at your photos: {done:,} of {total:,} to measure…")
            bar.configure(maximum=max(1, total), value=done)

    def ok(r):
        if r is None or cancel.is_set():
            return
        st.result = r
        st.ticked = set().union(*(c.ticked() for c in r.cards))
        win.cleanup_result = r
        if card:
            card_view(win, st, card)
        else:
            cards(win, st)

    def err(e):
        if win.current == "cleanup:working":
            win.failed(box, e, ("Try again", lambda: view(win, src, items, card, st)))
    st.runner.submit(lambda: cl.analyse(src, items, checkup_ui.phone_dir(win), progress=progress, cancel=cancel,
                                        screenshot_days=st.days), ok, err)


# -- 2. the cards ---------------------------------------------------------------------------------------------------
def cards(win, st: State):
    r = st.result
    win.current = "cleanup"
    win._clear()
    took = ("from PhoneKeep's last look" if r.measured == 0 else
            f"in {r.seconds:.0f} s" if r.seconds < 90 else f"in {r.seconds / 60:.0f} min")
    _top(win, "‹  Photos", lambda: back_to_photos(win, st), "Photo clean-up",
         f"{len(st.items):,} photos and videos from {st.src.label}, {took}")
    grid = tk.Frame(win.content, bg=BG)
    grid.pack(fill="x")
    win.cleanup_cards = {}
    for n, c in enumerate(r.cards):
        box = tk.Frame(grid, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        box.grid(row=n // 2, column=n % 2, sticky="nsew", padx=(0, 10), pady=(0, 10))
        grid.columnconfigure(n % 2, weight=1, uniform="card")
        tk.Label(box, text=c.title, bg=CARD, fg=INK, font=font(15, "bold"), anchor="w").pack(fill="x", padx=16,
                                                                                             pady=(14, 0))
        tk.Label(box, text=c.finds, bg=CARD, fg=MUTED, font=font(11), anchor="w", justify="left",
                 wraplength=330).pack(fill="x", padx=16)
        if c.key == "screenshots":
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=16, pady=(4, 0))
            tk.Label(row, text="Older than", bg=CARD, fg=INK, font=font(11)).pack(side="left")
            days = tk.Spinbox(row, from_=1, to=3650, width=5, font=font(11))
            days.delete(0, "end")
            days.insert(0, str(st.days))
            days.pack(side="left", padx=4)
            tk.Label(row, text="days", bg=CARD, fg=INK, font=font(11)).pack(side="left")
            RoundButton(row, "Apply", lambda d=days: set_days(win, st, d.get()), "light", 70, 26, 11).pack(
                side="left", padx=6)
        if c.count:
            text = f"{items_text(c.count)} · {size_text(c.space)}"
            tk.Label(box, text=text, bg=CARD, fg=INK, font=font(17, "bold"), anchor="w").pack(fill="x", padx=16,
                                                                                              pady=(8, 0))
            tk.Label(box, text=c.suggested, bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(fill="x", padx=16)
            ticked = len(c.ticked() & st.ticked)
            tk.Label(box, text=f"{ticked:,} ticked to save and remove" if ticked else "None ticked yet", bg=CARD,
                     fg=INK if ticked else MUTED, font=font(11), anchor="w").pack(fill="x", padx=16)
            RoundButton(box, "Review ›", lambda k=c.key: card_view(win, st, k), "secondary", 110, 32, 12).pack(
                anchor="w", padx=16, pady=(8, 0))
        else:
            tk.Label(box, text="Nothing found", bg=CARD, fg=MUTED, font=font(14), anchor="w").pack(fill="x", padx=16,
                                                                                                   pady=(8, 0))
        if c.note:
            tk.Label(box, text=c.note, bg=CARD, fg=MUTED, font=font(10), anchor="w", justify="left",
                     wraplength=330).pack(fill="x", padx=16, pady=(6, 0))
        tk.Frame(box, bg=CARD, height=14).pack()
        win.cleanup_cards[c.key] = box
    out = []
    if r.left_out.get("hidden"):
        n = r.left_out["hidden"]
        out.append(f"{n:,} hidden photo{'s' if n != 1 else ''} (they stay behind Hidden)")
    if r.left_out.get("icloud"):
        n = r.left_out["icloud"]
        out.append(f"{n:,} only in iCloud (they can't be saved from here)")
    if out:
        tk.Label(win.content, text="Left out: " + " and ".join(out) + ". Favourites and photos in albums are never "
                 "suggested.", bg=BG, fg=MUTED, font=font(11), anchor="w", justify="left", wraplength=720).pack(
            fill="x", pady=(2, 0))
    _foot(win, st)


def set_days(win, st: State, value: str):
    try:
        st.days = max(1, min(3650, int(value)))
    except ValueError:
        return
    view(win, st.src, st.items, st=st)            # measured photos come from the cache: this is quick


def _foot(win, st: State, refresh=None):
    foot = tk.Frame(win.content, bg=BG)
    foot.pack(fill="x", side="bottom", pady=(10, 0))
    n, space = st.totals()
    btn = RoundButton(foot, f"Save to computer ({items_text(n)}, {size_text(space)})", lambda: save(win, st),
                      "primary", 380, 40, 13)
    btn.pack(side="right")
    tk.Label(foot, text="PhoneKeep can't remove photos from the iPhone yet. After saving, it shows the steps to "
             "remove them on the phone.", bg=BG, fg=MUTED, font=font(11), justify="left", wraplength=360).pack(
        side="right", padx=12)
    win.cleanup_button = btn
    return btn


# -- 3. one card ---------------------------------------------------------------------------------------------------
def card_view(win, st: State, key: str, page: int = 0):
    r = st.result
    c = r.card(key)
    win.current = f"cleanup:{key}"
    win._clear()
    top = _top(win, "‹  Clean-up", lambda: cards(win, st), c.title)

    def count_line():
        mine = {i.id for i in c.candidates()}
        n, space = r.total(st.ticked & mine)
        win.view_sub.configure(text=f"{items_text(c.count)} · {n:,} ticked ({size_text(space)}) · {c.suggested}")
    count_line()

    def tick_all(on: bool):
        ids = {i.id for i in c.candidates()}
        st.ticked = (st.ticked | ids) if on else (st.ticked - ids)
        card_view(win, st, key, page)
    RoundButton(top, "Untick all", lambda: tick_all(False), "light", 100, 30, 11).pack(side="right")
    RoundButton(top, "Tick all", lambda: tick_all(True), "light", 90, 30, 11).pack(side="right", padx=6)
    tk.Label(win.content, text="Click a photo to tick or untick it. Space: preview.", bg=BG, fg=MUTED,
             font=font(11), anchor="w").pack(fill="x")
    foot_holder = {}

    def changed():
        count_line()
        n, space = st.totals()
        foot_holder["btn"].configure_text(f"Save to computer ({items_text(n)}, {size_text(space)})")

    foot_holder["btn"] = _foot(win, st)              # packed first, so a short window can't squeeze it out
    outer = tk.Frame(win.content, bg=BG)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
    sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=BG)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window(0, 0, window=inner, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    ui.wheel_scroll(canvas)
    worker = ui.BgWorker(inner)
    inner.bind("<Destroy>", lambda e: worker.stop() if e.widget is inner else None)
    images, tiles = {}, {}
    cursor = {"item": None, "list": []}

    def preview():
        shown = cursor["list"]
        if not shown:
            return
        idx = shown.index(cursor["item"]) if cursor["item"] in shown else 0
        quicklook.Viewer(win, [quicklook.Item(i.name, read=lambda i=i: st.src.read(i.id),
                                              to_file=lambda d, i=i: st.src.copy(i.id, d), size=i.size,
                                              kind="video" if i.video else "") for i in shown], idx)
    win.cleanup_preview = preview

    def draw(tile, item, group):
        tile.delete("all")
        img = images.get(item.id)
        if img is not None:
            tile.create_image(TILE // 2, TILE // 2, image=img)
        else:
            tile.create_rectangle(0, 0, TILE, TILE, fill=theme.TILE_BG, outline="")
            tile.create_text(TILE // 2, TILE // 2, text="▶" if item.video else "🖼", font=font(24), fill=MUTED)
        if item.video:
            tile.create_rectangle(4, TILE - 20, 30, TILE - 4, fill=theme.BADGE_BG, outline="")
            tile.create_text(17, TILE - 12, text="▶", fill=theme.ON_DARK, font=font(10))
        if item.live_video:
            tile.create_rectangle(4, 4, 36, 20, fill=theme.BADGE_BG, outline="")
            tile.create_text(20, 12, text="LIVE", fill=theme.ON_DARK, font=font(8, "bold"))
        if item.id in group.locked:
            label = "★ Favourite" if item.favorite else "In an album"
            tile.create_rectangle(TILE - 82, TILE - 22, TILE - 4, TILE - 4, fill=theme.BADGE_GREY, outline="")
            tile.create_text(TILE - 43, TILE - 13, text=label, fill=theme.ON_DARK, font=font(9, "bold"))
        elif item.id not in st.ticked and (item.id in group.keep or key in GROUPED):
            tile.create_rectangle(TILE - 50, TILE - 22, TILE - 4, TILE - 4, fill=GREEN, outline="")
            tile.create_text(TILE - 27, TILE - 13, text="Keep", fill=theme.ON_DARK, font=font(10, "bold"))
        if item.id in st.saved_ids:
            tile.create_rectangle(TILE - 58, 4, TILE - 4, 20, fill=theme.CARD, outline="")
            tile.create_text(TILE - 31, 12, text="Saved ✓", fill=GREEN, font=font(9, "bold"))
        if item.id in st.ticked:
            tile.create_rectangle(2, 2, TILE - 2, TILE - 2, outline=SELECT_BLUE, width=5)

    def toggle(item, group):
        cursor["item"] = item
        if item.id in group.locked:
            return
        st.ticked ^= {item.id}
        draw(tiles[item.id], item, group)
        changed()
    win.cleanup_toggle = lambda item_id: next(toggle(i, g) for g in c.groups for i in g.items if i.id == item_id)

    def tile_for(parent, item, group):
        cell = tk.Frame(parent, bg=BG)
        t = tk.Canvas(cell, width=TILE, height=TILE, bg=theme.TILE_BG, highlightthickness=0, cursor="hand2")
        t.pack()
        t.bind("<ButtonRelease-1>", lambda e: (t.focus_set(), toggle(item, group)))
        t.bind("<space>", lambda e: (cursor.update(item=item), preview(), "break")[2])
        note = group.notes.get(item.id, "")
        sub = " · ".join(x for x in (note, size_text(st.result.space_of(item)), _day(item)) if x)
        tk.Label(cell, text=sub, bg=BG, fg=MUTED, font=font(9), wraplength=TILE).pack()
        tiles[item.id] = t
        cursor["list"].append(item)
        draw(t, item, group)

        def ready(path, item=item, t=t):
            img = ui.load_photo(path, TILE, square=True)
            if img is not None and t.winfo_exists():
                images[item.id] = img
                draw(t, item, group)
        worker.submit(lambda i=item: st.src.thumbnail(i), ready)
        return cell

    groups = c.groups[page * PAGE:(page + 1) * PAGE]
    if key in GROUPED:
        for n, g in enumerate(groups):
            row = tk.Frame(inner, bg=BG)
            row.pack(fill="x", pady=(8, 0), anchor="w")
            what = "Copies" if key == "duplicates" else "Similar shots"
            tk.Label(row, text=f"{what}: {len(g.items)} · {_day(g.items[0])}", bg=BG, fg=INK, font=font(11, "bold"),
                     anchor="w").pack(fill="x")
            strip = tk.Frame(row, bg=BG)
            strip.pack(fill="x", anchor="w")
            for k, item in enumerate(g.items[:12]):
                tile_for(strip, item, g).grid(row=0, column=k, padx=(0, 8), sticky="n")
    else:
        flat = tk.Frame(inner, bg=BG)
        flat.pack(fill="x", anchor="w", pady=(8, 0))
        cols = 6
        for n, g in enumerate(groups):
            tile_for(flat, g.items[0], g).grid(row=n // cols, column=n % cols, padx=(0, 8), pady=(0, 8), sticky="n")
    if len(c.groups) > (page + 1) * PAGE:
        RoundButton(inner, f"Next {min(PAGE, len(c.groups) - (page + 1) * PAGE)} ›",
                    lambda: card_view(win, st, key, page + 1), "light", 140, 32, 12).pack(anchor="w", pady=10)
    if page:
        RoundButton(inner, "‹ Previous", lambda: card_view(win, st, key, page - 1), "light", 140, 32, 12).pack(
            anchor="w", pady=(0, 10))


def _day(item) -> str:
    try:
        return f"{item.when.day} {item.when:%b %Y}" if item.when.year > 1970 else ""
    except (AttributeError, ValueError):
        return ""


# -- 4. saving and the steps on the iPhone --------------------------------------------------------------------------
def save(win, st: State, folder=None):
    r = st.result
    chosen = [r.items[i] for i in sorted(st.ticked) if i in r.items]
    if not chosen:
        from tkinter import messagebox
        messagebox.showinfo("PhoneKeep", "Tick the photos to save first: open a card with Review.", parent=win)
        return
    if folder is None:
        folder = win.out_dir("photos")
        if folder is None:
            return
    win.current = "cleanup:saving"
    win._clear()
    _top(win, "‹  Clean-up", lambda: (cancel.set(), cards(win, st)), "Photo clean-up")
    box = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    box.pack(fill="x")
    line = tk.Label(box, text=f"Saving {items_text(len(chosen))} to {folder}…", bg=CARD, fg=INK, font=font(14),
                    anchor="w")
    line.pack(fill="x", padx=18, pady=(18, 6))
    bar = ttk.Progressbar(box, mode="determinate", maximum=len(chosen), length=520)
    bar.pack(anchor="w", padx=18)
    tk.Label(box, text="Each file is checked against the iPhone's copy after it's written.", bg=CARD, fg=MUTED,
             font=font(11), anchor="w").pack(fill="x", padx=18, pady=(8, 0))
    cancel = threading.Event()
    RoundButton(box, "Stop", lambda: cancel.set(), "secondary", 100, 34, 12).pack(anchor="w", padx=18, pady=(12, 18))

    def progress(done, total):
        st.runner.on_ui(lambda: line.winfo_exists() and (
            line.configure(text=f"Saving: {done:,} of {total:,}…"), bar.configure(value=done)))

    def ok(res):
        st.saved_ids |= {s.item.id for s in res.saved}
        win.cleanup_saved = res
        summary(win, st, res, folder)

    def err(e):
        win.failed(box, e, ("Try again", lambda: save(win, st, folder)))
    st.runner.submit(lambda: cl.save(st.src, chosen, folder, checkup_ui.phone_dir(win), progress, cancel), ok, err)


def summary(win, st: State, res: cl.SaveResult, folder):
    r = st.result
    win.current = "cleanup:done"
    win._clear()
    _top(win, "‹  Clean-up", lambda: cards(win, st), "Photo clean-up")
    box = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    box.pack(fill="x")
    n = len(res.saved)
    tk.Label(box, text=f"Saved {items_text(n)} to your archive.", bg=CARD, fg=INK, font=font(19, "bold"),
             anchor="w").pack(fill="x", padx=18, pady=(16, 2))
    tk.Label(box, text=str(folder), bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(fill="x", padx=18)
    size_only = len(res.saved) - len(res.verified)
    if size_only:
        tk.Label(box, text=f"{size_only:,} very large file{'s were' if size_only != 1 else ' was'} checked by size "
                 "only, so they aren't listed below for removal.", bg=CARD, fg=INK, font=font(12), anchor="w",
                 justify="left", wraplength=700).pack(fill="x", padx=18, pady=(6, 0))
    if res.failed:
        tk.Label(box, text=f"{len(res.failed):,} couldn't be saved:", bg=CARD, fg=RED, font=font(12, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(8, 0))
        for item, why in res.failed[:10]:
            tk.Label(box, text=f"•  {item.name}: {why}", bg=CARD, fg=INK, font=font(11), anchor="w").pack(fill="x",
                                                                                                         padx=18)
        if len(res.failed) > 10:
            tk.Label(box, text=f"…and {len(res.failed) - 10:,} more", bg=CARD, fg=MUTED, font=font(11),
                     anchor="w").pack(fill="x", padx=18)
    ok = res.verified
    if ok:
        _n, space = r.total(s.item.id for s in ok)
        tk.Label(box, text=f"To free {size_text(space)}, remove them on the iPhone", bg=CARD, fg=INK,
                 font=font(15, "bold"), anchor="w").pack(fill="x", padx=18, pady=(16, 2))
        tk.Label(box, text="Each one listed here is in the archive, its checksum matching the iPhone's copy. "
                 "PhoneKeep can't remove photos from the iPhone yet.", bg=CARD, fg=MUTED, font=font(11), anchor="w",
                 justify="left", wraplength=700).pack(fill="x", padx=18)
        card_of = {}
        for c in reversed(r.cards):           # an item on several cards goes with the first one
            for i in c.candidates():
                card_of[i.id] = c.key
        win.cleanup_steps = cl.removal_steps(ok, card_of)
        for head, text in win.cleanup_steps:
            tk.Label(box, text=head, bg=CARD, fg=INK, font=font(12, "bold"), anchor="w").pack(fill="x", padx=18,
                                                                                              pady=(8, 0))
            tk.Label(box, text=text, bg=CARD, fg=INK, font=font(12), anchor="w", justify="left",
                     wraplength=700).pack(fill="x", padx=18)
        warn = cl.ICLOUD_WARNING if r.icloud else "If iCloud Photos is on: " + cl.ICLOUD_WARNING[0].lower() + \
            cl.ICLOUD_WARNING[1:]
        tk.Label(box, text="⚠  " + warn, bg=CARD, fg=INK, font=font(12, "bold"), anchor="w", justify="left",
                 wraplength=700).pack(fill="x", padx=18, pady=(14, 0))
    row = tk.Frame(box, bg=CARD)
    row.pack(fill="x", padx=18, pady=(16, 18))
    from phone import reveal
    import sys
    RoundButton(row, "Show in Finder" if sys.platform == "darwin" else "Show folder", lambda: reveal(folder),
                "primary", 160, 36, 12).pack(side="left")
    RoundButton(row, "Back to clean-up", lambda: cards(win, st), "secondary", 160, 36, 12).pack(side="left", padx=8)
