"""Diagnosis (read-only): which photos are really on the iPhone. Checks 300 photos from the library against the
phone's own files and compares with what the library says, then prints only counts. Nothing is copied or changed.

    .venv/bin/python tools/check_icloud.py
"""
import random, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phonekeep as wv
import photos as ph
import library

d = next((d for d in wv.list_devices() if d.get("ConnectionType") == "USB"), None)
if d is None:
    sys.exit("Plug the iPhone in with a cable and unlock it, then run this again.")
print("reading the Photos library from the iPhone (about a minute)…", flush=True)
src = ph.DevicePhotoSource(d["UniqueDeviceID"], Path(tempfile.mkdtemp(prefix="pk-check-")))
try:
    lib = library.read(src._library_copy())
    keys = [k for k, a in lib.assets.items() if not a.trashed and k.startswith("PhotoData/")]
    random.seed(1)
    sample = random.sample(keys, min(300, len(keys)))
    table = {}
    for k in sample:
        try:
            src._run(ph._aw(src.afc.stat(k)), timeout=30)
            there = True
        except Exception:
            there = False
        says = lib.assets[k].local
        table[(there, says)] = table.get((there, says), 0) + 1
    print(f"{len(keys):,} library items outside DCIM; checked {len(sample)}:")
    for (there, says), n in sorted(table.items(), key=str):
        print(f"  file on the phone: {'yes' if there else 'no ':<3}  library says local: {str(says):<5}  → {n}")
finally:
    src.close()
