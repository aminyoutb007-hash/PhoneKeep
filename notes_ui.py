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
    `open_attachment(a)` opens a file attachment (the window's viewer)."""

    def __init__(self, txt: tk.Text, read: Callable, open_attachment: Callable[[dict], None]):
        self.txt, self.read, self.open_attachment = txt, read, open_attachment
        self.images: list = []                       # PhotoImages must outlive their place in the text
        self.tables: list[tk.Frame] = []
        self.shown: dict = {"images": 0, "tables": 0, "files": 0}
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
        self.shown = {"images": 0, "tables": 0, "files": 0}
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")

    def show(self, note: dict) -> None:
        self.clear()
        t = self.txt
        if note.get("locked"):
            t.insert("end", "🔒\nLocked on your iPhone\n", ("locked",))
            t.insert("end", "Open it on the iPhone with your Notes password.", ("locked", "meta"))
        elif note.get("blocks") is None:
            t.insert("end", note.get("text") or "", ("para",))
        else:
            atts = note.get("attachments") or {}
            for b in note["blocks"]:
                if b["kind"] == "para":
                    self._para(b)
                else:
                    self._attachment(atts.get(b["id"]) or {"kind": "file", "name": "", "file": None})
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
        for text, fmt, link in b["spans"]:
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

    def _image(self, a: dict) -> bool:
        src = a.get("file") if a.get("kind") in ("image", "drawing") else None
        src = src or a.get("preview")
        im = picture(self.read(*src)) if src else None
        if im is None or ImageTk is None:
            return False
        ph = ImageTk.PhotoImage(im)
        self.images.append(ph)
        self.txt.image_create("end", image=ph, padx=2, pady=4)
        self.txt.insert("end", "\n")
        self.shown["images"] += 1
        return True

    def _table(self, rows: list[list[str]]) -> None:
        f = tk.Frame(self.txt, bg=theme.BORDER, bd=0)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                tk.Label(f, text=cell, bg=theme.CARD, fg=theme.TEXT, font=font(12, "bold" if r == 0 else "normal"),
                         anchor="nw", justify="left", wraplength=180, padx=6, pady=4
                         ).grid(row=r, column=c, sticky="nsew", padx=(0 if c else 1, 1), pady=(0 if r else 1, 1))
        self.tables.append(f)
        self.txt.window_create("end", window=f, padx=2, pady=6)
        self.txt.insert("end", "\n")
        self.shown["tables"] += 1

    def _file_line(self, a: dict) -> None:
        t = self.txt
        kind = a.get("kind", "file")
        label = notes_doc.KIND_LABEL.get(kind, "File")
        name = a.get("name") or ""
        self._n += 1
        tag = f"att{self._n}"
        if kind == "link":                               # shown, never opened: PhoneKeep doesn't go online
            t.insert("end", f"{ICON['link']} {a.get('name') or ''}" + (f"  {a['url']}" if a.get("url") and
                                                                        a["url"] != a.get("name") else ""),
                     ("meta",))
        elif a.get("file"):
            t.tag_bind(tag, "<Button-1>", lambda e, a=a: self.open_attachment(a))
            t.tag_bind(tag, "<Enter>", lambda e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda e: t.configure(cursor=""))
            t.insert("end", f"{ICON.get(kind, '📎')} {label}{': ' + name if name and name != label else ''}  Open",
                     ("file", tag))
            self.shown["files"] += 1
        else:
            t.insert("end", f"{ICON.get(kind, '📎')} {label}{': ' + name if name else ''} (not in the backup)",
                     ("meta",))
        t.insert("end", "\n")

    def _attachment(self, a: dict) -> None:
        kind = a.get("kind")
        if kind == "table" and a.get("rows"):
            self._table(a["rows"])
        elif kind == "gallery":
            pages = a.get("items") or []
            drawn = sum(self._image(p) for p in pages)
            if not drawn:
                self._file_line(a)
        elif kind in ("image", "drawing"):
            if not self._image(a):
                self._file_line(a)
        else:
            if kind in ("scan", "pdf", "video") and a.get("preview"):
                self._image({"kind": "preview", "preview": a["preview"]})
            self._file_line(a)
