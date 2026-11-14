"""
PhoneKeep - photo sources for the photo picker.

Two places photos can come from:
  * BackupPhotoSource - the camera roll inside an iPhone backup (when iCloud Photos is off);
  * DevicePhotoSource - straight off the iPhone over USB / Wi-Fi (works with iCloud Photos).

Both list the same kind of PhotoItem, make small preview thumbnails, and copy chosen items.
For previews they use the small JPEG thumbnails iOS keeps itself
(Media/PhotoData/Thumbnails/V2/DCIM/.../<n>.JPG), so browsing doesn't download every
full-size photo; they fall back to shrinking the original when no thumbnail exists.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import inspect
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".dng", ".tif", ".tiff", ".bmp"}
VID_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi"}
THUMB_PX = 240

try:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
except Exception:  # Pillow missing: no previews, picking by name/date still works
    Image = None


@dataclass
class PhotoItem:
    id: str                # e.g. "DCIM/100APPLE/IMG_0001.HEIC"
    name: str
    size: int
    when: dt.datetime
    video: bool
    live_video: Optional[str] = None  # id of the .MOV that belongs to a Live Photo
    # P1, from the phone's Photos library (library.py); left at these defaults when it can't be read
    favorite: bool = False
    hidden: bool = False
    screenshot: bool = False
    albums: tuple = ()
    lat: Optional[float] = None
    lon: Optional[float] = None
    live_lib: bool = False
    cloud_only: bool = False          # the full photo is only in iCloud: shown greyed, can't be saved from here

    @property
    def month(self) -> str:
        return self.when.strftime("%Y-%m")

    @property
    def live(self) -> bool:
        return self.live_video is not None


def _apply_library(items: list[PhotoItem], lib, has_file=None) -> list[PhotoItem]:
    """Favourite / hidden / screenshot / albums / location and the date taken, from the Photos library.
    Items in Recently Deleted are left out (the Photos app doesn't show them in the library either).

    With iCloud Photos, photos that came from another device (and some the iPhone re-downloaded) are kept in
    PhotoData/CPLAssets, not in DCIM; they are only found through the library. has_file(id) says whether
    such a file is really there (a backup knows; on the phone the library is trusted)."""
    if lib is None:
        return items
    seen = {i.id for i in items}
    for key, a in getattr(lib, "assets", {}).items():
        if key in seen or a.trashed or not key.startswith(("DCIM/", "PhotoData/")):
            continue
        ext = Path(key).suffix.lower()
        if ext not in IMG_EXT | VID_EXT:
            continue
        # not found where it should be: a DCIM file missing from the phone's folder, a file not in the backup,
        # or the library saying the original isn't on the phone ("Optimise iPhone Storage")
        cloud = key.startswith("DCIM/") or a.local is False or (has_file is not None and not has_file(key))
        name = getattr(a, "original", None) or Path(key).name       # "IMG_1234.HEIC", not the iCloud file name
        items.append(PhotoItem(key, name, 0, a.taken or dt.datetime(1970, 1, 1), a.video or ext in VID_EXT,
                               cloud_only=cloud))
    out = []
    for i in items:
        a = lib.get(i.id)
        if a is None:
            out.append(i)
            continue
        if a.trashed:
            continue
        i.favorite, i.hidden, i.screenshot = a.favorite, a.hidden, a.screenshot
        i.live_lib = a.live                     # a Live Photo per the library (its video may be kept elsewhere)
        i.albums, i.lat, i.lon = tuple(a.albums), a.lat, a.lon
        if a.taken is not None:
            i.when = a.taken
        out.append(i)
    out.sort(key=lambda i: i.when, reverse=True)
    return out


def _pair_live_photos(items: list[PhotoItem]) -> list[PhotoItem]:
    """Hide the .MOV half of a Live Photo and attach it to its still image."""
    stills = {(os.path.dirname(i.id), Path(i.name).stem.upper()): i for i in items if not i.video}
    out = []
    for i in items:
        key = (os.path.dirname(i.id), Path(i.name).stem.upper())
        if i.video and Path(i.name).suffix.lower() == ".mov" and key in stills:
            stills[key].live_video = i.id
            continue
        out.append(i)
    out.sort(key=lambda i: i.when, reverse=True)
    return out


def _make_thumb(src: Path, dest: Path) -> Optional[Path]:
    if Image is None:
        return None
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((THUMB_PX, THUMB_PX))
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(dest, "JPEG", quality=80)
        return dest
    except Exception:
        return None


class PhotoSource:
    label = "photos"

    def __init__(self, cache_dir: Path):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _thumb_path(self, item: PhotoItem) -> Path:
        return self.cache / "thumbs" / (hashlib.sha1(item.id.encode(), usedforsecurity=False).hexdigest()[:20] + ".jpg")

    def items(self) -> list[PhotoItem]:
        raise NotImplementedError

    def library(self):
        """The phone's Photos library (favourites, albums, hidden…), or None. Read once."""
        if not hasattr(self, "_library"):
            self._library = None
            try:
                db = self._library_copy()
                if db is not None:
                    import library
                    self._library = library.read(db)
            except Exception:
                self._library = None
        return self._library

    def _library_copy(self) -> Optional[Path]:
        return None

    def thumbnail(self, item: PhotoItem) -> Optional[Path]:
        raise NotImplementedError

    def copy(self, item_id: str, dest: Path) -> bool:
        raise NotImplementedError

    def read(self, item_id: str) -> Optional[bytes]:
        """The photo itself in memory, for the Space preview (Q1); None when it can't be read."""
        return None

    def close(self) -> None:
        pass


class BackupPhotoSource(PhotoSource):
    label = "this backup"

    def __init__(self, reader, cache_dir: Path):
        super().__init__(cache_dir)
        self.reader = reader
        self.meta = reader.file_meta("CameraRollDomain", "Media/")  # rel -> (fileID, mtime, size)

    def items(self) -> list[PhotoItem]:
        out = []
        for rel, (fid, mtime, size) in self.meta.items():
            if not rel.startswith("Media/DCIM/"):
                continue
            ext = Path(rel).suffix.lower()
            if ext not in IMG_EXT | VID_EXT:
                continue
            when = dt.datetime.fromtimestamp(mtime) if mtime else dt.datetime(1970, 1, 1)
            out.append(PhotoItem(rel[len("Media/"):], Path(rel).name, size or 0, when, ext in VID_EXT))
        items = _apply_library(_pair_live_photos(out), self.library(),
                               has_file=lambda key: ("Media/" + key) in self.meta)
        for i in items:
            if not i.size and ("Media/" + i.id) in self.meta:
                i.size = self.meta["Media/" + i.id][2] or 0
        return items

    def _library_copy(self) -> Optional[Path]:
        dest = self.cache / "library" / "Photos.sqlite"
        for extra in ("-wal", "-shm"):                     # never pair a fresh copy with an old log
            Path(str(dest) + extra).unlink(missing_ok=True)
        rel = "Media/PhotoData/Photos.sqlite"
        if rel not in self.meta or not self._extract(rel, dest):
            return None
        for extra in ("-wal", "-shm"):                     # the latest changes may still be in the write-ahead log
            if rel + extra in self.meta:
                self._extract(rel + extra, Path(str(dest) + extra))
        return dest

    def _extract(self, rel: str, dest: Path) -> bool:
        m = self.meta.get(rel)
        if not m:
            return False
        with self._lock:
            ok = self.reader.extract("CameraRollDomain", rel, m[0], dest)
        if ok and m[1]:
            os.utime(dest, (m[1], m[1]))
        return ok

    def read(self, item_id: str) -> Optional[bytes]:
        m = self.meta.get("Media/" + item_id)
        if not m:
            return None
        with self._lock:
            return self.reader.read_bytes("CameraRollDomain", "Media/" + item_id, m[0])

    def thumbnail(self, item: PhotoItem) -> Optional[Path]:
        tp = self._thumb_path(item)
        if tp.exists():
            return tp
        prefix = f"Media/PhotoData/Thumbnails/V2/{item.id}/"
        ios_thumbs = sorted((r for r in self.meta if r.startswith(prefix) and r.lower().endswith(".jpg")),
                            key=lambda r: self.meta[r][2] or 0, reverse=True)
        src = self.cache / "src" / tp.name
        if ios_thumbs and self._extract(ios_thumbs[0], src):
            return _make_thumb(src, tp)
        if item.video:
            return None
        full = self.cache / "full" / item.id
        if full.exists() or self._extract("Media/" + item.id, full):
            return _make_thumb(full, tp)
        return None

    def copy(self, item_id: str, dest: Path) -> bool:
        if dest.exists() and dest.stat().st_size > 0:
            return True
        full = self.cache / "full" / item_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        if full.exists():
            shutil.copy2(full, dest)
            return True
        return self._extract("Media/" + item_id, dest)


async def _aw(x):
    return await x if inspect.isawaitable(x) else x


class DevicePhotoSource(PhotoSource):
    """Talks to the iPhone's media folder (AFC) on a private event loop in a background thread."""
    label = "the iPhone"

    def __init__(self, udid: Optional[str], cache_dir: Path):
        super().__init__(cache_dir)
        self.udid = udid
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.afc = None
        self._run(self._connect())
        self._sizes: dict[str, int] = {}

    def _run(self, coro, timeout: float = 600):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _connect(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
        lockdown = await _aw(create_using_usbmux(serial=self.udid))
        self.afc = AfcService(lockdown)
        await _aw(self.afc.__aenter__())

    async def _items(self) -> list[PhotoItem]:
        out = []
        async for root, _dirs, files in self.afc.walk("DCIM"):
            for f in files:
                ext = Path(f).suffix.lower()
                if f.startswith(".") or ext not in IMG_EXT | VID_EXT:
                    continue
                rid = "/".join(x for x in (root.strip("/") + "/" + f).split("/") if x)
                st = await _aw(self.afc.stat(rid))
                when = st.get("st_mtime") or st.get("st_birthtime")
                when = when if isinstance(when, dt.datetime) else dt.datetime(1970, 1, 1)
                size = int(st.get("st_size", 0))
                self._sizes[rid] = size
                out.append(PhotoItem(rid, f, size, when.replace(tzinfo=None), ext in VID_EXT))
        return _pair_live_photos(out)

    def items(self) -> list[PhotoItem]:
        items = _apply_library(self._run(self._items(), timeout=3600), self.library())
        # The library says a photo is on the phone when only a smaller version is (checked on the owner's
        # iPhone, 14 Nov: 22 of 46 such photos had no file). Look for each one; a missing file is iCloud-only.
        todo = [i for i in items if i.id.startswith("PhotoData/") and not i.cloud_only]
        if todo:
            found = self._run(self._exist([i.id for i in todo]), timeout=3600)
            for i in todo:
                if i.id in found:
                    self._sizes[i.id] = found[i.id]
                    i.size = found[i.id]
                else:
                    i.cloud_only = True
        return items

    async def _exist(self, ids: list[str]) -> dict:
        """{id: size} for the files that are on the phone."""
        out = {}
        for rid in ids:
            try:
                st = await _aw(self.afc.stat(rid))
                out[rid] = int(st.get("st_size", 0))
            except Exception:
                pass
        return out

    def _library_copy(self) -> Optional[Path]:
        dest = self.cache / "library" / "Photos.sqlite"
        for extra in ("-wal", "-shm"):                     # never pair a fresh copy with an old log
            Path(str(dest) + extra).unlink(missing_ok=True)
        with self._lock:
            if not self._run(self._pull("PhotoData/Photos.sqlite", dest), timeout=600):
                return None
            for extra in ("-wal", "-shm"):
                self._run(self._pull("PhotoData/Photos.sqlite" + extra, Path(str(dest) + extra)), timeout=600)
        return dest

    async def _pull(self, src: str, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self.afc.pull(src, str(dest), progress_bar=False)
            return dest.exists()
        except TypeError:  # older signature without progress_bar
            await self.afc.pull(src, str(dest))
            return dest.exists()
        except Exception:
            return False

    async def _thumbnail(self, item: PhotoItem) -> Optional[Path]:
        tp = self._thumb_path(item)
        if tp.exists():
            return tp
        tdir = f"PhotoData/Thumbnails/V2/{item.id}"
        try:
            names = [n for n in await _aw(self.afc.listdir(tdir)) if n.lower().endswith(".jpg")]
        except Exception:
            names = []
        src = self.cache / "src" / tp.name
        if names:
            best = sorted(names, key=lambda n: (len(n), n), reverse=True)[0]
            if await self._pull(f"{tdir}/{best}", src):
                return _make_thumb(src, tp)
        if item.video:
            return None
        full = self.cache / "full" / item.id  # reused when the photo is copied later
        if full.exists() or await self._pull(item.id, full):
            return _make_thumb(full, tp)
        return None

    def thumbnail(self, item: PhotoItem) -> Optional[Path]:
        with self._lock:
            return self._run(self._thumbnail(item), timeout=120)

    def copy(self, item_id: str, dest: Path) -> bool:
        size = self._sizes.get(item_id)
        if dest.exists() and dest.stat().st_size > 0 and (size is None or dest.stat().st_size == size):
            return True
        full = self.cache / "full" / item_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        if full.exists():
            shutil.copy2(full, dest)
            return True
        with self._lock:
            return self._run(self._pull(item_id, dest))

    def read(self, item_id: str) -> Optional[bytes]:
        full = self.cache / "full" / item_id
        if full.exists():
            return full.read_bytes()
        with self._lock:
            try:
                return self._run(_aw(self.afc.get_file_contents(item_id)), timeout=300)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            # fall back to copying it (the way Save does), then reading the copy and removing it at once
            import quicklook
            tmp = quicklook.private_dir() / ("read-" + hashlib.sha1(item_id.encode(), usedforsecurity=False).hexdigest()[:16])
            try:
                if self._run(self._pull(item_id, tmp)) and tmp.exists():
                    return tmp.read_bytes()
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            finally:
                tmp.unlink(missing_ok=True)
            return None

    def close(self) -> None:
        try:
            if self.afc is not None:
                self._run(_aw(self.afc.__aexit__(None, None, None)), timeout=10)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
