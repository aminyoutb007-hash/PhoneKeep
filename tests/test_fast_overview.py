"""5.1.3: a phone appears and fills in fast; over Wi-Fi it isn't asked for what only works over a cable.

Measured on a real iPhone over a cable (15 Nov): the window waited about 30 s, almost all of it for the app list with
sizes. Checks, with a fake iPhone (nothing talks to a real phone):
- the overview (battery, storage, the phone's details) is asked for without the app list and shown at once;
- the app list is read only when Storage (or Apps, or the check-up's Storage details) is opened: names first, shown
  at once with "updating sizes…", then the sizes a few apps at a time, then saved per phone (by UDID);
- next time the saved list is shown at once, marked with its date, and refreshed quietly;
- over Wi-Fi: no wallpaper or battery IORegistry asked for (the saved copies are used), short timeouts;
- the timing log is written only when asked for, with step names and seconds only.
"""
import json, os, sys, time, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
import phonekeep
REAL_OVERVIEW = phonekeep.device_overview       # the set-up below replaces it with a stand-in
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821

import deviceinfo as di
import overview_ui
import phoneapps
import timing

G = 1000 ** 3
NAMES = {f"com.example.app{i:02d}": f"Example App {i:02d}" for i in range(45)}         # invented, 45 apps: 3 chunks
SIZES = {b: ((i + 1) * 100_000_000, (i + 1) * 10_000_000) for i, b in enumerate(NAMES)}

# -- phoneapps --------------------------------------------------------------------------------------------------------
home_cache = wv.phone_cache(UDID)                                                          # noqa: F821
import shutil
shutil.rmtree(home_cache, ignore_errors=True)
known = [di.AppSize("com.example.app00", "Example App 00", 5, 6), di.AppSize("com.example.gone", "Gone", 7, 8)]
merged = phoneapps.with_names({"com.example.app00": "Example App 00", "com.example.new": "New"}, known)
check([(a.bundle, a.total, a.sized) for a in merged] == [("com.example.app00", 11, False), ("com.example.new", 0, False)],  # noqa: F821
      "names first: an app's known size is kept until its new size comes in; new apps have none yet; removed apps go")
phoneapps.with_sizes(merged, {"com.example.new": (3, 4)})
check(merged[1].total == 7 and merged[1].sized and not merged[0].sized, "sizes are filled in as they arrive")     # noqa: F821
check([len(c) for c in phoneapps.chunks(phoneapps.with_names(NAMES, []))] == [20, 20, 5], "sizes asked for 20 apps at a time")  # noqa: F821
check(phoneapps.load_saved(UDID) == ([], "") and phoneapps.load_saved(None) == ([], ""), "nothing saved yet: nothing shown")  # noqa: F821
check(str(phoneapps.saved_file(UDID)).startswith(str(Path(os.environ["PHONEKEEP_HOME"]))),                    # noqa: F821
      "the saved list is kept in PhoneKeep's own folder on this computer")

# -- the phone window ---------------------------------------------------------------------------------------------
calls = {"overview": [], "names": 0, "sizes": [], "wallpaper": 0}
OV = dict(total=128 * G, free=78 * G)


def overview(udid=None, apps=True, timeout=180, wifi=False):
    calls["overview"].append({"apps": apps, "wifi": wifi})
    return di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", **OV)


class FastDevice(SimulatedDevice):                                                       # noqa: F821
    def wallpaper(self, which="homescreen"):
        calls["wallpaper"] += 1
        return super().wallpaper(which)

    def app_names(self, timeout=60):
        calls["names"] += 1
        return dict(NAMES)

    def app_sizes(self, bundles, timeout=120):
        calls["sizes"].append((len(bundles), timeout))
        time.sleep(0.3)
        return {b: SIZES[b] for b in bundles}


wv.device_overview = overview                                                            # noqa: F821
devmod.LiveDevice = FastDevice                                                           # noqa: F821
app = FakeApp()                                                                          # noqa: F821


def settle(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def open_window(conn):
    w = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": conn, "ProductVersion": "26.5"}, UDID)  # noqa: F821
    pump(app, lambda: w.overview is not None and w.live is not None, 30, "overview")    # noqa: F821
    return w


t0 = time.time()
win = open_window("USB")
check(win.overview is not None and calls["overview"][-1] == {"apps": False, "wifi": False},                 # noqa: F821
      f"the overview (battery, storage, details) comes without the app list, shown at once ({time.time() - t0:.1f} s)")
check(calls["names"] == 0 and not calls["sizes"], "opening the window doesn't ask for the app list")          # noqa: F821
pump(app, lambda: win.wall_img is not None, 10, "wallpaper")                             # noqa: F821
check(calls["wallpaper"] >= 1 and wv.phone_picture(UDID).exists(),                                    # noqa: F821
      "over a cable the wallpaper is read, and a copy kept for Wi-Fi")

overview_ui.storage_view(win, win.overview)
pump(app, lambda: win._apps_list is not None, 10, "names")                               # noqa: F821
note = win.apps_note.cget("text") if getattr(win, "apps_note", None) else ""
check(calls["names"] == 1 and len(win.overview.apps) == 45 and "updating sizes…" in note,                     # noqa: F821
      f"Storage opened: the app names at once, with '{note}'")
pump(app, lambda: win._apps_state == "done", 30, "sizes")                                # noqa: F821
settle(0.3)
check([n for n, _t in calls["sizes"]] == [20, 20, 5] and all(a.sized for a in win.overview.apps)              # noqa: F821
      and win.overview.largest_apps(1)[0].name == "Example App 44", "then the sizes, 20 apps at a time, biggest first")
check(win.current == "storage" and getattr(win, "apps_note").cget("text") == "",                              # noqa: F821
      "when every size is in, the note goes")
saved, when = phoneapps.load_saved(UDID)                                                 # noqa: F821
check(len(saved) == 45 and when, f"the full list is saved for this phone ({when})")      # noqa: F821
overview_ui.storage_view(win, win.overview)
check(calls["names"] == 1, "read once per window")                                      # noqa: F821
win.close()

# next time: the saved list at once, marked with its date, refreshed quietly
calls["sizes"].clear()
win = open_window("USB")
check(len(win.overview.apps) == 45 and win.overview.apps_as_of == when and calls["names"] == 1,               # noqa: F821
      "next time: the saved list is there before anything is asked")
overview_ui.storage_view(win, win.overview)
settle(0.2)
note = win.apps_note.cget("text")
check(note == f"App sizes from {when} · updating sizes…", f"marked with its date while it's refreshed: '{note}'")  # noqa: F821
pump(app, lambda: win._apps_state == "done", 30, "refresh")                              # noqa: F821
check(calls["names"] == 2 and win.overview.apps_as_of == "", "then refreshed quietly")  # noqa: F821
win.open_app("apps")
check(win._apps_state == "done", "opening Apps asks for the list too (already here: not again)")              # noqa: F821
win.close()

# over Wi-Fi
calls["wallpaper"], calls["sizes"] = 0, []
win = open_window("Network")
pump(app, lambda: win.wall_img is not None, 10, "saved wallpaper")                       # noqa: F821
check(calls["overview"][-1] == {"apps": False, "wifi": True} and calls["wallpaper"] == 0 and win.wall_img is not None,  # noqa: F821
      "over Wi-Fi: the overview is asked for in its Wi-Fi way, the wallpaper isn't asked for, the saved one is shown")
overview_ui.storage_view(win, win.overview)
pump(app, lambda: win._apps_state == "done", 30, "Wi-Fi sizes")                          # noqa: F821
check(calls["sizes"] and all(t <= 30 for _n, t in calls["sizes"]), "over Wi-Fi each size query has a short timeout")  # noqa: F821
win.close()

# the main window's card over Wi-Fi: the saved wallpaper, a short battery timeout
import app as appmod
made, bat = [], []
devmod.LiveDevice = lambda *a, **k: made.append(1)                                        # noqa: F821
wv.battery_state = lambda udid=None, timeout=60: bat.append(timeout) or {"level": 50, "charging": False}  # noqa: F821
fake = types.SimpleNamespace(_phone_extra={}, devices=[{"UniqueDeviceID": UDID, "ConnectionType": "Network"}],  # noqa: F821
                             call=lambda f: None)
appmod.App._read_phone_extra(fake, UDID)                                                 # noqa: F821
check(not made and bat == [wv.WIFI_TIMEOUT // 3] and fake._phone_extra[UDID]["battery"]["level"] == 50,     # noqa: F821
      "main window over Wi-Fi: no wallpaper asked for; the battery with a short timeout")

# device_overview: Wi-Fi flag, short timeout, the battery details from the last cable time
import subprocess
runs = []
RAW = {"info": {"DeviceName": "Test iPhone", "ProductType": "iPhone17,3"}, "disk": {"TotalDiskCapacity": 128 * G,
       "TotalDataAvailable": 78 * G}, "battery": {}, "problems": {}}


def fake_run(cmd, **k):
    runs.append((cmd, k.get("timeout")))
    raw = dict(RAW, battery_io={"CycleCount": 99, "DesignCapacity": 4000, "NominalChargeCapacity": 3600}) \
        if "--wifi" not in cmd else dict(RAW, problems={"battery_io": "over Wi-Fi"})
    return types.SimpleNamespace(stdout="PKOVERVIEW " + json.dumps(raw), returncode=0)


real_run, phonekeep.subprocess.run = phonekeep.subprocess.run, fake_run
try:
    cable = REAL_OVERVIEW(UDID, apps=False)                                              # noqa: F821
    air = REAL_OVERVIEW(UDID, apps=False, wifi=True)                                     # noqa: F821
finally:
    phonekeep.subprocess.run = real_run
check("--no-apps" in runs[0][0] and "--wifi" not in runs[0][0] and "--wifi" in runs[1][0]
      and runs[1][1] <= phonekeep.WIFI_TIMEOUT, "the overview: no app list; over Wi-Fi in its Wi-Fi way with a short timeout")  # noqa: F821
check(cable.battery.cycles == 99 and air is not None and air.battery.cycles == 99,
      "over Wi-Fi the battery details are the saved copy from the last cable connection")  # noqa: F821
lsrc = (HERE.parent / "launcher.py").read_text(encoding="utf-8")
i = lsrc.index("def _pk_overview")
body = lsrc[i:lsrc.index("\ndef ", i + 10)]
check("if wifi:" in body and body.index("if wifi:") < body.index("DiagnosticsService(ld)")
      and "asyncio.wait_for(make(conn[\"lockdown\"]), limit)" in body,
      "launcher over Wi-Fi: no IORegistry, each query with a short timeout")             # noqa: F821

# the timing log: only when asked for, step names and seconds only
log = W / "timing-test.log"                                                              # noqa: F821
log.unlink(missing_ok=True)
os.environ.pop("PHONEKEEP_TIMING", None)
with timing.step("a step"):
    pass
check(not log.exists(), "no timing log unless it's asked for")                         # noqa: F821
os.environ["PHONEKEEP_TIMING"] = str(log)
with timing.step("a step"):
    pass
parts = log.read_text(encoding="utf-8").strip().split("\t")
check(len(parts) == 5 and parts[2] == "a step" and parts[4] == "ok", "the timing log: a step's name and its seconds")  # noqa: F821
os.environ.pop("PHONEKEEP_TIMING", None)

app.destroy()
print("\nFAST OVERVIEW TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)  # noqa: F821
os._exit(1 if failures else 0)
