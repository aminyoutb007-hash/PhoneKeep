"""P1 diagnosis (read-only): which of the phone's albums and hidden photos the Photos app shows.

Copies the iPhone's Photos library database (no photos) and writes a report of the albums' settings and the
hidden-photo flags to tests/work/albums-report.json, on this computer only. Nothing is changed on the phone.

    .venv/bin/python tools/check_albums.py
"""
import json, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import phonekeep as wv
import photos as ph

d = next((d for d in wv.list_devices() if d.get("ConnectionType") == "USB"), None)
if d is None:
    sys.exit("Plug the iPhone in with a cable and unlock it, then run this again.")
print("reading the Photos library from the iPhone (about a minute)…", flush=True)
src = ph.DevicePhotoSource(d["UniqueDeviceID"], Path(tempfile.mkdtemp(prefix="pk-check-")))
try:
    db = src._library_copy()
finally:
    src.close()
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def table(name, where=""):
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{name}")')]
    out = []
    for r in con.execute(f'SELECT * FROM "{name}" {where}'):
        out.append({c: v for c, v in zip(cols, r) if not isinstance(v, bytes) and v is not None})
    return cols, out


report = {}
_c, albums = table("ZGENERICALBUM")
report["album_kinds"] = sorted({(a.get("ZKIND"), a.get("ZTITLE") if a.get("ZKIND") != 2 else "") for a in albums},
                               key=lambda x: (x[0] or 0, str(x[1])))
report["user_albums"] = [a for a in albums if a.get("ZKIND") == 2]
report["folders"] = [a for a in albums if a.get("ZKIND") in (4000, 3999)]
acols = [r[1] for r in con.execute('PRAGMA table_info("ZASSET")')]
report["asset_columns"] = acols
flags = {}
for col in ("ZHIDDEN", "ZTRASHEDSTATE", "ZVISIBILITYSTATE", "ZAVALANCHEPICKTYPE", "ZSAVEDASSETTYPE",
            "ZCLOUDLOCALSTATE", "ZSYNDICATIONSTATE", "ZACTIVELIBRARYSCOPEPARTICIPATIONSTATE", "ZBUNDLESCOPE"):
    if col in acols:
        flags[col] = dict(con.execute(f"SELECT COALESCE({col}, -1), COUNT(*) FROM ZASSET GROUP BY 1").fetchall())
report["asset_flags"] = flags
report["hidden_files_sample"] = [r for r in con.execute(
    "SELECT ZDIRECTORY, ZFILENAME FROM ZASSET WHERE ZHIDDEN = 1 LIMIT 5")] if "ZHIDDEN" in acols else []
out = ROOT / "tests" / "work" / "albums-report.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
print(f"report written ({len(report['user_albums'])} albums). Hidden flag counts: {flags.get('ZHIDDEN')}")
