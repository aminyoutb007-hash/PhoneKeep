"""P1 diagnosis (read-only): which of the phone's user albums the Photos app shows. Prints, for every album,
the library columns that differ between albums, so the ones Photos hides can be told apart. Album titles only;
no photos are copied.

    .venv/bin/python tools/check_albums.py
"""
import sqlite3, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phonekeep as wv
import photos as ph

d = next((d for d in wv.list_devices() if d.get("ConnectionType") == "USB"), None)
if d is None:
    sys.exit("Plug the iPhone in with a cable and unlock it, then run this again.")
src = ph.DevicePhotoSource(d["UniqueDeviceID"], Path(tempfile.mkdtemp(prefix="pk-check-")))
print("reading the Photos library from the iPhone (about a minute)…", flush=True)
try:
    db = src._library_copy()
finally:
    src.close()
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cols = [r[1] for r in con.execute('PRAGMA table_info("ZGENERICALBUM")')]
rows = [dict(zip(cols, r)) for r in con.execute("SELECT * FROM ZGENERICALBUM WHERE ZKIND = 2 AND ZTITLE IS NOT NULL")]
pks = {r[0]: r for r in con.execute("SELECT Z_PK, ZKIND, ZTITLE FROM ZGENERICALBUM")}
skip = {"Z_PK", "Z_OPT", "ZTITLE", "ZUUID", "ZCLOUDGUID", "ZCREATIONDATE", "ZSTARTDATE", "ZENDDATE", "ZKEYASSET",
        "ZSECONDARYKEYASSET", "ZTERTIARYKEYASSET", "ZCUSTOMKEYASSET", "ZCACHEDCOUNT", "ZCACHEDPHOTOSCOUNT",
        "ZCACHEDVIDEOSCOUNT", "ZLASTMODIFIEDDATE", "ZCLOUDCREATIONDATE", "ZCLOUDLASTINTERESTINGCHANGEDATE"}
vary = [c for c in cols if c not in skip and len({repr(r[c])[:40] for r in rows}) > 1
        and not isinstance(rows[0][c], bytes)]
print("columns that differ:", ", ".join(vary))
for r in rows:
    parent = r.get("ZPARENTFOLDER")
    pk = f"parent kind {pks[parent][1]}" if parent in pks else "no parent"
    print(f"- {str(r['ZTITLE'])[:28]:<28} {pk:<16} " + " ".join(f"{c[1:]}={r[c]}" for c in vary if c != "ZPARENTFOLDER"))
