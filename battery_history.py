"""H3: the Battery card's history, notes and tips (docs/spec/13-phone-health.md#h3-battery-card-and-battery-history).

The iPhone only shows today's battery health; PhoneKeep keeps one reading per backup (date, health, cycles,
full-charge and design capacity, temperature) in the phone's checkup.json (H1), so it can draw health over time.
Kept free of Tk, like checkup.py: the window draws what this works out.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Optional

import models

# Every threshold in one place.
REPLACE_BELOW = 80            # % health: Apple usually recommends a replacement below this
HOT_C = 35.0                  # battery temperature at a backup (°C) that's worth the "charging in heat" tip
CHART_MIN_POINTS = 2
NORMAL_MARGIN = 3             # points below the expected health that still count as normal wear
NOTE_MIN_DAYS = 30            # a "dropped N points in M months" line needs at least this much history


def rated_cycles(product_type: Optional[str]) -> int:
    """Apple: iPhone 15 and later keep 80% of their capacity at 1000 full cycles; earlier models at 500."""
    g = models.generation(product_type)
    return 1000 if g is not None and g >= 15 else 500


def has_charge_limit(product_type: Optional[str]) -> bool:
    """The 80% charge limit (Settings → Battery → Charging) is on iPhone 15 and later."""
    g = models.generation(product_type)
    return g is not None and g >= 15


def readings(history: list) -> list:
    """[(datetime, entry)] for the backups that recorded a battery health, oldest first."""
    out = []
    for e in history:
        try:
            w = dt.datetime.fromisoformat(e["when"])
        except (KeyError, TypeError, ValueError):
            continue
        if e.get("health") is not None:
            out.append((w, e))
    return sorted(out, key=lambda x: x[0])


def points(history: list) -> list:
    """[(datetime, health %)]: one point per backup, for the chart."""
    return [(w, int(e["health"])) for w, e in readings(history)]


def wear(health: int, cycles: Optional[int], product_type: Optional[str]) -> str:
    """'normal' or 'faster than usual' for this many cycles (Apple's figure: 80% at the rated cycles)."""
    if cycles is None:
        return ""
    expected = 100 - 20 * min(cycles, 2 * rated_cycles(product_type)) / rated_cycles(product_type)
    return "normal" if health >= expected - NORMAL_MARGIN else "faster than usual"


def note(history: list, product_type: Optional[str] = None) -> str:
    """The plain-language line under the chart."""
    rs = readings(history)
    if not rs:
        return ""
    now_w, now = rs[-1]
    h, cycles = int(now["health"]), now.get("cycles")
    if h < REPLACE_BELOW:
        return f"Below {REPLACE_BELOW}%: Apple usually recommends a battery replacement at this point."
    judge = wear(h, cycles, product_type)
    tail = f", {judge} for {cycles} cycles" if judge else ""
    since = now_w - dt.timedelta(days=91)
    window = [(w, e) for w, e in rs if w >= since]
    first_w, first = window[0]
    days = (now_w - first_w).days
    if days >= NOTE_MIN_DAYS:
        months = max(1, round(days / 30.4))
        span = f"{months} month{'s' if months != 1 else ''}"
        drop = int(first["health"]) - h
        if drop > 0:
            return f"Health dropped {drop} point{'s' if drop != 1 else ''} in {span}{tail}."
        return f"Health held at about {h}% over {span}{tail}."
    if judge:
        return f"About {h}% after {cycles} charge cycles: {judge} for this iPhone."
    return ""


def tips(history: list, product_type: Optional[str] = None) -> list:
    """'Tips for this iPhone': only the ones that apply to this model and what the phone reported."""
    out = []
    if has_charge_limit(product_type):
        out.append("Use the 80% charge limit if the iPhone usually charges for hours (overnight, at a desk): "
                   "Settings → Battery → Charging → 80% Limit.")
        out.append("Or keep Optimised Battery Charging on: Settings → Battery → Charging.")
    else:
        out.append("Keep Optimised Battery Charging on: Settings → Battery → Battery Health & Charging.")
    temps = [e.get("temperature") for _w, e in readings(history) if e.get("temperature") is not None]
    hot = max(temps, default=None)
    if hot is not None and hot >= HOT_C:
        out.append(f"Avoid charging in heat: at one backup the battery was at {hot:.0f} °C. Charge it somewhere cool, "
                   "and take a thick case off while it charges.")
    # Background App Refresh's biggest users: the phone doesn't report them to a computer, so that tip isn't shown.
    return out


def csv_text(history: list) -> str:
    """The history as CSV ('Save details'), one row per backup."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "health_percent_about", "cycle_count", "full_charge_capacity_mAh", "design_capacity_mAh",
                "temperature_c"])
    for when, e in readings(history):
        w.writerow([when.strftime("%Y-%m-%d %H:%M"), e.get("health"), e.get("cycles"), e.get("full_mah"),
                    e.get("design_mah"), "" if e.get("temperature") is None else round(float(e["temperature"]), 1)])
    return buf.getvalue()
