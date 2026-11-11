"""
PhoneKeep - spreadsheet exports (Excel .xlsx and CSV) for chats.

Security: chat text is written as plain text, never as a formula. A message such as
=HYPERLINK("http://evil","click") stays inert in Excel, Numbers and Google Sheets:
  * in .xlsx every text cell is stored with the string type, so Excel can't evaluate it;
  * in .csv any value starting with = + - @ (or a tab/CR) gets a leading apostrophe,
    the standard defence against "CSV injection".
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
from pathlib import Path
from typing import Callable, Optional

_RISKY_START = ("=", "+", "-", "@", "\t", "\r")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # characters Excel files can't hold
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")

HEADERS = ["Date", "Time", "Sender", "Message", "Type", "Attachment", "Starred"]


def csv_safe(v):
    """Neutralise values a spreadsheet would treat as a formula."""
    if isinstance(v, str) and v.startswith(_RISKY_START):
        return "'" + v
    return v


def write_csv_rows(path: Path, headers: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel reads UTF-8 right
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            w.writerow([csv_safe(x) for x in r])


def _msg_row(m: dict) -> tuple:
    t = dt.datetime.fromisoformat(m["time"]) if m.get("time") else None
    text = m.get("text") or ""
    if m.get("caption") and m["caption"] != text:
        text = (text + "\n" + m["caption"]).strip()
    if m.get("location"):
        text = (text + f"\nLocation: {m['location'][0]:.5f}, {m['location'][1]:.5f}").strip()
    if m.get("contact"):
        text = (text + f"\nContact: {m['contact']}").strip()
    if m["type"] == "deleted" and not text:
        text = "This message was deleted"
    attach = m.get("media") or ("(not in backup)" if m.get("media_missing") else "")
    return t, m.get("sender", ""), text, m["type"], attach, "yes" if m.get("starred") else ""


def _file_stub(name: str, used: set, n: int = 60) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")[:n] or "chat"
    stub, k = s, 2
    while stub.lower() in used:
        stub, k = f"{s} ({k})", k + 1
    used.add(stub.lower())
    return stub


def write_chats_csv(chats: list[dict], folder: Path, log: Callable[[str], None] = print) -> Path:
    """One CSV per chat, plus all chats together in one file."""
    folder = Path(folder)
    used: set = set()
    everything = []
    for c in chats:
        rows = []
        for m in c["messages"]:
            t, sender, text, typ, attach, star = _msg_row(m)
            row = [t.strftime("%Y-%m-%d") if t else "", t.strftime("%H:%M:%S") if t else "",
                   sender, text, typ, attach, star]
            rows.append(row)
            everything.append([c["name"]] + row)
        write_csv_rows(folder / f"{_file_stub(c['name'], used)}.csv", HEADERS, rows)
    write_csv_rows(folder / "_All chats.csv", ["Chat"] + HEADERS, everything)
    log(f"CSV: {len(chats)} chat file{'s' if len(chats) != 1 else ''} + one combined file in {folder}")
    return folder


def write_chats_xlsx(chats: list[dict], path: Path, title: str = "WhatsApp",
                     log: Callable[[str], None] = print) -> Path:
    """Excel workbook: a Summary sheet (with links) and one sheet per chat."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.hyperlink import Hyperlink
    except ImportError:
        raise RuntimeError("Excel export needs openpyxl: pip install openpyxl")

    path = Path(path)
    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="008069")
    link_font = Font(color="0563C1", underline="single")
    wrap = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")

    def put(ws, row, col, value, number_format=None, align=None):
        if isinstance(value, str):
            value = _CTRL.sub("", value)[:32000]
        cell = ws.cell(row=row, column=col)
        cell.value = value
        if isinstance(value, str):
            cell.data_type = "s"  # plain text, never a formula
        if number_format:
            cell.number_format = number_format
        if align:
            cell.alignment = align
        return cell

    def header(ws, names, widths):
        for i, (h, w) in enumerate(zip(names, widths), 1):
            c = put(ws, 1, i, h)
            c.font, c.fill = head_font, head_fill
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.page_setup.orientation = "landscape"   # prints one page wide
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "1:1"

    # sheet names: max 31 chars, no []:*?/\ , unique (case-insensitive), not "Summary"
    used = {"summary"}
    sheet_names = []
    for c in chats:
        base = _SHEET_BAD.sub("_", c["name"]).strip("' ")[:28] or "Chat"
        name, k = base, 2
        while name.lower() in used:
            suffix = f" ({k})"
            name, k = base[:31 - len(suffix)] + suffix, k + 1
        used.add(name.lower())
        sheet_names.append(name)

    summary = wb.active
    summary.title = "Summary"
    header(summary, ["Chat", "Type", "Messages", "First message", "Last message", "Open"],
           [38, 10, 12, 18, 18, 14])
    for r, (c, sname) in enumerate(zip(chats, sheet_names), 2):
        times = [m["time"] for m in c["messages"] if m.get("time")]
        put(summary, r, 1, c["name"])
        put(summary, r, 2, "Group" if c.get("group") else "Person")
        put(summary, r, 3, len(c["messages"]))
        if times:
            put(summary, r, 4, dt.datetime.fromisoformat(times[0]), "yyyy-mm-dd hh:mm")
            put(summary, r, 5, dt.datetime.fromisoformat(times[-1]), "yyyy-mm-dd hh:mm")
        link = put(summary, r, 6, "Go to sheet")
        link.hyperlink = Hyperlink(ref=link.coordinate, location=f"'{sname}'!A1", display="Go to sheet")
        link.font = link_font
    if chats:
        summary.auto_filter.ref = f"A1:F{len(chats) + 1}"

    for c, sname in zip(chats, sheet_names):
        ws = wb.create_sheet(sname)
        header(ws, HEADERS, [12, 9, 22, 70, 10, 34, 8])
        for r, m in enumerate(c["messages"], 2):
            t, sender, text, typ, attach, star = _msg_row(m)
            if t:
                put(ws, r, 1, t.date(), "yyyy-mm-dd", top)
                put(ws, r, 2, t.time().replace(microsecond=0), "hh:mm", top)
            put(ws, r, 3, sender, align=top)
            put(ws, r, 4, text, align=wrap)
            put(ws, r, 5, typ, align=top)
            cell = put(ws, r, 6, os.path.basename(attach) if m.get("media") else attach, align=top)
            if m.get("media"):  # link to the copied file, relative to the workbook
                cell.hyperlink = m["media"]
                cell.font = link_font
            put(ws, r, 7, star, align=top)
        if c["messages"]:
            ws.auto_filter.ref = f"A1:G{len(c['messages']) + 1}"

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    log(f"Excel: {path.name} ({len(chats)} chat sheet{'s' if len(chats) != 1 else ''} + summary)")
    return path
