"""P1: save photos as the original or as "Most compatible" JPG (docs/spec/07-photos-media.md#p1-photos).

"Most compatible" turns HEIC/HEIF into JPG and keeps what makes a photo findable: the date taken and the location
(the original EXIF is carried over; when it lacks them, they're filled from the Photos library), and the file's date
is set to the date taken. Other photos (JPG, PNG…) and videos are saved as they are (video conversion is P8).
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path
from typing import Optional

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


def save_item(source, item, folder: Path, compatible: bool, tmp: Path) -> list[Path]:
    """Save one photo or video (and a Live Photo's short video) into folder. Returns the files written."""
    out = []
    name = jpg_name(item.name) if compatible and not item.video else item.name
    dest = folder / name
    if compatible and not item.video and Path(item.name).suffix.lower() in CONVERT:
        raw = tmp / item.name
        if source.copy(item.id, raw) and to_jpg(raw, dest, item.when, getattr(item, "lat", None), getattr(item, "lon", None)):
            out.append(dest)
        elif source.copy(item.id, folder / item.name):              # couldn't convert: keep the original
            out.append(folder / item.name)
    elif source.copy(item.id, dest):
        set_file_date(dest, item.when)
        out.append(dest)
    if getattr(item, "live_video", None):                           # a Live Photo: the photo and its short video
        mov = folder / (Path(name).stem + Path(item.live_video).suffix)
        if source.copy(item.live_video, mov):
            set_file_date(mov, item.when)
            out.append(mov)
    return out
