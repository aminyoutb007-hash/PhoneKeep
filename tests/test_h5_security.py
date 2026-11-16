"""H5: the Security card (docs/spec/13-phone-health.md#h5-security-card).

Done when:
- with test fixtures, each check produces its warning: no passcode, an unknown profile, an app from outside the App
  Store, jailbreak signs, an old iOS version;
- a clean fixture shows all ticks and the wording "No problems found in these checks";
- no check writes anything to the phone (verified by the phone-write gate's log).
The phone is a set of fake services that record every request; the fixtures are what --pk-security reads from a
phone. The spyware check (S5) isn't built. Names are invented.
"""
import asyncio, contextlib, datetime as dt, io, json, os, shutil, sys, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE / "work" / "h5"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
os.environ["PHONEKEEP_HOME"] = str(W / "home")
os.environ["PHONEKEEP_NO_HELPER"] = "1"
sys.path.insert(0, str(HERE.parent))

import checkup as cu
import security as sx

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


CLEAN = {"password_protected": True, "ios": "27.2.1", "product_type": "iPhone16,1", "profiles": [],
         "management": {"supervised": False, "org": "", "server": "", "mdm_unremovable": False},
         "outside": [], "user_apps": 120, "jailbreak": [], "problems": {}}


def run_checks(raw, known=frozenset(), seen=False):
    cs = sx.checks(raw, known, [seen])
    return {c.key: c for c in cs}, cs


# -- a clean phone: all ticks, "No problems found in these checks" --------------------------------------------------------
by, cs = run_checks(CLEAN)
check([c.state for c in cs] == ["ok", "ok", "ok", "ok", "ok", "unknown"] and by["spyware"].title == "Spyware check",
      f"a clean fixture: a tick for each check (the spyware check isn't built: shown as not checked): "
      f"{[(c.key, c.state) for c in cs]}")
card = cu.security_card(cu.Facts(when=dt.datetime.now(), **sx.facts(cs)))
check(card.level == "green" and card.reason == "Green: No problems found in these checks." and "safe" not in
      card.reason.lower(), f"the card: {card.reason}")
check(by["ios"].text.startswith("iOS 27.2.1 has the latest security updates") and
      "Latest iOS known to PhoneKeep: 27.2.1, 9 Nov 2026" in by["ios"].text, f"iOS, with the list's date: {by['ios'].text}")
check(by["outside"].text == "All 120 apps came from the App Store." and by["jailbreak"].state == "ok",
      "the apps and jailbreak checks say what they looked at")

# -- each check produces its warning --------------------------------------------------------------------------------------
sx.PASSCODE_FLAG = "set"                             # as it will be once a read on an unlocked iPhone settles it
by, _ = run_checks({**CLEAN, "password_protected": False})
check(by["passcode"].state == "warn" and by["passcode"].advice == sx.ADVICE["passcode"], "no passcode: its warning")
sx.PASSCODE_FLAG = None
by, _ = run_checks({**CLEAN, "password_protected": False})
check(by["passcode"].state == "unknown", "while the flag's meaning isn't settled, a False read says nothing (unknown)")
by, _ = run_checks({**CLEAN, "password_protected": False}, seen=True)
check(by["passcode"].state == "ok", "a passcode seen at an earlier check counts")

prof = {**CLEAN, "profiles": [{"id": "com.example.track", "name": "Example Tracker", "org": "Example Ltd",
                               "removable": True, "active": True}]}
by, cs = run_checks(prof)
check(by["profiles"].state == "warn" and by["profiles"].text == "Example Tracker (from Example Ltd)"
      and "VPN & Device Management" in by["profiles"].advice, f"an unknown profile, named with who installed it: {by['profiles'].text}")
c = cu.security_card(cu.Facts(when=dt.datetime.now(), **sx.facts(cs)))
check(c.level == "red" and c.reason == "Red: An unknown configuration profile or device management is installed: "
      "Example Tracker (from Example Ltd).", f"the card: {c.reason}")
by, _ = run_checks(prof, known=frozenset({"com.example.track"}))
check(by["profiles"].state == "ok", "once the owner recognises it, no warning")
mdm = {**CLEAN, "management": {"supervised": True, "org": "Example School", "server": "", "mdm_unremovable": False}}
by, _ = run_checks(mdm)
check(by["profiles"].text == "Device management by Example School (the iPhone is supervised)", f"device management: {by['profiles'].text}")

side = {**CLEAN, "outside": [{"bundle": "com.example.dev", "name": "Test Build", "signer": "Apple Development: Sam Lee (AB12)", "marketplace": ""},
                             {"bundle": "com.example.corp", "name": "Corp Tools", "signer": "iPhone Distribution: Example Corp", "marketplace": ""},
                             {"bundle": "com.example.mkt", "name": "Market Game", "signer": "Apple iPhone OS Application Signing", "marketplace": "com.example.store"}]}
by, cs = run_checks(side)
check(by["outside"].state == "warn" and by["outside"].text == (
      "Test Build: installed by a developer, with Xcode or a similar tool; Corp Tools: installed with a company's "
      "certificate (Example Corp); Market Game: from an alternative app marketplace"),
      f"apps from outside the App Store, each named with how it was installed: {by['outside'].text}")
c = cu.security_card(cu.Facts(when=dt.datetime.now(), **sx.facts(cs)))
check(c.level == "amber" and c.reason == "Amber: An app from outside the App Store: Test Build.", f"the card: {c.reason}")

jb = {**CLEAN, "jailbreak": ["the jailbreak app Sileo", "the full-disk file service (afc2), which only jailbreaks add"]}
by, cs = run_checks(jb)
check(by["jailbreak"].state == "warn" and "Sileo" in by["jailbreak"].text and "protections" in by["jailbreak"].advice,
      f"jailbreak signs, named, with what a jailbreak means: {by['jailbreak'].text}")
c = cu.security_card(cu.Facts(when=dt.datetime.now(), **sx.facts(cs)))
check(c.level == "red" and c.reason.startswith("Red: Signs of a jailbreak were found: the jailbreak app Sileo"),
      f"the card: {c.reason}")

for ios, model, state, start in (
        ("27.1", "iPhone17,1", "warn", "iOS is out of date: this iPhone has iOS 27.1, and 27.2.1 is available."),
        ("26.7.3", "iPhone14,2", "ok", "iOS 26.7.3 has the latest security updates for its version. iOS 27.2.1 is also available"),
        ("26.5", "iPhone14,2", "warn", "iOS is out of date: this iPhone has iOS 26.5, and 26.7.3 is available."),
        ("18.7.12", "iPhone11,8", "ok", "iOS 18.7.12 has the latest security updates for its version. ("),
        ("17.6.1", "iPhone11,8", "warn", "iOS is out of date: this iPhone has iOS 17.6.1, which no longer gets security updates; it can update to iOS 18.7.12."),
        ("16.7.10", "iPhone10,3", "warn", "This iPhone has iOS 16.7.10 and can't update further"),
        ("27.3", "iPhone18,1", "ok", "iOS 27.3 is newer than PhoneKeep's list.")):
    c = sx.ios_check(ios, model)
    check(c.state == state and c.text.startswith(start), f"iOS {ios} on {model}: {c.text[:90]}")
by, cs = run_checks({**CLEAN, "ios": "27.1"})
c = cu.security_card(cu.Facts(when=dt.datetime.now(), **sx.facts(cs)))
check(c.level == "amber" and c.reason == "Amber: iOS is out of date." and "Software Update" in c.details[0],
      f"an old iOS version: {c.reason}")

# -- the reads: only reads, and the phone-write gate's log stays empty -----------------------------------------------------
CALLS = []
PHONE_VALUES = {"PasswordProtected": True, "ProductVersion": "27.1", "ProductType": "iPhone16,1", "BuildVersion": "24B1"}


class FakeLockdown:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def get_value(self, key=None, domain=None):
        CALLS.append(("get_value", key))
        return PHONE_VALUES.get(key)

    async def start_lockdown_service(self, name):
        CALLS.append(("start_service", name))
        raise RuntimeError("InvalidServiceError")      # afc2 isn't there: no jailbreak

    def __getattr__(self, name):
        def refuse(*a, **k):
            CALLS.append(("REFUSED lockdown." + name,))
            raise RuntimeError(name)
        return refuse


class FakeMC:
    def __init__(self, lockdown):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def get_profile_list(self):
        CALLS.append(("get_profile_list",))
        return {"ProfileMetadata": {"com.example.track": {"PayloadDisplayName": "Example Tracker",
                                                          "PayloadOrganization": "Example Ltd"}},
                "ProfileManifest": {"com.example.track": {"IsActive": True}}, "OrderedIdentifiers": [], "Status": "Acknowledged"}

    async def get_cloud_configuration(self):
        CALLS.append(("get_cloud_configuration",))
        return {"IsSupervised": False}

    def __getattr__(self, name):                      # install, remove, erase, flush… recorded and refused
        def refuse(*a, **k):
            CALLS.append(("REFUSED mobileconfig." + name,))
            raise RuntimeError(name)
        return refuse


class FakeIP:
    def __init__(self, lockdown):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def get_apps(self, application_type="Any", **k):
        CALLS.append(("get_apps", application_type))
        return {"com.example.chat": {"ApplicationType": "User", "CFBundleDisplayName": "Chat App",
                                     "SignerIdentity": "Apple iPhone OS Application Signing"},
                "com.example.dev": {"ApplicationType": "User", "CFBundleDisplayName": "Test Build",
                                    "SignerIdentity": "Apple Development: Sam Lee (AB12)"},
                "org.coolstar.SileoStore": {"ApplicationType": "System", "CFBundleDisplayName": "Sileo"},
                "com.apple.mobilesafari": {"ApplicationType": "System", "CFBundleDisplayName": "Safari"}}

    def __getattr__(self, name):
        def refuse(*a, **k):
            CALLS.append(("REFUSED apps." + name,))
            raise RuntimeError(name)
        return refuse


async def fake_connect(serial=None):
    return FakeLockdown()

import pymobiledevice3.lockdown as pl
import pymobiledevice3.services.mobile_config as pmc
import pymobiledevice3.services.installation_proxy as pip_
real = (pl.create_using_usbmux, pmc.MobileConfigService, pip_.InstallationProxyService)
pl.create_using_usbmux, pmc.MobileConfigService, pip_.InstallationProxyService = fake_connect, FakeMC, FakeIP
import launcher
import phone_write
import activity
out = io.StringIO()
with contextlib.redirect_stdout(out):
    launcher._pk_security([])
pl.create_using_usbmux, pmc.MobileConfigService, pip_.InstallationProxyService = real
line = next(l for l in out.getvalue().splitlines() if l.startswith("PKSECURITY "))
raw = json.loads(line[len("PKSECURITY "):])
check(raw["ios"] == "27.1" and raw["profiles"][0]["name"] == "Example Tracker" and raw["outside"][0]["name"] == "Test Build"
      and raw["jailbreak"] == ["the jailbreak app Sileo"] and raw["user_apps"] == 2,
      "--pk-security reads the version, the profiles, the apps from outside the App Store and the jailbreak signs")
kinds = sorted({c[0] for c in CALLS})
check(not [c for c in CALLS if c[0].startswith("REFUSED")] and set(kinds) <= {
      "get_value", "get_profile_list", "get_cloud_configuration", "get_apps", "start_service"}
      and ("start_service", "com.apple.afc2") in CALLS,
      f"only reads (lockdown values, the profile list, the cloud configuration, the app list, the afc2 probe): {kinds}")
check(not activity.ACTIVITY_FILE.exists() or not activity.ACTIVITY_FILE.read_text().strip(),
      "the phone-write gate's log is empty after the checks: nothing was written to the phone")
src = (HERE.parent / "launcher.py").read_text(encoding="utf-8")
body = src[src.index("def _pk_security"):src.index("def _pk_battery")]
check(not any(w in body for w in ("install_profile", "remove_profile", "erase", "set_value", "phone_write", ".flush(")),
      "the security reads' code has no call that changes the phone")

# -- the record, and the check-up with the phone away ------------------------------------------------------------------------
pd = W / "backups" / "00008130-FAKE"
cu.record_security(pd, sx.summary(raw, dt.datetime.now()))
d = cu.load(pd)
check(d["security"]["passcode_seen"] is True, "a locked read is remembered: a passcode was seen")
r = cu.check(pd)
check(r is not None and r.card("security").level == "red" and "Example Tracker" in r.card("security").reason,
      f"the check-up reads the record: {r.card('security').reason if r else None}")
cu.recognise(pd, "com.example.track")
r = cu.check(pd)
check(not any("Example Tracker" in x for x in r.card("security").details) and r.card("security").reason.startswith(
      "Red: Signs of a jailbreak"), f"after 'I recognise this' the profile isn't a finding any more: {r.card('security').reason}")

import phonekeep as wv
seen = {}


def fake_run(cmd, **kw):
    seen["cmd"], seen["timeout"] = cmd, kw.get("timeout")
    return types.SimpleNamespace(stdout=line + "\n", returncode=0)

real_run = wv.subprocess.run
wv.subprocess.run, wv.check_pmd3 = fake_run, (lambda: None)
got = wv.read_security("00008130-FAKE", pd, timeout=wv.CHECKUP_TIMEOUT)
wv.subprocess.run = real_run
check(got is not None and "--pk-security" in seen["cmd"] and seen["timeout"] == 20,
      "read_security runs the reads with the backup's 20 s timeout")
check("read_security(udid, _snaps.phone_dir(backup_root, udid), timeout=CHECKUP_TIMEOUT)"
      in (HERE.parent / "phonekeep.py").read_text(encoding="utf-8"), "each backup runs the checks after the record")

# -- Security details --------------------------------------------------------------------------------------------------------
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
            self.backup_dir, self.udid, self.current = W / "backups", "00008130-FAKE", None
            self.overview, self.live = None, None
            self.view_header = lambda key, sub="": phone.PhoneWindow.view_header(self, key, sub)

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            pass

    def texts(w, out=None):
        out = [] if out is None else out
        for x in w.winfo_children():
            if isinstance(x, tk.Label):
                out.append(x.cget("text"))
            if isinstance(x, checkup_ui.RoundButton):
                out.append("[" + x.text + "]")
            texts(x, out)
        return out
    d = cu.load(pd)
    d["known_profiles"] = []
    cu._save(pd, d)
    win = Win()
    checkup_ui.view(win)
    checkup_ui.details(win, "security")
    win.update()
    t = texts(win.content)
    check(all(f"{m}  {title}" in t for m, title in (("✓", "Passcode"), ("⚠", "iOS version"),
                                                     ("⚠", "Configuration profiles and device management"),
                                                     ("⚠", "Apps from outside the App Store"),
                                                     ("⚠", "Signs of a jailbreak"), ("–", "Spyware check"))),
          "the details list each check with a tick or a warning")
    check("[I recognise Example Tracker]" in t and sx.LOCKDOWN_MODE in t and any("Access Now" in x for x in t),
          "with 'I recognise this' for a profile, and Lockdown Mode and help organisations when something is serious")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

spec = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"security"' in spec, "the packaged app includes the security checks")
print(f"H5 TESTS: {'PASS' if not failures else 'FAIL (' + str(len(failures)) + ')'}")
sys.exit(1 if failures else 0)
