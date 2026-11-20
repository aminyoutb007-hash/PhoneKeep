"""Q4: the storage map. What fills the iPhone as coloured blocks, each as big as the space it takes, that can be
clicked into: Photos → Videos → the largest videos; Apps → the largest apps; Messages → its attachments.

Read-only: the figures are the Storage screen's (V3: free and the total from the iPhone, the rest PhoneKeep's own
estimates) and, below the first level, the newest backup's file list. Nothing is asked of the phone."""
from __future__ import annotations

import datetime as dt
import tkinter as tk
import tkinter.font as tkfont
from pathlib import PurePosixPath
from typing import Callable, Optional

import deviceinfo as di
import theme
import ui
from ui import BG, CARD, INK, LINE, MUTED, RoundButton, font

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi"}
PHOTO_EXT = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".gif", ".dng", ".tif", ".tiff", ".webp", ".raw"}
MOST_VIDEOS = 30            # the largest videos each get a block; the rest share one
MOST_APPS = 20


class Block:
    """One block of the map. `open` is the key of the level it opens, or a function, or None."""

    def __init__(self, name: str, size: int, colour: str, sub: str = "", open=None, exact: bool = False):
        self.name, self.size, self.colour, self.sub, self.open, self.exact = name, size, colour, sub, open, exact

    def size_text(self) -> str:
        return ("" if self.exact else "about ") + di.human(self.size)


# -- the layout: squarified treemap (Bruls, Huizing, van Wijk 2000) -------------------------------------------------
def squarify(sizes: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Rectangles (x, y, w, h) filling the box, one per size (largest first works best), each with an area in
    proportion to its size and as close to square as the row allows."""
    total = sum(sizes)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0) for _ in sizes]
    scale = w * h / total
    areas = [s * scale for s in sizes]
    out: list[tuple[float, float, float, float]] = []
    i = 0

    def worst(row, side):
        s = sum(row)
        if s <= 0 or side <= 0:
            return float("inf")
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) if r > 0 else float("inf")
                   for r in row)
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        j = i + 1
        while j < len(areas) and worst(row + [areas[j]], side) <= worst(row, side):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if w >= h:                                  # a column on the left
            cw = s / h if h else 0
            yy = y
            for a in row:
                rh = a / cw if cw else 0
                out.append((x, yy, cw, rh))
                yy += rh
            x, w = x + cw, w - cw
        else:                                       # a row along the top
            rh = s / w if w else 0
            xx = x
            for a in row:
                rw = a / rh if rh else 0
                out.append((xx, y, rw, rh))
                xx += rw
            y, h = y + rh, h - rh
        i = j
    return out


# -- what's in each level -------------------------------------------------------------------------------------------
def _kind(rel: str) -> str:
    ext = PurePosixPath(rel).suffix.lower()
    return "video" if ext in VIDEO_EXT else "photo" if ext in PHOTO_EXT else "other"


def media_sizes(file_meta: Callable[[str, str], dict]) -> dict:
    """From the backup's file list (BackupData.file_meta): what Photos and Messages hold, by kind.
    {"photos": {"video": n, "photo": n, "other": n}, "videos": [(name, size, mtime)] biggest first,
     "messages": {"video": n, "photo": n, "other": n, "history": n}}"""
    photos = {"video": 0, "photo": 0, "other": 0}
    videos = []
    for rel, (_fid, mtime, size) in file_meta("CameraRollDomain", "Media/DCIM/").items():
        k = _kind(rel)
        photos[k] += size or 0
        if k == "video":
            videos.append((PurePosixPath(rel).name, size or 0, mtime))
    videos.sort(key=lambda v: -v[1])
    msgs = {"video": 0, "photo": 0, "other": 0, "history": 0}
    for rel, (_fid, _m, size) in file_meta("MediaDomain", "Library/SMS/Attachments/").items():
        msgs[_kind(rel)] += size or 0
    msgs["history"] = sum((m[2] or 0) for m in file_meta("HomeDomain", "Library/SMS/").values())
    return {"photos": photos, "videos": videos, "messages": msgs}


def _date(mtime) -> str:
    try:
        d = dt.datetime.fromtimestamp(float(mtime)) if mtime else None
        return f"{d.day} {d:%b %Y}" if d else ""
    except (OverflowError, OSError, ValueError):
        return ""


def levels(ov: di.Overview, cats: list, media: Optional[dict]) -> dict[str, tuple[str, list[Block]]]:
    """key -> (title, blocks, biggest first). "top" is the whole iPhone; the others open from it. Blocks under
    a size of 0 are left out."""
    col = di.CATEGORY_COLOURS
    top = []
    for name, n, exact in cats:
        if not n:
            continue
        opens = {"Photos": "photos", "Apps": "apps", "Messages": "messages"}.get(name)
        if opens in ("photos", "messages") and not media:     # what's inside them comes from the backup
            opens = None
        top.append(Block(name, n, col[name], open=opens, exact=exact))
    out = {"top": ("iPhone", sorted(top, key=lambda b: -b.size))}

    apps = ov.largest_apps(MOST_APPS)
    rest = [a for a in sorted(ov.apps, key=lambda a: -a.total)][MOST_APPS:]
    blocks = [Block(a.name, a.total, theme.storage_shade(col["Apps"], i, len(apps) + 1)) for i, a in enumerate(apps)
              if a.total]
    if sum(a.total for a in rest):
        blocks.append(Block(f"{len(rest)} other apps", sum(a.total for a in rest),
                            theme.storage_shade(col["Apps"], len(apps), len(apps) + 1)))
    out["apps"] = ("Apps", blocks)

    if media:
        p = media["photos"]
        shade = lambda i: theme.storage_shade(col["Photos"], i, 3)
        vids = media["videos"]
        pb = [Block("Videos", p["video"], shade(0), f"{len(vids)} videos", open="videos" if vids else None),
              Block("Photos", p["photo"], shade(1)),
              Block("Edits and other files", p["other"], shade(2))]
        out["photos"] = ("Photos", sorted((b for b in pb if b.size), key=lambda b: -b.size))
        big = vids[:MOST_VIDEOS]
        vb = [Block(name, size, theme.storage_shade(col["Photos"], i, len(big) + 1), _date(mtime), open="cleanup")
              for i, (name, size, mtime) in enumerate(big) if size]
        small = vids[MOST_VIDEOS:]
        if sum(v[1] for v in small):
            vb.append(Block(f"{len(small)} smaller videos", sum(v[1] for v in small),
                            theme.storage_shade(col["Photos"], len(big), len(big) + 1), open="cleanup"))
        out["videos"] = ("Videos", vb)
        m = media["messages"]
        shade = lambda i: theme.storage_shade(col["Messages"], i, 4)
        mb = [Block("Videos sent and received", m["video"], shade(0)),
              Block("Photos sent and received", m["photo"], shade(1)),
              Block("Other attachments", m["other"], shade(2)),
              Block("The messages themselves", m["history"], shade(3))]
        out["messages"] = ("Messages", sorted((b for b in mb if b.size), key=lambda b: -b.size))
    return out


PATH = {"top": (), "photos": ("top",), "apps": ("top",), "messages": ("top",), "videos": ("top", "photos")}
NOTES = {
    "top": "Free and the total are exact, from the iPhone. The rest are estimates, as on the Storage screen. "
           "Click a block with › to see what's in it.",
    "photos": "From the newest backup: photos kept only in iCloud aren't counted.",
    "videos": "The largest videos first. Click one to review them in Photo clean-up, where they can be saved "
              "to this computer.",
    "apps": "Each app with its documents and data, as the iPhone reports it.",
    "messages": "From the newest backup: Messages' attachments, and its history of texts.",
}


# -- the screen -----------------------------------------------------------------------------------------------------
def view(win, ov: di.Overview, key: str = "top", again: bool = False):
    """The map, at level `key`. Below the first level it needs the backup's file list, read in the background.
    again=True (opened from Storage): a list that couldn't be read last time is tried once more."""
    if again:
        win.map_failed = None
    win.current = "storagemap"
    win._clear()
    win.map_key = key
    cats = di.categories(ov, getattr(win, "photos_bytes", None), getattr(win, "messages_bytes", None))
    top = tk.Frame(win.content, bg=BG)
    top.pack(fill="x", pady=(0, 10))
    import overview_ui                              # here: it opens the map too
    RoundButton(top, "‹  Storage", lambda: overview_ui.storage_view(win, win.overview or ov), "secondary", 110, 32,
                12).pack(side="left")
    tk.Label(top, text="Storage map", bg=BG, fg=INK, font=font(19, "bold")).pack(side="left", padx=12)
    tk.Label(top, text=f"{di.human(ov.used)} used · {di.human(ov.free)} free" if ov.total else "",
             bg=BG, fg=MUTED, font=font(12)).pack(side="left")

    media = win.map_media[1] if getattr(win, "map_media", None) and win.map_media[0] is win.data else None
    failed = getattr(win, "map_failed", None)
    failed = failed[1] if failed and failed[0] is getattr(win, "data", None) else None
    if media is None and failed is None and getattr(win, "data", None) is not None:
        _read_media(win, ov, key)
    lv = levels(ov, cats, media)
    if key not in lv:
        key = "top"
    title, blocks = lv[key]

    crumbs = tk.Frame(win.content, bg=BG)
    crumbs.pack(fill="x", pady=(0, 6))
    win.map_crumbs = []
    for n, k in enumerate(PATH[key] + (key,)):
        if n:
            tk.Label(crumbs, text="›", bg=BG, fg=MUTED, font=font(13)).pack(side="left", padx=4)
        here = k == key
        lab = tk.Label(crumbs, text=lv[k][0] if k in lv else k, bg=BG, fg=INK if here else theme.ACCENT,
                       font=font(13, "bold" if here else "normal"), cursor="" if here else "hand2")
        lab.pack(side="left")
        if not here:
            lab.bind("<Button-1>", lambda e, k=k: view(win, win.overview or ov, k))
        win.map_crumbs.append(lab.cget("text"))

    note = NOTES.get(key, "")
    if key == "top" and any(n is None for _c, n, _e in cats):
        note += (f" {di.SYSTEM_UNKNOWN} can't be estimated on this iPhone (the app sizes it reports overlap with "
                 "it), so it isn't on the map and the blocks add up to less than the whole iPhone.")
    if key in ("top", "apps") and ov.apps_updating:
        note += " The iPhone is still sending app sizes, so Apps and Other change as they come in."
    if key == "top" and failed:
        note += f" {failed}"
    elif key == "top" and media is None and getattr(win, "data", None) is not None:
        note += " Reading the backup for what's inside Photos and Messages…"
    elif key == "top" and getattr(win, "data", None) is None:
        note += " Photos and Messages open once there's a backup."
    win.map_note = tk.Label(win.content, text=note, bg=BG, fg=MUTED, font=font(11), anchor="w", justify="left",
                            wraplength=640)
    win.map_note.pack(fill="x", pady=(0, 8))

    box = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    box.pack(fill="both", expand=True)
    canvas = tk.Canvas(box, bg=CARD, highlightthickness=0, height=360)
    canvas.pack(fill="both", expand=True, padx=8, pady=8)
    win.map_canvas = canvas
    win.map_blocks = blocks
    hover = tk.Label(win.content, text=" ", bg=BG, fg=INK, font=font(12), anchor="w")
    hover.pack(fill="x", pady=(6, 0))
    win.map_hover = hover

    def act(b: Block):
        if b.open == "cleanup":
            import checkup_ui
            checkup_ui.open_cleanup(win, "videos")
        elif b.open:
            view(win, win.overview or ov, b.open)

    win.map_open = lambda name: act(next(b for b in blocks if b.name == name))

    def describe(b: Block) -> str:
        total = sum(x.size for x in blocks) or 1
        bits = [b.name, b.size_text(), f"{100 * b.size / total:.0f}%"]
        if b.sub:
            bits.insert(2, b.sub)
        return " · ".join(bits) + ("  ›" if b.open else "")

    bold, plain = tkfont.Font(font=font(12, "bold")), tkfont.Font(font=font(11))
    small = tk.Frame(win.content, bg=BG)          # blocks too small to carry their name: named here, under the map

    def fit(text: str, f: tkfont.Font, room: float) -> str:
        """The text on one line in `room` pixels, cut with "…" if it's longer; "" if not even that fits."""
        if f.measure(text) <= room:
            return text
        while text and f.measure(text + "…") > room:
            text = text[:-1]
        return text + "…" if len(text) >= 3 else ""

    def draw(_e=None):
        canvas.delete("all")
        for w in small.winfo_children():
            w.destroy()
        win.map_unnamed = []
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 20 or h < 20:
            return
        if not blocks:
            canvas.create_text(w / 2, h / 2, text="Nothing to show here yet.", fill=MUTED, font=font(13))
            return
        rects = squarify([b.size for b in blocks], 0, 0, w, h)
        win.map_rects = []
        for i, (b, (x, y, rw, rh)) in enumerate(zip(blocks, rects)):
            tag = f"b{i}"
            # a 2 px gap of the card's colour between blocks
            canvas.create_rectangle(x + 1, y + 1, x + rw - 1, y + rh - 1, fill=b.colour, outline=CARD, width=2,
                                    tags=(tag,))
            ink = theme.ink_on(b.colour)
            name = fit(b.name + ("  ›" if b.open and b.open != "cleanup" else ""), bold, rw - 16) if rh > 30 else ""
            if name:
                canvas.create_text(x + 8, y + 7, anchor="nw", text=name, fill=ink, font=font(12, "bold"), tags=(tag,))
                size = fit(b.size_text(), plain, rw - 16) if rh > 50 else ""
                if size:
                    canvas.create_text(x + 8, y + 27, anchor="nw", text=size, fill=ink, font=font(11), tags=(tag,))
            else:
                win.map_unnamed.append(b.name)
            win.map_rects.append((b.name, x, y, rw, rh))
            canvas.tag_bind(tag, "<Enter>", lambda e, b=b: hover.configure(text=describe(b)))
            canvas.tag_bind(tag, "<Leave>", lambda e: hover.configure(text=" "))
            if b.open:
                canvas.tag_bind(tag, "<Enter>", lambda e, b=b: (hover.configure(text=describe(b)),
                                                                canvas.configure(cursor="hand2")), add="+")
                canvas.tag_bind(tag, "<Leave>", lambda e: canvas.configure(cursor=""), add="+")
                canvas.tag_bind(tag, "<Button-1>", lambda e, b=b: act(b))
        # named under the map, with their size (the biggest of them; the hover line has every one)
        shown = [b for b in blocks if b.name in win.map_unnamed][:6]
        if shown:
            tk.Label(small, text="Also:", bg=BG, fg=MUTED, font=font(11)).pack(side="left")
        for b in shown:
            lab = tk.Label(small, text=f"{b.name} · {b.size_text()}" + ("  ›" if b.open else ""), bg=BG,
                           fg=theme.ACCENT if b.open else MUTED, font=font(11), cursor="hand2" if b.open else "")
            lab.pack(side="left", padx=(8, 0))
            if b.open:
                lab.bind("<Button-1>", lambda e, b=b: act(b))
    canvas.bind("<Configure>", draw)
    small.pack(fill="x", pady=(6, 0))

    win.map_lines = [describe(b) for b in blocks]
    if key == "videos":
        RoundButton(win.content, "Review in Photo clean-up", lambda: act(Block("", 0, "", open="cleanup")),
                    "secondary", 220, 32, 12).pack(anchor="w", pady=(8, 0))


def _read_media(win, ov, key):
    """The backup's Photos and Messages by kind, once per opened backup; the map is drawn again when it's in."""
    data = win.data
    if getattr(win, "map_reading", None) is data:
        return
    win.map_reading = data

    def ok(m):
        if data is not win.data:
            return
        win.map_media = (data, m)               # for this backup only: another one is read again
        win.map_reading = None
        if win.current == "storagemap" and win.overview is not None:
            view(win, win.overview, getattr(win, "map_key", "top"))

    def err(_e):
        win.map_reading = None
        if data is not win.data:
            return
        # said once, not tried again by itself (that would loop); opening the map from Storage tries again
        win.map_failed = (data, "The backup's list of files couldn't be read, so what's inside Photos and Messages "
                                "can't be shown. Open the map again from Storage to try again.")
        if win.current == "storagemap" and win.overview is not None:
            view(win, win.overview, getattr(win, "map_key", "top"))
    win.backup_runner.submit(lambda: media_sizes(data.file_meta), ok, err)
