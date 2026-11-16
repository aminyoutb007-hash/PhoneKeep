"""5.1.3: the iPhone's home screen in the main window's small phone picture, like the phone window.

With an invented home screen (never a real one), checks:
- the small phone shows the saved home screen in its dark frame; with none saved, the drawn phone with a tick;
- searching dims it and shows a small spinner; not connected dims it and shows a "not connected" badge;
- over a cable a fresh home screen is read once (read-only) and quietly replaces the saved one; over Wi-Fi it isn't
  asked for and the saved one shows at once;
- the phone window shows the saved home screen at once instead of a plain green screen;
- the saved picture is in PhoneKeep's own folder (the tests' folder here), never in the repo.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
from PIL import Image

W = HERE / "work" / "main-wallpaper"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


PHONE = {"DeviceName": "Test iPhone", "UniqueDeviceID": "00008030-MAINWALL", "ConnectionType": "USB",
         "ProductVersion": "26.5", "ProductType": "iPhone15,3"}
UD = PHONE["UniqueDeviceID"]
shutil.rmtree(wv.phone_cache(UD), ignore_errors=True)


def invented(colour, name):
    """An invented home screen: two coloured halves, nothing from a real phone."""
    p = W / name
    im = Image.new("RGB", (390, 844), colour)
    im.paste((250, 250, 250), (0, 422, 390, 844))
    im.save(p)
    return p


check(str(wv.phone_picture(UD)).startswith(str(Path(os.environ["PHONEKEEP_HOME"]))),
      "the saved home screen is kept in PhoneKeep's own folder")
repo = subprocess.run(["git", "ls-files"], cwd=HERE.parent, capture_output=True, text=True).stdout.split()
check(not any(f.endswith("homescreen.png") for f in repo), "no saved home screen is in the repo")

import tkinter as tk
import app as appmod
import device as devmod
import theme

reads = []


class Live:
    """A stand-in phone: its home screen is an invented picture."""
    def __init__(self, udid, cache_dir=None):
        reads.append(udid)

    def wallpaper(self, which="homescreen"):
        return invented((30, 90, 200), "fresh.png") if which == "homescreen" else None

    def close(self):
        pass


REAL_LIVE = devmod.LiveDevice
devmod.LiveDevice = Live
reach = {"devs": [PHONE]}
wv.list_devices = lambda: list(reach["devs"])
wv.battery_state = lambda udid=None, **k: None
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"backup_dir": str(W / "Backups"), "first_run_done": True}), encoding="utf-8")
a = appmod.App()
a.withdraw()


def pump(until, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    return False


icon = a.phone

# no picture saved yet: the drawn phone
reach["devs"] = []
a.detect(silent=True)
pump(lambda: icon.state == "none")
check(icon.picture is None and not icon.find_withtag("picture") and not icon.find_withtag("badge"),
      "no picture saved yet: the drawn phone, as before")
check(icon.state == "none" and any(icon.itemcget(i, "text") == "?" for i in icon.find_all() if icon.type(i) == "text"),
      "  and not connected shows the drawn phone's '?'")

# over Wi-Fi with a saved picture: shown at once, nothing asked for
invented((200, 60, 60), "saved.png")
wv.keep_phone_picture(UD, W / "saved.png")
reach["devs"] = [dict(PHONE, ConnectionType="Network")]
a.detect(silent=True)
pump(lambda: icon.state == "ok")
check(icon.picture == wv.phone_picture(UD) and icon.find_withtag("picture") and not reads,
      "over Wi-Fi: the saved home screen shows at once and nothing is asked of the phone")
check(icon.itemcget(icon.find_withtag("picture")[0], "image") == str(icon._imgs["full"]),
      "connected: the picture at full strength in the dark frame")

# searching: dimmed, a small spinner
a.busy = True                         # the app's own regular look for the phone waits meanwhile
icon.set_state("searching")
pump(lambda: False, 0.3)
check(icon.itemcget(icon.find_withtag("picture")[0], "image") == str(icon._imgs["dim"]) and icon.find_withtag("spinner"),
      "searching: the picture dimmed, with a small spinner")
spin0 = icon._spin
pump(lambda: icon._spin != spin0, 2)
check(icon._spin != spin0, "  and the spinner turns")
a.busy = False

# at start-up: searching before any picture, then the saved picture comes (the app's first look, about 300 ms in)
fresh = appmod.PhoneIcon(a, theme.CARD)
pump(lambda: False, 0.3)
check(fresh.state == "searching" and not fresh._spinning, "start-up: searching with no picture yet (the drawn phone)")
fresh.set_picture(wv.phone_picture(UD))
spin1 = fresh._spin
pump(lambda: fresh._spin != spin1, 2)
check(fresh._spin != spin1 and fresh.find_withtag("spinner"),
      "  the saved picture comes while searching: the spinner turns from the start")
fresh.destroy()

# not connected: dimmed, a badge
a.s["chosen_udid"] = UD
reach["devs"] = []
a.detect(silent=True)
pump(lambda: icon.state == "none")
badge = icon.find_withtag("badge")
check(icon.picture is not None and icon.itemcget(icon.find_withtag("picture")[0], "image") == str(icon._imgs["dim"])
      and badge and icon.itemcget(badge[0], "text") == "not connected" and not icon.find_withtag("spinner"),
      "not connected: the last phone's picture dimmed, with a small 'not connected' badge")

# over a cable: a fresh home screen quietly replaces the saved one
def corner():
    """The saved picture's corner colour; the file is closed at once (Windows can't replace a file held open)."""
    try:
        with Image.open(wv.phone_picture(UD)) as im:
            return im.getpixel((5, 5))
    except OSError:                          # caught between the app's write and its rename
        return None


before = corner()
reach["devs"] = [PHONE]
a.detect(silent=True)
pump(lambda: reads and corner() not in (before, None), 10)
pump(lambda: False, 0.3)
check(reads == [UD] and corner() == (30, 90, 200),
      "over a cable: a fresh home screen is read from this phone and replaces the saved one")
check(icon.state == "ok" and icon.picture == wv.phone_picture(UD), "  and the small phone shows the fresh one")
a.detect(silent=True)
pump(lambda: False, 0.5)
check(reads == [UD], "read once per session, not on every look for the phone")

# a try that can't connect (the phone locked or gone; tried again every minute) leaves nothing behind
import asyncio, threading
import pymobiledevice3.lockdown as pmd_lockdown
import quicklook


async def no_phone(serial=None, **k):
    raise ConnectionRefusedError("no phone here")
real_connect, pmd_lockdown.create_using_usbmux = pmd_lockdown.create_using_usbmux, no_phone
threads, folders = threading.active_count(), len(list(quicklook.private_dir().iterdir()))
for _ in range(3):
    try:
        REAL_LIVE("00008030-NOPHONE")
    except Exception:
        pass
pump(lambda: threading.active_count() <= threads, 3)
pmd_lockdown.create_using_usbmux = real_connect
check(threading.active_count() <= threads and len(list(quicklook.private_dir().iterdir())) == folders,
      "a try that can't connect leaves no thread and no folder behind")

# the phone window: the saved picture at once, not a plain green screen
import phone


class NeverConnects:
    def __init__(self, udid, cache_dir=None):
        time.sleep(5)
        raise ConnectionError("not now")


devmod.LiveDevice = NeverConnects
wv.device_overview = lambda udid=None, apps=True, **k: None
win = phone.PhoneWindow(a, PHONE, UD)
check(win.wall_img is not None, "the phone window shows the saved home screen at once (before any connection)")
win.live_runner.stop()
win.destroy()
a.destroy()
print("\nMAIN WALLPAPER TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)
os._exit(1 if failures else 0)
