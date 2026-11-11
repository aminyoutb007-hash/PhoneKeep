"""
PhoneKeep - full-iPhone extractors.

Each section reads one kind of data out of an iPhone backup and writes a
browsable page (plus CSV / vCard / iCal / plain files where useful):

  WhatsApp, Messages (SMS/iMessage), Photos & videos, Contacts, Calls,
  Notes, Calendar, Voicemail, Voice memos, Safari, Apps, and optionally
  every raw file in the backup.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import traceback
import zlib
from pathlib import Path
from typing import Callable, Optional

import phonekeep as wv
from phonekeep import _e, Log, PhoneKeepError

HOME = "HomeDomain"
MEDIA = "MediaDomain"
CAMERA = "CameraRollDomain"

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".dng", ".tif", ".tiff", ".bmp"}
VID_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi"}
WEB_IMG = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

try:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        HEIF = True
    except Exception:
        HEIF = False
except Exception:  # Pillow not installed: no thumbnails / HEIC conversion
    Image = None
    HEIF = False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def t2001(v) -> Optional[dt.datetime]:
    """Apple 'Cocoa' timestamp (seconds or nanoseconds since 2001) -> local datetime."""
    if v in (None, "", 0):
        return None
    try:
        v = float(v)
        if v > 1e12:
            v /= 1e9
        return dt.datetime.fromtimestamp(v + wv.APPLE_EPOCH)
    except (ValueError, OverflowError, OSError):
        return None


def fmt(d: Optional[dt.datetime], with_time=True) -> str:
    if not d:
        return ""
    return d.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def dur(sec) -> str:
    try:
        sec = int(float(sec or 0))
    except ValueError:
        return ""
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def safe_name(s: str, n: int = 80) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s or "").strip(" .")
    return s[:n] or "untitled"


def cols(con, table) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def select(con, table, wanted: list[str], extra: str = "") -> list[sqlite3.Row]:
    have = cols(con, table)
    parts = [c if c in have else f"NULL AS {c}" for c in wanted]
    return con.execute(f"SELECT {', '.join(parts)} FROM {table} {extra}").fetchall()


def phone_key(s: str) -> str:
    s = (s or "").strip().lower()
    if "@" in s:
        return s
    d = re.sub(r"\D", "", s)
    return d[-9:] if len(d) >= 7 else s


PAGE_CSS = r"""
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}
.card{display:block;background:var(--panel);border-radius:12px;padding:16px;text-decoration:none;color:var(--ink)}
.card .ic{font-size:28px}.card b{display:block;font-size:17px;margin-top:6px}
.card span{color:var(--muted);font-size:13px}.card.off{opacity:.55}
table{width:100%;border-collapse:collapse;background:var(--panel);border-radius:10px;overflow:hidden;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{position:sticky;top:58px;background:var(--panel);font-size:12.5px;color:var(--muted)}
td a{word-break:break-all}.tw{overflow-x:auto}
.note{background:var(--panel);border-radius:10px;padding:14px 16px;margin-bottom:10px}
.note h3{margin:0 0 4px;font-size:16px}.note pre{white-space:pre-wrap;font:inherit;margin:8px 0 0}
.ph{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px}
.ph a{position:relative;display:block;aspect-ratio:1;background:var(--panel);border-radius:4px;overflow:hidden;
color:var(--muted);text-decoration:none}
.ph img{width:100%;height:100%;object-fit:cover}.ph .tag{position:absolute;left:4px;bottom:4px;background:rgba(0,0,0,.6);
color:#fff;font-size:11px;padding:1px 5px;border-radius:4px}.ph .ico{display:grid;place-items:center;height:100%;font-size:30px}
h2{font-size:16px;margin:22px 0 8px}.pill{display:inline-block;background:var(--panel);border-radius:14px;padding:4px 10px;
margin:0 6px 6px 0;color:var(--ink);text-decoration:none;font-size:13px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;background:var(--panel);border-radius:10px;padding:12px 16px;margin-bottom:14px}
.kv dt{color:var(--muted)}.kv dd{margin:0}
"""

FILTER_JS = ('<script>(function(){var f=document.getElementById("f");if(!f)return;'
             'var rows=[].slice.call(document.querySelectorAll("[data-row]"));'
             'f.oninput=function(){var v=f.value.toLowerCase();rows.forEach(function(r){'
             'r.classList.toggle("hide",r.textContent.toLowerCase().indexOf(v)<0)})}})();</script>')


def page(title: str, body: str, root: str = "../", filt: bool = False, extra_head: str = "") -> str:
    """root = relative path from this page to the archive root (where assets/ lives)."""
    home = f'<a href="{root}index.html">&#8962; iPhone</a>' if root else ""
    search = '<input id="f" type="search" placeholder="Filter">' if filt else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} · {wv.APP_NAME}</title>'
            f'<link rel="stylesheet" href="{root}assets/style.css">'
            f'<link rel="stylesheet" href="{root}assets/vault.css">{extra_head}</head><body>'
            f'<header><h1>{_e(title)}</h1>{search}{home}</header>'
            f'<div class="wrap">{body}</div>{FILTER_JS if filt else ""}</body></html>')


def table(headers: list[str], rows: list[list[str]], raw_cols: set[int] = frozenset()) -> str:
    """Rows are plain text unless the column index is in raw_cols (pre-built HTML)."""
    h = "".join(f"<th>{_e(x)}</th>" for x in headers)
    b = "".join("<tr data-row>" + "".join(
        f"<td>{c if i in raw_cols else _e(c)}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


# ---------------------------------------------------------------------------
# context shared by all sections
# ---------------------------------------------------------------------------

class Ctx:
    def __init__(self, reader: wv.BackupReader, out: Path, log: Log, include_media: bool,
                 binfo: dict, progress: Optional[Callable[[float], None]] = None):
        self.reader, self.out, self.log = reader, out, log
        self.include_media, self.binfo = include_media, binfo
        self.progress = progress
        self.names: dict[str, str] = {}
        self._files: dict[str, dict[str, str]] = {}
        self.tmp = Path(reader._tmp.name)

    def files(self, domain: str) -> dict[str, str]:
        if domain not in self._files:
            self._files[domain] = self.reader.list_files(domain)
        return self._files[domain]

    def name_for(self, addr: Optional[str]) -> Optional[str]:
        if not addr:
            return None
        return self.names.get(phone_key(addr))

    def label(self, addr: Optional[str]) -> str:
        return self.name_for(addr) or (addr or "Unknown")

    def db(self, domain: str, rel: str) -> Optional[sqlite3.Connection]:
        """Extract a SQLite DB (with -wal/-shm) to temp and open it, or None if absent."""
        f = self.files(domain)
        if rel not in f:
            return None
        d = self.tmp / "db" / hashlib.sha1(f"{domain}/{rel}".encode()).hexdigest()[:12]
        d.mkdir(parents=True, exist_ok=True)
        local = d / Path(rel).name
        if not self.reader.extract(domain, rel, f[rel], local):
            return None
        for sfx in ("-wal", "-shm"):
            if rel + sfx in f:
                self.reader.extract(domain, rel + sfx, f[rel + sfx], d / (Path(rel).name + sfx))
        con = sqlite3.connect(str(local))
        con.row_factory = sqlite3.Row
        return con

    def copy(self, domain: str, rel: str, dest: Path, keep_time: bool = True) -> bool:
        """Copy one backup file to dest (skips if already there)."""
        if dest.exists() and dest.stat().st_size > 0:
            return True
        fid = self.files(domain).get(rel)
        if not fid:
            return False
        ok = self.reader.extract(domain, rel, fid, dest)
        if ok and keep_time:
            mt = self.reader.file_mtime(fid)
            if mt:
                try:
                    os.utime(dest, (mt, mt))
                except OSError:
                    pass
        return ok

    def web_image(self, src: Path, dest_jpg: Path, max_px: int = 2048) -> bool:
        """Convert an image (e.g. HEIC) into a browser-friendly JPEG."""
        if Image is None:
            return False
        if dest_jpg.exists():
            return True
        try:
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((max_px, max_px))
                dest_jpg.parent.mkdir(parents=True, exist_ok=True)
                im.convert("RGB").save(dest_jpg, "JPEG", quality=85)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Contacts (runs first: gives names to Messages, Calls, WhatsApp)
# ---------------------------------------------------------------------------

def _clean_label(l) -> str:
    l = str(l or "")
    m = re.match(r"_\$!<(.+)>!\$_", l)
    return (m.group(1) if m else l).lower()


def load_contacts(ctx: Ctx) -> list[dict]:
    con = ctx.db(HOME, "Library/AddressBook/AddressBook.sqlitedb")
    if con is None:
        return []
    labels = {}
    if "ABMultiValueLabel" in tables(con):
        labels = {r["ROWID"]: r["value"] for r in con.execute("SELECT ROWID, value FROM ABMultiValueLabel")}
    people: dict[int, dict] = {}
    for r in select(con, "ABPerson", ["ROWID", "First", "Middle", "Last", "Organization", "Nickname",
                                      "JobTitle", "Note", "Birthday"]):
        name = " ".join(x for x in (r["First"], r["Middle"], r["Last"]) if x) \
            or r["Organization"] or r["Nickname"] or ""
        bday = None
        if r["Birthday"]:
            try:
                bday = (dt.datetime(2001, 1, 1) + dt.timedelta(seconds=float(r["Birthday"]))).date()
            except (ValueError, OverflowError):
                pass
        people[r["ROWID"]] = {"name": name, "first": r["First"] or "", "last": r["Last"] or "",
                              "org": r["Organization"] or "", "title": r["JobTitle"] or "",
                              "note": r["Note"] or "", "birthday": bday.isoformat() if bday else "",
                              "phones": [], "emails": []}
    if "ABMultiValue" in tables(con):
        for r in select(con, "ABMultiValue", ["record_id", "property", "label", "value"]):
            p = people.get(r["record_id"])
            if not p or not r["value"]:
                continue
            lab = _clean_label(labels.get(r["label"], ""))
            if r["property"] == 3:
                p["phones"].append((lab, str(r["value"])))
            elif r["property"] == 4:
                p["emails"].append((lab, str(r["value"])))
    con.close()
    result = [p for p in people.values() if p["name"] or p["phones"] or p["emails"]]
    for p in result:
        nm = p["name"] or (p["phones"][0][1] if p["phones"] else p["emails"][0][1])
        p["name"] = nm
        for _, v in p["phones"] + p["emails"]:
            ctx.names.setdefault(phone_key(v), nm)
    result.sort(key=lambda p: p["name"].lower())
    return result


def sec_contacts(ctx: Ctx, people: list[dict]) -> dict:
    if not people:
        raise PhoneKeepError("No contacts in this backup.")
    d = ctx.out / "Contacts"
    d.mkdir(parents=True, exist_ok=True)

    def vesc(s):
        return str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    with open(d / "contacts.vcf", "w", encoding="utf-8", newline="") as f:
        for p in people:
            f.write("BEGIN:VCARD\r\nVERSION:3.0\r\n")
            f.write(f"N:{vesc(p['last'])};{vesc(p['first'])};;;\r\nFN:{vesc(p['name'])}\r\n")
            if p["org"]:
                f.write(f"ORG:{vesc(p['org'])}\r\n")
            if p["title"]:
                f.write(f"TITLE:{vesc(p['title'])}\r\n")
            for lab, v in p["phones"]:
                f.write(f"TEL;TYPE={(lab or 'voice').upper().replace(' ', '')}:{vesc(v)}\r\n")
            for lab, v in p["emails"]:
                f.write(f"EMAIL;TYPE=INTERNET:{vesc(v)}\r\n")
            if p["birthday"]:
                f.write(f"BDAY:{p['birthday']}\r\n")
            if p["note"]:
                f.write(f"NOTE:{vesc(p['note'])}\r\n")
            f.write("END:VCARD\r\n")
    rows = [[p["name"], "\n".join(f"{v} ({l})" if l else v for l, v in p["phones"]),
             "\n".join(v for _, v in p["emails"]), " · ".join(x for x in (p["org"], p["title"]) if x),
             p["birthday"], p["note"]] for p in people]
    hdr = ["Name", "Phone", "Email", "Company", "Birthday", "Note"]
    write_csv(d / "contacts.csv", hdr, rows)
    body = (f'<p class="meta">{len(people):,} contacts · <a href="contacts.vcf">Download vCard (.vcf)</a> '
            f'(import into iPhone, Android, Google, Outlook) · <a href="contacts.csv">CSV</a></p>'
            + table(hdr, [[*r[:5], r[5]] for r in rows]).replace("\n", "<br>"))
    (d / "index.html").write_text(page("Contacts", body, filt=True), encoding="utf-8")
    return {"count": len(people), "detail": f"{len(people):,} contacts", "link": "Contacts/index.html"}


# ---------------------------------------------------------------------------
# Messages (SMS / iMessage / RCS)
# ---------------------------------------------------------------------------

def decode_attributed_body(b: Optional[bytes]) -> str:
    """Pull the plain text out of iOS's 'typedstream' attributedBody blob."""
    if not b:
        return ""
    b = bytes(b)
    i = b.find(b"NSString")
    if i < 0:
        return ""
    i += len(b"NSString") + 5
    if i >= len(b):
        return ""
    n = b[i]
    i += 1
    if n == 0x81:
        n = int.from_bytes(b[i:i + 2], "little")
        i += 2
    elif n == 0x82:
        n = int.from_bytes(b[i:i + 3], "little")
        i += 3
    return b[i:i + n].decode("utf-8", "replace")


def sec_messages(ctx: Ctx) -> dict:
    con = ctx.db(HOME, "Library/SMS/sms.db")
    if con is None:
        raise PhoneKeepError("No Messages database in this backup.")
    t = tables(con)
    handles = {r["ROWID"]: r["id"] for r in con.execute("SELECT ROWID, id FROM handle")}
    chats: dict[int, dict] = {}
    for r in select(con, "chat", ["ROWID", "chat_identifier", "display_name", "style", "service_name"]):
        group = r["style"] == 43
        chats[r["ROWID"]] = {"id": r["ROWID"], "jid": r["chat_identifier"],
                             "name": r["display_name"] or ("" if group else ctx.label(r["chat_identifier"])),
                             "group": group, "service": r["service_name"], "messages": [], "archived": False}
    if "chat_handle_join" in t:
        members: dict[int, list[str]] = {}
        for r in con.execute("SELECT chat_id, handle_id FROM chat_handle_join"):
            members.setdefault(r[0], []).append(ctx.label(handles.get(r[1])))
        for cid, c in chats.items():
            if not c["name"]:
                ms = members.get(cid, [])
                c["name"] = ", ".join(ms[:3]) + (f" +{len(ms) - 3}" if len(ms) > 3 else "") or c["jid"] or "Group"
    msg_chat = {r[1]: r[0] for r in con.execute("SELECT chat_id, message_id FROM chat_message_join")}
    atts: dict[int, list[sqlite3.Row]] = {}
    if "message_attachment_join" in t and "attachment" in t:
        arows = {r["ROWID"]: r for r in select(con, "attachment", ["ROWID", "filename", "mime_type", "transfer_name"])}
        for mid, aid in con.execute("SELECT message_id, attachment_id FROM message_attachment_join"):
            if aid in arows:
                atts.setdefault(mid, []).append(arows[aid])

    media_files = ctx.files(MEDIA)
    mdir = ctx.out / "Messages" / "media"
    n_media = 0
    rows = select(con, "message", ["ROWID", "text", "attributedBody", "handle_id", "date", "is_from_me",
                                   "item_type", "associated_message_type", "group_title", "service"],
                  "ORDER BY date, ROWID")
    for r in rows:
        if (r["associated_message_type"] or 0) != 0:  # tapback reactions
            continue
        c = chats.get(msg_chat.get(r["ROWID"]))
        if c is None:
            continue
        when = t2001(r["date"])
        base = {"time": when.isoformat(timespec="seconds") if when else None,
                "from_me": bool(r["is_from_me"]),
                "sender": "You" if r["is_from_me"] else ctx.label(handles.get(r["handle_id"])),
                "starred": False}
        if (r["item_type"] or 0) != 0:
            txt = f"Group renamed to “{r['group_title']}”" if r["group_title"] else "Group update"
            c["messages"].append({**base, "id": r["ROWID"], "type": "system", "text": txt})
            continue
        text = (r["text"] or decode_attributed_body(r["attributedBody"]) or "").replace("\ufffc", "").strip()
        parts = []
        for k, a in enumerate(atts.get(r["ROWID"], [])):
            fn = (a["filename"] or "")
            rel = re.sub(r"^(~/|/var/mobile/|/private/var/mobile/)", "", fn)
            mime = a["mime_type"] or ""
            typ = ("image" if mime.startswith("image/") else "video" if mime.startswith("video/")
                   else "audio" if mime.startswith("audio/") else "document")
            m = {**base, "id": f"{r['ROWID']}-{k}", "type": typ, "text": "",
                 "caption": a["transfer_name"] or Path(rel).name}
            if rel in media_files and ctx.include_media:
                sub = rel.split("Attachments/", 1)[-1]
                dest = mdir / sub
                if ctx.copy(MEDIA, rel, dest):
                    n_media += 1
                    shown = dest
                    if dest.suffix.lower() in (".heic", ".heif", ".tif", ".tiff"):
                        jpg = dest.with_suffix(".jpg")
                        if ctx.web_image(dest, jpg):
                            shown = jpg
                    m["media"] = "media/" + shown.relative_to(mdir).as_posix()
                    if typ == "image":
                        m.pop("caption", None)
                else:
                    m["media_missing"] = True
            else:
                m["media_missing"] = True
            parts.append(m)
        if text or not parts:
            c["messages"].append({**base, "id": r["ROWID"], "type": "text", "text": text})
        c["messages"].extend(parts)
    con.close()

    # merge iMessage/SMS threads with the same person into one conversation
    merged: dict[str, dict] = {}
    for c in chats.values():
        if not c["messages"]:
            continue
        key = "g" + str(c["id"]) if c["group"] else "p" + phone_key(c["jid"] or str(c["id"]))
        if key in merged:
            merged[key]["messages"].extend(c["messages"])
        else:
            merged[key] = c
    result = list(merged.values())
    for c in result:
        c["messages"].sort(key=lambda m: m["time"] or "")
    result.sort(key=lambda c: c["messages"][-1]["time"] or "", reverse=True)
    n = sum(len(c["messages"]) for c in result)
    ctx.log(f"Messages: {len(result):,} conversations, {n:,} messages, {n_media:,} attachments.")
    if not result:
        raise PhoneKeepError("No messages found.")
    wv.write_archive(result, ctx.out / "Messages", ctx.binfo, ctx.log, title="Messages", hub=True)
    return {"count": n, "detail": f"{len(result):,} conversations · {n:,} messages",
            "link": "Messages/index.html"}


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------

def sec_whatsapp(ctx: Ctx) -> dict:
    r = wv.export_whatsapp(ctx.reader, ctx.out / "WhatsApp", ctx.include_media, False, ctx.log,
                           None, ctx.binfo, ctx.name_for, hub=True)
    r["link"] = "WhatsApp/index.html"
    return r


# ---------------------------------------------------------------------------
# Photos & videos
# ---------------------------------------------------------------------------

def _photo_date(p: Path) -> dt.datetime:
    if Image is not None and p.suffix.lower() in IMG_EXT:
        try:
            with Image.open(p) as im:
                ex = im.getexif()
                v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
                if v:
                    return dt.datetime.strptime(str(v)[:19], "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return dt.datetime.fromtimestamp(p.stat().st_mtime)


def sec_photos(ctx: Ctx) -> dict:
    d = ctx.out / "Photos"
    orig = d / "Originals"
    files = ctx.files(CAMERA)
    from_backup = {rel: fid for rel, fid in files.items() if rel.startswith("Media/DCIM/")}
    if from_backup and ctx.include_media:
        ctx.log(f"Copying {len(from_backup):,} camera-roll files from the backup...")
        for i, rel in enumerate(from_backup, 1):
            ctx.copy(CAMERA, rel, orig / rel[len("Media/"):])
            if i % 500 == 0:
                ctx.log(f"  {i:,}/{len(from_backup):,}")
    items = [p for p in orig.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXT | VID_EXT] \
        if orig.exists() else []
    if not items:
        raise PhoneKeepError("No photos in this backup. If iCloud Photos is on, iOS leaves the library "
                              "out of backups: use 'Copy photos directly' in the app.")
    stems = {(p.parent, p.stem.upper()) for p in items if p.suffix.lower() in IMG_EXT}
    live = {(p.parent, p.stem.upper()): p for p in items
            if p.suffix.lower() == ".mov" and (p.parent, p.stem.upper()) in stems}
    items = [p for p in items if not (p.suffix.lower() == ".mov" and (p.parent, p.stem.upper()) in stems)]

    ctx.log(f"Building photo gallery for {len(items):,} items" + (" (making thumbnails)..." if Image else "..."))
    thumbs = d / ".thumbs"
    by_year: dict[int, list[tuple[dt.datetime, Path]]] = {}
    for i, p in enumerate(items, 1):
        when = _photo_date(p)
        by_year.setdefault(when.year, []).append((when, p))
        if p.suffix.lower() in IMG_EXT and Image is not None:
            ctx.web_image(p, thumbs / (hashlib.sha1(str(p.relative_to(orig)).encode()).hexdigest()[:16] + ".jpg"), 360)
        if i % 500 == 0:
            ctx.log(f"  {i:,}/{len(items):,}")

    def tile(when: dt.datetime, p: Path) -> str:
        rel = p.relative_to(d).as_posix()
        th = thumbs / (hashlib.sha1(str(p.relative_to(orig)).encode()).hexdigest()[:16] + ".jpg")
        ext = p.suffix.lower()
        if th.exists():
            inner = f'<img loading="lazy" src=".thumbs/{th.name}" alt="">'
        elif ext in WEB_IMG:
            inner = f'<img loading="lazy" src="{_e(rel)}" alt="">'
        else:
            inner = f'<div class="ico">{"&#9654;" if ext in VID_EXT else "&#128247;"}</div>'
        tag = "LIVE" if (p.parent, p.stem.upper()) in live else ("&#9654;" if ext in VID_EXT else "")
        lv = live.get((p.parent, p.stem.upper()))
        title = f"{p.name} · {fmt(when)}" + (" · Live Photo (click for still; video: " + lv.name + ")" if lv else "")
        return (f'<a href="{_e(rel)}" target="_blank" title="{_e(title)}" data-row>{inner}'
                f'{f"<span class=tag>{tag}</span>" if tag else ""}</a>')

    years = sorted(by_year, reverse=True)
    for y in years:
        lst = sorted(by_year[y], key=lambda x: x[0], reverse=True)
        body, month = [], None
        for when, p in lst:
            mo = when.strftime("%B")
            if mo != month:
                if month:
                    body.append("</div>")
                body.append(f'<h2>{mo} {y}</h2><div class="ph">')
                month = mo
            body.append(tile(when, p))
        body.append("</div>")
        nav = "".join(f'<a class="pill" href="{yy}.html">{yy} ({len(by_year[yy]):,})</a>' for yy in years)
        (d / f"{y}.html").write_text(page(f"Photos {y}", f"<p>{nav}</p>" + "".join(body)), encoding="utf-8")
    def mini(p: Path) -> str:
        th = thumbs / (hashlib.sha1(str(p.relative_to(orig)).encode()).hexdigest()[:16] + ".jpg")
        src = f".thumbs/{th.name}" if th.exists() else (_e(p.relative_to(d).as_posix())
                                                       if p.suffix.lower() in WEB_IMG else "")
        return ('<span style="aspect-ratio:1;overflow:hidden;border-radius:4px;background:var(--line)">'
                + (f'<img loading="lazy" src="{src}" alt="" style="width:100%;height:100%;object-fit:cover">'
                   if src else "") + "</span>")
    cards = "".join(
        f'<a class="card" href="{y}.html"><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px">'
        + "".join(mini(p) for w, p in sorted(by_year[y], key=lambda x: x[0], reverse=True)[:3])
        + f'</div><b>{y}</b><span>{len(by_year[y]):,} items</span></a>' for y in years)
    note = ("" if Image else '<p class="meta">Tip: install Pillow + pillow-heif for thumbnails of HEIC photos.</p>')
    (d / "index.html").write_text(page("Photos & videos",
        f'<p class="meta">{len(items):,} photos & videos · {len(live):,} Live Photos · originals are in the '
        f'<b>Photos/Originals</b> folder</p>{note}<div class="grid">{cards}</div>'), encoding="utf-8")
    nv = sum(1 for p in items if p.suffix.lower() in VID_EXT)
    return {"count": len(items), "detail": f"{len(items) - nv:,} photos · {nv:,} videos", "link": "Photos/index.html"}


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def sec_calls(ctx: Ctx) -> dict:
    con = ctx.db(HOME, "Library/CallHistoryDB/CallHistory.storedata")
    if con is None:
        raise PhoneKeepError("Call history is only included in ENCRYPTED backups. "
                              "Turn on backup encryption in the app, then back up again.")
    rows = []
    for r in select(con, "ZCALLRECORD", ["ZADDRESS", "ZDATE", "ZDURATION", "ZORIGINATED", "ZANSWERED",
                                         "ZSERVICE_PROVIDER", "ZNAME", "ZCALLTYPE", "ZLOCATION"],
                    "ORDER BY ZDATE DESC"):
        addr = r["ZADDRESS"]
        if isinstance(addr, bytes):
            addr = addr.decode("utf-8", "replace")
        addr = str(addr or "")
        sp = (r["ZSERVICE_PROVIDER"] or "").lower()
        svc = ("FaceTime" if "facetime" in sp else "WhatsApp" if "whatsapp" in sp
               else "Phone" if "telephony" in sp or not sp else sp.split(".")[-1].capitalize())
        if svc == "FaceTime":
            svc += " video" if r["ZCALLTYPE"] == 8 else " audio"
        direction = "Outgoing" if r["ZORIGINATED"] else ("Incoming" if r["ZANSWERED"] else "Missed")
        rows.append([fmt(t2001(r["ZDATE"])), direction, r["ZNAME"] or ctx.label(addr), addr, svc,
                     dur(r["ZDURATION"]), r["ZLOCATION"] or ""])
    con.close()
    if not rows:
        raise PhoneKeepError("No calls found.")
    d = ctx.out / "Calls"
    hdr = ["Date", "Type", "Name", "Number", "Service", "Duration", "Location"]
    write_csv(d / "calls.csv", hdr, rows)
    missed = sum(1 for r in rows if r[1] == "Missed")
    (d / "index.html").write_text(page("Calls", f'<p class="meta">{len(rows):,} calls · {missed:,} missed · '
                                       f'<a href="calls.csv">CSV</a></p>' + table(hdr, rows), filt=True),
                                  encoding="utf-8")
    return {"count": len(rows), "detail": f"{len(rows):,} calls", "link": "Calls/index.html"}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        x = b[i]
        i += 1
        result |= (x & 0x7F) << shift
        if not x & 0x80:
            return result, i
        shift += 7


def _pb_fields(buf: bytes):
    i = 0
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
            return
        yield f, wt, v


def note_text(data: Optional[bytes]) -> Optional[str]:
    if not data:
        return None
    try:
        raw = zlib.decompress(bytes(data), 16 + zlib.MAX_WBITS)
    except zlib.error:
        try:
            raw = zlib.decompress(bytes(data))
        except zlib.error:
            raw = bytes(data)
    buf = raw
    try:
        for want in (2, 3, 2):  # NoteStoreProto.document.note.note_text
            buf = next(v for f, wt, v in _pb_fields(buf) if f == want and wt == 2)
        return buf.decode("utf-8", "replace").replace("\ufffc", "[attachment]")
    except (StopIteration, IndexError):
        return None


def sec_notes(ctx: Ctx) -> dict:
    con = None
    for dom in ctx.reader.domains("%group.com.apple.notes%"):
        con = ctx.db(dom, "NoteStore.sqlite")
        if con:
            break
    if con is None:
        raise PhoneKeepError("No Notes database in this backup.")
    want = ["Z_PK", "ZTITLE1", "ZTITLE2", "ZSNIPPET", "ZFOLDER", "ZNOTEDATA", "ZCREATIONDATE1",
            "ZCREATIONDATE3", "ZMODIFICATIONDATE1", "ZISPASSWORDPROTECTED", "ZMARKEDFORDELETION"]
    objs = select(con, "ZICCLOUDSYNCINGOBJECT", want)
    folders = {r["Z_PK"]: r["ZTITLE2"] for r in objs if r["ZTITLE2"]}
    data = {}
    if "ZICNOTEDATA" in tables(con):
        data = {r["Z_PK"]: r["ZDATA"] for r in select(con, "ZICNOTEDATA", ["Z_PK", "ZDATA"])}
    notes = []
    for r in objs:
        if r["ZNOTEDATA"] is None or r["ZMARKEDFORDELETION"]:
            continue
        locked = bool(r["ZISPASSWORDPROTECTED"])
        text = None if locked else note_text(data.get(r["ZNOTEDATA"]))
        notes.append({"title": r["ZTITLE1"] or (text or "").split("\n", 1)[0][:80] or "Untitled",
                      "folder": folders.get(r["ZFOLDER"], "Notes"),
                      "created": t2001(r["ZCREATIONDATE3"] or r["ZCREATIONDATE1"]),
                      "modified": t2001(r["ZMODIFICATIONDATE1"]),
                      "text": "🔒 Locked note (protected by your Notes password)" if locked
                      else (text if text is not None else (r["ZSNIPPET"] or "")),
                      "locked": locked})
    con.close()
    if not notes:
        raise PhoneKeepError("No notes found.")
    notes.sort(key=lambda n: n["modified"] or dt.datetime.min, reverse=True)
    d = ctx.out / "Notes"
    txt_dir = d / "text"
    used = set()
    for n in notes:
        if n["locked"]:
            continue
        base = txt_dir / safe_name(n["folder"], 40) / safe_name(n["title"], 60)
        p, k = base.with_suffix(".txt"), 2
        while p in used:
            p, k = Path(f"{base} ({k}).txt"), k + 1
        used.add(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(n["text"], encoding="utf-8")
    fl = sorted({n["folder"] for n in notes})
    pills = "".join(f'<span class="pill">{_e(f)} ({sum(1 for n in notes if n["folder"] == f)})</span>' for f in fl)
    cards = "".join(
        f'<div class="note" data-row><h3>{_e(n["title"])}</h3><span class="meta">{_e(n["folder"])} · '
        f'edited {fmt(n["modified"])}</span><pre>{wv._linkify(_e(n["text"]))}</pre></div>' for n in notes)
    (d / "index.html").write_text(page("Notes", f'<p class="meta">{len(notes):,} notes · plain-text copies '
                                       f'in <b>Notes/text</b></p><p>{pills}</p>{cards}', filt=True),
                                  encoding="utf-8")
    return {"count": len(notes), "detail": f"{len(notes):,} notes", "link": "Notes/index.html"}


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def sec_calendar(ctx: Ctx) -> dict:
    con = ctx.db(HOME, "Library/Calendar/Calendar.sqlitedb")
    if con is None:
        raise PhoneKeepError("No Calendar database in this backup.")
    t = tables(con)
    locs = {r[0]: r[1] for r in con.execute("SELECT ROWID, title FROM Location")} if "Location" in t else {}
    cals = {r[0]: r[1] for r in con.execute("SELECT ROWID, title FROM Calendar")} if "Calendar" in t else {}
    ev = []
    for r in select(con, "CalendarItem", ["ROWID", "summary", "start_date", "end_date", "all_day",
                                          "location_id", "description", "calendar_id", "unique_identifier"]):
        s, e = t2001(r["start_date"]), t2001(r["end_date"])
        if not s or not r["summary"]:
            continue
        ev.append({"title": r["summary"], "start": s, "end": e, "all_day": bool(r["all_day"]),
                   "loc": locs.get(r["location_id"]) or "", "desc": r["description"] or "",
                   "cal": cals.get(r["calendar_id"]) or "", "uid": r["unique_identifier"] or f"wv-{r['ROWID']}"})
    con.close()
    if not ev:
        raise PhoneKeepError("No calendar events found.")
    ev.sort(key=lambda x: x["start"], reverse=True)
    d = ctx.out / "Calendar"
    d.mkdir(parents=True, exist_ok=True)

    def ics_esc(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def ics_dt(x: dt.datetime, all_day: bool) -> str:
        if all_day:
            return ";VALUE=DATE:" + x.strftime("%Y%m%d")
        return ":" + x.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with open(d / "calendar.ics", "w", encoding="utf-8", newline="") as f:
        f.write("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//PhoneKeep//EN\r\n")
        for x in ev:
            f.write(f"BEGIN:VEVENT\r\nUID:{ics_esc(x['uid'])}\r\nSUMMARY:{ics_esc(x['title'])}\r\n"
                    f"DTSTART{ics_dt(x['start'], x['all_day'])}\r\n")
            if x["end"]:
                f.write(f"DTEND{ics_dt(x['end'], x['all_day'])}\r\n")
            if x["loc"]:
                f.write(f"LOCATION:{ics_esc(x['loc'])}\r\n")
            if x["desc"]:
                f.write(f"DESCRIPTION:{ics_esc(x['desc'])}\r\n")
            f.write("END:VEVENT\r\n")
        f.write("END:VCALENDAR\r\n")
    hdr = ["Start", "End", "Event", "Location", "Calendar", "Notes"]
    rows = [[fmt(x["start"], not x["all_day"]), fmt(x["end"], not x["all_day"]), x["title"], x["loc"],
             x["cal"], x["desc"]] for x in ev]
    write_csv(d / "calendar.csv", hdr, rows)
    (d / "index.html").write_text(page("Calendar", f'<p class="meta">{len(ev):,} events · '
                                       f'<a href="calendar.ics">Download .ics</a> (import into any calendar) · '
                                       f'<a href="calendar.csv">CSV</a></p>' + table(hdr, rows), filt=True),
                                  encoding="utf-8")
    return {"count": len(ev), "detail": f"{len(ev):,} events", "link": "Calendar/index.html"}


# ---------------------------------------------------------------------------
# Voicemail & voice memos
# ---------------------------------------------------------------------------

def sec_voicemail(ctx: Ctx) -> dict:
    con = ctx.db(HOME, "Library/Voicemail/voicemail.db")
    if con is None:
        raise PhoneKeepError("No visual voicemail in this backup.")
    d = ctx.out / "Voicemail"
    rows = []
    for r in select(con, "voicemail", ["ROWID", "date", "sender", "callback_num", "duration", "trashed_date"],
                    "ORDER BY date DESC"):
        when = dt.datetime.fromtimestamp(r["date"]) if r["date"] else None
        audio = ""
        for ext in (".amr", ".m4a", ".wav"):
            rel = f"Library/Voicemail/{r['ROWID']}{ext}"
            if rel in ctx.files(HOME) and ctx.copy(HOME, rel, d / f"{r['ROWID']}{ext}"):
                audio = f'<a href="{r["ROWID"]}{ext}" download>&#11015; {r["ROWID"]}{ext}</a>'
                break
        who = r["sender"] or r["callback_num"] or ""
        rows.append([fmt(when), ctx.label(who), who, dur(r["duration"]),
                     "deleted" if r["trashed_date"] else "", audio])
    con.close()
    if not rows:
        raise PhoneKeepError("No voicemails found.")
    hdr = ["Date", "From", "Number", "Length", "Status", "Audio"]
    write_csv(d / "voicemail.csv", hdr, [r[:5] for r in rows])
    (d / "index.html").write_text(page("Voicemail", f'<p class="meta">{len(rows):,} voicemails. Audio is '
                                       f'AMR: VLC or QuickTime will play it.</p>' + table(hdr, rows, {5}),
                                       filt=True), encoding="utf-8")
    return {"count": len(rows), "detail": f"{len(rows):,} voicemails", "link": "Voicemail/index.html"}


def sec_voicememos(ctx: Ctx) -> dict:
    found: list[tuple[str, str]] = []
    titles: dict[str, tuple[str, Optional[dt.datetime], float]] = {}
    for dom in ctx.reader.domains("%VoiceMemos%") + [MEDIA]:
        f = ctx.files(dom)
        for rel in f:
            if rel.lower().endswith((".m4a", ".qta")) and (dom != MEDIA or rel.startswith("Media/Recordings/")):
                found.append((dom, rel))
        for rel in f:
            if rel.endswith("CloudRecordings.db") or rel.endswith("Recordings.db"):
                con = ctx.db(dom, rel)
                if con and "ZCLOUDRECORDING" in tables(con):
                    for r in select(con, "ZCLOUDRECORDING", ["ZPATH", "ZCUSTOMLABEL", "ZENCRYPTEDTITLE",
                                                             "ZDATE", "ZDURATION"]):
                        if r["ZPATH"]:
                            titles[Path(r["ZPATH"]).name] = (r["ZCUSTOMLABEL"] or r["ZENCRYPTEDTITLE"] or "",
                                                             t2001(r["ZDATE"]), r["ZDURATION"] or 0)
                if con:
                    con.close()
    if not found:
        raise PhoneKeepError("No voice memos in this backup.")
    d = ctx.out / "Voice Memos"
    items = []
    for dom, rel in found:
        name = Path(rel).name
        dest = d / name
        if not ctx.copy(dom, rel, dest):
            continue
        title, when, length = titles.get(name, ("", None, 0))
        when = when or dt.datetime.fromtimestamp(dest.stat().st_mtime)
        title = title or dest.stem
        nice = d / safe_name(f"{when:%Y-%m-%d %H%M} {title}{dest.suffix}", 120)
        if nice != dest and not nice.exists():
            dest.rename(nice)
            dest = nice
        elif nice.exists() and nice != dest:
            dest.unlink(missing_ok=True)
            dest = nice
        items.append((when, title, length, dest))
    items.sort(key=lambda x: x[0], reverse=True)
    from urllib.parse import quote
    rows = [[fmt(w), t, dur(l), f'<audio controls preload="none" src="{quote(p.name)}"></audio> '
             f'<a href="{quote(p.name)}" download>&#11015;</a>'] for w, t, l, p in items]
    (d / "index.html").write_text(page("Voice Memos", f'<p class="meta">{len(items):,} recordings</p>'
                                       + table(["Date", "Title", "Length", "Play"], rows, {3}), "../", True),
                                  encoding="utf-8")
    return {"count": len(items), "detail": f"{len(items):,} recordings", "link": "Voice Memos/index.html"}


# ---------------------------------------------------------------------------
# Safari
# ---------------------------------------------------------------------------

def sec_safari(ctx: Ctx) -> dict:
    d = ctx.out / "Safari"
    bm, hist = [], []
    con = ctx.db(HOME, "Library/Safari/Bookmarks.db")
    if con is not None and "bookmarks" in tables(con):
        folders = {r["id"]: r["title"] for r in select(con, "bookmarks", ["id", "title", "type"]) if r["type"] == 1}
        for r in select(con, "bookmarks", ["id", "title", "url", "type", "parent"]):
            if r["type"] == 0 and r["url"] and not str(r["url"]).startswith("javascript:"):
                bm.append([folders.get(r["parent"]) or "", r["title"] or "", r["url"]])
        con.close()
    for dom in ("AppDomain-com.apple.mobilesafari", HOME):
        con = ctx.db(dom, "Library/Safari/History.db")
        if con is None:
            continue
        if {"history_items", "history_visits"} <= tables(con):
            for r in con.execute("SELECT v.visit_time, v.title, i.url FROM history_visits v "
                                 "JOIN history_items i ON i.id = v.history_item ORDER BY v.visit_time DESC"):
                hist.append([fmt(t2001(r[0])), r[1] or "", r[2] or ""])
        con.close()
        break
    if not bm and not hist:
        raise PhoneKeepError("No Safari data (browsing history needs an ENCRYPTED backup).")

    def link(u):
        return f'<a href="{_e(u)}" target="_blank" rel="noopener noreferrer">{_e(u[:140])}</a>'
    write_csv(d / "bookmarks.csv", ["Folder", "Title", "URL"], bm)
    write_csv(d / "history.csv", ["Visited", "Title", "URL"], hist)
    body = (f'<p class="meta">{len(bm):,} bookmarks & reading list · {len(hist):,} history visits · '
            f'<a href="bookmarks.csv">bookmarks CSV</a> · <a href="history.csv">history CSV</a></p>'
            f'<h2>Bookmarks</h2>' + table(["Folder", "Title", "URL"], [[f, t, link(u)] for f, t, u in bm], {2})
            + f'<h2>History{" (latest 5,000; full list in CSV)" if len(hist) > 5000 else ""}</h2>'
            + table(["Visited", "Title", "URL"], [[a, b, link(u)] for a, b, u in hist[:5000]], {2}))
    (d / "index.html").write_text(page("Safari", body, filt=True), encoding="utf-8")
    return {"count": len(bm) + len(hist), "detail": f"{len(bm):,} bookmarks · {len(hist):,} visits",
            "link": "Safari/index.html"}


# ---------------------------------------------------------------------------
# Apps & raw files
# ---------------------------------------------------------------------------

def sec_apps(ctx: Ctx) -> dict:
    import plistlib
    apps = set()
    try:
        with open(ctx.reader.path / "Info.plist", "rb") as f:
            apps.update(plistlib.load(f).get("Installed Applications", []) or [])
    except Exception:
        pass
    apps.update(x[len("AppDomain-"):] for x in ctx.reader.domains("AppDomain-%"))
    apps = sorted(a for a in apps if a)
    if not apps:
        raise PhoneKeepError("No app list in this backup.")
    d = ctx.out / "Apps"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for a in apps:
        n = len(ctx.files("AppDomain-" + a))
        rows.append([a, f"{n:,} files" if n else "",
                     f'<a href="https://apps.apple.com/search?term={_e(a.split(".")[-1])}" target="_blank" rel="noopener">App Store</a>'])
    (d / "index.html").write_text(page("Apps", f'<p class="meta">{len(apps):,} apps. Their data is '
                                       f'included in the "All files" export.</p>'
                                       + table(["App ID", "Data in backup", ""], rows, {2}), filt=True),
                                  encoding="utf-8")
    return {"count": len(apps), "detail": f"{len(apps):,} apps", "link": "Apps/index.html"}


def sec_rawfiles(ctx: Ctx) -> dict:
    rows = ctx.reader.db.execute("SELECT domain, relativePath, fileID FROM Files WHERE flags=1").fetchall()
    d = ctx.out / "All files"
    ctx.log(f"Exporting every file in the backup ({len(rows):,} files) — this can take a while...")
    n = 0
    for i, (dom, rel, fid) in enumerate(rows, 1):
        parts = [safe_name(dom, 120)] + [safe_name(p, 120) for p in rel.split("/") if p]
        dest = d.joinpath(*parts)
        if dest.exists() and dest.stat().st_size > 0:
            n += 1
        else:
            ctx._files.setdefault(dom, {})[rel] = fid
            n += ctx.copy(dom, rel, dest)
        if i % 2000 == 0:
            ctx.log(f"  {i:,}/{len(rows):,}")
            if ctx.progress:
                ctx.progress(100.0 * i / len(rows))
    (d / "README.txt").parent.mkdir(parents=True, exist_ok=True)
    (d / "README.txt").write_text("Every file from the iPhone backup, organised as <domain>/<path>.\n"
                                  "AppDomain-<app id> folders hold each app's documents and data.\n",
                                  encoding="utf-8")
    return {"count": n, "detail": f"{n:,} files", "link": "All files/README.txt"}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

SECTIONS = [
    ("whatsapp", "WhatsApp", "&#128172;", sec_whatsapp),
    ("messages", "Messages", "&#128488;", sec_messages),
    ("photos", "Photos & videos", "&#128247;", sec_photos),
    ("contacts", "Contacts", "&#128100;", None),  # handled specially
    ("calls", "Calls", "&#128222;", sec_calls),
    ("notes", "Notes", "&#128221;", sec_notes),
    ("calendar", "Calendar", "&#128197;", sec_calendar),
    ("voicemail", "Voicemail", "&#128252;", sec_voicemail),
    ("voicememos", "Voice Memos", "&#127897;", sec_voicememos),
    ("safari", "Safari", "&#127760;", sec_safari),
    ("apps", "Apps", "&#128241;", sec_apps),
    ("files", "All files (raw)", "&#128193;", sec_rawfiles),
]
DEFAULT_SECTIONS = [k for k, *_ in SECTIONS if k != "files"]


def export_all(backup_path, out_dir=wv.DEFAULT_ARCHIVE_DIR, password: Optional[str] = None,
               sections: Optional[list[str]] = None, include_media: bool = True,
               log: Log = wv._print, progress: Optional[Callable[[float], None]] = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sections = sections or DEFAULT_SECTIONS
    binfo = wv.backup_info(Path(backup_path))
    results = []
    with wv.BackupReader(backup_path, password, log) as reader:
        ctx = Ctx(reader, out, log, include_media, binfo, None)
        people = []
        try:
            people = load_contacts(ctx)
        except Exception as e:
            log(f"Contacts could not be read ({e}).")
        todo = [s for s in SECTIONS if s[0] in sections]
        for i, (key, label, icon, fn) in enumerate(todo):
            log(f"\n== {label} ==")
            if progress:
                ctx.progress = (lambda base, span: (lambda p: progress(base + span * p / 100)))(
                    100 * i / len(todo), 100 / len(todo))
                progress(100 * i / len(todo))
            try:
                r = sec_contacts(ctx, people) if key == "contacts" else fn(ctx)
                log(f"{label}: {r.get('detail', '')}")
            except PhoneKeepError as e:
                r = {"count": 0, "note": str(e)}
                log(f"{label}: {e}")
            except Exception as e:
                r = {"count": 0, "note": f"Could not read this section ({type(e).__name__})."}
                log(f"{label}: failed — {type(e).__name__}: {e}")
                log(traceback.format_exc(limit=3))
            results.append((key, label, icon, r))
    write_hub(out, binfo, results, reader_info(Path(backup_path)))
    if progress:
        progress(100.0)
    log(f"\nAll done. Open: {out / 'index.html'}")
    return out / "index.html"


def reader_info(path: Path) -> dict:
    import plistlib
    try:
        with open(path / "Info.plist", "rb") as f:
            p = plistlib.load(f)
    except Exception:
        return {}
    return {k: p.get(k) for k in ("Device Name", "Product Type", "Product Version", "Phone Number",
                                  "Serial Number", "IMEI", "Last Backup Date") if p.get(k)}


def write_hub(out: Path, binfo: dict, results: list, info: dict) -> None:
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "style.css").write_text(wv.CSS, encoding="utf-8")
    (out / "assets" / "vault.css").write_text(PAGE_CSS, encoding="utf-8")
    # keep earlier results for sections not re-run this time
    state_file = out / "assets" / "sections.json"
    try:
        prev = {k: v for k, v in json.loads(state_file.read_text(encoding="utf-8")).items()}
    except Exception:
        prev = {}
    for key, label, icon, r in results:
        prev[key] = {"label": label, "icon": icon, **r}
    state_file.write_text(json.dumps(prev, default=str), encoding="utf-8")

    cards = []
    for key, label, icon, _ in SECTIONS:
        r = prev.get(key)
        if not r:
            continue
        if r.get("link") and r.get("count"):
            from urllib.parse import quote
            cards.append(f'<a class="card" href="{quote(r["link"])}"><div class="ic">{icon}</div>'
                         f'<b>{_e(label)}</b><span>{_e(r.get("detail", ""))}</span></a>')
        else:
            cards.append(f'<div class="card off"><div class="ic">{icon}</div><b>{_e(label)}</b>'
                         f'<span>{_e(r.get("note", "Nothing found"))}</span></div>')
    kv = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v.strftime('%Y-%m-%d %H:%M') if isinstance(v, dt.datetime) else v)}</dd>"
                 for k, v in info.items())
    body = (f'<dl class="kv">{kv}<dt>Backup</dt><dd>{"encrypted" if binfo.get("encrypted") else "not encrypted"}'
            f'</dd><dt>Archive built</dt><dd>{dt.datetime.now():%Y-%m-%d %H:%M}</dd></dl>'
            f'<div class="grid">{"".join(cards)}</div>'
            + ('' if binfo.get("encrypted") else
               '<p class="meta" style="margin-top:16px">Tip: turn on backup encryption in the app to also '
               'include call history, Safari history and other protected data.</p>'))
    (out / "index.html").write_text(page(info.get("Device Name") or "iPhone", body, root=""), encoding="utf-8")
