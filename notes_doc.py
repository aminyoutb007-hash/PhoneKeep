"""D4: a note as on the phone (docs/spec/08-personal-data.md#d4-notes).

Apple Notes keeps a note's body as gzipped protobuf (NoteStoreProto -> Document -> Note): the text, and "attribute
runs" over it, each with a length in UTF-16 units and the style of that stretch: paragraph style (title, heading,
subheading, monospaced, bulleted / dashed / numbered list, checklist with its tick), indent, bold / italic, underline,
strikethrough, link, and an attachment (U+FFFC in the text) with its identifier and type.

Tables are attachments too, kept as Apple's "mergeable data" (a CRDT, also gzipped protobuf): an ICTable object with
crRows and crColumns (ordered sets of row and column UUIDs) and cellColumns (column -> row -> a small note with the
cell's text). Galleries (scanned pages) list their pages' identifiers in their own mergeable data.

This is read-only, from the backup's NoteStore.sqlite; field numbers follow the published layout the open-source
apple_cloud_notes_parser uses. Anything not understood is kept as plain text, never dropped.
"""
from __future__ import annotations

import re
import zlib
from typing import Optional

STYLES = {0: "title", 1: "heading", 2: "subheading", 4: "mono", 100: "bullet", 101: "dash", 102: "number",
          103: "check"}
LISTS = ("bullet", "dash", "number", "check")
OBJ = "￼"


MAX_UNZIP = 32 * 1024 * 1024    # a note body or table is a few KB; more than this is a damaged or hostile blob
MAX_INDENT = 8                  # Notes goes no deeper; a bigger number would build huge margins and strings
MAX_CELLS = 100_000             # a table's rows x columns; a bigger one is damaged (and the grid alone would be huge)
_BREAKS = re.compile("(\n|" + OBJ + ")")
_UUID = re.compile(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


def unzip(data) -> Optional[bytes]:
    """A blob gunzipped (or inflated), at most MAX_UNZIP bytes: None if it would be bigger. Not compressed at all:
    the bytes as they are."""
    if not data:
        return None
    data = bytes(data)
    for wbits in (16 + zlib.MAX_WBITS, zlib.MAX_WBITS):
        d = zlib.decompressobj(wbits)
        try:
            out = d.decompress(data, MAX_UNZIP)
        except zlib.error:
            continue
        if d.unconsumed_tail:
            return None                                   # a "gzip bomb": refused, never expanded
        return out
    return data


def _varint(b: bytes, i: int) -> tuple[int, int]:
    """A protobuf varint: at most 10 bytes (64 bits); anything longer is damaged."""
    shift = result = 0
    for _ in range(10):
        x = b[i]
        i += 1
        result |= (x & 0x7F) << shift
        if not x & 0x80:
            return result, i
        shift += 7
    raise ValueError("varint longer than 10 bytes")


def _int(v, default: int = 0) -> int:
    """A field that should be a varint; anything else (a damaged body) counts as the default."""
    return v if isinstance(v, int) else default


def fields(buf: bytes) -> dict[int, list]:
    """One protobuf message: field number -> its values in order (ints for varints, bytes for the rest)."""
    out: dict[int, list] = {}
    i = 0
    try:
        while i < len(buf):
            key, i = _varint(buf, i)
            f, wt = key >> 3, key & 7
            if wt == 0:
                v, i = _varint(buf, i)
            elif wt == 1:
                v, i = buf[i:i + 8], i + 8
            elif wt == 2:
                n, i = _varint(buf, i)
                v, i = buf[i:i + n], i + n
            elif wt == 5:
                v, i = buf[i:i + 4], i + 4
            else:
                break
            out.setdefault(f, []).append(v)
    except (IndexError, ValueError):                       # cut short or damaged: what was read so far
        pass
    return out


def _one(msg: dict, f: int, default=None):
    v = msg.get(f)
    return v[0] if v else default


def _str(v) -> str:
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else ("" if v is None else str(v))


def _note_msg(data) -> Optional[dict]:
    """NoteStoreProto.document(2).note(3), from a ZICNOTEDATA.ZDATA blob."""
    raw = unzip(data)
    if not raw:
        return None
    doc = _one(fields(raw), 2)
    note = _one(fields(doc), 3) if isinstance(doc, bytes) else None
    return fields(note) if isinstance(note, bytes) else None


# -- the body: text + runs -> paragraphs ------------------------------------------------------------------------

def _run(r: bytes) -> dict:
    m = fields(r)
    ps = fields(_one(m, 2, b"")) if isinstance(_one(m, 2), bytes) else {}
    style = STYLES.get(_int(_one(ps, 1, -1), -1), "body")
    done = None
    if style == "check":
        cl = fields(_one(ps, 5, b"")) if isinstance(_one(ps, 5), bytes) else {}
        done = bool(_int(_one(cl, 2, 0)))
    weight = _int(_one(m, 5, 0))
    att = fields(_one(m, 12, b"")) if isinstance(_one(m, 12), bytes) else {}
    return {"len": _int(_one(m, 1, 0)), "style": style, "indent": min(MAX_INDENT, _int(_one(ps, 4, 0))), "done": done,
            "bold": weight in (1, 3), "italic": weight in (2, 3), "underline": bool(_int(_one(m, 6, 0))),
            "strike": bool(_int(_one(m, 7, 0))), "link": _str(_one(m, 9)) or None,
            "attachment": (_str(_one(att, 1)), _str(_one(att, 2))) if att.get(1) else None}


def body(data) -> Optional[tuple[str, list[dict]]]:
    """(text, runs) of a note, or None if the blob isn't a note body (a locked note is encrypted)."""
    note = _note_msg(data)
    if note is None or not note.get(2):
        return None
    text = _str(note[2][0])
    return text, [_run(r) for r in note.get(5, []) if isinstance(r, bytes)]


def _pieces(text: str, runs: list[dict]):
    """(text, run) pieces; lengths are UTF-16 units. Text past the last run gets a plain run."""
    u16 = text.encode("utf-16-le", "surrogatepass")
    pos = 0
    plain = {"len": 0, "style": "body", "indent": 0, "done": None, "bold": False, "italic": False,
             "underline": False, "strike": False, "link": None, "attachment": None}
    for r in runs:
        n = max(0, _int(r["len"]))
        if n == 0:
            continue
        yield u16[pos * 2:(pos + n) * 2].decode("utf-16-le", "surrogatepass"), r
        pos += n
    if pos * 2 < len(u16):
        yield u16[pos * 2:].decode("utf-16-le", "surrogatepass"), plain


def paragraphs(text: str, runs: list[dict]) -> list[dict]:
    """The note as blocks, in order:
    {"kind": "para", "style", "indent", "done", "number", "spans": [(text, {"bold", "italic", ...}, link)]}
    {"kind": "attachment", "id", "uti"}
    A paragraph's style is the one on its line (Notes stores it on every run of the line, newline included)."""
    blocks: list[dict] = []
    spans: list = []
    style = {"style": "body", "indent": 0, "done": None}
    seen: set[str] = set()                                      # attachments already in the note

    def close():
        nonlocal spans
        txt = "".join(s[0] for s in spans)
        blocks.append({"kind": "para", "style": style["style"], "indent": style["indent"], "done": style["done"],
                       "number": 0, "spans": [s for s in spans if s[0]], "text": txt})
        spans = []

    for chunk, r in _pieces(text, runs):
        fmt = {k for k in ("bold", "italic", "underline", "strike") if r[k]}
        for part in _split_keep(chunk):
            if part == "\n":
                style = {"style": r["style"], "indent": r["indent"], "done": r["done"]}
                close()
            elif part == OBJ and r["attachment"] and r["attachment"][0] in seen:
                continue                                         # named again: shown once (a damaged body)
            elif part == OBJ and r["attachment"]:
                seen.add(r["attachment"][0])
                if spans:
                    style = {"style": r["style"], "indent": r["indent"], "done": r["done"]}
                    close()
                blocks.append({"kind": "attachment", "id": r["attachment"][0], "uti": r["attachment"][1]})
            elif part:
                style = {"style": r["style"], "indent": r["indent"], "done": r["done"]}
                spans.append((part.replace(OBJ, ""), fmt, r["link"]))
    if spans:
        close()
    # numbered lists count per indent, starting again after anything else
    counts: dict[int, int] = {}
    for b in blocks:
        if b["kind"] == "para" and b["style"] == "number":
            counts = {k: v for k, v in counts.items() if k <= b["indent"]}
            counts[b["indent"]] = counts.get(b["indent"], 0) + 1
            b["number"] = counts[b["indent"]]
        elif not (b["kind"] == "para" and b["style"] in LISTS):
            counts = {}
    # an empty line after an attachment is the attachment's own line break: not a paragraph of its own
    out = []
    for i, b in enumerate(blocks):
        if (b["kind"] == "para" and not b["text"] and b["style"] not in LISTS and i and
                blocks[i - 1]["kind"] == "attachment"):
            continue
        out.append(b)
    return out


def _split_keep(s: str):
    """Split on newlines and U+FFFC, keeping them as their own pieces."""
    return (p for p in _BREAKS.split(s) if p)


# -- mergeable data: tables and galleries ---------------------------------------------------------------------

def _mergeable(data) -> Optional[dict]:
    """MergableDataProto.mergable_data_object(2).mergeable_data_object_data(3) as
    {"entries", "keys", "types", "uuids"}."""
    raw = unzip(data)
    if not raw:
        return None
    obj = _one(fields(raw), 2)
    d = _one(fields(obj), 3) if isinstance(obj, bytes) else None
    if not isinstance(d, bytes):
        return None
    m = fields(d)
    return {"entries": [fields(e) for e in m.get(3, []) if isinstance(e, bytes)],
            "keys": [_str(k) for k in m.get(4, [])], "types": [_str(t) for t in m.get(5, [])],
            "uuids": [bytes(u) for u in m.get(6, [])]}


def _objid(b) -> dict:
    return fields(b) if isinstance(b, bytes) else {}


def table(data) -> Optional[list[list[str]]]:
    """A table attachment's cells, row by row, as on the phone; None if it can't be read. Every step is linear in
    the blob (UUIDs by a dict, each object read once), so a damaged or hostile table can't hold the backup long."""
    md = _mergeable(data)
    if not md:
        return None
    entries, keys, types, uuids = md["entries"], md["keys"], md["types"], md["uuids"]
    uuid_at: dict[bytes, int] = {}
    for n, u in enumerate(uuids):
        uuid_at.setdefault(u, n)                                  # the first, as list.index would

    def custom(e):
        cm = _one(e, 13)
        return fields(cm) if isinstance(cm, bytes) else None

    stands_for: dict[int, Optional[int]] = {}

    def uuid_index(i) -> Optional[int]:
        """The UUID an object stands for: its custom map's first value (an index into the UUID list)."""
        if not isinstance(i, int) or not 0 <= i < len(entries):
            return None
        if i not in stands_for:
            cm = custom(entries[i])
            stands_for[i] = _one(_objid(_one(fields(cm[3][0]), 2)), 2) if cm and cm.get(3) else None
        return stands_for[i]

    def dict_elements(msg) -> list[tuple[dict, dict]]:
        return [(_objid(_one(fields(el), 1)), _objid(_one(fields(el), 2))) for el in msg.get(1, [])]

    root = None
    for e in entries:
        cm = custom(e)
        if cm and 0 <= _int(_one(cm, 1, -1), -1) < len(types) and types[_one(cm, 1)] == "com.apple.notes.ICTable":
            root = cm
            break
    if root is None:
        return None
    parts = {}
    for me in root.get(3, []):
        f = fields(me)
        k = _int(_one(f, 1, -1), -1)
        if 0 <= k < len(keys):
            parts[keys[k]] = _one(_objid(_one(f, 2)), 6)

    def order(i) -> dict[int, int]:
        """An ordered set (crRows / crColumns): UUID index -> position."""
        if not isinstance(i, int) or not 0 <= i < len(entries):
            return {}
        os_ = fields(_one(entries[i], 16, b"") or b"")
        ordering = fields(_one(os_, 1, b"") or b"")
        arr = fields(_one(ordering, 1, b"") or b"")
        pos: dict[int, int] = {}
        for n, a in enumerate(arr.get(2, [])):
            u = _one(fields(a), 2)
            if isinstance(u, bytes) and u in uuid_at:
                pos[uuid_at[u]] = n
        contents = fields(_one(ordering, 2, b"") or b"")
        for k, v in dict_elements(contents):
            ku, vu = uuid_index(_one(k, 6)), uuid_index(_one(v, 6))
            if ku in pos and vu is not None:
                pos[vu] = pos[ku]
        return pos

    rows, cols = order(parts.get("crRows")), order(parts.get("crColumns"))
    if not rows or not cols:
        return None
    nr, nc = max(rows.values()) + 1, max(cols.values()) + 1
    if nr * nc > MAX_CELLS:
        return None
    grid = [["" for _ in range(nc)] for _ in range(nr)]
    vi_of: dict[int, int] = {}                                    # a column -> its cells (a dictionary), last wins
    cc = parts.get("cellColumns")
    if isinstance(cc, int) and 0 <= cc < len(entries):
        for k, v in dict_elements(fields(_one(entries[cc], 6, b"") or b"")):
            col = cols.get(uuid_index(_one(k, 6)))
            vi = _one(v, 6)
            if col is not None and isinstance(vi, int) and 0 <= vi < len(entries):
                vi_of[col] = vi
    cells_of: dict[int, dict[int, int]] = {}                       # a dictionary -> {row: its cell}, read once

    def cells(vi) -> dict[int, int]:
        if vi not in cells_of:
            in_rows: dict[int, int] = {}
            for rk, rv in dict_elements(fields(_one(entries[vi], 6, b"") or b"")):
                row = rows.get(uuid_index(_one(rk, 6)))
                ci = _one(rv, 6)
                if row is not None and isinstance(ci, int) and 0 <= ci < len(entries):
                    in_rows[row] = ci                              # the last one, as before
            cells_of[vi] = in_rows
        return cells_of[vi]

    texts: dict[int, Optional[str]] = {}
    for col, vi in vi_of.items():                                 # at most rows x columns writes (MAX_CELLS)
        for row, ci in cells(vi).items():
            if ci not in texts:
                cell = _one(entries[ci], 10)
                texts[ci] = _str(_one(fields(cell), 2)).replace(OBJ, "").strip("\n") if isinstance(cell, bytes) else None
            if texts[ci] is not None:
                grid[row][col] = texts[ci]
    return grid


def gallery_order(data, ids: list[str]) -> list[str]:
    """A gallery's pages in its own order (the order their identifiers appear in its data); the rest after. One
    pass over the data, whatever the number of pages."""
    raw = unzip(data) or b""
    want = {i.upper() for i in ids}
    first: dict[str, int] = {}
    for m in _UUID.finditer(raw):
        u = m.group().decode().upper()
        if u in want and u not in first:
            first[u] = m.start()
    return sorted(ids, key=lambda i: (i.upper() not in first, first.get(i.upper(), 0)))


# -- plain text --------------------------------------------------------------------------------------------------

KIND_LABEL = {"image": "Image", "drawing": "Drawing", "scan": "Scanned document", "pdf": "PDF", "audio": "Audio",
              "video": "Video", "link": "Link", "file": "File", "table": "Table", "gallery": "Scanned pages"}


def prefix(b: dict) -> str:
    s = b["style"]
    if s == "bullet":
        return "• "
    if s == "dash":
        return "– "
    if s == "number":
        return f"{b['number']}. "
    if s == "check":
        return "☑ " if b["done"] else "☐ "
    return ""


def plain(blocks: list[dict], attachments: dict) -> str:
    """The note as text: lists and checklists marked, tables as tab-separated rows, attachments named."""
    out = []
    for b in blocks:
        if b["kind"] == "para":
            out.append("    " * min(MAX_INDENT, _int(b["indent"])) + prefix(b) + b["text"])
            continue
        a = attachments.get(b["id"]) or {}
        kind = a.get("kind") or "file"
        if kind == "table" and a.get("rows"):
            out.extend("\t".join(r) for r in a["rows"])
        elif kind == "link" and a.get("url"):
            out.append(a["url"])
        else:
            label = KIND_LABEL.get(kind, "File")
            n = len(a.get("items") or [])
            out.append(f"[{label}{f' ({n})' if n else ''}{': ' + a['name'] if a.get('name') else ''}]")
    return "\n".join(out)
