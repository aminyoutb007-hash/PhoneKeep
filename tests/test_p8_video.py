"""P8: "Most compatible" turns HEVC videos into H.264 MP4 (docs/spec/07-photos-media.md#p8-video-conversion).

Done when: "a converted video plays in Windows Media Player and QuickTime with the original date."
The two clips in tests/fixtures/video are one second of a generated test pattern and a tone (no camera, no
person): hevc.mov (HEVC, its index after the picture data) and h264.mov (H.264, index first).

Everywhere: the video format is read from the file, and the date taken and location are written into an MP4 the
way Windows (the movie's "created" time) and Apple (its QuickTime keys and ©xyz) read them, with the picture data
still where the index says. On a Mac (avconvert): an HEVC video saved "Most compatible" comes out as an H.264 MP4
dated and located like the original, the file's date is the date taken, a Live Photo's video too; an H.264 video,
"Original", or a conversion that fails saves the original; nothing is left in the temp folder. Without avconvert
(Windows, Linux) videos are saved as they are.
"""
import datetime as dt, os, shutil, struct, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
import faulthandler
faulthandler.dump_traceback_later(240, exit=True)

import photoconv
import photos as ph
import videoconv

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


FIX = HERE / "fixtures" / "video"
W = HERE / "work" / "p8"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
TAKEN = dt.datetime(2023, 6, 14, 10, 30, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))   # 09:30 UTC
LAT, LON = 48.8584, 2.2945
SECS = int((TAKEN - videoconv.EPOCH_1904).total_seconds())


def moov_info(path: Path) -> dict:
    """What a player reads: header times, ©xyz, Apple's keys, the chunk offsets, and the video format."""
    off, moov = videoconv._moov(path)
    info = {"times": [], "xyz": None, "keys": {}, "offsets": [], "codec": videoconv.video_codec(path)}
    stack = [(8, len(moov))]
    keys = []
    while stack:
        a, b = stack.pop()
        for k, s, h, e in videoconv._atoms(moov, a, b):
            if k in videoconv.CONTAINERS or k == b"meta":
                stack.append((s + h, e))
            elif k in (b"mvhd", b"tkhd", b"mdhd"):
                v = moov[s + h]
                info["times"] += list(struct.unpack(">QQ" if v == 1 else ">II", moov[s + h + 4:s + h + (20 if v == 1 else 12)]))
            elif k == b"\xa9xyz":
                n = struct.unpack(">H", moov[s + h:s + h + 2])[0]
                info["xyz"] = moov[s + h + 4:s + h + 4 + n].decode()
            elif k == b"keys":
                p = s + h + 8
                while p < e:
                    n = struct.unpack(">I", moov[p:p + 4])[0]
                    keys.append(moov[p + 8:p + n].decode())
                    p += n
            elif k == b"ilst":
                for k2, s2, h2, e2 in videoconv._atoms(moov, s + h, e):
                    idx = struct.unpack(">I", k2)[0]
                    info["keys"][idx] = moov[s2 + h2 + 16:e2].decode()
            elif k in (b"stco", b"co64"):
                n = struct.unpack(">I", moov[s + h + 4:s + h + 8])[0]
                w = 4 if k == b"stco" else 8
                info["offsets"] += [struct.unpack(">I" if w == 4 else ">Q", moov[p:p + w])[0]
                                    for p in range(s + h + 8, s + h + 8 + n * w, w)]
    info["keys"] = {keys[i - 1]: v for i, v in info["keys"].items() if 0 < i <= len(keys)}
    info["moov_at"] = off
    return info


def chunks(path: Path, offsets: list) -> list:
    with open(path, "rb") as f:
        out = []
        for o in offsets:
            f.seek(o)
            out.append(f.read(32))
        return out


# -- reading the format -------------------------------------------------------------------------------------------
check(videoconv.video_codec(FIX / "hevc.mov") == "hvc1" and videoconv.is_hevc(FIX / "hevc.mov"),
      "an HEVC video is recognised as HEVC")
check(videoconv.video_codec(FIX / "h264.mov") == "avc1" and not videoconv.is_hevc(FIX / "h264.mov"),
      "an H.264 video is not")
junk = W / "junk.MOV"
junk.write_bytes(b"\0\0\0\x14ftypqt  fake movie")
cut = W / "cut.MOV"
cut.write_bytes((FIX / "hevc.mov").read_bytes()[:-300])                 # the index cut off at the end
check(videoconv.video_codec(junk) is None and videoconv.video_codec(cut) is None
      and videoconv.video_codec(W / "missing.MOV") is None,
      "a file that isn't a readable video (or is cut short, or missing) has no format, without an error")

# -- writing the date and the location (any computer) -------------------------------------------------------------
for name, where in (("h264.mov", "index before the picture data"), ("hevc.mov", "index after the picture data")):
    f = W / f"stamp-{name}"
    shutil.copy(FIX / name, f)
    before = moov_info(f)
    data = chunks(f, before["offsets"])
    ok = videoconv.stamp(f, TAKEN, LAT, LON)
    after, size = moov_info(f), f.stat().st_size
    check(ok and after["times"] and all(t == SECS for t in after["times"]),
          f"{where}: every created/modified time in the file is the date taken ({len(after['times'])} times)")
    check(after["xyz"] == "+48.8584+002.2945/" and after["keys"] == {
        "com.apple.quicktime.creationdate": "2023-06-14T10:30:00+0100",
        "com.apple.quicktime.location.ISO6709": "+48.8584+002.2945/"},
        f"{where}: the location (©xyz) and Apple's date and location keys are written: {after['xyz']} {after['keys']}")
    check(chunks(f, after["offsets"]) == data and after["codec"] == before["codec"],
          f"{where}: the picture and sound are still exactly where the index points ({len(data)} chunks)")
    videoconv.stamp(f, TAKEN, LAT, LON)
    again = moov_info(f)
    check(again["xyz"] == after["xyz"] and again["keys"] == after["keys"] and f.stat().st_size == size
          and chunks(f, again["offsets"]) == data,
          f"{where}: writing it twice changes nothing more (no second location, no second set of keys)")
    check(not list(W.glob("*.part")), f"{where}: no half-written file is left")
nodate = W / "nodate.mov"
shutil.copy(FIX / "h264.mov", nodate)
check(videoconv.stamp(nodate, None, None, None) and nodate.read_bytes() == (FIX / "h264.mov").read_bytes(),
      "no date and no location: the file is left as it is")
check(not videoconv.stamp(junk, TAKEN, LAT, LON), "a file that isn't a video isn't changed (and says so)")


def meta_with(handler: bytes, pairs) -> bytes:
    """A QuickTime 'meta' as an iPhone writes it under moov: hdlr, keys, ilst."""
    A = videoconv._atom
    keys = A(b"keys", struct.pack(">II", 0, len(pairs))
             + b"".join(struct.pack(">I4s", 8 + len(k), b"mdta") + k.encode() for k, _v in pairs))
    ilst = A(b"ilst", b"".join(A(struct.pack(">I", n), A(b"data", struct.pack(">II", 1, 0) + v.encode()))
                               for n, (_k, v) in enumerate(pairs, 1)))
    return A(b"meta", A(b"hdlr", b"\0" * 8 + handler + b"\0" * 13) + keys + ilst)


def meta_pairs(meta: bytes) -> list:
    names, vals = [], {}
    for k, s, h, e in videoconv._atoms(meta, 8):
        if k == b"keys":
            p = s + h + 8
            while p < e:
                n = struct.unpack(">I", meta[p:p + 4])[0]
                names.append(meta[p + 8:p + n].decode())
                p += n
        elif k == b"ilst":
            for k2, s2, h2, e2 in videoconv._atoms(meta, s + h, e):
                vals[struct.unpack(">I", k2)[0]] = meta[s2 + h2 + 16:e2].decode()
    return [(names[i - 1], vals[i]) for i in sorted(vals)]


had = meta_with(b"mdta", [("com.apple.quicktime.make", "Apple"),
                          ("com.apple.quicktime.creationdate", "2020-01-01T00:00:00+0000")])
merged = videoconv._apple_keys(had, TAKEN, LAT, LON)
check(merged is not None and meta_pairs(merged) == [
    ("com.apple.quicktime.make", "Apple"),
    ("com.apple.quicktime.creationdate", "2023-06-14T10:30:00+0100"),
    ("com.apple.quicktime.location.ISO6709", "+48.8584+002.2945/")],
    f"Apple's keys already in the file: the others are kept, the date replaced, the location added "
    f"({meta_pairs(merged) if merged else None})")
check(videoconv._apple_keys(meta_with(b"mdir", [("x", "y")]), TAKEN, LAT, LON) is None,
      "a 'meta' that isn't Apple's keys is left alone")


# -- saving ---------------------------------------------------------------------------------------------------------
class FileSrc:
    def __init__(self, files):
        self.files = files

    def copy(self, item_id, dest):
        if item_id not in self.files:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.files[item_id], dest)
        return True


from PIL import Image
import pillow_heif
pillow_heif.register_heif_opener()
heic = W / "src" / "IMG_0300.HEIC"
heic.parent.mkdir(parents=True)
Image.new("RGB", (80, 60), (30, 120, 200)).save(heic)
src = FileSrc({"DCIM/IMG_0200.MOV": FIX / "hevc.mov", "DCIM/IMG_0201.MOV": FIX / "h264.mov",
               "DCIM/IMG_0300.HEIC": heic, "DCIM/IMG_0300.MOV": FIX / "hevc.mov"})
naive = TAKEN.astimezone().replace(tzinfo=None)                  # the library's dates are the computer's local time
v_hevc = ph.PhotoItem("DCIM/IMG_0200.MOV", "IMG_0200.MOV", 1, naive, True, lat=LAT, lon=LON)
v_h264 = ph.PhotoItem("DCIM/IMG_0201.MOV", "IMG_0201.MOV", 1, naive, True)
live = ph.PhotoItem("DCIM/IMG_0300.HEIC", "IMG_0300.HEIC", 1, naive, False, live_video="DCIM/IMG_0300.MOV",
                    lat=LAT, lon=LON)


def save(item, compatible, folder):
    tmp = W / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    out = photoconv.save_item(src, item, W / folder, compatible, tmp)
    return out, list(tmp.iterdir())


orig, left = save(v_hevc, False, "original")
check([p.name for p in orig] == ["IMG_0200.MOV"] and (W / "original/IMG_0200.MOV").read_bytes()
      == (FIX / "hevc.mov").read_bytes(), "Original: the HEVC video is saved exactly as it is")

if videoconv.available():
    out, left = save(v_hevc, True, "compatible")
    mp4 = W / "compatible" / "IMG_0200.MP4"
    info = moov_info(mp4) if mp4.exists() else {}
    check([p.name for p in out] == ["IMG_0200.MP4"] and info.get("codec") == "avc1",
          f"Most compatible: the HEVC video is saved as an H.264 MP4 ({[p.name for p in out]}, {info.get('codec')})")
    check(info.get("times") and all(t == SECS for t in info["times"])
          and info["keys"].get("com.apple.quicktime.creationdate") == "2023-06-14T10:30:00+0100",
          "  with the date taken inside (what QuickTime, Finder and Windows Media Player show as created)")
    check(info.get("xyz") == "+48.8584+002.2945/"
          and info["keys"].get("com.apple.quicktime.location.ISO6709") == "+48.8584+002.2945/",
          "  and the location")
    check(abs(mp4.stat().st_mtime - TAKEN.timestamp()) < 2
          and (not hasattr(mp4.stat(), "st_birthtime") or abs(mp4.stat().st_birthtime - TAKEN.timestamp()) < 2),
          "  and the file's own dates (modified, and created on a Mac) are the date taken")
    check(not left, f"  nothing is left in the temp folder ({[p.name for p in left]})")
    check(not (W / "compatible" / "IMG_0200.MOV").exists(), "  and the HEVC original isn't saved next to it")
    import subprocess
    r = subprocess.run(["/usr/bin/avconvert", "-s", str(mp4), "-o", str(W / "replay.mov"), "-p", "PresetPassthrough",
                        "--replace"], capture_output=True)
    check(r.returncode == 0 and (W / "replay.mov").stat().st_size > 0,
          "  and macOS's own video framework reads the whole MP4 again (it plays)")
    again, _ = save(v_hevc, True, "compatible")
    check([p.name for p in again] == ["IMG_0200.MP4"] and sorted(p.name for p in (W / "compatible").iterdir())
          == ["IMG_0200.MP4"], "saving again doesn't make a second copy")

    out, left = save(v_h264, True, "compatible")
    check([p.name for p in out] == ["IMG_0201.MOV"] and (W / "compatible/IMG_0201.MOV").read_bytes()
          == (FIX / "h264.mov").read_bytes() and not left,
          "a video that is already H.264 is saved as it is (it plays everywhere already)")

    out, left = save(live, True, "live")
    names = sorted(p.name for p in out)
    check(names == ["IMG_0300.JPG", "IMG_0300.MP4"] and moov_info(W / "live/IMG_0300.MP4")["codec"] == "avc1"
          and not left, f"a Live Photo: a JPG and an H.264 MP4 with the same name ({names})")

    real = videoconv.AVCONVERT
    videoconv.AVCONVERT = "/usr/bin/false"          # the conversion fails (exists, runs, answers "no")
    try:
        out, left = save(v_hevc, True, "failed")
    finally:
        videoconv.AVCONVERT = real
    check([p.name for p in out] == ["IMG_0200.MOV"] and (W / "failed/IMG_0200.MOV").read_bytes()
          == (FIX / "hevc.mov").read_bytes() and not left
          and abs((W / "failed/IMG_0200.MOV").stat().st_mtime - TAKEN.timestamp()) < 2,
          "a conversion that fails saves the original (dated), and leaves nothing behind")
else:
    print("     (no avconvert on this computer: the conversion checks run on a Mac)")

real_available = videoconv.available
videoconv.available = lambda: False                 # Windows and Linux
try:
    out, left = save(v_hevc, True, "windows")
    live_out, _ = save(live, True, "windows-live")
finally:
    videoconv.available = real_available
check([p.name for p in out] == ["IMG_0200.MOV"] and (W / "windows/IMG_0200.MOV").read_bytes()
      == (FIX / "hevc.mov").read_bytes()
      and sorted(p.name for p in live_out) == ["IMG_0300.JPG", "IMG_0300.MOV"],
      "without a converter (Windows), Most compatible saves videos as they are, a Live Photo's too")

import ui
text = Path(ui.__file__).read_text(encoding="utf-8")
check("videoconv.available()" in text and "Videos are always saved as they are." in text,
      "the Save dialog says what happens to videos on this computer")

print("\nP8 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
