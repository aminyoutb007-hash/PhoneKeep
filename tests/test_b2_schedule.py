"""B2: scheduled automatic backups (docs/spec/03-backup.md), driven with a fake clock and a stub iPhone.

Done when:
  - With "Daily, 9 pm", a backup starts by itself after 9 pm when the phone joins the Wi-Fi.
  - Closing the main window does not stop scheduled backups (the helper runs them; no window here at all).
  - After restarting the computer, the next scheduled backup still runs (a fresh Helper reads the plan
    and health from disk and carries on).
  - A second backup the same day is skipped.
  - The phone card shows the next backup time, and after a missed day the amber line with its fix.
Plus: retries every 30 minutes until midnight, "only when charging", and the one failure notification
after 3 failed days in a row.
"""
import datetime as dt, json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phonekeep as wv
import helper_core as hc
import scheduler as sch

keychain.use_memory()
W = HERE / "work" / "b2"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
hc.LOCK_FILE = W / "helper.lock"
hc.PORT_FILE = W / "app.port"
hc.SETTINGS_FILE = W / "settings.json"
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


def D(day, hour, minute=0):
    return dt.datetime(2026, 11, day, hour, minute)


# -- the pure rules ----------------------------------------------------------------------------------------
plan = sch.Plan(mode="daily", hour=21)
h = sch.Health(failed_days=[])
check(sch.decide(plan, h, D(12, 20, 59), True, None, False) == ("wait", "before the scheduled time"), "before 9 pm: wait")
check(sch.decide(plan, h, D(12, 21, 0), False, None, False)[1] == "the iPhone isn't reachable", "9 pm, phone away: wait for it")
check(sch.decide(plan, h, D(12, 21, 5), True, None, False) == ("backup", ""), "9:05 pm, phone joins the Wi-Fi: back up")
h.last_ok = D(12, 21, 10)
check(sch.decide(plan, h, D(12, 23, 0), True, None, False)[1].startswith("a backup less than 20 hours"), "same day again: skipped")
check(sch.decide(plan, h, D(13, 21, 0), True, None, False) == ("backup", ""), "next day 9 pm: back up (20 h rule)")
h.last_ok, h.last_try = None, D(12, 21, 20)
check(sch.decide(plan, h, D(12, 21, 40), True, None, False)[1] == "tried less than 30 minutes ago", "retry no sooner than 30 min")
check(sch.decide(plan, h, D(12, 21, 51), True, None, False) == ("backup", ""), "after 30 min: try again")
check(sch.decide(sch.Plan("daily", 21, only_when_charging=True), sch.Health(failed_days=[]), D(12, 21, 5), True, False, False)[1]
      == "waiting for the iPhone to be charging", "only when charging: waits")
check(sch.decide(sch.Plan("daily", 21, only_when_charging=True), sch.Health(failed_days=[]), D(12, 21, 5), True, True, False)[0] == "backup",
      "only when charging: charging → back up")
check(sch.decide(sch.Plan("weekly", 21, weekday=6), sch.Health(failed_days=[]), D(12, 21, 5), True, None, False)[1] == "no run scheduled today",
      "weekly on Sunday: Thursday waits")
check(sch.decide(sch.Plan("weekly", 21, weekday=6), sch.Health(failed_days=[]), D(15, 21, 5), True, None, False)[0] == "backup",
      "weekly on Sunday: Sunday backs up")
check(sch.decide(sch.Plan("daily", 21, paused=True), sch.Health(failed_days=[]), D(12, 21, 5), True, None, False)[1] == "no run scheduled today", "paused: nothing")
check(sch.decide(plan, sch.Health(failed_days=[]), D(12, 21, 5), True, None, True)[1] == "a backup is already running", "never two at once")

# next-run wording for the card
check(plan.next_run_text(D(12, 10), None) == "next tonight around 9 pm", "card: next tonight around 9 pm")
check(plan.next_run_text(D(12, 22), D(12, 21, 30)) == "next tomorrow around 9 pm", "card after tonight's backup: next tomorrow")
check(sch.Plan("weekly", 9, weekday=6).next_run_text(D(12, 10), None) == "next Sunday around 9 am", "card weekly: next Sunday around 9 am")
check(sch.Plan("daily", 21, paused=True).next_run_text(D(12, 10), None) == "automatic backups paused", "card paused")

# card states
ok_h = sch.Health(last_ok=D(12, 19), failed_days=[])
check(sch.card_state(plan, ok_h, D(12, 21)) == ("ok", "Last backup: 2 hours ago · next tomorrow around 9 pm"), f"card ok line: {sch.card_state(plan, ok_h, D(12, 21))}")
missed = sch.Health(last_ok=D(10, 21), failed_days=["2026-11-11"], last_reason="")
st, line = sch.card_state(plan, missed, D(12, 21))
check(st == "amber" and line.startswith("Last backup 2 days ago.") and "Wi-Fi" in line and "plug it in" in line, f"card amber explains itself: {line!r}")
missed.last_reason = "Not enough space on this disk: 4.0 GB free."
st, line = sch.card_state(plan, missed, D(12, 21))
check(st == "amber" and "Not enough space" in line, f"card amber carries the real reason: {line!r}")
check(sch.card_state(sch.Plan("off"), missed, D(12, 21))[0] == "ok", "no schedule: never amber")

# the 3-days failure notice
fh = sch.Health(failed_days=["2026-11-10", "2026-11-11"], last_reason="PhoneKeep couldn't reach your iPhone.")
check(sch.failure_notice(fh, dt.date(2026, 11, 11)) is None, "two failed days: no notification yet")
fh.failed_days.append("2026-11-12")
n = sch.failure_notice(fh, dt.date(2026, 11, 12))
check(n and n[0] == "iPhone not backed up for 3 days" and "reach your iPhone" in n[1] and "plug it in" in n[1].lower(), f"three failed days: one notification with the reason and the fix: {n}")
fh.noticed_failure_on = "2026-11-12"
check(sch.failure_notice(fh, dt.date(2026, 11, 12)) is None, "and not again the same day")

# health survives a restart (disk round trip)
fh.last_ok = D(9, 21)
fh.save(W / "ph")
back = sch.Health.load(W / "ph")
check(back.last_ok == D(9, 21) and back.failed_days == fh.failed_days and back.noticed_failure_on == "2026-11-12", "health round-trips through health.json")

# -- the helper with a fake clock and a stub iPhone, no window ------------------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
UD = "00008030-B2TEST"
shutil.copytree(fake, W / "Backups" / UD)          # the first backup was made from the window
stub = W / "stub_launcher.py"
stub.write_text('''
import sys, time
from pathlib import Path
args = sys.argv[1:]
if args[0] == "--pk-will-encrypt":
    print("PKWILLENCRYPT 1")
elif args[0] == "--pk-battery":
    print("PKBATTERY charging=" + ("1" if Path(sys.argv[0]).with_name("charging.flag").exists() else "0") + " level=80")
elif args[0] == "--pk-backup":
    Path(sys.argv[0]).with_name("backups.log").open("a").write("backup\\n")
    for p in (50, 100):
        print(f"PKPCT {p}", flush=True)
''')
wv._launcher_cmd = lambda: [sys.executable, str(stub)]
wv.check_pmd3 = lambda: None
PHONE = {"DeviceName": "Amin's iPhone", "UniqueDeviceID": UD, "ConnectionType": "WiFi", "ProductVersion": "26.1"}
reach = {"on": False}
wv.list_devices = lambda: [PHONE] if reach["on"] else []
hc.SETTINGS_FILE.write_text(json.dumps({"auto_backup": "daily", "auto_backup_hour": 21, "backup_dir": str(W / "Backups")}))
notes = []
clock = {"now": D(12, 20, 0)}


def new_helper():
    h = hc.Helper(notify=lambda t, m: notes.append((t, m)), backup_dir=W / "Backups")
    h.clock = lambda: clock["now"]
    h._refresh_at = 0
    return h


def backups_made():
    f = W / "backups.log"
    return len(f.read_text().splitlines()) if f.exists() else 0


def wait_idle(h):
    t0 = time.time()
    while h.busy and time.time() - t0 < 60:
        time.sleep(0.05)


h = new_helper()
check(h.tick().startswith("wait"), "8 pm: nothing happens")
clock["now"] = D(12, 21, 2)
r = h.tick()
check("isn't reachable" in r and backups_made() == 0, "9:02 pm, phone not on the Wi-Fi yet: waits")
reach["on"] = True
clock["now"] = D(12, 21, 7)
r = h.tick(); wait_idle(h)
check(r.startswith("backup:") and backups_made() == 1, "9:07 pm, phone joins the Wi-Fi: a backup starts by itself")
check(notes and notes[-1][0] == "iPhone backed up", f"quiet success notification: {notes[-1]}")
clock["now"] = D(12, 22, 30)
r = h.tick(); wait_idle(h)
check(backups_made() == 1 and "20 hours" in r, "a second backup the same day is skipped")

# the computer restarts: a brand-new helper, state from disk only
h = new_helper()
clock["now"] = D(13, 21, 1)
r = h.tick(); wait_idle(h)
check(backups_made() == 2 and r.startswith("backup:"), "after a restart, the next day's scheduled backup still runs")

# a missed day → amber card line; three missed days → one notification
reach["on"] = False
for day in (14, 15, 16):
    clock["now"] = D(day, 23, 30)
    h.tick()
health = sch.Health.load(W / "Backups" / UD)
check(health.consecutive_failed_days(dt.date(2026, 11, 16)) == 3, f"three missed days recorded: {health.failed_days}")
three = [n for n in notes if n[0] == "iPhone not backed up for 3 days"]
check(len(three) == 1 and "reach your iPhone" in three[0][1], f"exactly one failure notification, with the fix: {three}")
clock["now"] = D(16, 23, 40)
h.tick()
check(len([n for n in notes if n[0] == "iPhone not backed up for 3 days"]) == 1, "no second notification the same day")
card = sch.card_state(sch.Plan.from_settings(json.loads(hc.SETTINGS_FILE.read_text())), health, D(16, 23, 45))
check(card[0] == "amber" and card[1].startswith("Last backup 3 days ago.") and "reach your iPhone" in card[1], f"phone card amber line: {card[1]!r}")
lines = h.status_lines()
check(any(l.startswith("⚠ Last backup") for l in lines), f"menu shows the amber line too: {lines}")

# only when charging
hc.SETTINGS_FILE.write_text(json.dumps({"auto_backup": "daily", "auto_backup_hour": 21, "auto_backup_charging": True, "backup_dir": str(W / "Backups")}))
reach["on"] = True
clock["now"] = D(17, 21, 1)
r = h.tick(); wait_idle(h)
check("charging" in r and backups_made() == 2, "only when charging: not charging → waits")
(W / "charging.flag").write_text("1")
clock["now"] = D(17, 21, 32)
r = h.tick(); wait_idle(h)
check(backups_made() == 3, "plugged in → the backup runs")
health = sch.Health.load(W / "Backups" / UD)
check(health.failed_days == [] and health.last_ok == D(17, 21, 32), "a good backup clears the failed days")

# paused / off
hc.SETTINGS_FILE.write_text(json.dumps({"auto_backup": "daily", "auto_backup_hour": 21, "auto_backup_paused": True, "backup_dir": str(W / "Backups")}))
clock["now"] = D(18, 21, 1)
check(h.tick() == "off" and backups_made() == 3, "paused: nothing runs")


# the first-run guide now asks "Back up automatically every day?" (hidden until this feature existed)
import app as appmod
check(appmod.App.FEATURES["scheduler"] is True, "first-run guide's daily-backup question is on with B2")

print("\nB2 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
