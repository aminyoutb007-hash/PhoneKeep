"""5.1.3 (reviewer's findings on #59/#60): reads on a connection the window has let go of, and the app list's reads.

With a fake iPhone (nothing talks to a real phone), checks:
- once a LiveDevice or DevicePhotoSource is closed (the phone went), a read that was still waiting fails at once as a
  dropped connection, and new reads fail at once with the plain "disconnected" sentence, instead of hanging until their
  timeout (up to 10 minutes) and showing "TimeoutError";
- a connect that fails lets go of the photo source's thread;
- the app list's names and sizes reconnect once on a dropped connection, like the other live reads.
"""
import asyncio, os, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
import pymobiledevice3.lockdown as pmd_lockdown
import pymobiledevice3.services.afc as pmd_afc
import pymobiledevice3.services.installation_proxy as pmd_ip
import device as devmod
import photos as ph
import reconnect
from errors import DISCONNECTED

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


class FakeLockdown:
    async def get_value(self, key=None, domain=None):
        await asyncio.sleep(1000)                 # a question the phone never answers

    async def close(self):
        pass


state = {"connect_fails": False, "browse_drops": 0, "connects": 0}


async def fake_connect(serial=None, **k):
    state["connects"] += 1
    if state["connect_fails"]:
        raise ConnectionRefusedError("no phone here")
    return FakeLockdown()


class FakeAfc:
    def __init__(self, lockdown):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def listdir(self, path):
        await asyncio.sleep(1000)


class FakeProxy:
    def __init__(self, lockdown):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def browse(self, options=None, attributes=None):
        if state["browse_drops"]:
            state["browse_drops"] -= 1
            raise ConnectionAbortedError("connection was terminated")
        return [{"CFBundleIdentifier": "com.example.app01", "CFBundleDisplayName": "Example App 01"}]

    async def get_apps(self, **k):
        if state["browse_drops"]:
            state["browse_drops"] -= 1
            raise ConnectionAbortedError("connection was terminated")
        return {b: {"StaticDiskUsage": 100, "DynamicDiskUsage": 10} for b in k.get("bundle_identifiers") or []}


pmd_lockdown.create_using_usbmux = fake_connect
pmd_afc.AfcService = FakeAfc
pmd_ip.InstallationProxyService = FakeProxy
WORK = HERE / "work" / "closed-connection"
WORK.mkdir(parents=True, exist_ok=True)


def waiting_read(owner, run):
    """Start a read that never gets an answer; returns what it raised and how long it took."""
    out = {}

    def go():
        t = time.time()
        try:
            run()
        except BaseException as e:
            out["e"] = e
        out["s"] = time.time() - t
    th = threading.Thread(target=go, daemon=True)
    th.start()
    time.sleep(0.3)
    return th, out


# -- LiveDevice ---------------------------------------------------------------------------------------------------
live = devmod.LiveDevice("00008030-CLOSED", cache_dir=WORK / "live")
th, out = waiting_read(live, lambda: live.run(live.lockdown.get_value(domain="com.apple.disk_usage"), 600))
t = time.time()
live.close()
th.join(5)
check(not th.is_alive() and isinstance(out.get("e"), ConnectionAbortedError) and out["s"] < 5,
      f"LiveDevice closed: a read still waiting fails at once as a dropped connection ({out.get('s', 0):.1f} s)")
check(time.time() - t < 5, "  and closing doesn't wait for it")
t = time.time()
try:
    live.app_names(timeout=600)
    got = None
except Exception as e:
    got = e
check(isinstance(got, reconnect.Disconnected) and time.time() - t < 2,
      f"  a new read fails at once ({time.time() - t:.2f} s), as Disconnected")
check(str(got) == DISCONNECTED, f"  shown as the plain sentence, not 'TimeoutError': '{got}'")
import errors
check(errors.explain(ConnectionAbortedError("the connection was closed")).message == DISCONNECTED,
      "  and a dropped connection outside a retry reads the same plain sentence")

# the usual case after the phone goes: the one retry couldn't reconnect, so there's nothing left to close
live = devmod.LiveDevice("00008030-CLOSED", cache_dir=WORK / "live-nc")
th, out = waiting_read(live, lambda: live.run(live.lockdown.get_value(domain="com.apple.disk_usage"), 600))
live.lockdown = reconnect.NotConnected()
live.close()
th.join(5)
check(not th.is_alive() and isinstance(out.get("e"), ConnectionAbortedError) and out["s"] < 3,
      f"LiveDevice with nothing left to close: a waiting read still fails at once ({out.get('s', 0):.1f} s)")

# -- DevicePhotoSource ----------------------------------------------------------------------------------------------
src = ph.DevicePhotoSource("00008030-CLOSED", WORK / "photos")
th, out = waiting_read(src, lambda: src._run(src.afc.listdir("DCIM"), 600))
src.close()
th.join(5)
check(not th.is_alive() and isinstance(out.get("e"), ConnectionAbortedError) and out["s"] < 5,
      f"DevicePhotoSource closed: a read still waiting fails at once ({out.get('s', 0):.1f} s)")
t = time.time()
try:
    src._run(src.afc.listdir("DCIM"), 600)
    got = None
except BaseException as e:
    got = e
check(isinstance(got, ConnectionAbortedError) and reconnect.is_dropped(got) and time.time() - t < 2,
      "  a new read fails at once, as a dropped connection (so the window says so plainly)")

src = ph.DevicePhotoSource("00008030-CLOSED", WORK / "photos-nc")
afc = src.afc
th, out = waiting_read(src, lambda: src._run(afc.listdir("DCIM"), 600))
src.afc = reconnect.NotConnected()
src.close()
th.join(5)
check(not th.is_alive() and isinstance(out.get("e"), ConnectionAbortedError) and out["s"] < 3,
      f"DevicePhotoSource with nothing left to close: a waiting read still fails at once ({out.get('s', 0):.1f} s)")

state["connect_fails"] = True
threads = threading.active_count()
for _ in range(3):
    try:
        ph.DevicePhotoSource("00008030-CLOSED", WORK / "photos2")
    except Exception:
        pass
end = time.time() + 3
while threading.active_count() > threads and time.time() < end:
    time.sleep(0.05)
check(threading.active_count() <= threads, "a photo source that can't connect leaves no thread behind")
state["connect_fails"] = False

# -- the app list reconnects once -----------------------------------------------------------------------------------
live = devmod.LiveDevice("00008030-CLOSED", cache_dir=WORK / "live2")
state["browse_drops"], state["connects"] = 1, 0
names = live.app_names(timeout=10)
check(names == {"com.example.app01": "Example App 01"} and live.generation == 1 and state["connects"] == 1,
      "app names: a dropped connection reconnects once and the names come")
state["browse_drops"], state["connects"] = 1, 0
sizes = live.app_sizes(["com.example.app01"], timeout=10)
check(sizes == {"com.example.app01": (100, 10)} and live.generation == 2 and state["connects"] == 1,
      "app sizes: the same")
live.close()

print("\nCLOSED CONNECTION TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)
os._exit(1 if failures else 0)
