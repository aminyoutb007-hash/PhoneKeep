"""Fix (5.2): a quick failing app-list read made the Storage screen redraw and ask again for ever.

The Storage screen asks the iPhone for its app list (5.1.3). When that ask failed straight away (for example a
Wi-Fi link that's dropping), the failure redrew Storage, the redraw asked again, that failed again, and so on: the
window stopped responding. With a fake iPhone whose app list always fails (nothing talks to a real phone), checks:
- a failed ask redraws Storage once and doesn't ask again: the window keeps answering;
- redrawing Storage (sizes arriving, the overview coming back) doesn't ask again either;
- opening Storage again (from another screen) asks again, and a list that now answers is shown;
- the same for the Check-up's Storage card, whose suggestions ask for the app list too;
- opening Apps after a failure asks again (opening it is always the user's choice).
"""
import copy, os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821
faulthandler.dump_traceback_later(90, exit=True)    # the loop this checks hangs the window: fail, don't wait   # noqa: F821

import deviceinfo as di
import overview_ui

G = 1000 ** 3
apps = [di.AppSize(f"com.example.app{i:02d}", f"Example App {i:02d}", (5 - i) * G, G // 10) for i in range(3)]  # invented
OV = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=128 * G, free=60 * G, apps=list(apps))
asked = {"n": 0, "fail": True}


class Failing(SimulatedDevice):                                                          # noqa: F821
    def app_names(self, timeout=60):
        asked["n"] += 1
        if asked["fail"]:
            raise wv.PhoneKeepError("the link dropped")                                  # noqa: F821
        return {a.bundle: a.name for a in apps}

    def app_sizes(self, bundles, timeout=120):
        return {a.bundle: (a.app_bytes, a.data_bytes) for a in apps if a.bundle in bundles}


wv.device_overview = lambda udid=None, apps=True, **k: copy.copy(OV)                    # noqa: F821
devmod.LiveDevice = Failing                                                              # noqa: F821
app = FakeApp()                                                                          # noqa: F821
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": "USB", "ProductVersion": "26.5"}, UDID)  # noqa: F821
pump(app, lambda: win.overview is not None and win.live is not None, 30, "overview")    # noqa: F821
win.overview.apps, win.overview.apps_as_of = list(apps), ""   # this test's apps, not a list another test saved


def settle(seconds=2.0):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.01)


overview_ui.storage_view(win, win.overview)
settle()
check(asked["n"] == 1 and win._apps_state == "" and win.current == "storage",                         # noqa: F821
      f"a failed app list is asked for once, not again and again ({asked['n']} asks in 2 s)")
t = time.time()
app.update()
check(time.time() - t < 0.5, "  the window keeps answering")                                         # noqa: F821
overview_ui.storage_view(win, win.overview)              # redrawn (sizes arriving, the overview coming back)
win._apps_refresh(force=True)
settle(1)
check(asked["n"] == 1, f"redrawing Storage doesn't ask again ({asked['n']} asks)")                     # noqa: F821
check(any(isinstance(c, tk.Widget) for c in win.content.winfo_children()), "  and Storage is still shown")  # noqa: F821

win.show_home()
asked["fail"] = False
overview_ui.storage_view(win, win.overview)              # opened again from another screen
pump(app, lambda: win._apps_state == "done", 30, "list")                                 # noqa: F821
check(asked["n"] == 2 and win._apps_state == "done" and not win._apps_failed,                          # noqa: F821
      f"opening Storage again asks again, and the list that answers now is shown ({asked['n']} asks)")
overview_ui.storage_view(win, win.overview)
settle(0.5)
check(asked["n"] == 2, "  once it's here it isn't asked for again")                                  # noqa: F821

# the same from the Check-up's Storage card (its suggestions ask for the app list too)
import checkup_ui
win.show_home()
asked.update(n=0, fail=True)
win._apps_state, win._apps_list = "", None                # as if this window had never asked
win.overview.apps = list(apps)
checkup_ui.details(win, "storage")
settle()
check(asked["n"] == 1 and win.current == "checkup:storage",                                           # noqa: F821
      f"Check-up → Storage: a failed app list is asked for once ({asked['n']} asks in 2 s)")
checkup_ui.details(win, "storage")                       # redrawn
win._apps_refresh(force=True)
settle(1)
check(asked["n"] == 1, f"  redrawing it doesn't ask again ({asked['n']} asks)")                        # noqa: F821
win.show_home()
asked["fail"] = False
checkup_ui.details(win, "storage")                       # opened again
pump(app, lambda: win._apps_state == "done", 30, "list")                                 # noqa: F821
check(asked["n"] == 2 and win._apps_state == "done", f"  opening it again asks again ({asked['n']} asks)")  # noqa: F821

# opening Apps (always the user's choice, never a redraw) asks again after a failure too
win.show_home()
asked.update(n=0, fail=True)
win._apps_state, win._apps_list = "", None
overview_ui.storage_view(win, win.overview)
settle(1)
win.show_home()
win.open_app("apps")
settle(1)
check(asked["n"] == 2, f"after a failed app list, opening Apps asks again ({asked['n']} asks)")             # noqa: F821

faulthandler.cancel_dump_traceback_later()                                              # noqa: F821
win.destroy()
print("\nSTORAGE LOOP TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures))  # noqa: F821
sys.exit(1 if failures else 0)
