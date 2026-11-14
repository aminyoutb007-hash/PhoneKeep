"""Owner's real-iPhone check for V1-V3: reads the connected iPhone (read-only) and prints what PhoneKeep
will show, next to where to find the same value on the phone. Nothing is changed on the phone.

    .venv/bin/python tools/check_iphone.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phonekeep as wv
import deviceinfo as di

devs = wv.list_devices()
if not devs:
    sys.exit("No iPhone found. Plug it in, unlock it once, then run this again.")
for d in devs:
    ov = wv.device_overview(d["UniqueDeviceID"])
    if ov is None:
        print(f"\n{d.get('DeviceName')}: its details couldn't be read.")
        continue
    b = ov.battery
    print(f"\n=== {ov.name} ({d.get('ConnectionType')}) ===")
    rows = [
        ("Model", ov.model, "Settings → General → About → Model Name"),
        ("iOS", ov.ios, "About → iOS Version"),
        ("Capacity", ov.capacity_label(), "About → Capacity"),
        ("Free", di.human(ov.free), "General → iPhone Storage (top line)"),
        ("Used", di.human(ov.used), "General → iPhone Storage (top line)"),
        ("Serial", ov.serial, "About → Serial Number"),
        ("Colour", ov.colour or (ov.colour_hex and f"swatch {ov.colour_hex}") or "(not shown)", "the phone itself"),
        ("Battery health", f"about {b.health}%" if b.health is not None else "not reported", "Settings → Battery → Battery Health"),
        ("Charge cycles", b.cycles, "Battery → Battery Health (iPhone 15 and later)"),
        ("Charge now", f"{b.level}%" + (" charging" if b.charging else ""), "status bar"),
        ("Temperature", f"{b.temperature} °C" if b.temperature is not None else "not reported", "(not shown on the phone)"),
        ("Apps listed", len(ov.apps), "General → iPhone Storage list"),
    ]
    for k, v, where in rows:
        print(f"  {k:<15} {str(v):<26} compare: {where}")
    for a in ov.largest_apps(5):
        print(f"     {a.name:<28} {di.human(a.total)}")
    if ov.problems:
        print("  couldn't read:", ", ".join(ov.problems))
