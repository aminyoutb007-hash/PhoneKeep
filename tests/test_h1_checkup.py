"""H1: the check-up screen (docs/spec/13-phone-health.md#h1-check-up-screen).

Done when:
- with the test fixtures, each card shows green, amber and red at the thresholds, with the matching one-line reason;
- "Why is my phone slow?" names the red and amber causes in order of impact;
- a red card produces exactly one helper notification, and none again until it changes;
- opening the check-up adds less than 1 second to the phone window.
Also: the record made after every backup, and the cards "As of last backup, 3 Nov" with the phone away.
The helper backs up a stub iPhone here (as in test_e2_helper.py); nothing touches a real phone.
"""
import datetime as dt
import json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE / "work" / "h1"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
os.environ["PHONEKEEP_HOME"] = str(W / "home")
sys.path.insert(0, str(HERE.parent))

import checkup as cu
import deviceinfo as di

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


NOW = dt.datetime(2026, 11, 14, 12, 0)
GB = 1000 ** 3


def facts(**kw):
    return cu.Facts(when=NOW, live=True, **kw)


def card(key, **kw):
    return cu.evaluate(facts(**kw)).card(key)


# -- Storage: 85% amber, 95% red ---------------------------------------------------------------------------------
c = card("storage", total=100 * GB, free=int(15.01 * GB))            # 84.99% full
check(c.level == "green" and c.reason == "Green: 84% full, about 15 GB free.", f"storage just under 85%: {c.reason}")
c = card("storage", total=100 * GB, free=15 * GB)
check(c.level == "amber" and c.reason == "Amber: 85% full. Free about 1 GB to get below 85%.", f"storage at 85%: {c.reason}")
c = card("storage", total=256 * GB, free=23 * GB)                    # 91% full, the spec's example
check(c.level == "amber" and c.reason == "Amber: 91% full. Free about 16 GB to get below 85%.", f"storage at 91%: {c.reason}")
c = card("storage", total=100 * GB, free=int(5.01 * GB))
check(c.level == "amber", f"storage just under 95% is still amber: {c.reason}")
c = card("storage", total=100 * GB, free=5 * GB)
check(c.level == "red" and c.reason == "Red: 95% full. Free about 11 GB to get below 85%.", f"storage at 95%: {c.reason}")
check(card("storage").level == "unknown" and "didn't report" in card("storage").reason, "storage not reported: not checked")

# -- Battery: below 85 amber, below 80 red, a 5-point drop in 3 months amber, service red ------------------------
check(card("battery", health=85).level == "green" and card("battery", health=85).reason == "Green: Health about 85%.",
      "battery at 85%: green")
c = card("battery", health=84)
check(c.level == "amber" and c.reason == "Amber: Health about 84%.", f"battery at 84%: {c.reason}")
check(card("battery", health=80).level == "amber", "battery at 80%: still amber")
c = card("battery", health=79)
check(c.level == "red" and c.reason == "Red: Health about 79%. Apple usually recommends a new battery below 80%.",
      f"battery at 79%: {c.reason}")
hist = [(NOW - dt.timedelta(days=80), 95), (NOW - dt.timedelta(days=40), 93)]
c = card("battery", health=90, health_history=hist)
check(c.level == "amber" and c.reason == "Amber: Health dropped 5 points in 3 months.", f"a 5-point drop in 3 months: {c.reason}")
c = card("battery", health=91, health_history=hist)
check(c.level == "green", "a 4-point drop: green")
c = card("battery", health=90, health_history=[(NOW - dt.timedelta(days=120), 97), (NOW - dt.timedelta(days=60), 93)])
check(c.level == "green", "a drop from more than 3 months ago doesn't count")
c = card("battery", health=92, battery_service=True)
check(c.level == "red" and c.reason == "Red: The iPhone says the battery needs service.", f"needs service: {c.reason}")
check(card("battery").level == "unknown", "battery not reported: not checked")

# -- Stability: 3+ crashes amber, 10+ red, an unexpected restart red ---------------------------------------------
c = card("stability", crashes={}, unexpected_restarts=0)
check(c.level == "green" and c.reason == "Green: No app crashes in the last 7 days.", f"no crashes: {c.reason}")
c = card("stability", crashes={"Maps": 2})
check(c.level == "green" and "No app crashed 3 or more times" in c.reason, f"2 crashes: {c.reason}")
c = card("stability", crashes={"Maps": 2, "Camera App": 3})
check(c.level == "amber" and c.reason == "Amber: Camera App crashed 3 times this week.", f"3 crashes: {c.reason}")
c = card("stability", crashes={"Camera App": 4, "Chat App": 14})
check(c.level == "red" and c.reason == "Red: Chat App crashed 14 times this week." and len(c.details) == 2,
      f"14 crashes, most first: {c.reason}")
c = card("stability", crashes={"Maps": 9}, unexpected_restarts=1)
check(c.level == "red" and c.reason == "Red: The iPhone restarted unexpectedly once this week.", f"a restart: {c.reason}")
check(card("stability").level == "unknown" and "Not checked yet" in card("stability").reason,
      "crash reports not read yet: not checked")

# -- Security: amber for old iOS / an app from outside the App Store; red for the rest ---------------------------
clean = dict(no_passcode=False, unknown_profiles=[], jailbreak=[], spyware_matched=False, ios_outdated=False,
             outside_app_store=[])
c = card("security", **clean)
check(c.level == "green" and c.reason == "Green: No problems found in these checks." and "safe" not in c.reason.lower(),
      f"clean phone, never 'safe': {c.reason}")
for change, level, reason in (
        ({"ios_outdated": True}, "amber", "Amber: iOS is out of date."),
        ({"outside_app_store": ["Sideloaded App"]}, "amber", "Amber: An app from outside the App Store: Sideloaded App."),
        ({"no_passcode": True}, "red", "Red: No passcode is set."),
        ({"unknown_profiles": ["Example MDM"]}, "red",
         "Red: An unknown configuration profile or device management is installed: Example MDM."),
        ({"jailbreak": ["a package manager app"]}, "red", "Red: Signs of a jailbreak were found: a package manager app."),
        ({"spyware_matched": True}, "red", "Red: A spyware indicator matched.")):
    c = card("security", **{**clean, **change})
    check(c.level == level and c.reason == reason, f"security {list(change)[0]}: {c.reason}")
c = card("security", **{**clean, "ios_outdated": True, "no_passcode": True})
check(c.level == "red" and c.details[0] == "No passcode is set." and c.details[1] == "iOS is out of date.",
      "the most serious finding leads")
check(card("security").level == "unknown", "security checks not built yet: not checked")

check(set(cu.THRESHOLDS) >= {"storage_amber_pct", "storage_red_pct", "battery_amber_health", "battery_red_health",
                             "battery_drop_points", "crash_amber", "crash_red"}, "all thresholds in one table")
src = (HERE.parent / "checkup.py").read_text(encoding="utf-8")
check(not any(f" {n}" in src.split("THRESHOLDS = {")[1].split("}", 1)[1] for n in ("85", "95", ">= 10")),
      "no threshold numbers outside the table")

# -- the summary and "Why is my phone slow?" ---------------------------------------------------------------------
r = cu.evaluate(facts(total=100 * GB, free=4 * GB, health=78, crashes={"Chat App": 4}, unexpected_restarts=0,
                      **{**clean, "ios_outdated": True}))
check(r.summary() == "4 things need attention", f"summary: {r.summary()}")
check(r.why_slow() == "Your storage is 96% full, your battery is at about 78% and Chat App crashed 4 times this week. "
                      "All of these slow an iPhone down. Start with Storage. Also look at Security: iOS is out of date.",
      f"why slow, reds first then amber, by impact: {r.why_slow()}")
r = cu.evaluate(facts(total=100 * GB, free=10 * GB, health=78))
check(r.why_slow().startswith("Your battery is at about 78% and your storage is 90% full. Both slow an iPhone down. "
                              "Start with Battery."), f"a red battery comes before an amber storage: {r.why_slow()}")
check(r.summary() == "2 things need attention (Stability and Security not checked yet)", f"summary: {r.summary()}")
r = cu.evaluate(facts(total=100 * GB, free=60 * GB, health=96))
check(r.summary() == "Nothing needs attention (Stability and Security not checked yet)"
      and r.why_slow().startswith("Nothing PhoneKeep checked explains a slow iPhone.")
      and r.why_slow().endswith("(Stability and Security are not checked yet.)"), f"all green: {r.why_slow()}")
r = cu.evaluate(facts(total=100 * GB, free=3 * GB, health=90))
check(r.summary() == "1 thing needs attention (Stability and Security not checked yet)"
      and "This can slow an iPhone down. Start with Storage." in r.why_slow(), f"one cause: {r.why_slow()}")

# -- the record after each backup, and the cards as of the last backup -----------------------------------------
def ov(total, free, health):
    o = di.Overview(name="Test iPhone", ios="26.1", total=total, free=free)
    o.battery = di.Battery(health=health, cycles=300)
    return o


pd = W / "record"
check(cu.check(pd) is None, "no backup yet: no check-up")
check(not cu.record(pd, None) and not cu.record(pd, di.Overview()), "nothing reported: nothing recorded")
cu.record(pd, ov(100 * GB, 50 * GB, 95), dt.datetime(2026, 8, 20, 9, 0))
cu.record(pd, ov(100 * GB, 9 * GB, 89), dt.datetime(2026, 11, 3, 9, 0))
saved = json.loads((pd / "checkup.json").read_text(encoding="utf-8"))
check(len(saved["history"]) == 2 and saved["history"][1]["health"] == 89 and saved["history"][1]["cycles"] == 300,
      "each backup adds what the phone reported to the phone's record")
r = cu.check(pd)
check(not r.facts.live and r.as_of(dt.date(2026, 11, 14)) == "As of last backup, 3 Nov", f"phone away: {r.as_of(dt.date(2026, 11, 14))}")
check(r.card("storage").level == "amber" and r.card("battery").level == "amber"
      and "dropped 6 points" in r.card("battery").details[-1], "from the record: storage and the battery's 3-month drop")
r = cu.check(pd, ov(100 * GB, 40 * GB, 89), NOW)
check(r.facts.live and r.as_of() == "Now, from the iPhone" and r.card("storage").level == "green",
      "with the phone connected, the cards are from it now")
check(cu.day_text(dt.datetime(2025, 10, 27), dt.date(2026, 11, 14)) == "27 Oct 2025", "another year shows the year")

# -- a red card: exactly one helper notification, none again until it changes ----------------------------------
import phonekeep as wv
import helper_core as hc

fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
phone_said = W / "overview.json"
stub = W / "stub_launcher.py"
stub.write_text(f'''
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 1")
elif args[0] == "--pk-backup":
    target = Path(args[1]) / "00008030-H1TEST"
    if not (target / "Manifest.db").exists():
        shutil.copytree(r"{fake}", target)
    print("PKPCT 100", flush=True)
elif args[0] == "--pk-overview":
    assert "--no-apps" in args             # after a backup only storage and battery are asked, quickly
    if Path(r"{phone_said}.dozing").exists():
        import time; time.sleep(60)        # a Wi-Fi phone that dozed off once the backup was done
    print("PKOVERVIEW " + Path(r"{phone_said}").read_text(), flush=True)
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
PHONE = {"DeviceName": "Test iPhone", "UniqueDeviceID": "00008030-H1TEST", "ConnectionType": "USB", "ProductVersion": "26.1"}
wv.list_devices = lambda: [PHONE]


def phone_reports(free_gb, health=92):
    phone_said.write_text(json.dumps({"info": {"DeviceName": "Test iPhone", "ProductVersion": "26.1"},
                                      "disk": {"TotalDiskCapacity": 128 * GB, "TotalDataAvailable": int(free_gb * GB)},
                                      "battery_io": {"BatteryData": {"MaximumCapacityPercent": health}}, "problems": {}}))


notes = []
h = hc.Helper(notify=lambda t, m: notes.append((t, m)), backup_dir=W / "Backups")
h.refresh_devices(force=True)


def back_up():
    notes.clear()
    check(h.back_up_now(), "the helper backs up")
    t0 = time.time()
    while h.busy and time.time() - t0 < 60:
        time.sleep(0.05)
    return [n for n in notes if n[0] != "iPhone backed up"]


phone_reports(40)
check(back_up() == [] and not h.needs_attention(), "all green: no check-up notification, no dot")
phone_reports(3)                                          # 97% full
got = back_up()
check(got == [("Test iPhone: storage almost full", "97% full. Free about 17 GB to get below 85%.")],
      f"storage turns red: exactly one notification: {got}")
check(h.needs_attention(), "the helper's icon shows a dot")
check(back_up() == [], "still red at the next backup: no second notification")
phone_reports(2)
check(back_up() == [], "red with a different figure: still the same problem, no notification")
phone_reports(30)
check(back_up() == [] and not h.needs_attention(), "fixed: nothing sent, and the dot goes")
phone_reports(3)
check(len(back_up()) == 1, "red again after it changed: one new notification")
dot = hc.icon_image(None, 64, dot=True)
check(dot.tobytes() != hc.icon_image(None, 64).tobytes() and dot.getpixel((53, 10))[3] > 0, "the dot is drawn on the icon")
rec = json.loads((W / "Backups" / "00008030-H1TEST" / "checkup.json").read_text(encoding="utf-8"))
check(len(rec["history"]) == 6, "every backup recorded the check-up")

# the dot is worked out once per backup, not on every icon refresh (follow-up to #40)
reads = []
real_any_red = cu.any_red
cu.any_red = lambda folder: (reads.append(folder), real_any_red(folder))[1]
h._red.clear()
for _ in range(20):                                       # the icon refreshes often
    h.needs_attention()
check(len(reads) == 1, f"20 icon refreshes read the phone's record once ({len(reads)})")
phone_reports(30)
back_up()
check(not h.needs_attention() and len(reads) == 2, f"after the next backup it's read again, once ({len(reads)})")
h.needs_attention()
check(len(reads) == 2, "and kept until the backup after that")
cu.any_red = real_any_red

# a phone that dozes off after its backup doesn't hold up the end of it (follow-up to #40)
check(wv.CHECKUP_TIMEOUT == 20, "the check-up's read after a backup waits at most 20 s")
wv.CHECKUP_TIMEOUT = 2
Path(str(phone_said) + ".dozing").write_text("")
t0 = time.time()
back_up()
took = time.time() - t0
rec = json.loads((W / "Backups" / "00008030-H1TEST" / "checkup.json").read_text(encoding="utf-8"))
check(took < 15 and len(rec["history"]) == 7, f"the backup ends after the timeout ({took:.0f} s), with nothing recorded")
Path(str(phone_said) + ".dozing").unlink()
wv.CHECKUP_TIMEOUT = 20
phone_reports(3)                                          # red again, for the window checks below
back_up()

# -- the screen, in a phone window: opens in under 1 second -----------------------------------------------------
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    import checkup_ui
    import phone

    class Win(tk.Toplevel):
        """What checkup_ui needs from the phone window."""
        def __init__(self):
            super().__init__(root)
            self.content = tk.Frame(self)
            self.content.pack(fill="both", expand=True)
            self.backup_dir, self.udid, self.overview, self.current = W / "Backups", "00008030-H1TEST", None, None
            self.view_header = lambda key, sub="": phone.PhoneWindow.view_header(self, key, sub)

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            pass

    win = Win()
    check(checkup_ui.tile_text(win) == "1 to look at", f"the tile says how many cards need a look: {checkup_ui.tile_text(win)}")
    t0 = time.perf_counter()
    checkup_ui.view(win)
    win.update()
    ms = (time.perf_counter() - t0) * 1000
    check(ms < 1000, f"the check-up opens in under 1 second ({ms:.0f} ms)")
    check(set(win.checkup_cards) == {"storage", "battery", "stability", "security"}, "four cards side by side")
    texts = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                texts.append(c.cget("text"))
            walk(c)
    walk(win.content)
    check(any(t.startswith("As of last backup, ") for t in texts), "phone away: each card says 'As of last backup'")
    check("●  Act now" in texts and "1 thing needs attention (Stability and Security not checked yet)" in texts,
          "the red card and the summary line")
    check("safe" not in " ".join(texts).lower(), "never says 'safe'")
    import ui
    red_texts = []

    def reds(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label) and str(c.cget("fg")).lower() == ui.RED.lower():
                red_texts.append(c.cget("text"))
            reds(c)
    reds(win.content)
    check(not red_texts, "a red card isn't drawn in the error colour (real_check would take it for an error)")
    checkup_ui.details(win, "storage")
    texts.clear()
    walk(win.content)
    check(any("97% full" in t for t in texts), "See details lists the findings")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

psrc = (HERE.parent / "phone.py").read_text(encoding="utf-8")
check('("checkup", "Check-up"' in psrc and (HERE.parent / "assets" / "icons" / "checkup.png").exists(),
      "the phone window has a Check-up icon, drawn by PhoneKeep")
spec = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"checkup", "checkup_ui"' in spec, "the packaged app includes the check-up")

print("\nH1 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
