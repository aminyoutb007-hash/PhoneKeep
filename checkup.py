"""H1: the phone check-up (docs/spec/13-phone-health.md#h1-check-up-screen).

Four cards, Storage, Battery, Stability and Security, each green, amber or red with one line saying why, a
summary line ("2 things need attention") and one plain answer to "Why is my phone slow?".

Kept free of Tk and of the phone connection, like deviceinfo.py: the window, the helper and the tests feed it
an Overview (V1-V3) and the small record PhoneKeep keeps per phone (checkup.json next to the snapshots), which
make_backup adds to after every backup. With the phone away, the cards come from that record and say
"As of last backup, 3 Nov".

Storage and Battery come from what the iPhone reports (V2, V3). Stability (crash reports, H4) and Security
(H5) aren't read from the phone yet: their cards say "Not checked yet" until those land, and are worked out
here from Facts so the thresholds are tested now.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

GB = 1000 ** 3
GREEN, AMBER, RED, UNKNOWN = "green", "amber", "red", "unknown"

# Every threshold in one place (spec: "tunable in one table in the code, not scattered").
THRESHOLDS = {
    "storage_amber_pct": 85,          # % full or more
    "storage_red_pct": 95,
    "battery_amber_health": 85,       # health below this
    "battery_red_health": 80,
    "battery_drop_points": 5,         # ... or dropped this many points
    "battery_drop_days": 91,          # ... within about 3 months
    "crash_days": 7,                  # crashes are counted over this many days
    "crash_amber": 3,                 # one app crashed this many times or more
    "crash_red": 10,
}

ORDER = ("storage", "battery", "stability", "security")        # also the order of impact on speed
TITLES = {"storage": "Storage", "battery": "Battery", "stability": "Stability", "security": "Security"}
# what the helper's one notification says when a card turns red ("Amin's iPhone: storage almost full")
ALERTS = {"storage": "storage almost full", "battery": "battery needs attention",
          "stability": "an app keeps crashing", "security": "a security check needs a look"}
HISTORY_MAX = 1000                    # backups kept in the record (years of daily backups)


@dataclass
class Facts:
    """What the check-up knows about one phone. None means "not checked" (not reported, or not read yet)."""
    when: dt.datetime
    live: bool = False                                # read from the phone just now, or from the last backup
    total: Optional[int] = None                       # bytes
    free: Optional[int] = None
    health: Optional[int] = None                      # battery health, %
    battery_service: Optional[bool] = None            # the phone says the battery needs service
    health_history: list = field(default_factory=list)   # [(datetime, health %)], oldest first
    crashes: Optional[dict] = None                    # app name -> crashes in the last 7 days (H4)
    unexpected_restarts: Optional[int] = None         # in the last 7 days (H4)
    no_passcode: Optional[bool] = None                # H5
    unknown_profiles: Optional[list] = None           # names of profiles / device management not recognised
    jailbreak: Optional[list] = None                  # what was found
    spyware_matched: Optional[bool] = None            # S5, run on request
    ios_outdated: Optional[bool] = None
    outside_app_store: Optional[list] = None          # app names


@dataclass
class Card:
    key: str
    level: str
    reason: str                                       # the one line on the card, e.g. "Amber: 91% full. …"
    details: list = field(default_factory=list)       # every finding, most serious first (See details)
    slow: str = ""                                    # how it reads in "Why is my phone slow?"

    @property
    def title(self) -> str:
        return TITLES[self.key]

    @property
    def needs_attention(self) -> bool:
        return self.level in (AMBER, RED)


@dataclass
class Report:
    facts: Facts
    cards: list

    def card(self, key: str) -> Card:
        return next(c for c in self.cards if c.key == key)

    def as_of(self, today: Optional[dt.date] = None) -> str:
        """'Now, from the iPhone' or 'As of last backup, 3 Nov'."""
        if self.facts.live:
            return "Now, from the iPhone"
        return f"As of last backup, {day_text(self.facts.when, today)}"

    def summary(self) -> str:
        n = sum(1 for c in self.cards if c.needs_attention)
        line = ("Nothing needs attention" if n == 0 else "1 thing needs attention" if n == 1
                else f"{n} things need attention")
        unchecked = [c.title for c in self.cards if c.level == UNKNOWN]
        if unchecked:
            line += f" ({_join(unchecked)} not checked yet)"
        return line

    def why_slow(self) -> str:
        """One plain answer drawn from all four cards, most likely cause first."""
        rank = {RED: 0, AMBER: 1}
        causes = sorted((c for c in self.cards if c.needs_attention and c.key != "security"),
                        key=lambda c: (rank[c.level], ORDER.index(c.key)))
        sec = next((c for c in self.cards if c.key == "security" and c.needs_attention), None)
        if causes:
            parts = [c.slow for c in causes]
            text = _cap(_join(parts)) + ". "
            text += ("This can slow an iPhone down." if len(parts) == 1 else
                     "Both slow an iPhone down." if len(parts) == 2 else "All of these slow an iPhone down.")
            text += f" Start with {causes[0].title}."
        else:
            text = ("Nothing PhoneKeep checked explains a slow iPhone. Restarting it often helps: hold the side "
                    "button and a volume button, then slide to power off.")
        if sec is not None:
            text += f" Also look at Security: {sec.slow}."
        unchecked = [c.title for c in self.cards if c.level == UNKNOWN]
        if unchecked:
            text += f" ({_join(unchecked)} {'is' if len(unchecked) == 1 else 'are'} not checked yet.)"
        return text


# -- the four cards -----------------------------------------------------------------------------------------
def storage_card(f: Facts) -> Card:
    t = THRESHOLDS
    if not f.total or f.free is None:
        return Card("storage", UNKNOWN, "Not checked: the iPhone didn't report its storage.")
    used = max(0, f.total - f.free)
    ratio = used / f.total
    pct = math.floor(ratio * 100)                     # never shows "85%" on a card that's still green
    if ratio * 100 >= t["storage_amber_pct"]:
        level = RED if ratio * 100 >= t["storage_red_pct"] else AMBER
        to_free = used - f.total * (t["storage_amber_pct"] / 100) + 1
        why = f"{pct}% full. Free about {_gb_up(to_free)} to get below {t['storage_amber_pct']}%."
        return Card("storage", level, f"{level.capitalize()}: {why}", [why], f"your storage is {pct}% full")
    why = f"{pct}% full, about {_gb_down(f.free)} free."
    return Card("storage", GREEN, f"Green: {why}", [why])


def battery_card(f: Facts) -> Card:
    t = THRESHOLDS
    found, level, slow = [], GREEN, ""
    if f.battery_service:
        found.append("The iPhone says the battery needs service.")
        level, slow = RED, "your battery needs service"
    if f.health is None:
        if not found:
            return Card("battery", UNKNOWN, "Not checked: the iPhone didn't report its battery health.")
        return Card("battery", level, f"Red: {found[0]}", found, slow)
    h = f.health
    if h < t["battery_red_health"]:
        found.append(f"Health about {h}%. Apple usually recommends a new battery below {t['battery_red_health']}%.")
        level, slow = RED, slow or f"your battery is at about {h}%"
    elif h < t["battery_amber_health"]:
        found.append(f"Health about {h}%.")
        if level == GREEN:
            level, slow = AMBER, f"your battery is at about {h}%"
    drop = health_drop(f)
    if drop >= t["battery_drop_points"]:
        found.append(f"Health dropped {drop} points in 3 months.")
        if level == GREEN:
            level, slow = AMBER, f"your battery health dropped {drop} points in 3 months"
    if level == GREEN:
        return Card("battery", GREEN, f"Green: Health about {h}%.", [f"Health about {h}%."])
    return Card("battery", level, f"{level.capitalize()}: {found[0]}", found, slow)


def health_drop(f: Facts) -> int:
    """Points lost since the oldest reading in the last ~3 months (0 when there's nothing to compare)."""
    if f.health is None:
        return 0
    since = f.when - dt.timedelta(days=THRESHOLDS["battery_drop_days"])
    old = [h for w, h in f.health_history if w >= since and h is not None]
    return max(0, old[0] - f.health) if old else 0


def stability_card(f: Facts) -> Card:
    t = THRESHOLDS
    if f.crashes is None and f.unexpected_restarts is None:
        return Card("stability", UNKNOWN, "Not checked yet: PhoneKeep doesn't read the iPhone's crash reports yet.")
    found, level, slow = [], GREEN, ""
    if f.unexpected_restarts:
        n = f.unexpected_restarts
        found.append("The iPhone restarted unexpectedly " + ("once" if n == 1 else f"{n} times") + " this week.")
        level, slow = RED, "your iPhone restarted unexpectedly this week"
    # most crashes first, so the first app over the line sets the card when no restart already made it red
    for app, n in sorted((f.crashes or {}).items(), key=lambda kv: (-kv[1], kv[0])):
        if n < t["crash_amber"]:
            break
        found.append(f"{app} crashed {n} times this week.")
        if level == GREEN:
            level, slow = (RED if n >= t["crash_red"] else AMBER), f"{app} crashed {n} times this week"
    if level == GREEN:
        why = ("No app crashes in the last 7 days." if not any((f.crashes or {}).values())
               else f"No app crashed {t['crash_amber']} or more times in the last 7 days.")
        return Card("stability", GREEN, f"Green: {why}", [why])
    return Card("stability", level, f"{level.capitalize()}: {found[0]}", found, slow)


def security_card(f: Facts) -> Card:
    checks = (f.no_passcode, f.unknown_profiles, f.jailbreak, f.spyware_matched, f.ios_outdated, f.outside_app_store)
    if all(c is None for c in checks):
        return Card("security", UNKNOWN, "Not checked yet: the security checks come in a later version of PhoneKeep.")
    red, amber = [], []
    if f.no_passcode:
        red.append("No passcode is set.")
    for p in f.unknown_profiles or []:
        red.append(f"An unknown configuration profile or device management is installed: {p}.")
    if f.jailbreak:
        red.append("Signs of a jailbreak were found: " + ", ".join(f.jailbreak) + ".")
    if f.spyware_matched:
        red.append("A spyware indicator matched.")
    if f.ios_outdated:
        amber.append("iOS is out of date.")
    for a in f.outside_app_store or []:
        amber.append(f"An app from outside the App Store: {a}.")
    found = red + amber
    if not found:
        return Card("security", GREEN, "Green: No problems found in these checks.", ["No problems found in these checks."])
    level = RED if red else AMBER
    return Card("security", level, f"{level.capitalize()}: {found[0]}", found, found[0][0].lower() + found[0][1:-1])


def evaluate(f: Facts) -> Report:
    return Report(f, [storage_card(f), battery_card(f), stability_card(f), security_card(f)])


# -- the record kept per phone: <backups>/<udid>/checkup.json --------------------------------------------------
def _path(phone_dir: Path) -> Path:
    return Path(phone_dir) / "checkup.json"


def load(phone_dir: Path) -> dict:
    try:
        d = json.loads(_path(phone_dir).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("history", [])
            d.setdefault("notified", {})
            return d
    except (OSError, ValueError):
        pass
    return {"history": [], "notified": {}}


def _save(phone_dir: Path, d: dict) -> None:
    try:
        Path(phone_dir).mkdir(parents=True, exist_ok=True)
        tmp = _path(phone_dir).with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(_path(phone_dir))
    except OSError:
        pass


def entry_from(ov, when: dt.datetime) -> Optional[dict]:
    """What one backup adds to the record, from a deviceinfo.Overview (None if the phone told us nothing)."""
    if ov is None:
        return None
    b = ov.battery
    e = {"when": when.isoformat(timespec="seconds"), "ios": ov.ios or None,
         "product_type": getattr(ov, "product_type", "") or None, "total": ov.total, "free": ov.free,
         "health": b.health, "cycles": b.cycles, "full_mah": b.full_mah, "design_mah": b.design_mah,
         "temperature": b.temperature}
    return e if any(e[k] is not None for k in ("total", "free", "health")) else None


def record(phone_dir: Path, ov, when: Optional[dt.datetime] = None) -> bool:
    """After a backup: add what the phone reported to its record. Returns True if something was added."""
    e = entry_from(ov, when or dt.datetime.now())
    if e is None:
        return False
    d = load(phone_dir)
    d["history"] = (d["history"] + [e])[-HISTORY_MAX:]
    _save(phone_dir, d)
    return True


def _when(e: dict) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(e["when"])
    except (KeyError, TypeError, ValueError):
        return None


def facts(phone_dir: Optional[Path], ov=None, now: Optional[dt.datetime] = None) -> Optional[Facts]:
    """The check-up's facts: from the phone (ov, read just now) when there is one, else from the last backup's
    entry in the record. None when there's nothing at all yet."""
    d = load(phone_dir) if phone_dir is not None else {"history": []}
    hist = [(w, e.get("health")) for e in d["history"] if (w := _when(e)) is not None]
    if ov is not None and entry_from(ov, now or dt.datetime.now()) is not None:
        return Facts(when=now or dt.datetime.now(), live=True, total=ov.total, free=ov.free,
                     health=ov.battery.health, health_history=hist)
    last = next((e for e in reversed(d["history"]) if _when(e) is not None), None)
    if last is None:
        return None
    w = _when(last)
    return Facts(when=w, live=False, total=last.get("total"), free=last.get("free"), health=last.get("health"),
                 health_history=[(hw, h) for hw, h in hist if hw <= w])


def check(phone_dir: Optional[Path], ov=None, now: Optional[dt.datetime] = None) -> Optional[Report]:
    f = facts(phone_dir, ov, now)
    return evaluate(f) if f is not None else None


def new_alerts(phone_dir: Path, report: Report, name: str) -> list:
    """The helper's notifications for this report: one per card that has just turned red, and none again until
    that card changes (a card that's no longer red is forgotten, so turning red again notifies again)."""
    d = load(phone_dir)
    before = set(d.get("notified") or {})
    now_red = {c.key: c.reason for c in report.cards if c.level == RED}
    out = [(f"{name}: {ALERTS[k]}", why.split(": ", 1)[-1]) for k, why in now_red.items() if k not in before]
    if set(now_red) != before:
        d["notified"] = {k: dt.datetime.now().isoformat(timespec="seconds") for k in now_red}
        _save(phone_dir, d)
    return out


def any_red(phone_dir: Path) -> bool:
    """For the helper's dot: is any card red as of the last backup?"""
    r = check(phone_dir)
    return r is not None and any(c.level == RED for c in r.cards)


# -- wording helpers --------------------------------------------------------------------------------------------
def _gb_up(n: float) -> str:
    return f"{max(1, math.ceil(n / GB))} GB"


def _gb_down(n: float) -> str:
    return f"{n / GB:.0f} GB" if n >= GB else f"{max(1, round(n / 1000 ** 2))} MB"


def _join(parts: list) -> str:
    parts = list(parts)
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def day_text(when: dt.datetime, today: Optional[dt.date] = None) -> str:
    """'3 Nov', or '27 Oct 2025' for another year."""
    today = today or dt.date.today()
    return f"{when.day} {when:%b}" + ("" if when.year == today.year else f" {when.year}")
