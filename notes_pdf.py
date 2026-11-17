"""D4: notes to PDF (docs/spec/08-personal-data.md#d4-notes).

Each note starts on a new page: its title, folder and dates, then the note as on the phone: headings, lists,
checklists (☐ / ☑), monospaced text, bold / underline / strikethrough and links, tables as a grid, and images,
drawings and scanned pages scaled to the page. Audio, video and other files are named (they can't be printed).
Same fonts, colour emoji and "Page N of M" as the chat PDFs (M3). Images are scaled in PhoneKeep's private temp
folder, removed when the PDF is made; the PDF is written next to its final name and then renamed.
"""
from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import chat_pdf as cp
import notes_doc

IMG_MAX_W = cp.BODY_W
IMG_MAX_H = 120 * mm
MAX_PICTURES = 1_000      # pictures in one note's pages; the rest are named in a line (a 20,000-page "gallery" is
                          # damaged or hostile, and each picture is scaled on disk until the PDF is made)


def _styles():
    base = ParagraphStyle("note", fontName="PK", fontSize=11, leading=15, textColor=cp.INK, spaceAfter=2)
    return {
        "body": base,
        "title": ParagraphStyle("note_title", parent=base, fontName="PK-Bold", fontSize=18, leading=23, spaceAfter=6),
        "heading": ParagraphStyle("note_h", parent=base, fontName="PK-Bold", fontSize=15, leading=20, spaceBefore=6),
        "subheading": ParagraphStyle("note_sh", parent=base, fontName="PK-Bold", fontSize=12.5, leading=17,
                                     spaceBefore=4),
        "mono": ParagraphStyle("note_mono", parent=base, fontName="Courier", fontSize=10, leading=13),
        "meta": ParagraphStyle("note_meta", parent=base, fontSize=8.5, leading=11, textColor=cp.MUTED, spaceAfter=8),
        "file": ParagraphStyle("note_file", parent=base, textColor=cp.MUTED),
        "cell": ParagraphStyle("note_cell", parent=base, fontSize=9.5, leading=12, spaceAfter=0),
        "cellhead": ParagraphStyle("note_cellh", parent=base, fontName="PK-Bold", fontSize=9.5, leading=12,
                                   spaceAfter=0),
    }


def _when(v) -> str:
    try:
        return v.strftime("%d %b %Y, %H:%M")
    except Exception:
        return ""


class _Pictures:
    """Backup images scaled for the page once each (by backup file), as JPEGs in a private folder; at most
    MAX_PICTURES drawn per note (`in_note` counts them, `left_out` the rest)."""

    def __init__(self, folder: Path, read: Callable):
        self.folder, self.read, self.n = folder, read, 0
        self.scaled: dict[tuple, Optional[tuple[str, float, float]]] = {}
        self.in_note = self.left_out = 0
        folder.mkdir(parents=True, exist_ok=True)

    def flowable(self, src) -> Optional[RLImage]:
        if not src or cp.Image is None:
            return None
        if self.in_note >= MAX_PICTURES:
            self.left_out += 1
            return None
        key = tuple(src)
        if key not in self.scaled:
            self.scaled[key] = self._scale(src)
        if self.scaled[key] is None:
            return None
        self.in_note += 1
        path, w, h = self.scaled[key]
        img = RLImage(path, width=w, height=h)
        img.hAlign = "LEFT"
        return img

    def _scale(self, src) -> Optional[tuple[str, float, float]]:
        data = self.read(*src)
        if not data:
            return None
        try:
            im = cp.Image.open(io.BytesIO(data))
            if im.format == "JPEG":
                im.draft("RGB", (1400, 1400))
            im = im.convert("RGB")
            im.thumbnail((1400, 1400))
        except Exception:
            return None
        self.n += 1
        p = self.folder / f"n{self.n}.jpg"
        im.save(p, "JPEG", quality=82)
        scale = min(IMG_MAX_W / im.width, IMG_MAX_H / im.height, 1.0 if im.width > 300 else 2.0)
        return str(p), im.width * scale, im.height * scale


def _spans(b: dict, emoji) -> str:
    out = []
    for text, fmt, link in b["spans"]:
        s = cp.markup(cp.drawable(text), emoji, 11)
        if "bold" in fmt and b["style"] not in ("title", "heading", "subheading"):
            s = f"<b>{s}</b>"
        if "underline" in fmt:
            s = f"<u>{s}</u>"
        if "strike" in fmt:
            s = f"<strike>{s}</strike>"
        if link:
            s = f'<font color="#0a63c9"><u>{s}</u></font>'
        out.append(s)
    return "".join(out) or "&nbsp;"


def note_flowables(n: dict, st: dict, emoji, pics: _Pictures) -> list:
    fl = [Paragraph(cp.markup(cp.drawable(n.get("title") or "Untitled"), emoji, 18), st["title"])]
    meta = " · ".join(x for x in (n.get("folder") or "", f"created {_when(n.get('created'))}" if n.get("created")
                                  else "", f"edited {_when(n.get('modified'))}" if n.get("modified") else "") if x)
    fl.append(Paragraph(cp.markup(meta, emoji, 8.5), st["meta"]))
    if n.get("locked"):
        fl.append(Paragraph("🔒 Locked on your iPhone. Open it on the iPhone with your Notes password.", st["file"]))
        return fl
    if n.get("blocks") is None:
        for line in (n.get("text") or "").split("\n"):
            fl.append(Paragraph(cp.markup(cp.drawable(line), emoji, 11) or "&nbsp;", st["body"]))
        return fl
    atts = n.get("attachments") or {}
    pics.in_note = pics.left_out = 0
    first_title = True
    for b in n["blocks"]:
        if b["kind"] == "para":
            if b["style"] == "title" and first_title and b["text"].strip() == (n.get("title") or "").strip():
                first_title = False                     # the title is already the page's heading
                continue
            style = st.get(b["style"], st["body"])
            if b["style"] in notes_doc.LISTS or b["indent"]:
                hang = 14 if b["style"] in notes_doc.LISTS else 0
                style = ParagraphStyle(f"{style.name}{b['indent']}{hang}", parent=style,
                                       leftIndent=16 * b["indent"] + hang, firstLineIndent=-hang)
            pre = notes_doc.prefix(b)
            if cp.is_rtl(b["text"]):                    # Arabic: shaped and laid out right to left, as in chats
                rtl = ParagraphStyle(style.name + "rtl", parent=style, alignment=cp.TA_RIGHT, leftIndent=0,
                                     firstLineIndent=0, rightIndent=16 * b["indent"])
                fl.append(Paragraph(cp.markup_rtl(pre + b["text"], emoji, cp.BODY_W - 16 * b["indent"],
                                                  style.fontSize), rtl))
                continue
            text = (f'<font color="#0F766E">{pre}</font>' if b["style"] == "check" else pre) + _spans(b, emoji)
            fl.append(Paragraph(text, style))
            continue
        a = atts.get(b["id"]) or {"kind": "file", "name": "", "file": None}
        kind = a.get("kind")
        if kind == "table" and a.get("rows"):
            rows = [[Paragraph(cp.markup(cp.drawable(c), emoji, 9.5) or "&nbsp;", st["cellhead" if r == 0 else "cell"])
                     for c in row] for r, row in enumerate(a["rows"])]
            ncols = max(len(r) for r in rows)
            t = Table(rows, colWidths=[cp.BODY_W / max(ncols, 1)] * ncols, hAlign="LEFT")
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, cp.BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f4"))]))
            fl += [Spacer(1, 3), t, Spacer(1, 5)]
            continue
        pages = a.get("items") if kind == "gallery" else [a] if kind in ("image", "drawing") else []
        drawn = 0
        for p in pages or []:
            img = pics.flowable(p.get("file") or p.get("preview"))
            if img is not None:
                fl += [img, Spacer(1, 4)]
                drawn += 1
        if drawn:
            continue
        if kind in ("scan", "pdf", "video") and a.get("preview"):
            img = pics.flowable(a["preview"])
            if img is not None:
                fl += [img, Spacer(1, 2)]
        label = notes_doc.KIND_LABEL.get(kind, "File")
        name = a.get("url") if kind == "link" else a.get("name")
        missing = "" if a.get("file") or kind == "link" else " (not in the backup)"
        fl.append(Paragraph(cp.markup(f"[{label}{': ' + name if name and name != label else ''}{missing}]", emoji, 11),
                            st["file"]))
    if pics.left_out:
        fl.append(Paragraph(f"[{pics.left_out:,} more picture{'s' if pics.left_out != 1 else ''} not in this PDF: "
                            f"at most {MAX_PICTURES:,} a note]", st["file"]))
    return fl


def write_notes_pdf(notes: list[dict], dest: Path, read: Callable, title: str = "Notes",
                    progress: Optional[Callable[[float], None]] = None) -> Path:
    """One PDF with these notes, each on its own page(s). `read(domain, rel)` gives a backup file's bytes."""
    cp._register_fonts()
    import quicklook
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    work = quicklook.private_tmp("phonekeep-notes-pdf-")
    try:                                             # whatever stops it (a damaged picture, a cancel), work goes
        emoji = cp.EmojiCache(work / "emoji")
        pics = _Pictures(work / "img", read)
        st = _styles()
        story: list = []
        for i, n in enumerate(notes):
            if i:
                story.append(PageBreak())
            story += note_flowables(n, st, emoji, pics)
            if progress:
                progress((i + 1) / max(len(notes), 1))
        dest.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(str(part), pagesize=cp.A4, leftMargin=cp.MARGIN, rightMargin=cp.MARGIN,
                                topMargin=cp.MARGIN, bottomMargin=cp.MARGIN + 4 * mm, title=title,
                                author="PhoneKeep")
        doc.build(story or [Paragraph("No notes.", st["body"])], canvasmaker=cp._NumberedCanvas)
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink()
        shutil.rmtree(work, ignore_errors=True)        # the scaled pictures: not kept until PhoneKeep closes
    return dest
