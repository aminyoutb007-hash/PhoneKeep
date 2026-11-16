"""L1 (5.2): the phone window in the Direction A layout (docs/spec/14-layouts.md#l1-phone-window-layout).

With a fake iPhone and invented data (nothing talks to a real phone), checks:
- the header: the phone's name, Refresh from iPhone, Saved files, and Save everything as the main button;
- the left column: the phone picture, then the Snapshot card;
- the home screen: the three cards, then "What's on this iPhone" as one tile per section in four columns, each with
  its name and count, then the line saying what comes from the backup and what is read live;
- every section opens from its tile, and the Battery and Storage cards open their details.
"""
import os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821

import deviceinfo as di
import overview_ui
import theme

G = 1000 ** 3
OV = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=128 * G, free=78 * G,
                 battery=di.Battery(level=64, health=91, cycles=120))
wv.device_overview = lambda udid=None, apps=True, **k: OV                                # noqa: F821
app = FakeApp()                                                                          # noqa: F821
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": "USB", "ProductVersion": "26.5"}, UDID)  # noqa: F821
win.geometry("1220x800")
pump(app, lambda: win.overview is not None and win.data is not None, 60, "overview and backup")  # noqa: F821
win.show_home()
app.update()


def texts(w, out):
    for c in w.winfo_children():
        try:
            out.append(str(c.cget("text")))
        except Exception:
            pass
        texts(c, out)
    return out


# -- the header ----------------------------------------------------------------------------------------------------
head = win.save_all_btn.master
words = texts(head, [])
check(win.save_all_btn.winfo_ismapped() and "Test iPhone" in words, "the header has the phone's name and Save everything")  # noqa: F821
buttons = [c for c in head.winfo_children() if isinstance(c, phone.RoundButton)]           # noqa: F821
check(len(buttons) >= 3 and buttons[0] is win.save_all_btn and win.save_all_btn.kind == "primary" and all(b.kind != "primary" for b in buttons[1:]),
      "  Save everything is the main button, at the right, beside Saved files and Refresh from iPhone")  # noqa: F821
check(not any("Save everything" in t for t in texts(win.content, [])), "  and it isn't repeated on the home screen")  # noqa: F821

# -- the left column -----------------------------------------------------------------------------------------------
left = win.timeline.master
check(win.mock.master is left and win.timeline.cget("bg") == theme.CARD and "SNAPSHOT" in texts(win.timeline, []),  # noqa: F821
      "the left column: the phone picture, then the Snapshot card")

# -- the home screen -----------------------------------------------------------------------------------------------
kids = win.content.winfo_children()
check(kids[0] is win.overview_strip and any(t == "What's on this iPhone" for t in texts(win.content, [])),  # noqa: F821
      "the home screen: the three cards first, then \"What's on this iPhone\"")
keys = [k for k, *_r in phone.APPS]                                                        # noqa: F821
check(sorted(win.tiles) == sorted(keys), f"one tile per section ({len(win.tiles)} of {len(keys)})")  # noqa: F821
cols = {int(t.grid_info()["column"]) for t in win.tiles.values()}
check(cols == {0, 1, 2, 3}, f"  in four columns ({sorted(cols)})")                          # noqa: F821
check(all(t.cget("bg") == theme.CARD for t in win.tiles.values()), "  each a white card")      # noqa: F821
label_of = dict((k, l) for k, l, *_r in phone.APPS)                                         # noqa: F821
check(all(label_of[k] in texts(t, []) for k, t in win.tiles.items()), "  each with its name")  # noqa: F821
check(all(win.tile_count[k].cget("text") for k in keys), "  and a count, or where it comes from")  # noqa: F821
check(win.src_line is not None and win.src_line.winfo_ismapped() and win.src_line.cget("text") == win.src_text
      and "from the backup" in win.src_text, "under the tiles: what comes from the backup and what is read live")  # noqa: F821
kept = (win.data, win.data_error)
for err in ("No backup yet. Messages, chats, calls & notes appear after the first backup.", None):
    win.data, win.data_error = None, err
    win._update_src_line()
    check(win.src_text and ".." not in win.src_text and "…." not in win.src_text and win.src_text.endswith((".", "…")),
          f"  the line ends each part once, with no double full stop ({win.src_text!r})")  # noqa: F821
win.data, win.data_error = kept
win._update_src_line()
seen = []
for k in keys:                                  # every tile fits in the window's normal size
    t = win.tiles[k]
    seen.append(t.winfo_rooty() + t.winfo_height() <= win.content.winfo_rooty() + win.content.winfo_height() + 1)
check(all(seen), f"  every tile can be seen in the window's normal size ({sum(seen)} of {len(seen)})")  # noqa: F821

# -- every section opens from its tile; the cards open their details ----------------------------------------------
opened = []
real_open = win.open_app
win.open_app = lambda k: opened.append(k)
win.show_home()
app.update()
for k in keys:
    t = win.tiles[k]
    target = t.winfo_children()[-1].winfo_children()[0]          # the name, inside the tile
    target.event_generate("<Button-1>", x=2, y=2)
    t.event_generate("<Button-1>", x=2, y=2)
app.update()
check(opened == [k for k in keys for _ in (0, 1)], f"every section opens from its tile, by its name or anywhere on it ({len(opened)} clicks)")  # noqa: F821
win.open_app = real_open
went = []
rb, rs = overview_ui.battery_view, overview_ui.storage_view
overview_ui.battery_view = lambda w, ov: went.append("battery")
overview_ui.storage_view = lambda w, ov: went.append("storage")
win.show_home()
app.update()
for card in win.overview_strip.winfo_children():
    card.event_generate("<Button-1>", x=2, y=2)
app.update()
overview_ui.battery_view, overview_ui.storage_view = rb, rs
check(went == ["battery", "storage"], f"the Battery and Storage cards open their details ({went})")  # noqa: F821

win.close()
app.destroy()
print("\nL1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)  # noqa: F821
os._exit(1 if failures else 0)
