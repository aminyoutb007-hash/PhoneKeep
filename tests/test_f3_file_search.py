"""F3: file search in App Files (on the phone) and All files (in the backup).

The pattern: a name or part of one, * for anything, ? for one character, a / to match the path; case and
accents don't matter. All files on the invented FULLTEST backup: "*.jpg" lists every JPEG the backup has (the
count worked out from the backup on its own) with its area, path, size and date; a newer search replaces an older
one; a file found opens in the preview and is saved; clearing the box shows the folders again. App Files on a
simulated iPhone: "*.pdf" finds the PDFs in every app that shares files (in folders inside folders too), says
which app couldn't be read, and a result opens and is saved into its own app's folder. Read-only on the phone.
"""
import datetime as dt, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
os.environ["PHONEKEEP_NO_HELPER"] = "1"

W = HERE / "work"
UDID = "00008030-FULLTEST"
BACKUPS = W / "Backups"
if not (BACKUPS / UDID / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

import tkinter as tk
import device as devmod
import filesearch
import keychain
import phone
import photos as ph
import phonekeep as wv
import quicklook as ql

keychain.use_memory()
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


# -- the pattern ----------------------------------------------------------------------------------------------
P = filesearch.Pattern
check(P("*.pdf").match("Invoice March.PDF") and not P("*.pdf").match("invoice.pdf.txt"),
      "*.pdf: every name ending in .pdf, upper or lower case")
check(P("invoice*").match("Invoice 2026.pdf") and not P("invoice*").match("My invoice.pdf"),
      "invoice*: names that start with it")
check(P("invoice").match("My Invoice.pdf") and P("cafe").match("Café menu.pdf"),
      "a word alone: anywhere in the name, accents don't matter")
check(P("IMG_00??.JPG").match("img_0012.jpg") and not P("IMG_00??.JPG").match("IMG_001.JPG"),
      "? is one character")
check(P("*/Scans/*.pdf").match("a.pdf", "Documents/Scans/a.pdf") and not P("*/Scans/*.pdf").match("a.pdf", "Documents/a.pdf"),
      "a pattern with a / is matched against the path")
check(not P("") and not P("*") and not P(" ** "), "an empty search, or * alone, isn't a search (it would list everything)")

# -- the simulated iPhone ---------------------------------------------------------------------------------------
E = devmod.Entry
T = dt.datetime(2026, 3, 4, 10, 30)
FILES = {
    "com.apple.Pages": [E("Letters", "Documents/Letters", True), E("Invoice March.pdf", "Documents/Letters/Invoice March.pdf", False, 120_000, T),
                        E("Scans", "Documents/Letters/Scans", True), E("scan 1.PDF", "Documents/Letters/Scans/scan 1.PDF", False, 900_000, T),
                        E("notes.txt", "Documents/notes.txt", False, 400, T)],
    "org.videolan.vlc-ios": [E("clip.mp4", "Documents/clip.mp4", False, 48_000_000, T), E("Invoice.pdf", "Documents/Invoice.pdf", False, 50_000, T)],
}


class SimulatedDevice:
    def __init__(self, udid, cache_dir=None):
        self.udid, self.calls = udid, []

    def wallpaper(self, which="homescreen"):
        return None

    def music(self):
        return []

    def books(self):
        return []

    def apps(self):
        return [devmod.AppInfo("org.videolan.vlc-ios", "VLC", "3.5", True),
                devmod.AppInfo("com.apple.Pages", "Pages", "14.0", True),
                devmod.AppInfo("com.example.locked", "Locked Notes", "1.0", True),
                devmod.AppInfo("com.spotify.client", "Spotify", "8.9", False)]

    def app_list(self, bundle_id, path="Documents"):
        return [e for e in FILES.get(bundle_id, []) if e.path.rsplit("/", 1)[0] == path]

    def app_walk(self, bundle_id, limit=20000, stop=None):
        self.calls.append(("app_walk", bundle_id))
        if bundle_id == "com.example.locked":
            raise wv.PhoneKeepError("The app didn't answer.")
        if bundle_id not in FILES:
            raise AssertionError(f"walked an app that doesn't share files: {bundle_id}")
        return list(FILES[bundle_id])

    def app_pull(self, bundle_id, path, dest_dir):
        self.calls.append(("app_pull", bundle_id, path))
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        (Path(dest_dir) / Path(path).name).write_bytes(f"{bundle_id}:{path}".encode())
        return True

    def close(self):
        pass


class NoDevicePhotos:
    def __init__(self, udid, cache_dir):
        raise wv.PhoneKeepError("not simulated")


devmod.LiveDevice = SimulatedDevice
wv.device_overview = lambda udid=None, apps=True, **k: None
ph.DevicePhotoSource = NoDevicePhotos


class FakeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(BACKUPS), "archive_dir": str(W / "Archive-f3")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass


def pump(until, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


app = FakeApp()
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone"}, UDID)
check(pump(lambda: win.data is not None and win.live is not None, 90), "the window opens on the invented backup and the simulated iPhone")
OUT = W / "f3-saved"
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)
phone.ask_save_folder = lambda parent, title, start: str(OUT)
opened = []
phone.open_file = lambda p: opened.append(Path(p))

# -- All files: the backup ------------------------------------------------------------------------------------
win.open_app("allfiles")
check(pump(lambda: getattr(win, "allfiles_hits", None) is not None and getattr(win, "allfiles_search", None), 60),
      "All files opens")
reader = win.data.reader
want = sorted((d, rel) for d in reader.domains("%") for rel in reader.file_meta(d)
              if rel.lower().endswith(".jpg"))                 # worked out from the backup on its own
hits = win.allfiles_hits


class _Box:                                   # the search box, through its text
    def delete(self, *a):
        win.allfiles_q.set("")

    def insert(self, _i, text):
        win.allfiles_q.set(text)


entry = _Box()
entry.delete(0, "end")
entry.insert(0, "*.JPG")
win.allfiles_search()
check(pump(lambda: hits.winfo_manager() and len(hits.get_children()) > 0, 60) and want,
      f"*.JPG in All files ... ({len(want)} JPEGs in the backup)")
rows = [hits.item(i, "values") for i in hits.get_children()]
check(sorted(r[1] for r in rows) == sorted(rel for _d, rel in want) and all(r[0] and r[2] and r[3] is not None for r in rows),
      f"  lists every JPEG the backup has, with its area, path, size and date ({len(rows)} of {len(want)})")
entry.delete(0, "end")
entry.insert(0, "no-such-file-anywhere*")
win.allfiles_search()
check(pump(lambda: not hits.get_children(), 30), "a newer search replaces the results (none for a name that isn't there)")
entry.delete(0, "end")
entry.insert(0, "*.jpg")
win.allfiles_search()
pump(lambda: len(hits.get_children()) == len(want), 60)
first = hits.get_children()[0]
hits.selection_set(first)
hits.focus(first)
win.allfiles_preview()
v = ql.Viewer.current
check(v is not None and v.name_lbl.cget("text") == Path(hits.item(first, "values")[1]).name,
      "a file found opens in the preview")
v.close()
before = set(OUT.rglob("*"))
hits.selection_set(first)
save_btn = None
for w in win.content.winfo_children():
    for c in w.winfo_children():
        if getattr(c, "text", None) == "Save selected":
            save_btn = c
save_btn.command()
check(pump(lambda: any(p.is_file() for p in set(OUT.rglob("*")) - before), 30)
      and any(p.name == Path(hits.item(first, "values")[1]).name for p in OUT.rglob("*")),
      "Save selected saves the file found")
entry.delete(0, "end")
win.allfiles_search()
check(pump(lambda: not hits.winfo_manager(), 10), "clearing the box shows the folders again")

# -- App Files: the phone ---------------------------------------------------------------------------------------
win.open_app("files")
check(pump(lambda: getattr(win, "files_search", None) is not None and hasattr(win.live, "calls"), 60), "App Files opens")
fq, find = win.files_search
fq.set("*.pdf")
find()


def all_widgets(w):
    out = [w]
    for c in w.winfo_children():
        out += all_widgets(c)
    return out


trees = [w for w in all_widgets(win.content) if w.winfo_class() == "Treeview" and "s" in w.cget("columns")]
ft = trees[0] if trees else None
check(ft is not None and pump(lambda: any("Invoice" in str(ft.item(i, "values")[0]) for i in ft.get_children()), 30),
      "*.pdf in App Files ...")
names = sorted(str(ft.item(i, "values")[0]) for i in ft.get_children())
check(names == ["📄 Pages  ›  Letters/Invoice March.pdf", "📄 Pages  ›  Letters/Scans/scan 1.PDF", "📄 VLC  ›  Invoice.pdf"],
      f"  finds the PDFs in every app that shares files, in folders inside folders too ({names})")
walked = [c[1] for c in win.live.calls if c[0] == "app_walk"]
crumb = [w for w in all_widgets(win.content) if w.winfo_class() == "Label" and "match" in str(w.cget("text"))]
check("com.spotify.client" not in walked and crumb and "Locked Notes" in crumb[0].cget("text")
      and "3 files match" in crumb[0].cget("text"),
      f"  only apps that share files are read, and one that couldn't be is named ({crumb[0].cget('text') if crumb else ''})")
vlc = next(i for i in ft.get_children() if "VLC" in str(ft.item(i, "values")[0]))
ft.selection_set(vlc)
ft.focus(vlc)
win.files_open()
check(pump(lambda: opened and opened[-1].read_bytes() == b"org.videolan.vlc-ios:Documents/Invoice.pdf", 15),
      "a result opens from its own app")
ft.selection_set(*ft.get_children())
for w in all_widgets(win.content):
    if getattr(w, "text", None) == "Save selected":
        w.command()
check(pump(lambda: (OUT / "VLC" / "Invoice.pdf").exists() and (OUT / "Pages" / "scan 1.PDF").exists(), 30)
      and (OUT / "Pages" / "Invoice March.pdf").read_bytes() == b"com.apple.Pages:Documents/Letters/Invoice March.pdf",
      "Save selected saves each result into its own app's folder")
check(not [c for c in win.live.calls if c[0] not in ("app_walk", "app_pull")],
      "the phone is only read (its apps' files listed and copied)")

win.destroy()
app.destroy()
print("\nF3 TESTS:", "FAIL" if failures else "PASS", flush=True)
os._exit(1 if failures else 0)
