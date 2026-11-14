"""H3: the Battery card's history (docs/spec/13-phone-health.md#h3-battery-card-and-battery-history).

Done when:
- after three backups, the chart shows three points that match the phone's Settings → Battery at each time
  (within 1%): here, three recorded backups give three points with exactly the recorded health; the match with
  Settings over real backups is the owner's check;
- tips that don't apply to the model or situation are not shown.
Also: the note under the chart, the chart's fallback with fewer than 2 points, and Save details (CSV + JSON).
Nothing touches a real phone.
"""
import csv, datetime as dt, io, json, os, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE / "work" / "h3"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
os.environ["PHONEKEEP_HOME"] = str(W / "home")
sys.path.insert(0, str(HERE.parent))

import battery_history as bh
import checkup as cu
import deviceinfo as di
import models

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


P14, P15, P16E, AIR, SE = "iPhone15,3", "iPhone15,4", "iPhone17,5", "iPhone18,4", "iPhone14,6"
check([models.generation(c) for c in (P14, P15, P16E, AIR, SE, None)] == [14, 15, 16, 17, None, None],
      "model generation from the code the phone reports")
check(bh.rated_cycles(P14) == 500 and bh.rated_cycles(P15) == 1000 and bh.rated_cycles(SE) == 500,
      "Apple's rated cycles: 1000 from iPhone 15, 500 before")
check(not bh.has_charge_limit(P14) and bh.has_charge_limit(P15) and bh.has_charge_limit(AIR) and not bh.has_charge_limit(SE),
      "the 80% charge limit: iPhone 15 and later only")

T0 = dt.datetime(2026, 8, 1, 9, 0)


def entry(days, health, cycles=None, temp=None, pt=P14):
    return {"when": (T0 + dt.timedelta(days=days)).isoformat(), "health": health, "cycles": cycles,
            "full_mah": 4000, "design_mah": 4323, "temperature": temp, "product_type": pt}


# -- the note under the chart --------------------------------------------------------------------------------------
check(bh.note([entry(0, 78, 600)], P14) == "Below 80%: Apple usually recommends a battery replacement at this point.",
      "below 80%: the replacement line")
n = bh.note([entry(0, 92, 220), entry(45, 90, 260), entry(90, 88, 300)], P14)
check(n == "Health dropped 4 points in 3 months, normal for 300 cycles.", f"the spec's example: {n}")
n = bh.note([entry(0, 92, 100), entry(90, 85, 160)], P14)
check(n == "Health dropped 7 points in 3 months, faster than usual for 160 cycles.", f"faster than usual: {n}")
n = bh.note([entry(0, 96, 200), entry(90, 96, 300)], P15)
check(n == "Health held at about 96% over 3 months, normal for 300 cycles.", f"held: {n}")
n = bh.note([entry(-200, 99, 10), entry(0, 95, 200), entry(60, 93, 260)], P14)
check(n == "Health dropped 2 points in 2 months, normal for 260 cycles.", f"only the last 3 months count: {n}")
n = bh.note([entry(0, 91, 300)], P14)
check(n == "About 91% after 300 charge cycles: normal for this iPhone.", f"one backup: {n}")
check(bh.note([], P14) == "" and bh.note([entry(0, 91)], P14) == "", "nothing to say: no line")
check(bh.wear(84, 900, P15) == "normal" and bh.wear(84, 900, P14) == "normal" and bh.wear(84, 300, P14) == "faster than usual",
      "wear judged against the model's rated cycles")

# -- tips: only the ones that apply -------------------------------------------------------------------------------
t = bh.tips([entry(0, 90, 300, 30.0)], P14)
check(len(t) == 1 and "Optimised Battery Charging" in t[0] and "Battery Health & Charging" in t[0],
      f"iPhone 14: Optimised Charging only (no 80% limit on that model): {t}")
t = bh.tips([entry(0, 90, 300, 30.0)], P15)
check(any("80% Limit" in x for x in t) and any("Optimised Battery Charging" in x for x in t) and not any("heat" in x for x in t),
      "iPhone 15: the 80% limit too; no heat tip at 30 °C")
t = bh.tips([entry(0, 90, 300, 31.0), entry(10, 90, 310, 37.4)], P14)
check(any(x.startswith("Avoid charging in heat: at one backup the battery was at 37 °C.") for x in t),
      "a hot reading at a backup: the heat tip, with the temperature")
check(not any("Background App Refresh" in x for x in bh.tips([entry(0, 90)], P15)),
      "Background App Refresh: not shown (the phone doesn't report which apps use it)")

# -- each backup records the battery, and the history comes back as points and CSV -------------------------------
pd = W / "Backups" / "00008030-H3TEST"
for i, (h, c) in enumerate(((93, 280), (92, 300), (91, 330))):
    ov = di.Overview(name="Test iPhone", product_type=P14, ios="26.1", total=128 * 10 ** 9, free=40 * 10 ** 9)
    ov.battery = di.Battery(health=h, cycles=c, design_mah=4323, full_mah=4323 * h // 100, temperature=29.5 + i)
    cu.record(pd, ov, T0 + dt.timedelta(days=30 * i))
hist = cu.load(pd)["history"]
check(all(e["product_type"] == P14 and e["cycles"] and e["full_mah"] and e["design_mah"] and e["temperature"] for e in hist),
      "each backup records date, health, cycles, full-charge and design capacity, temperature and the model")
pts = bh.points(hist)
check([h for _w, h in pts] == [93, 92, 91] and len(pts) == 3, f"three backups: three points with the recorded health {pts}")
rows = list(csv.reader(io.StringIO(bh.csv_text(hist))))
check(rows[0] == ["date", "health_percent_about", "cycle_count", "full_charge_capacity_mAh", "design_capacity_mAh",
                  "temperature_c"] and len(rows) == 4 and rows[3][1] == "91" and rows[3][5] == "31.5",
      f"the CSV: a header and one row per backup ({rows[3]})")

# -- the Battery details screen -----------------------------------------------------------------------------------
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    import checkup_ui
    import phone

    class Win(tk.Toplevel):
        def __init__(self, udid, ov=None):
            super().__init__(root)
            self.content = tk.Frame(self)
            self.content.pack(fill="both", expand=True)
            self.backup_dir, self.udid, self.overview, self.current = W / "Backups", udid, ov, None
            self.view_header = lambda key, sub="": phone.PhoneWindow.view_header(self, key, sub)

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            pass

    def labels(w, out):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                out.append(c.cget("text"))
            labels(c, out)
        return out

    win = Win("00008030-H3TEST")
    checkup_ui.view(win)
    checkup_ui.details(win, "battery")
    win.update()
    texts = labels(win.content, [])
    check(win.battery_chart is not None and len(win.battery_points) == 3, "the chart is drawn with three points")
    cv = win.battery_chart
    ovals = [cv.coords(i) for i in cv.find_all() if cv.type(i) == "oval"]
    check(len(ovals) == 3 and all(abs((c[2] - c[0]) - 8) < 0.01 for c in ovals), "one 8 px point per backup")
    ys = [(c[1] + c[3]) / 2 for c in ovals]
    check(ys[0] < ys[1] < ys[2], "lower health sits lower on the chart")
    chart_text = [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]
    check("about 91%" in chart_text and "80%: replace" in chart_text and "1 Aug" in chart_text,
          f"the latest point labelled, the 80% line named, the first date shown: {chart_text}")
    x, y = (ovals[1][0] + ovals[1][2]) / 2, (ovals[1][1] + ovals[1][3]) / 2
    cv.hover(type("E", (), {"x": int(x), "y": int(y)})())
    tip = [cv.itemcget(i, "text") for i in cv.find_withtag("tip") if cv.type(i) == "text"]
    check(tip == ["31 Aug · about 92%"], f"hovering a point shows its date and health: {tip}")
    check(win.battery_note == "Health dropped 2 points in 2 months, normal for 330 cycles." and win.battery_note in texts,
          f"the note under the chart: {win.battery_note}")
    check(win.battery_today.startswith("As of last backup, ") and "about 91% health · 330 charge cycles" in win.battery_today,
          f"today's figures, as of the last backup when the phone is away: {win.battery_today}")
    check(len(win.battery_tips) == 1 and not any("80% Limit" in x for x in win.battery_tips),
          "tips for this model only (an iPhone 14 Pro Max: no 80% limit)")

    live = di.Overview(name="Test iPhone", product_type=P15, total=128 * 10 ** 9, free=40 * 10 ** 9)
    live.battery = di.Battery(health=91, cycles=331, level=64, charging=True)
    win2 = Win("00008030-H3TEST", live)
    checkup_ui.details(win2, "battery")
    win2.update()
    check(win2.battery_today == "Today: about 91% health · 331 charge cycles · charge now 64% (charging)",
          f"with the phone connected, today's figures from it: {win2.battery_today}")
    check(any("80% Limit" in x for x in win2.battery_tips), "the connected phone's model decides the tips")
    (W / "out").mkdir()
    saved = checkup_ui.save_battery_details(win2, cu.load(pd)["history"], live, W / "out" / "battery.csv")
    check(saved.exists() and saved.read_text(encoding="utf-8").count("\n") == 4
          and json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))["battery"]["cycle_count"] == 331,
          "Save details writes the history as CSV, and V2's JSON next to it")

    # the chart's labels: inside the canvas, and never on the line or its points (review of #44)
    def layout(healths, every_days=30):
        c = tk.Canvas(root, width=640, height=210)
        pts_ = [(T0 + dt.timedelta(days=i * every_days), h) for i, h in enumerate(healths)]
        checkup_ui.draw_health_chart(c, pts_)
        c.update_idletasks()
        texts_ = [(c.itemcget(i, "text"), c.bbox(i)) for i in c.find_all() if c.type(i) == "text"]
        outside = [t for t, b in texts_ if b[0] < 0 or b[1] < 0 or b[2] > 640 or b[3] > 210]
        dots = [c.coords(i) for i in c.find_all() if c.type(i) == "oval"]
        line_xy = [((d[0] + d[2]) / 2, (d[1] + d[3]) / 2) for d in dots]
        labels_ = [(c.itemcget(i, "text"), c.bbox(i)) for i in c.find_withtag("label")]
        on_line = [t for t, b in labels_ if checkup_ui._crosses(b, line_xy)
                   or any(checkup_ui._overlap(b, d) for d in dots)]
        between = len(labels_) == 2 and checkup_ui._overlap(labels_[0][1], labels_[1][1])
        for px, py in line_xy:                        # each point's hover tooltip stays inside too
            c.hover(type("E", (), {"x": int(px), "y": int(py)})())
            b = c.bbox("tip")
            if b and (b[0] < 0 or b[1] < 0 or b[2] > 640 or b[3] > 210):
                outside.append("tooltip")
        c.destroy()
        return outside, on_line, between, [t for t, _b in labels_]

    for what, healths in (("the latest point at the right edge (86%)", [92, 90, 88, 86]),
                          ("crossing 80% at the left", [83, 79, 78, 77, 76]),
                          ("crossing 80% at the right", [90, 88, 85, 82, 79]),
                          ("hovering around 80% all along", [81, 79, 81, 79, 81, 79, 80]),
                          ("a steep drop, two backups", [100, 60]),
                          ("thirty backups", [100 - i // 2 for i in range(30)]),
                          ("the latest point at the top", [97, 98, 99, 100])):
        outside, on_line, between, shown = layout(healths)
        check(not outside and not on_line and not between and shown and shown[0].startswith("about "),
              f"chart labels with {what}: inside the canvas, off the line and its points, apart"
              f" (outside {outside}, on the line {on_line}, overlapping {between}, labels {shown})")
    check(any(t.startswith("The dashed line is 80%") for t in texts),
          "the caption under the chart names the 80% line (also when there's no free place for its label)")

    cu.record(W / "Backups" / "00008030-ONE", di.Overview(total=1, free=1, battery=di.Battery(health=97)), T0)
    win3 = Win("00008030-ONE")
    checkup_ui.details(win3, "battery")
    win3.update()
    check(win3.battery_chart is None and any(t.startswith("The chart fills in as PhoneKeep backs up") for t in labels(win3.content, [])),
          "one backup: no chart yet, and it says why")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

spec = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"battery_history"' in spec, "the packaged app includes the battery history")

print("\nH3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
