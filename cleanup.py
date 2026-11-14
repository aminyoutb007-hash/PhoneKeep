"""C1: Photo clean-up, find and save (docs/spec/13-phone-health.md#c1-photo-clean-up-find-and-save).

Six cards of photos and videos the owner may want off the phone: Duplicates, Similar shots, Poor quality,
Old screenshots, Large videos and Chat clutter. Everything is worked out on this computer from the photos PhoneKeep
already reads (live from the iPhone or from a backup): nothing is sent anywhere.

- Exact duplicates by checksum. Only files that share a size can be copies, so only those are read in full.
- Similar shots by a visual fingerprint (a 64-bit difference hash of the small thumbnail) plus the time taken,
  and bursts as the Photos library records them.
- Quality by sharpness and exposure, measured on the small version iOS keeps of each photo: sharpness is how
  strong its strongest edges are (a blurred photo has none anywhere; a plain but sharp one still has crisp
  outlines), exposure its mean brightness, and a photo with almost no detail at all is what a pocket shot or a
  finger over the lens looks like. Blur too slight to see at that size isn't found: finding it would mean reading
  every full photo, too slow over the cable.
- Screenshots, screen recordings, bursts and the app that saved an image come from the Photos library where it
  records them; otherwise from file details (a PNG is a screenshot, RPReplay*.MP4 a screen recording, a JPEG with
  no camera in its details came from an app).

Favourites and photos in any album are never suggested for removal. Hidden photos are left out (they stay behind
the app lock), and so are photos whose full version is only in iCloud (they can't be saved from here).
The measurements are cached per phone next to its backups (cleanup-cache.json), so a second visit is instant.

Saving goes to the folder the owner picks (the archive). Each file is checked after it's written: its checksum
must match what was read from the phone. The record of what was saved and checked (cleanup.json) is what C2 will
remove from; until then the screen shows the steps to remove them on the iPhone.
Kept free of Tk: the window (cleanup_ui.py) draws what this works out.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:
    from PIL import Image, ImageFilter, ImageOps, ImageStat
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
except Exception:      # Pillow missing: only checksums, dates and sizes are used
    Image = None

# Every threshold in one place.
SIMILAR_SECONDS = 10                  # shots this close together (and alike) are one run
SIMILAR_BITS = 10                     # fingerprints differing in at most this many of 64 bits look alike
BLURRY_BELOW = 10                     # sharpness: the 99th percentile of edge strength (0-128) at MEASURE_PX
FLAT_BELOW = 4.0                      # spread of brightness: below this a photo has almost no detail
DARK_BELOW = 28                       # mean brightness (0-255)
BRIGHT_ABOVE = 238
SCREENSHOT_DAYS = 30                  # Old screenshots: older than this (adjustable on the screen)
LARGE_VIDEO = 100 * 1000 ** 2         # Large videos: from this size
MEASURE_PX = 256                      # photos are measured at this size, whatever size they come in
CHECKSUM_IN_MEMORY = 1024 ** 3        # bigger files are copied and checked by size only (not offered for removal)
APP_MAX_BYTES = 3 * 1000 ** 2         # without the library's app record, only small JPEGs are looked at
WORKERS = 4
CACHE_VERSION = 1

CHAT_APPS = {                         # bundle ids the library records as having saved an image
    "net.whatsapp.WhatsApp": "WhatsApp", "net.whatsapp.WhatsAppSMB": "WhatsApp Business",
    "ph.telegra.Telegraph": "Telegram", "org.whispersystems.signal": "Signal", "com.facebook.Messenger": "Messenger",
    "com.viber": "Viber", "jp.naver.line": "LINE", "com.tencent.xin": "WeChat", "com.apple.MobileSMS": "Messages",
    "com.skype.skype": "Skype", "com.hammerandchisel.discord": "Discord", "com.toyopagroup.picaboo": "Snapchat",
}

CARDS = (  # key, title, what it finds, what's suggested
    ("duplicates", "Duplicates", "Exact copies, including the same photo saved twice from a chat",
     "Keep one: the original with the most kept"),
    ("similar", "Similar shots", "Bursts and runs of near-identical photos taken seconds apart",
     "Keep the sharpest; tick which others go"),
    ("poor", "Poor quality", "Blurry, very dark or overexposed photos, and ones with almost no detail (a pocket shot, a finger over the lens)",
     "Review one by one"),
    ("screenshots", "Old screenshots", f"Screenshots and screen recordings older than {SCREENSHOT_DAYS} days",
     "Remove in bulk"),
    ("videos", "Large videos", "Biggest videos first, with size and length",
     "Save to the computer, then remove"),
    ("chat", "Chat clutter", "Images saved into the camera roll from WhatsApp and other chat apps",
     "Remove in bulk"),
)

STEPS = {   # how to remove them on the iPhone while PhoneKeep can't (C2)
    "duplicates": "On the iPhone: Photos → Utilities → Duplicates → Merge.",
    "screenshots": "On the iPhone: Photos → Media Types → Screenshots (and Screen Recordings), select them, then Delete.",
}
ICLOUD_WARNING = ("With iCloud Photos on, deleting a photo on the iPhone also deletes it from iCloud and from every "
                  "other device signed in to it. These are saved on this computer.")


# -- results ----------------------------------------------------------------------------------------------------
@dataclass
class Group:
    items: list                       # photos.PhotoItem, shown side by side
    keep: set = field(default_factory=set)       # suggested keepers (marked Keep)
    locked: set = field(default_factory=set)     # favourites and album photos: never offered
    ticked: set = field(default_factory=set)     # ticked to go, to begin with
    notes: dict = field(default_factory=dict)    # item id -> "blurry", "2 min 10 s"…

    def candidates(self) -> list:
        return [i for i in self.items if i.id not in self.keep and i.id not in self.locked]


@dataclass
class Card:
    key: str
    title: str
    finds: str
    suggested: str
    groups: list = field(default_factory=list)
    note: str = ""                    # what wasn't checked, if anything
    space_of: Callable = None

    def candidates(self) -> list:
        return [i for g in self.groups for i in g.candidates()]

    @property
    def count(self) -> int:
        return len(self.candidates())

    @property
    def space(self) -> int:
        return sum(self.space_of(i) for i in self.candidates())

    def ticked(self) -> set:
        return set().union(*(g.ticked for g in self.groups)) if self.groups else set()


@dataclass
class Result:
    cards: list
    items: dict                       # id -> PhotoItem (every item the cards show)
    left_out: dict                    # {"hidden": n, "icloud": n}
    seconds: float = 0.0
    measured: int = 0                 # items measured this time (0 on a second visit: all from the cache)
    icloud: Optional[bool] = None     # iCloud Photos on (True), off (False), not known (None)
    space_of: Callable = None

    def card(self, key: str) -> Card:
        return next(c for c in self.cards if c.key == key)

    def total(self, ids) -> tuple:
        """(count, bytes) of a set of item ids, each counted once."""
        ids = set(ids)
        return len(ids), sum(self.space_of(self.items[i]) for i in ids if i in self.items)


# -- measuring ---------------------------------------------------------------------------------------------------
def protected(i) -> bool:
    return bool(getattr(i, "favorite", False) or getattr(i, "albums", ()))


def key_of(i) -> str:
    try:
        t = int(i.when.timestamp())
    except (OverflowError, OSError, ValueError):
        t = 0
    return f"{i.id}|{i.size}|{t}"


def _edge_strength(g) -> int:
    """The 99th percentile of how strongly each pixel differs from its neighbours (0-128)."""
    edges = g.filter(ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128))
    edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))     # the filter leaves the border as it was
    h = [0] * 129
    for v, n in enumerate(edges.histogram()):
        h[abs(v - 128)] += n
    left = sum(h) * 0.01
    for v in range(128, -1, -1):
        left -= h[v]
        if left <= 0:
            return v
    return 0


def measure_image(path_or_bytes) -> Optional[dict]:
    """{"dh": fingerprint, "sharp": sharpness, "mean": brightness, "flat": spread} of a photo or its thumbnail."""
    if Image is None or path_or_bytes is None:
        return None
    try:
        src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
        with Image.open(src) as im:
            im.draft("L", (MEASURE_PX * 2, MEASURE_PX * 2))           # JPEG: decode small, much faster
            g = ImageOps.exif_transpose(im).convert("L")
        g.thumbnail((MEASURE_PX, MEASURE_PX))
        px = list(g.resize((9, 8), Image.BILINEAR).getdata())
        bits = 0
        for r in range(8):
            for c in range(8):
                bits = (bits << 1) | (px[r * 9 + c] > px[r * 9 + c + 1])
        st = ImageStat.Stat(g)
        return {"dh": bits, "sharp": _edge_strength(g), "mean": round(st.mean[0], 1),
                "flat": round(st.stddev[0], 1)}
    except Exception:
        return None


def has_camera(data: Optional[bytes]) -> Optional[bool]:
    """Does a photo's EXIF name the camera that took it? None when it can't be read."""
    if Image is None or not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            exif = im.getexif()
            return bool(exif.get(0x010F) or exif.get(0x0110))      # Make, Model
    except Exception:
        return None


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def cache_load(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d.get("items", {}) if d.get("version") == CACHE_VERSION else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _write_json(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, path)


def analyse(source, items: list, phone_dir: Optional[Path] = None, now: Optional[dt.datetime] = None,
            progress: Optional[Callable] = None, cancel: Optional[threading.Event] = None,
            screenshot_days: int = SCREENSHOT_DAYS) -> Optional[Result]:
    """The six cards for these items. progress(done, total) is called from worker threads; returns None if
    cancelled. The measurements are kept in phone_dir/cleanup-cache.json (none kept when phone_dir is None)."""
    t0 = time.perf_counter()
    now = now or dt.datetime.now()
    lib = None
    try:
        lib = source.library()
    except Exception:
        lib = None
    hidden = [i for i in items if getattr(i, "hidden", False)]
    cloud = [i for i in items if getattr(i, "cloud_only", False) and not getattr(i, "hidden", False)]
    pool = [i for i in items if not getattr(i, "hidden", False) and not getattr(i, "cloud_only", False)]
    cache_path = Path(phone_dir) / "cleanup-cache.json" if phone_dir else None
    cache = cache_load(cache_path)
    knows_app = bool(getattr(lib, "knows_app", False))

    # what each item needs: a checksum when another item has its size, a measurement for photos,
    # and its camera details when the library doesn't say which app saved it
    by_size: dict = {}
    for i in pool:
        if i.size:
            by_size.setdefault(i.size, []).append(i)
    want_sha = {i.id for g in by_size.values() if len(g) > 1 for i in g}
    todo = []
    for i in pool:
        k = key_of(i)
        c = cache.get(k, {})
        need = []
        if i.id in want_sha and "sha" not in c:
            need.append("sha")
        if not i.video and "mean" not in c and "bad" not in c:
            need.append("measure")
        if (not knows_app and not i.video and not getattr(i, "screenshot", False) and "cam" not in c
                and Path(i.name).suffix.lower() in (".jpg", ".jpeg") and 0 < i.size <= APP_MAX_BYTES):
            need.append("cam")
        if need:
            todo.append((i, k, need))

    done = [0]
    lock = threading.Lock()

    def work(job):
        i, k, need = job
        if cancel is not None and cancel.is_set():
            return
        c = dict(cache.get(k, {}))
        data = None
        if "sha" in need or "cam" in need:
            data = source.read(i.id)
            if data is not None:
                if "sha" in need:
                    c["sha"] = hashlib.sha256(data).hexdigest()
                if "cam" in need:
                    cam = has_camera(data)
                    if cam is not None:
                        c["cam"] = cam
        if "measure" in need:
            m = None
            try:
                t = source.thumbnail(i)
                m = measure_image(t) if t else None
            except Exception:
                m = None
            if m is None and data is not None:
                m = measure_image(data)
            if m is None:
                c["bad"] = 1                    # can't be measured (no thumbnail, unreadable): not judged
            else:
                c.update(m)
        with lock:
            cache[k] = c
            done[0] += 1
            if progress:
                progress(done[0], len(todo))

    if todo:
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(work, todo))
    if cancel is not None and cancel.is_set():
        return None
    if cache_path is not None and todo:
        keep = {key_of(i) for i in items}           # forget photos no longer on the phone
        try:
            _write_json(cache_path, {"version": CACHE_VERSION, "items": {k: v for k, v in cache.items() if k in keep}})
        except OSError:
            pass
    facts = {i.id: cache.get(key_of(i), {}) for i in pool}

    def space_of(i) -> int:
        return (i.size or 0) + (source.part_size(i.live_video) if getattr(i, "live_video", None) else 0)

    icloud = True if (cloud or any(i.id.startswith("PhotoData/CPLAssets/") for i in items)) else None
    cards = _cards(pool, facts, now, lib is not None, knows_app, screenshot_days, space_of)
    shown = {i.id: i for c in cards for g in c.groups for i in g.items}
    r = Result(cards, shown, {"hidden": len(hidden), "icloud": len(cloud)}, time.perf_counter() - t0, len(todo),
               icloud, space_of)
    if phone_dir:
        remember(Path(phone_dir), r, {i.id for i in items})
    return r


# -- the cards ---------------------------------------------------------------------------------------------------
def _rank(i, f: dict) -> tuple:
    """Which of a group to keep: the sharpest, then the largest, then with location and date, then favourites;
    then the camera's own over an app's copy, then the earliest."""
    dated = getattr(i, "when", None) is not None and i.when.year > 1970
    located = getattr(i, "lat", None) is not None
    return (f.get("sharp", 0.0), i.size or 0, located and dated, bool(getattr(i, "favorite", False)),
            not getattr(i, "saved_by", None), -(i.when.timestamp() if dated else 0))


def _group(members: list, facts: dict, tick: bool) -> Optional[Group]:
    best = max(members, key=lambda i: _rank(i, facts.get(i.id, {})))
    g = Group(sorted(members, key=lambda i: i.when), keep={best.id}, locked={i.id for i in members if protected(i)})
    if not g.candidates():
        return None
    if tick:
        g.ticked = {i.id for i in g.candidates()}
    return g


def length_text(seconds: Optional[float]) -> str:
    if not seconds:
        return ""
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s" if s % 60 else f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _is_screenshot(i, have_lib: bool) -> bool:
    if getattr(i, "screenshot", False) or getattr(i, "screen_recording", False):
        return True
    if have_lib:
        return False
    name = i.name.lower()                    # without the library: what the file itself says
    return name.endswith(".png") or name.startswith("rpreplay")


def _cards(pool: list, facts: dict, now: dt.datetime, have_lib: bool, knows_app: bool, days: int,
           space_of) -> list:
    cards = {k: Card(k, t, f, s, space_of=space_of) for k, t, f, s in CARDS}
    cards["screenshots"].finds = f"Screenshots and screen recordings older than {days} days"

    # Duplicates: the same checksum
    by_sha: dict = {}
    for i in pool:
        sha = facts[i.id].get("sha")
        if sha:
            by_sha.setdefault(sha, []).append(i)
    copies = set()                                   # duplicates that aren't kept: left out of Similar shots
    for members in by_sha.values():
        if len(members) > 1:
            g = _group(members, facts, tick=True)
            if g:
                cards["duplicates"].groups.append(g)
                copies |= {i.id for i in g.candidates()}

    # Similar shots: bursts, and runs taken seconds apart that look alike
    stills = sorted((i for i in pool if not i.video and i.id not in copies and not _is_screenshot(i, have_lib)
                     and "dh" in facts[i.id] and facts[i.id]["flat"] >= FLAT_BELOW), key=lambda i: i.when)
    runs, run = [], []
    for i in stills:
        if run:
            p = run[-1]
            close = (i.when - p.when).total_seconds() <= SIMILAR_SECONDS
            if close and distance(facts[i.id]["dh"], facts[p.id]["dh"]) <= SIMILAR_BITS:
                run.append(i)
                continue
            runs.append(run)
        run = [i]
    if run:
        runs.append(run)
    bursts: dict = {}
    for i in pool:
        if getattr(i, "burst", None) and not i.video and i.id not in copies:
            bursts.setdefault(i.burst, []).append(i)
    grouped = set()
    for members in list(bursts.values()) + runs:
        members = [i for i in members if i.id not in grouped]
        if len(members) > 1:
            g = _group(members, facts, tick=False)
            if g:
                cards["similar"].groups.append(g)
                grouped |= {i.id for i in members}

    # Poor quality: very dark, overexposed or blurry
    for i in sorted(pool, key=lambda i: i.when, reverse=True):
        f = facts[i.id]
        if i.video or protected(i) or "mean" not in f or _is_screenshot(i, have_lib):
            continue
        why = ("very dark" if f["mean"] < DARK_BELOW else "overexposed" if f["mean"] > BRIGHT_ABOVE
               else "almost no detail" if f["flat"] < FLAT_BELOW else "blurry" if f["sharp"] < BLURRY_BELOW else "")
        if why:
            cards["poor"].groups.append(Group([i], notes={i.id: why}))

    # Old screenshots and screen recordings
    cutoff = now - dt.timedelta(days=days)
    for i in sorted(pool, key=lambda i: i.when):
        if _is_screenshot(i, have_lib) and not protected(i) and i.when < cutoff:
            cards["screenshots"].groups.append(Group([i], ticked={i.id}))

    # Large videos, biggest first
    for i in sorted((i for i in pool if i.video and not protected(i) and (i.size or 0) >= LARGE_VIDEO),
                    key=lambda i: -(i.size or 0)):
        cards["videos"].groups.append(Group([i], notes={i.id: length_text(getattr(i, "duration", None))}))

    # Chat clutter: saved by a chat app (the library says so), or with no camera in its details
    for i in sorted(pool, key=lambda i: i.when, reverse=True):
        if i.video or protected(i) or _is_screenshot(i, have_lib) or i.id in copies:
            continue
        app = CHAT_APPS.get(getattr(i, "saved_by", None) or "")
        if app is None and not knows_app and facts[i.id].get("cam") is False:
            app = "an app"
        if app:
            cards["chat"].groups.append(Group([i], ticked={i.id}, notes={i.id: f"saved from {app}"}))
    if not knows_app:
        cards["chat"].note = ("The iPhone's library doesn't record which app saved each image here, so this card "
                              "lists small JPEGs with no camera in their details: usually images saved from chats.")
    return [cards[k] for k, *_ in CARDS]


# -- the archive: saving and checking ------------------------------------------------------------------------------
def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _part_name(item, part: str) -> str:
    """The name a part is saved under: the photo's own, its Live Photo video with the same name, and the edit
    as '<name> (edited).jpg'."""
    stem = Path(item.name).stem
    if part == item.id:
        return item.name
    if part == getattr(item, "live_video", None):
        return stem + Path(part).suffix
    return f"{stem} (edited){Path(part).suffix}"


@dataclass
class Saved:
    item: object
    files: list                       # [(path, sha256 or None)]
    checked: str                      # "checksum": every file matches what was read; "size": checked by size only


@dataclass
class SaveResult:
    saved: list = field(default_factory=list)          # Saved
    failed: list = field(default_factory=list)         # (item, reason)

    @property
    def verified(self) -> list:
        return [s for s in self.saved if s.checked == "checksum"]


def save(source, items: list, folder: Path, phone_dir: Optional[Path] = None,
         progress: Optional[Callable] = None, cancel: Optional[threading.Event] = None) -> SaveResult:
    """Save each item, whole (the photo, a Live Photo's video, an edit), into folder/<year-month>/ and check
    every file against what was read. The record goes to phone_dir/cleanup.json."""
    import photoconv
    out = SaveResult()
    for n, item in enumerate(items, 1):
        if cancel is not None and cancel.is_set():
            break
        month = item.when.strftime("%Y-%m") if item.when.year > 1970 else "Unknown date"
        dest_dir = Path(folder) / month
        parts = [item.id] + ([item.live_video] if getattr(item, "live_video", None) else []) + source.edits(item)
        files, checked, why = [], "checksum", ""
        for part in parts:
            r = _save_part(source, part, dest_dir, _part_name(item, part), item.when)
            if isinstance(r, str):
                why = r
                break
            path, sha = r
            files.append((path, sha))
            if sha is None:
                checked = "size"
            photoconv.set_file_date(path, item.when)
        if why:
            out.failed.append((item, why))
        else:
            out.saved.append(Saved(item, files, checked))
        if progress:
            progress(n, len(items))
    if phone_dir:
        _record(Path(phone_dir), out)
    return out


def _save_part(source, part: str, dest_dir: Path, name: str, when) -> tuple | str:
    """(path, sha256) once the file in dest_dir matches what was read; (path, None) for a file too big to hold
    in memory, checked by size; a reason when it couldn't be saved."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    listed = source.part_size(part)
    if listed > CHECKSUM_IN_MEMORY:
        dest = dest_dir / name
        if dest.exists() and dest.stat().st_size != listed:
            dest = dest_dir / _free(dest_dir, name)
        if not source.copy(part, dest):
            return "couldn't be read from the iPhone"
        return (dest, None) if dest.stat().st_size == listed else "the saved copy has a different size"
    data = source.read(part)
    if data is None:
        return "couldn't be read from the iPhone"
    want = hashlib.sha256(data).hexdigest()
    dest = dest_dir / name
    if dest.exists():
        if dest.stat().st_size == len(data) and _sha_file(dest) == want:
            return dest, want                     # saved before: the same file
        dest = dest_dir / _free(dest_dir, name)
    tmp = dest.with_name("." + dest.name + ".part")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return f"couldn't be written ({e.strerror or e})"
    if _sha_file(dest) != want or (listed and listed != len(data)):
        return "the saved copy doesn't match the original"
    return dest, want


def _free(folder: Path, name: str) -> str:
    stem, ext = Path(name).stem, Path(name).suffix
    n = 2
    while (folder / f"{stem} ({n}){ext}").exists():
        n += 1
    return f"{stem} ({n}){ext}"


# -- the record per phone: <backups>/<udid>/cleanup.json -------------------------------------------------------------
def load(phone_dir: Optional[Path]) -> dict:
    d = {}
    if phone_dir:
        try:
            d = json.loads((Path(phone_dir) / "cleanup.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
    d.setdefault("saved", {})
    d.setdefault("last", None)
    return d


def _record(phone_dir: Path, r: SaveResult) -> None:
    d = load(phone_dir)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    for s in r.saved:
        d["saved"][s.item.id] = {"files": [[str(p), sha] for p, sha in s.files], "checked": s.checked,
                                 "video": bool(s.item.video), "size": sum(Path(p).stat().st_size for p, _ in s.files),
                                 "when": stamp}
    try:
        _write_json(phone_dir / "cleanup.json", d)
    except OSError:
        pass


def remember(phone_dir: Path, r: Result, on_phone: set) -> None:
    """The last analysis's totals, for the Storage card's suggestion (H2), and which saved items are no longer on
    the phone (removed there since)."""
    d = load(phone_dir)
    for item_id, e in d["saved"].items():
        e["gone"] = item_id not in on_phone
    count, space = r.total(i.id for c in r.cards for i in c.candidates())
    d["last"] = {"when": dt.datetime.now().isoformat(timespec="seconds"), "count": count, "space": space}
    try:
        _write_json(phone_dir / "cleanup.json", d)
    except OSError:
        pass


def in_archive(entry: dict) -> bool:
    """Is a saved item still in the archive, every file matching its checksum? (C2 removes only these.)"""
    if entry.get("checked") != "checksum":
        return False
    for path, sha in entry.get("files", []):
        p = Path(path)
        if not p.exists() or not sha or _sha_file(p) != sha:
            return False
    return True


def saved_videos(phone_dir: Optional[Path]) -> int:
    """Bytes of videos saved and checked by Photo clean-up, still on the iPhone at its last look and still in the
    archive: "Videos already saved on this computer" on the Storage card (the files are looked for, not re-read)."""
    total = 0
    for _item_id, e in load(phone_dir)["saved"].items():
        if not e.get("video") or e.get("checked") != "checksum" or e.get("gone"):
            continue
        if all(Path(p).exists() for p, _sha in e.get("files", [])):
            total += int(e.get("size") or 0)
    return total


# -- removing on the iPhone, until C2 ----------------------------------------------------------------------------------
def removal_steps(saved: list, card_of: dict) -> list:
    """[(heading, text)] for removing these saved items on the iPhone: Duplicates and screenshots have a place of
    their own in Photos; everything else is found by date."""
    by_card: dict = {}
    for s in saved:
        by_card.setdefault(card_of.get(s.item.id, "other"), []).append(s.item)
    out = []
    titles = {k: t for k, t, *_ in CARDS}
    for key, items in by_card.items():
        n = len(items)
        head = f"{titles.get(key, 'Others')}: {n:,} item{'s' if n != 1 else ''}"
        if key in STEPS:
            out.append((head, STEPS[key]))
            continue
        days: dict = {}
        for i in items:
            days[i.when.date()] = days.get(i.when.date(), 0) + 1
        listed = ", ".join(f"{d.day} {d:%b %Y} ({c})" for d, c in sorted(days.items(), reverse=True)[:12])
        more = f", and {len(days) - 12} more days" if len(days) > 12 else ""
        out.append((head, f"On the iPhone: Photos → Library, find them by date: {listed}{more}."))
    return out
