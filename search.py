"""
PhoneKeep - one search across the phone (E4, docs/spec/05-ease-of-use.md#e4-one-search-across-the-phone).

Searches the opened backup's Messages, WhatsApp, WhatsApp Business, Notes, Contacts, Calls and Safari at once.
Everything is held in memory while the phone window is open: nothing is written to disk and nothing leaves the
computer. Matching finds parts of words and ignores case and accents (é = e, ç = c; in Arabic the short vowel
marks, the hamza on alef and the stretching line), so French and Arabic text is found as typed.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional

# what can be searched, in the order the results are grouped
SOURCES = [("messages", "Messages"), ("whatsapp", "WhatsApp"), ("whatsappbusiness", "WhatsApp Business"),
           ("notes", "Notes"), ("contacts", "Contacts"), ("calls", "Calls"), ("safari", "Safari")]
LABELS = dict(SOURCES)
MIN_CHARS = 2                       # one letter finds too much to be useful
SHOWN = 5                           # results shown per app before "Show all"

# marks that NFKD splits off (accents, Arabic short vowels and hamza/madda on alef) and the Arabic stretching line
_MARKS = re.compile("[̀-ͯؐ-ًؚ-ٰٟۖ-ۭـ]")
_SPACE = re.compile(r"\s+")
_EXTRA = str.maketrans({"ٱ": "ا", "ى": "ي"})     # alef wasla -> alef, alef maqsura -> ya


def fold(s: Optional[str]) -> str:
    """The form text is compared in: lower case, no accents or vowel marks, spaces as one space."""
    if not s:
        return ""
    if s.isascii():
        return _SPACE.sub(" ", s.lower())
    s = _MARKS.sub("", unicodedata.normalize("NFKD", s)).translate(_EXTRA)
    return _SPACE.sub(" ", s.casefold())


def find_span(text: str, query: str) -> Optional[tuple[int, int]]:
    """Where `query` first matches inside `text` (start, end in `text` itself), the same way fold() compares."""
    spans = find_spans(text, query, 1)
    return spans[0] if spans else None


def find_spans(text: str, query: str, most: int = 0) -> list[tuple[int, int]]:
    """Every place `query` matches inside `text`, one after another (start, end in `text`); `most` > 0 stops early."""
    q = fold(query).strip()
    if not q:
        return []
    folded, where = [], []                  # folded characters and the original position each came from
    for i, ch in enumerate(text):
        f = fold(ch) if not ch.isspace() else " "
        folded.append(f)
        where.extend([i] * len(f))
    flat = "".join(folded)
    # spaces were squeezed in fold(): squeeze them here too, keeping the positions in step
    out, pos = [], []
    for c, p in zip(flat, where):
        if c == " " and out and out[-1] == " ":
            continue
        out.append(c)
        pos.append(p)
    flat, spans, at = "".join(out), [], 0
    while most <= 0 or len(spans) < most:
        at = flat.find(q, at)
        if at < 0:
            break
        spans.append((pos[at], pos[at + len(q) - 1] + 1))
        at += len(q)
    return spans


@dataclass
class Hit:
    key: str                    # which app (SOURCES)
    title: str                  # the chat, note, contact, call or page
    text: str                   # the matching text (shown as a snippet around the match)
    when: str = ""              # its date, as shown elsewhere in PhoneKeep
    ref: object = None          # what to open: a chat id, a note's place in the list, a row
    sort: str = field(default="", repr=False)


def _chat_entries(chats: list) -> list:
    out = []
    for c in chats:
        for m in c.get("messages") or ():
            text = " ".join(x for x in (m.get("text"), m.get("caption")) if x)
            if text and m.get("type") != "system":
                when = (m.get("time") or "")[:16].replace("T", " ")
                out.append(Hit("", c.get("name") or "", text, when, (c.get("id"), m.get("time")), m.get("time") or ""))
    return out


def entries(key: str, value) -> list:
    """Everything one app holds that the search looks at, as Hits (key filled in by the caller)."""
    import sections as sx
    if key in ("messages", "whatsapp", "whatsappbusiness"):
        return _chat_entries(value if key == "messages" else (value or {}).get("chats", []))
    if key == "notes":
        return [Hit("", n["title"], f"{n['title']}\n{n.get('text') or ''}", sx.fmt(n.get("modified")), i,
                    str(n.get("modified") or "")) for i, n in enumerate(value) if not n.get("locked")]
    if key == "contacts":
        return [Hit("", p["name"], " · ".join(x for x in [p["name"], p.get("org", ""), p.get("title", "")]
                                               + [v for _l, v in p.get("phones", [])] + [v for _l, v in p.get("emails", [])]
                                               + [p.get("note", "")] if x), "", i) for i, p in enumerate(value)]
    if key == "calls":
        return [Hit("", str(r[2] or r[3]), f"{r[2]} · {r[3]}", str(r[0]), i, str(r[0])) for i, r in enumerate(value)]
    if key == "safari":
        bm, hist = value
        return ([Hit("", t or u, f"{t} · {u}", "", ("bookmark", i)) for i, (_f, t, u) in enumerate(bm)]
                + [Hit("", t or u, f"{t} · {u}", a, ("visit", i), a) for i, (a, t, u) in enumerate(hist)])
    return []


class PhoneSearch:
    """The search for one opened backup. `get(key)` is the phone window's BackupData.get (loads one app)."""

    def __init__(self, get: Callable[[str], object]):
        self.get = get
        self.index: dict[str, tuple[list, list]] = {}      # key -> (folded texts, hits)
        self.missing: list[str] = []                        # apps this backup doesn't have
        self.build_seconds = 0.0

    @property
    def ready(self) -> bool:
        return len(self.index) + len(self.missing) == len(SOURCES)

    def build(self, progress: Callable[[str], None] = lambda label: None) -> None:
        """Load every app once (in the background) and fold its text. Apps the backup lacks are left out."""
        t0 = time.perf_counter()
        for key, label in SOURCES:
            if key in self.index or key in self.missing:
                continue
            progress(label)
            try:
                hits = entries(key, self.get(key))
            except Exception:
                self.missing.append(key)
                continue
            for h in hits:
                h.key = key
            self.index[key] = ([fold(h.text) for h in hits], hits)
        self.build_seconds = time.perf_counter() - t0

    def find(self, query: str) -> list[tuple[str, int, list]]:
        """[(key, number of matches, matching hits newest first)] for the apps with a match, in SOURCES order."""
        q = fold(query).strip()
        if len(q) < MIN_CHARS:
            return []
        out = []
        for key, _label in SOURCES:
            if key not in self.index:
                continue
            folded, hits = self.index[key]
            found = [hits[i] for i, t in enumerate(folded) if q in t]
            if found:
                found.sort(key=lambda h: h.sort, reverse=True)
                out.append((key, len(found), found))
        return out


def snippet(text: str, query: str, width: int = 90) -> tuple[str, str, str]:
    """(before, match, after) on one line, cut to about `width` characters around the match."""
    line = _SPACE.sub(" ", text).strip()
    span = find_span(line, query)
    if span is None:
        return line[:width] + ("…" if len(line) > width else ""), "", ""
    a, b = span
    room = max(10, (width - (b - a)) // 2)
    start = max(0, a - room)
    end = min(len(line), b + room)
    return ("…" if start else "") + line[start:a], line[a:b], line[b:end] + ("…" if end < len(line) else "")
