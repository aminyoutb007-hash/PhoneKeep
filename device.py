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
        if cache_dir is None:
            import quicklook
            cache_dir = quicklook.private_tmp("phonekeep-live-")     # goes when PhoneKeep closes
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self._lock = threading.Lock()
        self.lockdown = None
        self.run(self._connect(), 60)

    # plumbing -----------------------------------------------------------------
    def run(self, coro, timeout: float = 600):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _connect(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        self.lockdown = await _aw(create_using_usbmux(serial=self.udid))

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
        try:
            if self.lockdown is not None and hasattr(self.lockdown, "close"):
                self.run(_aw(self.lockdown.close()), 10)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)

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

    def wallpaper(self, which: str = "homescreen") -> Optional[Path]:
        """PNG of the home screen (or 'lockscreen') wallpaper, or None."""
        with self._lock:
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
            # sizes, and any files the library doesn't describe
            known = {t.path for t in tracks}
            sizes = {}
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
            except Exception:
                pass
            for t in tracks:
                t.size = sizes.get(t.path, 0)
            return [t for t in tracks if t.path in sizes] if sizes else tracks
        finally:
            await self._close(afc)

    def music(self) -> list[Track]:
        with self._lock:
            return self.run(self._music(), 1800)

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

    def copy_media(self, path: str, dest: Path, is_dir: bool = False) -> bool:
        with self._lock:
            return self.run(self._copy_media(path, dest, is_dir), 3600)

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

    def app_pull(self, bundle_id: str, path: str, dest_dir: Path) -> bool:
        """Copy a file or folder from an app's Documents into dest_dir."""
        with self._lock:
            return self.run(self._app_pull(bundle_id, path, Path(dest_dir)), 3600)


def _tracks_from_db(db: Path) -> list[Track]:
    """Read song titles etc. from the phone's MediaLibrary.sqlitedb (schema varies by iOS)."""
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        t = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"item", "item_extra"} <= t:
            return []
        icols = {r[1] for r in con.execute("PRAGMA table_info(item)")}
        ecols = {r[1] for r in con.execute("PRAGMA table_info(item_extra)")}
        sel = ["i.item_pid", "e.title" if "title" in ecols else "'' AS title",
               "e.location" if "location" in ecols else "'' AS location",
               "e.total_time_ms" if "total_time_ms" in ecols else "0 AS total_time_ms"]
        joins = ""
        if "base_location" in t and "base_location_id" in icols:
            sel.append("b.path AS base")
            joins += " LEFT JOIN base_location b ON b.base_location_id = i.base_location_id"
        else:
            sel.append("'' AS base")
        if "item_artist" in t and "item_artist_pid" in icols:
            sel.append("a.item_artist AS artist")
            joins += " LEFT JOIN item_artist a ON a.item_artist_pid = i.item_artist_pid"
        else:
            sel.append("'' AS artist")
        if "album" in t and "album_pid" in icols:
            sel.append("al.album AS album")
            joins += " LEFT JOIN album al ON al.album_pid = i.album_pid"
        else:
            sel.append("'' AS album")
        if "media_type" in icols:
            sel.append("i.media_type")
        out = []
        q = f"SELECT {', '.join(sel)} FROM item i JOIN item_extra e ON e.item_pid = i.item_pid{joins}"
        for r in con.execute(q):
            loc = r["location"] or ""
            if not loc:
                continue  # not on the phone (streams from Apple Music / iCloud)
            base = (r["base"] or "iTunes_Control/Music").strip("/")
            ext = Path(loc).suffix.lower()
            kind = ("Audiobook" if ext in (".m4b", ".aa", ".aax") else
                    "Video" if ext in (".m4v", ".mp4", ".mov") else "Song")
            out.append(Track(r["title"] or Path(loc).stem, r["artist"] or "", r["album"] or "",
                             (r["total_time_ms"] or 0) / 1000.0, f"{base}/{loc}", 0, kind))
        return out
    finally:
        con.close()


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
