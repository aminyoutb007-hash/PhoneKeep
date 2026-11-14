"""V1 / V2 / V3: what PhoneKeep can tell about the connected iPhone itself.

The launcher (`--pk-overview`) reads raw values from the phone: lockdown, the battery entry in the
IORegistry, the disk-usage domain and the installed apps with their sizes. It only reads, so nothing on
the phone changes. This module turns those raw values into what the window shows. It's kept free of
Tk and of the phone connection, so the tests can feed it stand-in values.

What's exact and what's "about" (docs/spec/10-device.md, feasibility notes in #20):
  * model, iOS, serial, capacity, free space: exact, straight from the phone;
  * battery health: Settings → Battery works it out the same way, but it can be a point or two off,
    so it's shown as "about 91%";
  * the storage categories (Apps, Photos, Messages, System, Other): estimates, labelled "about".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import models

GB = 1000 ** 3   # Apple counts storage in powers of 1000 (a "256 GB" phone)

# DeviceEnclosureColor names Apple uses as words on some models; others are hex values or bare numbers.
COLOUR_WORDS = {"black", "white", "silver", "gold", "rose gold", "space gray", "space grey", "blue", "red",
                "green", "yellow", "purple", "pink", "midnight", "starlight", "graphite", "sierra blue",
                "deep purple", "natural titanium", "black titanium", "white titanium", "blue titanium",
                "desert titanium", "cosmic orange", "deep blue", "sky blue", "light gold", "cloud white",
                "space black", "lavender", "sage", "mist blue", "teal", "ultramarine"}


@dataclass
class Battery:
    level: Optional[int] = None        # charge now, %
    charging: bool = False
    health: Optional[int] = None       # % of the original capacity it still holds
    cycles: Optional[int] = None
    design_mah: Optional[int] = None
    full_mah: Optional[int] = None
    temperature: Optional[float] = None   # °C

    def verdict(self) -> str:
        """A short plain-words line about the health, like Settings → Battery."""
        if self.health is None:
            return "The iPhone didn't report its battery health."
        h = self.health
        if h >= 80:
            word = "Good"
        elif h >= 70:
            word = "Worn"
        else:
            word = "Needs a new battery"
        return f"{word}: holds about {h}% of its original charge"

    def advice(self) -> str:
        if self.health is None:
            return ""
        if self.health >= 80:
            return "Apple considers a battery healthy down to 80%."
        return ("Below 80% Apple suggests a battery replacement; the iPhone may slow down at busy moments "
                "to avoid switching off.")


@dataclass
class AppSize:
    bundle: str
    name: str
    app_bytes: int
    data_bytes: int

    @property
    def total(self) -> int:
        return self.app_bytes + self.data_bytes


@dataclass
class Overview:
    name: str = "iPhone"
    model: str = "iPhone"
    product_type: str = ""
    ios: str = ""
    serial: str = ""
    colour: str = ""            # a word ("Deep Blue") when the phone says one, else ""
    colour_hex: str = ""        # "#3b3b3c" when the phone gives a colour value instead
    total: Optional[int] = None  # bytes
    free: Optional[int] = None
    battery: Battery = field(default_factory=Battery)
    apps: list[AppSize] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)   # section -> why it couldn't be read

    @property
    def used(self) -> Optional[int]:
        if self.total is None or self.free is None:
            return None
        return max(0, self.total - self.free)

    def capacity_label(self) -> str:
        """The size as Apple sells it: '256 GB' for a phone reporting 255.9 GB."""
        if not self.total:
            return ""
        gb = self.total / GB
        for size in (16, 32, 64, 128, 256, 512, 1024, 2048):
            if gb <= size * 1.02:
                return f"{size} GB" if size < 1024 else f"{size // 1024} TB"
        return f"{gb:.0f} GB"

    def largest_apps(self, n: int = 20) -> list[AppSize]:
        return sorted(self.apps, key=lambda a: a.total, reverse=True)[:n]


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _colour(raw: dict) -> tuple[str, str]:
    known = models.colour_name(raw.get("ProductType"), raw.get("DeviceEnclosureColor"))
    if known:
        return known, ""
    for key in ("DeviceEnclosureColor", "DeviceColor"):
        v = str(raw.get(key) or "").strip()
        if not v:
            continue
        if v.lower() in COLOUR_WORDS:
            return v.title(), ""
        if v.startswith("#") and len(v) in (4, 7):
            return "", v.lower()
    return "", ""


def battery_from(io: Optional[dict], lockdown_battery: Optional[dict] = None) -> Battery:
    """From the AppleSmartBattery entry of the IORegistry (plus the lockdown battery domain for the charge)."""
    b = Battery()
    lb = lockdown_battery or {}
    io = io or {}
    lvl = _int(lb.get("BatteryCurrentCapacity"))
    b.level = lvl if lvl is not None and lvl >= 0 else _int(io.get("CurrentCapacity"))
    b.charging = bool(lb.get("BatteryIsCharging", io.get("IsCharging", False)))
    data = io.get("BatteryData") if isinstance(io.get("BatteryData"), dict) else {}
    b.cycles = _int(io.get("CycleCount") if io.get("CycleCount") is not None else data.get("CycleCount"))
    b.design_mah = _int(io.get("DesignCapacity") or data.get("DesignCapacity"))
    b.full_mah = _int(io.get("NominalChargeCapacity") or io.get("AppleRawMaxCapacity") or data.get("NominalChargeCapacity"))
    pct = _int(io.get("MaximumCapacityPercent") or data.get("MaximumCapacityPercent"))
    if pct is not None and 0 < pct <= 100:
        b.health = pct                       # newer iPhones report the same number Settings shows
    elif b.design_mah and b.full_mah:
        b.health = max(1, min(100, round(100 * b.full_mah / b.design_mah)))
    t = io.get("Temperature")
    if isinstance(t, (int, float)) and t:
        b.temperature = round(t / 100, 1) if abs(t) > 200 else float(t)   # reported in hundredths of °C
    return b


def apps_from(raw: Optional[dict]) -> list[AppSize]:
    out = []
    for bundle, a in (raw or {}).items():
        if not isinstance(a, dict):
            continue
        out.append(AppSize(bundle, str(a.get("CFBundleDisplayName") or a.get("CFBundleName") or bundle),
                           _int(a.get("StaticDiskUsage")) or 0, _int(a.get("DynamicDiskUsage")) or 0))
    return out


def from_raw(raw: dict) -> Overview:
    """Turn what `--pk-overview` printed into an Overview."""
    info = raw.get("info") or {}
    ov = Overview()
    ov.name = str(info.get("DeviceName") or "iPhone")
    ov.product_type = str(info.get("ProductType") or "")
    ov.model = models.model_name(ov.product_type)
    ov.ios = str(info.get("ProductVersion") or "")
    ov.serial = str(info.get("SerialNumber") or "")
    ov.colour, ov.colour_hex = _colour(info)
    disk = raw.get("disk") or {}
    ov.total = _int(disk.get("TotalDiskCapacity")) or _int(info.get("TotalDiskCapacity"))
    ov.free = _int(disk.get("TotalDataAvailable"))
    ov.battery = battery_from(raw.get("battery_io"), raw.get("battery"))
    ov.apps = apps_from(raw.get("apps"))
    ov.problems = dict(raw.get("problems") or {})
    return ov


def parse_output(stdout: str) -> Optional[dict]:
    for line in (stdout or "").splitlines():
        if line.startswith("PKOVERVIEW "):
            try:
                return json.loads(line[len("PKOVERVIEW "):])
            except ValueError:
                return None
    return None


# -- V3: storage, split into rough categories -----------------------------------------------------------------
CATEGORY_COLOURS = {"Apps": "#4f7cff", "Photos": "#f2a93b", "Messages": "#34c759", "System": "#8e8e93",
                    "Other": "#c7c7cc", "Free": "#ececf0"}


def categories(ov: Overview, photos_bytes: Optional[int] = None, messages_bytes: Optional[int] = None) -> list[tuple[str, int, bool]]:
    """[(name, bytes, exact)] adding up to the capacity. Free (and the total) are exact, the rest "about".

    Apps = what the installed apps and their data take (the phone reports each one).
    Photos and Messages come from the newest backup when there is one (an iCloud-only library is mostly in
    iCloud, so this is what's on the phone). System is what's left of the capacity that isn't apps,
    photos, messages or free, capped at a sensible size; anything above that is "Other".
    """
    if not ov.total or ov.free is None:
        return []
    used = ov.used or 0
    apps = sum(a.total for a in ov.apps)
    photos = max(0, photos_bytes or 0)
    msgs = max(0, messages_bytes or 0)
    known = apps + photos + msgs
    if known > used:                       # estimates bigger than what's used: scale them down to fit
        f = used / known if known else 0
        apps, photos, msgs = int(apps * f), int(photos * f), int(msgs * f)
        known = apps + photos + msgs
    rest = used - known
    system = min(rest, int(12 * GB + 0.04 * ov.total))   # iOS itself and its caches: about 12 GB plus a little per size
    other = rest - system
    out = [("Apps", apps, False), ("Photos", photos, False), ("Messages", msgs, False),
           ("System", system, False), ("Other", other, False), ("Free", ov.free, True)]
    return [c for c in out if c[1] > 0 or c[0] == "Free"]


def human(n: Optional[int]) -> str:
    if n is None:
        return "?"
    if n >= GB:
        return f"{n / GB:.1f} GB"
    if n >= 1000 ** 2:
        return f"{n / 1000 ** 2:.0f} MB"
    return f"{max(0, n) / 1000:.0f} KB"


def details_json(ov: Overview) -> str:
    """The battery details as a JSON file (the "Save details" button in V2)."""
    b = ov.battery
    return json.dumps({
        "iphone": ov.name, "model": ov.model, "ios": ov.ios,
        "battery": {"health_percent_about": b.health, "cycle_count": b.cycles, "design_capacity_mAh": b.design_mah,
                    "full_charge_capacity_mAh": b.full_mah, "charge_now_percent": b.level, "charging": b.charging,
                    "temperature_c": b.temperature},
        "note": "Health is worked out the way Settings → Battery does; it can differ by a point or two.",
    }, indent=2, ensure_ascii=False)
