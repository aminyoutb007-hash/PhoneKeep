"""D4: Notes with folders, attachments and PDF (docs/spec/08-personal-data.md#d4-notes).

Done when: "A note with a table, a checklist and two images looks the same as on the phone and in its PDF."
On an invented backup (every note, folder, picture and word is made up), whose NoteStore.sqlite is written the way
iOS writes it (gzipped protobuf bodies with attribute runs, attachments in ZICCLOUDSYNCINGOBJECT with their files
under Accounts/<account>/Media|FallbackImages|FallbackPDFs|Previews, a table as Apple's mergeable data):
- the body is read with its styles: title, heading, checklist (ticked and not), bullets, numbered list, monospaced,
  bold, underline, strikethrough and a link, with run lengths in UTF-16 units (an emoji before a bold word);
- attachments: two images, a table (rows and columns in the table's own order, cells moved by an edit still in
  place), audio, a drawing (its fallback image), a scanned document (its PDF), a gallery of scanned pages in the
  gallery's own order, and one whose file isn't in the backup;
- folders: nested folders, Pinned, Recently Deleted; a locked note says "Locked on your iPhone";
- the phone window shows the folders, the notes of the one chosen, and the note as on the phone: checkboxes,
  list marks, the two images and the table drawn in the note, the audio as a line that opens it;
- Save this note as PDF / Save these as PDF: the PDF has the table's cells row by row, the checklist's boxes, the
  two images, and one page per note; Save this note (.txt) has the checklist and the table as text;
- an older Notes database without these columns still opens, as plain text.
"""
import datetime as dt, gzip, hashlib, io, json, os, plistlib, re, shutil, sqlite3, subprocess, sys, tempfile, time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


import phonekeep as wv
import sections as sx
import notes_doc
from PIL import Image

W = HERE / "work" / "d4"
shutil.rmtree(W, ignore_errors=True)
BK = W / "Backups" / "00008030-D4NOTESTEST00000"
BK.mkdir(parents=True)
E = wv.APPLE_EPOCH
t0 = dt.datetime(2026, 3, 1, 9, 0).timestamp() - E
with open(BK / "Info.plist", "wb") as f:
    plistlib.dump({"Device Name": "Test iPhone", "Product Type": "iPhone16,2", "Product Version": "26.1",
                   "Last Backup Date": dt.datetime(2026, 3, 10, 22, 0)}, f)
with open(BK / "Manifest.plist", "wb") as f:
    plistlib.dump({"IsEncrypted": False}, f)
man = sqlite3.connect(BK / "Manifest.db")
man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
DOM = "AppDomainGroup-group.com.apple.notes"


def add(domain, rel, data: bytes):
    fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
    (BK / fid[:2]).mkdir(exist_ok=True)
    (BK / fid[:2] / fid).write_bytes(data)
    man.execute("INSERT INTO Files VALUES (?,?,?,1,NULL)", (fid, domain, rel))


# -- protobuf, written the way Notes writes it ---------------------------------------------------------------------
def varint(n: int) -> bytes:
    out = b""
    while True:
        b7, n = n & 0x7F, n >> 7
        out += bytes([b7 | (0x80 if n else 0)])
        if not n:
            return out


def fld(num: int, v) -> bytes:
    if isinstance(v, int):
        return varint(num << 3) + varint(v)
    if isinstance(v, str):
        v = v.encode()
    return varint((num << 3) | 2) + varint(len(v)) + v


def msg(*pairs) -> bytes:
    return b"".join(fld(n, v) for n, v in pairs)


def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


STYLE = {"title": 0, "heading": 1, "subheading": 2, "mono": 4, "bullet": 100, "dash": 101, "number": 102,
         "check": 103}


def run(text, style=None, indent=0, done=None, bold=False, italic=False, underline=False, strike=False, link=None,
        att=None):
    """One attribute run over `text`; a paragraph style goes on every run of its line, newline included."""
    parts = [(1, u16(text))]
    if style is not None:
        ps = [(1, STYLE[style])]
        if indent:
            ps.append((4, indent))
        if style == "check":
            ps.append((5, msg((1, uuid.uuid4().bytes), (2, 1 if done else 0))))
        parts.append((2, msg(*ps)))
    if bold or italic:
        parts.append((5, 3 if bold and italic else 1 if bold else 2))
    if underline:
        parts.append((6, 1))
    if strike:
        parts.append((7, 1))
    if link:
        parts.append((9, link))
    if att:
        parts.append((12, msg((1, att[0]), (2, att[1]))))
    return text, msg(*parts)


def note_blob(runs) -> bytes:
    text = "".join(t for t, _r in runs)
    note = msg((2, text), *[(5, r) for _t, r in runs])
    return gzip.compress(msg((2, msg((2, 0), (3, note)))))


def U() -> str:
    return str(uuid.uuid4()).upper()


# -- a table as mergeable data: crRows / crColumns ordered sets, cellColumns dictionary --------------------------
def table_blob(cells: list[list[str]]) -> bytes:
    """cells[r][c]. The UUID list is shuffled and the rows' ordering refers to the cells' row objects through
    the ordering's contents dictionary, as after an edit on the phone, so the order must come from the table."""
    nr, nc = len(cells), len(cells[0])
    rows = [uuid.uuid4().bytes for _ in range(nr)]
    rows_cell = [uuid.uuid4().bytes for _ in range(nr)]           # the row objects cells point at (moved by an edit)
    cols = [uuid.uuid4().bytes for _ in range(nc)]
    uuids = list(reversed(rows + rows_cell + cols))
    keys = ["crRows", "crColumns", "cellColumns", "UUIDIndex"]
    types = ["com.apple.CRDT.NSUUID", "com.apple.notes.ICTable", "com.apple.CRDT.NSString"]
    entries: list[bytes] = []

    def objid(i):
        return msg((6, i))

    def uuid_entry(u):
        entries.append(msg((13, msg((1, 0), (3, msg((1, 3), (2, msg((2, uuids.index(u))))))))))
        return len(entries) - 1
    root_at = len(entries)
    entries.append(b"")                                            # filled in below
    row_e = {u: uuid_entry(u) for u in rows}
    rowc_e = {u: uuid_entry(u) for u in rows_cell}
    col_e = {u: uuid_entry(u) for u in cols}

    def ordered(order, remap):
        arr = msg((1, msg((2, ""))), *[(2, msg((1, i), (2, u))) for i, u in enumerate(order)])
        contents = msg(*[(1, msg((1, objid(remap[0][u])), (2, objid(remap[1][u])))) for u in order]) if remap else b""
        entries.append(msg((16, msg((1, msg((1, arr), (2, contents))), (2, b"")))))
        return len(entries) - 1
    rows_at = ordered(rows, (row_e, {rows[i]: rowc_e[rows_cell[i]] for i in range(nr)}))
    cols_at = ordered(cols, None)
    col_dicts = []
    for c in range(nc):
        els = []
        for r in range(nr):
            entries.append(msg((10, msg((2, cells[r][c])))))
            els.append((1, msg((1, objid(rowc_e[rows_cell[r]])), (2, objid(len(entries) - 1)))))
        entries.append(msg((6, msg(*els))))
        col_dicts.append(len(entries) - 1)
    entries.append(msg((6, msg(*[(1, msg((1, objid(col_e[cols[c]])), (2, objid(col_dicts[c])))) for c in range(nc)]))))
    cells_at = len(entries) - 1
    entries[root_at] = msg((13, msg((1, 1), (3, msg((1, 0), (2, objid(rows_at)))), (3, msg((1, 1), (2, objid(cols_at)))),
                                     (3, msg((1, 2), (2, objid(cells_at)))))))
    data = msg(*[(3, e) for e in entries], *[(4, k) for k in keys], *[(5, t) for t in types], *[(6, u) for u in uuids])
    return gzip.compress(msg((2, msg((2, 0), (3, data)))))


def jpeg(color, size=(240, 160)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "JPEG", quality=85)
    return b.getvalue()


def png(color, size=(200, 120)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


ACC = U()
TABLE = [["Day", "Place", "Cost"], ["Mon", "Seaside café", "12"], ["Tue", "Hill walk", "0"], ["Wed", "Museum", "8"]]
IMG1, IMG2, TBL, AUD, DRAW, SCAN, GAL, MISS = (U() for _ in range(8))
PAGES = [U(), U(), U()]                       # a gallery of scanned pages, stored out of order
M1, M2, MA, MP1, MP2, MP3, MMISS = (U() for _ in range(7))

trip = [run("Weekend trip\n", "title"),
        run("Packing\n", "heading"),
        run("Passport\n", "check", done=True), run("Charger\n", "check", done=False),
        run("Sun cream\n", "check", indent=1, done=False),
        run("Snacks\n", "bullet"), run("Tickets\n", "dash"),
        run("Book train\n", "number"), run("Pack bags\n", "number"),
        run("Lunch 🥪 "), run("bold", bold=True), run(" and "), run("underlined", underline=True), run(", "),
        run("crossed", strike=True), run(", a "), run("link", link="https://example.org/trip"), run("\n"),
        run("code = 42\n", "mono"),
        run(notes_doc.OBJ, att=(IMG1, "public.jpeg")), run("\n"),
        run(notes_doc.OBJ, att=(IMG2, "public.jpeg")), run("\n"),
        run(notes_doc.OBJ, att=(TBL, "com.apple.notes.table")), run("\n"),
        run(notes_doc.OBJ, att=(AUD, "com.apple.m4a-audio")), run("\n"),
        run("The end")]
other = [run("Receipts\n", "title"), run(notes_doc.OBJ, att=(GAL, "com.apple.notes.gallery")), run("\n"),
         run(notes_doc.OBJ, att=(DRAW, "com.apple.paper")), run("\n"),
         run(notes_doc.OBJ, att=(SCAN, "com.apple.paper.doc.scan")), run("\n"),
         run(notes_doc.OBJ, att=(MISS, "com.apple.m4a-audio")), run("\n"), run("Kept for taxes")]
pinned = [run("Door code\n", "title"), run("Ask at the desk")]
gone = [run("Old list\n", "title"), run("Nothing here")]
nested = [run("Plant care\n", "title"), run("Water on Sundays")]

objs = [  # Z_PK, title1, title2 (folder name), folder, notedata, created, modified, locked, deleted mark, pinned,
          # folder type, parent, identifier, uti, media, filename, mergeable, url, parentattachment
    (1, None, "Holidays", None, None, None, None, 0, 0, 0, 0, None, U(), None, None, None, None, None, None),
    (2, None, "Home", None, None, None, None, 0, 0, 0, 0, None, U(), None, None, None, None, None, None),
    (3, None, "Garden", None, None, None, None, 0, 0, 0, 0, 2, U(), None, None, None, None, None, None),
    (4, None, "Recently Deleted", None, None, None, None, 0, 0, 0, 1, None, U(), None, None, None, None, None, None),
    (10, "Weekend trip", None, 1, 100, t0, t0 + 900, 0, 0, 0, None, None, U(), None, None, None, None, None, None),
    (11, "Receipts", None, 2, 101, t0, t0 + 800, 0, 0, 0, None, None, U(), None, None, None, None, None, None),
    (12, "Door code", None, 2, 102, t0, t0 + 100, 0, 0, 1, None, None, U(), None, None, None, None, None, None),
    (13, "Old list", None, 4, 103, t0, t0 + 50, 0, 0, 0, None, None, U(), None, None, None, None, None, None),
    (14, "Plant care", None, 3, 104, t0, t0 + 60, 0, 0, 0, None, None, U(), None, None, None, None, None, None),
    (15, "Bank details", None, 2, 105, t0, t0 + 70, 1, 0, 0, None, None, U(), None, None, None, None, None, None),
    (16, "Erased", None, 2, 106, t0, t0 + 80, 0, 1, 0, None, None, U(), None, None, None, None, None, None),
    # attachments and their media
    (30, None, None, None, None, None, None, 0, 0, 0, None, None, IMG1, "public.jpeg", 50, None, None, None, None),
    (31, None, None, None, None, None, None, 0, 0, 0, None, None, IMG2, "public.jpeg", 51, None, None, None, None),
    (32, None, None, None, None, None, None, 0, 0, 0, None, None, TBL, "com.apple.notes.table", None, None,
     table_blob(TABLE), None, None),
    (33, None, None, None, None, None, None, 0, 0, 0, None, None, AUD, "com.apple.m4a-audio", 52, None, None, None, None),
    (34, None, None, None, None, None, None, 0, 0, 0, None, None, DRAW, "com.apple.paper", None, None, None, None, None),
    (35, None, None, None, None, None, None, 0, 0, 0, None, None, SCAN, "com.apple.paper.doc.scan", None, None, None,
     None, None),
    (36, None, None, None, None, None, None, 0, 0, 0, None, None, GAL, "com.apple.notes.gallery", None, None,
     gzip.compress(b"\x12\x00" + ("|".join([PAGES[2], PAGES[0], PAGES[1]])).encode()), None, None),
    (37, None, None, None, None, None, None, 0, 0, 0, None, None, PAGES[0], "public.jpeg", 53, None, None, None, 36),
    (38, None, None, None, None, None, None, 0, 0, 0, None, None, PAGES[1], "public.jpeg", 54, None, None, None, 36),
    (39, None, None, None, None, None, None, 0, 0, 0, None, None, PAGES[2], "public.jpeg", 55, None, None, None, 36),
    (40, None, None, None, None, None, None, 0, 0, 0, None, None, MISS, "com.apple.m4a-audio", 56, None, None, None, None),
    (50, None, None, None, None, None, None, 0, 0, 0, None, None, M1, None, None, "IMG_0101.jpeg", None, None, None),
    (51, None, None, None, None, None, None, 0, 0, 0, None, None, M2, None, None, "IMG_0102.jpeg", None, None, None),
    (52, None, None, None, None, None, None, 0, 0, 0, None, None, MA, None, None, "Recording.m4a", None, None, None),
    (53, None, None, None, None, None, None, 0, 0, 0, None, None, MP1, None, None, "Page.jpeg", None, None, None),
    (54, None, None, None, None, None, None, 0, 0, 0, None, None, MP2, None, None, "Page.jpeg", None, None, None),
    (55, None, None, None, None, None, None, 0, 0, 0, None, None, MP3, None, None, "Page.jpeg", None, None, None),
    (56, None, None, None, None, None, None, 0, 0, 0, None, None, MMISS, None, None, "Lost.m4a", None, None, None),
]
p = W / "NoteStore.sqlite"
c = sqlite3.connect(p)
c.executescript("""
CREATE TABLE ZICCLOUDSYNCINGOBJECT(Z_PK INTEGER PRIMARY KEY, ZTITLE1, ZTITLE2, ZFOLDER, ZNOTEDATA, ZCREATIONDATE1,
 ZMODIFICATIONDATE1, ZISPASSWORDPROTECTED, ZMARKEDFORDELETION, ZISPINNED, ZFOLDERTYPE, ZPARENT, ZIDENTIFIER,
 ZTYPEUTI, ZMEDIA, ZFILENAME, ZMERGEABLEDATA1, ZURLSTRING, ZPARENTATTACHMENT, ZSNIPPET, ZCREATIONDATE3);
CREATE TABLE ZICNOTEDATA(Z_PK INTEGER PRIMARY KEY, ZNOTE, ZDATA);""")
c.executemany("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (" + ",".join("?" * 21) + ")",
              [o + ("", None) for o in objs])
c.executemany("INSERT INTO ZICNOTEDATA VALUES (?,?,?)", [
    (100, 10, note_blob(trip)), (101, 11, note_blob(other)), (102, 12, note_blob(pinned)),
    (103, 13, note_blob(gone)), (104, 14, note_blob(nested)), (105, 15, b"\x00encrypted"),
    (106, 16, note_blob(gone))])
c.commit()
c.close()
add(DOM, "NoteStore.sqlite", p.read_bytes())
RED, BLUE = (220, 40, 40), (40, 80, 220)
add(DOM, f"Accounts/{ACC}/Media/{M1}/1_{U()}/IMG_0101.jpeg", jpeg(RED))
add(DOM, f"Accounts/{ACC}/Media/{M2}/IMG_0102.jpeg", jpeg(BLUE))              # an older layout: no generation folder
add(DOM, f"Accounts/{ACC}/Media/{MA}/1_{U()}/Recording.m4a", b"\x00\x00\x00\x18ftypM4A " + b"\0" * 64)
for m, col in ((MP1, (10, 200, 10)), (MP2, (200, 200, 10)), (MP3, (10, 200, 200))):
    add(DOM, f"Accounts/{ACC}/Media/{m}/1_{U()}/Page.jpeg", jpeg(col, (120, 170)))
add(DOM, f"Accounts/{ACC}/FallbackImages/{DRAW}/3_{U()}/FallbackImage.png", png((90, 90, 90)))
add(DOM, f"Accounts/{ACC}/FallbackPDFs/{SCAN}/8_{U()}/FallbackPDF.pdf", b"%PDF-1.4\n%invented\n")
add(DOM, f"Accounts/{ACC}/Previews/{SCAN}-1-192x256-0.png", png((240, 240, 240), (96, 128)))
man.commit()
man.close()

# -- reading ---------------------------------------------------------------------------------------------------------
reader = wv.BackupReader(BK, None, lambda m: None)
ctx = sx.Ctx(reader, W / "out", lambda m: None, False, {})
notes = sx.load_notes(ctx)
by = {n["title"]: n for n in notes}
check(set(by) == {"Weekend trip", "Receipts", "Door code", "Old list", "Plant care", "Bank details"},
      f"every note but the erased one is read ({sorted(by)})")
t = by["Weekend trip"]
paras = [b for b in t["blocks"] if b["kind"] == "para"]
styles = [(b["style"], b["text"]) for b in paras]
check(styles[:9] == [("title", "Weekend trip"), ("heading", "Packing"), ("check", "Passport"), ("check", "Charger"),
                     ("check", "Sun cream"), ("bullet", "Snacks"), ("dash", "Tickets"), ("number", "Book train"),
                     ("number", "Pack bags")], f"each line has its style: {styles[:9]}")
checks = [(b["text"], b["done"], b["indent"]) for b in paras if b["style"] == "check"]
check(checks == [("Passport", True, 0), ("Charger", False, 0), ("Sun cream", False, 1)],
      f"the checklist keeps its ticks and indent: {checks}")
check([b["number"] for b in paras if b["style"] == "number"] == [1, 2], "the numbered list counts 1, 2")
rich = next(b for b in paras if b["text"].startswith("Lunch"))
fmts = {s[0]: (s[1], s[2]) for s in rich["spans"]}
check(fmts.get("bold") == ({"bold"}, None) and fmts.get("underlined") == ({"underline"}, None)
      and fmts.get("crossed") == ({"strike"}, None) and fmts.get("link") == (set(), "https://example.org/trip"),
      f"bold, underline, strikethrough and a link sit on the right words after an emoji (UTF-16 lengths): {fmts}")
check(("mono", "code = 42") in styles, "monospaced text is kept")
atts = [t["attachments"][b["id"]] for b in t["blocks"] if b["kind"] == "attachment"]
check([a["kind"] for a in atts] == ["image", "image", "table", "audio"],
      f"the note's attachments in order: two images, a table, an audio ({[a['kind'] for a in atts]})")
check([a["file"][1].rsplit("/", 1)[-1] if a["file"] else None for a in atts] ==
      ["IMG_0101.jpeg", "IMG_0102.jpeg", None, "Recording.m4a"], "each image and the audio is found in the backup")
check(atts[2]["rows"] == TABLE, f"the table reads row by row in the table's own order: {atts[2]['rows']}")
check(ctx.read(*atts[0]["file"]) == jpeg(RED), "  an image's bytes are the backup's")
check("☑ Passport" in t["text"] and "☐ Charger" in t["text"] and "    ☐ Sun cream" in t["text"]
      and "1. Book train" in t["text"] and "Mon\tSeaside café\t12" in t["text"] and "[Image: IMG_0101.jpeg]" in t["text"],
      "the note as text marks the checklist, the list and the table's rows, and names the images")
r = by["Receipts"]
ra = [r["attachments"][b["id"]] for b in r["blocks"] if b["kind"] == "attachment"]
check([a["kind"] for a in ra] == ["gallery", "drawing", "scan", "audio"], f"a gallery, a drawing, a scan, an audio: "
      f"{[a['kind'] for a in ra]}")
check([k["id"] for k in ra[0]["items"]] == [PAGES[2], PAGES[0], PAGES[1]],
      "a gallery's pages come in the gallery's own order, not the database's")
check(ra[1]["file"] and ra[1]["file"][1].endswith("FallbackImage.png"), "a drawing shows its fallback image")
check(ra[2]["file"] and ra[2]["file"][1].endswith("FallbackPDF.pdf") and ra[2]["preview"] is not None,
      "a scanned document opens as its PDF, with its preview picture")
check(ra[3]["file"] is None, "an attachment whose file isn't in the backup is known to be missing")
check(by["Door code"]["pinned"] and by["Old list"]["deleted"] and by["Old list"]["folder"] == "Recently Deleted"
      and by["Plant care"]["folder"] == "Home › Garden", "pinned, Recently Deleted and a folder inside a folder")
check(by["Bank details"]["locked"] and by["Bank details"]["text"] == "🔒 Locked on your iPhone"
      and by["Bank details"]["blocks"] is None, "a locked note says it's locked on the iPhone, and nothing else")

# an older database: text only, no runs, none of the new columns (as tests/test_full_backup.py's)
old = notes_doc.paragraphs("Shopping\nMilk\nEggs", [])
check([b["text"] for b in old] == ["Shopping", "Milk", "Eggs"] and notes_doc.plain(old, {}) == "Shopping\nMilk\nEggs",
      "a body with no styles is plain lines, as before")

# -- damaged or hostile bodies: each shows as plain text or its snippet (or is left out), the others still load ----
import threading
import zlib


def bomb(mb: int) -> bytes:
    """A small gzip blob that would unpack to `mb` MB of zeros."""
    c = zlib.compressobj(9, zlib.DEFLATED, 31)
    chunk = b"\0" * (1 << 20)
    return b"".join(c.compress(chunk) for _ in range(mb)) + c.flush()


good_runs = [run("Still here\n", "title"), run("Fine", "check", done=True)]
bad = {
    "length sent as bytes": note_blob([("Bytes length\nmore", msg((1, b"\x05\x06")))]),
    "indent sent as bytes": note_blob([("Bytes indent\n", msg((1, 13), (2, msg((1, 100), (4, b"xx")))))]),
    "huge indent": note_blob([("Deep\n", msg((1, 5), (2, msg((1, 100), (4, 2 ** 30)))))]),
    "0xFF varint": gzip.compress(b"\x12" + b"\xff" * 1_000_000),
    "0xFF varint, not compressed": b"\x12" + b"\xff" * 1_000_000,
    "truncated gzip": note_blob(good_runs)[:25],
    "garbage": bytes(range(256)) * 40,
    "gzip bomb": bomb(200),
}
GALPARENT, GALPAGE = U(), U()
bad_gallery_note = note_blob([run("Odd gallery\n", "title"), run(notes_doc.OBJ, att=(GALPARENT, "com.apple.notes.gallery")),
                              run("\nafter")])


def hostile_table(n: int) -> bytes:
    """A table whose UUID list is long and whose rows' ordering names `n` UUIDs that aren't in it."""
    uuids = [uuid.uuid4().bytes for _ in range(n)]
    arr = msg((1, msg((2, ""))), *[(2, msg((1, i), (2, uuid.uuid4().bytes))) for i in range(n)])
    rows_e = msg((16, msg((1, msg((1, arr), (2, b""))), (2, b""))))
    root = msg((13, msg((1, 0), (3, msg((1, 0), (2, msg((6, 1))))), (3, msg((1, 1), (2, msg((6, 1))))))))
    data = msg((3, root), (3, rows_e), (4, "crRows"), (4, "crColumns"), (5, "com.apple.notes.ICTable"),
               *[(6, u) for u in uuids])
    return gzip.compress(msg((2, msg((2, 0), (3, data)))))


def one_column_table(nrows: int, repeats: int) -> bytes:
    """A real 1-column table of `nrows` rows (every cell "x") whose cellColumns names its one column `repeats`
    times, each time with the same cells."""
    rows_u = [uuid.uuid4().bytes for _ in range(nrows)]
    col_u = uuid.uuid4().bytes
    uuids = rows_u + [col_u]
    entries: list[bytes] = [b""]                                   # 0: the root, filled in below

    def uuid_entry(n):
        entries.append(msg((13, msg((1, 0), (3, msg((1, 3), (2, msg((2, n)))))))))
        return len(entries) - 1
    row_e = [uuid_entry(n) for n in range(nrows)]
    col_e = uuid_entry(nrows)

    def ordered(us):
        arr = msg((1, msg((2, ""))), *[(2, msg((1, i), (2, u))) for i, u in enumerate(us)])
        entries.append(msg((16, msg((1, msg((1, arr), (2, b""))), (2, b"")))))
        return len(entries) - 1
    rows_at, cols_at = ordered(rows_u), ordered([col_u])
    entries.append(msg((10, msg((2, "x")))))
    cell = len(entries) - 1
    entries.append(msg((6, msg(*[(1, msg((1, msg((6, e))), (2, msg((6, cell))))) for e in row_e]))))
    col_cells = len(entries) - 1
    el = msg((1, msg((1, msg((6, col_e))), (2, msg((6, col_cells))))))
    entries.append(msg((6, el * repeats)))
    cells_at = len(entries) - 1
    entries[0] = msg((13, msg((1, 1), (3, msg((1, 0), (2, msg((6, rows_at))))), (3, msg((1, 1), (2, msg((6, cols_at))))),
                              (3, msg((1, 2), (2, msg((6, cells_at))))))))
    data = msg(*[(3, e) for e in entries], (4, "crRows"), (4, "crColumns"), (4, "cellColumns"),
               (5, "com.apple.CRDT.NSUUID"), (5, "com.apple.notes.ICTable"), *[(6, u) for u in uuids])
    return gzip.compress(msg((2, msg((2, 0), (3, data)))))


TALL, TALL_ROWS = U(), 50_000
tall_note = note_blob([run("Tall table\n", "title")] +
                      [run(notes_doc.OBJ, att=(TALL, "com.apple.notes.table")) for _ in range(3_000)])
BIGTABLE, BIGGAL = U(), U()
GAL_PAGES = [U() for _ in range(20_000)]
big_gallery_data = gzip.compress(("".join(reversed(GAL_PAGES[:3])) + "0" * (30 << 20)).encode())
p2 = W / "NoteStore2.sqlite"
c2 = sqlite3.connect(p2)
c2.executescript("""
CREATE TABLE ZICCLOUDSYNCINGOBJECT(Z_PK INTEGER PRIMARY KEY, ZTITLE1, ZTITLE2, ZFOLDER, ZNOTEDATA, ZMODIFICATIONDATE1,
 ZIDENTIFIER, ZTYPEUTI, ZMEDIA, ZFILENAME, ZPARENTATTACHMENT, ZSNIPPET, ZMERGEABLEDATA1);
CREATE TABLE ZICNOTEDATA(Z_PK INTEGER PRIMARY KEY, ZNOTE, ZDATA);""")
rows2, data2 = [(1, None, "Tests", None, None, None, U(), None, None, None, None, None, None)], []
for k, (name, blob) in enumerate(bad.items()):
    rows2.append((10 + k, name, None, 1, 100 + k, t0 + k, U(), None, None, None, None, f"snippet of {name}", None))
    data2.append((100 + k, 10 + k, blob))
rows2.append((40, "Still here", None, 1, 140, t0 + 99, U(), None, None, None, None, None, None))
data2.append((140, 40, note_blob(good_runs)))
rows2.append((41, "Odd gallery", None, 1, 141, t0 + 98, U(), None, None, None, None, None, None))
data2.append((141, 41, bad_gallery_note))
rows2.append((50, None, None, None, None, None, GALPARENT, None, None, None, None, None, bomb(200)))   # no type
rows2.append((51, None, None, None, None, None, GALPAGE, "public.jpeg", None, None, 50, None, None))
rows2.append((60, None, None, None, None, None, BIGTABLE, "com.apple.notes.table", None, None, None, None,
              hostile_table(60_000)))
rows2.append((61, None, None, None, None, None, BIGGAL, "com.apple.notes.gallery", None, None, None, None,
              big_gallery_data))
rows2.append((62, None, None, None, None, None, TALL, "com.apple.notes.table", None, None, None, None,
              one_column_table(TALL_ROWS, 200_000)))
rows2.append((42, "Tall table", None, 1, 142, t0 + 97, U(), None, None, None, None, None, None))
data2.append((142, 42, tall_note))
DUPS = 5_000                        # rows sharing one identifier, or one media row, with as many files each
DUP_DRAW, DUP_MEDIA = U(), U()
rows2 += [(100_000 + k, None, None, None, None, None, DUP_DRAW, "com.apple.drawing.2", None, None, None, None, None)
          for k in range(DUPS)]
rows2.append((99_999, None, None, None, None, None, DUP_MEDIA, None, None, "pic.jpeg", None, None, None))
DUP_IMGS = [U() for _ in range(DUPS)]
rows2 += [(200_000 + k, None, None, None, None, None, im, "public.jpeg", 99_999, None, None, None, None)
          for k, im in enumerate(DUP_IMGS)]
dup_rels = ([f"Accounts/A/FallbackImages/{DUP_DRAW}/{k}/FallbackImage.png" for k in range(DUPS)]
            + [f"Accounts/A/Media/{DUP_MEDIA}/{k}/pic.jpeg" for k in range(DUPS)])
MANY_BOMBS = 100                   # each unpacks to 10 MB of tiny fields: under 32 MB, over MAX_BODY
small_bomb = gzip.compress(b"\x08\x01" * (5 << 20), 9)
for k in range(MANY_BOMBS):
    rows2.append((200 + k, f"Bomb {k}", None, 1, 300 + k, t0 - k, U(), None, None, None, None, f"snippet {k}", None))
    data2.append((300 + k, 200 + k, small_bomb))
rows2 += [(1000 + k, None, None, None, None, None, pg, "public.jpeg", None, None, 61, None, None)
          for k, pg in enumerate(GAL_PAGES)]
c2.executemany("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (" + ",".join("?" * 13) + ")", rows2)
c2.executemany("INSERT INTO ZICNOTEDATA VALUES (?,?,?)", data2)
c2.commit()
c2.close()
BK2 = W / "Backups" / "00008030-D4BADNOTES0000000"
BK2.mkdir(parents=True)
for f_ in ("Info.plist", "Manifest.plist"):
    shutil.copy(BK / f_, BK2 / f_)
m2 = sqlite3.connect(BK2 / "Manifest.db")
m2.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
fid2 = hashlib.sha1(f"{DOM}-NoteStore.sqlite".encode()).hexdigest()
(BK2 / fid2[:2]).mkdir(exist_ok=True)
(BK2 / fid2[:2] / fid2).write_bytes(p2.read_bytes())
m2.execute("INSERT INTO Files VALUES (?,?,?,1,NULL)", (fid2, DOM, "NoteStore.sqlite"))
m2.commit()
m2.close()
got: dict = {}


def load_bad():
    try:
        r2 = wv.BackupReader(BK2, None, lambda m: None)
        ctx2 = sx.Ctx(r2, W / "out2", lambda m: None, False, {})
        got["notes"] = sx.load_notes(ctx2)
        con2 = sqlite3.connect(p2)
        con2.row_factory = sqlite3.Row
        got["atts"] = sx._note_attachments(con2, DOM, dup_rels)
        con2.close()
    except BaseException as e:            # noqa: BLE001 - reported below
        got["error"] = e


t1 = time.time()
th = threading.Thread(target=load_bad, daemon=True)
th.start()
th.join(60)
took = time.time() - t1
bn = {n["title"]: n for n in got.get("notes", [])}
check(not th.is_alive() and "error" not in got and took < 30,
      f"damaged and hostile note bodies don't stop or hang the Notes screen ({took:.1f} s; "
      f"{type(got.get('error')).__name__ if 'error' in got else 'no error'})")
check(bn.get("Still here", {}).get("blocks") and bn["Still here"]["text"] == "Still here\n☑ Fine",
      "  a good note next to them is read as usual")
fine = {k: k in bn and isinstance(bn[k]["text"], str) and len(bn[k]["text"]) < 10_000 for k in bad}
check(all(fine.values()), f"  each damaged one is still listed, as what could be read, plain text or its snippet, "
      f"nothing huge: {[k for k, v in fine.items() if not v]}")
check(all(bn[k]["blocks"] is None for k in ("0xFF varint", "0xFF varint, not compressed", "garbage", "gzip bomb"))
      and bn["gzip bomb"]["text"] == "snippet of gzip bomb", "  one that can't be read at all falls back to the phone's snippet")
check("Still here\n☑ Fine".startswith(bn["truncated gzip"]["text"]), "  one cut short shows the part that could be read")
check(bn.get("Odd gallery", {}).get("blocks") is not None and "[Scanned pages]" in bn["Odd gallery"]["text"],
      "  a gallery whose parent has no type is still a gallery line, with no error")
ga = got.get("atts") or {}
check(BIGTABLE in ga and ga[BIGTABLE]["rows"] is None,
      "  a big table whose rows name UUIDs it doesn't have is read in one pass and shows as a table it can't read")
check(BIGGAL in ga and [k["id"] for k in ga[BIGGAL]["items"][:3]] == list(reversed(GAL_PAGES[:3]))
      and len(ga[BIGGAL]["items"]) == len(GAL_PAGES),
      "  a gallery of 20,000 pages in 30 MB of data is put in order in one pass")
check(TALL in ga and ga[TALL]["rows"] == [["x"]] * TALL_ROWS,
      "  a 1-column table of 50,000 rows whose column is named 200,000 times reads each row once")
check(ga.get(DUP_DRAW, {}).get("file") == (DOM, max(r_ for r_ in dup_rels if "FallbackImages" in r_))
      and all(ga.get(im, {}).get("file") == (DOM, max(r_ for r_ in dup_rels if "/Media/" in r_)) for im in DUP_IMGS),
      f"  {DUPS:,} rows sharing one identifier, and {DUPS:,} images sharing one media row, each with {DUPS:,} files, "
      f"look their files up once")
check(all(bn.get(f"Bomb {k}", {}).get("text") == f"snippet {k}" for k in range(MANY_BOMBS)),
      f"  {MANY_BOMBS} note bodies that each unpack to 10 MB are refused (4 MB a body, 64 MB in all) and show their "
      f"snippets")
tn = bn.get("Tall table", {})
check([b["id"] for b in tn.get("blocks") or [] if b["kind"] == "attachment"] == [TALL]
      and tn["text"].count("\n") < TALL_ROWS + 5,
      "  a note that names the same table 3,000 times shows it once")
deep = notes_doc.paragraphs("Deep\n", [{"len": 5, "style": "bullet", "indent": 10 ** 9, "done": None, "bold": False,
                                        "italic": False, "underline": False, "strike": False, "link": None,
                                        "attachment": None}])
check(len(notes_doc.plain(deep, {})) < 100, "  plain text caps an indent that came from anywhere")
check(notes_doc.unzip(bomb(200)) is None and notes_doc.unzip(gzip.compress(b"ok")) == b"ok",
      "  a gzip bomb is refused, a normal blob unpacks")

# -- the phone window ----------------------------------------------------------------------------------------------
import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import tkinter as tk
import ui
import phone
import quicklook as ql
import app as appmod
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
ql.play = lambda p: None                            # never opens another app
phone.reveal = lambda p: None
phone.open_file = lambda p: None
dest_dir = Path(tempfile.mkdtemp(prefix="pk-d4-"))
phone.ask_save_folder = lambda parent, title, start: str(dest_dir)
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(W / "Backups"),
                                            "archive_dir": str(W / "Saved")}), encoding="utf-8")
a = appmod.App()
a.after_cancel(a._timers.pop("first"))


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.01)
    return until()


pump(lambda: False, 0.3)
check(a.open_backup(BK), "the phone window opens on the invented backup")
win = a.phone_windows[-1]
pump(lambda: win.data is not None, 60)
win.open_app("notes")
pump(lambda: getattr(win, "notes_folders", None) is not None, 60)
folders, places, choose = win.notes_folders
labels = [folders.get(i) for i in range(folders.size())]
check(labels[0].startswith("All notes") and labels[1].startswith("📌 Pinned") and labels[-1].startswith("🗑 Recently Deleted")
      and any(l.startswith("Home › Garden") for l in labels), f"the folders: All, Pinned first, Recently Deleted last: "
      f"{labels}")


def trees(w):
    out = []
    for ch in w.winfo_children():
        if isinstance(ch, phone.ttk.Treeview):
            out.append(ch)
        out += trees(ch)
    return out


tree = trees(win.content)[0]
shown = [tree.item(i, "values")[0] for i in tree.get_children()]
check(shown[0] == "📌 Door code" and "Old list" not in " ".join(shown) and "🔒 Bank details" in shown,
      f"All notes: pinned first, the locked one marked, nothing from Recently Deleted: {shown}")
choose(next(i for i, p in enumerate(places) if p[0] == "deleted"))
check([tree.item(i, "values")[0] for i in tree.get_children()] == ["Old list"], "Recently Deleted has its own list")
choose(next(i for i, p in enumerate(places) if p[0] == "folder:Holidays"))
trip_iid = tree.get_children()[0]
view = win.note_view
txt = view.txt
# pictures are read in the background: one that arrives for a note no longer shown is dropped
choose(next(i for i, p in enumerate(places) if p[0] == "all"))
door = next(i for i in tree.get_children() if "Door code" in tree.item(i, "values")[0])
trip_all = str(notes.index(by["Weekend trip"]))
a.update()                                                   # earlier folder changes' redraws done
held = []
real_submit = view.submit
view.submit = lambda fn, ok: held.append((fn, ok))           # the background reads, held back until we say
tree.selection_set(trip_all)
a.update()
started = (len(held), view.pending, len(txt.image_names()))
tree.selection_set(door)
a.update()
for fn, ok in held:                                          # they finish after the other note was chosen
    ok(fn())
view.submit = real_submit
check(started[0] >= 2 and started[1:] == (2, 0) and view.pending == 0 and not txt.image_names() and view.shown["images"] == 0,
      f"pictures are read in the background, not when the note is drawn, and those for a note no longer shown "
      f"are dropped (asked, waiting, drawn at once: {started})")
choose(next(i for i, p in enumerate(places) if p[0] == "folder:Holidays"))
tree.selection_set(trip_iid)
a.update()
check(pump(lambda: view.pending == 0, 30), "  the note's pictures arrive")
body = txt.get("1.0", "end")
check("☑ Passport" in body and "☐ Charger" in body and "• Snacks" in body and "– Tickets" in body
      and "2. Pack bags" in body, "the note shows its checkboxes and list marks")
check(view.shown["images"] == 2 and len(txt.image_names()) == 2, f"the two images are drawn in the note "
      f"({view.shown['images']})")
check(view.shown["tables"] == 1 and view.tables and len(view.tables[0].grid_slaves()) == 12
      and view.tables[0].grid_slaves(row=1, column=1)[0].cget("text") == "Seaside café",
      "the table is drawn as a grid, each cell in its place")


def tags_at(word):
    i = txt.search(word, "1.0")
    return set(txt.tag_names(i)) if i else set()


check("heading" in tags_at("Packing") and "bold" in tags_at("bold") and "underline" in tags_at("underlined")
      and "strike" in tags_at("crossed") and "link" in tags_at("link") and "mono" in tags_at("code = 42")
      and "done" in tags_at("Passport") and "ind1h" in tags_at("Sun cream"),
      "headings, bold, underline, strikethrough, links, monospaced, a ticked item and an indented one look as on the phone")
opened = []
real_viewer = ql.Viewer
ql.Viewer = lambda parent, items, index=0, on_close=None: opened.append(items[index]) or None
i = txt.search("Audio", "1.0")
tag = next(t_ for t_ in txt.tag_names(i) if t_.startswith("att"))
txt.see(i)
a.update()
x, y, _w, h = txt.bbox(i)
txt.event_generate("<Motion>", x=x + 2, y=y + h // 2)      # Tk finds the tag under the pointer
txt.event_generate("<Button-1>", x=x + 2, y=y + h // 2)
a.update()
ql.Viewer = real_viewer
check(opened and opened[0].name == "Recording.m4a" and opened[0].read() is not None,
      "the audio is a line that opens it in the viewer, read from the backup")
choose(next(i for i, p in enumerate(places) if p[0] == "folder:Home"))
rec = next(i for i in tree.get_children() if tree.item(i, "values")[0] == "Receipts")
tree.selection_set(rec)
a.update()
pump(lambda: view.pending == 0, 30)
check(view.shown["images"] == 3 + 1 + 1, f"scanned pages, a drawing and a scan's preview are drawn "
      f"({view.shown['images']})")
check("(not in the backup)" in txt.get("1.0", "end"), "a missing attachment says it isn't in the backup")
lock = next(i for i in tree.get_children() if "Bank details" in tree.item(i, "values")[0])
tree.selection_set(lock)
a.update()
check("Locked on your iPhone" in txt.get("1.0", "end"), "a locked note shows a lock and 'Locked on your iPhone'")

# a note's big tables draw at most NoteView.MAX_CELLS cells (each a widget), whole rows, then say where the rest is
big_tables = {f"T{k}": {"id": f"T{k}", "kind": "table", "rows": rows_}
              for k, rows_ in enumerate([[["a"]] * 300, [["b", "c"]] * 1_000, [["d"]] * 10])}
t1 = time.time()
view.show({"title": "Big tables", "locked": False, "attachments": big_tables, "text": "",
           "blocks": [{"kind": "attachment", "id": k, "uti": "com.apple.notes.table"} for k in big_tables]})
a.update()
took = time.time() - t1
shown_txt = txt.get("1.0", "end")
check(view.MAX_CELLS == 400 and view.shown["cells"] == 400 and took < 10
      and [len(f.grid_slaves()) for f in view.tables] == [300, 100, 0],
      f"three tables of 300, 2,000 and 10 cells draw 400 cells in all, whole rows "
      f"({[len(f.grid_slaves()) for f in view.tables]}; {took:.1f} s)")
check("950 more rows: save this note as PDF or text to see them all" in shown_txt
      and "A table of 10 rows is too big to show here: save this note as PDF or text" in shown_txt,
      "  the table cut short says how many rows are left out, the one that doesn't fit says it's too big")

# E4's jump from a search hit lands on the note, whichever folder was chosen
idx = notes.index(by["Old list"])
win.find_hook[2](idx)
a.update()
check(tree.selection() == (str(idx),), "a search hit opens its note, even one in Recently Deleted")


# -- PDF and text -------------------------------------------------------------------------------------------------
def pdf_text(pdf: Path):
    if shutil.which("pdftotext"):
        r_ = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), "-"], capture_output=True)
        return r_.stdout.decode("utf-8", "replace") if r_.returncode == 0 else None
    if sys.platform == "darwin":
        try:
            from Quartz import PDFDocument
            from Foundation import NSURL
            d = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(pdf)))
            return str(d.string()) if d else None
        except Exception:
            return None
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf))
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    except Exception:
        return None


def pages(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf.read_bytes()))


def images(pdf: Path) -> int:
    return len(re.findall(rb"/DCTDecode", pdf.read_bytes()))      # photos (emoji are PNGs)


win.notes_save_pdf([by["Weekend trip"]], "Weekend trip")
pdf = dest_dir / "Weekend trip.pdf"
check(pump(lambda: pdf.exists(), 60), "Save this note as PDF makes Weekend trip.pdf")
pump(lambda: False, 0.3)
text = pdf_text(pdf) if pdf.exists() else None
check(pdf.exists() and images(pdf) == 2, f"  the PDF has the two images ({images(pdf) if pdf.exists() else 0})")
if text is None:
    print("     (no PDF text reader here: the PDF's text is checked on the other systems)")
else:
    flat = re.sub(r"[ \t]+", " ", text)
    check(all(w in flat for w in ("☑ Passport", "☐ Charger", "1. Book train", "Packing")),
          "  the PDF has the checklist's boxes, the numbered list and the heading")
    check(re.search(r"Mon\s+Seaside café\s+12", flat) and re.search(r"Wed\s+Museum\s+8", flat),
          "  the PDF has the table's cells row by row")
    check("Weekend trip" in flat and "Holidays" in flat, "  the PDF starts with the note's title and folder")
check(not list(dest_dir.glob("*.part")), "  nothing half-written is left")
choose(next(i for i, p in enumerate(places) if p[0] == "folder:Home"))
shown_now = [notes[int(i)] for i in tree.get_children()]
win.notes_save_pdf(shown_now, "Home")
many = dest_dir / "Home.pdf"
check(pump(lambda: many.exists(), 60), "Save these as PDF makes one PDF of the notes shown")
pump(lambda: False, 0.3)
want = len([n for n in shown_now if not n["locked"]])
check(many.exists() and pages(many) >= want, f"  each note starts its own page ({pages(many) if many.exists() else 0} "
      f"pages, {want} notes; the locked one is left out)")
if text is not None and many.exists():
    mt = pdf_text(many) or ""
    check("Bank details" not in mt and "Receipts" in mt and "Door code" in mt, "  the locked note isn't in it")

# Save this note (.txt)
choose(0)
tree.selection_set(str(notes.index(by["Weekend trip"])))
a.update()
before = set(dest_dir.glob("*.txt"))


def buttons(w):
    out = []
    for ch in w.winfo_children():
        if isinstance(ch, ui.RoundButton):
            out.append(ch)
        out += buttons(ch)
    return out


btn = next(b for b in buttons(win.content) if "(.txt)" in getattr(b, "text", ""))
btn.command()
a.update()
new = set(dest_dir.glob("*.txt")) - before
saved_txt = new.pop().read_text(encoding="utf-8") if new else ""
check("☑ Passport" in saved_txt and "Mon\tSeaside café\t12" in saved_txt,
      "Save this note (.txt) has the checklist and the table as text")

# Save all notes, with PDF (the Print path of Save everything)
out = W / "export"
sx.export_all(BK, out, None, ["notes"], include_media=True, log=lambda m: None, formats={"web", "pdf"})
allpdf = out / "Notes" / "PDF" / "Notes.pdf"
check(allpdf.exists() and images(allpdf) >= 2 + 3 + 1, f"Save all notes as PDF has every note's pictures "
      f"({images(allpdf) if allpdf.exists() else 0})")

for w_ in list(a.phone_windows):
    w_.destroy()
a.destroy()
print("\nD4 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
