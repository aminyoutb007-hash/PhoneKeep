"""H4: the Stability card's facts, from the iPhone's own crash reports (docs/spec/13-phone-health.md#h4-stability-card).

The launcher (`--pk-crashes`) copies the reports of the last 30 days into <backups>/<udid>/crash-reports/, read-only:
they stay on the phone. This reads what kind each one is from its first line (iOS's .ips files start with a small JSON
header) and keeps a summary in the phone's checkup.json, so the card can be shown with the phone away.

What counts (checked against a real iPhone's reports, 14 Nov):
- an app crash: bug_type 309 (109 before iOS 14) for something with a bundle id. A widget or extension that crashes is
  counted under its app ("Mi Home" for its home-screen widget), named as the phone's app list names it.
- an unexpected restart: a kernel panic (bug_type 210 / 110, panic-full / panic-base files). Red.
- a restart, possibly by itself: iOS restarting itself (SystemMemoryReset), often to free memory. Amber, not red
  (owner, 14 Nov): it isn't a fault the way a panic is.
- not counted: CPU and disk-use notices (202 / 145), hangs (288), memory events (298), battery logs (120) and the
  phone's own feedback reports. They aren't crashes, and the spec leaves memory figures out on purpose.
Kept free of Tk, like checkup.py.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CRASH_TYPES = {"309", "109"}
PANIC_TYPES = {"210", "110"}
RESTART_NAMES = ("panic-full", "panic-base")
SELF_RESTART_NAMES = ("SystemMemoryReset",)
SELF_RESTART = "*"                   # by_day's key for restarts iOS did by itself ("" is unexpected restarts)
KEEP_DAYS = 30                       # reports copied and kept; the card counts the last THRESHOLDS["crash_days"]
FOLDER = "crash-reports"
ADVICE = "Update it in the App Store; if it keeps crashing, delete and reinstall it."
RESTART_ADVICE = ("If it keeps happening, update iOS (Settings → General → Software Update). If it still does, "
                  "contact Apple Support: Save reports gives them what they need.")
SELF_RESTART_ADVICE = ("iOS sometimes restarts itself, for example to free memory: once in a while is nothing to worry "
                       "about. If it happens often, update iOS (Settings → General → Software Update).")


@dataclass
class Event:
    when: dt.datetime
    kind: str                        # "crash", "restart" (unexpected) or "self_restart" (possibly by itself)
    app: str = ""                    # the app's name, for a crash
    bundle: str = ""
    file: str = ""                   # where the report is, under crash-reports/


def _stamp(name: str) -> Optional[dt.datetime]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{6})", name)
    try:
        return dt.datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S") if m else None
    except ValueError:
        return None


def _when(header: dict, name: str) -> Optional[dt.datetime]:
    t = header.get("timestamp")                  # "2026-11-12 10:10:10.00 +0000"
    if isinstance(t, str):
        try:
            w = dt.datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")
            off = re.search(r"([+-])(\d{2})(\d{2})$", t.strip())
            if off:                              # to this computer's local time
                sign = 1 if off.group(1) == "+" else -1
                utc = w - sign * dt.timedelta(hours=int(off.group(2)), minutes=int(off.group(3)))
                return utc.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
            return w
        except ValueError:
            pass
    return _stamp(name)


def app_name(bundle: str, fallback: str, apps: Optional[dict] = None) -> str:
    """The app's name as the phone's app list has it; an extension's app for a widget or extension."""
    apps = apps or {}
    if bundle in apps:
        return apps[bundle]
    owner = max((b for b in apps if bundle.startswith(b + ".")), key=len, default=None)
    if owner:
        return apps[owner]
    return fallback or bundle


def read_one(path: Path, apps: Optional[dict] = None) -> Optional[Event]:
    """What one report is, or None when it isn't a crash or a restart."""
    name = path.name
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline()
    except OSError:
        return None
    header = {}
    try:
        header = json.loads(first) if first.lstrip().startswith("{") else {}
    except ValueError:
        header = {}
    bug = str(header.get("bug_type", ""))
    when = _when(header, name)
    if when is None:
        return None
    if name.startswith(SELF_RESTART_NAMES):
        return Event(when, "self_restart", file=name)
    if bug in PANIC_TYPES or name.startswith(RESTART_NAMES):
        return Event(when, "restart", file=name)
    if bug in CRASH_TYPES:
        bundle = str(header.get("bundleID") or "")
        if not bundle:
            return None                          # a system process, not an app
        return Event(when, "crash", app_name(bundle, str(header.get("app_name") or header.get("name") or ""), apps),
                     bundle, name)
    if not header and name.endswith(".crash"):   # the old plain-text format
        text = path.read_text(encoding="utf-8", errors="replace")[:4000]
        ident = re.search(r"^Identifier:\s*(\S+)", text, re.M)
        proc = re.search(r"^Process:\s*(.+?)\s*\[", text, re.M)
        if ident:
            return Event(when, "crash", app_name(ident.group(1), proc.group(1) if proc else "", apps), ident.group(1),
                         name)
    return None


def read_folder(folder: Path, apps: Optional[dict] = None) -> list:
    out = []
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file() and not p.name.endswith(".part"):
            e = read_one(p, apps)
            if e is not None:
                e.file = str(p.relative_to(folder))
                out.append(e)
    return sorted(out, key=lambda e: e.when)


def summary(events: list, read_at: dt.datetime) -> dict:
    """What checkup.json keeps: every crash and restart of the last KEEP_DAYS days, and when the phone was read."""
    since = read_at - dt.timedelta(days=KEEP_DAYS)
    return {"read": read_at.isoformat(timespec="seconds"),
            "events": [{"when": e.when.isoformat(timespec="seconds"), "kind": e.kind, "app": e.app, "file": e.file}
                       for e in events if e.when >= since]}


def kind(e: dict) -> str:
    """An event's kind; records kept before 14 Nov called iOS restarting itself a "restart"."""
    if e.get("kind") == "restart" and Path(e.get("file") or "").name.startswith(SELF_RESTART_NAMES):
        return "self_restart"
    return e.get("kind") or ""


def self_restarts(stability: Optional[dict], days: int) -> Optional[int]:
    """Restarts iOS did by itself over the `days` before the phone was read; None if never read."""
    if not stability or "read" not in stability:
        return None
    since = dt.datetime.fromisoformat(stability["read"]) - dt.timedelta(days=days)
    return sum(1 for e in stability.get("events", []) if kind(e) == "self_restart"
               and dt.datetime.fromisoformat(e["when"]) >= since)


def counts(stability: Optional[dict], days: int, now: Optional[dt.datetime] = None) -> tuple:
    """(crashes per app, unexpected restarts) over the `days` before the phone was read; (None, None) if never read."""
    if not stability or "read" not in stability:
        return None, None
    try:
        read = dt.datetime.fromisoformat(stability["read"])
    except (TypeError, ValueError):
        return None, None
    since = read - dt.timedelta(days=days)
    crashes, restarts = {}, 0
    for e in stability.get("events", []):
        try:
            w = dt.datetime.fromisoformat(e["when"])
        except (KeyError, TypeError, ValueError):
            continue
        if w < since:
            continue
        if kind(e) == "restart":
            restarts += 1
        elif kind(e) == "crash" and e.get("app"):
            crashes[e["app"]] = crashes.get(e["app"], 0) + 1
    return crashes, restarts


def by_day(stability: Optional[dict], days: int) -> list:
    """[(app, [(date, crashes)])] for the details screen, most first; unexpected restarts as app "", restarts iOS
    did by itself as SELF_RESTART."""
    if not stability or "read" not in stability:
        return []
    read = dt.datetime.fromisoformat(stability["read"])
    since = read - dt.timedelta(days=days)
    per: dict = {}
    for e in stability.get("events", []):
        w = dt.datetime.fromisoformat(e["when"])
        if w >= since:
            k = kind(e)
            key = e.get("app") if k == "crash" else SELF_RESTART if k == "self_restart" else ""
            per.setdefault(key, {}).setdefault(w.date(), 0)
            per[key][w.date()] += 1
    return sorted(((a, sorted(d.items())) for a, d in per.items()), key=lambda x: (-sum(n for _d, n in x[1]), x[0]))


def prune(folder: Path, now: Optional[dt.datetime] = None) -> int:
    """Remove copies (on this computer) older than KEEP_DAYS. The phone's own reports are never touched."""
    now = now or dt.datetime.now()
    gone = 0
    for p in Path(folder).rglob("*"):
        if p.is_file():
            w = _stamp(p.name) or dt.datetime.fromtimestamp(p.stat().st_mtime)
            if w < now - dt.timedelta(days=KEEP_DAYS):
                p.unlink(missing_ok=True)
                gone += 1
    return gone


def save_zip(folder: Path, events: list, dest: Path) -> Path:
    """Save reports: the reports behind these events in one zip, for anyone helping the owner."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for e in events:
            p = Path(folder) / e["file"]
            if p.is_file():
                z.write(p, e["file"])
    return dest
