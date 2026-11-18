"""H4: the Stability card (docs/spec/13-phone-health.md#h4-stability-card).

Done when:
- with seeded crash reports, the card lists the right apps and counts, and a seeded unexpected restart shows as red;
  iOS restarting itself (SystemMemoryReset) shows as amber, "possibly by itself" (owner, 14 Nov);
- after a check, the crash reports are still on the phone.
The seeded reports have the kinds a real iPhone keeps (14 Nov: crashes, panics and iOS restarting itself, plus CPU and
disk-use notices, hangs, memory events, battery logs and feedback reports that aren't crashes). The phone is a fake
crash-report service that records every call. App names are invented.
"""
import asyncio, datetime as dt, json, os, shutil, subprocess, sys, types, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE / "work" / "h4"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
os.environ["PHONEKEEP_HOME"] = str(W / "home")
os.environ["PHONEKEEP_NO_HELPER"] = "1"
sys.path.insert(0, str(HERE.parent))

import checkup as cu
import crashes as cr

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


NOW = dt.datetime.now().replace(microsecond=0)
APPS = {"com.example.chat": "Chat App", "com.example.maps": "Trail Maps", "com.example.home": "Home Hub"}


def ips(bug, when, **h):
    stamp = when.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.00 +0000")
    return json.dumps({"bug_type": str(bug), "timestamp": stamp, **h}) + "\n{\"rest\": \"of the report\"}\n"


def fname(kind, when, ext=".ips"):
    return f"{kind}-{when:%Y-%m-%d-%H%M%S}{ext}"


PHONE = {}          # what the fake phone's crash-report folder holds: path -> bytes


def put(path, text):
    PHONE[path] = text.encode()


for k in range(12):                                     # 12 crashes of one app this week
    w = NOW - dt.timedelta(hours=5 + 11 * k)
    put(fname("ChatApp", w), ips(309, w, app_name="ChatApp", bundleID="com.example.chat", name="ChatApp"))
for k in range(2):
    w = NOW - dt.timedelta(days=2, hours=k)
    put(fname("TrailMaps", w), ips(309, w, app_name="TrailMaps", bundleID="com.example.maps"))
w = NOW - dt.timedelta(days=1)                          # a home-screen widget of an app: counted under the app
put(fname("HomeHubWidgetExtension", w), ips(309, w, app_name="HomeHubWidgetExtension",
                                            bundleID="com.example.home.widget"))
w = NOW - dt.timedelta(days=12)                         # a crash before this week: not counted on the card
put(fname("TrailMaps", w), ips(309, w, app_name="TrailMaps", bundleID="com.example.maps"))
w = NOW - dt.timedelta(days=3)                          # a system process (no bundle id): not an app
put(fname("mediaserverd", w), ips(309, w, name="mediaserverd"))
w = NOW - dt.timedelta(days=4)                          # not crashes
put(fname("backupd.cpu_resource", w), ips(202, w, app_name="backupd"))
put(fname("installd.diskwrites_resource", w), ips(145, w, app_name="installd", bundleID="com.apple.installd"))
put(fname("JetsamEvent", w), ips(298, w))
put(fname("stacks", w), ips(288, w))
put(fname("LowBatteryLog", w), ips(120, w))
put(fname("SiriSearchFeedback", w), ips(313, w))
put("Retired/" + fname("OldApp", NOW - dt.timedelta(days=60)), ips(309, NOW - dt.timedelta(days=60), bundleID="com.x"))
w = NOW - dt.timedelta(days=1, hours=3)
put("Assistant/" + fname("panic-full", w), ips(210, w))  # an unexpected restart (in a subfolder)
w = NOW - dt.timedelta(days=2, hours=5)
put(fname("SystemMemoryReset", w), ips(298, w))          # iOS restarting itself: amber, not red (owner, 14 Nov)
put("notes.txt", "not a report")

# -- the fake crash-report service: every call recorded ----------------------------------------------------------------
CALLS = []


class FakeAfc:
    def __init__(self, lockdown, service_name=None):
        CALLS.append(("open", service_name))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        CALLS.append(("close",))

    async def walk(self, top):
        CALLS.append(("walk", top))
        dirs = {}
        for p in PHONE:
            d, _, f = p.rpartition("/")
            dirs.setdefault(d, []).append(f)
        for d, files in sorted(dirs.items()):
            yield ("/" + d) if d else "/", [], files

    async def stat(self, path):
        CALLS.append(("stat", path))
        return {"st_mtime": NOW, "st_size": len(PHONE[path])}

    async def get_file_contents(self, path):
        CALLS.append(("read", path))
        return PHONE[path]

    def __getattr__(self, name):                      # anything else (rm, rename, push…) is recorded and refused
        def refuse(*a, **k):
            CALLS.append(("REFUSED " + name, a))
            raise RuntimeError(f"{name} isn't allowed")
        return refuse


class FakeLockdown:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def start_lockdown_service(self, name):     # crashreportmover (flush) would come through here
        CALLS.append(("REFUSED service " + name,))
        raise RuntimeError("not allowed")


async def fake_connect(serial=None):
    return FakeLockdown()

import pymobiledevice3.lockdown as pl
import pymobiledevice3.services.afc as pa
real = (pl.create_using_usbmux, pa.AfcService)
pl.create_using_usbmux, pa.AfcService = fake_connect, FakeAfc
import launcher
import io, contextlib

phone_dir = W / "backups" / "00008120-FAKE"
folder = phone_dir / cr.FOLDER
before = dict(PHONE)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    launcher._pk_crashes([str(folder), "--days", "30"])
lines = out.getvalue().splitlines()
copied = [l[len("PKCRASH "):] for l in lines if l.startswith("PKCRASH ")]
check(lines[-1] == f"PKDONE {len(copied)}" and len(copied) == len(PHONE) - 2,
      f"the reports of the last 30 days are copied ({len(copied)}; the 60-day-old one and the text file aren't)")
check(all((folder / c).read_bytes() == PHONE[c] for c in copied), "each copy is the report itself")
check(PHONE == before, "after a check, the crash reports are still on the phone, unchanged")
check(not [c for c in CALLS if c[0].startswith("REFUSED")] and {c[0] for c in CALLS} <= {"open", "walk", "stat", "read", "close"}
      and ("open", "com.apple.crashreportcopymobile") in CALLS,
      f"only listing and reading: nothing removed, moved or flushed ({sorted({c[0] for c in CALLS})})")
CALLS.clear()
out = io.StringIO()
with contextlib.redirect_stdout(out):
    launcher._pk_crashes([str(folder), "--days", "30"])
check(not [l for l in out.getvalue().splitlines() if l.startswith("PKCRASH")] and not [c for c in CALLS if c[0] == "read"],
      "a second check copies nothing it already has")
pl.create_using_usbmux, pa.AfcService = real

# -- what the reports say ------------------------------------------------------------------------------------------------
events = cr.read_folder(folder, APPS)
kinds = sorted((e.kind, e.app) for e in events)
check(kinds.count(("crash", "Chat App")) == 12 and kinds.count(("crash", "Trail Maps")) == 3
      and kinds.count(("crash", "Home Hub")) == 1 and kinds.count(("restart", "")) == 1
      and kinds.count(("self_restart", "")) == 1 and len(kinds) == 18,
      f"crashes by app (names, not bundle ids; a widget under its app), the panic and iOS restarting itself; nothing "
      f"else: {len(kinds)}")
summary = cr.summary(events, NOW)
crash7, restarts7 = cr.counts(summary, 7)
check(crash7 == {"Chat App": 12, "Trail Maps": 2, "Home Hub": 1} and restarts7 == 1,
      f"the last 7 days: {crash7}, {restarts7} restart")
check(cr.counts(None, 7) == (None, None), "never read: not checked")
check(cr.self_restarts(summary, 7) == 1 and cr.self_restarts(None, 7) is None,
      "iOS restarting itself is counted on its own, not as an unexpected restart")
legacy = {**summary, "events": [{**e, "kind": "restart"} if e["file"].startswith("SystemMemoryReset") else e
                                for e in summary["events"]]}
check(cr.counts(legacy, 7)[1] == 1 and cr.self_restarts(legacy, 7) == 1,
      "a record kept before this change (its SystemMemoryReset called a restart) is read the new way")

cu.record_stability(phone_dir, summary)
f = cu.Facts(when=NOW, crashes=crash7, unexpected_restarts=restarts7, self_restarts=1)
c = cu.stability_card(f)
check(c.level == "red" and c.reason == "Red: The iPhone restarted unexpectedly once this week.",
      f"a seeded unexpected restart shows as red: {c.reason}")
check(c.details[1] == "Chat App crashed 12 times this week. " + cr.ADVICE and len(c.details) == 3
      and c.details[2] == "The iPhone restarted once this week, possibly by itself. " + cr.SELF_RESTART_ADVICE,
      f"the apps, most crashes first, each with the spec's advice, then the restart iOS did itself: {c.details[1:]}")
c5 = cu.stability_card(cu.Facts(when=NOW, crashes={}, unexpected_restarts=0, self_restarts=1))
check(c5.level == "amber" and c5.reason == "Amber: The iPhone restarted once this week, possibly by itself.",
      f"iOS restarting itself alone shows as amber, not red: {c5.reason}")
c6 = cu.stability_card(cu.Facts(when=NOW, crashes={"Trail Maps": 3}, unexpected_restarts=0, self_restarts=2))
check(c6.level == "amber" and c6.reason == "Amber: Trail Maps crashed 3 times this week." and
      c6.details[-1].startswith("The iPhone restarted 2 times this week, possibly by itself."),
      f"with an app's crashes: still amber, the app first: {c6.reason}")
c2 = cu.stability_card(cu.Facts(when=NOW, crashes=crash7, unexpected_restarts=0))
check(c2.level == "red" and c2.reason == "Red: Chat App crashed 12 times this week.", f"without the restart: {c2.reason}")
c3 = cu.stability_card(cu.Facts(when=NOW, crashes={"Trail Maps": 3}, unexpected_restarts=0))
check(c3.level == "amber" and c3.reason == "Amber: Trail Maps crashed 3 times this week.", f"3 crashes: {c3.reason}")
c4 = cu.stability_card(cu.Facts(when=NOW, crashes={}, unexpected_restarts=0))
check(c4.reason == "Green: No app crashes in the last 7 days.", f"nothing: {c4.reason}")
d = cu.load(phone_dir)
cu._save(phone_dir, {**d, "history": [{"when": NOW.isoformat(), "total": 128 * 10 ** 9, "free": 60 * 10 ** 9,
                                       "health": 95}]})
rep = cu.check(phone_dir)
check(rep.card("stability").level == "red" and rep.card("stability").reason.endswith("once this week."),
      "the check-up reads the record: Stability as of the last read, with the phone away")

days = cr.by_day(summary, 7)
check(days[0][0] == "Chat App" and sum(n for _d, n in days[0][1]) == 12 and len(days[0][1]) >= 5
      and ("", [((NOW - dt.timedelta(days=1, hours=3)).date(), 1)]) in days
      and (cr.SELF_RESTART, [((NOW - dt.timedelta(days=2, hours=5)).date(), 1)]) in days,
      "grouped by app and day for the details, both kinds of restart too")

z = cr.save_zip(folder, summary["events"], W / "out" / "reports.zip")
names = zipfile.ZipFile(z).namelist()
check(len(names) == 18 and any(n.startswith("Assistant/panic-full") for n in names), f"Save reports zips them ({len(names)})")

old = folder / fname("Ancient", NOW - dt.timedelta(days=45))
old.write_text("x")
n = cr.prune(folder)
check(n == 1 and not old.exists() and (folder / copied[0]).exists(),
      "copies on this computer older than 30 days are removed (the phone's never are)")

# -- after a backup: read with the backup's short timeout, into the phone's folder ------------------------------------------
import phonekeep as wv
seen = {}


def fake_run(cmd, **kw):
    seen["cmd"], seen["timeout"] = cmd, kw.get("timeout")
    return types.SimpleNamespace(stdout="PKDONE 0\n", returncode=0)

real_run = wv.subprocess.run
wv.subprocess.run = fake_run
wv.check_pmd3 = lambda: None
cu._save(phone_dir, {**cu.load(phone_dir), "apps": APPS})
s2 = wv.read_crash_reports("00008120-FAKE", phone_dir, timeout=wv.CHECKUP_TIMEOUT)
wv.subprocess.run = real_run
check("--pk-crashes" in seen["cmd"] and str(folder) in seen["cmd"] and seen["timeout"] == 20 and s2 is not None
      and cr.counts(s2, 7)[0].get("Chat App") == 12,
      "read_crash_reports copies into the phone's folder with the backup's 20 s timeout and records the summary, "
      "names from the saved app list")
src = (HERE.parent / "phonekeep.py").read_text(encoding="utf-8")
check("read_crash_reports(udid, _snaps.phone_dir(backup_root, udid), timeout=CHECKUP_TIMEOUT)" in src,
      "each backup reads the crash reports after the check-up record")

# -- the Stability details -------------------------------------------------------------------------------------------------
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    import checkup_ui, phone

    class Win(tk.Toplevel):
        def __init__(self):
            super().__init__(root)
            self.content = tk.Frame(self)
            self.content.pack(fill="both", expand=True)
            self.backup_dir, self.udid, self.current = W / "backups", "00008120-FAKE", None
            self.overview, self.live = None, None
            self.view_header = lambda key, sub="": phone.PhoneWindow.view_header(self, key, sub)
            self.saved_paths = None

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            pass

        def out_dir(self, key, protectable=True):
            return W / "chosen"

        def saved(self, paths, folder, what):
            self.saved_paths = paths

    win = Win()
    checkup_ui.view(win)
    checkup_ui.details(win, "stability")
    win.update()
    texts = []

    def walk(w):
        for x in w.winfo_children():
            if isinstance(x, tk.Label):
                texts.append(x.cget("text"))
            walk(x)
    walk(win.content)
    check("Chat App: 12 crashes" in texts and "Unexpected restarts: 1" in texts and cr.ADVICE in texts
          and cr.RESTART_ADVICE in texts and "Restarted, possibly by itself: 1" in texts
          and cr.SELF_RESTART_ADVICE in texts, "the details list each app's crashes by day with what to do")
    btn = next(x for x in win.content.winfo_children()[-1].winfo_children() if isinstance(x, checkup_ui.RoundButton))
    btn.command()
    check(win.saved_paths and zipfile.is_zipfile(win.saved_paths[0]), "Save reports… saves the zip where the owner chooses")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

spec = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"crashes"' in spec, "the packaged app includes the crash reports' reading")
print(f"H4 TESTS: {'PASS' if not failures else 'FAIL (' + str(len(failures)) + ')'}")
sys.exit(1 if failures else 0)
