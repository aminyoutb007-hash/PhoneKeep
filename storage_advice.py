"""H2: the Storage card's clean-up suggestions and storage forecast (docs/spec/13-phone-health.md#h2-storage-card-and-clean-up-suggestions).

A list of suggestions, biggest saving first, each with the space it frees and one action. PhoneKeep can't
remove these itself, so most actions are the exact steps on the phone ("Only promise what iOS allows").
Chat media and attachment sizes come from the apps' own databases in the backup, app sizes from the phone's app list, music from the
phone. All of them are estimates and say "about". The forecast under the bar comes from the used space the
check-up records after each backup (checkup.json, H1).

The two suggestions that open Photo clean-up (C1), "Videos already saved on this computer" and "Photo clean-up",
come with C1.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

GB = 1000 ** 3
MIN_BYTES = 500 * 1000 ** 2           # a suggestion appears only when it frees at least this much
TOP_CHATS = 5                         # chats listed under the WhatsApp suggestion
TOP_APPS = 20
FORECAST_MIN_BACKUPS = 4
FORECAST_FLAT = 0.005                 # used space rising less than this share of the capacity: flat
FORECAST_MAX_DAYS = 730               # further than about two years isn't worth a line

STEPS = {
    "whatsapp": "On the iPhone: WhatsApp → Settings → Storage and Data → Manage Storage. Start with the chats below.",
    "whatsappbusiness": ("On the iPhone: WhatsApp Business → Settings → Storage and Data → Manage Storage. "
                         "Start with the chats below."),
    "messages": "On the iPhone: Settings → General → iPhone Storage → Messages → Review Large Attachments.",
    "apps": ("On the iPhone: Settings → General → iPhone Storage, then tap an app. Offload App frees the app and "
             "keeps its documents and data; Delete App removes both."),
    "music": ("On the iPhone: Music → Library → Downloaded. Touch and hold an album or playlist, then Remove → "
              "Remove Download. The songs stay in your library to stream."),
}


@dataclass
class Suggestion:
    key: str
    title: str                        # "WhatsApp media: about 6 GB in 3 chats"
    size: int                         # bytes it would free (an estimate)
    steps: str                        # what to do on the phone
    items: list = field(default_factory=list)   # [(name, bytes)] shown under it: chats or apps
    note: str = ""


def about(n: Optional[float]) -> str:
    """'about 6 GB', 'about 1.4 GB', 'about 800 MB': an estimate, rounded."""
    if not n:
        return "about 0 MB"
    if n >= 10 * GB:
        return f"about {n / GB:.0f} GB"
    if n >= GB:
        return f"about {n / GB:.1f} GB".replace(".0 GB", " GB")
    return f"about {max(1, round(n / 1000 ** 2, -1 if n >= 100 * 1000 ** 2 else 0)):.0f} MB"


def build(wa_chats: Optional[list] = None, wab_chats: Optional[list] = None, attachments: Optional[int] = None,
          apps: Optional[list] = None, music: Optional[int] = None, backup_day: str = "") -> list:
    """The suggestions, biggest saving first. wa_chats / wab_chats: [(chat name, media bytes)];
    apps: deviceinfo.AppSize list. None for anything not known."""
    out = []
    kept = f"They are in your backup of {backup_day}." if backup_day else "They are in your latest backup."
    for key, label, chats in (("whatsapp", "WhatsApp", wa_chats), ("whatsappbusiness", "WhatsApp Business", wab_chats)):
        chats = sorted((c for c in chats or [] if c[1] > 0), key=lambda c: -c[1])
        total = sum(n for _c, n in chats)
        if total >= MIN_BYTES:
            title = f"{label} media: {about(total)} in {len(chats)} chat{'s' if len(chats) != 1 else ''}"
            out.append(Suggestion(key, title, total, STEPS[key], chats[:TOP_CHATS],
                                  f"Photos, videos and voice notes. {kept} To keep a chat on this computer as well, "
                                  f"open {label} in PhoneKeep and save it first."))
    if attachments and attachments >= MIN_BYTES:
        out.append(Suggestion("messages", f"Message attachments: {about(attachments)}", attachments, STEPS["messages"],
                              note=f"Photos, videos and files sent in Messages. {kept}"))
    if apps:
        top = sorted(apps, key=lambda a: -a.total)[:TOP_APPS]
        total = sum(a.total for a in top)
        if total >= MIN_BYTES:
            out.append(Suggestion("apps", f"Large apps: the {len(top)} largest use {about(total)}", total, STEPS["apps"],
                                  [(a.name, a.total) for a in top],
                                  "Each size is the app plus its documents and data, as the iPhone reports it."))
    if music and music >= MIN_BYTES:
        out.append(Suggestion("music", f"Downloaded music: {about(music)}", music, STEPS["music"]))
    return sorted(out, key=lambda s: -s.size)


# -- the forecast -------------------------------------------------------------------------------------------------
def forecast(history: list, today: Optional[dt.datetime] = None) -> Optional[str]:
    """'At this rate the iPhone will be full in about 3 months', from the used space recorded at each backup.
    None with fewer than 4 backups, or when use is flat or falling."""
    pts = []
    for e in history:
        try:
            w = dt.datetime.fromisoformat(e["when"])
            total, free = int(e["total"]), int(e["free"])
        except (KeyError, TypeError, ValueError):
            continue
        pts.append((w, total, free))
    if len(pts) < FORECAST_MIN_BACKUPS:
        return None
    pts.sort()
    t0 = pts[0][0]
    xs = [(w - t0).total_seconds() / 86400 for w, _t, _f in pts]
    ys = [t - f for _w, t, f in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var     # bytes a day
    total, free = pts[-1][1], pts[-1][2]
    if slope <= 0 or slope * (xs[-1] - xs[0]) < FORECAST_FLAT * total:
        return None
    days = free / slope
    if days > FORECAST_MAX_DAYS:
        return None
    if days < 14:
        when = f"about {max(1, round(days))} day{'s' if round(days) > 1 else ''}"
    elif days < 61:
        when = f"about {round(days / 7)} weeks"
    else:
        m = round(days / 30.4)
        when = f"about {m} months" if m < 24 else "about 2 years"
    return f"At this rate the iPhone will be full in {when}."


# -- sizes from the backup ----------------------------------------------------------------------------------------
# Each app's own database records every item's size, also when the file itself isn't in the backup (Messages in
# iCloud leaves attachments out; WhatsApp keeps some media out). Those figures are what the iPhone counts, so they
# come first; the files in the backup are the fallback (14 Nov, a real backup: 0.06 GB of WhatsApp files against
# 0.13 GB in its database, and no Messages attachments folder at all).
def _db(reader, domain: str, rel: str) -> Optional[sqlite3.Connection]:
    """A database from the backup, copied (with -wal / -shm) into the reader's private folder and opened."""
    import hashlib
    files = reader.list_files(domain, rel)
    if rel not in files:
        return None
    d = Path(reader._tmp.name) / "h2" / hashlib.sha1(f"{domain}/{rel}".encode()).hexdigest()[:12]
    local = d / Path(rel).name
    if not reader.extract(domain, rel, files[rel], local):
        return None
    for sfx in ("-wal", "-shm"):
        if rel + sfx in files:
            reader.extract(domain, rel + sfx, files[rel + sfx], d / (Path(rel).name + sfx))
    con = sqlite3.connect(str(local))
    con.row_factory = sqlite3.Row
    return con


def whatsapp_media(reader, business: bool = False, log=lambda m: None) -> Optional[list]:
    """[(chat name, bytes of its photos, videos and voice notes on the phone)], or None if that app isn't in the
    backup. From WhatsApp's own database (media kept on the phone); else from the media files in the backup."""
    import phonekeep as wv
    domain = wv.WA_BUSINESS_DOMAIN if business else wv.WA_DOMAIN
    if not reader.has_file(domain, wv.WA_DB):
        return None
    names, per_jid = {}, defaultdict(int)
    try:
        db_local, _ = wv._extract_wa_db(reader, domain, log)
        con = sqlite3.connect(str(db_local))
        con.row_factory = sqlite3.Row
        for s in wv._select(con, "ZWACHATSESSION", ["ZCONTACTJID", "ZPARTNERNAME"]):
            if s["ZCONTACTJID"]:
                names[s["ZCONTACTJID"]] = s["ZPARTNERNAME"] or wv.jid_label(s["ZCONTACTJID"])
        try:
            for jid, n in con.execute(
                    "SELECT s.ZCONTACTJID, SUM(i.ZFILESIZE) FROM ZWAMEDIAITEM i "
                    "JOIN ZWAMESSAGE m ON m.ZMEDIAITEM = i.Z_PK JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK "
                    "WHERE i.ZMEDIALOCALPATH IS NOT NULL AND i.ZMEDIALOCALPATH != '' GROUP BY s.ZCONTACTJID"):
                if jid and n:
                    per_jid[jid] += int(n)
        except sqlite3.Error:
            pass                                  # an older layout: the files below
        con.close()
    except Exception as e:
        log(f"WhatsApp media sizes: {type(e).__name__}: {e}")
    if not per_jid:
        for rel, (_fid, _mtime, size) in reader.file_meta(domain, "Message/Media/").items():
            parts = rel.split("/")
            if len(parts) > 3 and size:
                per_jid[parts[2]] += size
    return [(names.get(j) or wv.jid_label(j), n) for j, n in per_jid.items()]


def message_attachments(reader) -> int:
    """Bytes of Messages' attachments: from sms.db's own sizes, else the attachment files in the backup."""
    con = _db(reader, "HomeDomain", "Library/SMS/sms.db")
    if con is not None:
        try:
            n = con.execute("SELECT SUM(total_bytes) FROM attachment").fetchone()[0]
            if n:
                return int(n)
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return sum(size or 0 for _fid, _m, size in reader.file_meta("HomeDomain", "Library/SMS/Attachments/").values())


def from_backup(reader, log=lambda m: None) -> dict:
    """Everything H2 reads from the backup, in one go (run it off the window's thread)."""
    return {"wa_chats": whatsapp_media(reader, False, log), "wab_chats": whatsapp_media(reader, True, log),
            "attachments": message_attachments(reader)}
