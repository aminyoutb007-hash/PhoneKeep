"""Q1: quick preview everywhere (docs/spec/11-previews.md#q1-quick-preview-everywhere).

Done when "Space previews every kind of item listed above on Mac and Windows". Checked here with stand-in items:
- photo (HEIC too), text, PDF, video, audio, other: Space opens a large preview over the window; the arrows move
  to the next / previous item; Space or Esc closes it.
- images and text are shown from memory: nothing is written to disk for them.
- video and audio are copied to a private folder (only the user can read it), played from there, and the folder
  is deleted when PhoneKeep closes and again at the next start.
- the backup reader gives a file's bytes in memory (plain and encrypted backups), the photo sources too.
- Space in the photo grid previews the photo last clicked, with the arrows going through the month.
The real-Mac check (Quick Look playing a video, a PDF drawn by macOS) is in the PR.
"""
import io, os, shutil, stat, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

import quicklook as ql

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


check([ql.kind_of(n) for n in ("IMG_1.HEIC", "a.jpg", "clip.MOV", "memo.m4a", "x.pdf", "notes.txt", "Info.plist", "book.epub")]
      == ["image", "image", "video", "audio", "pdf", "text", "text", "other"], "each kind of item is recognised")
import plistlib
check("'Owner': 'Test'" in ql.text_of(plistlib.dumps({"Owner": "Test"}, fmt=plistlib.FMT_BINARY), "x.plist"),
      "a binary plist is shown as readable text")
check(ql.text_of("é".encode("utf-8") * 400_000, "a.txt").endswith("(the rest isn't shown in the preview)"),
      "a huge text file is cut, and says so")

# -- the backup reader: a file's bytes in memory ------------------------------------------------------------------
import phonekeep as wv
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
r = wv.BackupReader(fake, None, lambda m: None)
files = r.list_files("HomeDomain", "Library/SMS/sms.db")
rel, fid = next(iter(files.items()))
data = r.read_bytes("HomeDomain", rel, fid)
check(data is not None and data[:15] == b"SQLite format 3", "a plain backup's file is read into memory")
check(r.read_bytes("HomeDomain", rel, "../../etc/passwd") is None, "a bad file id is refused")


class FakeEnc:
    def extract_file_as_bytes(self, rel, domain_like=None):
        return b"decrypted:" + rel.encode()


r._enc = FakeEnc()
check(r.read_bytes("HomeDomain", rel, fid) == b"decrypted:" + rel.encode(),
      "an encrypted backup's file is decrypted into memory (never to disk)")


class FakeEncBroken:
    def extract_file_as_bytes(self, rel, domain_like=None):
        raise MemoryError("too big to decrypt in memory")

    def extract_file(self, relative_path, domain_like=None, output_filename=None):
        Path(output_filename).write_bytes(b"from-disk:" + relative_path.encode())


r._enc = FakeEncBroken()
check(r.read_bytes("HomeDomain", rel, fid) == b"from-disk:" + rel.encode() and not list(ql.private_dir().glob("read-*"))
      and "MemoryError" in r.last_error, "if decrypting in memory fails, it's decrypted to the private folder, read and removed")
r._enc = None
r.close()

import photos as ph


class Reader:
    def __init__(self):
        self.read = []

    def file_meta(self, domain, prefix):
        return {"Media/DCIM/100APPLE/IMG_0001.JPG": ("a" * 40, 1.7e9, 10)}

    def read_bytes(self, domain, rel, fid):
        self.read.append(rel)
        return b"JPEGDATA"


bps = ph.BackupPhotoSource(Reader(), HERE / "work" / "q1-cache")
check(bps.read("DCIM/100APPLE/IMG_0001.JPG") == b"JPEGDATA" and bps.read("DCIM/none.JPG") is None,
      "a photo in a backup is read into memory")

# -- a photo straight from the iPhone: if reading it whole fails, it's copied (like Save) and read from the copy --
import asyncio, threading


class FakeAfc:
    async def get_file_contents(self, path):
        raise ConnectionError("read refused")

    async def pull(self, src, dest, progress_bar=False):
        Path(dest).write_bytes(b"PHOTO:" + src.encode())


dps = ph.DevicePhotoSource.__new__(ph.DevicePhotoSource)
ph.PhotoSource.__init__(dps, HERE / "work" / "q1-dev")
dps.loop = asyncio.new_event_loop()
threading.Thread(target=dps.loop.run_forever, daemon=True).start()
dps.afc, dps._sizes = FakeAfc(), {}
got = dps.read("PhotoData/CPLAssets/group1/AAAA.HEIC")
check(got == b"PHOTO:PhotoData/CPLAssets/group1/AAAA.HEIC" and not list(ql.private_dir().glob("read-*")),
      "a photo on the iPhone that can't be read whole is copied, read and the copy removed at once")
dps.loop.call_soon_threadsafe(dps.loop.stop)

# -- the viewer ---------------------------------------------------------------------------------------------------
ql.cleanup()
played, written = [], []
ql.play = lambda p: played.append(p)
try:
    import tkinter as tk
    from PIL import Image
    root = tk.Tk()
    root.geometry("1000x700+0+0")
    root.update()

    def png(colour, size=(1200, 800)):
        b = io.BytesIO()
        Image.new("RGB", size, colour).save(b, "PNG")
        return b.getvalue()

    def to_file(name, data=b"media"):
        def go(dest):
            written.append(name)
            Path(dest).write_bytes(data)
            return True
        return go

    items = [ql.Item("IMG_0001.HEIC", read=lambda: png((200, 30, 30)), to_file=to_file("IMG_0001.HEIC")),
             ql.Item("Notes.txt", read=lambda: "Shopping list\nbread".encode(), to_file=to_file("Notes.txt")),
             ql.Item("Manual.pdf", read=lambda: b"%PDF-1.4 stand-in", to_file=to_file("Manual.pdf", b"%PDF-1.4")),
             ql.Item("clip.MOV", to_file=to_file("clip.MOV", b"\x00" * 1000), size=1000),
             ql.Item("memo.m4a", to_file=to_file("memo.m4a")),
             ql.Item("book.epub", to_file=to_file("book.epub")),
             ql.Item("gone.jpg", read=lambda: None)]

    def wait(v, until, t=10):
        end = time.time() + t
        while time.time() < end:
            root.update()
            if until():
                return True
            time.sleep(0.02)
        return False

    v = ql.Viewer(root, items, 0)
    wait(v, lambda: v.shown_kind == "image")
    v.update_idletasks()
    check(v.shown_kind == "image" and v.winfo_width() >= 700 and "IMG_0001.HEIC" == v.name_lbl.cget("text")
          and v.pos_lbl.cget("text").startswith("1 of 7"), f"Space on a photo: shown large over the window ({v.winfo_width()}px)")
    v.event_generate("<Right>")
    wait(v, lambda: v.shown_kind == "text")
    check(v.shown_kind == "text" and "Shopping list" in v.text_widget.get("1.0", "end") and v.index == 1,
          "→ moves to the next item: a text file is shown as text")
    v.move(1)
    wait(v, lambda: v.shown_kind not in ("loading",))
    check(v.shown_kind in ("pdf", "play"), f"a PDF: drawn by macOS on a Mac, an Open button elsewhere ({v.shown_kind})")
    v.move(1)
    wait(v, lambda: v.shown_kind == "play")
    check(v.shown_kind == "play" and v.index == 3, "a video shows a Play button")
    check(not written, f"nothing was written to disk for the photo, text and PDF previews ({written})")
    path = v.open_from_file(wait=True)
    mode = stat.S_IMODE(os.stat(ql.private_dir()).st_mode)
    check(path is not None and path.parent == ql.private_dir() and played == [path] and (os.name == "nt" or mode == 0o700),
          f"Play copies the video to the private folder (mode {oct(mode)}) and plays it from there")
    check(os.name == "nt" or stat.S_IMODE(os.stat(path).st_mode) == 0o600, "the copy is readable only by the user")
    v.move(1)
    wait(v, lambda: v.shown_kind == "play")
    check(v.items[v.index].kind == "audio" and v.shown_kind == "play", "audio shows a Play button too")
    v.move(1)
    wait(v, lambda: v.shown_kind == "play")
    check(v.items[v.index].name == "book.epub", "another kind (e-book) offers Open")
    v.move(1)
    wait(v, lambda: v.shown_kind == "error")
    check(v.shown_kind == "error", "an item that can't be read says so, in the preview")
    v.move(1)
    check(v.index == 0, "→ after the last item goes back to the first")
    v.event_generate("<Left>")
    check(v.index == 6, "← goes back")
    v.event_generate("<space>")
    root.update()
    check(ql.Viewer.current is None and not v.winfo_exists(), "Space closes the preview")
    v = ql.Viewer(root, items, 1)
    v.event_generate("<Escape>")
    root.update()
    check(ql.Viewer.current is None, "Esc closes it too")

    # bind_space on a list: Space opens the preview at the selected row, focus comes back to the list
    from tkinter import ttk
    tree = ttk.Treeview(root)
    tree.pack()
    for n, it in enumerate(items[:3]):
        tree.insert("", "end", iid=str(n), text=it.name)
    tree.selection_set("2")
    ql.bind_space(tree, lambda: (items[:3], int(tree.selection()[0])))
    tree.quick_preview()
    check(ql.Viewer.current is not None and ql.Viewer.current.index == 2, "Space on a list opens the selected row")
    ql.Viewer.current.close()

    # the photo grid: Space previews the photo last clicked, the arrows go through the month
    import ui, datetime as dt

    class Src:
        label = "test"

        def thumbnail(self, item):
            return None
    many = [ph.PhotoItem(f"DCIM/100APPLE/IMG_{n:04}.JPG", f"IMG_{n:04}.JPG", 1000, dt.datetime(2025, 3, 1 + n), False)
            for n in range(6)]
    got = []
    pp = ui.PhotoPanel(root, Src(), many, select_all=False, on_preview=lambda shown, idx: got.append((len(shown), idx)))
    pp.pack(fill="both", expand=True)
    pp.mlist.selection_set("2025-03")
    for _ in range(20):
        root.update()
    third = pp.months[pp._month()][2]
    pp._point_at(third)
    pp.preview_current()
    check(got == [(6, 2)], f"Space in the photo grid previews the photo last clicked, in its month ({got})")
    check(pp.tiles[third.id].bind("<space>"), "and the tiles answer to Space")
    pp.destroy()
    ql.cleanup()
    check(not ql._dir_path().exists(), "the private folder is deleted when PhoneKeep closes (and at the next start)")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

src = (HERE.parent / "app.py").read_text(encoding="utf-8")
check(src.count("quicklook.cleanup()") == 2, "PhoneKeep clears the private preview folder at start and when it closes")
psrc = (HERE.parent / "phone.py").read_text(encoding="utf-8")
check(psrc.count("preview=self._preview_from(getter)") == 4 and "on_preview=preview" in psrc and "quicklook.bind_space(files" in psrc
      and "phonekeep-view-" not in psrc and "phonekeep-play-" not in psrc,
      "Space previews in Photos, All files, Files from apps, voicemail, voice memos, music and books; no other temp folders")

print("\nQ1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
