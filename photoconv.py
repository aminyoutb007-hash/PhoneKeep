"""P1: save photos as the original or as "Most compatible" JPG (docs/spec/07-photos-media.md#p1-photos).

"Most compatible" turns HEIC/HEIF into JPG and keeps what makes a photo findable: the date taken and the location
(the original EXIF is carried over; when it lacks them, they're filled from the Photos library), and the file's date
is set to the date taken. Other photos (JPG, PNG…) are saved as they are. HEVC videos become H.264 MP4 on a Mac
(videoconv.py, P8); other videos, and every video on Windows, are saved as they are.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path
from typing import Optional

import videoconv

try:
    from PIL import Image
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
except Exception:      # Pillow missing: "Most compatible" falls back to the original
    Image = None

CONVERT = {".heic", ".heif"}
EXIF_IFD, GPS_IFD = 0x8769, 0x8825
DATETIME_ORIGINAL, DATETIME = 0x9003, 0x0132


def jpg_name(name: str) -> str:
    """'IMG_0001.HEIC' → 'IMG_0001.JPG' (other names unchanged)."""
    p = Path(name)
    return p.stem + ".JPG" if p.suffix.lower() in CONVERT else name


def set_file_date(path: Path, when: Optional[dt.datetime]) -> None:
    if when is not None and when.year > 1970:
        try:
            t = when.timestamp()
            os.utime(path, (t, t))
        except (OSError, OverflowError, ValueError):
            pass


def _dms(value: float):
    """Degrees, minutes, seconds (Pillow stores them as EXIF rationals)."""
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = round(((value - d) * 60 - m) * 60, 2)
    return (float(d), float(m), s)


def to_jpg(src: Path, dest: Path, when: Optional[dt.datetime] = None, lat: Optional[float] = None,
           lon: Optional[float] = None, quality: int = 92) -> bool:
    """Convert a HEIC to JPG at dest, keeping the EXIF (date, location, orientation) and the colour profile."""
    if Image is None:
        return False
    try:
        with Image.open(src) as im:
            exif = im.getexif()
            if when is not None and when.year > 1970:
                stamp = when.strftime("%Y:%m:%d %H:%M:%S")
                ifd = exif.get_ifd(EXIF_IFD)
                if not ifd.get(DATETIME_ORIGINAL):
                    ifd[DATETIME_ORIGINAL] = stamp
                if not exif.get(DATETIME):
                    exif[DATETIME] = stamp
            gps = exif.get_ifd(GPS_IFD)
            if lat is not None and lon is not None and not gps.get(2):
                gps[1], gps[2] = ("N" if lat >= 0 else "S"), _dms(lat)
                gps[3], gps[4] = ("E" if lon >= 0 else "W"), _dms(lon)
            dest.parent.mkdir(parents=True, exist_ok=True)
            icc = im.info.get("icc_profile")
            kw = {"quality": quality, "exif": exif.tobytes()}
            if icc:
                kw["icc_profile"] = icc
            im.convert("RGB").save(dest, "JPEG", **kw)
        set_file_date(dest, when)
        return True
    except Exception:
        try:
            dest.unlink()
        except OSError:
            pass
        return False


def free_name(folder: Path, name: str, size: int = 0, when=None) -> str:
    """name, or "name (2).ext" when a different photo already has that name in folder. Two photos can share a
    name (an iPhone restarts at IMG_0001, and iCloud photos from other devices keep their own numbering).
    A file of the same size, or dated with this photo's date (saved files get it), is taken to be this photo
    saved before, so saving again doesn't make copies."""
    p = Path(folder) / name
    if not p.exists() or (size and p.stat().st_size == size):
        return name
    if when is not None:
        try:
            if abs(p.stat().st_mtime - when.timestamp()) < 2:
                return name
        except (OSError, ValueError, OverflowError):
            pass
    stem, ext = Path(name).stem, Path(name).suffix
    n = 2
    while (Path(folder) / f"{stem} ({n}){ext}").exists():
        n += 1
    return f"{stem} ({n}){ext}"


def _saved_before(path: Path, when) -> bool:
    """path is missing, or is this item saved before (saved files are dated with the date taken)."""
    if not path.exists():
        return True
    try:
        return when is not None and abs(path.stat().st_mtime - when.timestamp()) < 2
    except (OSError, ValueError, OverflowError):
        return False


def _live_stem(folder: Path, item, photo_ext: str) -> str:
    """A Live Photo's name, free for the photo and for its video as .MOV and .MP4 (or taken by this Live Photo
    saved before), so neither ever replaces a different file and both keep the same name."""
    stem = Path(item.name).stem
    exts = {photo_ext, Path(item.live_video).suffix, ".MP4"}
    n, cand = 2, stem
    while not all(_saved_before(Path(folder) / (cand + e), item.when) for e in exts):
        cand, n = f"{stem} ({n})", n + 1
    return cand


def save_item(source, item, folder: Path, compatible: bool, tmp: Path) -> list[Path]:
    """Save one photo or video (and a Live Photo's short video) into folder. Returns the files written."""
    out = []
    lat, lon = getattr(item, "lat", None), getattr(item, "lon", None)
    live = getattr(item, "live_video", None)
    if compatible and item.video and videoconv.available():
        saved = _save_video(source, item.id, item.name, folder, item.when, lat, lon, tmp, getattr(item, "size", 0))
        out += [saved] if saved else []
    elif live:
        name = jpg_name(item.name) if compatible and not item.video else item.name
        stem = _live_stem(folder, item, Path(name).suffix)
        out += _save_still(source, item, folder, compatible, tmp, stem + Path(name).suffix)
        mov = stem + Path(live).suffix                              # a Live Photo: its short video, same name
        if compatible and videoconv.available():
            saved = _save_video(source, live, mov, folder, item.when, lat, lon, tmp, 0, keep_name=True)
            out += [saved] if saved else []
        elif source.copy(live, folder / mov):
            set_file_date(folder / mov, item.when)
            out.append(folder / mov)
    else:
        out += _save_still(source, item, folder, compatible, tmp)
    return out


def _save_video(source, src_id, name: str, folder: Path, when, lat, lon, tmp: Path, size: int = 0,
                keep_name: bool = False) -> Optional[Path]:
    """P8: an HEVC video becomes an H.264 MP4 (date and location kept); any other video, or one that can't be
    converted, is saved as it is. Works in tmp; the folder only gets the finished file."""
    raw, conv = Path(tmp) / f"src-{name}", Path(tmp) / f"conv-{Path(name).stem}.mp4"
    try:
        if not source.copy(src_id, raw):
            return None
        if videoconv.is_hevc(raw) and videoconv.to_h264(raw, conv, when, lat, lon):
            final = videoconv.mp4_name(name)
            final = final if keep_name else free_name(folder, final, 0, when)
            done = conv
        else:
            final = name if keep_name else free_name(folder, name, size, when)
            done = raw
        Path(folder).mkdir(parents=True, exist_ok=True)
        dest = Path(folder) / final
        part = dest.with_name(dest.name + ".part")                  # another drive: a copy that can stop half-way
        try:
            shutil.move(str(done), part)
            os.replace(part, dest)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
        set_file_date(dest, when)
        return dest
    finally:
        for f in (raw, conv):
            try:
                f.unlink()
            except OSError:
                pass


def _save_still(source, item, folder: Path, compatible: bool, tmp: Path, name: Optional[str] = None) -> list[Path]:
    """A photo (HEIC → JPG when compatible), or a video saved as it is. name: already chosen (a Live Photo)."""
    out = []
    if name is None:
        name = jpg_name(item.name) if compatible and not item.video else item.name
        name = free_name(folder, name, getattr(item, "size", 0), item.when)
    dest = folder / name
    if compatible and not item.video and Path(item.name).suffix.lower() in CONVERT:
        raw = tmp / item.name
        if source.copy(item.id, raw) and to_jpg(raw, dest, item.when, getattr(item, "lat", None), getattr(item, "lon", None)):
            out.append(dest)
        elif source.copy(item.id, folder / item.name):              # couldn't convert: keep the original
            out.append(folder / item.name)
        try:
            raw.unlink()                                            # the temp folder holds one item at a time
        except OSError:
            pass
    elif source.copy(item.id, dest):
        set_file_date(dest, item.when)
        out.append(dest)
    return out
