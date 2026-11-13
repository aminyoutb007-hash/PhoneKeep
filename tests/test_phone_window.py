"""Phone-window test against a simulated iPhone.

Opens the real PhoneWindow (phone.py) on the fake backup built by test_full_backup.py, with the live
iPhone replaced by a simulated device (wallpaper, music, books, apps and app files served from memory).
Checks that the home screen fills in its counts, that every app screen opens without an error, that a
save produces a file, and that the window closes cleanly.

Needs a display: on Mac and Windows there is one; on Linux run it under `xvfb-run`.
"""
import datetime as dt, io, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
import os
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))

W = HERE / "work"
UDID = "00008030-FULLTEST"
BACKUPS = W / "Backups"
if not (BACKUPS / UDID / "Manifest.db").exists():
    print("fake backup missing: building it with test_full_backup.py first", flush=True)
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

import faulthandler
faulthandler.dump_traceback_later(120, repeat=True)   # if this ever stalls in CI, show where

import tkinter as tk
from tkinter import ttk
from PIL import Image

import phonekeep as wv
import sections as sx
import device as devmod
import photos as ph
import phone
import keychain
from ui import RED

keychain.use_memory()   # never touch the real keychain from a test

# ---------------------------------------------------------------------------
# the simulated iPhone: same methods as device.LiveDevice, data from memory
# ---------------------------------------------------------------------------

SIM_DIR = W / "sim-phone"
shutil.rmtree(SIM_DIR, ignore_errors=True)
SIM_DIR.mkdir(parents=True)


class SimulatedDevice:
    def __init__(self, udid, cache_dir=None):
        self.udid = udid
        self.calls = []

    def wallpaper(self, which="homescreen"):
        self.calls.append(("wallpaper", which))
        p = SIM_DIR / f"{which}.png"
        Image.new("RGB", (390, 844), (40, 120, 90)).save(p)
        return p

    def music(self):
        self.calls.append(("music",))
        return [devmod.Track("Song One", "Artist A", "Album X", 201.0, "iTunes_Control/Music/F00/one.m4a", 4_000_000),
                devmod.Track("Song Two", "Artist B", "Album Y", 150.5, "iTunes_Control/Music/F01/two.m4a", 3_100_000)]

    def books(self):
        self.calls.append(("books",))
        return [devmod.Book("A Novel", "Writer", "Books/1.epub", "EPUB", 500_000, True),
                devmod.Book("Manual", "Maker", "Books/2.pdf", "PDF", 120_000, False)]

    def apps(self):
        self.calls.append(("apps",))
        return [devmod.AppInfo("org.videolan.vlc-ios", "VLC", "3.5", True),
                devmod.AppInfo("com.apple.Pages", "Pages", "14.0", True),
                devmod.AppInfo("com.spotify.client", "Spotify", "8.9", False)]

    def app_list(self, bundle_id, path="Documents"):
        self.calls.append(("app_list", bundle_id, path))
        return [devmod.Entry("Movies", "Documents/Movies", True),
                devmod.Entry("clip.mp4", "Documents/clip.mp4", False, 48_000_000, dt.datetime(2026, 3, 4, 10, 30))]

    def app_pull(self, bundle_id, path, dest_dir):
        self.calls.append(("app_pull", bundle_id, path))
        dest = Path(dest_dir) / Path(path).name
        dest.write_bytes(b"simulated")
        return True

    def copy_media(self, path, dest, is_dir=False):
        Path(dest).write_bytes(b"simulated")
        return True

    def close(self):
        self.calls.append(("close",))


class NoDevicePhotos:
    """Photos over the cable aren't simulated: the window must fall back to the backup's photos."""
    def __init__(self, udid, cache_dir):
        raise wv.PhoneKeepError("Photos on the iPhone aren't reachable (simulated).")


devmod.LiveDevice = SimulatedDevice
ph.DevicePhotoSource = NoDevicePhotos


class FakeApp(tk.Tk):
    """The bits of the main window that PhoneWindow uses (it is a Tk root, like app.App)."""
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(BACKUPS), "archive_dir": str(W / "Archive-phone-window")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:            # a console that can't show ✓ or ' (Windows cp1252)
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


def pump(root, until, timeout=60.0, what=""):
    """Run the Tk event loop until `until()` is true or the timeout passes."""
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    print(f"timed out waiting for {what}", flush=True)
    return False


def labels_in(widget):
    out = []
    for w in widget.winfo_children():
        if isinstance(w, tk.Label):
            out.append(w)
        out.extend(labels_in(w))
    return out


def error_labels(win):
    red = str(RED).lower()
    return [l for l in labels_in(win.content) if str(l.cget("fg")).lower() == red]


def still_loading(win):
    texts = [l.cget("text") for l in labels_in(win.content)]
    return any(t in ("Loading…", "Reading from the iPhone…") for t in texts)


# ---------------------------------------------------------------------------
# the test
# ---------------------------------------------------------------------------

app = FakeApp()
root = app
info = wv.backup_info(BACKUPS / UDID)
win = phone.PhoneWindow(app, {"DeviceName": info.get("name") or "Test iPhone"}, UDID)
# the window stays mapped: a withdrawn Toplevel behaves differently on macOS (geometry events), and the
# CI machines have a display

# window basics
check(info["name"] in win.title(), f"window title names the phone: {win.title()!r}")
check(tuple(win.minsize()) == (980, 640), "minimum window size is 980 x 640")

# home screen: counts fill in for every backup app
backup_apps = [k for k, *_r, where in phone.APPS if where == "backup"]
ok = pump(root, lambda: all(k in win.counts for k in backup_apps), 90, "home screen counts")
check(ok, "home screen counts filled in for every backup app")
expected_chats = len(sx.load_messages(win.data.ctx)) if win.data else -1
check(win.counts.get("messages") == f"{expected_chats:,} chats", f"Messages count matches the backup ({win.counts.get('messages')})")
present = [k for k in backup_apps if win.counts.get(k) not in (None, "nothing found")]
check(len(present) >= 8, f"{len(present)} apps have data in the fake backup")

# the simulated phone was used for the wallpaper
check(pump(root, lambda: win.live is not None, 30, "simulated device"), "simulated iPhone connected")
check(any(c[0] == "wallpaper" for c in win.live.calls), "wallpaper read from the simulated iPhone")

# every app screen opens: with content, or (for a kind of data the backup doesn't have) with a message
# that says so in plain words. Anything else shown in red is a failure.
for key, label, *_r in phone.APPS:
    win.open_app(key)
    pump(root, lambda: not still_loading(win), 90, f"{label} screen")
    errs = [l.cget("text") for l in error_labels(win)]
    has_data = win.counts.get(key, "") != "nothing found"
    empty_ok = (not has_data) and len(errs) == 1 and errs[0].startswith("No ") and "in this backup" in errs[0]
    check(not still_loading(win) and (not errs or empty_ok),
          f"{label} screen opens" + (" (empty state explained)" if empty_ok else "")
          + (f" (error: {errs[0][:80]})" if errs and not empty_ok else ""))
    check(len(win.content.winfo_children()) > 0, f"{label} screen shows content")

# usability task 3: "find a message containing a given word" — the chat search looks inside messages,
# opens the chat at the match and highlights it (12 Nov: it only matched chat names)
win.open_app("whatsapp")
pump(root, lambda: not still_loading(win), 90, "WhatsApp screen")
def _find(w, cls):
    for x in w.winfo_children():
        if isinstance(x, cls):
            return x
        r = _find(x, cls)
        if r is not None:
            return r
panel = _find(win.content, phone.ui.ChatPanel)
check(panel is not None, "WhatsApp opens the chat panel")
if panel is not None:
    sample = None
    for c in win.data.preview._chats("whatsapp"):
        for m in c["messages"]:
            words = [w for w in (m.get("text") or "").split() if len(w) > 4 and w.isalpha()]
            if words and words[0].lower() not in c["name"].lower():
                sample, chat_name = words[0], c["name"]
                break
        if sample:
            break
    check(sample is not None, f"a word from inside a message to search for: {sample!r}")
    panel.q.set(sample)
    root.update()
    shown = [panel.tree.item(i, "values")[1].replace("👥 ", "") for i in panel.tree.get_children()]
    check(chat_name in shown, f"searching {sample!r} lists the chat that contains it ({chat_name!r} in {shown[:5]})")
    check(panel.search_hint.cget("text").startswith(f"“{sample}” is in "), f"says how many messages match: {panel.search_hint.cget('text')!r}")
    iid = next(i for i in panel.tree.get_children() if panel.tree.item(i, "values")[1].replace("👥 ", "") == chat_name)
    panel._show(iid)
    root.update()
    ranges = panel.text.tag_ranges("hit")
    check(len(ranges) >= 2 and panel.text.get(ranges[0], ranges[1]).lower() == sample.lower(), "the match is highlighted in the chat")
    panel.q.set("zzqqxxnotthere")
    root.update()
    check(not panel.tree.get_children() and panel.search_hint.cget("text").startswith("No message contains"),
          f"a word nowhere says so: {panel.search_hint.cget('text')!r}")
    panel.q.set("")

    # M3 from the phone window: tick a chat → Save ticked as PDF → asked where → the PDF is there and shown
    dest_dir = Path(tempfile.mkdtemp(prefix="pk-pdf-dest-"))
    asked, shown_paths = [], []
    real_ask, real_reveal = phone.ask_save_folder, phone.reveal
    phone.ask_save_folder = lambda parent, title, start: asked.append(title) or str(dest_dir)
    phone.reveal = lambda p: shown_paths.append(Path(p))
    try:
        first = panel.tree.get_children()[0]
        panel._toggle(first)
        btn = next(w for w in panel.foot.winfo_children() if getattr(w, "text", "") == "Save ticked as PDF")
        btn.command()
        pump(root, lambda: list(dest_dir.glob("*.pdf")) and shown_paths, 60, "PDF saved")
        pdfs = list(dest_dir.glob("*.pdf"))
        check(asked and pdfs and pdfs[0].read_bytes().startswith(b"%PDF"), f"Save ticked as PDF asks where and saves there: {[p.name for p in pdfs]}")
        check(shown_paths and shown_paths[0] == pdfs[0], "and shows the new PDF in Finder straight away")
        check(win.bar_text.cget("text").startswith("✓ Saved ") and pdfs[0].name in win.bar_text.cget("text"),
              f"the banner names the file: {win.bar_text.cget('text')!r}")
    finally:
        phone.ask_save_folder, phone.reveal = real_ask, real_reveal

# photos came from the backup because the cable was 'unplugged'
check(isinstance(win.photo_src, ph.BackupPhotoSource), "Photos fell back to the backup when the iPhone wasn't reachable")

# saving: export one app through the window's own save path
out_dir = Path(app.s["archive_dir"])
shutil.rmtree(out_dir, ignore_errors=True)
win.export_section("messages", {"excel"})
ok = pump(root, lambda: str(win.bar_text.cget("text")).startswith("✓ Exported"), 120, "export banner")
check(ok, f"save shows a done banner: {win.bar_text.cget('text')!r}")
xlsx = list(out_dir.rglob("*.xlsx"))
check(bool(xlsx), f"save produced an Excel file ({len(xlsx)} found)")

# closing
# B3: renaming a snapshot from the timeline uses PhoneKeep's own text dialog (found on a Mac: Tk's
# simpledialog never appeared); the typed name lands in snapshots.json
import datetime as _dt, json as _json
from types import SimpleNamespace
import snapshots as _sn2
snap0 = SimpleNamespace(id="20261112-164026", when=_dt.datetime(2026, 11, 12, 16, 40), label=None, locked=False, title="Today")
typed = []
real_ask = phone.ui.ask_text
phone.ui.ask_text = lambda parent, title, prompt, initial="", ok="Save": typed.append((title, initial)) or "Before the holiday"
try:
    win._rename_snapshot(snap0)
finally:
    phone.ui.ask_text = real_ask
choices_file = _sn2.phone_dir(win.backup_dir, win.udid) / "snapshots.json"
saved = _json.loads(choices_file.read_text(encoding="utf-8")) if choices_file.exists() else {}
check(typed and typed[0][0] == "Rename snapshot", f"rename asks with the app's own dialog: {typed}")
check(saved.get(snap0.id, {}).get("label") == "Before the holiday", f"the new name is saved in snapshots.json: {saved}")
if choices_file.exists():
    choices_file.unlink()
d = phone.ui.TextDialog(win, "Rename snapshot", "A name:", initial="x")
root.update()
check(d.entry.get() == "x" and d.winfo_exists(), "the text dialog opens with the current name")
d._cancel()
check(d.result is None, "Cancel gives None")

# dark mode: a tk widget that sets a light background must also set its text colour, or macOS draws white
# text on it (12 Nov: every chat bubble looked empty). Checked on the source of every window module.
import ast as _ast
bad = []
for mod in ("ui.py", "phone.py", "app.py", "firstrun.py"):
    tree = _ast.parse((HERE.parent / mod).read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute) and node.func.attr in ("Text", "Listbox") \
                and isinstance(node.func.value, _ast.Name) and node.func.value.id == "tk":
            keys = {k.arg for k in node.keywords}
            if "bg" in keys and "fg" not in keys:
                bad.append(f"{mod}:{node.lineno}")
check(not bad, f"every tk.Text/Listbox with a background sets its text colour: {bad}")
# iMessage text inside attributedBody: older typedstream, NSMutableString variant, long (0x81) lengths,
# and a keyed archive — the decoder must find the text in all of them
import plistlib as _pl, sections as _sx
_blobs = [
    (b'\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+\x05Hello\x86', "Hello"),
    (b'\x84\x0fNSMutableString\x01\x84\x84\x08NSString\x01\x95\x84\x01+\x0bmerci bien!\x86', "merci bien!"),
    (b'NSString\x01\x94\x84\x01+\x81\x2c\x01' + b'x' * 300 + b'\x86', "x" * 300),
    (_pl.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": _pl.UID(1)},
                "$objects": ["$null", {"NSString": _pl.UID(2)}, {"NS.string": "Bonjour"}]}, fmt=_pl.FMT_BINARY), "Bonjour"),
]
check(all(_sx.decode_attributed_body(b) == want for b, want in _blobs), "attributedBody text found in every layout")

# every transfer shows progress and a realistic time left (01-principles.md, 6a)
import ui as _ui2
e = _ui2.Eta(settle=0.0)
first = e.feed(1.0)
check(first.endswith("working out time left…"), f"no estimate from the first second: {first!r}")
e.points[0] = (e.points[0][0] - 60, e.points[0][1])          # a minute ago we were at 1%
t = e.feed(21.0)
check(t.startswith("21%") and ("about 3 min left" in t or "about 4 min left" in t), f"20% in a minute → about 4 min left: {t!r}")
check(_ui2.Eta.fmt(30) == "under 2 min left" and _ui2.Eta.fmt(2 * 3600 + 5 * 60) == "about 2 h 05 min left", "wording")
check(e.feed(100) == "100%", "done")

win.close()
root.update()
check(("close",) in win.live.calls, "closing the window disconnects the simulated iPhone")

# photo chooser (13 Nov): Select none, then Select this month, must keep the month's photos on screen
import datetime as _dt
import photos as _ph
import ui as _ui


class _Src:
    label = "the iPhone"

    def thumbnail(self, item):
        return None


_items = [_ph.PhotoItem(f"DCIM/100APPLE/IMG_{n:04}.JPG", f"IMG_{n:04}.JPG", 1000, _dt.datetime(2025, 6 if n < 4 else 5, 1 + n), False)
          for n in range(6)]
pp = _ui.PhotoPanel(root, _Src(), _items)
pp.pack(fill="both", expand=True)
root.geometry("1000x700"); root.deiconify(); root.update()
pp.mlist.selection_set("2025-06"); root.update()


def _placed():
    root.update()
    return [i for i in pp.months["2025-06"] if i.id in pp.tiles and pp.tiles[i.id].winfo_manager() == "grid"]


check(len(_placed()) == 4, f"June shows its 4 photos ({len(_placed())})")
pp._set_all(False); root.update()
pp._set_month(True); root.update()
check(len(_placed()) == 4, f"after Select none, then Select this month, the photos are still shown ({len(_placed())})")
check(pp.selected == {i.id for i in pp.months["2025-06"]} and pp.mlist.item("2025-06", "values")[1] == "4/4",
      "and the month is ticked, 4/4")
pp._set_month(False); pp._set_all(True); root.update()
check(len(_placed()) == 4 and pp.mlist.selection() == ("2025-06",), "Clear this month and Select all keep the same month open")
# B3 timeline (13 Nov): every snapshot in one drop-down list, newest first; choosing one opens it
import snapshots as _sn
from types import SimpleNamespace as _NS2
_now = _dt.datetime.now().replace(second=0, microsecond=0)
_mk = lambda h, m, d=0: (lambda w: _NS2(id=f"{d}-{h}{m}", when=w, label="", locked=False, size=1e9, ios="26", encrypted=True,
                                         title=_sn.Snapshot.title.fget(_NS2(when=w, label=""))))((_now - _dt.timedelta(days=d)).replace(hour=h, minute=m))
_snaps = [_mk(12, 29), _mk(11, 33), _mk(18, 25, 1)] + [_mk(9, 0, d) for d in range(3, 12)]
_opened = []
_tl_host = tk.Toplevel(root)
_fake = _NS2(timeline=tk.Frame(_tl_host), snapshot=None, backup_dir=None, udid="x", open_snapshot=_opened.append,
             _snapshot_menu=lambda e, s: None)
_fake.timeline.pack()
_real_list = _sn.list_snapshots
_sn.list_snapshots = lambda a, b: _snaps
import phone as _phone
_phone.PhoneWindow._build_timeline(_fake)
_sn.list_snapshots = _real_list
root.update()
check(len(_fake.snap_choices) == 12 and _fake.snap_choices[0] == "Today 12:29  (latest)" and _fake.snap_choices[1] == "Today 11:33",
      f"all 12 snapshots are in one drop-down list, newest first, with times: {_fake.snap_choices[:3]}")
_fake.snap_var.set(_fake.snap_choices[2]); _fake.snap_box.event_generate("<<ComboboxSelected>>"); root.update()
check(_opened and _opened[-1] is _snaps[2], "choosing one opens that snapshot")
_tl_host.destroy()
check(all((_ui.ICON_DIR / f"keep_{k}-48.png").exists() for k in ("chats", "chats_photos", "everything", "custom")),
      "the main screen's four choices have drawn icons")
_picked = []
_cc = _ui.ChoiceCard(root, _ui.app_icon("keep_chats", size=48), "Chats", "WhatsApp and Messages", lambda: _picked.append(1))
_cc.pack(fill="x"); root.update()
_cc.set(True); root.update()
_texts = [_cc.itemcget(i, "text") for i in _cc.find_all() if _cc.type(i) == "text"]
check("Chats" in _texts and "✓" in _texts, f"a chosen card shows its title and a ✓ badge: {_texts}")
_cc.event_generate("<ButtonRelease-1>", x=10, y=10); root.update()
check(_picked == [1], "clicking a card chooses it")
_cc.destroy()
# headers (13 Nov): the right-hand buttons are packed first, so text on the left is trimmed, never drawn over them
_ps = (HERE.parent / "phone.py").read_text(encoding="utf-8")
_as = (HERE.parent / "app.py").read_text(encoding="utf-8")
check(_ps.index("Refresh from iPhone\", self.refresh") < _ps.index("self.sub = tk.Label(head")
      and _as.index("\"⚙  Settings\", self.open_settings") < _as.index("text=\"Back up your iPhone to this computer\""),
      "window headers pack their buttons before the text, so nothing overlaps")
import phone as _phone
check(all((_phone.ICON_DIR / f"{k}.png").exists() and (_phone.ICON_DIR / f"{k}-28.png").exists() for k, *_r in _phone.APPS),
      "every app on the home screen has PhoneKeep's own drawn icon (big and small)")
check(_phone.app_icon("messages") is not None, "and it loads")
check(ttk.Style().lookup("Months.Treeview", "background") == _ui.CARD, "the month list uses PhoneKeep's colours, not the system's dark ones")
pp.destroy()

# scrolling (13 Nov): the wheel scrolls the photos with the pointer over a tile; a Mac trackpad's two-finger
# scroll (Tk 9 <TouchpadScroll>) is unpacked the way Tk packs it
_many = [_ph.PhotoItem(f"DCIM/100APPLE/IMG_{n:04}.JPG", f"IMG_{n:04}.JPG", 1000, _dt.datetime(2025, 3, 1 + n % 28), False)
         for n in range(80)]
pp2 = _ui.PhotoPanel(root, _Src(), _many)
pp2.pack(fill="both", expand=True); root.update()
pp2.mlist.selection_set("2025-03")
for _ in range(30):
    root.update()
# 13 Nov: a line per year with its months under it; tiles fill the width; selected = a blue frame, no circle
check(pp2.mlist.exists("year-2025") and "2025-03" in pp2.mlist.get_children("year-2025")
      and pp2.mlist.item("2025-03", "values")[0].strip()[2:] == "March", "months are listed under their year, by name")
pp2.mlist.selection_set("year-2025"); root.update()
check(pp2._month() == "2025-03", "clicking a year opens its newest month")
_cw = pp2.canvas.winfo_width()
_used = pp2._cols() * (pp2.tile + pp2.GAP) + pp2.GAP
check(0 <= _cw - _used < pp2._cols() + pp2.GAP, f"the photos fill the width ({_used} of {_cw} px)")
_it = pp2.months["2025-03"][0]
pp2.selected.add(_it.id); pp2._draw_tile(_it)
_c = pp2.tiles[_it.id]
_kinds = [(_c.type(i), _c.itemcget(i, "outline") if _c.type(i) in ("rectangle", "oval") else "") for i in _c.find_all()]
check(("rectangle", _ui.SELECT_BLUE) in _kinds and not any(k == "oval" for k, _o in _kinds),
      "a selected photo has a blue frame and no tick circle")
# 13 Nov: one Select all / Select none button; a month's or a year's box in the list ticks all of it
pp2._set_all(False); root.update()
check(pp2.all_btn.text == "Select all", "with nothing selected the button says Select all")
_y = pp2.mlist.bbox("2025-03")[1] + 5
pp2._row_click(type("E", (), {"x": 40, "y": _y})()); root.update()
check(all(i.id in pp2.selected for i in pp2.months["2025-03"]) and pp2.mlist.item("2025-03", "values")[0].strip().startswith("☑"),
      "ticking a month's box selects the whole month")
pp2._row_click(type("E", (), {"x": 120, "y": _y})()); root.update()
check(all(i.id in pp2.selected for i in pp2.months["2025-03"]), "clicking the month's name only opens it")
_yy = pp2.mlist.bbox("year-2025")[1] + 5
pp2._row_click(type("E", (), {"x": 10, "y": _yy})()); root.update()
check(not pp2.selected, "ticking the year's box when all of it is selected clears the year")
pp2._flip_all(); root.update()
check(len(pp2.selected) == len(_many) and pp2.all_btn.text == "Select none", "Select all selects everything and becomes Select none")
_tile = next(iter(pp2.tiles.values()))
_y0 = pp2.canvas.yview()[0]
for _ in range(3):
    _tile.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    root.update()
check(pp2.canvas.yview()[0] > _y0, f"the mouse wheel over a photo scrolls the grid ({_y0:.3f} → {pp2.canvas.yview()[0]:.3f})")
check(_ui.touchpad_deltas((3 << 16) | (0x10000 - 25)) == (3, -25) and _ui.touchpad_deltas(40) == (0, 40)
      and _ui.touchpad_deltas(((0x10000 - 2) << 16) | 7) == (-2, 7), "two-finger trackpad deltas are unpacked (Tk 9)")
pp2.destroy()

# chat chooser (13 Nov): Select all / none sit right above the list, with a count; the ✓ header toggles all
_lists = {"whatsapp": ("WhatsApp", [{"id": f"c{n}", "name": f"Chat {n}", "group": False, "messages": 3, "last": f"2025-10-0{n+1}", "first": "2025-01-01", "days": ["2025-01-01"]} for n in range(4)])}
cp = _ui.ChatPanel(root, _lists)
cp.pack(fill="both", expand=True); root.update()
tbar = cp.tick_count.master
btn_texts = [w.text for w in tbar.winfo_children() if hasattr(w, "text")]
check(btn_texts == ["Select all", "Select none"] and tbar.master is cp.tree.master,
      f"Select all / Select none are in the bar right above the chat list: {btn_texts}")
check(tbar.winfo_y() < cp.tree.winfo_y(), "above it, not elsewhere in the window")
check(cp.tick_count.cget("text") == "4 of 4 shown are ticked", f"with a count: {cp.tick_count.cget('text')!r}")
cp._set_all(not cp._all_shown_ticked()); root.update()
check(not cp.selected and cp.tick_count.cget("text") == "0 of 4 shown are ticked", "the ✓ header unticks all shown")
cp._set_all(not cp._all_shown_ticked()); root.update()
check(len(cp.selected) == 4, "and ticks them again")
cp.destroy()
# light appearance: applied on a Mac (dark mode drew the lists black); nothing to do elsewhere
check(_ui.use_light_appearance(root) == (sys.platform == "darwin"), "every PhoneKeep window uses the light appearance on a Mac")
root.destroy()

print("\nPHONE WINDOW TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
