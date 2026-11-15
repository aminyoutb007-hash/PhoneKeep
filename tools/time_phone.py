"""How long a phone takes to appear and fill in (5.1.3, faster Wi-Fi): seconds per step, from "phone seen by usbmux"
to "window fully filled". Read-only for the phone; prints step names and seconds only (no names, no values).

    .venv/bin/python tools/time_phone.py            the phone as it's reachable now (cable or Wi-Fi)
    .venv/bin/python tools/time_phone.py --udid X   this phone, when more than one is reachable

With more than one iPhone reachable and no --udid, it times the one with backups in PhoneKeep's backups folder, and
stops if that isn't exactly one: it never picks a phone by chance.

It runs PhoneKeep's own code the way the app does: the main window's phone card (wallpaper and battery), then the
phone window (connection, wallpaper, the overview: battery and storage), then Storage (the app list: names, then sizes). The timing log goes to a temporary
file, deleted at the end. Nothing is written to the phone or to PhoneKeep's folder, and nothing leaves the computer.

It never opens a backup (the phone window gets an empty backups folder), so nothing is decrypted. Anything PhoneKeep's
code puts in its private temporary folder is deleted when the tool ends, also on an error, Ctrl-C or a stop signal; and
what a run that was killed outright left behind is deleted when the tool next starts, the way PhoneKeep does.
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REAL_HOME = Path(os.environ.get("PHONEKEEP_HOME") or Path.home() / "PhoneKeep")
try:                                    # only to tell which phone is backed up here (folders by UDID; none opened)
    import json
    BACKUPS = Path(json.loads((REAL_HOME / "settings.json").read_text(encoding="utf-8")).get("backup_dir")
                   or REAL_HOME / "Backups")
except (OSError, ValueError, AttributeError):
    BACKUPS = REAL_HOME / "Backups"
WANT = sys.argv[sys.argv.index("--udid") + 1] if "--udid" in sys.argv else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _clean_stale_work():
    """Work folders of earlier runs that were stopped outright (named by their process; older ones without)."""
    for d in Path(tempfile.gettempdir()).glob("pk-timing-*"):
        pid = d.name.split("-")[2]
        if not (pid.isdigit() and _alive(int(pid))):
            shutil.rmtree(d, ignore_errors=True)


_clean_stale_work()
WORK = Path(tempfile.mkdtemp(prefix=f"pk-timing-{os.getpid()}-"))
LOG = WORK / "timing.log"
os.environ["PHONEKEEP_HOME"] = str(WORK / "home")          # nothing written to the real PhoneKeep folder
os.environ["PHONEKEEP_TIMING"] = str(LOG)
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import quicklook                                            # noqa: E402

quicklook.cleanup_stale()               # what an earlier run (or PhoneKeep) stopped outright left behind


def _clean():
    quicklook.cleanup()                 # this run's private temporary folder
    shutil.rmtree(WORK, ignore_errors=True)


atexit.register(_clean)                 # runs on a normal end, an error and Ctrl-C (KeyboardInterrupt)
signal.signal(signal.SIGINT, signal.default_int_handler)    # Ctrl-C stops it even when started in the background
for _sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
    if _sig is not None:
        signal.signal(_sig, lambda *_a: sys.exit(1))       # a stop signal: end normally, so the clean-up runs

import tkinter as tk                                        # noqa: E402

import phonekeep as wv                                      # noqa: E402
import phone                                                # noqa: E402
import timing                                               # noqa: E402


class App(tk.Tk):
    """What the phone window needs from the main window."""
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(WORK / "Backups"),      # empty: no backup is opened, nothing decrypted
                  "archive_dir": str(WORK / "Archive")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass

    def confirm_private(self, then, reason=""):
        pass


def pump(root, until, timeout):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


T0 = time.perf_counter()


def mark(what):
    timing.log("= " + what, time.perf_counter() - T0, "since start")


devs = wv.list_devices()
mark("phone seen (usbmux list)")
if not devs:
    sys.exit("No iPhone reachable. Plug it in (or put it on the same Wi-Fi), unlock it, then run this again.")
def udid_of(d):
    return d.get("UniqueDeviceID") or d.get("Identifier")


if WANT:
    devs = [d for d in devs if udid_of(d) == WANT]
elif len(devs) > 1:
    import snapshots as sn                                  # noqa: E402
    devs = [d for d in devs if sn.latest_backup_path(BACKUPS, udid_of(d))]
if len(devs) != 1:
    sys.exit("More than one iPhone is reachable (or not the one asked for). Run again with --udid <the iPhone's UDID>.")
dev = devs[0]
how = "USB" if dev.get("ConnectionType") == "USB" else "Wi-Fi"
udid = dev.get("UniqueDeviceID") or dev.get("Identifier")
print(f"Timing the iPhone over {how}. This takes up to a few minutes.", flush=True)

# the main window's phone card: its wallpaper and battery (App._read_phone_extra); over Wi-Fi the app uses the
# saved wallpaper and asks the phone for the battery only, with a short timeout
import device as devmod                                     # noqa: E402
if how == "USB":
    try:
        live = devmod.LiveDevice(udid)
        try:
            live.wallpaper("lockscreen") or live.wallpaper("homescreen")
        finally:
            live.close()
    except Exception:
        pass
    wv.battery_state(udid)
else:
    wv.battery_state(udid, timeout=wv.WIFI_TIMEOUT)
mark("main window: phone card filled")

# the phone window
app = App()
t = time.perf_counter()
win = phone.PhoneWindow(app, dev, udid)
win.crashes_read = True
win.withdraw()
pump(app, lambda: win.live is not None or win.live_error, 120)
mark("phone window: connected")
# the wallpaper (over a cable only: over Wi-Fi it isn't asked for) and the overview arrive independently; each is
# marked when it happens
want_wall = how == "USB"
seen = set()


def watch():
    if want_wall and "wall" not in seen and win.wall_img is not None:
        seen.add("wall")
        mark("phone window: wallpaper shown")
    if "ov" not in seen and (win.overview is not None or win.overview_problem):
        seen.add("ov")
        mark("phone window: battery and storage shown" if win.overview is not None else "phone window: overview failed")
    return "ov" in seen and ("wall" in seen or not want_wall)


pump(app, watch, 300)
if want_wall and "wall" not in seen:
    mark("phone window: no wallpaper (gave up)")
mark("phone window: filled (all but the app list)")
# the app list, as when Storage is opened: names first, then the sizes
if win.overview is not None:
    import overview_ui                                      # noqa: E402
    overview_ui.storage_view(win, win.overview)
    pump(app, lambda: win._apps_list is not None or not win._apps_state, 120)
    mark("Storage: app names shown")
    pump(app, lambda: win._apps_state != "loading", 300)
    mark("Storage: all app sizes in" if win._apps_state == "done" else "Storage: app sizes failed")
try:
    win.close()
except Exception:
    pass

# the table: steps (seconds each) and when each milestone was reached
rows = [line.rstrip("\n").split("\t") for line in LOG.read_text(encoding="utf-8").splitlines()]
steps, marks = defaultdict(list), []
for _ts, _pid, name, secs, result in rows:
    if name.startswith("= "):
        marks.append((name[2:], float(secs)))
    else:
        steps[name].append((float(secs), result))
print(f"\nOver {how}: seconds per step")
print(f"{'step':48} {'seconds':>8}  result")
for name, runs in steps.items():
    for secs, result in runs:
        print(f"{name:48} {secs:8.2f}  {result}")
print(f"\nOver {how}: time since the start")
for name, secs in marks:
    print(f"{name:48} {secs:8.2f}")
_clean()
