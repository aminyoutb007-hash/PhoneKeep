"""D9: one date range and one search for "Save everything" (docs/spec/08-personal-data.md#d9-export-everything).

The rule, the same for every kind of data:
  * the date range applies to everything that has a date (messages, calls, notes, calendar events,
    voicemail, voice memos, Safari history, photos, files). An item without a date is left out while a
    range is set. Kinds that never have dates (contacts, bookmarks, the app list) ignore the range;
  * the search applies to everything that has text. Kinds with no text at all (photos and videos) are
    left out while searching, and the contents page says so;
  * a chat whose name matches keeps all its messages in the range; otherwise only the matching messages
    are kept.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional


def _day(when) -> Optional[dt.date]:
    if when is None or when == "":
        return None
    if isinstance(when, dt.datetime):
        return when.date()
    if isinstance(when, dt.date):
        return when
    if isinstance(when, (int, float)):
        try:
            return dt.datetime.fromtimestamp(when).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return dt.date.fromisoformat(str(when).strip()[:10])
    except ValueError:
        return None


@dataclass
class Filter:
    dates: Optional[tuple] = None          # (from, to) dt.date, either may be None
    search: str = ""

    def __post_init__(self):
        self.search = (self.search or "").strip()
        if self.dates and not any(self.dates):
            self.dates = None

    @property
    def on(self) -> bool:
        return bool(self.dates or self.search)

    def in_dates(self, when) -> bool:
        if not self.dates:
            return True
        d = _day(when)
        if d is None:
            return False
        lo, hi = self.dates
        return (lo is None or d >= lo) and (hi is None or d <= hi)

    def mentions(self, *texts) -> bool:
        if not self.search:
            return True
        q = self.search.casefold()
        return any(q in str(t).casefold() for t in texts if t)

    def keep(self, when, *texts, dated: bool = True) -> bool:
        """dated=False: this kind never has dates, so only the search applies."""
        return (not dated or self.in_dates(when)) and self.mentions(*texts)

    # chats ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _message_text(m: dict) -> list:
        return [v for k, v in m.items() if isinstance(v, str) and k not in ("time", "type", "media_rel", "media")]

    def chats(self, chats: list[dict]) -> list[dict]:
        """Messages in the range that mention the search (all of a chat's messages when its name matches).
        Chats left with nothing are dropped. Returns new chat dicts."""
        if not self.on:
            return chats
        out = []
        for c in chats:
            whole = self.search and self.mentions(c.get("name"))
            msgs = [m for m in c["messages"] if self.in_dates(m.get("time"))
                    and (whole or self.mentions(*self._message_text(m)))]
            if msgs:
                out.append(dict(c, messages=msgs))
        return out

    def describe(self) -> str:
        """'from 01 Oct 2026 to 30 Oct 2026, mentioning “invoice”' (for the log and the contents page)."""
        parts = []
        if self.dates:
            lo, hi = self.dates
            parts.append(f"from {lo:%d %b %Y} to {hi:%d %b %Y}" if lo and hi else
                         f"from {lo:%d %b %Y} onwards" if lo else f"up to {hi:%d %b %Y}")
        if self.search:
            parts.append(f"mentioning “{self.search}”")
        return ", ".join(parts) or "everything"


NONE = Filter()
