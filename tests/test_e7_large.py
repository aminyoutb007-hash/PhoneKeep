"""E7: fast with very large phones (docs/spec/05-ease-of-use.md#e7-fast-with-very-large-phones).

Done when: "With a test backup of 300,000 messages and 50,000 photos, all speed targets are met on a base-model Mac."
The speed targets (docs/spec/00-user-experience.md#speed-targets), each timed on tests/make_big.py's invented backup:
- open the phone window: home grid visible in under 1 s; counts fill in within 5 s;
- open a chat with 10,000 messages: first screen of messages in under 1 s;
- photo grid: smooth with 50,000 photos (no step of scrolling takes longer than a frame budget);
- search: first results in under 1 s for a phone with 200,000 messages (this one has 300,000);
- click to visible response: under 100 ms (opening Messages and Photos shows something at once).
The targets hold on a Mac. On the GitHub runners (shared, slower machines) the times are printed and only a
target missed by more than 5 times fails, so the test still catches a step that went from fast to slow.
"""
import json, os, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import faulthandler
faulthandler.dump_traceback_later(400, exit=True)   # a layout that keeps laying itself out hangs the window: fail
failures = []
SLACK = 5.0 if os.environ.get("CI") else 1.0          # GitHub's shared runners: only a big miss fails
times = {}


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def timed(name, seconds, target):
    times[name] = round(seconds, 3)
    check(seconds <= target * SLACK, f"{name}: {seconds * 1000:.0f} ms (target {target * 1000:.0f} ms"
                                     f"{', x5 on CI' if SLACK > 1 else ''})")


import make_big
BK = make_big.build()

import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
import tkinter as tk
import ui
import app as appmod
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
W = HERE / "work" / "e7"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(W / "Backups")}), encoding="utf-8")
a = appmod.App()
a.after_cancel(a._timers.pop("first"))


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.005)
    return until()


def find(w, cls):
    for c in w.winfo_children():
        if isinstance(c, cls):
            return c
        f = find(c, cls)
        if f is not None:
            return f
    return None


pump(lambda: False, 0.5)
# -- open the phone window ---------------------------------------------------------------------------------------
t0 = time.perf_counter()
check(a.open_backup(BK), "a phone window opens on the large invented backup")
win = a.phone_windows[-1]
pump(lambda: win.winfo_ismapped() and bool(win.tiles) if hasattr(win, "tiles") else win.winfo_ismapped(), 10)
timed("open the phone window: home grid visible", time.perf_counter() - t0, 1.0)
import phone
COUNTED = [k for k, *_r, where in phone.APPS if where == "backup"]      # Photos says "from the backup", no count
pump(lambda: win.data is not None and all(k in win.counts for k in COUNTED), 60)
timed("  counts fill in", time.perf_counter() - t0, 5.0)
print(f"     counts: messages {win.counts.get('messages')}, all files {win.counts.get('allfiles')}", flush=True)

# -- open Messages, then the chat with 10,000 messages ---------------------------------------------------------
t0 = time.perf_counter()
win.open_app("messages")
a.update_idletasks()
timed("click Messages: visible response", time.perf_counter() - t0, 0.1)
pump(lambda: find(win.content, ui.ChatPanel) is not None, 60)
timed("  Messages: chat list shown", time.perf_counter() - t0, 1.0)
panel = find(win.content, ui.ChatPanel)
big = next(str(i) for i, (_k, _l, c) in enumerate(panel.rows) if c["messages"] >= make_big.BIG_CHAT)
t0 = time.perf_counter()
panel.tree.selection_set(big)
panel._show(big)
a.update_idletasks()
timed("open a chat with 10,000 messages: first screen of messages", time.perf_counter() - t0, 1.0)
check("10,000 messages" in panel.pv_sub.cget("text"), f"  it's the big chat: {panel.pv_sub.cget('text')!r}")

# -- search -------------------------------------------------------------------------------------------------------
win.show_home()
pump(lambda: False, 0.3)
t0 = time.perf_counter()
win.find_q.set("holiday photos")
pump(lambda: win.current == "search" and "Messages" in win.find_text.get("1.0", "end"), 60)
timed("search 300,000 messages: first results", time.perf_counter() - t0 - 0.3, 1.0)   # less the typing pause

# -- photos ---------------------------------------------------------------------------------------------------------
win.find_q.set("")
win.show_home()
pump(lambda: False, 0.3)
t0 = time.perf_counter()
win.open_app("photos")
a.update_idletasks()
timed("click Photos: visible response", time.perf_counter() - t0, 0.1)
pump(lambda: find(win.content, ui.PhotoPanel) is not None and find(win.content, ui.PhotoPanel).tiles, 120)
timed("  Photos: first photos shown", time.perf_counter() - t0, 1.0)
pp = find(win.content, ui.PhotoPanel)
check(len(pp.items) == make_big.PHOTOS, f"  all {len(pp.items):,} photos are there")
t1 = time.perf_counter()
for item in pp.items[:1000]:
    pp.source.edits(item)
timed("finding 1,000 photos' edits (each thumbnail looks the same way)", time.perf_counter() - t1, 0.1)
import tkinter.font as tkfont
need = tkfont.Font(font=ui.font(12, "bold")).measure("50000/50000")
check(int(pp.mlist.column("n", "width")) >= need, f"  the list's counts fit (\"0/10000\" read \"0/1000\" before): "
      f"{pp.mlist.column('n', 'width')} px for {need} px")
# scroll the biggest collection to its end; every step must fit in a frame budget (smooth, no visible stutter)
key = max(pp.months, key=lambda k: len(pp.months[k]))      # Videos: 10,000
pp.mlist.selection_set(key)
pump(lambda: pp._month() == key, 10)
worst, steps = 0.0, 0
for i in range(1, 301):                            # dragging the scroll bar from top to bottom
    t1 = time.perf_counter()
    pp.canvas.yview_moveto(i / 300)
    a.update()
    worst = max(worst, time.perf_counter() - t1)
    steps += 1
check(pp.shown >= len(pp.months[key]), f"  scrolling reaches the end of all {len(pp.months[key]):,}")
for i in range(200):                               # then the mouse wheel, one notch (40 px) at a time, back up
    t1 = time.perf_counter()
    pp.canvas.yview_scroll(-40, "units")
    a.update()
    worst = max(worst, time.perf_counter() - t1)
    steps += 1
check(len(pp.pool) < 200 and len(pp.images) <= pp.KEEP_IMAGES,
      f"  only the rows on screen have tiles ({len(pp.pool)} tiles) and the thumbnails kept stay bounded ({len(pp.images)})")
print(f"     scrolled {len(pp.months[key]):,} photos in {steps} steps", flush=True)
timed("photo grid scroll: slowest step", worst, 0.1)

# -- reused tiles show and act on the right photo (a month of photos and videos, scrolled part of the way) --------
month = pp.month_keys[0]
pp.mlist.selection_set(month)
pump(lambda: pp._month() == month, 10)
pp.canvas.yview_moveto(0.4)
pump(lambda: False, 0.5)
items = pp.months[month]
cols, step = pp._cols(), pp.tile + pp.GAP
wrong = []
for c in pp.pool:
    if c.item is None:
        continue
    x, y = pp.canvas.coords(c.win)
    n = int((y - pp.GAP) // step) * cols + int((x - pp.GAP) // step)
    if items[n] is not c.item or pp.tiles.get(c.item.id) is not c:
        wrong.append(c.item.name)
check(pp.canvas.canvasy(0) > 0 and pp.tiles and not wrong,
      f"after scrolling, every tile shows the photo of its own place in the grid ({len(pp.tiles)} tiles, wrong: {wrong[:3]})")
c = next(c for c in pp.pool if c.item is not None and c.item is not items[pp.pool.index(c)])     # a reused tile
target = c.item
t1 = time.perf_counter()
c.event_generate("<ButtonRelease-1>", x=5, y=5)
a.update_idletasks()
timed("click a photo: it's selected", time.perf_counter() - t1, 0.1)
check(pp.selected == {target.id} and any(c.itemcget(k, "outline") == ui.SELECT_BLUE for k in c.find_all()
                                         if c.type(k) == "rectangle"),
      f"  a click on a reused tile selects the photo it shows now ({target.name}), with the frame")
away = next(i for i in items if i.id not in pp.tiles and not i.video)
drawn = []
real_draw = pp._draw_tile
pp._draw_tile = lambda item: (drawn.append(item.name), real_draw(item))
before = {id(c): c.item for c in pp.pool}
pp._thumb_ready(away, None, month)
pp._draw_tile = real_draw
check(not drawn and {id(c): c.item for c in pp.pool} == before,
      f"a late thumbnail for a photo scrolled away changes no tile on screen ({away.name}; redrawn: {drawn})")
t1 = time.perf_counter()
pp._set_all(True)
a.update_idletasks()
timed("Select all 50,000", time.perf_counter() - t1, 0.1)
framed = [c for c in pp.pool if c.item is not None and not getattr(c.item, "cloud_only", False)
          and any(c.itemcget(k, "outline") == ui.SELECT_BLUE for k in c.find_all() if c.type(k) == "rectangle")]
check(len(framed) == sum(1 for c in pp.pool if c.item is not None), f"  every tile on screen has the frame ({len(framed)})")
t1 = time.perf_counter()
pp._set_all(False)
a.update_idletasks()
timed("Select none", time.perf_counter() - t1, 0.1)
pp.canvas.yview_moveto(0.8)
pump(lambda: False, 0.3)
pp._set_month(True)
check(all(any(c.itemcget(k, "outline") == ui.SELECT_BLUE for k in c.find_all() if c.type(k) == "rectangle")
          for c in pp.pool if c.item is not None), "  after Select this month, tiles further down have the frame too")

print("\nE7 TIMES " + json.dumps(times), flush=True)
a.destroy()
print("\nE7 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures))
os._exit(1 if failures else 0)
