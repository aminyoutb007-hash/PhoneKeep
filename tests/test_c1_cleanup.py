"""C1: Photo clean-up, find and save (docs/spec/13-phone-health.md#c1-photo-clean-up-find-and-save).

Done when:
- on the rich photo fixture extended with seeded duplicates, near-duplicates, blurred, dark, screenshot and
  chat-saved images, each card finds what was seeded and nothing else (no favourites, no album photos);
- 10,000 photos are analysed in under 5 minutes on an Apple Silicon Mac; a second visit opens in under 2 seconds
  (here: 10,000 photos with their thumbnails from a stand-in source; the real iPhone in tools/real_check.py);
- every item offered for removal is present in the archive with a matching checksum.
The fixture is a copy of the rich test backup (make_rich.py) with seeded photos and a Photos library like the
phone's added to it. Nothing touches a real phone. Names are invented.
"""
import datetime as dt
import hashlib, io, os, plistlib, random, shutil, sqlite3, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE / "work" / "c1"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
os.environ["PHONEKEEP_HOME"] = str(W / "home")
os.environ["PHONEKEEP_NO_HELPER"] = "1"
sys.path.insert(0, str(HERE.parent))

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import cleanup as cl
import library
import phonekeep as wv
import photos as ph

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


MB = 1000 ** 2
NOW = dt.datetime(2026, 11, 14, 12, 0)


def scene(seed, size=(1200, 900), shift=0):
    random.seed(seed)
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    a = [random.randint(40, 230) for _ in range(6)]
    for y in range(size[1]):
        t = y / size[1]
        d.line([(0, y), (size[0], y)], fill=tuple(int(a[i] * (1 - t) + a[i + 3] * t) for i in range(3)))
    for _ in range(6):
        x, y, r = random.randint(0, size[0]), random.randint(0, size[1]), random.randint(60, 260)
        d.ellipse([x - r + shift, y - r, x + r + shift, y + r], fill=tuple(random.randint(30, 255) for _ in range(3)))
    for _ in range(40):                                   # fine detail, like a real photo's texture
        x, y = random.randint(0, size[0]), random.randint(0, size[1])
        d.line([(x + shift, y), (x + shift + random.randint(-80, 80), y + random.randint(-80, 80))],
               fill=tuple(random.randint(0, 255) for _ in range(3)), width=2)
    return im


def jpeg(im, exif=True, quality=85):
    b = io.BytesIO()
    kw = {}
    if exif:
        e = Image.Exif()
        e[0x010F], e[0x0110] = "Apple", "iPhone 15"         # Make, Model: taken with the camera
        kw["exif"] = e.tobytes()
    im.save(b, "JPEG", quality=quality, **kw)
    return b.getvalue()


def png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


# -- the fixture -------------------------------------------------------------------------------------------------
rich = HERE / "work" / "biz" / "backup"
if not (rich / "Manifest.db").exists():
    import subprocess
    for s in ("test_full_backup.py", "make_biz.py", "make_rich.py"):
        subprocess.run([sys.executable, str(HERE / s)], check=True, capture_output=True)
bk = W / "backup"
shutil.copytree(rich, bk)
man = sqlite3.connect(bk / "Manifest.db")
# the base fixture's placeholder videos are all the same 72 bytes (real copies of each other): made unique here,
# so the only copies are the seeded ones
for fid, rel, blob in man.execute("select fileID, relativePath, file from Files where domain='CameraRollDomain' "
                                  "and relativePath like 'Media/DCIM/%.MOV'").fetchall():
    f = bk / fid[:2] / fid
    data = f.read_bytes() + rel.encode()
    f.write_bytes(data)
    o = plistlib.loads(blob)
    for x in o["$objects"]:
        if isinstance(x, dict) and "Size" in x:
            x["Size"] = len(data)
    man.execute("update Files set file=? where fileID=?", (plistlib.dumps(o, fmt=plistlib.FMT_BINARY), fid))


def add(rel, data, when):
    dom = "CameraRollDomain"
    fid = hashlib.sha1(f"{dom}-{rel}".encode()).hexdigest()
    (bk / fid[:2]).mkdir(exist_ok=True)
    (bk / fid[:2] / fid).write_bytes(data)
    blob = plistlib.dumps({"$objects": ["$null", {"LastModified": int(when.timestamp()), "Size": len(data)}]},
                          fmt=plistlib.FMT_BINARY)
    man.execute("insert or replace into Files values (?,?,?,1,?)", (fid, dom, rel, blob))


T = dt.datetime(2026, 10, 1, 10, 0, 0)
base = scene(7)
seeded = []   # (file, data, when, library row overrides)


def seed(name, data, when, **lib):
    seeded.append((name, data, when, lib))


dup = jpeg(scene(11))
seed("IMG_2001.JPG", dup, T)                                                   # the original…
seed("IMG_2002.JPG", dup, T + dt.timedelta(days=3), by="net.whatsapp.WhatsApp")  # …and the same photo from a chat
fav_dup = jpeg(scene(12))
seed("IMG_2003.JPG", fav_dup, T + dt.timedelta(hours=1), fav=1)               # a favourite, and its copy
seed("IMG_2004.JPG", fav_dup, T + dt.timedelta(hours=2))
both = jpeg(scene(13))
seed("IMG_2005.JPG", both, T + dt.timedelta(hours=3), fav=1)                  # a favourite and an album photo:
seed("IMG_2006.JPG", both, T + dt.timedelta(hours=4), album=True)             # both kept, so no group
# a run of three shots seconds apart: the middle one is the sharpest
t = T + dt.timedelta(days=5)
seed("IMG_2010.JPG", jpeg(base.filter(ImageFilter.GaussianBlur(1.6))), t)
seed("IMG_2011.JPG", jpeg(scene(7, shift=4)), t + dt.timedelta(seconds=2))
seed("IMG_2012.JPG", jpeg(scene(7, shift=8).filter(ImageFilter.GaussianBlur(1.2))), t + dt.timedelta(seconds=4))
seed("IMG_2013.JPG", jpeg(scene(21)), t + dt.timedelta(seconds=6))           # seconds later, but another scene
# a burst, as the library records it (taken further apart than a run)
seed("IMG_2020.JPG", jpeg(scene(31)), T + dt.timedelta(days=6), burst="B-1")
seed("IMG_2021.JPG", jpeg(scene(31, shift=6).filter(ImageFilter.GaussianBlur(1.2))), T + dt.timedelta(days=6, seconds=30), burst="B-1")
# poor quality
BLUR = 24                                 # out of focus enough to see on a small version (what can be found)
seed("IMG_2030.JPG", jpeg(scene(41).filter(ImageFilter.GaussianBlur(BLUR))), T + dt.timedelta(days=7))
seed("IMG_2031.JPG", jpeg(ImageEnhance.Brightness(scene(42)).enhance(0.06)), T + dt.timedelta(days=7, hours=1))
seed("IMG_2032.JPG", jpeg(ImageEnhance.Brightness(scene(43)).enhance(6)), T + dt.timedelta(days=7, hours=2))
seed("IMG_2033.JPG", jpeg(scene(44).filter(ImageFilter.GaussianBlur(BLUR))), T + dt.timedelta(days=7, hours=3), fav=1)
seed("IMG_2034.JPG", jpeg(ImageEnhance.Brightness(scene(45)).enhance(0.06)), T + dt.timedelta(days=7, hours=4),
     album=True)
seed("IMG_2035.JPG", jpeg(scene(46).filter(ImageFilter.GaussianBlur(BLUR))), T + dt.timedelta(days=7, hours=5), hidden=1)
seed("IMG_2036.JPG", jpeg(scene(47).filter(ImageFilter.GaussianBlur(BLUR))), T + dt.timedelta(days=7, hours=6), local=0)
# screenshots and a screen recording: old ones, a recent one, an old favourite
seed("IMG_2040.PNG", png(scene(51, (590, 1280))), NOW - dt.timedelta(days=60), sub=10)
seed("IMG_2041.PNG", png(scene(52, (590, 1280))), NOW - dt.timedelta(days=5), sub=10)
seed("RPReplay_Final1700000000.MP4", b"\0\0\0\x18ftypmp42" + b"\0" * 2048, NOW - dt.timedelta(days=45), sub=103, kind=1)
seed("IMG_2043.PNG", png(scene(53, (590, 1280))), NOW - dt.timedelta(days=90), sub=10, fav=1)
# videos: a large one and a large one in an album
seed("IMG_2050.MOV", b"\0\0\0\x18ftypqt  " + os.urandom(3 * MB), T + dt.timedelta(days=8), kind=1, dur=131.4)
seed("IMG_2051.MOV", b"\0\0\0\x18ftypqt  " + os.urandom(3 * MB + 7), T + dt.timedelta(days=8, hours=1), kind=1,
     dur=40, album=True)
# saved from chat apps
seed("IMG_2060.JPG", jpeg(scene(61), exif=False), T + dt.timedelta(days=9), by="net.whatsapp.WhatsApp")
seed("IMG_2061.JPG", jpeg(scene(62), exif=False), T + dt.timedelta(days=9, hours=1), by="ph.telegra.Telegraph")
seed("IMG_2062.JPG", jpeg(scene(63), exif=False), T + dt.timedelta(days=9, hours=2), by="net.whatsapp.WhatsApp", fav=1)
seed("IMG_2063.JPG", jpeg(scene(64)), T + dt.timedelta(days=9, hours=3), by="com.example.camera")
# a Live Photo with an edit: saved whole (photo, its video, the edit)
seed("IMG_2070.JPG", jpeg(scene(71)), T + dt.timedelta(days=10), sub=2, adj=1)
live_mov = b"\0\0\0\x18ftypqt  " + os.urandom(4096)
edit_jpg = jpeg(scene(71).transpose(Image.FLIP_LEFT_RIGHT))

for name, data, when, _lib in seeded:
    if _lib.get("local") == 0:
        continue                                          # only in iCloud: not in the backup
    add(f"Media/DCIM/100APPLE/{name}", data, when)
add("Media/DCIM/100APPLE/IMG_2070.MOV", live_mov, T + dt.timedelta(days=10))
add("Media/PhotoData/Mutations/DCIM/100APPLE/IMG_2070/Adjustments/FullSizeRender.jpg", edit_jpg, T + dt.timedelta(days=11))
add("Media/PhotoData/Mutations/DCIM/100APPLE/IMG_2070/Adjustments/Adjustments.plist", b"<plist/>", T + dt.timedelta(days=11))


def apple(t):
    return (t - library.APPLE_EPOCH).total_seconds()


lib_path = W / "Photos.sqlite"
con = sqlite3.connect(lib_path)
con.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, ZFAVORITE INT, "
            "ZHIDDEN INT, ZTRASHEDSTATE INT, ZKIND INT, ZKINDSUBTYPE INT, ZDATECREATED REAL, ZLATITUDE REAL, "
            "ZLONGITUDE REAL, ZDURATION REAL, ZAVALANCHEUUID TEXT, ZHASADJUSTMENTS INT)")
con.execute("CREATE TABLE ZADDITIONALASSETATTRIBUTES (Z_PK INTEGER PRIMARY KEY, ZASSET INT, ZORIGINALFILENAME TEXT, "
            "ZIMPORTEDBYBUNDLEIDENTIFIER TEXT)")
con.execute("CREATE TABLE ZINTERNALRESOURCE (Z_PK INTEGER PRIMARY KEY, ZASSET INT, ZLOCALAVAILABILITY INT, "
            "ZRESOURCETYPE INT, ZVERSION INT)")
con.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INT, ZTRASHEDSTATE INT)")
con.execute("INSERT INTO ZGENERICALBUM VALUES (10, 'Garden', 2, 0)")
con.execute("CREATE TABLE Z_28ASSETS (Z_28ALBUMS INT, Z_3ASSETS INT, Z_FOK_3ASSETS INT)")
pk = 0
for name, data, when, o in seeded:
    pk += 1
    con.execute("INSERT INTO ZASSET VALUES (?,?,?,?,?,0,?,?,?,?,?,?,?,?)",
                (pk, "DCIM/100APPLE", name, o.get("fav", 0), o.get("hidden", 0), o.get("kind", 0), o.get("sub", 0),
                 apple(when), 51.5 if name == "IMG_2001.JPG" else None, -0.1 if name == "IMG_2001.JPG" else None,
                 o.get("dur"), o.get("burst"), o.get("adj", 0)))
    con.execute("INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (?,?,?,?)", (pk, pk, name, o.get("by")))
    con.execute("INSERT INTO ZINTERNALRESOURCE VALUES (?,?,?,0,0)", (pk, pk, o.get("local", 1)))
    if o.get("album"):
        con.execute("INSERT INTO Z_28ASSETS VALUES (10, ?, 0)", (pk,))
con.commit()
con.close()
add("Media/PhotoData/Photos.sqlite", lib_path.read_bytes(), NOW)
man.commit()
man.close()

# -- each card finds what was seeded and nothing else -----------------------------------------------------------------
reader = wv.BackupReader(bk, None, lambda m: None)
src = ph.BackupPhotoSource(reader, W / "cache")
items = src.items()
phone = W / "backups" / "00008110-FAKE"
phone.mkdir(parents=True)
cl.LARGE_VIDEO = 2 * MB                     # the fixture's videos are small; the rule is the same
r = cl.analyse(src, items, phone, now=NOW)
names = {i.id: i.name for i in items}


def found(key):
    return sorted(names[i.id] for i in r.card(key).candidates())


expect = {
    "duplicates": ["IMG_2002.JPG", "IMG_2004.JPG"],
    "similar": ["IMG_2010.JPG", "IMG_2012.JPG", "IMG_2021.JPG"],
    # and the base fixture's two photos, each a single flat colour: what a pocket shot looks like
    "poor": ["IMG_0100.JPG", "IMG_0101.JPG", "IMG_2030.JPG", "IMG_2031.JPG", "IMG_2032.JPG"],
    "screenshots": ["IMG_2040.PNG", "RPReplay_Final1700000000.MP4"],
    "videos": ["IMG_2050.MOV"],
    "chat": ["IMG_2060.JPG", "IMG_2061.JPG"],
}
for key, want in expect.items():
    check(found(key) == want, f"{r.card(key).title} finds what was seeded and nothing else: {found(key)}")

dups = r.card("duplicates").groups
g1 = next(g for g in dups if any(names[i.id] == "IMG_2001.JPG" for i in g.items))
check([names[i] for i in g1.keep] == ["IMG_2001.JPG"] and g1.ticked == {i.id for i in g1.candidates()},
      "Duplicates keeps the original (dated and located, the camera's own), the chat copy ticked to go")
g2 = next(g for g in dups if any(names[i.id] == "IMG_2003.JPG" for i in g.items))
check([names[i] for i in g2.keep] == ["IMG_2003.JPG"], "a favourite's copy goes; the favourite is the keeper")
check(not any(names[i.id] in ("IMG_2005.JPG", "IMG_2006.JPG") for g in dups for i in g.items),
      "copies that are a favourite and an album photo make no group (nothing to offer)")
run = next(g for g in r.card("similar").groups if any(names[i.id] == "IMG_2011.JPG" for i in g.items))
check([names[i] for i in run.keep] == ["IMG_2011.JPG"] and not run.ticked,
      "Similar shots keeps the sharpest of the run and ticks none (the owner ticks which go)")
check(not any(names[i.id] == "IMG_2013.JPG" for g in r.card("similar").groups for i in g.items),
      "a different scene seconds later isn't part of the run")
poor = {names[i.id]: g.notes[i.id] for g in r.card("poor").groups for i in g.items}
check(poor == {"IMG_2030.JPG": "blurry", "IMG_2031.JPG": "very dark", "IMG_2032.JPG": "overexposed",
              "IMG_0100.JPG": "almost no detail", "IMG_0101.JPG": "almost no detail"} and
      not r.card("poor").ticked(), f"Poor quality says why and leaves each to review: {poor}")
check(r.card("screenshots").ticked() == {i.id for i in r.card("screenshots").candidates()},
      "Old screenshots are ticked to go in bulk")
vid = r.card("videos").groups[0]
check(vid.notes[vid.items[0].id] == "2 min 11 s", f"Large videos show the length: {vid.notes}")
chat = {names[i.id]: g.notes[i.id] for g in r.card("chat").groups for i in g.items}
check(chat == {"IMG_2060.JPG": "saved from WhatsApp", "IMG_2061.JPG": "saved from Telegram"},
      f"Chat clutter names the app: {chat}")
offered = {names[i.id] for c in r.cards for i in c.candidates()}
check(not offered & {"IMG_2003.JPG", "IMG_2005.JPG", "IMG_2006.JPG", "IMG_2033.JPG", "IMG_2034.JPG", "IMG_2043.PNG",
                     "IMG_2051.MOV", "IMG_2062.JPG"}, "no favourite and no album photo is offered on any card")
check(not offered & {"IMG_2035.JPG", "IMG_2036.JPG"} and r.left_out == {"hidden": 1, "icloud": 1},
      f"hidden and iCloud-only photos are left out and counted: {r.left_out}")
check(not any(names[i.id].startswith("IMG_1") for c in r.cards for i in c.candidates()),
      "none of the rich fixture's ordinary photos is offered")
live = next(i for i in items if i.name == "IMG_2070.JPG")
check(live.live_video and r.space_of(live) == live.size + len(live_mov), "a Live Photo's space includes its video")
count, space = r.total(r.card("screenshots").ticked() | r.card("chat").ticked())
check(count == 4 and space == sum(r.space_of(r.items[i]) for i in r.card("screenshots").ticked()
                                  | r.card("chat").ticked()), "the totals count each item once")

# without the library's app record: small JPEGs with no camera in their details
r_noapp = cl._cards([i for i in items if not i.hidden and not i.cloud_only],
                    {i.id: {**cl.cache_load(phone / "cleanup-cache.json").get(cl.key_of(i), {}),
                            **({"cam": False} if i.name in ("IMG_2060.JPG", "IMG_2061.JPG") else {})} for i in items},
                    NOW, True, False, 30, r.space_of)
chat2 = [names[i.id] for i in r_noapp[5].candidates()]
check(sorted(chat2) == ["IMG_2060.JPG", "IMG_2061.JPG"] and "doesn't record" in r_noapp[5].note,
      f"without the library's app record, images with no camera details, and it says so: {chat2}")
check(cl.has_camera(jpeg(scene(1))) is True and cl.has_camera(jpeg(scene(1), exif=False)) is False,
      "camera details are read from the EXIF")

# second visit: everything from the cache
t0 = time.perf_counter()
r2 = cl.analyse(src, items, phone, now=NOW)
dt2 = time.perf_counter() - t0
check(r2.measured == 0 and dt2 < 2 and [found(k) for k in expect] == [sorted(names[i.id] for i in r2.card(k).candidates())
                                                                     for k in expect],
      f"a second visit measures nothing and opens in under 2 s ({dt2:.2f} s), with the same cards")

# -- every item saved is in the archive with a matching checksum ---------------------------------------------------------
archive = W / "archive"
chosen = [i for c in r.cards for i in c.candidates()] + [live]
chosen = list({i.id: i for i in chosen}.values())
res = cl.save(src, chosen, archive, phone)
check(not res.failed and len(res.saved) == len(chosen), f"all {len(chosen)} saved: failed {res.failed}")
check(all(s.checked == "checksum" for s in res.saved), "each one checked by checksum")
rec = cl.load(phone)
check(all(cl.in_archive(rec["saved"][i.id]) for i in chosen), "the record says each is in the archive, checksums matching")
lv = next(s for s in res.saved if s.item.id == live.id)
check(sorted(p.name for p, _ in lv.files) == ["IMG_2070 (edited).jpg", "IMG_2070.JPG", "IMG_2070.MOV"]
      and all(hashlib.sha256(p.read_bytes()).hexdigest() == sha for p, sha in lv.files),
      f"a Live Photo with an edit is saved whole: {[p.name for p, _ in lv.files]}")
check((archive / "2026-10" / "IMG_2070 (edited).jpg").read_bytes() == edit_jpg, "the edit's file is the edit itself")
vfile = next(s for s in res.saved if s.item.name == "IMG_2050.MOV").files[0][0]
check(vfile.parent.name == "2026-10" and abs(vfile.stat().st_mtime - dt.datetime(2026, 10, 9, 10).timestamp()) < 2,
      "saved by month, the file dated when it was taken")
res2 = cl.save(src, chosen, archive, phone)
check(len(list(archive.rglob("*.*"))) == sum(len(s.files) for s in res.saved) and not res2.failed,
      "saving again finds the same files and makes no copies")
check(cl.saved_videos(phone) == sum(p.stat().st_size for s in res.saved if s.item.video for p, _ in s.files),
      "the videos saved are counted for the Storage card")
# a file changed in the archive no longer counts as saved
bad = rec["saved"][live.id]["files"][0][0]
Path(bad).write_bytes(b"changed")
check(not cl.in_archive(cl.load(phone)["saved"][live.id]), "a file changed since is no longer counted as in the archive")
# a part that can't be read fails that item, and nothing is recorded for it
orig_read = src.read
src.read = lambda pid: None if pid.endswith("IMG_2061.JPG") else orig_read(pid)
res3 = cl.save(src, [i for i in chosen if i.name in ("IMG_2060.JPG", "IMG_2061.JPG")], W / "archive2", None)
src.read = orig_read
check([i.name for i, _ in res3.failed] == ["IMG_2061.JPG"] and [s.item.name for s in res3.saved] == ["IMG_2060.JPG"],
      "an item that can't be read is reported, the others saved")

steps = cl.removal_steps(res.verified, {i.id: c.key for c in reversed(r.cards) for i in c.candidates()})
heads = dict(steps)
check(any(h.startswith("Duplicates") and "Utilities → Duplicates → Merge" in t for h, t in steps)
      and any(h.startswith("Old screenshots") and "Media Types → Screenshots" in t for h, t in steps)
      and any(h.startswith("Poor quality") and "find them by date" in t and "Oct 2026" in t for h, t in steps),
      f"steps on the iPhone matched to each card: {list(heads)}")
check(rec.get("last") and rec["last"]["count"] == len({i.id for c in r.cards for i in c.candidates()}),
      "the last analysis's totals are kept for the Storage card")


# -- the screens -----------------------------------------------------------------------------------------------------
import storage_advice as sa
sg = sa.build(saved_videos=3 * 1000 ** 3, cleanup={"when": "2026-11-14T10:00:00", "count": 412, "space": 8_400_000_000})
check([(x.key, x.review) for x in sg] == [("cleanup", ""), ("saved_videos", "videos")]
      and sg[0].title == "Photo clean-up: about 8.4 GB" and sg[1].title == "Videos already saved on this computer: about 3 GB",
      f"the Storage card's two clean-up suggestions, with Review (H2): {[x.title for x in sg]}")
check(not sa.build(saved_videos=400 * MB, cleanup={"when": "x", "space": 300 * MB}), "under 500 MB they don't appear")
before = cl.saved_videos(phone)
big = next(i for i in items if i.name == "IMG_2050.MOV")
cl.remember(phone, r, {i.id for i in items if i.id != big.id})
check(before - cl.saved_videos(phone) == cl.load(phone)["saved"][big.id]["size"] > 0 and cl.load(phone)["saved"][big.id]["gone"],
      "a saved video no longer on the phone isn't counted as one that could go")
cl.remember(phone, r, {i.id for i in items})
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    import checkup_ui, cleanup_ui, phone as phonewin

    class Now:
        """The window's background runners, made synchronous for the test."""
        def submit(self, fn, ok=None, err=None):
            try:
                v = fn()
            except Exception as e:
                import traceback; traceback.print_exc()
                return err and err(e)
            return ok and ok(v)

        def on_ui(self, fn):                 # progress lines from the worker threads: not drawn here
            pass

    class Win(tk.Toplevel):
        def __init__(self):
            super().__init__(root)
            self.geometry("1100x800")
            self.content = tk.Frame(self)
            self.content.pack(fill="both", expand=True)
            self.backup_dir, self.udid, self.current = W / "backups", "00008110-FAKE", None
            self.backup_runner = self.live_runner = Now()
            self.view_header = lambda key, sub="": phonewin.PhoneWindow.view_header(self, key, sub)
            self.opened, self.photos_shown = [], 0

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            pass

        def v_photos(self, key, value):
            self.photos_shown += 1

        def open_app(self, key):
            self.opened.append(key)

        def failed(self, holder, e, retry=None):
            self.error = e

        def out_dir(self, key, protectable=True):
            return W / "chosen"

    def texts(w, out=None):
        out = [] if out is None else out
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                out.append(c.cget("text"))
            if isinstance(c, ui.RoundButton):
                out.append("[" + c.text + "]")
            texts(c, out)
        return out

    import ui
    shutil.rmtree(phone, ignore_errors=True)
    phone.mkdir(parents=True)
    win = Win()
    cleanup_ui.view(win, src, items)
    win.update()
    st = win.cleanup
    t1 = texts(win.content)
    check(win.current == "cleanup" and all(c in t1 for c in ("Duplicates", "Similar shots", "Poor quality",
                                                             "Old screenshots", "Large videos", "Chat clutter")),
          "Clean up opens one screen of the six cards")
    n_dup = r.card("duplicates").count
    check(any(x.startswith(f"{n_dup} items · ") for x in t1), f"each card has a count and the space it would free")
    n0, sp0 = st.totals()
    check(n0 == 6 and f"[Save to computer (6 items, {cleanup_ui.size_text(sp0)})]" in t1,
          f"the button names what's ticked: duplicates, old screenshots and chat clutter ({n0})")
    check(any(x.startswith("Left out: 1 hidden photo") and "1 only in iCloud" in x for x in t1),
          "what's left out is said")
    cleanup_ui.card_view(win, st, "duplicates")
    win.update()
    t2 = texts(win.content)
    check(win.current == "cleanup:duplicates" and sum(x.startswith("Copies: 2") for x in t2) == 2,
          "Duplicates shows its groups side by side")
    copy = next(i for i in items if i.name == "IMG_2002.JPG")
    win.cleanup_toggle(copy.id)
    check(copy.id not in st.ticked and st.totals()[0] == 5 and "[Save to computer (5 items" in " ".join(texts(win.content)),
          "one click unticks a copy, and the button follows")
    win.cleanup_toggle(copy.id)
    fav = next(i for i in items if i.name == "IMG_2003.JPG")
    win.cleanup_toggle(fav.id)
    check(fav.id not in st.ticked, "a favourite can't be ticked")
    keeper = next(i for i in items if i.name == "IMG_2001.JPG")
    win.cleanup_toggle(keeper.id)
    check(keeper.id in st.ticked, "the suggested keeper can be ticked too (every pick can be changed)")
    win.cleanup_toggle(keeper.id)
    cleanup_ui.card_view(win, st, "poor")
    win.update()
    check(not (st.ticked & {i.id for i in r.card("poor").candidates()}) and
          any(x.startswith("blurry · ") for x in texts(win.content)), "Poor quality: each says why, none ticked")
    cleanup_ui.set_days(win, st, "100")
    win.update()
    check(st.result.card("screenshots").count == 0 and "Nothing found" in texts(win.content),
          "the screenshots' age can be changed (older than 100 days: none)")
    cleanup_ui.set_days(win, st, "30")
    st.ticked |= {i.id for i in st.result.card("videos").candidates()}
    chosen_n = st.totals()[0]
    cleanup_ui.save(win, st)
    win.update()
    t3 = texts(win.content)
    check(win.current == "cleanup:done" and f"Saved {chosen_n} items to your archive." in t3,
          f"Save to computer, then the summary: {[x for x in t3 if x.startswith('Saved')]}")
    check(any(x.startswith("To free ") for x in t3) and any("Utilities → Duplicates → Merge" in x for x in t3)
          and any("Media Types → Screenshots" in x for x in t3) and ("⚠  " + cl.ICLOUD_WARNING) in t3,
          "with the steps on the iPhone for each card, and the iCloud warning (iCloud Photos is on here: a photo is "
          "only in iCloud)")
    rec = cl.load(phone)
    check(all(cl.in_archive(rec["saved"][i]) for i in st.ticked), "every item listed for removal is in the archive, "
                                                                   "checksum matching")
    checkup_ui.open_cleanup(win, "videos")
    check(win.opened == ["photos"] and win.open_cleanup == "videos", "Review on the Storage card opens Photos, then "
                                                                    "Photo clean-up on that card")
    cleanup_ui.view(win, src, items, "videos")
    win.update()
    check(win.current == "cleanup:videos" and any(x.startswith("2 min 11 s · ") for x in texts(win.content)),
          "it opens on Large videos, each with its length")
    cleanup_ui.back_to_photos(win, win.cleanup)
    check(win.photos_shown == 1, "‹ Photos goes back to the photos")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

spec_ = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"cleanup"' in spec_ and '"cleanup_ui"' in spec_, "the packaged app includes Photo clean-up")

# -- 10,000 photos in under 5 minutes; a second visit under 2 seconds ------------------------------------------------------
class Stand:
    """10,000 photos with their thumbnails, as a source would hand them over."""
    label = "a stand-in"

    def __init__(self, n):
        self.dir = W / "bench"
        self.dir.mkdir()
        thumbs = []
        for k in range(40):                              # 40 distinct thumbnails, reused
            p = self.dir / f"t{k}.jpg"
            scene(1000 + k, (320, 240)).save(p, "JPEG", quality=80)
            thumbs.append(p)
        self.thumbs = thumbs
        t = dt.datetime(2024, 1, 1)
        self.items = [ph.PhotoItem(f"DCIM/1{k // 1000:02d}APPLE/IMG_{k:05d}.JPG", f"IMG_{k:05d}.JPG",
                                   2 * MB + (k if k % 50 else k - 1), t + dt.timedelta(minutes=37 * k), False)
                      for k in range(n)]
        self.bytes = jpeg(scene(5, (400, 300)))

    def library(self):
        return None

    def thumbnail(self, i):
        return self.thumbs[int(i.name[4:9]) % 40]

    def read(self, pid):
        return self.bytes

    def part_size(self, pid):
        return 0


stand = Stand(10_000)
bench = W / "backups" / "bench"
t0 = time.perf_counter()
rb = cl.analyse(stand, stand.items, bench, now=NOW)
first = time.perf_counter() - t0
t0 = time.perf_counter()
rb2 = cl.analyse(stand, stand.items, bench, now=NOW)
second = time.perf_counter() - t0
print(f"     10,000 photos: first visit {first:.1f} s, second {second:.2f} s")
check(first < 300 and rb.measured == 10_000, f"10,000 photos analysed in under 5 minutes ({first:.0f} s)")
check(second < 2 and rb2.measured == 0, f"a second visit opens in under 2 seconds ({second:.2f} s)")

reader.close() if hasattr(reader, "close") else None
print(f"C1 TESTS: {'PASS' if not failures else 'FAIL (' + str(len(failures)) + ')'}")
sys.exit(1 if failures else 0)
