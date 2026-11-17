"""
PhoneKeep - things read live from the connected iPhone (not from a backup).

Apple lets a trusted computer read these directly:
  * the wallpaper (a picture of the home / lock screen),
  * the media folder: Music (iTunes_Control) and Books,
  * the Documents folder of apps that share files (Files, Pages, VLC, ...).

Everything runs on a private asyncio loop in a background thread, so the window can call
these like ordinary functions from worker threads. Nothing here writes to the phone.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import os
import plistlib
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

from reconnect import NotConnected, retry_once


async def _aw(x):
    return await x if inspect.isawaitable(x) else x


@dataclass
class Track:
    title: str
    artist: str
    album: str
    seconds: float
    path: str            # on the phone, e.g. iTunes_Control/Music/F12/ABCD.m4a
    size: int = 0
    kind: str = "Song"   # Song, Music video, Podcast, Audiobook...
    album_artist: str = ""                   # P2: the rest of the library's details, written into a saved song
    genre: str = ""
    year: int = 0
    track_no: int = 0
    track_count: int = 0
    disc_no: int = 0
    disc_count: int = 0
    artwork: str = ""    # the artwork's file on the phone (iTunes_Control/iTunes/Artwork/Originals/...), if any
    protected: bool = False                  # FairPlay: saved as it is, only plays on the owner's devices


class MusicList(list):
    """The songs on the phone, and how many more the library lists that only stream (Apple Music, iCloud)."""
    streaming = 0


@dataclass
class Book:
    title: str
    author: str
    path: str            # on the phone, e.g. Books/1234.epub (EPUBs are folders on the phone)
    kind: str            # EPUB, PDF, Audiobook
    size: int = 0
    is_dir: bool = False


@dataclass
class AppInfo:
    id: str
    name: str
    version: str = ""
    shares_files: bool = False


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    when: Optional[dt.datetime] = None
    extra: dict = field(default_factory=dict)


def safe_local(base: Path, rel: str) -> Optional[Path]:
    """base/rel, refusing anything that would land outside base (.., absolute paths)."""
    parts = [p for p in PurePosixPath(rel.replace("\\", "/")).parts if p not in ("/", "", ".")]
    if any(p == ".." for p in parts) or not parts:
        return None
    out = base.joinpath(*parts)
    try:
        out.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    return out


class LiveDevice:
    """One connection to the iPhone; each call opens the service it needs."""

    def __init__(self, udid: Optional[str], cache_dir: Optional[Path] = None):
        self.udid = udid
        made_cache = cache_dir is None
        if cache_dir is None:
            import quicklook
            cache_dir = quicklook.private_tmp("phonekeep-live-")     # goes when PhoneKeep closes
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self._lock = threading.Lock()
        self._conn_lock = threading.Lock()
        self.lockdown = None
        self.generation = 0          # counts reconnects (5.1.3)
        import timing
        try:
            with timing.step("live: lockdown connect"):
                self.run(self._connect(), 60)
        except BaseException:
            # not connected (locked, gone): let go of the loop's thread, and the empty folder made for this connection,
            # so tries every minute leave nothing behind (5.1.3)
            self.loop.call_soon_threadsafe(self.loop.stop)
            if made_cache:
                shutil.rmtree(self.cache, ignore_errors=True)
            raise

    # plumbing -----------------------------------------------------------------
    answered_at = 0.0       # when the iPhone last answered anything (5.1.3: a storage question that timed out is
                            # asked again then)
    closed = False          # once closed, reads fail at once as a dropped connection (5.1.3)

    def run(self, coro, timeout: float = 600):
        import reconnect
        return reconnect.run_on(self, coro, timeout)

    async def _connect(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        self.lockdown = await _aw(create_using_usbmux(serial=self.udid))

    def where(self) -> Optional[str]:
        """"USB" / "Network" when this iPhone is reachable now, None when it's gone (read-only, 5.1.3)."""
        import reconnect
        return reconnect.where(self.udid)

    def reconnect(self, seen: Optional[int] = None):
        """A new connection to the same phone (by its UDID, never another one), after the old one dropped. `seen`:
        the generation the caller saw fail; if another thread has reconnected since, that's kept."""
        if not self.udid:
            raise ConnectionError("no UDID: can't tell which iPhone to reconnect to")
        if self.closed:                          # let go of by the window: a new connection is the window's job
            raise ConnectionAbortedError("the connection was closed")
        with self._conn_lock:
            if seen is not None and seen != self.generation:
                return
            old, self.lockdown = self.lockdown, NotConnected()
            try:
                if old is not None and not isinstance(old, NotConnected):
                    self.run(_aw(old.close()), 5)
            except Exception:
                pass
            self.run(self._connect(), 60)
            self.generation += 1

    async def _afc(self):
        from pymobiledevice3.services.afc import AfcService
        afc = AfcService(self.lockdown)
        await _aw(afc.__aenter__())
        return afc

    @staticmethod
    async def _close(svc):
        try:
            await _aw(svc.__aexit__(None, None, None))
        except Exception:
            pass

    @staticmethod
    async def _pull(afc, src: str, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            await afc.pull(src, str(dest), progress_bar=False)
        except TypeError:
            await afc.pull(src, str(dest))
        return dest.exists()

    def close(self):
        import reconnect
        ld = self.lockdown
        reconnect.shut(self, _aw(ld.close()) if ld is not None and not isinstance(ld, NotConnected)
                       and hasattr(ld, "close") else None)

    # wallpaper ----------------------------------------------------------------
    async def _wallpaper(self, which: str) -> Optional[bytes]:
        from pymobiledevice3.services.springboard import SpringBoardServicesService
        sb = SpringBoardServicesService(self.lockdown)
        await _aw(sb.__aenter__())
        try:
            for get in (lambda: sb.get_wallpaper_preview_image(which),
                        lambda: sb.get_wallpaper_pngdata() if which == "homescreen" else None):
                try:
                    data = await _aw(get())
                    if data:
                        return data
                except Exception:
                    continue
            return None
        finally:
            await self._close(sb)

    @retry_once
    def wallpaper(self, which: str = "homescreen") -> Optional[Path]:
        """PNG of the home screen (or 'lockscreen') wallpaper, or None."""
        import timing
        with self._lock, timing.step(f"live: wallpaper ({which})"):
            data = self.run(self._wallpaper(which), 60)
        if not data:
            return None
        p = self.cache / f"wallpaper-{which}.png"
        p.write_bytes(data)
        return p

    # music --------------------------------------------------------------------
    async def _music(self) -> list[Track]:
        afc = await self._afc()
        try:
            db_dir = self.cache / "medialib"
            shutil.rmtree(db_dir, ignore_errors=True)
            base = "iTunes_Control/iTunes/MediaLibrary.sqlitedb"
            tracks: list[Track] = []
            try:
                if await self._pull(afc, base, db_dir / "MediaLibrary.sqlitedb"):
                    for sfx in ("-wal", "-shm"):
                        try:
                            await self._pull(afc, base + sfx, db_dir / ("MediaLibrary.sqlitedb" + sfx))
                        except Exception:
                            pass
                    tracks = _tracks_from_db(db_dir / "MediaLibrary.sqlitedb")
            except Exception:
                tracks = []
            streaming = getattr(tracks, "streaming", 0)
            # sizes, and any files the library doesn't describe
            known = {t.path for t in tracks}
            sizes = {}
            walked = False
            try:
                async for root, _dirs, files in afc.walk("iTunes_Control/Music"):
                    for f in files:
                        rel = "/".join(x for x in (root.strip("/") + "/" + f).split("/") if x)
                        try:
                            st = await _aw(afc.stat(rel))
                            sizes[rel] = int(st.get("st_size", 0))
                        except Exception:
                            sizes[rel] = 0
                        if rel not in known and not f.startswith("."):
                            tracks.append(Track(Path(f).stem, "", "", 0, rel))
                walked = True
            except Exception:
                pass
            for t in tracks:
                t.size = sizes.get(t.path, 0)
            out = MusicList(t for t in tracks if t.path in sizes or not walked)
            out.streaming = streaming + len(tracks) - len(out)    # listed by the library, but its file isn't here
            return out
        finally:
            await self._close(afc)

    @retry_once
    def music(self) -> "MusicList":
        with self._lock:
            return self.run(self._music(), 1800)

    async def _copy_song(self, t: Track, dest: Path) -> bool:
        afc = await self._afc()
        try:
            part = dest.with_name(dest.name + ".part")
            if not await self._pull(afc, t.path, part):
                return False
            art = await self._artwork(afc, t)
        finally:
            await self._close(afc)
        import music_tags
        music_tags.finish(part, dest, t, art)
        return True

    @retry_once
    def copy_song(self, t: Track, dest: Path) -> bool:
        """P2: copy a song and write the library's title, artist, album and artwork into it."""
        with self._lock:
            return self.run(self._copy_song(t, Path(dest)), 3600)

    async def _artwork(self, afc, t: Track) -> Optional[bytes]:
        if not t.artwork:
            return None
        tmp = Path(tempfile.mkdtemp(dir=self.cache))
        try:
            p = tmp / "art"
            return p.read_bytes() if await self._pull(afc, t.artwork, p) else None
        except Exception:
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def _artwork_alone(self, t: Track) -> Optional[bytes]:
        afc = await self._afc()
        try:
            return await self._artwork(afc, t)
        finally:
            await self._close(afc)

    @retry_once
    def artwork(self, t: Track) -> Optional[bytes]:
        """P2: a song's artwork as the Music app stores it (JPEG or PNG), or None."""
        with self._lock:
            return self.run(self._artwork_alone(t), 60)

    # books --------------------------------------------------------------------
    async def _books(self) -> list[Book]:
        afc = await self._afc()
        try:
            meta = {}
            for plist in ("Books/Books.plist", "Books/Purchases/Purchases.plist"):
                try:
                    tmp = self.cache / "books" / Path(plist).name
                    if await self._pull(afc, plist, tmp):
                        with open(tmp, "rb") as f:
                            for b in plistlib.load(f).get("Books", []):
                                p = b.get("Path") or b.get("Package Hash") or ""
                                if p:
                                    meta[Path(p).name] = (b.get("Name") or b.get("Title") or "",
                                                          b.get("Artist") or b.get("Author") or "")
                except Exception:
                    continue
            out: list[Book] = []
            for folder in ("Books", "Books/Purchases"):
                try:
                    names = await _aw(afc.listdir(folder))
                except Exception:
                    continue
                for n in names:
                    low = n.lower()
                    kind = ("EPUB" if low.endswith(".epub") else "PDF" if low.endswith(".pdf")
                            else "Audiobook" if low.endswith((".m4b", ".mp3", ".m4a")) else None)
                    if not kind:
                        continue
                    rel = f"{folder}/{n}"
                    try:
                        st = await _aw(afc.stat(rel))
                    except Exception:
                        st = {}
                    is_dir = st.get("st_ifmt") == "S_IFDIR"
                    title, author = meta.get(n, ("", ""))
                    out.append(Book(title or Path(n).stem, author, rel, kind, int(st.get("st_size", 0)), is_dir))
            return out
        finally:
            await self._close(afc)

    @retry_once
    def books(self) -> list[Book]:
        with self._lock:
            return self.run(self._books(), 600)

    # media folder copy --------------------------------------------------------
    async def _copy_media(self, path: str, dest: Path, is_dir: bool) -> bool:
        afc = await self._afc()
        try:
            if not is_dir:
                return await self._pull(afc, path, dest)
            # an EPUB stored unpacked on the phone: copy the folder, then zip it into a real .epub
            tmp = Path(tempfile.mkdtemp(dir=self.cache))
            try:
                await afc.pull(path, str(tmp), progress_bar=False)
            except TypeError:
                await afc.pull(path, str(tmp))
            src = tmp / Path(path).name
            if not src.is_dir():
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dest, "w") as z:
                mt = src / "mimetype"
                if mt.exists():
                    z.write(mt, "mimetype", compress_type=zipfile.ZIP_STORED)
                for f in sorted(src.rglob("*")):
                    if f.is_file() and f != mt:
                        z.write(f, f.relative_to(src).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
            shutil.rmtree(tmp, ignore_errors=True)
            return True
        finally:
            await self._close(afc)

    @retry_once
    def copy_media(self, path: str, dest: Path, is_dir: bool = False) -> bool:
        with self._lock:
            return self.run(self._copy_media(path, dest, is_dir), 3600)

    # the app list, in two passes (5.1.3): names at once, sizes a few at a time ---------------------------------
    async def _app_names(self) -> dict[str, str]:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService
        async with InstallationProxyService(self.lockdown) as ip:
            found = await _aw(ip.browse(options={"ApplicationType": "User"},
                                        attributes=["CFBundleIdentifier", "CFBundleDisplayName", "CFBundleName"]))
        return {a["CFBundleIdentifier"]: a.get("CFBundleDisplayName") or a.get("CFBundleName") or ""
                for a in found or [] if a.get("CFBundleIdentifier")}

    @retry_once
    def app_names(self, timeout: float = 60) -> dict[str, str]:
        """bundle id -> name of the installed apps, without sizes (a fraction of a second over a cable)."""
        import timing
        with self._lock, timing.step("live: app names"):
            return self.run(self._app_names(), timeout)

    async def _app_sizes(self, bundles: list[str]) -> dict[str, tuple[int, int]]:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService
        async with InstallationProxyService(self.lockdown) as ip:
            apps = await _aw(ip.get_apps(application_type="User", calculate_sizes=True, bundle_identifiers=bundles))
        return {b: (int(a.get("StaticDiskUsage") or 0), int(a.get("DynamicDiskUsage") or 0))
                for b, a in (apps or {}).items()}

    @retry_once
    def app_sizes(self, bundles: list[str], timeout: float = 120) -> dict[str, tuple[int, int]]:
        """bundle id -> (app bytes, data bytes) for these apps (about 1 s for 20 over a cable)."""
        import timing
        with self._lock, timing.step(f"live: app sizes ({len(bundles)} apps)"):
            return self.run(self._app_sizes(bundles), timeout)

    # apps & their files -------------------------------------------------------
    async def _apps(self) -> list[AppInfo]:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService
        ip = InstallationProxyService(self.lockdown)
        await _aw(ip.__aenter__())
        try:
            apps = await _aw(ip.get_apps(application_type="User"))
        finally:
            await self._close(ip)
        out = []
        for bid, info in (apps or {}).items():
            out.append(AppInfo(bid, info.get("CFBundleDisplayName") or info.get("CFBundleName") or bid,
                               info.get("CFBundleShortVersionString") or "",
                               bool(info.get("UIFileSharingEnabled"))))
        out.sort(key=lambda a: (not a.shares_files, a.name.lower()))
        return out

    @retry_once
    def apps(self) -> list[AppInfo]:
        with self._lock:
            return self.run(self._apps(), 300)

    async def _app_list(self, bundle_id: str, path: str) -> list[Entry]:
        from pymobiledevice3.services.house_arrest import HouseArrestService
        ha = await HouseArrestService.create(self.lockdown, bundle_id, documents_only=True)
        try:
            out = []
            base = path.strip("/") or "Documents"
            for n in await _aw(ha.listdir(base)):
                if n in (".", ".."):
                    continue
                rel = f"{base}/{n}"
                try:
                    st = await _aw(ha.stat(rel))
                except Exception:
                    st = {}
                when = st.get("st_mtime")
                out.append(Entry(n, rel, st.get("st_ifmt") == "S_IFDIR", int(st.get("st_size", 0) or 0),
                                 when.replace(tzinfo=None) if isinstance(when, dt.datetime) else None))
            out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
            return out
        finally:
            await self._close(ha)

    @retry_once
    def app_list(self, bundle_id: str, path: str = "Documents") -> list[Entry]:
        with self._lock:
            return self.run(self._app_list(bundle_id, path), 300)

    async def _app_pull(self, bundle_id: str, path: str, dest_dir: Path) -> bool:
        from pymobiledevice3.services.house_arrest import HouseArrestService
        ha = await HouseArrestService.create(self.lockdown, bundle_id, documents_only=True)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                await ha.pull(path, str(dest_dir), progress_bar=False)
            except TypeError:
                await ha.pull(path, str(dest_dir))
            return (dest_dir / PurePosixPath(path).name).exists()
        finally:
            await self._close(ha)

    @retry_once
    def app_pull(self, bundle_id: str, path: str, dest_dir: Path) -> bool:
        """Copy a file or folder from an app's Documents into dest_dir."""
        with self._lock:
            return self.run(self._app_pull(bundle_id, path, Path(dest_dir)), 3600)


ARTWORK_ROOT = "iTunes_Control/iTunes/Artwork/Originals"


def _tracks_from_db(db: Path) -> MusicList:
    """Read song titles etc. from the phone's MediaLibrary.sqlitedb (schema varies by iOS).
    Songs with no file on the phone (they stream from Apple Music / iCloud) aren't returned; they're counted in
    .streaming so the window can say why they're missing (P2)."""
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    out = MusicList()
    try:
        t = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"item", "item_extra"} <= t:
            return out
        icols = {r[1] for r in con.execute("PRAGMA table_info(item)")}
        ecols = {r[1] for r in con.execute("PRAGMA table_info(item_extra)")}

        def ecol(c, default):
            return f"e.{c}" if c in ecols else f"{default} AS {c}"

        def icol(c):
            return f"i.{c}" if c in icols else f"0 AS {c}"
        sel = ["i.item_pid", ecol("title", "''"), ecol("location", "''"), ecol("total_time_ms", "0"),
               ecol("year", "0"), ecol("track_count", "0"), ecol("disc_count", "0"),
               icol("track_number"), icol("disc_number"), icol("album_pid")]
        joins = ""
        for table, key, col, alias, name in (
                ("base_location", "base_location_id", "path", "b", "base"),
                ("item_artist", "item_artist_pid", "item_artist", "a", "artist"),
                ("album", "album_pid", "album", "al", "album"),
                ("album_artist", "album_artist_pid", "album_artist", "aa", "album_artist"),
                ("genre", "genre_id", "genre", "g", "genre")):
            if table in t and key in icols and col in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
                sel.append(f"{alias}.{col} AS {name}")
                joins += f" LEFT JOIN {table} {alias} ON {alias}.{key} = i.{key}"
            else:
                sel.append(f"'' AS {name}")
        if "media_type" in icols:
            sel.append("i.media_type")
        protected = set()
        if "item_store" in t and "is_protected" in {r[1] for r in con.execute("PRAGMA table_info(item_store)")}:
            protected = {r[0] for r in con.execute("SELECT item_pid FROM item_store WHERE is_protected")}
        # artwork: a song's own (entity type 0), else its album's (type 4); the file is under Artwork/Originals
        art: dict[tuple[int, int], str] = {}
        if {"artwork_token", "artwork"} <= t:
            try:
                for r in con.execute("SELECT k.entity_pid, k.entity_type, w.relative_path FROM artwork_token k "
                                     "JOIN artwork w ON w.artwork_token = k.artwork_token "
                                     "WHERE k.entity_type IN (0, 4) AND w.relative_path != ''"):
                    art.setdefault((r[1], r[0]), r[2])
            except sqlite3.Error:
                art = {}
        q = f"SELECT {', '.join(sel)} FROM item i JOIN item_extra e ON e.item_pid = i.item_pid{joins}"
        for r in con.execute(q):
            loc = r["location"] or ""
            if not loc:
                out.streaming += 1        # not on the phone (streams from Apple Music / iCloud)
                continue
            base = (r["base"] or "iTunes_Control/Music").strip("/")
            ext = Path(loc).suffix.lower()
            kind = ("Audiobook" if ext in (".m4b", ".aa", ".aax") else
                    "Video" if ext in (".m4v", ".mp4", ".mov") else "Song")
            cover = art.get((0, r["item_pid"])) or art.get((4, r["album_pid"])) or ""
            out.append(Track(r["title"] or Path(loc).stem, r["artist"] or "", r["album"] or "",
                             (r["total_time_ms"] or 0) / 1000.0, f"{base}/{loc}", 0, kind,
                             album_artist=r["album_artist"] or "", genre=r["genre"] or "",
                             year=int(r["year"] or 0), track_no=int(r["track_number"] or 0),
                             track_count=int(r["track_count"] or 0), disc_no=int(r["disc_number"] or 0),
                             disc_count=int(r["disc_count"] or 0),
                             artwork=f"{ARTWORK_ROOT}/{cover}" if cover else "",
                             protected=r["item_pid"] in protected or ext == ".m4p"))
        return out
    finally:
        con.close()


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
