"""Owner's real-iPhone check for P1: reads the Photos library from the connected iPhone (read-only) and prints
what PhoneKeep will show, so the counts can be compared with the Photos app. Nothing is changed on the phone,
and only counts and album names are printed (no photos are copied).

    .venv/bin/python tools/check_photos.py
"""
import shutil, sys, tempfile, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phonekeep as wv
import photos as ph
import library

devs = [d for d in wv.list_devices() if d.get("ConnectionType") == "USB"]
if not devs:
    sys.exit("Plug the iPhone in with a cable and unlock it, then run this again.")
d = devs[0]
print(f"=== {d.get('DeviceName')} (cable)")
src = ph.DevicePhotoSource(d["UniqueDeviceID"], Path(tempfile.mkdtemp(prefix="pk-check-")))
try:
    db = src._library_copy()
    if db is None:
        sys.exit("  The Photos library (PhotoData/Photos.sqlite) couldn't be copied from the phone.")
    print(f"  library copied: {db.stat().st_size / 1e6:.1f} MB"
          + "".join(f", {x} {Path(str(db) + x).stat().st_size / 1e6:.1f} MB" for x in ("-wal",) if Path(str(db) + x).exists()))
    lib = library.read(db)
    if lib is None:
        sys.exit("  The library was copied but couldn't be read (unknown layout).")
    a = list(lib.assets.values())
    live = [x for x in a if not x.trashed]
    n = lambda f: sum(1 for x in live if f(x))
    rows = [("Items in the library", len(live), "Photos app → Library → All"),
            ("Favourites", n(lambda x: x.favorite), "Albums → Favourites"),
            ("Videos", n(lambda x: x.video), "Media Types → Videos"),
            ("Screenshots", n(lambda x: x.screenshot), "Media Types → Screenshots"),
            ("Live Photos", n(lambda x: x.live), "Media Types → Live Photos"),
            ("Hidden", n(lambda x: x.hidden), "Utilities → Hidden"),
            ("Recently Deleted (left out)", sum(1 for x in a if x.trashed), "Utilities → Recently Deleted")]
    for k, v, where in rows:
        print(f"  {k:<28} {v:>7}   compare: {where}")
    print(f"  Albums ({len(lib.albums)}):")
    for _key, title, count in lib.albums:
        print(f"     {title:<32} {count:>6}")
except Exception:
    traceback.print_exc()
finally:
    src.close()
    shutil.rmtree(src.cache, ignore_errors=True)    # the library copied off the phone
