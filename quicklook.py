"""Q1: quick preview everywhere (docs/spec/11-previews.md#q1-quick-preview-everywhere).

Select something and press Space: a large preview opens over the window. The arrow keys move to the
next or previous item, and Space or Esc closes it.

What's shown, and where the bytes go:
  * images (HEIC too), text and PDFs are shown from memory: nothing decrypted is written to disk for them.
    PDFs are drawn by macOS itself (Quartz) on a Mac; on Windows a PDF opens in the PDF app from the private
    folder below, because Tk can't draw one.
  * video and audio need a file to play: they are copied to a private folder (only the user can read it),
    played by the computer's own player (QuickTime Player on a Mac), and the folder is deleted when
    PhoneKeep closes and again at the next start in case it crashed.

An Item is the name plus how to get the content: read() → bytes for what is shown from memory,
to_file(dest) → bool for what has to be played from a file. The caller provides both (from a backup, or
from the phone over the cable), so this module knows nothing about where things come from.
"""
from __future__ import annotations

import io
import os
import plistlib
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    from PIL import Image, ImageOps, ImageTk
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
except Exception:  # no Pillow: images show as a card with an Open button
    Image = None

IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff", ".dng"}
VIDEO = {".mov", ".mp4", ".m4v", ".3gp", ".avi", ".webm"}
AUDIO = {".m4a", ".mp3", ".aac", ".wav", ".caf", ".amr", ".opus", ".ogg", ".m4r", ".aiff", ".flac"}
TEXT = {".txt", ".csv", ".json", ".log", ".md", ".vcf", ".ics", ".xml", ".plist", ".html", ".htm", ".rtf", ".strings"}
PDF = {".pdf"}
MAX_MEMORY = 200 * 1024 * 1024        # bigger than this is played from a file, never held in memory
MAX_TEXT = 300_000                     # characters shown for a text file
BG, FG, MUTED = "#1c1c1e", "#f2f2f7", "#a1a1aa"


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    for kind, exts in (("image", IMAGE), ("video", VIDEO), ("audio", AUDIO), ("pdf", PDF), ("text", TEXT)):
        if ext in exts:
            return kind
    return "other"


@dataclass
class Item:
    name: str
    read: Optional[Callable[[], Optional[bytes]]] = None      # for images, text and PDFs
    to_file: Optional[Callable[[Path], bool]] = None          # for video, audio and anything else
    size: Optional[int] = None
    kind: str = ""
    why: Optional[Callable[[], Optional[str]]] = None         # why it couldn't be read, for the message

    def __post_init__(self):
        self.kind = self.kind or kind_of(self.name)


# -- the private folder for things that must be played from a file ------------------------------------------------
def _dir_path() -> Path:
    try:
        who = os.getlogin()
    except Exception:
        who = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return Path(tempfile.gettempdir()) / f"phonekeep-previews-{who}"


def private_dir() -> Path:
    """A folder only this user can read, inside the computer's temporary folder."""
    d = _dir_path()
    d.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def cleanup() -> None:
    """Delete everything previews left behind (called when PhoneKeep closes and when it starts)."""
    shutil.rmtree(_dir_path(), ignore_errors=True)


def play(path: Path) -> None:
    """The computer's own player (QuickTime Player on a Mac, with its scrubber)."""
    try:
        if sys.platform == "darwin":
            # the Mac's own app for it (QuickTime Player for video and audio). Not qlmanage: it's a debugging
            # tool and crashed on macOS 26 (owner's Mac, 14 Nov).
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# -- turning bytes into something to show --------------------------------------------------------------------------
def text_of(data: bytes, name: str) -> str:
    if Path(name).suffix.lower() == ".plist" or data[:6] == b"bplist":
        try:
            import pprint
            return pprint.pformat(plistlib.loads(data), width=100)
        except Exception:
            pass
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            t = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        t = data.decode("utf-8", "replace")
    return t[:MAX_TEXT] + ("\n\n… (the rest isn't shown in the preview)" if len(t) > MAX_TEXT else "")


def image_of(data: bytes, box: tuple[int, int]):
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail(box)
        return im.convert("RGB")


def pdf_pages(data: bytes, width: int, max_pages: int = 12) -> Optional[list]:
    """The first pages of a PDF as images, drawn in memory by macOS. None where that isn't possible."""
    if sys.platform != "darwin" or Image is None:
        return None
    try:
        import Quartz
        from Foundation import NSData
        doc = Quartz.CGPDFDocumentCreateWithProvider(
            Quartz.CGDataProviderCreateWithCFData(NSData.dataWithBytes_length_(data, len(data))))
        if doc is None:
            return None
        out = []
        for n in range(1, min(Quartz.CGPDFDocumentGetNumberOfPages(doc), max_pages) + 1):
            page = Quartz.CGPDFDocumentGetPage(doc, n)
            box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFCropBox)
            scale = width / max(1.0, box.size.width)
            w, h = int(box.size.width * scale), int(box.size.height * scale)
            ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
                                               Quartz.kCGImageAlphaPremultipliedLast)
            Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
            Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
            Quartz.CGContextScaleCTM(ctx, scale, scale)
            Quartz.CGContextTranslateCTM(ctx, -box.origin.x, -box.origin.y)
            Quartz.CGContextDrawPDFPage(ctx, page)
            img = Quartz.CGBitmapContextCreateImage(ctx)
            raw = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
            out.append(Image.frombuffer("RGBA", (w, h), bytes(raw), "raw", "RGBA",
                                        Quartz.CGImageGetBytesPerRow(img), 1).convert("RGB"))
        return out
    except Exception:
        return None


def human(n: Optional[int]) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


# -- the viewer -------------------------------------------------------------------------------------------------------
class Viewer(tk.Toplevel):
    """The preview over the window. One at a time: opening another replaces it."""
    current: Optional["Viewer"] = None

    def __init__(self, parent: tk.Misc, items: list[Item], index: int = 0, on_close: Callable = None):
        if Viewer.current is not None:
            try:
                Viewer.current.close()
            except tk.TclError:
                pass
        top = parent.winfo_toplevel()
        super().__init__(top, bg=BG)
        Viewer.current = self
        self.items, self.index, self.on_close = items, max(0, min(index, len(items) - 1)), on_close
        self.title("Preview")
        self.transient(top)
        top.update_idletasks()
        w, h = max(700, int(top.winfo_width() * 0.86)), max(500, int(top.winfo_height() * 0.86))
        x = top.winfo_rootx() + (top.winfo_width() - w) // 2
        y = top.winfo_rooty() + (top.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.box = (w - 60, h - 120)
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=16, pady=(10, 4))
        self.close_lbl = tk.Label(head, text="✕", bg=BG, fg=FG, font=("Helvetica", 16), cursor="hand2")
        self.close_lbl.pack(side="right")
        self.close_lbl.bind("<Button-1>", lambda e: self.close())
        self.name_lbl = tk.Label(head, text="", bg=BG, fg=FG, font=("Helvetica", 14, "bold"), anchor="w")
        self.name_lbl.pack(side="left")
        self.pos_lbl = tk.Label(head, text="", bg=BG, fg=MUTED, font=("Helvetica", 12))
        self.pos_lbl.pack(side="left", padx=12)
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=16)
        tk.Label(self, text="←  →  next and previous  ·  Space or Esc to close", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(pady=(4, 10))
        for k in ("<Escape>", "<space>"):
            self.bind(k, lambda e: self.close())
        for k in ("<Right>", "<Down>"):
            self.bind(k, lambda e: self.move(1))
        for k in ("<Left>", "<Up>"):
            self.bind(k, lambda e: self.move(-1))
        self.bind("<Return>", lambda e: self.shown_kind == "play" and self.open_from_file())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._jobs: queue.Queue = queue.Queue()
        self._done: queue.Queue = queue.Queue()
        self._alive = True
        self._gen = 0
        self.shown_kind = ""          # what's on screen now: image / text / pdf / play / card / loading / error
        self._imgs = []
        threading.Thread(target=self._work, daemon=True).start()
        self._poll()
        self.show()
        self.focus_force()

    # background loading -------------------------------------------------------------------------------------------
    def _work(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            gen, fn = job
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001 - shown in the preview
                res, err = None, e
            self._done.put((gen, res, err))

    def _poll(self):
        if not self._alive:
            return
        try:
            while True:
                gen, res, err = self._done.get_nowait()
                if gen == "played":
                    self._played(res, err)
                elif gen == self._gen:
                    self._render(res, err)
        except queue.Empty:
            pass
        self.after(40, self._poll)

    # showing -------------------------------------------------------------------------------------------------------
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._imgs = []
        self.status = None

    def move(self, step: int):
        if not self.items:
            return
        self.index = (self.index + step) % len(self.items)
        self.show()

    def show(self):
        it = self.items[self.index]
        self._gen += 1
        gen = self._gen
        self.name_lbl.configure(text=it.name)
        self.pos_lbl.configure(text=f"{self.index + 1} of {len(self.items)}" + (f" · {human(it.size)}" if it.size else ""))
        self._clear()
        self.shown_kind = "loading"
        tk.Label(self.body, text="Loading…", bg=BG, fg=MUTED, font=("Helvetica", 14)).pack(expand=True)
        box = self.box

        def load():
            in_memory = it.kind in ("image", "text", "pdf") and it.read is not None and (it.size or 0) <= MAX_MEMORY
            if in_memory:
                data = it.read()
                if data is None:
                    why = getattr(it, "why", None)
                    why = why() if callable(why) else why
                    raise FileNotFoundError("PhoneKeep couldn't read it from the iPhone or the backup."
                                            + (f"\n({why})" if why else ""))
                if it.kind == "image" and Image is not None:
                    return "image", image_of(data, box)
                if it.kind == "text":
                    return "text", text_of(data, it.name)
                if it.kind == "pdf":
                    pages = pdf_pages(data, min(box[0] - 30, 900))
                    if pages:
                        return "pdf", pages
            if it.kind in ("video", "audio", "pdf", "other", "image") and it.to_file is not None:
                return "file", None          # played / opened from the private folder when asked
            return "card", None
        self._jobs.put((gen, load))

    def _render(self, res, err):
        self._clear()
        it = self.items[self.index]
        if err is not None:
            self.shown_kind = "error"
            tk.Label(self.body, text=f"Couldn't preview {it.name}.\n{err}", bg=BG, fg="#ff6b6b",
                     font=("Helvetica", 13), justify="center", wraplength=600).pack(expand=True)
            return
        kind, value = res
        if kind == "image":
            self.shown_kind = "image"
            img = ImageTk.PhotoImage(value)
            self._imgs.append(img)
            tk.Label(self.body, image=img, bg=BG).pack(expand=True)
        elif kind == "text":
            self.shown_kind = "text"
            t = tk.Text(self.body, wrap="word", bg="#2c2c2e", fg=FG, insertbackground=FG, relief="flat",
                        font=("Menlo" if sys.platform == "darwin" else "Consolas", 12), padx=14, pady=10)
            t.insert("1.0", value)
            t.configure(state="disabled")
            t.pack(fill="both", expand=True)
            self.text_widget = t
        elif kind == "pdf":
            self.shown_kind = "pdf"
            cv = tk.Canvas(self.body, bg=BG, highlightthickness=0)
            sb = tk.Scrollbar(self.body, orient="vertical", command=cv.yview)
            cv.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            cv.pack(fill="both", expand=True)
            y = 0
            for page in value:
                img = ImageTk.PhotoImage(page)
                self._imgs.append(img)
                cv.create_image(self.box[0] // 2, y, image=img, anchor="n")
                y += page.size[1] + 12
            cv.configure(scrollregion=(0, 0, self.box[0], y))
            cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        else:
            self.shown_kind = "play" if kind == "file" else "card"
            icon = {"video": "🎬", "audio": "🎵", "pdf": "📄", "image": "🖼"}.get(it.kind, "📎")
            tk.Label(self.body, text=icon, bg=BG, fg=FG, font=("Helvetica", 54)).pack(pady=(70, 6))
            tk.Label(self.body, text=it.name, bg=BG, fg=FG, font=("Helvetica", 15, "bold")).pack()
            if kind == "file":
                verb = "Play" if it.kind in ("video", "audio") else "Open"
                b = tk.Label(self.body, text=f"▶  {verb}" if verb == "Play" else "Open", bg="#0a84ff", fg="white",
                             font=("Helvetica", 14, "bold"), padx=22, pady=8, cursor="hand2")
                b.pack(pady=16)
                b.bind("<Button-1>", lambda e: self.open_from_file())
                self.status = tk.Label(self.body, text="", bg=BG, fg=MUTED, font=("Helvetica", 11))
                self.status.pack()
                tk.Label(self.body, text=("Plays in QuickTime Player." if sys.platform == "darwin" else
                                          "Opens in the computer's own app.") +
                         " A private copy is kept only until PhoneKeep closes.",
                         bg=BG, fg=MUTED, font=("Helvetica", 11)).pack()
            else:
                tk.Label(self.body, text="No preview for this kind of item. Save it to open it.", bg=BG, fg=MUTED,
                         font=("Helvetica", 12)).pack(pady=10)

    def open_from_file(self, wait: bool = False) -> Optional[Path]:
        """Copy the item to the private folder (in the background) and play / open it there.
        wait=True copies right away and returns the path (used by the tests)."""
        it = self.items[self.index]
        dest = private_dir() / f"{self.index}-{Path(it.name).name}"

        def copy():
            ok = dest.exists() and dest.stat().st_size > 0
            if not ok and it.to_file is not None:
                ok = bool(it.to_file(dest))
            if not ok:
                return None
            try:
                os.chmod(dest, 0o600)
            except OSError:
                pass
            play(dest)
            return dest
        if wait:
            return copy()
        if getattr(self, "status", None) is not None:
            self.status.configure(text="Copying…")
        gen = self._gen

        threading.Thread(target=lambda: self._done.put(("played", gen, copy())), daemon=True).start()
        return None

    def _played(self, gen, path):
        if gen != self._gen or not self._alive or getattr(self, "status", None) is None:
            return
        try:
            self.status.configure(text="" if path else "Couldn't copy it from the iPhone or the backup.")
        except tk.TclError:
            pass

    def close(self):
        self._alive = False
        self._jobs.put(None)
        if Viewer.current is self:
            Viewer.current = None
        try:
            self.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()


def bind_space(widget: tk.Misc, make: Callable[[], Optional[tuple[list[Item], int]]]) -> None:
    """Space (and Return on lists) on `widget` previews: make() gives (items, index) for the current selection."""
    def go(_e=None):
        got = make()
        if got and got[0]:
            Viewer(widget, got[0], got[1], on_close=lambda: _refocus(widget))
        return "break"
    widget.bind("<space>", go)
    widget.quick_preview = go


def _refocus(w):
    try:
        w.focus_set()
    except tk.TclError:
        pass
