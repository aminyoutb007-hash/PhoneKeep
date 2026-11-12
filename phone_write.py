"""The only door to writing on the iPhone (docs/spec/12-engineering.md, architecture rules).

Every action that changes the phone goes through `run()`:
  - it must have been confirmed by the owner (an explicit button or a named dialog; the caller
    passes `confirmed=True` only after that happened — see 04-security.md S1 for which clicks count);
  - it is written to the activity log (S7) as one plain line, never containing a password or any
    message text.

No other module may call a phone-write API directly. In P1 the actions are: turning backup
encryption on, changing the backup password, and turning on Wi-Fi sync.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable, Optional, TypeVar

import phonekeep as wv

T = TypeVar("T")

ACTIVITY_FILE = wv.DEFAULT_HOME / "activity.jsonl"


class NotConfirmed(wv.PhoneKeepError):
    pass


def log_activity(summary: str, phone: Optional[str] = None, kind: str = "phone-write") -> None:
    """One line, local only, kept 12 months (S7). `summary` must never contain a password or message text."""
    try:
        ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"when": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind,
                                "phone": phone, "summary": summary}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run(action: str, phone_name: str, fn: Callable[[], T], *, confirmed: bool) -> T:
    """Perform `fn` (which writes to the phone) after the owner confirmed `action`, and log it.

    `action` is the plain-words summary that goes in the activity log, e.g.
    "Turned on backup encryption" or "Changed the backup password".
    """
    if not confirmed:
        raise NotConfirmed(f"{action}: not confirmed by the owner, nothing was changed.")
    result = fn()
    log_activity(action, phone_name)
    return result


# -- the P1 actions ---------------------------------------------------------------------------

def turn_on_encryption(udid: Optional[str], phone_name: str, password: str, *, confirmed: bool,
                       log=lambda m: None) -> None:
    run("Turned on backup encryption", phone_name,
        lambda: wv.set_backup_encryption(True, password, udid, log), confirmed=confirmed)


def turn_off_encryption(udid: Optional[str], phone_name: str, password: str, *, confirmed: bool,
                        log=lambda m: None) -> None:
    run("Turned off backup encryption", phone_name,
        lambda: wv.set_backup_encryption(False, password, udid, log), confirmed=confirmed)


def change_password(udid: Optional[str], phone_name: str, old: str, new: str, *, confirmed: bool,
                    log=lambda m: None) -> None:
    run("Changed the backup password", phone_name,
        lambda: wv.change_backup_password(old, new, udid, log), confirmed=confirmed)
