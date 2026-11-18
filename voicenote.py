"""Q2: a voice note's length and waveform, from the file alone and without decoding any sound.

A voice note is compressed with a variable bit rate (Opus, AAC): each packet of sound takes more bytes when there's
more going on (speech) and few when it's quiet. So the packet sizes, which every container lists, draw the shape of
the recording. Read here from the three containers phones use:
- CAF (Messages' "Audio Message.caf", Opus or AAC): the 'desc' and 'pakt' chunks;
- Ogg (WhatsApp's .opus): the pages' segment tables and the last page's granule position;
- MP4 / M4A (AAC): the sound track's 'mdhd' and 'stsz' boxes.
Everything is bounded (file size, packet count, box depth): a file from a backup is never trusted.
"""
from __future__ import annotations

import struct
from typing import Optional

MAX_BYTES = 64 * 1024 * 1024        # a voice note bigger than this isn't drawn (an hour of Opus is ~10 MB)
MAX_PACKETS = 2_000_000
BARS = 36


def shape(data: bytes, bars: int = BARS) -> Optional[tuple[float, list[float]]]:
    """(seconds, `bars` heights from 0.15 to 1) or None when the file isn't one of these or doesn't make sense."""
    if not data or len(data) > MAX_BYTES:
        return None
    try:
        if data[:4] == b"caff":
            got = _caf(data)
        elif data[:4] == b"OggS":
            got = _ogg(data)
        elif data[4:8] == b"ftyp":
            got = _mp4(data)
        else:
            return None
    except (struct.error, IndexError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if not got:
        return None
    seconds, sizes = got
    if not sizes or not (0 < seconds < 24 * 3600):
        return None
    return seconds, heights(sizes, bars)


def heights(sizes: list[int], bars: int = BARS) -> list[float]:
    """The packet sizes in `bars` groups, each group's average from the quiet level (10th percentile) to the loud
    one (95th), as 0.15 (silence still shows a little bar, as on the phone) to 1."""
    bars = max(1, min(bars, len(sizes)))
    groups = []
    for b in range(bars):
        part = sizes[b * len(sizes) // bars:(b + 1) * len(sizes) // bars] or [0]
        groups.append(sum(part) / len(part))
    ranked = sorted(sizes)
    low = ranked[len(ranked) // 10]
    high = ranked[min(len(ranked) - 1, len(ranked) * 95 // 100)]
    span = high - low
    if span <= 0:
        return [0.5] * bars
    return [round(0.15 + 0.85 * max(0.0, min(1.0, (g - low) / span)), 3) for g in groups]


def fmt(seconds: float) -> str:
    """0:07, 1:05, 1:02:03 as the phone writes a voice note's length."""
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# -- CAF --------------------------------------------------------------------------------------------------------
def _caf(data: bytes) -> Optional[tuple[float, list[int]]]:
    pos, rate, per_packet_bytes, per_packet_frames, pakt = 8, 0.0, 0, 0, None
    while pos + 12 <= len(data):
        kind, size = data[pos:pos + 4], struct.unpack(">q", data[pos + 4:pos + 12])[0]
        body = pos + 12
        if kind == b"desc":
            rate, _fmt, _flags, per_packet_bytes, per_packet_frames = struct.unpack(">d4sIII", data[body:body + 24])
        elif kind == b"pakt":
            pakt = (body, min(len(data), body + size) if size >= 0 else len(data))
        if size < 0:                    # -1: the data chunk runs to the end of the file
            break
        pos = body + size
    if pakt is None or not rate:
        return None
    start, end = pakt
    packets, valid_frames = struct.unpack(">qq", data[start:start + 16])
    if not (0 < packets <= MAX_PACKETS):
        return None
    pos, sizes, frames = start + 24, [], 0
    for _ in range(packets):
        if per_packet_bytes:
            n = per_packet_bytes
        else:
            n, pos = _ber(data, pos, end)
        if not per_packet_frames:
            f, pos = _ber(data, pos, end)
            frames += f
        sizes.append(n)
    total = valid_frames if valid_frames > 0 else (frames or packets * per_packet_frames)
    return total / rate, sizes


def _ber(data: bytes, pos: int, end: int) -> tuple[int, int]:
    """CAF's variable-length number: 7 bits a byte, the high bit set on every byte but the last (at most 5)."""
    v = 0
    for _ in range(5):
        if pos >= end:
            raise ValueError("packet table ends early")
        b = data[pos]
        pos += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, pos
    raise ValueError("packet size too long")


# -- Ogg Opus ---------------------------------------------------------------------------------------------------
def _ogg(data: bytes) -> Optional[tuple[float, list[int]]]:
    pos, sizes, current, granule, packets_seen, pre_skip = 0, [], 0, 0, 0, 0
    while pos + 27 <= len(data) and data[pos:pos + 4] == b"OggS":
        g = struct.unpack("<q", data[pos + 6:pos + 14])[0]
        nseg = data[pos + 26]
        table = data[pos + 27:pos + 27 + nseg]
        body = pos + 27 + nseg
        if len(table) < nseg or body + sum(table) > len(data):
            break                                # a page cut short: what's before it is all there is
        if g > 0:
            granule = g
        for lace in table:
            current += lace
            if lace < 255:                       # a packet ends here
                if packets_seen == 0 and data[body:body + 8] == b"OpusHead":
                    pre_skip = struct.unpack("<H", data[body + 10:body + 12])[0]
                elif packets_seen >= 2:          # OpusHead and OpusTags aren't sound
                    sizes.append(current)
                    if len(sizes) > MAX_PACKETS:
                        return None
                packets_seen += 1
                body += current
                current = 0
        pos = pos + 27 + nseg + sum(table)
    if not sizes or granule <= pre_skip:
        return None
    return (granule - pre_skip) / 48000.0, sizes


# -- MP4 / M4A --------------------------------------------------------------------------------------------------
def _mp4(data: bytes) -> Optional[tuple[float, list[int]]]:
    moov = _child(data, 0, len(data), b"moov")
    if moov is None:
        return None
    for trak in _children(data, *moov, b"trak"):
        mdia = _child(data, *trak, b"mdia")
        if mdia is None:
            continue
        hdlr = _child(data, *mdia, b"hdlr")
        if hdlr is None or data[hdlr[0] + 8:hdlr[0] + 12] != b"soun":
            continue
        mdhd = _child(data, *mdia, b"mdhd")
        stbl = None
        minf = _child(data, *mdia, b"minf")
        if minf is not None:
            stbl = _child(data, *minf, b"stbl")
        stsz = _child(data, *stbl, b"stsz") if stbl is not None else None
        if mdhd is None or stsz is None:
            return None
        v = data[mdhd[0]]
        if v == 1:
            scale, length = struct.unpack(">IQ", data[mdhd[0] + 20:mdhd[0] + 32])
        else:
            scale, length = struct.unpack(">II", data[mdhd[0] + 12:mdhd[0] + 20])
        fixed, count = struct.unpack(">II", data[stsz[0] + 4:stsz[0] + 12])
        if not (0 < count <= MAX_PACKETS) or not scale:
            return None
        if fixed:
            sizes = [fixed] * count
        else:
            if stsz[0] + 12 + 4 * count > stsz[1]:
                return None
            sizes = list(struct.unpack(f">{count}I", data[stsz[0] + 12:stsz[0] + 12 + 4 * count]))
        return length / scale, sizes
    return None


def _children(data: bytes, start: int, end: int, kind: bytes):
    """(body start, body end) of each `kind` box directly inside [start, end)."""
    pos, n = start, 0
    while pos + 8 <= end and n < 10_000:
        n += 1
        size, k = struct.unpack(">I4s", data[pos:pos + 8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", data[pos + 8:pos + 16])[0], 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        if k == kind:
            yield pos + head, pos + size
        pos += size


def _child(data: bytes, start: int, end: int, kind: bytes):
    return next(_children(data, start, end, kind), None)
