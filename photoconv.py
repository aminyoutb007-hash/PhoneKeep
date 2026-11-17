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


def save_item(source, item, folder: Path, compatible: bool, tmp: Path) -> list[Path]:
    """Save one photo or video (and a Live Photo's short video) into folder. Returns the files written."""
    out = []
    lat, lon = getattr(item, "lat", None), getattr(item, "lon", None)
    if compatible and item.video and videoconv.available():
        saved = _save_video(source, item.id, item.name, folder, item.when, lat, lon, tmp, getattr(item, "size", 0))
        out += [saved] if saved else []
    else:
        out += _save_still(source, item, folder, compatible, tmp)
    if getattr(item, "live_video", None):                           # a Live Photo: the photo and its short video
        stem = Path(out[0].name).stem if out else Path(item.name).stem
        mov = stem + Path(item.live_video).suffix
        if compatible and videoconv.available():
            saved = _save_video(source, item.live_video, mov, folder, item.when, lat, lon, tmp, 0, keep_name=True)
            out += [saved] if saved else []
        elif source.copy(item.live_video, folder / mov):
            set_file_date(folder / mov, item.when)
            out.append(folder / mov)
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
        shutil.move(str(done), dest)
        set_file_date(dest, when)
        return dest
    finally:
        for f in (raw, conv):
            try:
                f.unlink()
            except OSError:
                pass


def _save_still(source, item, folder: Path, compatible: bool, tmp: Path) -> list[Path]:
    """A photo (HEIC → JPG when compatible), or a video saved as it is."""
    out = []
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
