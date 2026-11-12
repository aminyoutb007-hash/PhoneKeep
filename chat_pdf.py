"""M3: chats to PDF (docs/spec/06-messages.md#m3-chats-to-pdf-and-print).

The PDF looks like the phone: your messages in green bubbles on the right, the other side's in white
bubbles on the left, sender names in groups, a day line between days, photos inline (scaled to fit),
videos and voice notes as labelled tiles, colour emoji, Arabic shaped and laid out right to left.
Every page carries the chat name and date range at the top and "Page N of M" at the bottom.

Pure Python (ReportLab + Pillow), with the fonts shipped in assets/fonts so the output is the same on
every computer: DejaVu Sans (Latin, Arabic and most symbols) and Noto Color Emoji (each emoji is drawn
once to a small PNG and placed inline).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Callable, Iterable, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - Pillow is a dependency
    Image = None

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
FONTS = HERE / "assets" / "fonts"

INK = colors.HexColor("#111b21")
MUTED = colors.HexColor("#667781")
GREEN = colors.HexColor("#008069")
ME = colors.HexColor("#d9fdd3")
THEM = colors.white
BORDER = colors.HexColor("#d1d7db")
DAY_BG = colors.HexColor("#e9edef")
SYS = colors.HexColor("#8a6d1d")

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
BODY_W = PAGE_W - 2 * MARGIN
BUBBLE_MAX = BODY_W * 0.72
PAD = 6
FONT_SIZE = 10.5
IMG_MAX_W = 70 * mm
IMG_MAX_H = 90 * mm
EMOJI_PT = FONT_SIZE + 1.5

_fonts_ready = False
_reshaper = None


def _font_file(name: str) -> Path:
    p = FONTS / name
    if p.exists():
        return p
    for d in ("/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "C:/Windows/Fonts"):
        q = Path(d) / name
        if q.exists():
            return q
    raise FileNotFoundError(f"font {name} not found (expected in {FONTS})")


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("PK", str(_font_file("DejaVuSans.ttf"))))
    pdfmetrics.registerFont(TTFont("PK-Bold", str(_font_file("DejaVuSans-Bold.ttf"))))
    pdfmetrics.registerFontFamily("PK", normal="PK", bold="PK-Bold", italic="PK", boldItalic="PK-Bold")
    _fonts_ready = True


# -- text: emoji, Arabic ------------------------------------------------------------------------------------

_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF),
                 (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3299), (0x00A9, 0x00A9), (0x00AE, 0x00AE),
                 (0x2122, 0x2122), (0x2190, 0x21FF), (0x25A0, 0x25FF), (0x2934, 0x2935))
_JOINERS = {0x200D, 0xFE0F, 0xFE0E, 0x20E3} | set(range(0x1F3FB, 0x1F400)) | set(range(0xE0020, 0xE0080))


# symbols below U+1F000 that are emoji by default (Unicode Emoji_Presentation); the others (✓, ☺, ♥, →) stay
# text unless followed by the emoji selector U+FE0F
_BMP_EMOJI = set()
for _a, _b in ((0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3), (0x25FD, 0x25FE),
               (0x2614, 0x2615), (0x2648, 0x2653), (0x267F, 0x267F), (0x2693, 0x2693), (0x26A1, 0x26A1),
               (0x26AA, 0x26AB), (0x26BD, 0x26BE), (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4),
               (0x26EA, 0x26EA), (0x26F2, 0x26F3), (0x26F5, 0x26F5), (0x26FA, 0x26FA), (0x26FD, 0x26FD),
               (0x2705, 0x2705), (0x270A, 0x270B), (0x2728, 0x2728), (0x274C, 0x274C), (0x274E, 0x274E),
               (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797), (0x27B0, 0x27B0), (0x27BF, 0x27BF),
               (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55)):
    _BMP_EMOJI.update(range(_a, _b + 1))


def _is_emoji_start(cp: int, nxt: int = 0) -> bool:
    if cp >= 0x1F000:
        return any(a <= cp <= b for a, b in _EMOJI_RANGES)
    if not any(a <= cp <= b for a, b in _EMOJI_RANGES):
        return False
    return cp in _BMP_EMOJI or nxt == 0xFE0F


def _arabic(ch: str) -> bool:
    cp = ord(ch)
    return 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF or 0xFB50 <= cp <= 0xFDFF \
        or 0xFE70 <= cp <= 0xFEFF


def is_rtl(text: str) -> bool:
    """Mostly right-to-left (Arabic letters outnumber Latin ones)."""
    a = sum(1 for ch in text if _arabic(ch))
    latin = sum(1 for ch in text if ch.isalpha() and not _arabic(ch))
    return a > 0 and a >= latin


def split_runs(text: str) -> list[tuple[str, str]]:
    """[(kind, text)] with kind 'emoji' (a whole emoji sequence: ZWJ, skin tone, flag, keycap) or 'text'."""
    out: list[tuple[str, str]] = []
    buf = ""
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        keycap = text[i] in "0123456789#*" and i + 1 < n and ord(text[i + 1]) in (0xFE0F, 0x20E3) and \
            ("\u20e3" in text[i + 1:i + 3])
        nxt = ord(text[i + 1]) if i + 1 < n else 0
        if _is_emoji_start(cp, nxt) or keycap:
            if buf:
                out.append(("text", buf))
                buf = ""
            j = i + 1
            if 0x1F1E6 <= cp <= 0x1F1FF and j < n and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF:
                j += 1  # flag: two regional indicators
            while j < n:
                c2 = ord(text[j])
                if c2 in _JOINERS:
                    j += 1
                    if c2 == 0x200D and j < n:
                        j += 1  # the emoji joined on
                    continue
                break
            seq = text[i:j]
            # a plain symbol with the text-style selector stays text
            if seq.endswith("\ufe0e"):
                buf += seq
            else:
                out.append(("emoji", seq))
            i = j
            continue
        buf += text[i]
        i += 1
    if buf:
        out.append(("text", buf))
    return out


class EmojiCache:
    """Each emoji sequence drawn once (colour, from Noto Color Emoji) to a PNG used inline in the PDF."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.paths: dict[str, Optional[str]] = {}
        self.font = None
        if Image is not None:
            try:
                self.font = ImageFont.truetype(str(_font_file("NotoColorEmoji.ttf")), 109)
            except Exception:
                self.font = None

    def png(self, seq: str) -> Optional[str]:
        if seq in self.paths:
            return self.paths[seq]
        path = None
        if self.font is not None:
            try:
                im = Image.new("RGBA", (136 * max(1, len(seq) // 2 + 1), 128), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((0, 0), seq, font=self.font, embedded_color=True)
                box = im.getbbox()
                if box:
                    im = im.crop(box)
                    side = max(im.size)
                    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
                    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
                    sq = sq.resize((48, 48), Image.LANCZOS)
                    h = hashlib.sha1(seq.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
                    p = self.folder / f"e{h}.png"
                    sq.save(p)
                    path = str(p)
            except Exception:
                path = None
        self.paths[seq] = path
        return path


_covered: Optional[set] = None


def drawable(text: str) -> str:
    """Characters the bundled font lacks become their standard decomposition when that is drawable
    (e.g. the ligature ﷺ becomes the full phrase); emoji are left alone (drawn as images)."""
    global _covered
    if _covered is None:
        _covered = set(TTFont("PKcov", str(_font_file("DejaVuSans.ttf"))).face.charToGlyph)
    out = []
    for kind, run in split_runs(text):
        if kind == "emoji":
            out.append(run)
            continue
        for ch in run:
            if ord(ch) in _covered or ch in "\n\t ":
                out.append(ch)
            else:
                alt = unicodedata.normalize("NFKC", ch)
                out.append(alt if alt != ch and all(ord(c) in _covered for c in alt) else ch)
    return "".join(out)


def _shape_arabic(line: str) -> str:
    """Visual order with joined letter forms, for one line of right-to-left text."""
    global _reshaper
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError:  # pragma: no cover - listed in requirements
        return line
    if _reshaper is None:
        # whole-word ligatures (Allah, the Basmala, ...) are single glyphs most fonts lack: keep the letters
        _reshaper = arabic_reshaper.ArabicReshaper(configuration={"support_ligatures": False,
                                                                   "delete_harakat": False})
    return get_display(_reshaper.reshape(line))


def markup(text: str, emoji: EmojiCache, size: float = FONT_SIZE) -> str:
    """Paragraph markup for left-to-right text: escaped, line breaks kept, emoji as inline images."""
    parts = []
    for kind, s in split_runs(text):
        if kind == "emoji":
            p = emoji.png(s)
            if p:
                parts.append(f'<img src="{p}" width="{size + 1.5}" height="{size + 1.5}" valign="-2"/>')
            else:
                parts.append(escape(s))
        else:
            parts.append(escape(s).replace("\n", "<br/>"))
    return "".join(parts)


def _wrap_logical(text: str, width: float, size: float) -> list[str]:
    """Break right-to-left text into lines (logical order) that fit the width once shaped."""
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = (cur + " " + w) if cur else w
            if pdfmetrics.stringWidth(_shape_arabic(trial), "PK", size) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def markup_rtl(text: str, emoji: EmojiCache, width: float, size: float = FONT_SIZE) -> str:
    """Paragraph markup for right-to-left text: wrapped in logical order, then each line shaped and
    reordered for display (so lines come out top to bottom in reading order)."""
    out = []
    for line in _wrap_logical(text, width, size):
        shaped = _shape_arabic(line)
        out.append(markup(shaped, emoji, size))
    return "<br/>".join(out)


# -- layout -------------------------------------------------------------------------------------------------

def _styles():
    base = ParagraphStyle("pk", fontName="PK", fontSize=FONT_SIZE, leading=FONT_SIZE * 1.35, textColor=INK)
    return {
        "body": base,
        "body_rtl": ParagraphStyle("pk_rtl", parent=base, alignment=TA_RIGHT),
        "sender": ParagraphStyle("pk_sender", parent=base, fontName="PK-Bold", fontSize=9, leading=11, textColor=GREEN),
        "meta": ParagraphStyle("pk_meta", parent=base, fontSize=7.5, leading=9, textColor=MUTED, alignment=TA_RIGHT),
        "day": ParagraphStyle("pk_day", parent=base, fontName="PK-Bold", fontSize=8.5, leading=11, textColor=MUTED,
                              alignment=TA_CENTER),
        "sys": ParagraphStyle("pk_sys", parent=base, fontSize=8.5, leading=11, textColor=SYS, alignment=TA_CENTER),
        "tile": ParagraphStyle("pk_tile", parent=base, fontSize=9.5, leading=12, textColor=MUTED),
    }


TYPE_LABEL = {"video": "Video", "audio": "Voice message", "contact": "Contact card", "location": "Location",
              "document": "Document", "sticker": "Sticker", "gif": "GIF", "image": "Photo", "call": "Call",
              "deleted": "This message was deleted"}
IMG_SUFFIX = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".tif", ".tiff", ".bmp"}


def _when(m: dict) -> Optional[dt.datetime]:
    t = m.get("time")
    if isinstance(t, dt.datetime):
        return t
    if t:
        try:
            return dt.datetime.fromisoformat(str(t))
        except ValueError:
            return None
    return None


def _duration(m: dict) -> str:
    sec = m.get("duration") or m.get("seconds")
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return ""
    return f"{sec // 60}:{sec % 60:02d}"


class _Images:
    """Photos scaled for the page once (JPEG draft decoding keeps 2,000-message chats fast)."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.cache: dict[Path, Optional[tuple[str, int, int]]] = {}

    def get(self, src: Path) -> Optional[tuple[str, int, int]]:
        if src in self.cache:
            return self.cache[src]
        res = None
        if Image is not None and src.exists() and src.suffix.lower() in IMG_SUFFIX:
            try:
                with Image.open(src) as im:
                    if im.format == "JPEG":
                        im.draft("RGB", (900, 900))
                    im = im.convert("RGB")
                    im.thumbnail((900, 900))
                    h = hashlib.sha1(str(src).encode(), usedforsecurity=False).hexdigest()[:16]
                    out = self.folder / f"i{h}.jpg"
                    im.save(out, "JPEG", quality=80)
                    res = (str(out), im.width, im.height)
            except Exception:
                res = None
        self.cache[src] = res
        return res


def _bubble(cells: list, me: bool, width: float):
    t = Table([[c] for c in cells], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ME if me else THEM),
        ("BOX", (0, 0), (-1, -1), 0.4, ME if me else BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), PAD), ("RIGHTPADDING", (0, 0), (-1, -1), PAD),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, 0), PAD - 1), ("BOTTOMPADDING", (0, -1), (-1, -1), PAD - 2),
        ("ROUNDEDCORNERS", [7, 7, 7, 7]),
    ]))
    row = [["", t]] if me else [[t, ""]]
    outer = Table(row, colWidths=[BODY_W - width - 2, width + 2] if me else [width + 2, BODY_W - width - 2])
    outer.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return outer


def _text_width(text: str, size: float, rtl: bool) -> float:
    w = 0.0
    for line in text.split("\n"):
        shown = _shape_arabic(line) if rtl else line
        lw = 0.0
        for kind, s in split_runs(shown):
            lw += (size + 2) if kind == "emoji" else pdfmetrics.stringWidth(s, "PK", size)
        w = max(w, lw)
    return w


def _centered(p: Paragraph, width: float, bg) -> Table:
    t = Table([[p]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    t.hAlign = "CENTER"
    return t


def chat_flowables(chat: dict, base: Path, emoji: EmojiCache, images: _Images, st: dict) -> list:
    """The flowables of one chat: day lines, system lines and bubbles."""
    flow: list = []
    last_day = None
    group = bool(chat.get("group"))
    for m in chat.get("messages", []):
        when = _when(m)
        day = when.strftime("%A %d %B %Y") if when else ""
        if day and day != last_day:
            flow.append(Spacer(1, 4))
            flow.append(_centered(Paragraph(escape(day), st["day"]), 60 * mm, DAY_BG))
            flow.append(Spacer(1, 3))
            last_day = day
        if m.get("type") == "system":
            flow.append(Paragraph(markup(m.get("text") or "Group update", emoji, 8.5), st["sys"]))
            continue
        me = bool(m.get("from_me"))
        cells: list = []
        inner_max = BUBBLE_MAX - 2 * PAD
        need = 40.0
        if group and not me and m.get("sender"):
            cells.append(Paragraph(markup(m["sender"], emoji, 9), st["sender"]))
            need = max(need, pdfmetrics.stringWidth(m["sender"], "PK-Bold", 9))
        mtype = m.get("type") or "text"
        media = m.get("media")
        src = (base / media) if media else None
        if mtype in ("image", "sticker", "gif"):
            got = images.get(src) if src else None
            if got:
                path, w, h = got
                scale = min(IMG_MAX_W / w, IMG_MAX_H / h, 1.0 if mtype == "sticker" else 99)
                if mtype == "sticker":
                    scale = min(scale, 35 * mm / max(w, h))
                iw, ih = w * scale, h * scale
                cells.append(RLImage(path, width=iw, height=ih))
                need = max(need, iw)
            else:
                cells.append(Paragraph(markup("📷 " + TYPE_LABEL[mtype] + (" (not in the backup)" if m.get("media_missing")
                                                                            else ""), emoji, 9.5), st["tile"]))
        elif mtype in ("video", "audio", "document", "contact", "location", "call"):
            label = TYPE_LABEL[mtype]
            icon = {"video": "▶", "audio": "🎙", "document": "📄", "contact": "👤", "location": "📍", "call": "📞"}[mtype]
            dur = _duration(m)
            name = Path(media).name if media and mtype in ("video", "document") else ""
            line = f"{icon}  {label}" + (f" · {dur}" if dur else "") + (f" · {name}" if name else "")
            cells.append(Paragraph(markup(line, emoji, 9.5), st["tile"]))
            need = max(need, _text_width(line, 9.5, False) + 4)
        body = drawable((m.get("text") or "").strip())
        cap = drawable((m.get("caption") or "").strip())
        if cap and cap != body:
            body = (body + "\n" + cap).strip()
        if not body and mtype == "deleted":
            body = TYPE_LABEL["deleted"]
        if body:
            rtl = is_rtl(body)
            if rtl:
                cells.append(Paragraph(markup_rtl(body, emoji, inner_max), st["body_rtl"]))
            else:
                cells.append(Paragraph(markup(body, emoji), st["body"]))
            need = max(need, _text_width(body, FONT_SIZE, rtl) + 2)
        if not cells:
            cells.append(Paragraph(escape(TYPE_LABEL.get(mtype, mtype)), st["tile"]))
        stamp = when.strftime("%H:%M") if when else ""
        if stamp:
            cells.append(Paragraph(stamp, st["meta"]))
        width = min(BUBBLE_MAX, max(need, 46) + 2 * PAD)
        flow.append(_bubble(cells, me, width))
    if not chat.get("messages"):
        flow.append(Paragraph("No messages in this chat.", st["sys"]))
    return flow


def _date_range(chat: dict) -> str:
    times = [t for t in (_when(m) for m in chat.get("messages", [])) if t]
    if not times:
        return ""
    a, b = min(times), max(times)
    fmt = "%d %b %Y"
    return a.strftime(fmt) if a.date() == b.date() else f"{a.strftime(fmt)} – {b.strftime(fmt)}"


class _NumberedCanvas(rl_canvas.Canvas):
    """Draws 'Page N of M' once the total is known."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("PK", 8)
            self.setFillColor(MUTED)
            self.drawCentredString(PAGE_W / 2, 9 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _safe_name(s: str, n: int = 80) -> str:
    s = unicodedata.normalize("NFC", s or "Chat")
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip(" .") or "Chat"
    return s[:n]


def write_pdf(chats: list[dict], dest: Path, base: Path, app_title: str = "",
              progress: Optional[Callable[[float], None]] = None) -> Path:
    """One PDF with these chats (each starting on a new page, with its own header). `base` is the folder
    that messages' 'media' paths are relative to."""
    _register_fonts()
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="phonekeep-pdf-"))
    emoji = EmojiCache(work / "emoji")
    images = _Images(work / "img")
    st = _styles()
    header = {"name": "", "range": ""}

    def on_page(c, doc):
        c.saveState()
        c.setFont("PK-Bold", 11)
        c.setFillColor(INK)
        name = drawable(header["name"])
        shown = (_shape_arabic(name) if is_rtl(name) else name)[:90]
        x, y = MARGIN, PAGE_H - 11 * mm
        for kind, run in split_runs(shown):
            if kind == "emoji":
                png = emoji.png(run)
                if png:
                    c.drawImage(png, x, y - 2, 12, 12, mask="auto")
                x += 13
            else:
                c.drawString(x, y, run)
                x += pdfmetrics.stringWidth(run, "PK-Bold", 11)
        c.setFont("PK", 8.5)
        c.setFillColor(MUTED)
        right = " · ".join(x for x in (app_title, header["range"]) if x)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 11 * mm, right)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(MARGIN, PAGE_H - 13.5 * mm, PAGE_W - MARGIN, PAGE_H - 13.5 * mm)
        c.restoreState()

    frame = Frame(MARGIN, 14 * mm, BODY_W, PAGE_H - 30 * mm, id="body", leftPadding=0, rightPadding=0,
                  topPadding=2, bottomPadding=2)
    doc = BaseDocTemplate(str(dest), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=17 * mm,
                          bottomMargin=14 * mm, title=", ".join(c.get("name", "") for c in chats[:3]),
                          author="PhoneKeep", creator="PhoneKeep")
    doc.addPageTemplates([PageTemplate(id="chat", frames=[frame], onPage=on_page)])

    from reportlab.platypus import ActionFlowable, PageBreak

    class _SetHeader(ActionFlowable):
        def __init__(self, name, rng):
            super().__init__()
            self.name, self.rng = name, rng

        def apply(self, doc):
            header["name"], header["range"] = self.name, self.rng

        def wrap(self, aw, ah):
            return 0, 0

        def draw(self):
            header["name"], header["range"] = self.name, self.rng

    story: list = []
    total = max(1, sum(len(c.get("messages", [])) for c in chats))
    done = 0
    for i, chat in enumerate(chats):
        if i:
            story.append(_SetHeader(chat.get("name", ""), _date_range(chat)))
            story.append(PageBreak())
        else:
            header["name"], header["range"] = chat.get("name", ""), _date_range(chat)
        story.extend(chat_flowables(chat, base, emoji, images, st))
        done += len(chat.get("messages", []))
        if progress:
            progress(60.0 * done / total)
    if progress:
        progress(70.0)
    doc.build(story, canvasmaker=_NumberedCanvas)
    if progress:
        progress(100.0)
    return dest


def write_chats_pdf(chats: list[dict], out: Path, app_title: str, log: Callable[[str], None] = lambda m: None,
                    combined: bool = False, progress: Optional[Callable[[float], None]] = None) -> Path:
    """The PDF part of a chat export: out/PDF/<chat>.pdf for each chat, or out/PDF/<app> chats.pdf with
    all of them. Returns the PDF folder (or the combined file)."""
    folder = out / "PDF"
    folder.mkdir(parents=True, exist_ok=True)
    started = time.time()
    if combined:
        # named after what's in it, so it can be found (usability test, 12 Nov: "WhatsApp chats.pdf" wasn't)
        first = _safe_name(chats[0].get("name") or "Chat", 60) if chats else "Chats"
        name = first if len(chats) == 1 else f"{first} and {len(chats) - 1} more chat{'s' if len(chats) > 2 else ''}"
        dest = write_pdf(chats, folder / f"{name}.pdf", out, app_title, progress)
        log(f"PDF: {len(chats):,} chats in one file ({time.time() - started:.0f} s).")
        return dest
    used: set = set()
    for i, c in enumerate(chats):
        name = _safe_name(c.get("name") or "Chat")
        stem, k = name, 2
        while stem.lower() in used:
            stem, k = f"{name} ({k})", k + 1
        used.add(stem.lower())
        write_pdf([c], folder / f"{stem}.pdf", out, app_title)
        if progress:
            progress(100.0 * (i + 1) / len(chats))
    log(f"PDF: {len(chats):,} chats, one file each ({time.time() - started:.0f} s).")
    return folder


def print_pdf(path: Path) -> str:
    """Show the system print dialog for a PDF; nothing is printed unless the owner clicks Print there.
    Returns what happened, in words for the banner.

    Mac: the standard print panel from PDFKit, run by PhoneKeep itself. (Asking Preview by script to
    'print with print dialog' printed straight away instead, and a printer that was off made macOS
    relaunch the print queue again and again — owner's Mac, 12 Nov. Never script another app to print.)
    If PDFKit isn't available, the PDF opens in Preview and the owner presses ⌘P.
    Windows: the PDF opens in the default PDF app, whose Print (Ctrl+P) shows the dialog."""
    import os
    import subprocess
    path = Path(path)
    if sys.platform == "darwin":
        try:
            import Quartz  # noqa: F401  (pyobjc-framework-Quartz: PDFKit)
            from AppKit import NSPrintInfo
            from Foundation import NSURL
            from Quartz import PDFDocument
            doc = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(path)))
            if doc is None:
                raise RuntimeError("PDFKit couldn't read the PDF")
            info = NSPrintInfo.sharedPrintInfo()
            op = doc.printOperationForPrintInfo_scalingMode_autoRotate_(info, 1, True)  # 1 = scale down to fit
            op.setShowsPrintPanel_(True)
            op.setShowsProgressPanel_(True)
            op.runOperation()               # the owner chooses Print or Cancel in the panel
            return "Print dialog shown."
        except Exception:
            subprocess.Popen(["open", "-a", "Preview", str(path)])
            return "The PDF is open in Preview — press ⌘P to print it."
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return "The PDF is open — press Ctrl+P to print it."
    subprocess.Popen(["xdg-open", str(path)])
    return "The PDF is open — use its Print command."
