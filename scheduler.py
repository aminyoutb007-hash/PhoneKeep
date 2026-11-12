"""B2. Scheduled automatic backups (docs/spec/03-backup.md), run by the helper (E2).

The rules, all in one place so they can be tested with a fake clock:
  - Daily or Weekly at "around <hour>"; starts when the phone is reachable at or after that time;
    tries again every 30 minutes until midnight.
  - Skips if a backup less than 20 hours old exists.
  - Never two backups of the same phone at once (the helper guarantees it).
  - "Only when charging" waits for the phone to be on power.
  - Notifications: success each time; failure only after 3 failed days in a row, with the reason and the fix.
  - Survives a restart: the helper starts at login and reads everything from disk.

The settings it reads (settings.json): auto_backup = "daily" | "weekly" | "off", auto_backup_hour (0-23,
default 21), auto_backup_weekday (0 = Monday, default 6 = Sunday), auto_backup_charging (bool),
auto_backup_paused (bool). Per phone it reads <backup>/<udid>/health.json written by the helper.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RETRY_MINUTES = 30
FRESH_HOURS = 20
FAILED_DAYS_BEFORE_NOTICE = 3


@dataclass
class Plan:
    mode: str = "off"            # daily | weekly | off
    hour: int = 21
    weekday: int = 6             # for weekly: 0 = Monday
    only_when_charging: bool = False
    paused: bool = False

    @classmethod
    def from_settings(cls, s: dict) -> "Plan":
        return cls(mode=s.get("auto_backup", "off") or "off", hour=int(s.get("auto_backup_hour", 21)),
                   weekday=int(s.get("auto_backup_weekday", 6)),
                   only_when_charging=bool(s.get("auto_backup_charging", False)),
                   paused=bool(s.get("auto_backup_paused", False)))

    def window_start(self, now: dt.datetime) -> Optional[dt.datetime]:
        """The scheduled moment of today's run, or None if today has no run."""
        if self.mode == "off" or self.paused:
            return None
        if self.mode == "weekly" and now.weekday() != self.weekday:
            return None
        return now.replace(hour=self.hour, minute=0, second=0, microsecond=0)

    def next_run_text(self, now: dt.datetime, last_ok: Optional[dt.datetime]) -> str:
        """For the phone card: 'next tonight around 9 pm', 'next tomorrow around 9 pm', 'next Sunday around 9 pm'."""
        if self.paused:
            return "automatic backups paused"
        if self.mode == "off":
            return ""
        hour = f"{(self.hour % 12) or 12} {'am' if self.hour < 12 else 'pm'}"
        day = self._next_day(now, last_ok)
        if day == now.date():
            return f"next {'tonight' if self.hour >= 17 else 'today'} around {hour}"
        if day == now.date() + dt.timedelta(days=1):
            return f"next tomorrow around {hour}"
        return f"next {day.strftime('%A')} around {hour}"

    def _next_day(self, now: dt.datetime, last_ok: Optional[dt.datetime]) -> dt.date:
        d = now.date()
        for _ in range(8):
            start = dt.datetime.combine(d, dt.time(self.hour))
            weekday_ok = self.mode == "daily" or d.weekday() == self.weekday
            fresh = last_ok is not None and (start - last_ok) < dt.timedelta(hours=FRESH_HOURS)
            passed = d == now.date() and now >= start + dt.timedelta(hours=24 - self.hour)   # midnight passed
            if weekday_ok and not fresh and not passed:
                return d
            d += dt.timedelta(days=1)
        return d


@dataclass
class Health:
    last_ok: Optional[dt.datetime] = None
    failed_days: list = None
    last_try: Optional[dt.datetime] = None
    last_reason: str = ""
    noticed_failure_on: Optional[str] = None     # the day the 3-days notice went out

    @classmethod
    def load(cls, folder: Path) -> "Health":
        h = cls(failed_days=[])
        try:
            d = json.loads((folder / "health.json").read_text(encoding="utf-8"))
            h.last_ok = dt.datetime.fromisoformat(d["last_ok"]) if d.get("last_ok") else None
            h.failed_days = list(d.get("failed_days", []))
            h.last_try = dt.datetime.fromisoformat(d["last_try"]) if d.get("last_try") else None
            h.last_reason = d.get("last_reason", "")
            h.noticed_failure_on = d.get("noticed_failure_on")
        except Exception:
            pass
        return h

    def save(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "health.json").write_text(json.dumps({
                "last_ok": self.last_ok.isoformat(timespec="seconds") if self.last_ok else None,
                "failed_days": self.failed_days or [],
                "last_try": self.last_try.isoformat(timespec="seconds") if self.last_try else None,
                "last_reason": self.last_reason, "noticed_failure_on": self.noticed_failure_on}), encoding="utf-8")
        except OSError:
            pass

    def consecutive_failed_days(self, today: dt.date) -> int:
        n, d = 0, today
        days = set(self.failed_days or [])
        while d.isoformat() in days:
            n += 1
            d -= dt.timedelta(days=1)
        return n


def is_fresh(now: dt.datetime, last_ok: Optional[dt.datetime]) -> bool:
    return last_ok is not None and (now - last_ok) < dt.timedelta(hours=FRESH_HOURS)


def decide(plan: Plan, health: Health, now: dt.datetime, phone_reachable: bool,
           charging: Optional[bool], busy: bool) -> tuple[str, str]:
    """What the helper should do right now: ("backup", ""), or ("wait", reason).
    Pure: no clock, no phone, no disk."""
    if busy:
        return "wait", "a backup is already running"
    start = plan.window_start(now)
    if start is None:
        return "wait", "no run scheduled today"
    if now < start:
        return "wait", "before the scheduled time"
    if is_fresh(now, health.last_ok):
        return "wait", "a backup less than 20 hours old exists"
    if health.last_try and (now - health.last_try) < dt.timedelta(minutes=RETRY_MINUTES) \
            and health.last_try.date() == now.date() and health.last_try >= start:
        return "wait", "tried less than 30 minutes ago"
    if not phone_reachable:
        return "wait", "the iPhone isn't reachable"
    if plan.only_when_charging and charging is False:
        return "wait", "waiting for the iPhone to be charging"
    return "backup", ""


def card_state(plan: Plan, health: Health, now: dt.datetime, connected_how: str = "") -> tuple[str, str]:
    """For the phone card and the menu: ("ok" | "amber" | "none", one line).
    Amber after a missed day, with the fix in the same line (never a colour change alone)."""
    last = health.last_ok
    nxt = plan.next_run_text(now, last)
    if last is None:
        return "none", "Not backed up yet" + (f" · {nxt}" if nxt else "")
    age = now - last
    if plan.mode != "off" and not plan.paused and age > dt.timedelta(days=2) - dt.timedelta(hours=4):
        days = age.days
        fix = health.last_reason or "Connect your iPhone to the same Wi-Fi, or plug it in."
        when = "yesterday" if days < 2 else f"{days} days ago"
        return "amber", f"Last backup {when}. {fix}"
    return "ok", f"Last backup: {_ago(now, last)}" + (f" · {nxt}" if nxt else "")


def _ago(now: dt.datetime, when: dt.datetime) -> str:
    s = int((now - when).total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if s < 2 * 86400:
        return "yesterday"
    return f"{s // 86400} days ago"


def failure_notice(health: Health, today: dt.date) -> Optional[tuple[str, str]]:
    """The one failure notification: only after 3 failed days in a row, once per streak."""
    n = health.consecutive_failed_days(today)
    if n >= FAILED_DAYS_BEFORE_NOTICE and health.noticed_failure_on != today.isoformat():
        reason = health.last_reason or "PhoneKeep couldn't reach your iPhone."
        return "iPhone not backed up for 3 days", f"{reason} Plug it in or put it on the same Wi-Fi to catch up."
    return None
