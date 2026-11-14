"""P1: Photos (docs/spec/07-photos-media.md#p1-photos).

Done when:
- "Albums and favourites match the phone."  → a Photos.sqlite like the phone's (both the iOS 14+ ZASSET layout and the
  older ZGENERICASSET one, with the album link table's numbered names) gives the right favourites, albums with their
  photos, videos, screenshots, Live Photos, hidden and deleted items; the photo list shows them as collections.
  (On the owner's Mac: compare with the Photos app.)
- "A saved JPG shows the original date and location."  → a HEIC with its own date and GPS, and one without (filled
  from the library), saved as "Most compatible": the JPG carries DateTimeOriginal and GPS, and the file's date is
  the date taken. A Live Photo saves as the photo plus its short video with the same name.
Also: Hidden stays closed until confirmed (Touch ID / the computer's password when the app lock is on).
"""
import datetime as dt, os, shutil, sqlite3, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import library
import photoconv
import photos as ph

W = HERE / "work" / "p1"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


def apple(t: dt.datetime) -> float:
    return (t - library.APPLE_EPOCH).total_seconds()


T0 = dt.datetime(2025, 6, 14, 18, 30, 5)
# (dir, file, fav, hidden, trashed, kind, subtype, lat, lon)
ASSETS = [
    ("DCIM/100APPLE", "IMG_0001.HEIC", 1, 0, 0, 0, 2, 48.8566, 2.3522),      # favourite Live Photo in Paris
    ("DCIM/100APPLE", "IMG_0002.PNG", 0, 0, 0, 0, 10, -180, -180),           # screenshot, no location
    ("DCIM/100APPLE", "IMG_0003.MOV", 0, 0, 0, 1, 0, 0, 0),                  # video
    ("DCIM/100APPLE", "IMG_0004.HEIC", 0, 1, 0, 0, 0, 51.5, -0.12),          # hidden
    ("DCIM/100APPLE", "IMG_0005.JPG", 0, 0, 1, 0, 0, 0, 0),                  # in Recently Deleted
    ("DCIM/100APPLE", "IMG_0006.JPG", 1, 0, 0, 0, 0, 0, 0),                  # favourite, in an album
    # iCloud Photos keeps photos from other devices in PhotoData/CPLAssets, not DCIM (found on the owner's phone)
    ("PhotoData/CPLAssets/group338", "2DA16694-AAAA.HEIC", 1, 0, 0, 0, 0, 0, 0),   # favourite, from iCloud
    ("PhotoData/CPLAssets/group12", "7F00AA11-BBBB.HEIC", 0, 1, 0, 0, 0, 0, 0),    # hidden, from iCloud
    ("PhotoData/CPLAssets/group5", "99CC0000-CCCC.HEIC", 0, 0, 0, 0, 0, 0, 0),     # only in iCloud (Optimise)
    ("DCIM/101APPLE", "IMG_0909.HEIC", 1, 0, 0, 0, 0, 0, 0),                        # DCIM path, file not on the phone
]


def make_db(path: Path, new_layout: bool):
    con = sqlite3.connect(path)
    at = "ZASSET" if new_layout else "ZGENERICASSET"
    con.execute(f"CREATE TABLE {at} (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, ZFAVORITE INT, "
                "ZHIDDEN INT, ZTRASHEDSTATE INT, ZKIND INT, ZKINDSUBTYPE INT, ZDATECREATED REAL, ZLATITUDE REAL, "
                "ZLONGITUDE REAL)")
    for n, (d, f, fav, hid, tr, kind, sub, lat, lon) in enumerate(ASSETS, 1):
        con.execute(f"INSERT INTO {at} VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (n, d, f, fav, hid, tr, kind, sub, apple(T0 + dt.timedelta(days=n)), lat, lon))
    con.execute("CREATE TABLE ZADDITIONALASSETATTRIBUTES (Z_PK INTEGER PRIMARY KEY, ZASSET INT, ZORIGINALFILENAME TEXT)")
    con.executemany("INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (?,?,?)", [(1, 7, "IMG_5001.HEIC"), (2, 8, "IMG_5002.HEIC")])
    con.execute("CREATE TABLE ZINTERNALRESOURCE (Z_PK INTEGER PRIMARY KEY, ZASSET INT, ZLOCALAVAILABILITY INT, "
                "ZRESOURCETYPE INT, ZVERSION INT)")
    con.executemany("INSERT INTO ZINTERNALRESOURCE VALUES (?,?,?,?,?)",
                    [(1, 7, 1, 0, 0), (2, 8, 1, 0, 0), (3, 9, -1, 0, 0), (4, 9, 1, 0, 2)])   # 9: only a small version here
    con.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INT, ZTRASHEDSTATE INT)")
    con.executemany("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?)",
                    [(10, "Holidays", 2, 0), (11, "Recents", 1505, 0), (12, "Old", 2, 1), (13, "Family", 2, 0)])
    link, a_col, s_col = ("Z_28ASSETS", "Z_28ALBUMS", "Z_3ASSETS") if new_layout else ("Z_26ASSETS", "Z_26ALBUMS", "Z_34ASSETS")
    con.execute(f"CREATE TABLE {link} ({a_col} INT, {s_col} INT, Z_FOK_{s_col[2:]} INT)")
    con.executemany(f"INSERT INTO {link} VALUES (?,?,0)", [(10, 1), (10, 6), (13, 6), (13, 4), (12, 2)])
    con.commit()
    con.close()


for new in (True, False):
    db = W / f"Photos-{'new' if new else 'old'}.sqlite"
    make_db(db, new)
    lib = library.read(db)
    tag = "iOS 14+" if new else "iOS 13"
    a1, a2, a3, a4 = (lib.get(f"DCIM/100APPLE/IMG_000{n}.{e}") for n, e in ((1, "HEIC"), (2, "PNG"), (3, "MOV"), (4, "HEIC")))
    check(a1.favorite and a1.live and a1.lat == 48.8566 and a1.taken == T0 + dt.timedelta(days=1),
          f"{tag}: favourite, Live Photo, location and date taken")
    check(a2.screenshot and a2.lat is None and a3.video and a4.hidden and lib.get("DCIM/100APPLE/IMG_0005.JPG").trashed,
          f"{tag}: screenshot (no location), video, hidden, deleted")
    check([(t, n) for _k, t, n in lib.albums] == [("Holidays", 2), ("Family", 1)],
          f"{tag}: the user's albums with their counts (not system or deleted ones; hidden photos not counted): {lib.albums}")
check(library.read(W / "nothing.sqlite") is None, "a missing or unreadable library gives nothing (never guesses)")

# -- applied to the photo list: deleted left out, collections ---------------------------------------------------
lib = library.read(W / "Photos-new.sqlite")
items = [ph.PhotoItem(f"DCIM/100APPLE/{f}", f, 1000, dt.datetime(2026, 1, 1), f.endswith(".MOV")) for d, f, *_ in ASSETS
         if d == "DCIM/100APPLE"]
items.append(ph.PhotoItem("DCIM/100APPLE/IMG_0001.MOV", "IMG_0001.MOV", 900, dt.datetime(2026, 1, 1), True))
items = ph._apply_library(ph._pair_live_photos(items), lib)
ids = {i.name: i for i in items}
check("IMG_0005.JPG" not in ids and ids["IMG_0001.HEIC"].live_video and ids["IMG_0001.HEIC"].when == T0 + dt.timedelta(days=1),
      "deleted items are left out; the Live Photo keeps its video; dates come from the library")
cpl = {i.id: i for i in items if i.id.startswith("PhotoData/")}
check({"PhotoData/CPLAssets/group338/2DA16694-AAAA.HEIC", "PhotoData/CPLAssets/group12/7F00AA11-BBBB.HEIC"} <= set(cpl)
      and cpl["PhotoData/CPLAssets/group338/2DA16694-AAAA.HEIC"].favorite
      and cpl["PhotoData/CPLAssets/group12/7F00AA11-BBBB.HEIC"].hidden,
      "photos kept in iCloud's folder on the phone (not DCIM) are listed too, with favourite and hidden")
check({"IMG_5001.HEIC", "IMG_5002.HEIC"} <= {i.name for i in cpl.values()},
      "under the name they were taken with")
_ids = {i.id: i for i in items}
check(_ids["DCIM/101APPLE/IMG_0909.HEIC"].cloud_only and _ids["PhotoData/CPLAssets/group5/99CC0000-CCCC.HEIC"].cloud_only
      and not _ids["DCIM/100APPLE/IMG_0001.HEIC"].cloud_only,
      "only in iCloud: the library says the original isn't on the phone, or its file isn't there")

# straight from the iPhone: a photo the library calls local is looked for; a missing file is iCloud-only
import asyncio, threading


class _Afc:
    async def stat(self, p):
        if p.endswith("BBBB.HEIC"):
            raise FileNotFoundError(p)
        return {"st_size": 1234}


_d = ph.DevicePhotoSource.__new__(ph.DevicePhotoSource)
ph.PhotoSource.__init__(_d, W / "dev-cache")
_d.loop = asyncio.new_event_loop()
threading.Thread(target=_d.loop.run_forever, daemon=True).start()
_d.afc, _d._sizes, _d._library = _Afc(), {}, lib


async def _no_dcim():
    return []
_d._items = _no_dcim
_dev = {i.id: i for i in _d.items()}
check(not _dev["PhotoData/CPLAssets/group338/2DA16694-AAAA.HEIC"].cloud_only
      and _dev["PhotoData/CPLAssets/group338/2DA16694-AAAA.HEIC"].size == 1234
      and _dev["PhotoData/CPLAssets/group12/7F00AA11-BBBB.HEIC"].cloud_only,
      "on the iPhone, each photo the library calls local is looked for; one whose file is missing is iCloud-only")
_d.loop.call_soon_threadsafe(_d.loop.stop)
_back = ph._apply_library([], lib, has_file=lambda k: k.endswith("AAAA.HEIC"))
check([i.id for i in _back if not i.cloud_only] == ["PhotoData/CPLAssets/group338/2DA16694-AAAA.HEIC"],
      "from a backup, only those whose file is in the backup can be saved; the rest are marked iCloud-only")

try:
    import tkinter as tk
    import ui
    root = tk.Tk()
    root.geometry("1000x700")

    class Src:
        label = "the iPhone"

        def library(self):
            return lib

        def thumbnail(self, item):
            return None
    asked = []
    pp = ui.PhotoPanel(root, Src(), items, unlock=lambda go: asked.append(go))
    pp.pack(fill="both", expand=True)
    root.update()
    label = lambda r: pp.mlist.item(r, "values")[0].strip().lstrip("☐☑◪").strip()
    rows = {r: label(r) for r in pp.mlist.get_children("")}
    check(list(rows)[:4] == ["c:fav", "c:videos", "c:shots", "c:live"] and rows["c:fav"] == "★ Favourites",
          f"the list starts with Favourites, Videos, Screenshots, Live Photos: {list(rows.values())[:4]}")
    albums = [label(r) for r in pp.mlist.get_children("head-albums")]
    check(albums == ["Holidays", "Family"] or albums == ["Holidays"],
          f"then Albums, with the user's albums: {albums}")
    _cl = [i for i in pp.items if i.cloud_only]
    pp._toggle(_cl[0]); pp._set_all(True)
    check(_cl and not any(i.id in pp.selected for i in _cl) and "2 only in iCloud" in pp.count.cget("text"),
          f"iCloud-only photos can't be selected, and the count says how many: {pp.count.cget('text')!r}")
    pp._set_all(False)
    check(len(pp.months["c:fav"]) == 4 and pp.mlist.item("c:fav", "values")[1].endswith("/4") and {i.name for i in pp.months["album:10"]} == {"IMG_0001.HEIC", "IMG_0006.JPG"},
          "favourites and an album hold the right photos")
    check("c:hidden" in rows and "🔒" in pp.mlist.item("c:hidden", "values")[0] and pp.mlist.item("c:hidden", "values")[1] == "",
          "Hidden is listed, locked, without its count")
    check(not any(i.hidden for i in pp.items) and "IMG_0004.HEIC" not in {i.name for i in pp.months["album:13"]},
          "hidden photos aren't in the library, collections or albums")
    pp._set_all(False); pp._flip_all(); root.update()
    check(pp.selected and not any(i.hidden for i in items if i.id in pp.selected),
          "Select all doesn't select hidden photos while Hidden is closed")
    pp.mlist.selection_set("c:hidden"); root.update()
    check(len(asked) == 1 and not pp.hidden_open and pp._month() is None, "opening Hidden asks first; nothing shown yet")
    asked[0](); root.update()
    check(pp.hidden_open and pp._month() == "c:hidden" and {i.name for i in pp.months["c:hidden"]} == {"IMG_0004.HEIC", "IMG_5002.HEIC"},
          "once confirmed, Hidden shows its photos")
    pp.destroy()
    # the dialog for the save format
    d_res = {}

    def answer():
        d = [w for w in root.winfo_children() if isinstance(w, ui.ChoiceDialog)][0]
        d.var.set(1); d._ok()
    root.after(300, answer)
    check(ui.ask_photo_format(root) is True, "Save asks 'Original (HEIC) / Most compatible (JPG)'")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

# -- Most compatible: HEIC → JPG with date and location ---------------------------------------------------------
from PIL import Image
import pillow_heif
pillow_heif.register_heif_opener()


class FileSrc:
    def __init__(self, files):
        self.files = files

    def copy(self, item_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.files[item_id], dest)
        return True


shot = dt.datetime(2024, 8, 3, 9, 15, 0)
heic_with = W / "src" / "IMG_0101.HEIC"
heic_with.parent.mkdir(parents=True)
ex = Image.Exif()
ex.get_ifd(photoconv.EXIF_IFD)[photoconv.DATETIME_ORIGINAL] = "2024:08:03 09:15:00"
ex.get_ifd(photoconv.GPS_IFD).update({1: "N", 2: (40.0, 25.0, 0.0), 3: "W", 4: (3.0, 42.0, 0.0)})
Image.new("RGB", (80, 60), (30, 120, 200)).save(heic_with, exif=ex.tobytes())
heic_without = W / "src" / "IMG_0102.HEIC"
Image.new("RGB", (80, 60), (200, 120, 30)).save(heic_without)
mov = W / "src" / "IMG_0102.MOV"
mov.write_bytes(b"\0\0\0\x14ftypqt  fake movie")
src = FileSrc({"DCIM/IMG_0101.HEIC": heic_with, "DCIM/IMG_0102.HEIC": heic_without, "DCIM/IMG_0102.MOV": mov})
i1 = ph.PhotoItem("DCIM/IMG_0101.HEIC", "IMG_0101.HEIC", 1, shot, False)
i2 = ph.PhotoItem("DCIM/IMG_0102.HEIC", "IMG_0102.HEIC", 1, shot + dt.timedelta(hours=1), False,
                  live_video="DCIM/IMG_0102.MOV", lat=-33.8688, lon=151.2093)
out_dir, tmp = W / "out", W / "tmp"
saved = photoconv.save_item(src, i1, out_dir, True, tmp) + photoconv.save_item(src, i2, out_dir, True, tmp)
names = sorted(p.name for p in saved)
check(names == ["IMG_0101.JPG", "IMG_0102.JPG", "IMG_0102.MOV"],
      f"Most compatible: HEIC saved as JPG; the Live Photo's video beside it, same name: {names}")
for p, when, lat_ref in ((out_dir / "IMG_0101.JPG", shot, "N"), (out_dir / "IMG_0102.JPG", shot + dt.timedelta(hours=1), "S")):
    with Image.open(p) as im:
        fmt = im.format
        e = im.getexif()
        dto = e.get_ifd(photoconv.EXIF_IFD).get(photoconv.DATETIME_ORIGINAL)
        gps = e.get_ifd(photoconv.GPS_IFD)
    check(fmt == "JPEG" and dto == when.strftime("%Y:%m:%d %H:%M:%S") and gps.get(1) == lat_ref and gps.get(2),
          f"{p.name}: a real JPG with the date taken ({dto}) and the location ({gps.get(1)})")
    check(abs(p.stat().st_mtime - when.timestamp()) < 2, f"{p.name}: the file's date is the date taken")
orig = photoconv.save_item(src, i1, W / "orig", False, tmp)
check([p.name for p in orig] == ["IMG_0101.HEIC"] and abs(orig[0].stat().st_mtime - shot.timestamp()) < 2,
      "Original keeps the HEIC (with the file date set to the date taken)")

src_txt = (HERE.parent / "phone.py").read_text(encoding="utf-8")
check("ask_photo_format" in src_txt and "photoconv.save_item" in src_txt, "the iPhone window's Save asks the format and uses it")

# two different photos with the same name don't overwrite each other; saving the same one again makes no copy
import photoconv as pc
_f = W / "names"
shutil.rmtree(_f, ignore_errors=True); _f.mkdir()
(_f / "IMG_0001.JPG").write_bytes(b"x" * 10)
pc.set_file_date(_f / "IMG_0001.JPG", dt.datetime(2025, 1, 1, 12))
check(pc.free_name(_f, "IMG_0001.JPG", 99, dt.datetime(2024, 5, 5)) == "IMG_0001 (2).JPG",
      "a different photo with the same name is saved as 'IMG_0001 (2).JPG'")
check(pc.free_name(_f, "IMG_0001.JPG", 10) == "IMG_0001.JPG" and
      pc.free_name(_f, "IMG_0001.JPG", 0, dt.datetime(2025, 1, 1, 12)) == "IMG_0001.JPG",
      "the same photo saved again keeps its name (no copies)")

print("\nP1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
