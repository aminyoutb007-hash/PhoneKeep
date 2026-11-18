"""F3: file search in App Files (on the phone) and All files (in the backup).

A search is a file name, or part of one ("invoice"), or a pattern where * matches anything and ? one character
("*.pdf", "invoice*", "IMG_00??.JPG"). Upper and lower case, and accents, don't matter. A pattern with a "/" is
matched against the file's whole path instead of its name ("*/Scans/*.pdf"). Read-only, nothing leaves the computer.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Callable, Optional

from search import fold

MAX_HITS = 5000          # shown at most; the count says if there were more


class Pattern:
    def __init__(self, query: str):
        self.query = (query or "").strip()
        q = fold(self.query)
        self.text = q
        self.glob = "*" in q or "?" in q
        self.on_path = "/" in q
        self._rx = re.compile(fnmatch.translate(q), re.S) if self.glob else None

    def __bool__(self) -> bool:
        return bool(self.text.strip("*? "))

    def match(self, name: str, path: str = "") -> bool:
        target = fold(path or name) if self.on_path else fold(name)
        if self._rx is not None:
            return self._rx.match(target) is not None or (self.on_path and self._rx.match(target.lstrip("/")) is not None)
        return self.text in target


def in_backup(file_meta: Callable[[str], dict], domains: list, pattern: Pattern, limit: int = MAX_HITS,
              stop: Optional[Callable[[], bool]] = None) -> tuple[list, int]:
    """Files in the backup whose name (or path) matches: ([(domain, rel, size, mtime)], how many in all)."""
    hits, total = [], 0
    for d in domains:
        if stop and stop():
            break
        for rel, (_fid, mtime, size) in file_meta(d).items():
            if pattern.match(rel.rsplit("/", 1)[-1], rel):
                total += 1
                if len(hits) < limit:
                    hits.append((d, rel, size or 0, mtime))
    hits.sort(key=lambda h: (h[0], h[1].lower()))
    return hits, total


def in_apps(walk: Callable[[str], list], apps: list, pattern: Pattern, limit: int = MAX_HITS,
            stop: Optional[Callable[[], bool]] = None,
            progress: Optional[Callable[[int, int, str], None]] = None) -> tuple[list, int, list]:
    """Files in the sharing apps' Documents on the phone whose name (or path) matches:
    ([(app, entry)], how many in all, [names of apps that couldn't be read])."""
    hits, total, failed = [], 0, []
    sharing = [a for a in apps if a.shares_files]
    for i, a in enumerate(sharing):
        if stop and stop():
            break
        if progress:
            progress(i, len(sharing), a.name)
        try:
            entries = walk(a.id)
        except Exception:
            failed.append(a.name)
            continue
        for e in entries:
            if not e.is_dir and pattern.match(e.name, e.path[len("Documents"):] if e.path.startswith("Documents") else e.path):
                total += 1
                if len(hits) < limit:
                    hits.append((a, e))
    hits.sort(key=lambda h: (h[0].name.lower(), h[1].path.lower()))
    return hits, total, failed
