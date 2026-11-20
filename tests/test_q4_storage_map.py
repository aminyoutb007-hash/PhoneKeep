"""Q4: the storage map. What fills the iPhone as blocks as big as the space each takes, that can be clicked into:
Photos → Videos → the largest videos (which open Photo clean-up on Large videos); Apps → the largest apps;
Messages → its attachments.

With a fake iPhone, invented apps and an invented backup file list (nothing talks to a real phone), checks:
- the layout: every block's area is in proportion to its size, inside the map, with no overlaps, and close to square;
- Storage → Storage map: the whole iPhone first (Apps, Photos, Messages, System, Other, Free);
- Photos opens Videos, Photos and other files; Videos opens the 30 largest videos, the rest as one block; a click on
  one opens Photo clean-up on Large videos; Apps opens the 20 largest apps and one block for the rest; Messages opens
  its attachments by kind and its history;
- the path at the top goes back up; a name on a block fits inside it;
- read-only: the map asks the phone nothing, and the backup's file list is read once per backup.
"""
import os, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821

import checkup_ui
import deviceinfo as di
import overview_ui
import storage_map as sm

G = 1000 ** 3
M = 1000 ** 2

# -- the layout -------------------------------------------------------------------------------------------------------
sizes = [500, 300, 120, 80, 40, 30, 20, 7, 2, 1]
for BW, BH in ((800, 400), (300, 600), (640, 360)):
    rects = sm.squarify(sizes, 0, 0, BW, BH)
    tot = sum(sizes)
    ok_area = all(abs(rw * rh - BW * BH * s / tot) < 0.005 * BW * BH for s, (x, y, rw, rh) in zip(sizes, rects))
    inside = all(x >= -0.01 and y >= -0.01 and x + rw <= BW + 0.01 and y + rh <= BH + 0.01 for x, y, rw, rh in rects)
    overlap = any(min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 0.01
                  and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > 0.01
                  for i, a in enumerate(rects) for b in rects[i + 1:])
    worst = max(max(rw / rh, rh / rw) for x, y, rw, rh in rects[:4])
    check(ok_area and inside and not overlap and worst < 3.5,                                   # noqa: F821
          f"{BW}x{BH}: each block's area in proportion, inside, no overlaps, the big ones near square (worst {worst:.1f})")
check(sm.squarify([0, 0], 0, 0, 100, 100) == [(0, 0, 0.0, 0.0)] * 2 and sm.squarify([], 0, 0, 10, 10) == [],   # noqa: F821
      "nothing to show: no blocks, no error")
# many tiny blocks beside huge ones (a 1 TB library next to 1-byte files), zeros among them, sizes not in order,
# and boxes from a phone-sized map down to 1 x 1: every block gets its share, nothing negative, outside or overlapping
tiny_cases = {"one huge, 300 of 1": [10 ** 12] + [1] * 300,
              "zeros among them": [10 ** 12, 0, 5, 0, 1],
              "halving 60 times": [2 ** (60 - i) for i in range(60)],
              "300 equal tiny ones": [1] * 300,
              "not in order": [1, 10 ** 9, 3, 10 ** 6, 2]}
tiny_bad = []


def _overlap(a, b):
    return max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0.0, min(a[1] + a[3], b[1] + b[3])
                                                                       - max(a[1], b[1]))


for label, sizes in tiny_cases.items():
    for BW, BH in ((800, 360), (300, 600), (1, 1)):
        rects = sm.squarify(sizes, 0, 0, BW, BH)
        tot, box = sum(sizes), BW * BH
        share = [box * s_ / tot for s_ in sizes]
        eps = 1e-9 * max(BW, BH)                              # rounding, scaled to the box
        why = ("count" if len(rects) != len(sizes) else
               "negative or NaN" if any(not (rw >= 0 and rh >= 0) for x, y, rw, rh in rects) else
               "outside" if any(x < -eps or y < -eps or x + rw > BW + eps or y + rh > BH + eps
                                for x, y, rw, rh in rects) else
               # each block's area is its own share (to rounding), however small, and together they fill the box
               "area" if any(abs(rw * rh - e) > 1e-6 * e + 1e-12 * box for e, (x, y, rw, rh) in zip(share, rects))
               or abs(sum(rw * rh for x, y, rw, rh in rects) - box) > 1e-9 * box else
               # no two blocks share more than rounding of the smaller one's area
               "overlap" if any(_overlap(a, b) > 1e-6 * min(a[2] * a[3], b[2] * b[3]) + 1e-12 * box
                                for i, a in enumerate(rects) for b in rects[i + 1:]) else "")
        if why:
            tiny_bad.append(f"{label} in {BW}x{BH}: {why}")
check(not tiny_bad, "tiny blocks: each has its share, none negative, outside or overlapping, in any box"     # noqa: F821
      + (f" ({'; '.join(tiny_bad)})" if tiny_bad else ""))

# a Live Photo's moving part (a .MOV next to its still) is part of the photo, as in Photos and clean-up
live = {"Media/DCIM/100APPLE/IMG_0500.HEIC": ("a" * 40, 0, 3_000_000),
        "Media/DCIM/100APPLE/IMG_0500.MOV": ("b" * 40, 0, 2_000_000),
        "Media/DCIM/100APPLE/IMG_0501.MOV": ("c" * 40, 0, 50_000_000),
        "Media/DCIM/100APPLE/IMG_0502.BMP": ("d" * 40, 0, 1_000_000),      # a still photos.py pairs, as the map must
        "Media/DCIM/100APPLE/IMG_0502.MOV": ("e" * 40, 0, 1_000_000)}
ms = sm.media_sizes(lambda d, p: live if d == "CameraRollDomain" else {})
check([v[0] for v in ms["videos"]] == ["IMG_0501.MOV"]                                          # noqa: F821
      and ms["photos"] == {"video": 50_000_000, "photo": 6_000_000, "other": 1_000_000, "deleted": 0},
      f"a Live Photo's .MOV counts with its photo, not as a video ({ms['photos']})")

# with the Photos library: what's in its Recently Deleted shows as that (a Live Photo's moving part with its
# photo), the originals iCloud Photos downloaded again (PhotoData/CPLAssets) count too, a Live Photo kept there is
# paired as in DCIM, and the videos are named as Photos names them
import datetime as _dt
import photos as _ph
cam = {"Media/DCIM/100APPLE/IMG_0600.HEIC": ("f" * 40, 0, 4_000_000),
       "Media/DCIM/100APPLE/IMG_0600.MOV": ("1" * 40, 0, 3_000_000),           # its Live Photo's moving part
       "Media/DCIM/100APPLE/IMG_0601.MOV": ("2" * 40, 0, 70_000_000),
       "Media/DCIM/100APPLE/IMG_0602.MOV": ("3" * 40, 0, 20_000_000),          # in Recently Deleted
       "Media/DCIM/100APPLE/IMG_0603.HEIC": ("7" * 40, 0, 2_000_000),          # a Live Photo in Recently Deleted
       "Media/DCIM/100APPLE/IMG_0603.MOV": ("8" * 40, 0, 1_000_000),
       "Media/DCIM/100APPLE/IMG_0600.AAE": ("4" * 40, 0, 1_000),
       "Media/PhotoData/CPLAssets/group1/0A1B.MOV": ("5" * 40, 0, 90_000_000),  # downloaded again from iCloud
       "Media/PhotoData/CPLAssets/group1/0A1C.HEIC": ("6" * 40, 0, 5_000_000),  # a Live Photo kept there
       "Media/PhotoData/CPLAssets/group1/0A1C.MOV": ("9" * 40, 0, 2_500_000),
       "Media/PhotoData/CPLAssets/group2/0B2D.JPG": ("a" * 40, 0, 6_000_000),   # not a library row: not deleted
       "Media/PhotoData/CPLAssets/group2/0B2E.MOV": ("b" * 40, 0, 8_000_000)}   # not listed: not a map video
when = _dt.datetime(2026, 1, 1)
its = [_ph.PhotoItem("DCIM/100APPLE/IMG_0600.HEIC", "IMG_0600.HEIC", 4_000_000, when, False,
                     live_video="DCIM/100APPLE/IMG_0600.MOV"),
       _ph.PhotoItem("DCIM/100APPLE/IMG_0601.MOV", "IMG_0601.MOV", 70_000_000, when, True),
       _ph.PhotoItem("PhotoData/CPLAssets/group1/0A1B.MOV", "IMG_0700.MOV", 90_000_000, when, True),
       _ph.PhotoItem("PhotoData/CPLAssets/group1/0A1C.HEIC", "IMG_0701.HEIC", 5_000_000, when, False),
       _ph.PhotoItem("DCIM/100APPLE/IMG_0703.MOV", "IMG_0703.MOV", 0, when, True, cloud_only=True)]   # iCloud only
in_trash = {"DCIM/100APPLE/IMG_0602.MOV", "DCIM/100APPLE/IMG_0603.HEIC"}
fm = lambda d, p: {k: v for k, v in cam.items() if k.startswith(p)} if d == "CameraRollDomain" else {}
in_lib = sm.media_sizes(fm, its, in_trash)
check([v[:2] for v in in_lib["videos"]] == [("IMG_0700.MOV", 90_000_000), ("IMG_0601.MOV", 70_000_000)]   # noqa: F821
      and in_lib["photos"] == {"video": 160_000_000, "photo": 20_500_000, "other": 8_001_000, "deleted": 23_000_000},
      f"with the library: Recently Deleted is what it has there (a Live Photo with its moving part); a Live Photo in "
      f"PhotoData/CPLAssets is paired, and a file there that isn't in Photos' list isn't deleted either; the videos "
      f"are Photos', named as in Photos, and a video it doesn't list is another file ({in_lib['photos']})")
# no library (Photos.sqlite missing or unreadable): nothing is called deleted, every camera file still counts
no_lib = sm.media_sizes(fm, [i for i in its if i.id.startswith("DCIM/")], None)
check(no_lib["photos"]["deleted"] == 0 and sum(no_lib["photos"].values()) == sum(v[2] for v in cam.values()),  # noqa: F821
      f"  without the library nothing is called Recently Deleted, and every camera file still counts, PhotoData/"
      f"CPLAssets too ({no_lib['photos']})")
# the window's read (_read_media) hands the library's Recently Deleted to the map: with an invented source whose
# library has one trashed video, its size reaches win.map_media; with no library, nothing is deleted
import types as _types


class _Src:
    def __init__(self, lib):
        self.lib = lib

    def library(self):
        return self.lib


class _Data:
    def __init__(self, lib):
        self.src = _Src(lib)

    def file_meta(self, d, p=""):
        return fm(d, p)

    def get(self, key):
        assert key == "photos"
        return self.src, its


_Lib = _types.SimpleNamespace
for lib, want in ((_Lib(assets={"DCIM/100APPLE/IMG_0602.MOV": _Lib(trashed=True),
                                "DCIM/100APPLE/IMG_0601.MOV": _Lib(trashed=False)}), 20_000_000), (None, 0)):
    _w = _types.SimpleNamespace(data=_Data(lib), current="elsewhere", overview=None,
                                backup_runner=_types.SimpleNamespace(submit=lambda fn, ok, err: ok(fn())))
    sm._read_media(_w, None, "photos")
    got = getattr(_w, "map_media", (None, {}))[1]
    check(got.get("photos", {}).get("deleted") == want                                                # noqa: F821
          and [v[0] for v in got.get("videos", [])][:2] == ["IMG_0700.MOV", "IMG_0601.MOV"],
          f"  the window's read hands the library's Recently Deleted to the map "
          f"({'one trashed video' if lib else 'no library'}: {got.get('photos', {}).get('deleted')}), with Photos' videos")

_r = type("R", (), {"file_meta": lambda self, d, p="": {k: v for k, v in cam.items() if k.startswith(p)}
                    if d == "CameraRollDomain" else {}})()
check(phone.PhoneWindow._backup_sizes(_r)[0] == sum(v[2] for v in cam.values()),                      # noqa: F821
      "  and the Storage screen's Photos (V3) counts PhotoData/CPLAssets as well, so the map's levels agree")

# -- an invented phone and backup ---------------------------------------------------------------------------------------
names = [(f"Example App {i:02d}", f"com.example.app{i:02d}") for i in range(23)]                    # invented
apps = [di.AppSize(b, n, (30 - i) * G // 10, G // 20) for i, (n, b) in enumerate(names)]
OV = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=256 * G, free=60 * G, apps=apps)
videos = {f"Media/DCIM/100APPLE/IMG_{i:04d}.MOV": (f"{i:040x}", 1_750_000_000 + i * 86400, (900 - i * 20) * M)
          for i in range(40)}                                                                     # 40 invented videos
stills = {f"Media/DCIM/100APPLE/IMG_{i:04d}.HEIC": (f"{i:040x}", 1_750_000_000, 3 * M) for i in range(100, 2100)}
edits = {f"Media/DCIM/100APPLE/IMG_{i:04d}.AAE": (f"{i:040x}", 1_750_000_000, 2_000) for i in range(100, 200)}
FILES = {("CameraRollDomain", "Media/DCIM/"): {**videos, **stills, **edits},
         ("MediaDomain", "Library/SMS/Attachments/"): {"Library/SMS/Attachments/aa/01/a.mov": ("1" * 40, 0, 400 * M),
                                                       "Library/SMS/Attachments/aa/02/b.jpeg": ("2" * 40, 0, 250 * M),
                                                       "Library/SMS/Attachments/aa/03/c.pdf": ("3" * 40, 0, 50 * M)},
         ("HomeDomain", "Library/SMS/"): {"Library/SMS/sms.db": ("4" * 40, 0, 300 * M)}}
reads = {"n": 0}


class FakeBackup:
    """Just the file list the map reads, under the window's lock as BackupData would."""
    def file_meta(self, domain, prefix=""):
        reads["n"] += 1
        return dict(FILES.get((domain, prefix), {}))

    def close(self):
        pass


asked = {"n": 0}


class Quiet(SimulatedDevice):                                                            # noqa: F821
    def app_names(self, timeout=60):
        asked["n"] += 1
        return {a.bundle: a.name for a in apps}

    def app_sizes(self, bundles, timeout=120):
        asked["n"] += 1
        return {a.bundle: (a.app_bytes, a.data_bytes) for a in apps if a.bundle in bundles}


wv.device_overview = lambda udid=None, apps=True, **k: OV                                # noqa: F821
devmod.LiveDevice = Quiet                                                                # noqa: F821
app = FakeApp()                                                                          # noqa: F821
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": "USB", "ProductVersion": "26.5"}, UDID)  # noqa: F821
pump(app, lambda: win.overview is not None and win.live is not None, 30, "overview")    # noqa: F821
win.overview.apps, win.overview.apps_as_of = list(apps), ""
win._apps_state = "done"
win.geometry("1220x800")
# the window opens this test phone's own backup (and works out its sizes) in the background: let that finish, so it
# can't land on top of the invented backup put in its place here (seen on Linux)
pump(app, lambda: win.data is not None and win.photos_bytes is not None and win.messages_bytes is not None, 60,
     "the window's own backup")                                                                    # noqa: F821
drained = []                                     # a marker after anything still queued on the backup's worker
win.backup_runner.submit(lambda: None, lambda _r: drained.append(1), lambda _e: drained.append(1))
pump(app, lambda: bool(drained), 60, "the backup's worker")                                        # noqa: F821
win.data.close()
data = FakeBackup()
win.data = data
win.photos_bytes = sum(v[2] for v in FILES[("CameraRollDomain", "Media/DCIM/")].values())
win.messages_bytes = 1000 * M


def settle(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        app.update()
        time.sleep(0.02)


opened = []
checkup_ui.open_cleanup = lambda w, card: opened.append(card)
before = asked["n"]

overview_ui.storage_view(win, win.overview)
app.update()
check(getattr(win, "map_button", None) is not None and win.map_button.winfo_ismapped(),          # noqa: F821
      "Storage has a Storage map button")
win.map_button.command()
pump(app, lambda: win.current == "storagemap" and getattr(win, "map_media", None), 30, "the backup's file list")  # noqa: F821
settle()                                                                    # noqa: F821
names_top = [b.name for b in win.map_blocks]
check(win.current == "storagemap" and set(names_top) == {"Apps", "Photos", "Messages", "System", "Other", "Free"},   # noqa: F821
      f"the map: the whole iPhone first ({', '.join(names_top)})")
check([b.size for b in win.map_blocks] == sorted((b.size for b in win.map_blocks), reverse=True),    # noqa: F821
      "  biggest first")
check(sum(b.size for b in win.map_blocks) == OV.total, "  and together they're the whole capacity")     # noqa: F821
check({b.name for b in win.map_blocks if b.open} == {"Apps", "Photos", "Messages"},              # noqa: F821
      "  Apps, Photos and Messages can be opened")
check(win.map_crumbs == ["iPhone"], f"  the path at the top says where it is ({win.map_crumbs})")    # noqa: F821
cv = win.map_canvas
MW, MH = cv.winfo_width(), cv.winfo_height()
check(MW > 500 and MH > 250, f"  the map has room ({MW}x{MH})")                                      # noqa: F821
total = sum(b.size for b in win.map_blocks)
areas = {n: rw * rh for n, x, y, rw, rh in win.map_rects}
check(all(abs(areas[b.name] - MW * MH * b.size / total) < 0.01 * MW * MH for b in win.map_blocks),    # noqa: F821
      "  each block on screen is as big as the space it takes")


def texts_fit():
    """Every name and size drawn on a block stays inside that block, and no two overlap."""
    bad = []
    cv = win.map_canvas
    boxes = [cv.bbox(t) for t in cv.find_all() if cv.type(t) == "text"]
    for i, a in enumerate(boxes):
        for c in boxes[i + 1:]:
            if min(a[2], c[2]) - max(a[0], c[0]) > 1 and min(a[3], c[3]) - max(a[1], c[1]) > 1:
                bad.append(f"overlap at {a[:2]}")
    for name, x, y, rw, rh in win.map_rects:
        i = [r[0] for r in win.map_rects].index(name)
        for t in win.map_canvas.find_withtag(f"b{i}"):
            if win.map_canvas.type(t) == "text":
                x0, y0, x1, y1 = win.map_canvas.bbox(t)
                if x0 < x - 1 or y0 < y - 1 or x1 > x + rw + 1 or y1 > y + rh + 1:
                    bad.append(name)
    return bad


check(not texts_fit(), f"  a name on a block fits inside it ({texts_fit() or 'all fit'})")               # noqa: F821
check("Messages" in win.map_unnamed and any("Messages · about" in str(w.cget("text"))
      for w in win.content.winfo_children()[-1].winfo_children()),
      f"  a block too small for its name is named under the map ({win.map_unnamed})")             # noqa: F821


def click(name):
    """A real click in the middle of that block on the map."""
    n, x, y, rw, rh = next(r for r in win.map_rects if r[0] == name)
    win.map_canvas.event_generate("<Motion>", x=int(x + rw / 2), y=int(y + rh / 2))
    win.map_canvas.event_generate("<Button-1>", x=int(x + rw / 2), y=int(y + rh / 2))
    app.update()


click("Photos")
pump(app, lambda: getattr(win, "map_key", "") == "photos", 5)                                    # noqa: F821
if win.map_key != "photos":                    # no pointer events here (a window not on screen): the same action
    print("  (no pointer events on this screen: opening the block as a click would)")
    win.map_open("Photos")
    app.update()
settle()                                                                    # noqa: F821
pb = {b.name: b for b in win.map_blocks}
check(win.map_key == "photos" and set(pb) == {"Videos", "Photos", "Edits and other files"},     # noqa: F821
      f"Photos opens: what's in it ({', '.join(pb)})")
check(pb["Videos"].size == sum(v[2] for v in videos.values()) and pb["Videos"].sub == "40 videos"
      and pb["Photos"].size == 2000 * 3 * M, "  videos and photos, with their sizes from the backup")    # noqa: F821
check(win.map_crumbs == ["iPhone", "Photos"], f"  the path: {' › '.join(win.map_crumbs)}")      # noqa: F821
win.map_open("Videos")
settle()                                                                    # noqa: F821
vb = win.map_blocks
check(win.map_key == "videos" and len(vb) == 31 and vb[0].name == "IMG_0000.MOV" and vb[0].size == 900 * M
      and vb[-1].name == "10 smaller videos" and vb[-1].size == sum((900 - i * 20) * M for i in range(30, 40)),
      f"Videos opens: the 30 largest, biggest first, and the rest as one ({vb[-1].name})")          # noqa: F821
check(vb[0].sub and "2025" in vb[0].sub, f"  each with its date ({vb[0].sub})")                    # noqa: F821
check(win.map_crumbs == ["iPhone", "Photos", "Videos"], f"  the path: {' › '.join(win.map_crumbs)}")  # noqa: F821
check(not texts_fit(), f"  names fit inside their blocks ({texts_fit() or 'all fit'})")           # noqa: F821
win.map_open("IMG_0003.MOV")
check(opened == ["videos"], f"a click on a video opens Photo clean-up on Large videos ({opened})")    # noqa: F821
# back up by the path


def click_path(text):
    """A click on that link in the path at the top, once it's on screen (on a busy machine the new labels can take
    a moment to show, and a click on one that isn't shown yet is lost); then the map that click opens."""
    crumb = [w for w in win.content.winfo_children()[1].winfo_children() if isinstance(w, tk.Label)
             and w.cget("text") == text]                                                           # noqa: F821
    pump(app, lambda: crumb[0].winfo_viewable(), 5, f"the path's {text} link on screen")         # noqa: F821
    crumb[0].event_generate("<Button-1>")
    pump(app, lambda: win.map_key == "top", 5, f"the map its {text} link opens")                  # noqa: F821


click_path("iPhone")
check(win.map_key == "top", "the path at the top goes back up (iPhone)")                           # noqa: F821
win.map_open("Apps")
app.update()
ab = win.map_blocks
check(win.map_key == "apps" and len(ab) == 21 and ab[0].name == "Example App 00"
      and ab[-1].name == "3 other apps", f"Apps opens: the 20 largest and the rest as one ({ab[-1].name})")   # noqa: F821
sm.view(win, win.overview, "top")
win.map_open("Messages")
app.update()
mb = {b.name: b.size for b in win.map_blocks}
check(mb == {"Videos sent and received": 400 * M, "Photos sent and received": 250 * M, "Other attachments": 50 * M,
             "The messages themselves": 300 * M}, f"Messages opens: its attachments by kind and its history")  # noqa: F821
check(reads["n"] == 4, f"the backup's file list was read once for this backup ({reads['n']} reads: 4 folders)")  # noqa: F821
# another backup: it's read again; the map says so while it's read
win.data = FakeBackup()
sm.view(win, win.overview, "top")
check("Reading the backup" in win.map_note.cget("text"), "a newer backup: read again, and the map says so meanwhile")  # noqa: F821
pump(app, lambda: reads["n"] == 6 and win.map_media[0] is win.data, 30)                         # noqa: F821
# while the list is being read, neither Photos nor Messages can be opened (what's inside them comes from it)
slow_go = threading.Event()


class SlowBackup(FakeBackup):
    def file_meta(self, domain, prefix=""):
        slow_go.wait(20)
        return super().file_meta(domain, prefix)


win.data = SlowBackup()
sm.view(win, win.overview, "top")
closed = {b.name for b in win.map_blocks if not b.open}
check({"Photos", "Messages"} <= closed and "Reading the backup" in win.map_note.cget("text"),
      "while the backup is read, Photos and Messages don't open yet")                             # noqa: F821
slow_go.set()
pump(app, lambda: win.map_media[0] is win.data, 30)                                               # noqa: F821


class FlakyBackup(FakeBackup):
    """Its file list can't be read the first time; it can after that."""
    def __init__(self):
        self.calls = 0

    def file_meta(self, domain, prefix=""):
        self.calls += 1
        if self.calls == 1:
            raise wv.PhoneKeepError("This backup was closed.")                                     # noqa: F821
        return super().file_meta(domain, prefix)


flaky = FlakyBackup()
win.data = flaky
sm.view(win, win.overview, "top")
pump(app, lambda: getattr(win, "map_failed", None) and win.map_failed[0] is flaky, 30)            # noqa: F821
settle()
check("couldn't be read" in win.map_note.cget("text") and "Reading the backup" not in win.map_note.cget("text")
      and not any(b.open for b in win.map_blocks if b.name in ("Photos", "Messages")),
      f"a list that can't be read: the map says so plainly, and Photos and Messages stay closed")  # noqa: F821
sm.view(win, win.overview, "top")
settle(1)
check(flaky.calls == 1 and "couldn't be read" in win.map_note.cget("text"),
      f"  it isn't tried again by itself (no endless retries; {flaky.calls} read)")                 # noqa: F821
sm.view(win, win.overview, "top", again=True)                       # as the Storage map button opens it
pump(app, lambda: getattr(win, "map_media", None) and win.map_media[0] is flaky, 30)              # noqa: F821
settle()
check(flaky.calls > 1 and win.map_failed is None and "couldn't be read" not in win.map_note.cget("text")
      and any(b.open for b in win.map_blocks if b.name == "Photos"),
      "  opening it again from Storage tries the same backup again, and then Photos opens")        # noqa: F821
# an iPhone whose System can't be estimated: it's left off the map, and the map says the blocks add up to less
big = [di.AppSize(f"com.example.big{i}", f"Example Big {i}", 42 * G, 0) for i in range(4)]         # invented
was_apps = win.overview.apps
win.overview.apps = big
sm.view(win, win.overview, "top")
settle()
check(not any(b.name.startswith("System") for b in win.map_blocks) and "can't be estimated" in win.map_note.cget("text")
      and sum(b.size for b in win.map_blocks) < OV.total,
      "System can't be estimated: it's left off, and the map says the blocks add up to less than the iPhone")  # noqa: F821
win.overview.apps = was_apps
win.data = None
sm.view(win, win.overview, "top")
check(not next(b for b in win.map_blocks if b.name == "Photos").open
      and "once there's a backup" in win.map_note.cget("text"), "no backup: Photos can't be opened, and it says why")  # noqa: F821
# the app sizes arrive while the map is open (5.2.6 follow-up): it's drawn again with them, and says they're coming in
import dataclasses
sm.view(win, win.overview, "apps")
win._apps_shown_at = 0.0                                            # the 2-second limit between redraws has passed
win._apps_arrived(list(apps[:5]), True)                             # the first sizes are in, more to come
app.update()
check(win.current == "storagemap" and win.map_key == "apps" and len(win.map_blocks) == 5
      and "still sending app sizes" in win.map_note.cget("text"),
      f"app sizes arriving: the open map is drawn again with them, and says more are coming ({len(win.map_blocks)} apps)")  # noqa: F821
win.data = flaky                                                    # its file list is in (read above)
sm.view(win, win.overview, "top")
win.map_open("Photos")
app.update()
drawn = win.map_canvas
win._apps_shown_at = 0.0
win._apps_arrived(list(apps[:6]), True)
app.update()
check(win.map_key == "photos" and win.map_canvas is drawn,
      "  a level without app sizes on it (Photos) isn't drawn again for them")                    # noqa: F821
win.data = None
sm.view(win, win.overview, "apps")
win._apps_shown_at = 0.0
win._apps_arrived(list(apps), False)                                # all of them
app.update()
check(win.map_key == "apps" and len(win.map_blocks) == 21 and "still sending" not in win.map_note.cget("text"),
      f"  and again when they're all in ({len(win.map_blocks)} blocks)")                           # noqa: F821
# the phone is read again (a new overview) while the map is open: the path and the blocks use the new figures
was_ov = win.overview
new_ov = dataclasses.replace(OV, apps=[di.AppSize(f"com.example.new{i}", f"Example New {i}", 2 * G, 0)
                                       for i in range(3)])                                          # invented
sm.view(win, was_ov, "top")                                         # the top level, drawn with the old figures
win.overview = new_ov
win.map_open("Apps")                                                # a block click alone, no path link first
app.update()
check(win.map_key == "apps" and [b.name for b in win.map_blocks] == [f"Example New {i}" for i in range(3)],
      f"a block click opens it with the phone's newest figures ({len(win.map_blocks)} apps)")      # noqa: F821
sm.view(win, was_ov, "apps")                                        # an inner level, drawn with the old figures
click_path("iPhone")
top_apps = next((b.size for b in win.map_blocks if b.name == "Apps"), None)
if top_apps is not None:                        # the top level was drawn to the end, Apps block and all
    win.map_open("Apps")
    app.update()
check(win.map_key == "apps" and top_apps == 6 * G and [b.name for b in win.map_blocks] == [f"Example New {i}" for i in range(3)],
      f"the path and the blocks follow the phone's newest figures, not the ones the map opened with ({top_apps}; "
      f"at {win.map_key}: {', '.join(b.name for b in win.map_blocks[:4])})")                       # noqa: F821
win.overview = was_ov
# back to Storage
win.content.winfo_children()[0].winfo_children()[0].command()                     # ‹ Storage
app.update()
check(win.current == "storage", "‹ Storage goes back")                                             # noqa: F821
check(asked["n"] == before, "read-only: the map asks the phone nothing")                           # noqa: F821
win.data = data
win.close()
app.destroy()
print("\nQ4 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)  # noqa: F821
os._exit(1 if failures else 0)
