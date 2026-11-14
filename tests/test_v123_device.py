"""V1 device overview, V2 battery health, V3 storage usage (docs/spec/10-device.md).

Checked here with a stand-in iPhone (invented values); the real-iPhone checks against Settings are in the PR:
- V1 "Every value matches Settings → General → About": model from the phone's code, iOS, serial (click to copy),
  capacity as sold, free space, colour, last backup.
- V2 "Health within a point or two of Settings → Battery" (shown as "about"): worked out from the phone's own
  numbers, with the plain-words verdict, cycles, charge now, temperature, and "Save details" as JSON.
- V3 "Total, used and free exact; categories labelled about; Photos / Messages open those screens":
  categories add up to the capacity, the 20 largest apps are listed biggest first.
Also: reading the phone is read-only (the launcher only asks questions), and a missing section doesn't break the rest.
"""
import asyncio, json, os, sys, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

import deviceinfo as di

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


GBy = 1000 ** 3
RAW = {
    "info": {"DeviceName": "Test iPhone", "ProductType": "iPhone18,2", "ProductVersion": "26.1",
             "SerialNumber": "TESTSERIAL01", "DeviceEnclosureColor": "Deep Blue"},
    "disk": {"TotalDiskCapacity": 255_900_000_000, "TotalDataCapacity": 245_000_000_000, "TotalDataAvailable": 61_200_000_000},
    "battery": {"BatteryCurrentCapacity": 64, "BatteryIsCharging": True},
    "battery_io": {"CycleCount": 212, "DesignCapacity": 4832, "NominalChargeCapacity": 4410, "Temperature": 3050,
                   "BatteryData": {}},
    "apps": {f"com.example.app{i}": {"CFBundleDisplayName": f"Example App {i}", "StaticDiskUsage": (i + 1) * 100_000_000,
                                      "DynamicDiskUsage": (i % 3) * 250_000_000} for i in range(25)},
    "problems": {},
}

ov = di.from_raw(RAW)
check(ov.model == "iPhone 17 Pro Max" and ov.ios == "26.1" and ov.serial == "TESTSERIAL01" and ov.colour == "Deep Blue",
      f"V1: model, iOS, serial and colour from the phone ({ov.model}, {ov.ios}, {ov.colour})")
check(ov.capacity_label() == "256 GB" and ov.free == 61_200_000_000 and ov.used == 255_900_000_000 - 61_200_000_000,
      f"V1: capacity as Apple sells it ({ov.capacity_label()}); free and used are exact")
for t, want in ((63_000_000_000, "64 GB"), (127_800_000_000, "128 GB"), (511_000_000_000, "512 GB"),
                (1_022_000_000_000, "1 TB")):
    check(di.Overview(total=t).capacity_label() == want, f"capacity {t} → {want}")
hexov = di.from_raw({"info": {"DeviceEnclosureColor": "#3B3B3C", "DeviceColor": "1"}})
check(hexov.colour == "" and hexov.colour_hex == "#3b3b3c", "a colour given as a value is shown as a swatch, not a made-up name")
check(di.from_raw({"info": {"DeviceColor": "3"}}).colour == "", "a bare colour number shows nothing rather than a guess")

b = ov.battery
check(b.health == round(100 * 4410 / 4832) == 91 and b.cycles == 212 and b.level == 64 and b.charging and b.temperature == 30.5,
      f"V2: health {b.health}%, {b.cycles} cycles, charge {b.level}% charging, {b.temperature} °C")
check(b.verdict() == "Good: holds about 91% of its original charge", f"V2: the plain-words line ({b.verdict()})")
check(di.battery_from({"MaximumCapacityPercent": 88, "DesignCapacity": 4000, "NominalChargeCapacity": 3900}).health == 88,
      "V2: when the phone reports Settings' own number, that's the one shown")
check(di.battery_from({"DesignCapacity": 3000, "NominalChargeCapacity": 2000}).verdict().startswith("Needs a new battery"),
      "V2: a worn battery says so")
check(di.battery_from(None).health is None and "didn't report" in di.battery_from(None).verdict(),
      "V2: no battery details: says so, invents nothing")
j = json.loads(di.details_json(ov))
check(j["battery"]["health_percent_about"] == 91 and j["battery"]["cycle_count"] == 212 and j["model"] == "iPhone 17 Pro Max",
      "V2: Save details writes the numbers as JSON")

cats = di.categories(ov, photos_bytes=80 * GBy, messages_bytes=9 * GBy)
names = [c[0] for c in cats]
check(sum(c[1] for c in cats) == ov.total, f"V3: the categories add up to the capacity exactly ({names})")
check(names[:3] == ["Apps", "Photos", "Messages"] and cats[-1] == ("Free", ov.free, True)
      and all(not exact for n, _, exact in cats if n != "Free"), "V3: Free is exact, every other category is 'about'")
apps_total = sum(a.total for a in ov.apps)
check(dict((n, v) for n, v, _ in cats)["Apps"] == apps_total, "V3: Apps is the sum of what each app reports")
huge = di.categories(ov, photos_bytes=10 ** 13)
check(sum(c[1] for c in huge) == ov.total and all(c[1] >= 0 for c in huge), "V3: estimates bigger than the phone are scaled to fit")
top = ov.largest_apps()
check(len(top) == 20 and top == sorted(top, key=lambda a: a.total, reverse=True) and top[0].name == "Example App 23",
      f"V3: the 20 largest apps, biggest first ({top[0].name})")
half = di.from_raw({"info": RAW["info"], "disk": RAW["disk"], "problems": {"battery_io": "no", "apps": "no"}})
check(half.free == ov.free and half.battery.health is None and half.apps == [] and di.categories(half),
      "a section that couldn't be read leaves the rest working")
check(di.parse_output("noise\nPKOVERVIEW " + json.dumps(RAW) + "\n") == RAW and di.parse_output("PKERR x") is None,
      "the launcher's output line is read back")

# -- the launcher's --pk-overview, against a stand-in phone: it only asks questions -------------------------------
calls = []


class FakeLockdown:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get_value(self, domain=None, key=None):
        calls.append(("get_value", domain))
        return {None: RAW["info"], "com.apple.disk_usage": RAW["disk"], "com.apple.mobile.battery": RAW["battery"]}.get(domain, {})

    def __getattr__(self, name):           # anything else (set_value, remove_value, ...) would be a write
        calls.append(("OTHER", name))
        raise AttributeError(name)


class FakeService:
    def __init__(self, lockdown): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def ioregistry(self, plane=None, name=None, ioclass=None):
        calls.append(("ioregistry", ioclass))
        return dict(RAW["battery_io"], Serial="X")

    async def get_apps(self, application_type="Any", calculate_sizes=False, **k):
        calls.append(("get_apps", application_type, calculate_sizes))
        return RAW["apps"]


async def fake_usbmux(serial=None, **k):
    return FakeLockdown()

import pymobiledevice3.lockdown as pl, pymobiledevice3.services.diagnostics as pd, pymobiledevice3.services.installation_proxy as pi
pl.create_using_usbmux, pd.DiagnosticsService, pi.InstallationProxyService = fake_usbmux, FakeService, FakeService
import io, contextlib, launcher
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    launcher._pk_overview(["--udid", "00008030-TEST"])
raw = di.parse_output(buf.getvalue())
check(raw is not None and di.from_raw(raw).battery.health == 91 and len(raw["apps"]) == 25 and "Serial" not in raw["battery_io"],
      "--pk-overview prints the phone's details (only the values PhoneKeep uses)")
check(not [c for c in calls if c[0] == "OTHER"] and ("get_apps", "User", True) in calls and ("ioregistry", "AppleSmartBattery") in calls,
      f"reading the phone only asks questions: {sorted(set(c[0] for c in calls))}")
src = (HERE.parent / "launcher.py").read_text(encoding="utf-8")
body = src[src.index("def _pk_overview"):src.index("def _pk_change_password")]
check(not any(w in body for w in ("set_value", "remove_value", "uninstall", "install(", "restart", "shutdown")),
      "and the code has no call that would change the phone")

# -- the window ---------------------------------------------------------------------------------------------------
try:
    import tkinter as tk
    import overview_ui
    root = tk.Tk()
    root.withdraw()

    class Win(tk.Toplevel):
        def __init__(self):
            super().__init__(root)
            self.content = tk.Frame(self)
            self.content.pack(fill="both", expand=True)
            self.current, self.opened = None, []
            self.photos_bytes, self.messages_bytes = 80 * GBy, 9 * GBy

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            self.current = None
            self._clear()
            overview_ui.cards(self, self.content, ov, "Last backup 13 Nov 2026 21:04").pack(fill="x")

        def open_app(self, k):
            self.opened.append(k)

    def texts(w):
        out = []
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                out.append(c.cget("text"))
            out += texts(c)
        return out

    w = Win()
    w.withdraw()
    w.show_home()
    w.update()
    t = " | ".join(texts(w.content))
    check(all(x in t for x in ("iPhone 17 Pro Max", "256 GB", "Deep Blue", "iOS 26.1", "TESTSERIAL01", "Last backup 13 Nov 2026",
                               "about 91%", "212 charge cycles", "Charge now 64% · charging", "61.2 GB free")),
          f"V1: the strip shows model, capacity, colour, iOS, serial, last backup, battery and free space: {t}")
    overview_ui.copy_serial(w, ov.serial, w.serial_label)
    check(w.clipboard_get() == "TESTSERIAL01" and "copied" in w.serial_label.cget("text"), "V1: clicking the serial copies it")

    overview_ui.battery_view(w, ov)
    w.update()
    t = " | ".join(texts(w.content))
    check(w.current == "battery" and "Good: holds about 91% of its original charge" in t and "4410 mAh of 4832 mAh" in t
          and "30.5 °C" in t, f"V2: the Battery screen: {t[:160]}…")
    out = overview_ui.save_details(w, ov, HERE / "work" / "v2-battery.json")
    check(json.loads(out.read_text(encoding="utf-8"))["battery"]["cycle_count"] == 212, "V2: Save details writes the file")

    overview_ui.storage_view(w, ov)
    w.update()
    t = " | ".join(texts(w.content))
    check(w.current == "storage" and "about " + di.human(apps_total) in t and di.human(ov.free) in t
          and len(w.app_rows) == 20 and w.app_rows[0] == "Example App 23", "V3: categories with 'about', and the 20 largest apps")
    w.storage_rows["Photos"].open()
    w.storage_rows["Messages"].open()
    check(all(c.bind("<Button-1>") for c in w.storage_rows["Photos"].winfo_children()), "the whole Photos row is clickable")
    check(w.opened == ["photos", "messages"], f"V3: clicking Photos or Messages opens that screen ({w.opened})")
    w.destroy()
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

print("\nV1-V3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
