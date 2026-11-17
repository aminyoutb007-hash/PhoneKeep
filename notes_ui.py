"""D4: a note shown as on the phone, in the phone window's Notes screen (docs/spec/08-personal-data.md#d4-notes).

Headings, lists, checklists, monospaced text, bold / italic / underline / strikethrough and links get their own
look; images, drawings and scanned pages are drawn in the note (read from the backup into memory, scaled to the
pane); tables are drawn as a grid; audio, video, PDFs and other files are a line you click to open (the Q1 viewer).
Read-only: nothing here writes to the backup or the phone.
"""
from __future__ import annotations

import io
import tkinter as tk
from typing import Callable, Optional

import notes_doc
import theme
from ui import font

try:
    from PIL import Image, ImageTk
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
except Exception:                                   # pragma: no cover - Pillow is a dependency
    Image = ImageTk = None

IMAGE_MAX_W = 520
IMAGE_MAX_H = 640
INDENT = 22
LINE = 2_000              # characters on one line of the view: Tk lays out a long line slowly (one of 100,000: 4.5 s)
                          # but many short ones at once, so a longer paragraph gets a line break here (on screen only)
CELL = 2_000              # characters in one table cell drawn as a grid


def _broken(s: str, col: int = 0) -> tuple[str, int]:
    """`s` (no newlines) with a line break wherever its line would pass LINE characters, at a space if there's one
    near; and the column it ends at."""
    out = []
    while col + len(s) > LINE:
        cut = LINE - col
        space = s.rfind(" ", 0, cut)
        if space > cut // 2:
            cut = space + 1
        out.append(s[:cut] + "\n")
        s, col = s[cut:], 0
    out.append(s)
    return "".join(out), col + len(s)


def _lines(s: str) -> str:
    """Text with newlines, each line broken as _broken does."""
    return "\n".join(_broken(line)[0] for line in s.split("\n"))
ICON = {"audio": "🎤", "video": "🎬", "pdf": "📄", "scan": "📄", "file": "📎", "link": "🔗", "image": "🖼",
        "drawing": "✏️", "gallery": "🖼", "table": "▦"}


def picture(data: Optional[bytes], max_w: int = IMAGE_MAX_W, max_h: int = IMAGE_MAX_H):
    """A PIL image scaled to fit, or None."""
    if not data or Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        if im.format == "JPEG":
            im.draft("RGB", (max_w * 2, max_h * 2))
        im = im.convert("RGB")
        im.thumbnail((max_w, max_h))
        return im
    except Exception:
        return None


class NoteView:
    """Draws one note into a tk.Text. `read(domain, rel)` gives a backup file's bytes (None if it can't);
    `open_attachment(a)` opens a file attachment (the window's viewer). `submit(fn, ok)` runs fn in the background
    and ok(result) back on the UI thread (the window's backup runner): pictures are read and decoded there, never on
    the UI thread, and each goes into the note when it's ready. Without it they're read straight away (tests)."""

    CACHE = 48                                       # decoded pictures kept, by backup file
    MAX_CELLS = 400                                  # table cells drawn as a grid in one note: each is a widget,
                                                     # and Tk lays out many slowly (500: 0.6 s, 1,500: 17 s)
    MAX_TEXT_ROWS = 5_000                            # rows past the grid, shown as lines of text (cheap); the
                                                     # rest are in the note's PDF and text
    MAX_PICTURES = 150                               # pictures drawn in one note (each a background read and a
                                                     # picture on screen); the rest are in the note's PDF
    MAX_BLOCKS = 20_000                              # lines and attachments drawn in one note; the rest are in
                                                     # its PDF and text

    def __init__(self, txt: tk.Text, read: Callable, open_attachment: Callable[[dict], None],
                 submit: Optional[Callable] = None):
        self.txt, self.read, self.open_attachment = txt, read, open_attachment
        self.submit = submit or (lambda fn, ok: ok(fn()))
        self.gen = 0                                 # which note is shown: a picture for an earlier one is dropped
        self.pending = 0                             # pictures still being read for the note shown
        self.cache: dict = {}
        self.images: list = []                       # PhotoImages must outlive their place in the text
        self.tables: list[tk.Frame] = []
        self.shown: dict = {"images": 0, "tables": 0, "files": 0, "cells": 0, "text_rows": 0, "queued": 0,
                            "pictures_left": 0}
        ink, muted = theme.TEXT, theme.TEXT_2
        t = txt
        t.tag_configure("title", font=font(20, "bold"), spacing1=4, spacing3=8)
        t.tag_configure("heading", font=font(17, "bold"), spacing1=8, spacing3=4)
        t.tag_configure("subheading", font=font(15, "bold"), spacing1=6, spacing3=2)
        t.tag_configure("mono", font=("Menlo", 12) if t.tk.call("tk", "windowingsystem") == "aqua" else ("Consolas", 11))
        t.tag_configure("bold", font=font(13, "bold"))
        t.tag_configure("italic", font=font(13, "italic"))
        t.tag_configure("bolditalic", font=font(13, "bold italic"))
        t.tag_configure("underline", underline=True)
        t.tag_configure("strike", overstrike=True)
        t.tag_configure("link", foreground=theme.LINK, underline=True)
        t.tag_configure("box", foreground=theme.ACCENT, font=font(15))
        t.tag_configure("done", foreground=muted)
        t.tag_configure("meta", foreground=muted, font=font(11))
        t.tag_configure("file", foreground=theme.ACCENT, font=font(13))
        t.tag_configure("locked", foreground=muted, font=font(15), justify="center", spacing1=40)
        t.tag_configure("para", foreground=ink)
        self._indents: set = set()
        self._n = 0

    def _indent(self, n: int, hanging: bool) -> str:
        tag = f"ind{n}{'h' if hanging else ''}"
        if tag not in self._indents:
            first = INDENT * n
            self.txt.tag_configure(tag, lmargin1=first, lmargin2=first + (INDENT if hanging else 0))
            self._indents.add(tag)
        return tag

    def clear(self):
        for f in self.tables:
            f.destroy()
        self.images, self.tables = [], []
        self.shown = {"images": 0, "tables": 0, "files": 0, "cells": 0, "text_rows": 0, "queued": 0,
                      "pictures_left": 0}
        self.gen += 1
        self.pending = 0
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")

    def show(self, note: dict) -> None:
        self.clear()
        t = self.txt
        if note.get("locked"):
            t.insert("end", "🔒\nLocked on your iPhone\n", ("locked",))
            t.insert("end", "Open it on the iPhone with your Notes password.", ("locked", "meta"))
        elif note.get("blocks") is None:
            t.insert("end", _lines(note.get("text") or ""), ("para",))
        else:
            atts = note.get("attachments") or {}
            blocks = note["blocks"]
            for b in blocks[:self.MAX_BLOCKS]:
                if b["kind"] == "para":
                    self._para(b)
                else:
                    self._attachment(atts.get(b["id"]) or {"kind": "file", "name": "", "file": None})
            n = self.shown["pictures_left"]
            if n:
                t.insert("end", f"{n:,} more picture{'s' if n != 1 else ''}: save this note as PDF to see "
                                f"{'them' if n != 1 else 'it'}\n", ("meta",))
            if len(blocks) > self.MAX_BLOCKS:
                t.insert("end", f"This note goes on for {len(blocks) - self.MAX_BLOCKS:,} more lines: save it as "
                                f"PDF or text to see it all\n", ("meta",))
        t.configure(state="disabled")

    def _para(self, b: dict) -> None:
        t = self.txt
        style = b["style"]
        hanging = style in notes_doc.LISTS
        base = ["para", self._indent(b["indent"], hanging)]
        if style in ("title", "heading", "subheading", "mono"):
            base.append(style)
        if style == "check":
            t.insert("end", ("☑" if b["done"] else "☐") + " ", tuple(base + ["box"]))
        elif hanging:
            t.insert("end", notes_doc.prefix(b), tuple(base))
        col = 0
        for text, fmt, link in b["spans"]:
            text, col = _broken(text, col)
            tags = list(base)
            if "bold" in fmt and "italic" in fmt and style not in ("title", "heading", "subheading"):
                tags.append("bolditalic")
            elif "bold" in fmt and style not in ("title", "heading", "subheading"):
                tags.append("bold")
            elif "italic" in fmt:
                tags.append("italic")
            tags += [k for k in ("underline", "strike") if k in fmt]
            if link:
                tags.append("link")
            if style == "check" and b["done"]:
                tags.append("done")
            t.insert("end", text, tuple(tags))
        t.insert("end", "\n", tuple(base))

    def _image(self, a: dict, fallback: Optional[dict] = None) -> bool:
        """A picture's place in the note; it's read and decoded in the background and put there when ready (or,
        if it can't be, `fallback`'s line). False if there's no picture to read."""
        src = a.get("file") if a.get("kind") in ("image", "drawing") else None
        src = src or a.get("preview")
        if not src or ImageTk is None:
            return False
        if self.shown["queued"] >= self.MAX_PICTURES:       # said at the end of the note
            self.shown["pictures_left"] += 1
            return True
        self.shown["queued"] += 1
        self._n += 1
        mark = f"pic{self._n}"
        self.txt.mark_set(mark, "end-1c")
        self.txt.mark_gravity(mark, "left")
        self.txt.insert("end", "\n")
        gen, key = self.gen, tuple(src)
        self.pending += 1

        def load():
            if gen != self.gen:                      # another note is shown already: nothing to read
                return None
            if key in self.cache:
                return self.cache[key]
            try:
                im = picture(self.read(*key))
            except Exception:
                im = None
            if len(self.cache) >= self.CACHE:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = im
            return im

        def put(im):
            if gen != self.gen:                      # another note is shown now
                if mark in self.txt.mark_names():
                    self.txt.mark_unset(mark)
                return
            self.pending -= 1
            t = self.txt
            was = t.cget("state")
            t.configure(state="normal")
            if im is not None:
                ph = ImageTk.PhotoImage(im)
                self.images.append(ph)
                t.image_create(mark, image=ph, padx=2, pady=4)
                self.shown["images"] += 1
            elif fallback is not None:
                self._file_line(fallback, at=mark, newline=False)
            t.mark_unset(mark)
            t.configure(state=was)
        self.submit(load, put)
        return True

    def _table(self, rows: list[list[str]]) -> None:
        left = self.MAX_CELLS - self.shown["cells"]
        width = max((len(row) for row in rows), default=0)
        fit = min(len(rows), left // width) if width else len(rows)   # whole rows only, within the note's cells
        f = tk.Frame(self.txt, bg=theme.BORDER, bd=0)
        for r, row in enumerate(rows[:fit]):
            for c, cell in enumerate(row):
                tk.Label(f, text=cell if len(cell) <= CELL else cell[:CELL] + "…", bg=theme.CARD, fg=theme.TEXT, font=font(12, "bold" if r == 0 else "normal"),
                         anchor="nw", justify="left", wraplength=180, padx=6, pady=4
                         ).grid(row=r, column=c, sticky="nsew", padx=(0 if c else 1, 1), pady=(0 if r else 1, 1))
        self.shown["cells"] += sum(len(row) for row in rows[:fit])
        self.tables.append(f)
        if fit:
            self.txt.window_create("end", window=f, padx=2, pady=6)
            self.txt.insert("end", "\n")
        as_text = rows[fit:fit + max(0, self.MAX_TEXT_ROWS - self.shown["text_rows"])]   # the rest, as lines of text
        if as_text:
            self.txt.insert("end", _lines("\n".join("\t".join(r) for r in as_text)) + "\n", ("para", "mono"))
            self.shown["text_rows"] += len(as_text)
        rest = len(rows) - fit - len(as_text)
        if rest > 0:
            self.txt.insert("end", f"{rest:,} more row{'s' if rest != 1 else ''}: save this note as PDF or text to "
                                   f"see them all\n", ("meta",))
        self.shown["tables"] += 1

    def _file_line(self, a: dict, at: str = "end", newline: bool = True) -> None:
        t = self.txt
        kind = a.get("kind", "file")
        label = notes_doc.KIND_LABEL.get(kind, "File")
        name = a.get("name") or ""
        self._n += 1
        tag = f"att{self._n}"
        if kind == "link":                               # shown, never opened: PhoneKeep doesn't go online
            t.insert(at, f"{ICON['link']} {a.get('name') or ''}" + (f"  {a['url']}" if a.get("url") and
                                                                     a["url"] != a.get("name") else ""),
                     ("meta",))
        elif a.get("file"):
            t.tag_bind(tag, "<Button-1>", lambda e, a=a: self.open_attachment(a))
            t.tag_bind(tag, "<Enter>", lambda e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda e: t.configure(cursor=""))
            t.insert(at, f"{ICON.get(kind, '📎')} {label}{': ' + name if name and name != label else ''}  Open",
                     ("file", tag))
            self.shown["files"] += 1
        else:
            t.insert(at, f"{ICON.get(kind, '📎')} {label}{': ' + name if name else ''} "
                         f"({'not in the backup' if not a.get('file') else 'can’t be shown'})", ("meta",))
        if newline:
            t.insert(at, "\n")

    def _attachment(self, a: dict) -> None:
        kind = a.get("kind")
        if kind == "table" and a.get("rows"):
            self._table(a["rows"])
        elif kind == "gallery":
            pages = a.get("items") or []
            queued = sum(self._image(p, fallback=p) for p in pages)
            if not queued:
                self._file_line(a)
        elif kind in ("image", "drawing"):
            if not self._image(a, fallback=a):
                self._file_line(a)
        else:
            if kind in ("scan", "pdf", "video") and a.get("preview"):
                self._image({"kind": "preview", "preview": a["preview"]})
            self._file_line(a)
