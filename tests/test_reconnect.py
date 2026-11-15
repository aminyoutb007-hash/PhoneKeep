"""5.1.3: the iPhone unplugged and plugged back in (even into another USB port).

Before, the phone window kept its dead connection: the header still said "connected by USB cable" and Space on a
photo showed "ConnectionTerminatedError: Connection was terminated abruptly". Checks, with a fake iPhone:
- a live read whose connection drops once reconnects (same UDID) and retries once: the read works;
- a phone that stays gone: plain words ("The iPhone was disconnected. Plug it back in and try again."), never the
  exception's name, also in the Space preview; the header says "Not connected · plug your iPhone back in" in the
  warning colour; live-only sections show a calm "Plug your iPhone back in to see this"; the backup keeps working;
- the phone comes back (USB or Wi-Fi): a new connection by itself, the header updated, the open section reloaded;
- only this phone's UDID is ever asked for or connected to; another phone is never picked up in its place.
Nothing here talks to a real phone.
"""
import asyncio, os, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))

sys.path.insert(0, str(HERE.parent))
import photos
RealPhotoSource = photos.DevicePhotoSource          # the set-up below replaces it with a stand-in

# the phone window test's set-up (fake backup, simulated iPhone, FakeApp, pump, labels_in) without its test part
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()       # noqa: F821 - from the set-up

import errors
import theme
import reconnect as rc
import quicklook as ql


class ConnectionTerminatedError(Exception):      # pymobiledevice3's, by name
    pass


class NoDeviceConnectedError(Exception):
    pass


DROP = ConnectionTerminatedError("Connection was terminated abruptly")

# -- 1. retry once ----------------------------------------------------------------------------------------------------
class Conn:
    def __init__(self, drops, back=True):
        self.udid, self.generation, self.drops, self.back = UDID, 0, drops, back   # noqa: F821
        self.reconnects, self.calls = [], 0

    def reconnect(self, seen=None):
        self.reconnects.append(seen)
        if not self.back:
            raise NoDeviceConnectedError("no device")
        self.generation += 1

    @rc.retry_once
    def read(self):
        self.calls += 1
        if self.drops:
            self.drops -= 1
            raise DROP
        return b"photo"


once = Conn(drops=1)
check(once.read() == b"photo" and once.reconnects == [0] and once.calls == 2,        # noqa: F821
      "a connection that drops once: reconnect once, retry once, the read works")
gone = Conn(drops=9, back=False)
try:
    gone.read()
    got = None
except Exception as e:                                                                   # noqa: BLE001
    got = e
check(isinstance(got, rc.Disconnected) and str(got) == rc.DISCONNECTED and gone.calls == 1
      and errors.is_plain(str(got)), f"stays gone: one plain sentence, no exception name ({got})")              # noqa: F821
again = Conn(drops=9)
try:
    again.read()
except Exception as e:                                                                   # noqa: BLE001
    got = e
check(isinstance(got, rc.Disconnected) and again.calls == 2 and len(again.reconnects) == 1,          # noqa: F821
      "drops again after reconnecting: one retry only, then the plain sentence")


class Other(Conn):
    @rc.retry_once
    def read(self):
        raise ValueError("not a connection problem")


o = Other(0)
try:
    o.read()
except ValueError:
    pass
check(o.reconnects == [], "any other error is left as it is: no reconnect")            # noqa: F821
check(all(rc.is_dropped(e) for e in (DROP, BrokenPipeError(), ConnectionAbortedError(), ConnectionResetError(),
                                      NoDeviceConnectedError()))
      and not any(rc.is_dropped(e) for e in (RuntimeError("x"), ValueError("bad"), ConnectionError("read refused"))),
      "dropped connections are told apart from other errors")                           # noqa: F821
wrapped = RuntimeError("reading failed")
wrapped.__cause__ = DROP
check(rc.is_dropped(wrapped), "a dropped connection behind another error counts too")   # noqa: F821
check(errors.explain(DROP).message == rc.DISCONNECTED,
      "the errors table words a dropped connection the same way anywhere")             # noqa: F821

# -- the photo reader and the Space preview -----------------------------------------------------------------------
class DeadAfc:
    async def get_file_contents(self, path):
        raise DROP

    async def pull(self, src, dest, progress_bar=False):
        raise DROP

    async def __aexit__(self, *a):
        pass


class GoodAfc(DeadAfc):
    async def get_file_contents(self, path):
        return b"PHOTO:" + path.encode()


def photo_source(back):
    dps = RealPhotoSource.__new__(RealPhotoSource)
    ph.PhotoSource.__init__(dps, W / "reconnect-photos")                                 # noqa: F821
    dps.udid, dps.generation, dps._conn_lock = UDID, 0, threading.Lock()                 # noqa: F821
    dps.loop = asyncio.new_event_loop()
    threading.Thread(target=dps.loop.run_forever, daemon=True).start()
    dps.afc, dps._sizes, dps.asked = DeadAfc(), {}, []

    async def connect():
        dps.asked.append(dps.udid)
        if not back:
            raise NoDeviceConnectedError("no device")
        dps.afc = GoodAfc()
    dps._connect = connect
    return dps


p1 = photo_source(back=True)
check(p1.read("DCIM/100APPLE/IMG_0001.HEIC") == b"PHOTO:DCIM/100APPLE/IMG_0001.HEIC" and p1.asked == [UDID],  # noqa: F821
      "Space on a photo after the cable moved: reconnects to the same iPhone and shows it")
p2 = photo_source(back=False)
check(p2.read("DCIM/100APPLE/IMG_0002.HEIC") is None and p2.last_error == rc.DISCONNECTED,             # noqa: F821
      f"Space on a photo with the iPhone gone: the reason is the plain sentence ({p2.last_error})")
ql.cleanup()
app = root = FakeApp()                                                                   # noqa: F821
item = ql.Item("IMG_0002.HEIC", read=lambda: p2.read("DCIM/100APPLE/IMG_0002.HEIC"),
               why=lambda: p2.last_error, size=10)
viewer = ql.Viewer(root, [item], 0)                                                      # noqa: F821
pump(root, lambda: viewer.shown_kind == "error", 20, "the preview's message")            # noqa: F821
shown = " ".join(str(l.cget("text")) for l in labels_in(viewer.body))                    # noqa: F821
check(rc.DISCONNECTED in shown and "Error" not in shown and "terminated" not in shown,
      f"the preview says it in plain words: {shown!r}")                                  # noqa: F821
viewer.close()
for p in (p1, p2):
    p.loop.call_soon_threadsafe(p.loop.stop)

# -- 2. the phone window: gone, then back -------------------------------------------------------------------------
phone.WATCH_MS = 80                                                                      # noqa: F821
state = {"how": "USB"}
asked, made = [], []


class WatchedDevice(SimulatedDevice):                                                    # noqa: F821
    def __init__(self, udid, cache_dir=None):
        super().__init__(udid, cache_dir)
        made.append(self)

    def where(self):
        asked.append(self.udid)
        return state["how"]


devmod.LiveDevice = WatchedDevice                                                        # noqa: F821
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": "USB",  # noqa: F821
                                           "ProductVersion": "26.5"}, UDID)              # noqa: F821
pump(app, lambda: win.live is not None and win.where is not None, 30, "connected")       # noqa: F821
check(win.sub.cget("text") == "iOS 26.5 · connected by USB cable", f"connected: {win.sub.cget('text')}")      # noqa: F821
win.open_app("music")
pump(app, lambda: ("music",) in made[0].calls and not still_loading(win), 20, "music")   # noqa: F821

state["how"] = None                                                                      # unplugged
pump(app, lambda: not win.phone_here and not still_loading(win), 20, "gone")             # noqa: F821
check(win.sub.cget("text") == rc.GONE and str(win.sub.cget("fg")).upper() == theme.WARN_TEXT.upper(),  # noqa: F821
      f"unplugged: the header says '{win.sub.cget('text')}' in the warning colour")       # noqa: F821
texts = [str(l.cget("text")) for l in labels_in(win.content)]                            # noqa: F821
check(rc.PLUG_BACK in texts and not error_labels(win),                             # noqa: F821
      "the open live section (Music) says 'Plug your iPhone back in to see this', calmly, not as an error")
for key in ("books", "files"):
    win.open_app(key)
    pump(app, lambda: not still_loading(win), 10, key)                                   # noqa: F821
    texts = [str(l.cget("text")) for l in labels_in(win.content)]                        # noqa: F821
    check(rc.PLUG_BACK in texts and not error_labels(win), f"{key} while it's gone: the calm message")  # noqa: F821
win.open_app("contacts")
pump(app, lambda: win.data is not None and not still_loading(win), 30, "contacts")       # noqa: F821
texts = [str(l.cget("text")) for l in labels_in(win.content)]                            # noqa: F821
check(rc.PLUG_BACK not in texts and not error_labels(win), "data from the backup keeps working (Contacts)")  # noqa: F821
win.open_app("music")
pump(app, lambda: not still_loading(win), 10, "music while gone")                        # noqa: F821
n_before = len(made)

state["how"] = "USB"                                                                     # plugged into another port
pump(app, lambda: win.phone_here and len(made) > n_before and ("music",) in made[-1].calls, 20, "back")       # noqa: F821
check(win.sub.cget("text") == "iOS 26.5 · connected by USB cable"
      and str(win.sub.cget("fg")).upper() == theme.HEADER_TEXT.upper(),                  # noqa: F821
      "plugged back in: a new connection by itself, and the header says so")
pump(app, lambda: not still_loading(win), 10, "music reloaded")                          # noqa: F821
check(("music",) in made[-1].calls and win.current == "music" and not error_labels(win)  # noqa: F821
      and rc.PLUG_BACK not in [str(l.cget("text")) for l in labels_in(win.content)],                  # noqa: F821
      "the open section (Music) reloads from the new connection, no Refresh needed")
check(("close",) in made[0].calls, "the dead connection is closed")                     # noqa: F821

state["how"] = "Network"                                                                 # cable out, still on Wi-Fi
n_before = len(made)
pump(app, lambda: len(made) > n_before and win.live is made[-1], 20, "Wi-Fi")            # noqa: F821
check(win.sub.cget("text") == "iOS 26.5 · connected by Wi-Fi", f"over Wi-Fi: {win.sub.cget('text')}")       # noqa: F821
check(set(asked) == {UDID} and all(d.udid == UDID for d in made),                         # noqa: F821
      "only this iPhone's UDID is ever asked for or connected to")

# -- 4. never another phone ---------------------------------------------------------------------------------------
from pymobiledevice3 import usbmux
_real_list = usbmux.list_devices
listed = []


async def fake_list(usbmux_address=None):
    return listed


usbmux.list_devices = fake_list
try:
    listed[:] = [usbmux.MuxDevice(1, "00008110-0000000000OTHER", "USB")]
    check(rc.where(UDID) is None, "another iPhone on the cable doesn't count as this one")             # noqa: F821
    listed[:] = [usbmux.MuxDevice(1, "00008110-0000000000OTHER", "USB"), usbmux.MuxDevice(2, UDID, "Network")]  # noqa: F821
    check(rc.where(UDID) == "Network", "this iPhone over Wi-Fi is found by its UDID")                   # noqa: F821
    listed.append(usbmux.MuxDevice(3, UDID, "USB"))                                      # noqa: F821
    check(rc.where(UDID) == "USB", "on the cable and Wi-Fi: the cable")                                # noqa: F821
    check(rc.where(None) is None, "no UDID: nothing is looked for")               # noqa: F821
finally:
    usbmux.list_devices = _real_list
_src_dev = (HERE.parent / "device.py").read_text(encoding="utf-8") + (HERE.parent / "photos.py").read_text(encoding="utf-8")
check(_src_dev.count("create_using_usbmux(serial=self.udid)") == 2 and "create_using_usbmux()" not in _src_dev,
      "reconnecting always names this iPhone's UDID")                                    # noqa: F821

win.close()
app.destroy()
print("\nRECONNECT TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)  # noqa: F821
os._exit(1 if failures else 0)                                                           # noqa: F821
