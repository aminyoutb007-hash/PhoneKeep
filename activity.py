"""S7: the activity record (docs/spec/04-security.md#s7-activity-log).

One line per thing PhoneKeep did: a backup, a save, a change written to the iPhone, a setting like where backups are
kept. Kept on this computer only (activity.jsonl in PhoneKeep's own folder), 12 months, never sent anywhere.
A line never holds a password, message text or a file's name from inside the backup: counts and folders only.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import threading
from pathlib import Path
from typing import Optional

import phonekeep as wv

ACTIVITY_FILE = wv.DEFAULT_HOME / "activity.jsonl"
KEEP_DAYS = 365                                 # "kept 12 months"
_lock = threading.Lock()                        # one writer at a time in this process (worker threads, the prune)


def log(summary: str, phone: Optional[str] = None, kind: str = "phone-write") -> None:
    """Add one line. `summary` must never contain a password or message text."""
    text = json.dumps({"when": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind,
                       "phone": phone, "summary": summary}, ensure_ascii=False) + "\n"
    with _lock:
        try:
            ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


def where(folder) -> str:
    """A folder as the record shows it: under the home folder as ~/… (any slashes, any case on Windows)."""
    p = os.path.normpath(str(folder))
    home = os.path.normpath(str(Path.home()))
    if os.path.normcase(p) == os.path.normcase(home):
        return "~"
    if os.path.normcase(p).startswith(os.path.normcase(home) + os.sep):
        return "~" + p[len(home):]
    return p


def saved(n: int, what: str, folder, phone: Optional[str] = None, plural: Optional[str] = None) -> None:
    """"Saved 12 photos to ~/Desktop": what was saved is counted, never named."""
    if n:
        log(f"Saved {n:,} {what if n == 1 else plural or what + 's'} to {where(folder)}", phone, kind="save")


def _parse(rows: list, since: dt.datetime) -> list[dict]:
    out = []
    for r in rows:
        try:
            d = json.loads(r)
            if dt.datetime.fromisoformat(d["when"]) >= since:
                out.append(d)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return out


def entries(now: Optional[dt.datetime] = None) -> list[dict]:
    """The last 12 months, newest first; damaged lines are skipped."""
    try:
        rows = ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):               # missing, unreadable or not UTF-8
        return []
    return _parse(rows, (now or dt.datetime.now()) - dt.timedelta(days=KEEP_DAYS))[::-1]


def line(d: dict) -> str:
    """One entry in plain words: "3 Nov 2026 21:04 · Backed up Sam's iPhone (encrypted)"."""
    try:
        t = dt.datetime.fromisoformat(d["when"])
        when = f"{t.day} {t.strftime('%b %Y %H:%M')}"
    except (ValueError, TypeError, KeyError):
        when = str(d.get("when", ""))
    phone = d.get("phone")
    text = d.get("summary", "")
    return f"{when} · {text}" + (f" ({phone})" if phone and phone not in text else "")


def prune(now: Optional[dt.datetime] = None) -> int:
    """Drop lines older than 12 months (and damaged ones). Returns how many were dropped. A line another process
    (the menu bar helper) adds meanwhile is never lost: if the file changed while this ran, it's left as it is."""
    with _lock:
        try:
            st = ACTIVITY_FILE.stat()
            rows = ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            return 0
        keep = _parse(rows, (now or dt.datetime.now()) - dt.timedelta(days=KEEP_DAYS))
        if len(keep) == len(rows):
            return 0
        tmp = ACTIVITY_FILE.with_suffix(".tmp")
        try:
            tmp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in keep), encoding="utf-8")
            now_st = ACTIVITY_FILE.stat()
            if (now_st.st_size, now_st.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
                tmp.unlink()                    # written to meanwhile: next start-up tries again
                return 0
            tmp.replace(ACTIVITY_FILE)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            return 0
        return len(rows) - len(keep)


def save_csv(dest: Path, now: Optional[dt.datetime] = None) -> Path:
    """The last 12 months as CSV (date, time, what, phone), oldest first, safe to open in Excel."""
    from tables import csv_safe
    dest = Path(dest)
    with open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Time", "What", "iPhone", "Kind"])
        for d in reversed(entries(now)):
            when = str(d.get("when", ""))
            w.writerow([csv_safe(x) for x in (when[:10], when[11:16], d.get("summary", ""), d.get("phone") or "",
                                              d.get("kind", ""))])
    return dest
