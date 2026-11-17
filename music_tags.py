"""
PhoneKeep - songs saved from the iPhone keep their title, artist, album and artwork (P2).

The Music app keeps a song's details in its library (MediaLibrary.sqlitedb), not always in the file, and stores the
file under a code name (iTunes_Control/Music/F12/ABCD.m4a). A saved song is put in an Artist/Album folder and
the library's details and artwork are written into the file's own tags, so Music, Windows Media Player, VLC and
others show them. Uses mutagen (GPL-2.0-or-later; pure Python, no network).

Safety: tags are written into a copy; if that fails, the song is saved untouched, never half-written. Songs
protected by Apple (FairPlay, e.g. .m4p) are saved as they are: they only play on the owner's authorised devices.
"""
from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import Optional

import sections as sx

UNKNOWN_ARTIST, UNKNOWN_ALBUM = "Unknown Artist", "Unknown Album"


def save_path(t) -> str:
    """Where a song goes inside the chosen folder: Artist/Album/NN Title.ext (as iTunes and Music lay them out)."""
    artist = sx.safe_name(t.album_artist or t.artist or UNKNOWN_ARTIST, 80)
    album = sx.safe_name(t.album or UNKNOWN_ALBUM, 80)
    title = t.title or Path(t.path).stem
    if t.track_no:
        title = (f"{t.disc_no}-" if t.disc_count > 1 and t.disc_no else "") + f"{t.track_no:02d} {title}"
    return f"{artist}/{album}/{sx.safe_name(title, 120)}{Path(t.path).suffix.lower()}"


def _cover(art: Optional[bytes]) -> Optional[tuple[bytes, str]]:
    """(image bytes, "jpeg" or "png") a tag can hold; other formats (HEIC...) become JPEG."""
    if not art:
        return None
    if art[:3] == b"\xff\xd8\xff":
        return art, "jpeg"
    if art[:8] == b"\x89PNG\r\n\x1a\n":
        return art, "png"
    try:
        from PIL import Image
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        with Image.open(io.BytesIO(art)) as im:
            b = io.BytesIO()
            im.convert("RGB").save(b, "JPEG", quality=92)
            return b.getvalue(), "jpeg"
    except Exception:
        return None


def _mp4(f, t, cover):
    from mutagen.mp4 import MP4Cover
    tags = f.tags
    for key, v in (("\xa9nam", t.title), ("\xa9ART", t.artist), ("\xa9alb", t.album), ("aART", t.album_artist),
                   ("\xa9gen", t.genre), ("\xa9day", str(t.year) if t.year else "")):
        if v:
            tags[key] = [v]
    if t.track_no:
        tags["trkn"] = [(t.track_no, t.track_count or 0)]
    if t.disc_no:
        tags["disk"] = [(t.disc_no, t.disc_count or 0)]
    if cover:
        tags["covr"] = [MP4Cover(cover[0], MP4Cover.FORMAT_JPEG if cover[1] == "jpeg" else MP4Cover.FORMAT_PNG)]


def _id3(tags, t, cover):
    from mutagen import id3
    for frame, v in ((id3.TIT2, t.title), (id3.TPE1, t.artist), (id3.TALB, t.album), (id3.TPE2, t.album_artist),
                     (id3.TCON, t.genre), (id3.TDRC, str(t.year) if t.year else "")):
        if v:
            tags.setall(frame.__name__, [frame(encoding=3, text=[v])])
    if t.track_no:
        tags.setall("TRCK", [id3.TRCK(encoding=3, text=[f"{t.track_no}/{t.track_count}" if t.track_count
                                                        else str(t.track_no)])])
    if t.disc_no:
        tags.setall("TPOS", [id3.TPOS(encoding=3, text=[f"{t.disc_no}/{t.disc_count}" if t.disc_count
                                                        else str(t.disc_no)])])
    if cover:
        tags.setall("APIC", [id3.APIC(encoding=3, mime=f"image/{cover[1]}", type=3, desc="Cover", data=cover[0])])


def _flac(f, t, cover):
    from mutagen.flac import Picture
    for key, v in (("title", t.title), ("artist", t.artist), ("album", t.album), ("albumartist", t.album_artist),
                   ("genre", t.genre), ("date", str(t.year) if t.year else ""),
                   ("tracknumber", str(t.track_no) if t.track_no else ""),
                   ("discnumber", str(t.disc_no) if t.disc_no else "")):
        if v:
            f[key] = [v]
    if cover:
        p = Picture()
        p.type, p.mime, p.desc, p.data = 3, f"image/{cover[1]}", "Cover", cover[0]
        f.clear_pictures()
        f.add_picture(p)


def write_tags(path: Path, t, art: Optional[bytes] = None) -> bool:
    """Write the library's details (and artwork, if there is one) into the file. True if the file was tagged."""
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    f = mutagen.File(str(path))
    if f is None:
        return False
    cover = _cover(art)
    if f.tags is None:
        f.add_tags()
    if isinstance(f, MP4):
        _mp4(f, t, cover)
    elif isinstance(f, FLAC):
        _flac(f, t, cover)
    elif isinstance(f, MP3) or hasattr(f.tags, "setall"):      # MP3, and AIFF / WAVE, which carry ID3 tags
        _id3(f.tags, t, cover)
    else:
        return False
    f.save()
    return True


def finish(part: Path, dest: Path, t, art: Optional[bytes] = None) -> bool:
    """`part` holds the song as copied from the iPhone. Put it at `dest` with its tags; True if tags were written.
    The tags go into a copy first, so a file mutagen can't handle is saved exactly as it came off the phone."""
    if getattr(t, "protected", False):
        os.replace(part, dest)
        return False
    work = part.with_name(part.name + ".tagging")
    try:
        shutil.copyfile(part, work)
        if write_tags(work, t, art):
            os.replace(work, dest)
            part.unlink(missing_ok=True)
            return True
    except Exception:
        pass
    work.unlink(missing_ok=True)
    os.replace(part, dest)
    return False
