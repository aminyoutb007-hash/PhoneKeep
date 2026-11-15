"""V6 (5.2): Storage tips. Under Storage → Largest apps, every app has a line on how to free the space it takes.

With a fake iPhone and invented apps (nothing talks to a real phone), checks:
- by default: "Offload on the iPhone: Settings → General → iPhone Storage → <app> → Offload App";
- for common big apps (by bundle ID) the app's own way first (e.g. YouTube's downloads), then offloading;
- every one of the 20 largest apps shows its line in the Storage screen;
- read-only: showing the tips asks the phone nothing more and PhoneKeep has no way to offload or delete an app.
"""
import os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821

import deviceinfo as di
import overview_ui
import storage_advice as sa

G = 1000 ** 3

# -- the lines ------------------------------------------------------------------------------------------------------
plain = sa.app_tip("com.example.notes", "Example Notes")
check(plain == ["Offload on the iPhone: Settings → General → iPhone Storage → Example Notes → Offload App "
                "(frees the app, keeps its documents and data)"],                          # noqa: F821
      f"an app with no known in-app way: offload on the iPhone, saying what it keeps ({plain[0]})")
yt = sa.app_tip("com.google.ios.youtube", "YouTube")
check(len(yt) == 2 and yt[0].startswith("In the app: YouTube → You → Downloads")                          # noqa: F821
      and yt[1] == ("Or offload it on the iPhone: Settings → General → iPhone Storage → YouTube → Offload App "
                    "(frees the app, keeps its documents and data)"),
      "a common big app: its own way first (YouTube's downloads), then offloading")
for bundle in ("com.tencent.xin", "com.spotify.client"):
    t = sa.app_tip(bundle, "X")
    check(len(t) == 2 and "Storage" in t[0], f"  {bundle}: its storage setting")                           # noqa: F821
check(all(" → " in v and v.endswith(".") for v in sa.IN_APP.values()), "every in-app way is written as steps")  # noqa: F821
check("iPhone Storage → the app → Offload App" in sa.app_tip("com.example.x", "")[0],                # noqa: F821
      "an app without a name still gets a readable line")

# -- the Storage screen -----------------------------------------------------------------------------------------------
names = [("YouTube", "com.google.ios.youtube"), ("WeChat", "com.tencent.xin"), ("Spotify", "com.spotify.client")]
names += [(f"Example App {i:02d}", f"com.example.app{i:02d}") for i in range(20)]                      # invented
apps = [di.AppSize(b, n, (30 - i) * G // 10, G // 20) for i, (n, b) in enumerate(names)]
OV = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=128 * G, free=60 * G, apps=apps)
asked = {"n": 0}


class Quiet(SimulatedDevice):                                                            # noqa: F821
    def app_names(self, timeout=60):
        asked["n"] += 1
        return {a.bundle: a.name for a in apps}

    def app_sizes(self, bundles, timeout=120):
        asked["n"] += 1
        return {a.bundle: (a.app_bytes, a.data_bytes) for a in apps if a.bundle in bundles}


wv.device_overview = lambda udid=None, apps=True, **k: OV                                # noqa: F821
devmod.LiveDevice = Quiet                                                                # noqa: F821
app = FakeApp()                                                                          # noqa: F821
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": "USB", "ProductVersion": "26.5"}, UDID)  # noqa: F821
pump(app, lambda: win.overview is not None and win.live is not None, 30, "overview")    # noqa: F821
win.overview.apps, win.overview.apps_as_of = list(apps), ""   # this test's apps, not a list another test saved
win._apps_state = "done"                      # the list is already here: showing the tips asks the phone nothing
before = asked["n"]
overview_ui.storage_view(win, win.overview)
app.update()
check(len(win.app_rows) == 20 and len(win.app_tips) == 20, "the 20 largest apps each have a 'how to free space' line")  # noqa: F821
check(win.app_tips[0].startswith("In the app: YouTube") and "Offload App" in win.app_tips[0],              # noqa: F821
      "  YouTube: its downloads, then offloading")
check(all(t.startswith(("Offload on the iPhone:", "In the app:")) for t in win.app_tips),                    # noqa: F821
      "  every line is steps on the phone")
labels = []


def texts(w):
    for c in w.winfo_children():
        try:
            labels.append(c.cget("text"))
        except Exception:
            pass
        texts(c)
texts(win.content)
check(sum(1 for t in labels if "Offload" in str(t)) == 20, "  and they're on the screen")                  # noqa: F821
# every one of the 20 can be reached in the window's normal size: the list scrolls, under the storage figures
win.geometry("1220x800")
app.update()
overview_ui.storage_view(win, win.overview)
app.update()
cv = getattr(win, "apps_canvas", None)        # the list's own scrolling area, when there is one


def shown(cell):
    """True when the whole of this app's cell is on screen: inside the window's content area and, if the list
    scrolls, inside its visible part."""
    for box in [win.content] + ([cv] if cv is not None else []):
        y0 = cell.winfo_rooty() - box.winfo_rooty()
        if y0 < 0 or y0 + cell.winfo_height() > box.winfo_height():
            return False
    return True


seen = set()
for k in range(0, 101, 5):
    if cv is not None:
        cv.yview_moveto(k / 100)
    app.update()
    seen |= {i for i, c in enumerate(win.app_cells) if shown(c)}
check(seen == set(range(20)), f"in the window's normal size every one of the 20 apps with its line can be seen "
      f"(scrolling the list): {len(seen)} of 20")                                         # noqa: F821
check(asked["n"] == before, "showing the tips asks the phone nothing")                                      # noqa: F821
import device as real_device
check(not any(hasattr(real_device.LiveDevice, m) for m in ("offload_app", "uninstall", "remove_app", "delete_app")),  # noqa: F821
      "read-only: PhoneKeep has no way to offload or delete an app itself")
win.close()
app.destroy()
print("\nSTORAGE TIPS TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)  # noqa: F821
os._exit(1 if failures else 0)
