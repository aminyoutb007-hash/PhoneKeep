"""5.1.3: over Wi-Fi a locked or dozing iPhone can hold back its storage answer (15 Nov: 3 runs out of 6 on the owner's
phone). One slow answer must never blank the rest. Checks, with a fake iPhone (nothing talks to a real phone):
- the overview helper: each question stands alone; when storage (or the phone's details) times out, everything else is
  still read and printed, on a fresh connection (a timed-out one is still waiting for its answer);
- the storage helper's second try gives up after its limit;
- the phone window: the rest shows at once, the Storage card says "Storage: waiting for the iPhone…" while storage is
  asked again (15 s); if it answers, the figures show; if not, "The iPhone didn't answer. It may be locked or
  asleep." with "Try again", and it's asked again by itself when the iPhone next answers anything (or after a while).
"""
import asyncio, contextlib, io, json, os, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
import launcher
import pymobiledevice3.lockdown as pmd_lockdown
_src = (HERE / "test_phone_window.py").read_text(encoding="utf-8")
exec(compile(_src.split("# the test\n")[0], str(HERE / "test_phone_window.py"), "exec"))
faulthandler.cancel_dump_traceback_later()                                              # noqa: F821

import deviceinfo as di
import overview_ui

G = 1000 ** 3
DISK = {"TotalDiskCapacity": 128 * G, "TotalDataCapacity": 120 * G, "TotalDataAvailable": 78 * G}
INFO = {"DeviceName": "Test iPhone", "ProductType": "iPhone17,1", "ProductVersion": "26.5", "SerialNumber": "TESTSERIAL1",
        "DeviceEnclosureColor": "1", "ModelNumber": "MTEST", "TotalDiskCapacity": 128 * G}
BATTERY = {"BatteryCurrentCapacity": 64, "BatteryIsCharging": False}


# -- the helpers, with a fake lockdown ---------------------------------------------------------------------------------
class FakeLockdown:
    """Hangs on the questions in `hang` (each one hangs `times` times, then answers). Like the real connection, once a
    question was given up on, the connection is spoiled: every later question on it is cancelled."""
    connects = 0
    hang, times = set(), {}

    def __init__(self):
        FakeLockdown.connects += 1
        self.spoiled = False

    async def get_value(self, key=None, domain=None):
        name = domain or key or "all"
        if self.spoiled:
            raise asyncio.CancelledError()
        if name in FakeLockdown.hang and FakeLockdown.times.get(name, 0) != 0:
            FakeLockdown.times[name] -= 1
            try:
                await asyncio.sleep(1000)
            finally:
                self.spoiled = True
        if domain == "com.apple.disk_usage":
            return dict(DISK)
        if domain == "com.apple.mobile.battery":
            return dict(BATTERY)
        return INFO.get(key) if key else dict(INFO)

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self.close()


async def fake_connect(serial=None, **k):
    return FakeLockdown()


pmd_lockdown.create_using_usbmux = fake_connect


def helper(fn, args, hang=(), times=1):
    FakeLockdown.connects, FakeLockdown.hang, FakeLockdown.times = 0, set(hang), {h: times for h in hang}
    out = io.StringIO()
    t = time.time()
    with contextlib.redirect_stdout(out):
        try:
            fn(args)
        except SystemExit:
            pass
    return out.getvalue(), time.time() - t


def overview_out(text):
    for line in text.splitlines():
        if line.startswith("PKOVERVIEW "):
            return json.loads(line[len("PKOVERVIEW "):])
    return None


text, secs = helper(launcher._pk_overview, ["--udid", "X", "--no-apps", "--wifi"], hang=["com.apple.disk_usage"])
raw = overview_out(text)
check(raw is not None and raw["info"].get("DeviceName") == "Test iPhone" and raw.get("battery") == BATTERY,     # noqa: F821
      f"storage times out over Wi-Fi: the phone's details and the battery are still read and printed ({secs:.1f} s)")
check(raw is not None and raw["problems"].get("disk", "").startswith("TimeoutError") and "disk" not in raw    # noqa: F821
      and "battery" not in raw["problems"], "  storage is noted as timed out, nothing else is")
ov = di.from_raw(raw)
check(ov.name == "Test iPhone" and ov.battery.level == 64 and ov.free is None and ov.total == 128 * G,         # noqa: F821
      "  the overview has the phone's details and battery, and no storage figures")

FakeLockdown.hang = set()
text, secs = helper(launcher._pk_overview, ["--udid", "X", "--no-apps", "--wifi"], hang=["all"])
raw = overview_out(text)
check(raw is not None and raw.get("battery") == BATTERY and raw.get("disk") == DISK                           # noqa: F821
      and raw["problems"].get("info", "").startswith("TimeoutError") and FakeLockdown.connects == 2,
      f"the phone's details time out: battery and storage are still read, on a fresh connection ({secs:.1f} s)")

text, secs = helper(launcher._pk_overview, ["--udid", "X", "--no-apps", "--wifi"], hang=["com.apple.mobile.battery"])
raw = overview_out(text)
check(raw is not None and raw.get("disk") == DISK and raw["problems"].get("battery", "").startswith("TimeoutError"),  # noqa: F821
      "the battery times out: storage is still read")

text, secs = helper(launcher._pk_overview, ["--udid", "X", "--no-apps"])
raw = overview_out(text)
check(raw is not None and raw.get("disk") == DISK and raw.get("battery") == BATTERY and FakeLockdown.connects == 1  # noqa: F821
      and set(raw["problems"]) <= {"battery_io"}, "nothing slow: everything on one connection, as before")

text, secs = helper(launcher._pk_storage, ["--udid", "X", "--limit", "1"], hang=["com.apple.disk_usage"])
check("PKDISK" not in text and "PKERR TimeoutError" in text and 0.9 < secs < 5,                              # noqa: F821
      f"the second try at storage gives up after its limit ({secs:.1f} s)")
text, secs = helper(launcher._pk_storage, ["--udid", "X", "--limit", "1"])
check(any(line.startswith("PKDISK ") and json.loads(line[7:]) == DISK for line in text.splitlines()),  # noqa: F821
      "  and prints the storage values when it's answered")

# -- tools/time_phone.py never leaves anything decrypted behind -------------------------------------------------------
tool = (HERE.parent / "tools" / "time_phone.py").read_text(encoding="utf-8")
app_block = tool[tool.index("class App("):tool.index("def pump(")]
check('"backup_dir": str(WORK / "Backups")' in app_block and "BACKUPS" not in app_block,  # noqa: F821
      "time_phone: the phone window gets an empty backups folder (no backup opened, nothing decrypted)")
check(tool.index("quicklook.cleanup_stale()") < tool.index("import phonekeep as wv"),  # noqa: F821
      "time_phone: at start, what a run stopped outright left behind is deleted")
check("atexit.register(_clean)" in tool and "quicklook.cleanup()" in tool and "signal.SIGTERM" in tool,       # noqa: F821
      "time_phone: its private folder is deleted on any end: normal, error, Ctrl-C or a stop signal")
check("_clean_stale_work()" in tool and 'prefix=f"pk-timing-{os.getpid()}-"' in tool                         # noqa: F821
      and tool.index("_clean_stale_work()\n") < tool.index('os.environ["PHONEKEEP_HOME"]'),
      "time_phone: work folders of runs stopped outright are deleted at the next start")

# -- the phone window --------------------------------------------------------------------------------------------------
calls = {"storage": 0}
mode = {"answers": True}
gate = threading.Event()


def overview(udid=None, apps=True, timeout=180, wifi=False):
    o = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=128 * G, free=None,
                    problems={"disk": "TimeoutError: "})
    o.battery = di.Battery(level=64, health=91, cycles=120)
    return o


def storage_values(udid=None, limit=wv.STORAGE_RETRY):                                   # noqa: F821
    calls["storage"] += 1
    calls["limit"] = limit
    gate.wait(10)
    return {"TotalDiskCapacity": 128 * G, "TotalDataAvailable": 78 * G} if mode["answers"] else None


wv.device_overview = overview                                                            # noqa: F821
wv.storage_values = storage_values                                                       # noqa: F821
devmod.LiveDevice = SimulatedDevice                                                      # noqa: F821
app = FakeApp()                                                                          # noqa: F821


def texts(w):
    out = []
    for c in w.winfo_children():
        try:
            out.append(c.cget("text"))
        except tk.TclError:                                                              # noqa: F821
            pass
        out += texts(c)
    return out


def strip_text(win):
    return " | ".join(t for t in texts(win.overview_strip) if t)


def open_window():
    gate.clear()
    w = phone.PhoneWindow(app, {"DeviceName": "Test iPhone", "ConnectionType": "Network", "ProductVersion": "26.5"}, UDID)  # noqa: F821
    pump(app, lambda: w.overview is not None and w.live is not None, 30, "overview")    # noqa: F821
    return w


# storage times out once; the second try answers
mode["answers"] = True
win = open_window()
s = strip_text(win)
check(win.storage_state == "waiting" and overview_ui.STORAGE_WAITING in s, f"storage timed out: the card says '{overview_ui.STORAGE_WAITING}'")  # noqa: F821
check("iPhone 16" in s and "about 91%" in s and "Charge now 64%" in s, "  and the phone's details and battery show at once")  # noqa: F821
gate.set()
pump(app, lambda: win.storage_state == "" and "78.0 GB free" in strip_text(win), 10, "second try")             # noqa: F821
check(calls["storage"] == 1 and calls["limit"] == 15 and win.overview.free == 78 * G and "78.0 GB free" in strip_text(win)
      and "disk" not in win.overview.problems, "the second try (15 s) answers: the storage figures show")    # noqa: F821
win.close()

# the phone is read again while the second try is still waiting (moved between cable and Wi-Fi, or back): the newer
# read gets its own try, and the card never stays on "waiting"
mode["answers"], calls["storage"] = False, 0
win = open_window()
first = win.overview
win._read_overview()
pump(app, lambda: win.overview is not first, 10, "newer read")                         # noqa: F821
gate.set()
pump(app, lambda: calls["storage"] == 2 and win.storage_state == "failed", 15, "both tries")  # noqa: F821
check(calls["storage"] == 2 and win.storage_state == "failed" and win.storage_try is not None
      and overview_ui.STORAGE_NO_ANSWER in strip_text(win),
      "read again while the second try waits: the newer read gets its own try; no answer ends in 'Try again'")  # noqa: F821
win.close()

# storage never answers
mode["answers"], calls["storage"] = False, 0
win = open_window()
gate.set()
pump(app, lambda: win.storage_state == "failed", 10, "no answer")                       # noqa: F821
s = strip_text(win)
check(overview_ui.STORAGE_NO_ANSWER in s and win.storage_try is not None and win.storage_try.winfo_exists(),  # noqa: F821
      f"no answer the second time: '{overview_ui.STORAGE_NO_ANSWER}' with 'Try again'")
check("iPhone 16" in s and "about 91%" in s and "Charge now 64%" in s, "  and the rest is filled")           # noqa: F821
check(calls["storage"] == 1, "  asked once more, not over and over")                    # noqa: F821
win.retry_storage()
check(win.storage_state == "waiting" and overview_ui.STORAGE_WAITING in strip_text(win), "'Try again': waiting again")  # noqa: F821
pump(app, lambda: win.storage_state == "failed", 10, "no answer again")                 # noqa: F821
check(calls["storage"] == 2, "  and asked again")                                       # noqa: F821
settle_until = time.time() + 4
pump(app, lambda: time.time() > settle_until, 6, "quiet")                                # noqa: F821
check(calls["storage"] == 2, "no answer and no sign of life: not asked again within the minute")              # noqa: F821
win.live.answered_at = time.time()                                                       # the iPhone answers something else
pump(app, lambda: calls["storage"] == 3, 8, "sign of life")                              # noqa: F821
check(calls["storage"] == 3, "the iPhone answers something else (awake or unlocked): storage is asked again by itself")  # noqa: F821
pump(app, lambda: win.storage_state == "failed", 10, "failed again")                     # noqa: F821
mode["answers"] = True
phone.STORAGE_AGAIN_S = 1                                                                # noqa: F821
pump(app, lambda: win.storage_state == "" and "78.0 GB free" in strip_text(win), 15, "after a while")           # noqa: F821
check(calls["storage"] == 4 and "78.0 GB free" in strip_text(win),
      "with no sign of life it's asked again after a while anyway; when it answers the figures show")      # noqa: F821
quiet_until = time.time() + 4                                                           # a minute is 1 s here
pump(app, lambda: time.time() > quiet_until, 6, "answered: quiet")                       # noqa: F821
check(calls["storage"] == 4 and win._storage_tick_id is None,
      "once storage has answered, it isn't asked again (the regular check stops)")       # noqa: F821
win.close()

app.destroy()
print("\nSTORAGE TIMEOUT TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)  # noqa: F821
os._exit(1 if failures else 0)
