"""X2. Backup redaction tool (docs/spec/12-engineering.md): an anonymised copy of a real backup for the
regression library.

    python tools/redact_backup.py <backup folder> <output folder> [--password-stdin]

Rules (agreed 11 Nov):
  - Runs on the owner's computer only; nothing leaves it. The output never goes in the public repository.
  - No photos, videos, voice notes or attachments: each becomes a placeholder of the same type and size.
  - Names, phone numbers, email addresses, postal addresses, and all message, note and calendar text are
    replaced with generated values, consistently (the same real value always becomes the same fake one).
    The phone's serial number, UDID, phone number, IMEI and Wi-Fi details too.
  - Every file the tool doesn't understand becomes a zero-filled placeholder of the same size, so nothing
    personal can slip through in a cache or a settings file.
  - Prints a report of everything it replaced, by kind and count, for the owner to check before the copy goes
    anywhere.

The output is an unencrypted iTunes-style backup that PhoneKeep opens like any other.
"""
from __future__ import annotations

import hashlib
import io
import os
import plistlib
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phonekeep as wv  # noqa: E402

FIRST = ["Alex", "Sam", "Nour", "Maya", "Omar", "Lina", "Youssef", "Sara", "Karim", "Dina", "Tom", "Emma",
         "Rania", "Hugo", "Léa", "Adam", "Zoe", "Ali", "Mia", "Noah", "Amira", "Jules", "Inès", "Eli"]
LAST = ["Haddad", "Martin", "Bennani", "Dubois", "Khalil", "Moreau", "Farah", "Lefèvre", "Saleh", "Roux",
        "Mansour", "Garcia", "Nasser", "Petit", "Ziani", "Bernard", "Idris", "Fontaine", "Rami", "Leroy"]
WORDS = ("the quick brown fox jumps over a lazy dog while someone makes coffee and reads the morning news "
         "about rain trains markets gardens music photos travel dinner friends family work school weekend "
         "invoice meeting project holiday birthday café été merci bonjour demain مرحبا شكرا كيف الحال ok 👍 🙂").split()
STREETS = ["Example Street", "Sample Road", "Test Avenue", "Demo Lane", "Placeholder Square"]

# column names that are structure, not content: left alone
KEEP = re.compile(r"^(service|service_name|mime|mime_type|type|z\w*type|uti|z?\w*path|filename|transfer_name|flags|label|guid"
                  r"|uuid|kind|status|version|folder|domain|style|special_id|category|protocol|country|lang\w*|timezone"
                  r"|color|format|\w*identifier|z_\w+|z_pk|rowid|id|\w*date\w*|\w*time\w*|duration|size|width|height"
                  r"|\w*count|sort\w*|order|index|pinned|archived|hidden|is_\w+|has_\w+|z\w*flags|answered|originated"
                  r"|all_day|trashed_date|parent|balloon_bundle_id|bundle_id|handle_id|chat_id|message_id|attachment_id"
                  r"|record_id|property|\w+_id|media_type|sticker|ext|zmessagetype|zsessiontype|zarchived|zisfromme|item_type"
                  r"|associated_message_type|location_id|calendar_id)$", re.I)
NAME = re.compile(r"(name|title|summary|subject|organization|company|nickname|sender|display|partner|contact|from$|group)", re.I)
TEXTY = re.compile(r"(text|body|snippet|note|content|message|caption|comment|description|^zdata$|subtitle|preview)", re.I)
ADDRESS = re.compile(r"(address|street|city|location)", re.I)

PHONE_RE = re.compile(r"^\+?[\d\s().-]{6,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^(https?|ftp)://", re.I)
JID_RE = re.compile(r"^(\d+)(@(s\.whatsapp\.net|g\.us|lid|broadcast).*)$")


class Mapper:
    """Consistent replacements: the same real value always maps to the same fake one."""

    def __init__(self):
        self.seen: dict[str, str] = {}
        self.counts = Counter()
        self.n = 0

    def _idx(self, value: str) -> int:
        return int(hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:8], 16)

    def _remember(self, kind: str, value: str, fake: str) -> str:
        if value not in self.seen:
            self.seen[value] = fake
            self.counts[kind] += 1
        return self.seen[value]

    def name(self, value: str) -> str:
        if not value:
            return value
        if value in self.seen:
            return self.seen[value]
        i = self._idx(value)
        parts = value.split()
        fake = FIRST[i % len(FIRST)] if len(parts) == 1 else f"{FIRST[i % len(FIRST)]} {LAST[(i // 7) % len(LAST)]}"
        return self._remember("names", value, fake)

    def phone(self, value: str) -> str:
        if value in self.seen:
            return self.seen[value]
        self.n += 1
        digits = re.sub(r"\D", "", value)
        fake = f"+447700{900000 + (self._idx(digits) % 900):06d}"
        return self._remember("phone numbers", value, fake)

    def email(self, value: str) -> str:
        if value in self.seen:
            return self.seen[value]
        fake = f"person{self._idx(value) % 10000}@example.com"
        return self._remember("email addresses", value, fake)

    def url(self, value: str) -> str:
        if value in self.seen:
            return self.seen[value]
        fake = f"https://example.com/page{self._idx(value) % 100000}"
        return self._remember("web addresses", value, fake)

    def jid(self, value: str) -> str:
        m = JID_RE.match(value or "")
        if not m:
            return self.phone(value) if PHONE_RE.match(value or "") else value
        return self.phone(m.group(1)).lstrip("+") + m.group(2)

    def address(self, value: str) -> str:
        if value in self.seen:
            return self.seen[value]
        i = self._idx(value)
        return self._remember("addresses", value, f"{1 + i % 200} {STREETS[i % len(STREETS)]}")

    def text(self, value: str) -> str:
        """Generated words of about the same length, same number of lines; deterministic."""
        if not value or not value.strip():
            return value
        if value in self.seen:
            return self.seen[value]
        i = self._idx(value)
        out_lines = []
        for ln, line in enumerate(value.split("\n")):
            words, length = [], 0
            k = i + ln
            while length < max(1, len(line)):
                w = WORDS[(k * 7 + len(words) * 13) % len(WORDS)]
                words.append(w)
                length += len(w) + 1
            out_lines.append(" ".join(words)[:max(1, len(line))].rstrip() if line else "")
        return self._remember("text passages", value, "\n".join(out_lines))

    SYSTEM_SEG = re.compile(r"^([0-9A-Fa-f.\-_]+|(IMG|PXL|VID|DSC|MOV|RPReplay|Screenshot|Photo|Video|AUD|PTT|STK|DOC)[-_ ]?[\w.-]*|"
                            r"Media|Message|Library|Documents|Desktop|Downloads|Mobile Documents|com~apple~CloudDocs|Attachments|"
                            r"File Provider Storage|WhatsApp|Profile|Stickers|Thumbnails|\.?[A-Za-z]+)$")
    PERSONAL_AREA = re.compile(r"(^|/)(Mobile Documents|Documents|Desktop|Downloads|File Provider Storage|Attachments|Message/Media|Media)(/|$)")

    def pathname(self, value: str) -> str:
        """A file path with the owner's own folder and file names replaced segment by segment (deterministic,
        so references in the chat databases and Manifest.db stay in step). System-looking segments
        (IMG_1234.jpg, GUIDs, single words such as Library) are kept."""
        if not isinstance(value, str) or "/" not in value or not self.PERSONAL_AREA.search(value):
            return value
        out = []
        area = False
        for seg in value.split("/"):
            if area and seg and not self.SYSTEM_SEG.match(seg):
                stem, dot, ext = seg.rpartition(".")
                if not dot:
                    stem, ext = seg, ""
                i = self._idx(stem)
                fake = f"{FIRST[i % len(FIRST)].lower()}-{(i // 13) % 997}"
                self._remember("file and folder names", stem, fake)
                seg = fake + (dot + ext if dot and len(ext) <= 5 else "")
            out.append(seg)
            if self.PERSONAL_AREA.search("/" + seg + "/"):
                area = True
        return "/".join(out)

    def shape(self, value):
        """Only what the value's shape gives away (for structural columns): numbers, emails, ids, links, paths."""
        if not isinstance(value, str) or not value:
            return value
        if "/" in value and self.PERSONAL_AREA.search(value):
            return self.pathname(value)
        if EMAIL_RE.match(value):
            return self.email(value)
        if URL_RE.match(value):
            return self.url(value)
        if JID_RE.match(value):
            return self.jid(value)
        if PHONE_RE.match(value) and sum(c.isdigit() for c in value) >= 6:
            return self.phone(value)
        return value

    def any(self, column: str, value):
        """Decide by the column name, then by what the value looks like."""
        if not isinstance(value, str) or not value:
            return value
        if EMAIL_RE.match(value):
            return self.email(value)
        if URL_RE.match(value):
            return self.url(value)
        if value.lower().startswith("javascript:"):
            return "javascript:void(0)"
        if JID_RE.match(value):
            return self.jid(value)
        if PHONE_RE.match(value) and sum(c.isdigit() for c in value) >= 6:
            return self.phone(value)
        if ADDRESS.search(column):
            return self.address(value)
        if NAME.search(column):
            return self.name(value)
        return self.text(value)


def redact_sqlite(src: Path, dest: Path, mapper: Mapper, report: Counter) -> None:
    shutil.copyfile(src, dest)
    con = sqlite3.connect(dest)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
        stringy = [c[1] for c in cols if "TEXT" in (c[2] or "").upper() or "CHAR" in (c[2] or "").upper() or c[2] in ("", None)
                   or NAME.search(c[1]) or TEXTY.search(c[1]) or ADDRESS.search(c[1])]
        text_cols = [c for c in stringy if not KEEP.search(c)]      # content: replaced by kind
        keep_cols = [c for c in stringy if KEEP.search(c)]          # structure: only numbers/emails/ids/links inside it
        # every BLOB goes: metadata blobs carry quoted text and link previews, image blobs are the owner's photos
        blob_cols = [c[1] for c in cols if "BLOB" in (c[2] or "").upper()]
        if not text_cols and not blob_cols and not keep_cols:
            continue
        pk = next((c[1] for c in cols if c[5]), "rowid")
        all_cols = text_cols + keep_cols + blob_cols
        rows = con.execute(f'SELECT "{pk}", ' + ", ".join(f'"{c}"' for c in all_cols) + f' FROM "{t}"').fetchall()
        for row in rows:
            key, values = row[0], list(row[1:])
            new = []
            changed = False
            for c, v in zip(all_cols, values):
                if c in text_cols:
                    nv = None if isinstance(v, (bytes, bytearray)) else mapper.any(c, v)   # rich text blobs in untyped columns go too
                elif c in keep_cols:
                    nv = mapper.shape(v)
                else:
                    nv = (PLACEHOLDER_JPEG if (v and _looks_like_image(v)) else None) if v else v   # blobs are dropped; images become a placeholder
                changed |= nv != v
                new.append(nv)
            if changed:
                con.execute(f'UPDATE "{t}" SET ' + ", ".join(f'"{c}"=?' for c in all_cols) + f' WHERE "{pk}"=?', (*new, key))
                report[f"rows changed in {src.name}"] += 1
    con.commit()
    con.execute("VACUUM")
    con.close()


def _looks_like_image(b: bytes) -> bool:
    return bytes(b[:3]) == b"\xff\xd8\xff" or bytes(b[:8]) == b"\x89PNG\r\n\x1a\n"


def _placeholder_jpeg() -> bytes:
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (120, 160, 140)).save(buf, "JPEG")
        return buf.getvalue()
    except Exception:
        return b"\xff\xd8\xff"


PLACEHOLDER_JPEG = _placeholder_jpeg()

MAGIC = {".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG\r\n\x1a\n", ".heic": b"\0\0\0\x18ftypheic",
         ".mov": b"\0\0\0\x18ftypqt  ", ".mp4": b"\0\0\0\x18ftypisom", ".m4a": b"\0\0\0\x18ftypM4A ", ".amr": b"#!AMR\n",
         ".opus": b"OggS", ".caf": b"caff", ".aac": b"\xff\xf1", ".pdf": b"%PDF-1.4\n", ".gif": b"GIF89a"}


def placeholder(dest: Path, size: int, suffix: str) -> None:
    """A file of the same type (by its magic bytes) and size, with nothing in it."""
    suffix = suffix.lower()
    body = b""
    if suffix in (".jpg", ".jpeg", ".png") and size > 2000:
        try:
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (120, 160, 140)).save(buf, "JPEG" if suffix != ".png" else "PNG")
            body = buf.getvalue()
        except Exception:
            body = MAGIC.get(suffix, b"")
    else:
        body = MAGIC.get(suffix, b"")
    with open(dest, "wb") as f:
        f.write(body[:size])
        if size > len(body):
            f.seek(size - 1)
            f.write(b"\0")


KNOWN_DBS = (re.compile(p) for p in (
    r"Library/SMS/sms\.db$", r"Library/AddressBook/AddressBook(Images)?\.sqlitedb$", r"Library/CallHistoryDB/CallHistory\.storedata$",
    r"NoteStore\.sqlite$", r"Library/Calendar/Calendar\.sqlitedb$", r"Library/Voicemail/voicemail\.db$",
    r"Library/Safari/(Bookmarks|History)\.db$", r"ChatStorage\.sqlite$", r"ContactsV2\.sqlite$",
    r"CloudRecordings\.db$", r"Recordings\.db$", r"Photos\.sqlite$"))
KNOWN_DBS = list(KNOWN_DBS)
STRUCTURE = re.compile(r"(^Media/.*\.(AAE|aae)$)")


def redact_backup(src: Path, out: Path, password: Optional[str] = None, log=print, progress=None) -> Counter:
    src, out = Path(src), Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty.")
    out.mkdir(parents=True, exist_ok=True)
    reader = wv.BackupReader(src, password, log=lambda m: None)
    mapper = Mapper()
    report = Counter()
    # Info.plist and Manifest.plist: identifiers replaced, structure kept
    with open(src / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    fake_udid = hashlib.sha1(str(info.get("Unique Identifier", "")).encode()).hexdigest()[:8].upper()
    for key in ("Serial Number", "IMEI", "IMEI 2", "MEID", "ICCID", "ICCID 2", "Phone Number", "Unique Identifier", "Target Identifier",
                "GUID", "iTunes Settings", "Applications", "iTunes Files", "Build Version"):
        if key in info:
            info[key] = ("00008030-" + fake_udid + "0000000E") if "Identifier" in key else \
                        ("+447700900000" if key == "Phone Number" else ("REDACTED" if isinstance(info[key], str) else {} if isinstance(info[key], dict) else info[key]))
            report["identifiers replaced"] += 1
    if "Device Name" in info:
        info["Device Name"] = mapper.name(info["Device Name"]) + "'s iPhone" if "'" not in info["Device Name"] else "Test iPhone"
        report["identifiers replaced"] += 1
    with open(out / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    mp = {}
    try:
        with open(src / "Manifest.plist", "rb") as f:
            mp = plistlib.load(f)
    except Exception:
        pass
    mp = {"Version": mp.get("Version", "10.0"), "IsEncrypted": False, "Date": mp.get("Date"),
          "Lockdown": {k: v for k, v in (mp.get("Lockdown") or {}).items() if k in ("ProductVersion", "ProductType", "BuildVersion")},
          "Applications": {k: {} for k in (mp.get("Applications") or {})}, "WasPasscodeSet": False, "SystemDomainsVersion": mp.get("SystemDomainsVersion", "20.0")}
    with open(out / "Manifest.plist", "wb") as f:
        plistlib.dump({k: v for k, v in mp.items() if v is not None}, f)
    if (src / "Status.plist").exists():
        shutil.copyfile(src / "Status.plist", out / "Status.plist")
    # Manifest.db: the decrypted copy (keys removed with it); every file re-made
    shutil.copyfile(reader.manifest, out / "Manifest.db")
    con = sqlite3.connect(out / "Manifest.db")
    rows = con.execute("SELECT fileID, domain, relativePath, flags, file FROM Files").fetchall()
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)
    total = sum(1 for r in rows if r[3] == 1) or 1
    started = time.time()
    done = 0
    for fid, domain, rel, flags, blob in rows:
        if flags != 1 or not re.fullmatch(r"[0-9a-f]{40}", fid or ""):
            continue
        done += 1
        if progress and (done % 200 == 0 or done == total):
            elapsed = time.time() - started
            left = (total - done) * elapsed / done
            progress(f"{done:,} of {total:,} files · {100 * done // total}% · "
                     + ("under 2 min left" if left < 90 else f"about {int(left // 60)} min left"))
        dest = out / fid[:2] / fid
        dest.parent.mkdir(exist_ok=True)
        src_tmp = tmp / fid
        if not reader.extract(domain, rel, fid, src_tmp):
            placeholder(dest, 0, "")
            report["missing files (empty placeholder)"] += 1
            continue
        size = src_tmp.stat().st_size
        if any(p.search(rel) for p in KNOWN_DBS):
            try:
                redact_sqlite(src_tmp, dest, mapper, report)
                report["databases redacted"] += 1
            except sqlite3.DatabaseError:
                placeholder(dest, size, Path(rel).suffix)
                report["files replaced by placeholders"] += 1
        elif STRUCTURE.search(rel):
            shutil.copyfile(src_tmp, dest)
            report["structure files kept"] += 1
        else:
            placeholder(dest, size, Path(rel).suffix)
            kind = "photos & videos" if domain == "CameraRollDomain" else "attachments & voice notes" if "Attachments" in rel or "Message/Media" in rel \
                else "other files (zero-filled placeholders)"
            report[kind] += 1
        src_tmp.unlink(missing_ok=True)
        # the manifest's size stays the same (placeholders keep the size); its encryption key goes
        if blob:
            try:
                pl = plistlib.loads(blob)
                objs = pl.get("$objects", [])
                for o in objs:
                    if isinstance(o, dict) and "EncryptionKey" in o:
                        o.pop("EncryptionKey", None)
                con.execute("UPDATE Files SET file=? WHERE fileID=?", (plistlib.dumps(pl, fmt=plistlib.FMT_BINARY), fid))
            except Exception:
                pass
    # the owner's own folder and file names (iCloud Drive, app Documents, attachment names) are personal too;
    # done last because the extraction above looks files up by their real path
    for fid, rel in con.execute("SELECT fileID, relativePath FROM Files").fetchall():
        if rel:
            nrel = mapper.pathname(rel)
            if nrel != rel:
                con.execute("UPDATE Files SET relativePath=? WHERE fileID=?", (nrel, fid))
    con.commit()
    con.execute("VACUUM")
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    reader.close()
    for k, v in mapper.counts.items():
        report[k] = v
    return report


def main(argv=None) -> int:
    import argparse
    import getpass
    import logging
    logging.basicConfig(level=logging.WARNING)      # the decrypt library's per-file INFO lines would bury the progress line
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("backup", help="the real backup folder (never modified)")
    p.add_argument("out", help="an empty folder for the anonymised copy")
    p.add_argument("--password-stdin", action="store_true", help="read the backup password from standard input (never on the command line)")
    a = p.parse_args(argv)
    pw = None
    if wv.backup_info(Path(a.backup))["encrypted"]:
        pw = sys.stdin.readline().rstrip("\r\n") if a.password_stdin else getpass.getpass("Backup password: ")
    report = redact_backup(Path(a.backup), Path(a.out), pw,
                           progress=lambda line: print("\r" + line + " " * 12, end="", flush=True))
    print()
    print("\nRedaction report")
    for k in sorted(report):
        print(f"  {report[k]:>7,}  {k}")
    print(f"\nCheck the copy in {a.out} yourself before it goes anywhere. It is not for this public repository.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
