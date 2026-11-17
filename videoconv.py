"""P8: "Most compatible" also turns HEVC videos into H.264 MP4 (docs/spec/07-photos-media.md#p8-video-conversion).

On a Mac the conversion is done by `avconvert`, the command-line tool macOS ships in /usr/bin (Apple's own
AVFoundation encoder, run as a subprocess; no app is scripted and nothing is bundled). It keeps the size (no
upscaling, 4K stays 4K) but not the date taken or the location, so both are written back into the new file:
the movie, track and media headers get the date taken (what Finder, QuickTime and Windows show as "created" or
"Media created"), and the location goes into a ©xyz entry (ISO 6709, as the iPhone and Apple's Photos write it).
The file's own date is set to the date taken, as for photos.

On Windows and Linux there is no encoder PhoneKeep can count on (Windows needs a paid HEVC extension to even read
these videos; bundling ffmpeg is the owner's decision), so videos are saved as they are, as before.
Every step works on a copy in PhoneKeep's private temp folder; the saved folder only ever gets a finished file.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

AVCONVERT = "/usr/bin/avconvert"
PRESET = "Preset3840x2160"          # H.264; never upscales, so a 1080p (or portrait) video keeps its size
HEVC = {"hvc1", "hev1", "dvh1", "dvhe"}   # HEVC, and Dolby Vision HDR on HEVC (newer iPhones)
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"edts", b"dinf"}
EPOCH_1904 = dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)


def available() -> bool:
    """True when this computer can convert (a Mac with avconvert)."""
    return sys.platform == "darwin" and os.access(AVCONVERT, os.X_OK)


def mp4_name(name: str) -> str:
    """'IMG_0001.MOV' → 'IMG_0001.MP4'."""
    return Path(name).stem + ".MP4"


# -- reading the atoms -------------------------------------------------------------------------------------------
def _atoms(buf: bytes, start: int = 0, end: Optional[int] = None):
    """(type, start, header length, end) for each atom in buf[start:end]."""
    end = len(buf) if end is None else end
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack(">I4s", buf[i:i + 8])
        head = 8
        if size == 1:
            if i + 16 > end:
                return
            size, head = struct.unpack(">Q", buf[i + 8:i + 16])[0], 16
        elif size == 0:
            size = end - i
        if size < head or i + size > end:
            return
        yield kind, i, head, i + size
        i += size


def _top_level(path: Path):
    """(type, offset, size) of each top-level atom, reading only their headers."""
    out = []
    total = path.stat().st_size
    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= total:
            f.seek(pos)
            h = f.read(16)
            size, kind = struct.unpack(">I4s", h[:8])
            if size == 1:
                size = struct.unpack(">Q", h[8:16])[0]
            elif size == 0:
                size = total - pos
            if size < 8 or pos + size > total:
                break
            out.append((kind, pos, size))
            pos += size
    return out


def _moov(path: Path):
    """(offset, bytes) of the moov atom, or (None, None)."""
    for kind, off, size in _top_level(path):
        if kind == b"moov":
            with open(path, "rb") as f:
                f.seek(off)
                return off, f.read(size)
    return None, None


def video_codec(path: Path) -> Optional[str]:
    """The video track's sample format ('hvc1', 'avc1'…), or None when there is no readable video track."""
    try:
        _off, moov = _moov(Path(path))
    except OSError:
        return None
    if not moov:
        return None
    for kind, s, h, e in _atoms(moov, 8):
        if kind != b"trak":
            continue
        codec, video = None, False
        stack = [(s + h, e)]
        while stack:
            a, b = stack.pop()
            for k, s2, h2, e2 in _atoms(moov, a, b):
                if k in (b"mdia", b"minf", b"stbl"):
                    stack.append((s2 + h2, e2))
                elif k == b"hdlr" and moov[s2 + h2 + 8:s2 + h2 + 12] == b"vide":
                    video = True
                elif k == b"stsd" and e2 - s2 >= h2 + 16:
                    codec = moov[s2 + h2 + 12:s2 + h2 + 16].decode("latin-1")
        if video and codec:
            return codec
    return None


def is_hevc(path: Path) -> bool:
    return video_codec(path) in HEVC


# -- writing the date and the location back ---------------------------------------------------------------------
def _iso6709(lat: float, lon: float) -> str:
    return f"{lat:+08.4f}{lon:+09.4f}/"


def _rebuild(buf: bytes, start: int, end: int, secs: Optional[int], xyz: Optional[bytes], in_udta=False) -> bytes:
    """The atoms in buf[start:end] again, with the header times set to secs and ©xyz put in moov's udta."""
    out = b""
    seen_udta = False
    for kind, s, h, e in _atoms(buf, start, end):
        if kind in CONTAINERS:
            body = _rebuild(buf, s + h, e, secs, xyz if kind in (b"moov", b"udta") else None, kind == b"udta")
            if kind == b"udta":
                seen_udta = True
            atom = struct.pack(">I4s", 8 + len(body), kind) + body
        elif in_udta and kind == b"\xa9xyz" and xyz is not None:
            continue                                     # replaced by the one below
        else:
            atom = bytearray(buf[s:e])
            if secs is not None and kind in (b"mvhd", b"tkhd", b"mdhd"):
                if atom[h] == 1 and e - s >= h + 20:            # version 1: 64-bit created and modified
                    struct.pack_into(">QQ", atom, h + 4, secs, secs)
                elif atom[h] == 0 and e - s >= h + 12:          # version 0: 32-bit
                    struct.pack_into(">II", atom, h + 4, secs & 0xFFFFFFFF, secs & 0xFFFFFFFF)
            atom = bytes(atom)
        out += atom
    if xyz is not None and in_udta:
        out += xyz
    elif xyz is not None and not seen_udta and start == 8:  # moov without a udta: add one
        out += struct.pack(">I4s", 8 + len(xyz), b"udta") + xyz
    return out


def _shift_offsets(moov: bytearray, delta: int) -> None:
    """Move every chunk offset (stco / co64) by delta: the media data moved because moov before it grew."""
    stack = [(8, len(moov))]
    while stack:
        a, b = stack.pop()
        for k, s, h, e in _atoms(bytes(moov), a, b):
            if k in CONTAINERS:
                stack.append((s + h, e))
            elif k in (b"stco", b"co64"):
                n = struct.unpack(">I", moov[s + h + 4:s + h + 8])[0]
                p = s + h + 8
                for _ in range(n):
                    if k == b"stco":
                        struct.pack_into(">I", moov, p, struct.unpack(">I", moov[p:p + 4])[0] + delta)
                        p += 4
                    else:
                        struct.pack_into(">Q", moov, p, struct.unpack(">Q", moov[p:p + 8])[0] + delta)
                        p += 8


def _atom(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def _apple_keys(meta: Optional[bytes], when: Optional[dt.datetime], lat: Optional[float],
                lon: Optional[float]) -> Optional[bytes]:
    """moov's QuickTime 'meta' atom with Apple's own keys for the date taken and the location, as an iPhone writes
    them (what macOS and Apple's Photos read first). meta: the one already there (its other keys are kept, these
    two replaced), or None to make one. None back when there's nothing to write, or the one there isn't Apple's."""
    items = {}
    if when is not None and when.year > 1970:
        w = when if when.tzinfo else when.astimezone()
        items["com.apple.quicktime.creationdate"] = w.strftime("%Y-%m-%dT%H:%M:%S%z")
    if lat is not None and lon is not None and (lat, lon) != (0, 0):
        items["com.apple.quicktime.location.ISO6709"] = _iso6709(lat, lon)
    if not items:
        return None
    names, values, other = [], {}, b""
    hdlr = _atom(b"hdlr", b"\0" * 8 + b"mdta" + b"\0" * 12 + b"\0")
    if meta is not None:
        mdta = False
        for k, s, h, e in _atoms(meta, 8):
            if k == b"hdlr":
                mdta, hdlr = meta[s + h + 8:s + h + 12] == b"mdta", meta[s:e]
            elif k == b"keys":
                p = s + h + 8
                while p + 8 <= e:
                    n = struct.unpack(">I", meta[p:p + 4])[0]
                    if n < 8:
                        return None
                    names.append(meta[p + 8:p + n].decode("utf-8", "replace"))
                    p += n
            elif k == b"ilst":
                for k2, s2, _h2, e2 in _atoms(meta, s + h, e):
                    values[struct.unpack(">I", k2)[0]] = meta[s2:e2]
            else:
                other += meta[s:e]
        if not mdta:
            return None
    for key, value in items.items():
        if key not in names:
            names.append(key)
        n = names.index(key) + 1
        values[n] = _atom(struct.pack(">I", n), _atom(b"data", struct.pack(">II", 1, 0) + value.encode("utf-8")))
    keys = _atom(b"keys", struct.pack(">II", 0, len(names))
                 + b"".join(struct.pack(">I4s", 8 + len(k.encode()), b"mdta") + k.encode() for k in names))
    ilst = _atom(b"ilst", b"".join(values[n] for n in sorted(values)))
    return _atom(b"meta", hdlr + keys + ilst + other)


def stamp(path: Path, when: Optional[dt.datetime], lat: Optional[float] = None, lon: Optional[float] = None) -> bool:
    """Write the date taken and the location into an MP4/MOV in place. False when the file can't be read."""
    path = Path(path)
    secs = None
    if when is not None and when.year > 1970:
        w = when if when.tzinfo else when.astimezone()     # a naive date is the computer's local time
        secs = int((w - EPOCH_1904).total_seconds())
    xyz = None
    if lat is not None and lon is not None and (lat, lon) != (0, 0):
        text = _iso6709(lat, lon).encode("ascii")
        xyz = struct.pack(">I4sHH", 12 + len(text), b"\xa9xyz", len(text), 0x15C7) + text
    if secs is None and xyz is None:
        return True
    try:
        off, moov = _moov(path)
        if not moov:
            return False
        head = 16 if struct.unpack(">I", moov[:4])[0] == 1 else 8
        if head != 8:
            return False                                  # a moov over 4 GB: never written by avconvert
        body = _rebuild(moov, 8, len(moov), secs, xyz)
        metas = [(s, e) for k, s, _h, e in _atoms(body, 0) if k == b"meta"]
        if metas:                                             # Apple's keys already there: these two replaced
            s0, e0 = metas[0]
            merged = _apple_keys(body[s0:e0], when, lat, lon)
            if merged is not None:
                body = body[:s0] + merged + body[e0:]
        else:
            body += _apple_keys(None, when, lat, lon) or b""
        new = bytearray(struct.pack(">I4s", 0, b"moov") + body)
        struct.pack_into(">I", new, 0, len(new))
        delta = len(new) - len(moov)
        mdat_after = any(k == b"mdat" and o > off for k, o, _s in _top_level(path))
        if delta and mdat_after:
            _shift_offsets(new, delta)
        tmp = path.with_name(path.name + ".part")
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            dst.write(src.read(off))
            dst.write(new)
            src.seek(off + len(moov))
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(tmp, path)
        return True
    except (OSError, struct.error, ValueError, OverflowError):
        try:
            path.with_name(path.name + ".part").unlink()
        except OSError:
            pass
        return False


# -- converting --------------------------------------------------------------------------------------------------
def to_h264(src: Path, dest: Path, when: Optional[dt.datetime] = None, lat: Optional[float] = None,
            lon: Optional[float] = None) -> bool:
    """Convert an HEVC video to an H.264 MP4 at dest with its date and location. False (and no dest) when it
    can't be done here; the caller then saves the original."""
    dest = Path(dest)
    if not available():
        return False
    try:
        r = subprocess.run([AVCONVERT, "--source", str(src), "--output", str(dest), "--preset", PRESET,
                            "--replace"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        if r.returncode == 0 and dest.exists() and video_codec(dest) == "avc1" and stamp(dest, when, lat, lon):
            return True
    except OSError:
        pass
    try:
        dest.unlink()
    except OSError:
        pass
    return False
