"""P1: what the phone's own Photos library database knows about each photo (docs/spec/07-photos-media.md#p1-photos).

Photos.sqlite (on the phone at PhotoData/Photos.sqlite, in a backup under CameraRollDomain Media/PhotoData/) records,
for every item in DCIM: favourite, hidden, in the Recently Deleted bin, photo or video, Live Photo / screenshot,
the date taken and the location; and the user's albums with their items.

Its layout changes between iOS versions (ZGENERICASSET became ZASSET in iOS 14; the album link table is called
Z_<n>ASSETS with numbered columns), so the tables and columns are looked up, not assumed. Anything missing simply
isn't offered: PhoneKeep never guesses an album or a favourite.
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

APPLE_EPOCH = dt.datetime(2001, 1, 1)
SUBTYPE_LIVE = 2
SUBTYPE_SCREENSHOT = 10
USER_ALBUM = 2                    # ZGENERICALBUM.ZKIND for albums the user made


@dataclass
class Attrs:
    favorite: bool = False
    hidden: bool = False
    trashed: bool = False
    video: bool = False
    live: bool = False
    screenshot: bool = False
    taken: Optional[dt.datetime] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    albums: list = field(default_factory=list)       # album keys ("album:<pk>")
    original: Optional[str] = None                   # the name it was taken with ("IMG_1234.HEIC")


@dataclass
class Library:
    assets: dict                                      # "DCIM/100APPLE/IMG_0001.HEIC" -> Attrs
    albums: list                                      # [(key, title, count)], in the phone's order

    def get(self, item_id: str) -> Optional[Attrs]:
        return self.assets.get(item_id)


def _cols(con, table: str) -> set:
    return {r[1].upper() for r in con.execute(f'PRAGMA table_info("{table}")')}


def _tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _date(v) -> Optional[dt.datetime]:
    try:
        return APPLE_EPOCH + dt.timedelta(seconds=float(v)) if v is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def read(db: Path) -> Optional[Library]:
    """Read a copy of Photos.sqlite (with its -wal next to it, if there is one). None if it can't be read."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        tables = _tables(con)
        at = "ZASSET" if "ZASSET" in tables else ("ZGENERICASSET" if "ZGENERICASSET" in tables else None)
        if at is None:
            return None
        c = _cols(con, at)
        want = {"FAV": "ZFAVORITE", "HID": "ZHIDDEN", "TRASH": "ZTRASHEDSTATE", "KIND": "ZKIND",
                "SUB": "ZKINDSUBTYPE", "DATE": "ZDATECREATED", "LAT": "ZLATITUDE", "LON": "ZLONGITUDE"}
        sel = ", ".join(f"{v} AS {k}" if v in c else f"NULL AS {k}" for k, v in want.items())
        assets, by_pk = {}, {}
        for row in con.execute(f"SELECT Z_PK, ZDIRECTORY, ZFILENAME, {sel} FROM {at}"):
            pk, d, f, fav, hid, trash, kind, sub, date, lat, lon = row
            if not d or not f:
                continue
            ok_loc = lat is not None and lon is not None and not (lat == -180 and lon == -180) and (lat or lon)
            a = Attrs(favorite=bool(fav), hidden=bool(hid), trashed=bool(trash), video=kind == 1,
                      live=sub == SUBTYPE_LIVE, screenshot=sub == SUBTYPE_SCREENSHOT, taken=_date(date),
                      lat=float(lat) if ok_loc else None, lon=float(lon) if ok_loc else None)
            assets[f"{d.strip('/')}/{f}"] = a
            by_pk[pk] = a
        if "ZADDITIONALASSETATTRIBUTES" in tables:
            xc = _cols(con, "ZADDITIONALASSETATTRIBUTES")
            if {"ZASSET", "ZORIGINALFILENAME"} <= xc:
                for apk, name in con.execute("SELECT ZASSET, ZORIGINALFILENAME FROM ZADDITIONALASSETATTRIBUTES "
                                             "WHERE ZORIGINALFILENAME IS NOT NULL"):
                    if apk in by_pk:
                        by_pk[apk].original = str(name)

        albums = []
        if "ZGENERICALBUM" in tables:
            ac = _cols(con, "ZGENERICALBUM")
            if {"ZTITLE", "ZKIND"} <= ac:
                trash_col = "ZTRASHEDSTATE" if "ZTRASHEDSTATE" in ac else "0"
                rows = list(con.execute(f"SELECT Z_PK, ZTITLE FROM ZGENERICALBUM WHERE ZKIND = ? AND "
                                        f"COALESCE({trash_col}, 0) = 0 AND ZTITLE IS NOT NULL", (USER_ALBUM,)))
                link = _album_link(con, tables)
                counts = {}
                if link:
                    lt, a_col, s_col = link
                    for album_pk, asset_pk in con.execute(f"SELECT {a_col}, {s_col} FROM {lt}"):
                        a = by_pk.get(asset_pk)
                        if a is not None and not a.hidden and not a.trashed:
                            a.albums.append(f"album:{album_pk}")
                            counts[album_pk] = counts.get(album_pk, 0) + 1
                albums = [(f"album:{pk}", title, counts.get(pk, 0)) for pk, title in rows]
        return Library(assets, albums)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _album_link(con, tables: set):
    """The album ↔ asset table: Z_<n>ASSETS with a Z_<n>ALBUMS column and a Z_<m>ASSETS column."""
    for t in sorted(tables):
        if not re.fullmatch(r"Z_\d+ASSETS", t):
            continue
        cols = [x for x in _cols(con, t)]
        a = next((x for x in cols if re.fullmatch(r"Z_\d+ALBUMS", x)), None)
        s = next((x for x in cols if re.fullmatch(r"Z_\d+ASSETS", x)), None)
        if a and s:
            return t, a, s
    return None
