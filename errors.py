"""Plain-language errors (E3 in docs/spec/05-ease-of-use.md).

ONE table maps every known technical error to what the user sees: one sentence on what happened
and one button to fix it. Everything that shows an error to the user goes through `explain()`;
the technical text is kept in `Problem.details` for "Show details", never shown on its own.

Add a row here when a new situation appears. Never add a second place that words errors.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# action keys the windows know how to perform
TRY_AGAIN = "try_again"
CHANGE_LOCATION = "change_location"
SHOW_DETAILS = "show_details"
INSTALL_APPLE_DEVICES = "install_apple_devices"
ENTER_PASSWORD = "enter_password"


@dataclass
class Problem:
    key: str                      # row name, for tests and the activity log
    message: str                  # one sentence, plain words
    button: str                   # the one button's label
    action: str                   # what the button does (keys above)
    details: str = ""             # the technical text, behind "Show details"
    failure: bool = True          # red banner only for real failures (waiting for a drive is amber)


# (key, patterns to look for in the technical text (lower-case), message, button label, action)
# Order matters: the first row that matches wins.
TABLE = [
    ("backup_incomplete",
     ["backup didn't finish", "incomplete backup", "no manifest.db", "manifest.db missing"],
     "The last backup didn't finish. Back up again to complete it.", "Back up now", TRY_AGAIN),
    ("wrong_password",
     ["could not unlock the backup", "wrong password", "incorrect password", "invalid password",
      "bad decrypt", "that password doesn't open", "keybag", "unlock failed"],
     "That password doesn't open this backup.", "Try again", TRY_AGAIN),
    ("password_needed",
     ["enter the backup password", "passwordrequired", "backup is encrypted"],
     "This backup is protected with a password.", "Enter password", ENTER_PASSWORD),
    ("disk_full",
     ["no space left", "disk full", "enospc", "errno 28", "not enough space", "insufficient disk",
      "there is not enough space", "error 112", "winerror 112",
      "notenoughdiskspace", "needs more than", "bytes free", "more needed)"],      # the iPhone's own refusal
     "Not enough space on {disk}: {free} free.", "Change location", CHANGE_LOCATION),
    ("apple_service_missing",
     ["usbmuxd", "apple mobile device", "could not connect to usbmuxd", "connectionrefused", "no usbmux"],
     "Can't reach Apple's USB service. Install the Apple Devices app (from the Microsoft Store) or iTunes, then try again."
     if os.name == "nt" else
     "Can't reach your iPhone. Reconnect the cable, unlock it and try again.",
     "Install Apple Devices" if os.name == "nt" else "Try again",
     INSTALL_APPLE_DEVICES if os.name == "nt" else TRY_AGAIN),
    ("not_trusted",
     ["pairing", "not paired", "notpaired", "trust", "passwordprotected", "pairingdialogresponsepending",
      "user denied", "invalidhostid", "pair record"],
     "Tap Trust on your iPhone and enter your passcode.", "Try again", TRY_AGAIN),
    ("phone_locked",
     ["passcode", "device is locked", "locked", "password protected", "deviceLocked".lower(),
      "backup needs the device to be unlocked"],
     "Unlock your iPhone to continue.", "Try again", TRY_AGAIN),
    ("wifi_unreachable",
     ["wi-fi", "wifi", "no device found", "nodevice", "device not found", "not reachable", "timed out",
      "timeout", "connection reset", "network is unreachable", "no route to host", "host is down",
      "device disconnected", "connection lost", "broken pipe"],
     "Can't reach your iPhone over Wi-Fi. Make sure it's on the same network, or use a cable.", "Try again", TRY_AGAIN),
]

UNKNOWN = ("unknown", "Something went wrong. Your existing backups are safe.", "Show details", SHOW_DETAILS)


def _disk_name(path: Optional[Path]) -> str:
    if not path:
        return "this disk"
    p = Path(path)
    parts = p.resolve().parts
    if len(parts) >= 3 and parts[1] in ("Volumes",):           # /Volumes/Backup Drive/...
        return parts[2]
    if os.name == "nt" and p.drive:
        return p.drive.rstrip(":").upper() + ":"
    return "this disk"


def _free_text(path: Optional[Path]) -> str:
    try:
        free = shutil.disk_usage(str(path or Path.home())).free
    except OSError:
        return "very little"
    gb = free / 1e9
    return f"{gb:.1f} GB" if gb < 100 else f"{gb:.0f} GB"


def explain(error, where: Optional[Path] = None, needed_bytes: Optional[int] = None) -> Problem:
    """Map an exception or a block of technical text to one Problem from the table."""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}"
        if isinstance(error, OSError) and getattr(error, "errno", None) == 28:
            text += " (ENOSPC)"
    else:
        text = str(error or "")
    low = text.lower()
    for key, patterns, message, button, action in TABLE:
        if any(p in low for p in patterns):
            if key == "disk_full":
                m = re.search(r"needs more than (\d+) bytes free", low)      # the phone says how much it wants
                if m:
                    needed_bytes = int(m.group(1))
                need = f"{needed_bytes / 1e9:.1f} GB needed, " if needed_bytes else ""
                message = f"Not enough space on {_disk_name(where)}: {need}{_free_text(where)} free."
            return Problem(key, message, button, action, details=text)
    key, message, button, action = UNKNOWN
    if isinstance(error, BaseException) and error.__traceback__ is not None:
        # an error nobody expected: where it happened is what support needs (13 Nov: "error: Error -3 while
        # decompressing data" alone didn't say which file or which step)
        import traceback
        text += "\n\n" + "".join(traceback.format_exception(type(error), error, error.__traceback__, limit=-12)).rstrip()
    return Problem(key, message, button, action, details=text)


def short(error) -> str:
    """The one-sentence message only (for logs and the command line)."""
    return explain(error).message


def is_plain(message: str) -> bool:
    """True when a message carries no technical words (used by the tests)."""
    bad = ["traceback", "exception", "errno", "0x", "stack", "assert", "nonetype", "attributeerror",
           "keyerror", "oserror", "runtimeerror", "valueerror", "socket", "usbmux", "lockdown", "afc"]
    low = message.lower()
    return not any(b in low for b in bad) and not re.search(r"\b[A-Z][a-z]+Error\b", message)
