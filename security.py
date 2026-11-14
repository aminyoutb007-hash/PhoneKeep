"""H5: the Security card's checks (docs/spec/13-phone-health.md#h5-security-card).

A security check, not antivirus: it says exactly what it looked at. The launcher (`--pk-security`) reads, and only
reads: the phone's lockdown values, its list of configuration profiles and its device-management (cloud)
configuration, its app list, and whether the full-disk file service only jailbreaks add answers. PhoneKeep never
removes a profile or an app; it reports them. The result is kept in the phone's checkup.json like H1's record.

The checks:
- Passcode: not decided yet. Lockdown's PasswordProtected may only say whether the phone is locked right now (it's
  True on a locked iPhone); the reliable answer (SecurityInfo's PasscodePresent) needs a supervision identity, which
  PhoneKeep doesn't have. Until a read on an unlocked iPhone settles what the flag means, the check says so.
- iOS version: against IOS_KNOWN, shipped with PhoneKeep and labelled with its date.
- Configuration profiles and device management: each one named, with who installed it. Unknown until the owner says
  they recognise it.
- Apps from outside the App Store: signed by someone other than the App Store (a developer, a company certificate), or
  installed from an alternative marketplace.
- Signs of a jailbreak: a jailbreak's own apps, or the full-disk file service.
- Spyware check (S5): not built (waits for the owner's decision on MVT's licence and its indicator downloads).
Kept free of Tk, like checkup.py.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional

# Shipped with each PhoneKeep release (spec: "a small list … labelled with its date"). Each line Apple still patches,
# with its latest version; which line a model can reach comes from its product type (iPhone12,x = iPhone 11 and
# SE 2nd generation, the oldest that run iOS 27).
IOS_KNOWN = {
    "date": dt.date(2026, 11, 9),
    "latest": "27.2.1",
    "lines": {27: "27.2.1", 26: "26.7.3", 18: "18.7.12"},
    "reach": ((12, 27), (11, 18)),          # product-type major and up -> the newest line it can run
}
PASSCODE_FLAG = None      # what lockdown's PasswordProtected means: "set", "locked", or None while not known

ADVICE = {
    "passcode": "No passcode set. Anyone holding the phone can open it. Set one in Settings → Face ID & Passcode.",
    "ios": "Updates fix security problems. Settings → General → Software Update.",
    "profile": "If you don't recognise this, remove it in Settings → General → VPN & Device Management.",
    "outside": ("Apps from outside the App Store haven't been reviewed by Apple. If you didn't install it on purpose, "
                "delete it."),
    "jailbreak": ("A jailbreak turns off the iPhone's own protections, so any app can reach other apps' data. If you "
                  "didn't jailbreak it, back it up and restore it in Finder (or iTunes) to remove it."),
}
LOCKDOWN_MODE = ("Lockdown Mode is an optional, extreme protection for the very few people who may be personally "
                 "targeted by sophisticated attacks (journalists, activists, people at risk). It turns off some "
                 "features to make the iPhone much harder to attack. Turn it on in Settings → Privacy & Security → "
                 "Lockdown Mode.")
HELP = (("Access Now Digital Security Helpline", "https://www.accessnow.org/help/"),
        ("Amnesty International Security Lab", "https://securitylab.amnesty.org/get-help/"))


@dataclass
class Check:
    key: str
    title: str
    state: str                        # "ok", "warn" or "unknown"
    text: str                         # what was found
    advice: str = ""


def _ver(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3]) or (0,)


def known_text(known: dict = IOS_KNOWN) -> str:
    d = known["date"]
    return f"Latest iOS known to PhoneKeep: {known['latest']}, {d.day} {d:%b %Y}"


def newest_line(product_type: Optional[str], known: dict = IOS_KNOWN) -> Optional[int]:
    m = re.match(r"iPhone(\d+),", product_type or "")
    if not m:
        return None
    major = int(m.group(1))
    return next((line for at_least, line in known["reach"] if major >= at_least), 0)


def ios_check(ios: Optional[str], product_type: Optional[str], known: dict = IOS_KNOWN) -> Check:
    title = "iOS version"
    if not ios:
        return Check("ios", title, "unknown", "The iPhone didn't say its iOS version.")
    v, label = _ver(ios), known_text(known)
    line_latest = known["lines"].get(v[0])
    reach = newest_line(product_type, known)
    if v > _ver(known["latest"]) or (line_latest and v > _ver(line_latest)):
        return Check("ios", title, "ok", f"iOS {ios} is newer than PhoneKeep's list. ({label}.)")
    if line_latest and v < _ver(line_latest):
        return Check("ios", title, "warn", f"iOS is out of date: this iPhone has iOS {ios}, and {line_latest} is "
                     f"available. ({label}.)", ADVICE["ios"])
    if line_latest:
        newer = reach and reach > v[0] and reach in known["lines"]
        extra = f" iOS {known['lines'][reach]} is also available for it." if newer else ""
        return Check("ios", title, "ok", f"iOS {ios} has the latest security updates for its version.{extra} ({label}.)")
    if reach:                                         # an old line Apple no longer patches, and a newer one runs here
        target = known["lines"].get(reach, known["latest"])
        return Check("ios", title, "warn", f"iOS is out of date: this iPhone has iOS {ios}, which no longer gets "
                     f"security updates; it can update to iOS {target}. ({label}.)", ADVICE["ios"])
    return Check("ios", title, "warn", f"This iPhone has iOS {ios} and can't update further: Apple no longer sends it "
                 f"security updates. ({label}.)", "Consider a newer iPhone for things like banking.")


def how_installed(app: dict) -> str:
    signer = app.get("signer") or ""
    if app.get("marketplace"):
        return "from an alternative app marketplace"
    if signer.startswith(("iPhone Developer", "Apple Development")):
        return "installed by a developer, with Xcode or a similar tool"
    if signer.startswith("iPhone Distribution"):
        return "installed with a company's certificate (" + signer.split(":", 1)[-1].strip() + ")"
    return f"signed by {signer}" if signer else "not signed by the App Store"


def checks(raw: Optional[dict], known_profiles: frozenset = frozenset(), passcode_reads: list = ()) -> list:
    """Each check with what it found, from what --pk-security read; [] if nothing was read."""
    if not raw:
        return []
    out = []
    pp = raw.get("password_protected")
    if PASSCODE_FLAG == "set" and pp is not None:
        out.append(Check("passcode", "Passcode", "ok" if pp else "warn",
                         "A passcode is set." if pp else "No passcode is set.", "" if pp else ADVICE["passcode"]))
    elif any(r for r in passcode_reads) or pp:
        out.append(Check("passcode", "Passcode", "ok", "A passcode is set (the iPhone was locked with it at a check)."))
    else:
        out.append(Check("passcode", "Passcode", "unknown", "Not decided yet: the iPhone hasn't been seen locked. "
                         "Connect it once while it's locked."))
    out.append(ios_check(raw.get("ios"), raw.get("product_type")))
    if "profiles" in raw:
        found = []
        for p in raw.get("profiles", []):
            if p["id"] in known_profiles:
                continue
            who = f" (from {p['org']})" if p.get("org") else ""
            found.append(f"{p['name']}{who}")
        m = raw.get("management") or {}
        if m.get("supervised") or m.get("server") or m.get("org"):
            who = m.get("org") or m.get("server") or "an organisation"
            if f"management:{who}" not in known_profiles:
                found.append(f"Device management by {who}" + (" (the iPhone is supervised)" if m.get("supervised") else ""))
        out.append(Check("profiles", "Configuration profiles and device management", "warn" if found else "ok",
                         "; ".join(found) if found else
                         "No configuration profiles and no device management (apart from any you said you recognise).",
                         ADVICE["profile"] if found else ""))
    else:
        out.append(Check("profiles", "Configuration profiles and device management", "unknown",
                         "The iPhone didn't list its profiles."))
    if "outside" in raw:
        apps = [f"{a['name']}: {how_installed(a)}" for a in raw["outside"]]
        out.append(Check("outside", "Apps from outside the App Store", "warn" if apps else "ok",
                         "; ".join(apps) if apps else f"All {raw.get('user_apps', 0)} apps came from the App Store.",
                         ADVICE["outside"] if apps else ""))
    else:
        out.append(Check("outside", "Apps from outside the App Store", "unknown", "The iPhone didn't list its apps."))
    jb = raw.get("jailbreak")
    out.append(Check("jailbreak", "Signs of a jailbreak", "unknown" if jb is None else "warn" if jb else "ok",
                     "Not checked." if jb is None else ("Found " + " and ".join(jb) + ".") if jb else
                     "None found: no jailbreak apps, and the full-disk file service isn't there.",
                     ADVICE["jailbreak"] if jb else ""))
    out.append(Check("spyware", "Spyware check", "unknown",
                     "Not available yet in this version of PhoneKeep."))
    return out


def facts(cs: list) -> dict:
    """The Facts fields (checkup.Facts) the Security card is drawn from."""
    by = {c.key: c for c in cs}

    def state(k):
        return by[k].state if k in by else "unknown"
    out = {"no_passcode": None if state("passcode") == "unknown" else state("passcode") == "warn",
           "ios_outdated": None if state("ios") == "unknown" else state("ios") == "warn",
           "unknown_profiles": None if state("profiles") == "unknown" else
           ([x for x in by["profiles"].text.split("; ")] if state("profiles") == "warn" else []),
           "outside_app_store": None if state("outside") == "unknown" else
           ([x.split(": ")[0] for x in by["outside"].text.split("; ")] if state("outside") == "warn" else []),
           "jailbreak": None if state("jailbreak") == "unknown" else
           ([by["jailbreak"].text[len("Found "):-1]] if state("jailbreak") == "warn" else []),
           "spyware_matched": None}
    return out


def summary(raw: dict, read_at: dt.datetime) -> dict:
    """What checkup.json keeps: the last read (names of profiles and apps, no personal data), and passcode reads."""
    return {"read": read_at.isoformat(timespec="seconds"), "raw": raw}
