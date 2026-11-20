"""Q4 end to end: a click on a video in the storage map opens Photo clean-up on Large videos, with that video in it.

The Q4 test checks the map's blocks with a stand-in for Photo clean-up. This one goes all the way through the real
window, on the tests' invented backup (test_full_backup.py) and a simulated iPhone whose photos can't be reached
over the cable: Storage → Storage map → Photos → Videos, a click on a video block on the map itself, then Photos
opens from the backup and Photo clean-up opens on its Large videos card. Nothing talks to a real phone.

The invented videos are a few bytes each, so the Large videos card's threshold (cleanup.LARGE_VIDEO, 100 MB) is
lowered for this test only.
"""
import os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821

import cleanup as cl
import deviceinfo as di
import overview_ui

G = 1000 ** 3
apps = [di.AppSize(f"com.example.app{i:02d}", f"Example App {i:02d}", (5 - i) * G, G // 10) for i in range(4)]
OV = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=128 * G, free=40 * G, apps=apps)
wv.device_overview = lambda udid=None, apps=True, **k: OV                                # noqa: F821
cl.LARGE_VIDEO = 1                                    # the invented videos are tiny: every one counts as large here

app = FakeApp()                                                                          # noqa: F821
info = wv.backup_info(BACKUPS / UDID)                                                    # noqa: F821
win = phone.PhoneWindow(app, {"DeviceName": info.get("name") or "Test iPhone", "ConnectionType": "USB"}, UDID)  # noqa: F821
win.geometry("1220x800")
pump(app, lambda: win.overview is not None and win.data is not None and win.photos_bytes is not None   # noqa: F821
     and win.messages_bytes is not None, 90, "the window's backup and sizes")
win.overview.apps, win.overview.apps_as_of = list(apps), ""
win._apps_state = "done"

# Storage → Storage map → Photos → Videos
overview_ui.storage_view(win, win.overview)
app.update()
win.map_button.command()
pump(app, lambda: win.current == "storagemap" and getattr(win, "map_media", None), 30, "the backup's file list")  # noqa: F821
win.map_open("Photos")
win.map_open("Videos")
app.update()
vids = [b for b in win.map_blocks if b.open == "cleanup" and not b.name.endswith("smaller videos")]
check(win.map_key == "videos" and len(vids) > 0,                                                    # noqa: F821
      f"the map's Videos level lists the invented backup's videos ({', '.join(b.name for b in vids)})")

# a click on the first video's block, on the map itself
# (the map may be drawn again meanwhile, as the app sizes or the file list come in: wait until it holds still)
def drawn():
    c = win.map_canvas
    return (c.winfo_exists() and c.winfo_viewable() and win.map_key == "videos"
            and any(r[0] == vids[0].name for r in getattr(win, "map_rects", []) or []))


pump(app, drawn, 10, "the map drawn")                                                              # noqa: F821
end = time.time() + 1.0
while time.time() < end:                                                     # nothing redraws it for a second
    app.update()
    time.sleep(0.02)
pump(app, drawn, 10, "the map drawn")                                                              # noqa: F821
canvas = win.map_canvas
name, x, y, rw, rh = next(r for r in win.map_rects if r[0] == vids[0].name)
cx, cy = int(x + rw / 2), int(y + rh / 2)
canvas.event_generate("<Motion>", x=cx, y=cy)                       # the block under the pointer, then the click
canvas.event_generate("<Button-1>", x=cx, y=cy)                     # (it leaves the map at once: no release)
pump(app, lambda: win.current != "storagemap", 10, "the click on the video")                        # noqa: F821
check(win.current in ("photos", "cleanup:working", "cleanup:videos"),                               # noqa: F821
      f"a click on a video's block leaves the map for Photos ({win.current})")

# Photos opens from the backup (the iPhone's photos can't be reached), then Photo clean-up on Large videos
pump(app, lambda: win.current == "cleanup:videos", 90, "Photo clean-up on Large videos")             # noqa: F821
st = getattr(win, "cleanup", None)
card = st.result.card("videos") if st is not None and st.result is not None else None
in_card = [i.name for g in card.groups for i in g.items] if card is not None else []
check(win.current == "cleanup:videos" and st.src.label == "this backup",                           # noqa: F821
      f"Photo clean-up opens on Large videos, with the backup's photos ({win.current}, "
      f"{st.src.label if st else None})")
check(vids[0].name in in_card and in_card == sorted(in_card, key=lambda n: -next(
      i.size for g in card.groups for i in g.items if i.name == n)),
      f"the video clicked on the map is in it, biggest first ({vids[0].name} in {in_card})")      # noqa: F821
# the invented backup has a Live Photo (IMG_0101.JPG with IMG_0101.MOV): its moving part is part of the photo in
# Photos and clean-up, so the map doesn't list it as a video either (it did: a click found nothing to review)
check({b.name for b in vids} == set(in_card) and "IMG_0101.MOV" not in in_card,                     # noqa: F821
      f"every video on the map is in Large videos, and a Live Photo's moving part is in neither "
      f"(map {sorted(b.name for b in vids)}, clean-up {sorted(in_card)})")

win.close()
app.destroy()
print("\nQ4 VIDEOS → CLEAN-UP TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): "  # noqa: F821
                                           + "; ".join(failures)), flush=True)                   # noqa: F821
os._exit(1 if failures else 0)
