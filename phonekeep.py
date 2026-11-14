#!/usr/bin/env python3
"""
PhoneKeep - back up your whole iPhone over USB and turn it into a browsable,
searchable offline archive: WhatsApp, Messages, photos, contacts, calls,
notes, calendar, voicemail, voice memos, Safari and every raw file.

Built on open-source libraries:
  * pymobiledevice3       - talks to the iPhone over USB, makes the backup
  * iphone_backup_decrypt - decrypts encrypted local backups

Command line:
  python phonekeep.py devices                 list connected iPhones
  python phonekeep.py backup                  back up the connected iPhone
  python phonekeep.py backups                 list backups found on this computer
  python phonekeep.py export [--backup DIR]   build the full archive
  python phonekeep.py run [--photos]          backup + export in one go
  python phonekeep.py whatsapp                WhatsApp-only archive
  python phonekeep.py photos                  copy photos straight off the phone
  python phonekeep.py encryption on|off       protect backups with a password
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import html
import json
import os
import plistlib
import re
import threading
import time
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from tables import csv_safe as _csv_safe

APP_NAME = "PhoneKeep"
VERSION = "5.0.1"

try:
    from build_label import BUILD_LABEL   # "5.0-dev+B3" on a test build, "" on a release
except Exception:                          # pragma: no cover
    BUILD_LABEL = ""


def full_version() -> str:
    """'4.0.1' for a release, '4.0.1 (build 5.0-dev+B3)' for a test build."""
    return f"{VERSION} (build {BUILD_LABEL})" if BUILD_LABEL else VERSION

WA_DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
WA_BUSINESS_DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared"
WA_DB = "ChatStorage.sqlite"
APPLE_EPOCH = 978307200  # 2001-01-01 in Unix seconds

# PHONEKEEP_HOME: the tests point this at their own folder, so they never write to the real one
DEFAULT_HOME = Path(os.environ.get("PHONEKEEP_HOME") or Path.home() / "PhoneKeep")
DEFAULT_BACKUP_DIR = DEFAULT_HOME / "Backups"

# what the windows and the menu bar say, big, while the iPhone waits for its passcode
PASSCODE_PROMPT = "Look at your iPhone: unlock it and enter its passcode to start the backup."
DEFAULT_ARCHIVE_DIR = DEFAULT_HOME / "Archive"

Log = Callable[[str], None]


def _print(msg: str) -> None:
    print(msg, flush=True)


class PhoneKeepError(Exception):
    """An error with a message that is safe to show to the user.
    `details` keeps the technical text for "Show details"; `button`/`action` come from errors.py."""

    def __init__(self, message: str, details: str = "", button: str = "", action: str = "", key: str = ""):
        super().__init__(message)
        self.details, self.button, self.action, self.key = details, button, action, key

    @classmethod
    def from_problem(cls, output: str, where=None, needed_bytes=None) -> "PhoneKeepError":
        import errors
        pr = errors.explain(output, where, needed_bytes)
        return cls(pr.message, pr.details, pr.button, pr.action, pr.key)


class PasswordRequired(PhoneKeepError):
    pass


# ---------------------------------------------------------------------------
# Device + backup (pymobiledevice3)
# ---------------------------------------------------------------------------

def _helper() -> list[str]:
    """Command that runs pymobiledevice3: plain Python, or the bundled helper in the packaged app."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        cli = exe.with_name("phonekeep-cli.exe" if os.name == "nt" else "phonekeep-cli")
        return [str(cli if cli.exists() else exe), "-m", "pymobiledevice3"]
    return [sys.executable, "-m", "pymobiledevice3"]


# no console window flashing up on Windows
_NOWIN = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}


def _explain(output: str) -> str:
    """Turn helper output into the one-sentence message from the errors table (E3)."""
    import errors
    return errors.explain(output).message


def _tail_error(output: str) -> str:
    """The most telling line of helper output, for "Show details"."""
    lines = [l for l in output.strip().splitlines() if l.strip()]
    err = next((l for l in reversed(lines) if " ERROR " in l or "Error" in l), lines[-1] if lines else "")
    return re.sub(r"^\S+ \S+ \S+ \S+\[\d+\] ERROR ", "", err)


def _pmd3(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [*_helper(), *args]
    env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          encoding="utf-8", errors="replace", **_NOWIN)


def check_pmd3() -> None:
    try:
        import pymobiledevice3  # noqa: F401
    except ImportError:
        raise PhoneKeepError(
            "pymobiledevice3 is not installed. Run: pip install -r requirements.txt")


def list_devices() -> list[dict]:
    """Return connected iPhones/iPads as dicts (DeviceName, ProductVersion, UniqueDeviceID...)."""
    check_pmd3()
    r = _pmd3(["usbmux", "list"])
    if r.returncode != 0:
        raise PhoneKeepError.from_problem(r.stdout + r.stderr)
    out = r.stdout.strip()
    start = out.find("[")
    try:
        data = json.loads(out[start:]) if start >= 0 else []
    except json.JSONDecodeError:
        return []
    # usbmux can list the same phone over USB and Wi-Fi; prefer USB, dedupe by UDID
    seen, devices = set(), []
    for d in sorted(data, key=lambda d: d.get("ConnectionType") != "USB"):
        udid = d.get("UniqueDeviceID") or d.get("Identifier")
        if udid and udid not in seen:
            seen.add(udid)
            devices.append(d)
    return devices


def _launcher_cmd() -> list[str]:
    """Command that runs launcher.py's internal modes (--pk-backup, --pk-encryption)."""
    if getattr(sys, "frozen", False):
        return _helper()[:1]
    return [sys.executable, str(Path(__file__).resolve().with_name("launcher.py"))]


def _human_bytes(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit in ("bytes", "KB") else f"{n:,.1f} {unit}"
        n /= 1024
    return ""


def _folder_bytes(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _bytes_written_since(folder: Path, since: float) -> int:
    """Bytes in files written to `folder` since `since` (a time.time()). An update backup rewrites
    files that are already there, so the folder hardly grows while gigabytes arrive (13 Nov: the
    window said "getting ready" all through a backup); new and rewritten files both count here."""
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                st = os.stat(os.path.join(root, f))
            except OSError:
                continue
            if st.st_mtime >= since:
                total += st.st_size
    return total


_backup_proc: dict = {"proc": None, "cancelled": False}


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _wait_for_other_phone(backup_root: Path, udid: str, say: Callable[[str], None], poll: float = 3.0) -> None:
    """If another process is backing up a different phone, wait for it (B8: never two backups at once).
    Cancel works while waiting. The same phone is refused by its own lock (key "busy") instead."""
    marker = backup_root / "backup-running.lock"
    told = False
    while True:
        owner = _marker_owner(marker)
        if not owner:
            break
        try:
            _pid, other_udid, other_name = (marker.read_text(encoding="utf-8").split("\n") + ["", ""])[:3]
        except OSError:
            break
        if other_udid == udid:
            break                                 # the phone's own lock gives the "already running" message
        if not told:
            say(f"Waiting for the backup of '{other_name or 'another iPhone'}' to finish; this one starts right after.")
            told = True
        _backup_proc["waiting"] = True
        try:
            if _backup_proc.get("cancelled"):
                _backup_proc["cancelled"] = False
                raise BackupCancelled()
            time.sleep(poll)
        finally:
            _backup_proc["waiting"] = False


def _marker_owner(marker: Path) -> Optional[int]:
    """The pid of a live process that holds this backup marker, else None (a stale marker is ignored)."""
    try:
        pid = int(marker.read_text(encoding="utf-8").strip().split("\n")[0])     # first line: the pid
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and _pid_alive(pid) else None


class BackupCancelled(PhoneKeepError):
    """The owner pressed Cancel. Not a failure: the half-copied backup is finished next time."""

    def __init__(self):
        super().__init__("Backup cancelled. Back up again whenever you like; it carries on from here.",
                         button="Back up now", action="try_again", key="cancelled")


def cancel_backup() -> bool:
    """Stop the running backup (from any thread). True if one was running (or waiting for another phone's)."""
    if _backup_proc.get("waiting"):
        _backup_proc["cancelled"] = True
        return True
    proc = _backup_proc["proc"]
    if proc is None or proc.poll() is not None:
        return False
    _backup_proc["cancelled"] = True
    try:
        proc.terminate()
    except OSError:
        pass
    return True


def backup_running() -> bool:
    proc = _backup_proc["proc"]
    return proc is not None and proc.poll() is None


def _stream_backup(cmd: list[str], log: Log, progress, seen: dict) -> tuple[int, list[str]]:
    """Run a backup helper, forwarding progress. Returns (exit code, last output lines)."""
    env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env, bufsize=1, **_NOWIN)
    _backup_proc["proc"], _backup_proc["cancelled"] = proc, False
    last_pct, tail = -1, []
    assert proc.stdout is not None
    for raw in proc.stdout:  # universal newlines also split \r progress updates
        line = raw.strip()
        if not line:
            continue
        pct = None
        if line.startswith("PKPCT "):
            try:
                pct = float(line.split()[1])
            except (IndexError, ValueError):
                continue
        elif line.startswith("PKSTAGE"):
            seen["connected"] = True
            continue
        elif line.startswith("PKPASSCODE"):
            shown = line.split()[-1] == "shown"
            if shown != bool(seen.get("passcode")):
                seen["passcode"] = shown
                if seen.get("attention"):
                    seen["attention"](PASSCODE_PROMPT if shown else None)
            if shown:
                log("Enter your passcode on the iPhone to continue.")
            continue
        elif line.startswith("PKAPI"):
            tail.append(line)
            continue
        else:
            m = re.search(r"(\d{1,3}(?:\.\d+)?)%", line)
            if m and "backup" in line.lower():
                pct = float(m.group(1))
        if pct is not None:
            pct = max(0.0, min(100.0, pct))
            seen["pct"] = pct
            if pct >= 0.5 and seen.get("passcode"):
                seen["passcode"] = False
                if seen.get("attention"):
                    seen["attention"](None)
            if progress:
                progress(pct)
            if int(pct) // 5 != last_pct // 5:
                last_pct = int(pct)
                log(f"  backup progress: {int(pct)}%")
            continue
        if line.startswith("PKERR "):
            line = line[6:]
        if "passcode" in line.lower() and "enter" in line.lower():
            line = "Enter your passcode on the iPhone to continue."      # the phone's own prompt, in our words
            if not seen.get("passcode") and (seen.get("pct") or 0) < 0.5:
                seen["passcode"] = True
                if seen.get("attention"):
                    seen["attention"](PASSCODE_PROMPT)
        tail.append(line)
        tail = tail[-15:]
        if "--udid" in line and "no such option" in line.lower():
            break
        log("  " + line)
    return proc.wait(), tail


def make_backup(backup_root: Path = DEFAULT_BACKUP_DIR, udid: Optional[str] = None,
                log: Log = _print, progress: Optional[Callable[[float], None]] = None,
                status: Optional[Callable[[str], None]] = None,
                keep: int = 10, until_disk_full: bool = False,
                attention: Optional[Callable[[Optional[str]], None]] = None) -> Path:
    """Back up the connected iPhone into backup_root/<UDID>/current, incremental after the first run,
    then record it as a snapshot (B3) and tidy old ones. Returns the folder to open (the new snapshot).
    progress(percent) follows the iPhone's own estimate; status(text) gets a plain-language line
    every few seconds (what is happening, how much has been copied). attention(text) is called when the
    iPhone is waiting for its passcode (show it big: 13 Nov, one log line was easy to miss), and
    attention(None) once copying has started."""
    import snapshots as _snaps
    check_pmd3()
    devices = list_devices()
    if not devices:
        raise PhoneKeepError(
            "No iPhone found. Plug it in with a cable, unlock it and tap 'Trust This Computer'.")
    if udid is None:
        if len(devices) > 1:
            log("More than one device connected; using the first one.")
        udid = devices[0].get("UniqueDeviceID") or devices[0].get("Identifier")
    name = next((d.get("DeviceName") for d in devices
                 if (d.get("UniqueDeviceID") or d.get("Identifier")) == udid), udid)

    import location as _loc
    backup_root = Path(backup_root)
    if not _loc.is_available(backup_root):
        # the drive is unplugged: not an error, just waiting (B4)
        raise PhoneKeepError(_loc.connect_message(backup_root), button="Try again", action="try_again", key="drive_unavailable")
    backup_root.mkdir(parents=True, exist_ok=True)
    try:
        _snaps.check_filesystem(backup_root)
        _snaps.check_format(_snaps.phone_dir(backup_root, udid))
    except _snaps.FileSystemRefused as e:
        raise PhoneKeepError(str(e), button="Change location", action="change_location", key="fat32")
    except _snaps.FormatTooNew as e:
        raise PhoneKeepError(str(e), button="Show details", action="show_details", key="format")
    if _snaps.is_old_layout(_snaps.phone_dir(backup_root, udid)):
        if status:
            status("Converting your existing backup into its first snapshot…")
        _snaps.upgrade(backup_root, udid, log)
    live = _snaps.live_root(backup_root, udid)          # pymobiledevice3 appends the UDID itself
    live.mkdir(parents=True, exist_ok=True)
    target = _snaps.current_dir(backup_root, udid)
    existing = (target / "Manifest.db").exists()
    warning = _loc.space_warning(backup_root, _loc.estimate_needed(target if existing else None,
                                                                    None if existing else phone_used_bytes(udid)))
    if warning:
        raise PhoneKeepError(warning, button="Change location", action="change_location", key="disk_full")

    # B8: one backup at a time across all phones and processes (the window and the menu bar helper); a backup of
    # another phone waits for it and says so
    _wait_for_other_phone(backup_root, udid, status or log)

    # one backup of a phone at a time, across processes (the window and the menu bar helper)
    marker = _snaps.phone_dir(backup_root, udid) / "backup.lock"
    other = _marker_owner(marker)
    if other:
        raise PhoneKeepError("A backup of this iPhone is already running (from the menu bar helper or another window). "
                             "Wait for it to finish, then try again.", button="Try again", action="try_again", key="busy")
    try:
        marker.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    any_marker = backup_root / "backup-running.lock"
    try:
        any_marker.write_text(f"{os.getpid()}\n{udid}\n{name}", encoding="utf-8")
    except OSError:
        pass

    log(f"Backing up '{name}' to {target}")
    log("Incremental backup (only changes since last time)." if existing
        else "First backup: this copies everything and can take a while.")
    log("Keep the phone unlocked and awake. If it asks for your passcode, enter it on the phone.")

    # a small watcher that reports how much has been copied, so there is always a sign of life
    seen: dict = {"pct": None, "connected": False, "passcode": False, "attention": attention}

    def copying_started():
        if seen["passcode"]:
            seen["passcode"] = False
            if attention:
                attention(None)
    stop = threading.Event()
    t_start = time.time()

    def watch():
        while not stop.wait(4):
            if not status and not attention:
                continue
            status_ = status or (lambda _t: None)
            try:
                copied = _bytes_written_since(target, t_start - 2) if target.exists() else 0
            except Exception:
                continue
            mins = int((time.time() - t_start) // 60)
            took = f" · {mins} min so far" if mins else ""
            if seen["pct"] is None or seen["pct"] < 0.5:
                # Info.plist (with app icons) alone is ~20 MB and lands before the phone has even
                # built its snapshot; only real file data means copying has started
                if copied < 50_000_000:
                    status_("Your iPhone is getting the backup ready. This can take a few minutes "
                           "before copying starts. Keep it unlocked." + took)
                else:
                    copying_started()
                    status_(f"{_human_bytes(copied)} copied from the iPhone{took}")
            else:
                copying_started()
                status_(f"{_human_bytes(copied)} copied from the iPhone{took}")

    threading.Thread(target=watch, daemon=True).start()
    try:
        cmd = [*_launcher_cmd(), "--pk-backup", str(live), "--udid", udid]
        if not existing:
            cmd.append("--full")
        code, tail = _stream_backup(cmd, log, progress, seen)
        if code == 3:  # helper without the in-process API: use the pymobiledevice3 command
            args = ["backup2", "backup"] + (["--full"] if not existing else []) + ["--udid", udid, str(live)]
            code, tail = _stream_backup([*_helper(), *args], log, progress, seen)
            if code != 0 and any("no such option" in l.lower() and "udid" in l.lower() for l in tail):
                args = [a for a in args if a not in ("--udid", udid)]
                log("Retrying without --udid ...")
                code, tail = _stream_backup([*_helper(), *args], log, progress, seen)
    finally:
        stop.set()
        copying_started()            # whatever happened, the passcode notice goes away
        _backup_proc["proc"] = None
        try:
            marker.unlink()
        except OSError:
            pass
        try:
            if _marker_owner(any_marker) is None and any_marker.exists() and \
                    any_marker.read_text(encoding="utf-8").split("\n")[0].strip() == str(os.getpid()):
                any_marker.unlink()
        except OSError:
            pass

    if _backup_proc["cancelled"]:
        log("Backup cancelled by the owner. The next backup carries on from here.")
        raise BackupCancelled()
    if code != 0 or not (target / "Manifest.db").exists():
        raise PhoneKeepError.from_problem("\n".join(tail), where=backup_root)
    took = int(time.time() - t_start)
    log(f"Backup complete in {took // 60} min {took % 60} s.")
    if status:
        status("Saving this backup as a snapshot…")
    snap = _snaps.make_snapshot(backup_root, udid, log=log)
    _snaps.prune(backup_root, udid, keep=keep, until_disk_full=until_disk_full, log=log)
    try:                       # H1: the check-up's record (storage, battery) for "As of last backup" and history
        import checkup
        checkup.record(_snaps.phone_dir(backup_root, udid), device_overview(udid, apps=False))
    except Exception as e:     # never fails a backup that's already made
        log(f"The check-up couldn't be recorded: {type(e).__name__}: {e}")
    if progress:
        progress(100.0)
    return snap.path


def set_backup_encryption(on: bool, password: str, udid: Optional[str] = None, log: Log = _print) -> None:
    """Turn the iPhone's local-backup encryption on (new password) or off (current password).
    The password is passed through a pipe, never as a command-line argument."""
    check_pmd3()
    cmd = _launcher_cmd()
    cmd += ["--pk-encryption", "on" if on else "off"] + (["--udid", udid] if udid else [])
    env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, input=password + "\n", capture_output=True, text=True, env=env,
                       encoding="utf-8", errors="replace", **_NOWIN)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise PhoneKeepError.from_problem(out)
    log(f"Backup encryption turned {'on' if on else 'off'}. "
        + ("Keep this password safe; Apple cannot recover it." if on else ""))


def backup_will_encrypt(udid: Optional[str] = None) -> Optional[bool]:
    """Does this iPhone encrypt its backups? True/False, or None if it couldn't be asked
    (no phone, locked, not trusted). Never raises: the backup flow carries on either way."""
    try:
        check_pmd3()
        cmd = _launcher_cmd() + ["--pk-will-encrypt"] + (["--udid", udid] if udid else [])
        env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8",
                           errors="replace", timeout=60, **_NOWIN)
        for line in (r.stdout or "").splitlines():
            if line.startswith("PKWILLENCRYPT "):
                return line.split()[1] == "1"
    except Exception:
        pass
    return None


def change_backup_password(old: str, new: str, udid: Optional[str] = None, log: Log = _print) -> None:
    """Change the iPhone's backup password (done by the phone itself). Both passwords travel
    through a pipe, never on the command line. Only phone_write.py may call this."""
    check_pmd3()
    cmd = _launcher_cmd() + ["--pk-change-password"] + (["--udid", udid] if udid else [])
    env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, input=old + "\n" + new + "\n", capture_output=True, text=True, env=env,
                       encoding="utf-8", errors="replace", **_NOWIN)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or "PKDONE" not in out:
        raise PhoneKeepError.from_problem(out)
    log("Backup password changed.")


def set_wifi_sync(on: bool, udid: Optional[str] = None, log: Log = _print) -> None:
    """Turn the iPhone's Wi-Fi sync on or off (writes to the phone: only phone_write.py may call this)."""
    check_pmd3()
    cmd = _launcher_cmd() + ["--pk-wifi", "on" if on else "off"] + (["--udid", udid] if udid else [])
    env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace", **_NOWIN)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or "PKDONE" not in out:
        raise PhoneKeepError.from_problem(out)
    log(f"Wi-Fi backups turned {'on' if on else 'off'} on the iPhone.")


def phone_used_bytes(udid: Optional[str] = None) -> Optional[int]:
    """How much of the iPhone's storage is in use (for the first-backup space estimate), or None."""
    try:
        check_pmd3()
        cmd = _launcher_cmd() + ["--pk-storage"] + (["--udid", udid] if udid else [])
        env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace",
                           timeout=60, **_NOWIN)
        for line in (r.stdout or "").splitlines():
            if line.startswith("PKSTORAGE "):
                kv = dict(x.split("=") for x in line.split()[1:])
                return int(kv.get("used", 0)) or None
    except Exception:
        pass
    return None


def battery_state(udid: Optional[str] = None) -> Optional[dict]:
    """{"charging": bool, "level": int} from the phone, or None if it couldn't be asked."""
    try:
        check_pmd3()
        cmd = _launcher_cmd() + ["--pk-battery"] + (["--udid", udid] if udid else [])
        env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace",
                           timeout=60, **_NOWIN)
        for line in (r.stdout or "").splitlines():
            if line.startswith("PKBATTERY "):
                kv = dict(x.split("=") for x in line.split()[1:])
                return {"charging": kv.get("charging") == "1", "level": int(kv.get("level", -1))}
    except Exception:
        pass
    return None


def device_overview(udid: Optional[str] = None, apps: bool = True):
    """V1-V3: a deviceinfo.Overview of the connected phone (read-only), or None if it couldn't be asked."""
    import deviceinfo
    try:
        check_pmd3()
        cmd = _launcher_cmd() + ["--pk-overview"] + (["--udid", udid] if udid else []) + ([] if apps else ["--no-apps"])
        env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace",
                           timeout=180, **_NOWIN)
        raw = deviceinfo.parse_output(r.stdout)
        return deviceinfo.from_raw(raw) if raw is not None else None
    except Exception:
        return None


RESET_PASSWORD_HELP = (
    "If you don't know the backup password, your iPhone can remove it without losing anything:\n\n"
    "1. On the iPhone open Settings → General → Transfer or Reset iPhone → Reset.\n"
    "2. Tap Reset All Settings and enter your passcode.\n"
    "   (This keeps your photos, messages and apps. It only resets settings such as wallpaper,\n"
    "   Wi-Fi passwords and the backup password.)\n"
    "3. Come back to PhoneKeep and choose a new backup password."
)


RELEASES_PAGE = "https://github.com/aminyoutb007-hash/PhoneKeep/releases/latest"
RELEASES_API = "https://api.github.com/repos/aminyoutb007-hash/PhoneKeep/releases/latest"


def check_for_updates(timeout: float = 10.0) -> dict:
    """The one opt-in internet request (S3): one HTTPS GET to the release page, no identifiers.
    Returns {"current": VERSION, "latest": "5.0.0" or None, "newer": bool, "page": url, "error": str|None}."""
    import json as _json
    import urllib.request
    import netguard
    out = {"current": VERSION, "latest": None, "newer": False, "page": RELEASES_PAGE, "error": None}
    try:
        import ssl
        try:
            import certifi                      # the packaged app has no system CA bundle (python.org builds)
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "PhoneKeep", "Accept": "application/vnd.github+json"})
        with netguard.allow("Check for updates"):
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                data = _json.loads(r.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "").lstrip("v")
        out["latest"] = tag or None
        out["newer"] = bool(tag) and _version_tuple(tag) > _version_tuple(VERSION)
    except Exception as e:
        if getattr(e, "code", None) == 404:      # no release published yet
            out["latest"] = None
        else:
            out["error"] = "Couldn't reach the release page. Check your internet connection and try again."
        out["detail"] = f"{type(e).__name__}: {e}"
    return out


def _version_tuple(v: str) -> tuple:
    parts = []
    for x in v.split("."):
        digits = "".join(ch for ch in x if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def password_for_backup(path: Path) -> Optional[str]:
    """The stored password for a backup folder, if its phone has one in the keychain."""
    try:
        import keychain
        return keychain.get_password(Path(path).name)
    except Exception:
        return None


async def _sync_photos_async(dest: Path, udid: Optional[str], log: Log,
                             progress: Optional[Callable[[float], None]]) -> int:
    import posixpath
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService

    lockdown = create_using_usbmux(serial=udid)
    if hasattr(lockdown, "__await__"):
        lockdown = await lockdown
    new = 0
    async with AfcService(lockdown) as afc:
        todo = []
        async for root, _dirs, files in afc.walk("DCIM"):
            for f in files:
                if not f.startswith("."):
                    todo.append(posixpath.join(root, f))
        log(f"{len(todo):,} photo/video files on the iPhone.")
        for i, src in enumerate(todo, 1):
            local = dest.joinpath(*[x for x in src.split("/") if x])
            st = await afc.stat(src)
            size = int(st.get("st_size", -1))
            if not (local.exists() and local.stat().st_size == size):
                local.parent.mkdir(parents=True, exist_ok=True)
                await afc.pull(src, str(local), progress_bar=False)
                mt = st.get("st_mtime")
                if isinstance(mt, dt.datetime):
                    os.utime(local, (mt.timestamp(), mt.timestamp()))
                new += 1
            if progress and i % 20 == 0:
                progress(100.0 * i / len(todo))
            if i % 500 == 0:
                log(f"  {i:,}/{len(todo):,} checked, {new:,} new")
    return new


def sync_photos(dest: Path | str, udid: Optional[str] = None, log: Log = _print,
                progress: Optional[Callable[[float], None]] = None) -> Path:
    """Copy the camera roll straight off the iPhone (works even when iCloud Photos is on,
    for the photos stored on the phone). Only new files are copied on later runs."""
    check_pmd3()
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    log(f"Copying photos & videos directly from the iPhone to {dest} ...")
    try:
        import asyncio
        new = asyncio.run(_sync_photos_async(dest, udid, log, progress))
        log(f"Photos: {new:,} new files copied.")
    except PhoneKeepError:
        raise
    except Exception as e:
        log(f"Fast photo copy not available ({type(e).__name__}: {e}); using the simple copy...")
        args = ["afc", "pull", "--ignore-errors", "DCIM", str(dest)]
        if udid:
            args += ["--udid", udid]
        r = _pmd3(args)
        if r.returncode != 0:
            raise PhoneKeepError.from_problem(r.stdout + r.stderr)
        log("Photos copied.")
    if progress:
        progress(100.0)
    return dest


# ---------------------------------------------------------------------------
# Finding backups on this computer
# ---------------------------------------------------------------------------

def backup_search_roots() -> list[Path]:
    roots = [DEFAULT_BACKUP_DIR]
    home = Path.home()
    if sys.platform == "darwin":
        roots.append(home / "Library/Application Support/MobileSync/Backup")
    elif os.name == "nt":
        if os.environ.get("APPDATA"):
            roots.append(Path(os.environ["APPDATA"]) / "Apple Computer/MobileSync/Backup")
        roots.append(home / "Apple/MobileSync/Backup")  # Microsoft Store iTunes / Apple Devices
    return roots


def backup_incomplete(path: Path) -> bool:
    """A backup folder the phone started but never finished: blob folders or a Snapshot folder, no Manifest.db."""
    p = Path(path)
    if (p / "Manifest.db").exists():
        return False
    try:
        return (p / "Snapshot").is_dir() or any(c.is_dir() and len(c.name) == 2 for c in p.iterdir())
    except OSError:
        return False


def backup_info(path: Path) -> dict:
    info = {"path": str(path), "name": path.name, "date": None, "ios": None, "encrypted": False}
    try:
        with open(path / "Info.plist", "rb") as f:
            p = plistlib.load(f)
        info["name"] = p.get("Device Name") or p.get("Display Name") or path.name
        d = p.get("Last Backup Date")
        info["date"] = d.strftime("%Y-%m-%d %H:%M") if isinstance(d, dt.datetime) else None
        info["ios"] = p.get("Product Version")
    except Exception:
        pass
    try:
        with open(path / "Manifest.plist", "rb") as f:
            info["encrypted"] = bool(plistlib.load(f).get("IsEncrypted", False))
    except Exception:
        pass
    if not info["date"]:
        try:
            info["date"] = dt.datetime.fromtimestamp(
                (path / "Manifest.db").stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            pass
    return info


def find_backups(log: Log = _print) -> list[dict]:
    found = []
    for root in backup_search_roots():
        try:
            if not root.is_dir():
                continue
            for d in root.iterdir():
                if not d.is_dir():
                    continue
                if (d / "Manifest.db").exists():
                    found.append(backup_info(d))
                elif (d / "format.json").exists() or (d / "snapshots").is_dir():
                    import snapshots as _snaps
                    for s_ in _snaps.list_snapshots(root, d.name)[:1]:      # the latest snapshot of this phone
                        found.append(backup_info(s_.path))
        except PermissionError:
            if sys.platform == "darwin":
                who = "PhoneKeep" if getattr(sys, "frozen", False) else "your Terminal (or Python)"
                log(f"Skipped older Finder backups in {root} (no permission). That's fine: PhoneKeep "
                    f"makes its own backups. To include Finder backups, give {who} 'Full Disk Access' "
                    "in System Settings > Privacy & Security.")
            else:
                log(f"No permission to read {root}.")
    found.sort(key=lambda b: b["date"] or "", reverse=True)
    return found


# ---------------------------------------------------------------------------
# Reading files out of a backup (plain or encrypted)
# ---------------------------------------------------------------------------

def safe_join(base: Path, rel: str) -> Optional[Path]:
    """base/rel, or None when rel would land outside base (absolute path, '..', drive letter).
    Paths come from the backup's own database, so a tampered backup must not be able to
    write files anywhere else on the computer."""
    parts = [p for p in re.split(r"[\\/]+", rel or "") if p not in ("", ".")]
    if not parts or any(p == ".." or ":" in p or "\0" in p for p in parts):
        return None
    return Path(base).joinpath(*parts)


def _share_manifest(enc, manifest: Path) -> None:
    """Point the decryptor at our decrypted Manifest (in the private folder) instead of its own copy.
    Its copy sat in a folder of its own that only its __del__ removed, so every PhoneKeep that quit left one
    behind (14 Nov: 54 of them). And its connection could only be used from the thread that unlocked the backup,
    so a preview from the window failed with "Error querying Manifest database!". Callers hold the data lock."""
    try:
        own = enc._temporary_folder
        if enc._temp_manifest_db_conn is not None:
            enc._temp_manifest_db_conn.close()
        enc._temp_manifest_db_conn = sqlite3.connect(str(manifest), check_same_thread=False)
        enc._temp_decrypted_manifest_db_path = str(manifest)
        enc._temporary_folder = None              # ours is removed with the reader's private folder
        if own:
            shutil.rmtree(own, ignore_errors=True)
    except AttributeError:
        pass                                      # a newer decryptor: keep its own copy


class BackupReader:
    def __init__(self, path: Path | str, password: Optional[str] = None, log: Log = _print):
        self.path = Path(path)
        if not (self.path / "Manifest.db").exists():
            raise PhoneKeepError(f"{self.path} is not an iPhone backup (no Manifest.db).")
        self.log = log
        self.encrypted = backup_info(self.path)["encrypted"]
        import snapshots as _snaps
        self._snapshot = _snaps.is_snapshot(self.path)      # blobs live in the content store (B3)
        if self._snapshot:
            _snaps.install_decrypt_hook()
        import quicklook
        # decrypted databases: in the private folder, so they never outlive PhoneKeep (14 Nov: 23 were left behind)
        self._tmp = tempfile.TemporaryDirectory(prefix="phonekeep_", dir=quicklook.private_dir(),
                                                ignore_cleanup_errors=True)
        self._enc = None
        if self.encrypted:
            if not password:
                raise PasswordRequired("This backup is encrypted. Enter the backup password.")
            try:
                from iphone_backup_decrypt import EncryptedBackup
            except ImportError:
                raise PhoneKeepError(
                    "This backup is encrypted. Install the decryptor: pip install iphone_backup_decrypt")
            log("Unlocking encrypted backup (this takes up to a minute)...")
            manifest = Path(self._tmp.name) / "Manifest.db"
            try:
                self._enc = EncryptedBackup(backup_directory=str(self.path), passphrase=password)
                self._enc.save_manifest_file(str(manifest))
            except Exception as e:
                raise PhoneKeepError.from_problem(f"Could not unlock the backup: {type(e).__name__}: {e}")
            _share_manifest(self._enc, manifest)
            self.manifest = manifest
        else:
            self.manifest = self.path / "Manifest.db"
        # the pickers read previews from the window's thread while the worker waits
        self.db = sqlite3.connect(self.manifest.resolve().as_uri() + "?mode=ro", uri=True,
                                  check_same_thread=False)

    def close(self) -> None:
        try:
            self.db.close()
        finally:
            self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def has_file(self, domain: str, rel: str) -> bool:
        return self.db.execute("SELECT 1 FROM Files WHERE domain=? AND relativePath=? LIMIT 1",
                               (domain, rel)).fetchone() is not None

    def list_files(self, domain: str, prefix: str = "") -> dict[str, str]:
        """relativePath -> fileID for regular files under prefix."""
        rows = self.db.execute(
            "SELECT relativePath, fileID FROM Files WHERE domain=? AND flags=1 AND relativePath LIKE ?",
            (domain, prefix.replace("%", r"\%") + "%"))
        return {r[0]: r[1] for r in rows}

    def file_mtime(self, file_id: str) -> Optional[float]:
        """Original modification time stored in the manifest (unix seconds)."""
        row = self.db.execute("SELECT file FROM Files WHERE fileID=?", (file_id,)).fetchone()
        if not row or not row[0]:
            return None
        try:
            objs = plistlib.loads(row[0]).get("$objects", [])
            for o in objs:
                if isinstance(o, dict) and "LastModified" in o:
                    return float(o["LastModified"])
        except Exception:
            pass
        return None

    def file_meta(self, domain: str, prefix: str = "") -> dict[str, tuple]:
        """relativePath -> (fileID, mtime, size) for regular files under prefix, in one query."""
        out = {}
        for rel, fid, blob in self.db.execute(
                "SELECT relativePath, fileID, file FROM Files WHERE domain=? AND flags=1 AND relativePath LIKE ?",
                (domain, prefix.replace("%", r"\%") + "%")):
            mtime = size = None
            if blob:
                try:
                    for o in plistlib.loads(blob).get("$objects", []):
                        if isinstance(o, dict) and "LastModified" in o:
                            mtime, size = float(o["LastModified"]), int(o.get("Size") or 0)
                            break
                except Exception:
                    pass
            out[rel] = (fid, mtime, size)
        return out

    def domains(self, like: str = "%") -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT domain FROM Files WHERE domain LIKE ?", (like,))]

    def read_bytes(self, domain: str, rel: str, file_id: str) -> Optional[bytes]:
        """One backup file's content in memory (Q1 previews): nothing decrypted touches the disk."""
        if not re.fullmatch(r"[0-9a-fA-F]{40}", file_id or ""):
            return None
        if self._enc is not None:
            try:
                return self._enc.extract_file_as_bytes(rel, domain_like=domain)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            # fall back to decrypting it the way Save does, into the private preview folder, and remove it at once
            import quicklook
            tmp = quicklook.private_dir() / f"read-{file_id[:16]}"
            try:
                if self.extract(domain, rel, file_id, tmp):
                    return tmp.read_bytes()
            finally:
                tmp.unlink(missing_ok=True)
            return None
        if self._snapshot:
            import snapshots as _snaps
            src = _snaps.resolve(self.path, file_id)
            return src.read_bytes() if src is not None and src.exists() else None
        for src in (self.path / file_id[:2] / file_id, self.path / file_id):
            if src.exists():
                return src.read_bytes()
        return None

    def extract(self, domain: str, rel: str, file_id: str, dest: Path) -> bool:
        if ".." in Path(dest).parts or not re.fullmatch(r"[0-9a-fA-F]{40}", file_id or ""):
            return False  # refuse anything that could step outside the target folder
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self._enc is not None:
            try:
                self._enc.extract_file(relative_path=rel, domain_like=domain,
                                       output_filename=str(dest))
                return dest.exists()
            except Exception:
                return False
        if self._snapshot:
            import snapshots as _snaps
            src = _snaps.resolve(self.path, file_id)
            if src is not None and src.exists():
                shutil.copyfile(src, dest)
                return True
            return False
        for src in (self.path / file_id[:2] / file_id, self.path / file_id):
            if src.exists():
                shutil.copyfile(src, dest)
                return True
        return False


# ---------------------------------------------------------------------------
# WhatsApp database parsing
# ---------------------------------------------------------------------------

MSG_TYPES = {
    0: "text", 1: "image", 2: "video", 3: "audio", 4: "contact", 5: "location",
    6: "system", 7: "link", 8: "document", 11: "gif", 14: "deleted", 15: "sticker",
}

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VID_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".webm"}
AUD_EXT = {".opus", ".m4a", ".mp3", ".aac", ".ogg", ".wav", ".amr", ".caf"}


def apple_time(v) -> Optional[dt.datetime]:
    if v is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(v) + APPLE_EPOCH)
    except (OverflowError, OSError, ValueError):
        return None


def jid_label(jid: Optional[str]) -> str:
    if not jid:
        return "Unknown"
    user, _, server = jid.partition("@")
    if server == "s.whatsapp.net" and user.isdigit():
        return "+" + user
    return user


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _select(con, table, wanted: list[str], extra: str = "") -> list[sqlite3.Row]:
    have = _cols(con, table)
    parts = [c if c in have else f"NULL AS {c}" for c in wanted]
    return con.execute(f"SELECT {', '.join(parts)} FROM {table} {extra}").fetchall()


def parse_whatsapp(db_path: Path, log: Log = _print,
                   name_for: Optional[Callable[[str], Optional[str]]] = None) -> list[dict]:
    """Return a list of chats, each with its messages, from ChatStorage.sqlite (a temp copy)."""
    name_for = name_for or (lambda _x: None)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    tables = _tables(con)
    for t in ("ZWACHATSESSION", "ZWAMESSAGE"):
        if t not in tables:
            raise PhoneKeepError(f"Unexpected WhatsApp database format (missing {t}).")

    sessions = _select(con, "ZWACHATSESSION",
                       ["Z_PK", "ZCONTACTJID", "ZPARTNERNAME", "ZSESSIONTYPE", "ZARCHIVED"])
    names: dict[str, str] = {}
    for s in sessions:
        if s["ZCONTACTJID"] and s["ZPARTNERNAME"]:
            names[s["ZCONTACTJID"]] = s["ZPARTNERNAME"]

    push: dict[str, str] = {}
    if "ZWAPROFILEPUSHNAME" in tables:
        for r in _select(con, "ZWAPROFILEPUSHNAME", ["ZJID", "ZPUSHNAME"]):
            if r["ZJID"] and r["ZPUSHNAME"]:
                push[r["ZJID"]] = r["ZPUSHNAME"]

    members: dict[int, str] = {}
    if "ZWAGROUPMEMBER" in tables:
        for r in _select(con, "ZWAGROUPMEMBER", ["Z_PK", "ZMEMBERJID", "ZCONTACTNAME", "ZFIRSTNAME"]):
            jid = r["ZMEMBERJID"]
            members[r["Z_PK"]] = (names.get(jid) or r["ZCONTACTNAME"] or r["ZFIRSTNAME"]
                                  or name_for(jid_label(jid))
                                  or (("~" + push[jid]) if jid in push else None) or jid_label(jid))

    media: dict[int, sqlite3.Row] = {}
    if "ZWAMEDIAITEM" in tables:
        for r in _select(con, "ZWAMEDIAITEM", ["Z_PK", "ZMEDIALOCALPATH", "ZTITLE", "ZLATITUDE",
                                               "ZLONGITUDE", "ZVCARDNAME", "ZFILESIZE"]):
            media[r["Z_PK"]] = r

    chats: dict[int, dict] = {}
    for s in sessions:
        jid = s["ZCONTACTJID"] or ""
        if jid == "status@broadcast":
            continue
        is_group = s["ZSESSIONTYPE"] == 1 or jid.endswith("@g.us")
        chats[s["Z_PK"]] = {
            "id": s["Z_PK"], "jid": jid,
            "name": s["ZPARTNERNAME"] or name_for(jid_label(jid)) or push.get(jid) or jid_label(jid),
            "group": bool(is_group), "archived": bool(s["ZARCHIVED"]), "messages": [],
        }

    rows = _select(con, "ZWAMESSAGE",
                   ["Z_PK", "ZCHATSESSION", "ZISFROMME", "ZMESSAGEDATE", "ZTEXT", "ZMESSAGETYPE",
                    "ZGROUPMEMBER", "ZMEDIAITEM", "ZFROMJID", "ZSTARRED"],
                   "ORDER BY ZMESSAGEDATE, Z_PK")
    for r in rows:
        chat = chats.get(r["ZCHATSESSION"])
        if chat is None:
            continue
        when = apple_time(r["ZMESSAGEDATE"])
        mtype = MSG_TYPES.get(r["ZMESSAGETYPE"], "other")
        if r["ZISFROMME"]:
            sender = "You"
        elif chat["group"]:
            sender = (members.get(r["ZGROUPMEMBER"]) if r["ZGROUPMEMBER"] else None) \
                or names.get(r["ZFROMJID"] or "") or name_for(jid_label(r["ZFROMJID"])) \
                or jid_label(r["ZFROMJID"])
        else:
            sender = chat["name"]
        msg = {
            "id": r["Z_PK"], "time": when.isoformat(timespec="seconds") if when else None,
            "from_me": bool(r["ZISFROMME"]), "sender": sender, "type": mtype,
            "text": r["ZTEXT"] or "", "starred": bool(r["ZSTARRED"]),
        }
        m = media.get(r["ZMEDIAITEM"]) if r["ZMEDIAITEM"] else None
        if m is not None:
            if m["ZMEDIALOCALPATH"]:
                msg["media_src"] = m["ZMEDIALOCALPATH"]
            if m["ZTITLE"]:
                msg["caption"] = m["ZTITLE"]
            if mtype == "location" and m["ZLATITUDE"] is not None and m["ZLONGITUDE"] is not None:
                msg["location"] = [m["ZLATITUDE"], m["ZLONGITUDE"]]
            if mtype == "contact" and m["ZVCARDNAME"]:
                msg["contact"] = m["ZVCARDNAME"]
        chat["messages"].append(msg)
    con.close()

    result = [c for c in chats.values() if c["messages"]]
    result.sort(key=lambda c: c["messages"][-1]["time"] or "", reverse=True)
    log(f"Found {len(result)} chats with {sum(len(c['messages']) for c in result):,} messages.")
    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^\w\-]+", "-", s, flags=re.UNICODE).strip("-")
    return (s[:n] or "chat").lower()


def _media_candidates(src: str) -> list[str]:
    s = src.lstrip("/")
    c = [s, "Message/" + s]
    if s.startswith("Message/"):
        c.append(s[len("Message/"):])
    return c


def _extract_wa_db(reader: "BackupReader", domain: str, log: Log = _print) -> tuple[Path, dict]:
    """Copy one WhatsApp app's ChatStorage.sqlite (+ journal files) out of the backup, once."""
    files = reader.list_files(domain)
    work = Path(reader._tmp.name) / ("wa-business" if domain == WA_BUSINESS_DOMAIN else "whatsapp")
    work.mkdir(exist_ok=True)
    db_local = work / WA_DB
    if not db_local.exists():
        log("Extracting WhatsApp" + (" Business" if domain == WA_BUSINESS_DOMAIN else "") + " database...")
        if WA_DB not in files or not reader.extract(domain, WA_DB, files[WA_DB], db_local):
            raise PhoneKeepError("Could not extract ChatStorage.sqlite from the backup.")
        for extra in (WA_DB + "-wal", WA_DB + "-shm"):
            if extra in files:
                reader.extract(domain, extra, files[extra], work / extra)
    return db_local, files


def list_whatsapp_chats(reader: "BackupReader", business: bool = False, name_for=None,
                        log: Log = _print) -> list[dict]:
    """Quick overview of the chats in one WhatsApp app: id, name, group, messages, last date.
    Returns [] when that app isn't in the backup."""
    domain = WA_BUSINESS_DOMAIN if business else WA_DOMAIN
    if not reader.has_file(domain, WA_DB):
        return []
    db_local, _ = _extract_wa_db(reader, domain, log)
    name_for = name_for or (lambda _x: None)
    con = sqlite3.connect(str(db_local))
    con.row_factory = sqlite3.Row
    stats = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT ZCHATSESSION, COUNT(*), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE GROUP BY ZCHATSESSION")}
    out = []
    for s in _select(con, "ZWACHATSESSION", ["Z_PK", "ZCONTACTJID", "ZPARTNERNAME", "ZSESSIONTYPE"]):
        jid = s["ZCONTACTJID"] or ""
        n, last = stats.get(s["Z_PK"], (0, None))
        if jid == "status@broadcast" or not n:
            continue
        when = apple_time(last)
        out.append({"id": s["Z_PK"], "name": s["ZPARTNERNAME"] or name_for(jid_label(jid)) or jid_label(jid),
                    "group": s["ZSESSIONTYPE"] == 1 or jid.endswith("@g.us"), "messages": n,
                    "last": when.strftime("%Y-%m-%d") if when else ""})
    con.close()
    out.sort(key=lambda c: c["last"], reverse=True)
    return out


def load_whatsapp(reader: "BackupReader", business: bool = False, strict: bool = False,
                  name_for=None, log: Log = _print) -> dict:
    """Read every chat of one WhatsApp app: {"domain", "files", "chats"}.
    strict=True only accepts the app asked for; otherwise falls back to the other one."""
    domain = WA_BUSINESS_DOMAIN if business else WA_DOMAIN
    if strict and not reader.has_file(domain, WA_DB):
        raise PhoneKeepError(
            ("No WhatsApp Business" if business else "No WhatsApp") + " data in this backup. If "
            "the app's end-to-end encrypted chat backup is on, iOS may leave chats out of device backups.")
    if not reader.has_file(domain, WA_DB):
        other = WA_DOMAIN if business else WA_BUSINESS_DOMAIN
        if reader.has_file(other, WA_DB):
            domain = other
            log("Using WhatsApp Business data found in this backup.")
        else:
            raise PhoneKeepError(
                "No WhatsApp data in this backup. If WhatsApp's end-to-end encrypted chat "
                "backup is on, iOS may leave chats out of device backups.")
    db_local, files = _extract_wa_db(reader, domain, log)
    return {"domain": domain, "files": files, "chats": parse_whatsapp(db_local, log, name_for)}


def whatsapp_media_rel(loaded: dict, m: dict) -> Optional[str]:
    """Backup path of a message's photo/video/document, if the backup has it."""
    src = m.get("media_src")
    if not src:
        return None
    return next((p for p in _media_candidates(src) if p in loaded["files"]), None)


def parse_day(text: Optional[str]) -> Optional[dt.date]:
    """'2024-05-31' (or 31/05/2024) -> date; empty -> None."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise PhoneKeepError(f"Not a date: {text!r}. Use the form 2024-05-31.")


def filter_by_dates(chats: list[dict], dates=None) -> list[dict]:
    """Keep only messages between dates=(from, to) (dates, both inclusive, either may be None).
    Chats left with no messages are dropped. Returns new chat dicts."""
    lo, hi = (dates or (None, None))
    if not lo and not hi:
        return chats
    lo_s = lo.isoformat() if lo else "0000"
    hi_s = hi.isoformat() if hi else "9999"
    out = []
    for c in chats:
        msgs = [m for m in c["messages"] if m.get("time") and lo_s <= m["time"][:10] <= hi_s]
        if msgs:
            out.append(dict(c, messages=msgs))
    return out


def describe_dates(dates) -> str:
    lo, hi = (dates or (None, None))
    if lo and hi:
        return f"from {lo:%d %b %Y} to {hi:%d %b %Y}"
    if lo:
        return f"from {lo:%d %b %Y} onwards"
    if hi:
        return f"up to {hi:%d %b %Y}"
    return "all dates"


def export_whatsapp(reader: "BackupReader", out: Path, include_media: bool = True,
                    business: bool = False, log: Log = _print,
                    progress: Optional[Callable[[float], None]] = None,
                    binfo: Optional[dict] = None, name_for=None, hub: bool = False,
                    strict: bool = False, only_chats: Optional[set] = None,
                    formats: Optional[set] = None, loaded: Optional[dict] = None,
                    dates=None, pdf_combined: bool = False, search: str = "") -> dict:
    """Build the WhatsApp (or WhatsApp Business) archive in `out` from an open backup.
    loaded: the result of load_whatsapp(), when the chats were already read (e.g. for the picker).
    dates: (from, to) to keep only messages in that period."""
    out = Path(out)
    loaded = loaded or load_whatsapp(reader, business, strict, name_for, log)
    domain, files = loaded["domain"], loaded["files"]
    chats = [dict(c, messages=[dict(m) for m in c["messages"]]) for c in loaded["chats"]]
    if only_chats is not None:
        chats = [c for c in chats if c["id"] in only_chats]
        log(f"Exporting the {len(chats)} chat{'s' if len(chats) != 1 else ''} you selected.")
        if not chats:
            raise PhoneKeepError("No chats selected for this app.")
    import exportfilter
    flt = exportfilter.Filter(tuple(dates) if dates else None, search)
    if flt.on:
        chats = flt.chats(chats)
        log(f"Keeping messages {flt.describe()}: {sum(len(c['messages']) for c in chats):,} "
            f"messages in {len(chats)} chat{'s' if len(chats) != 1 else ''}.")
        if not chats:
            raise PhoneKeepError(f"No messages {flt.describe()} in the chats you chose.")

    media_dir = out / "media"
    copied = missing = skipped = 0
    jobs = []
    for c in chats:
        for m in c["messages"]:
            if "media_src" not in m:
                continue
            rel = whatsapp_media_rel(loaded, m)
            if rel is None:
                m["media_missing"] = True
                missing += 1
                continue
            local = rel[len("Message/"):] if rel.startswith("Message/") else rel
            dest = safe_join(media_dir, local)
            if dest is None:
                m["media_missing"] = True
                missing += 1
                continue
            m["media"] = "media/" + dest.relative_to(media_dir).as_posix()
            jobs.append((rel, files[rel], dest))

    if include_media and jobs:
        log(f"Copying {len(jobs):,} media files (already-copied files are skipped)...")
        for i, (rel, fid, dest) in enumerate(jobs, 1):
            if dest.exists() and dest.stat().st_size > 0:
                skipped += 1
            elif reader.extract(domain, rel, fid, dest):
                copied += 1
            else:
                missing += 1
            if progress and i % 25 == 0:
                progress(100.0 * i / len(jobs))
            if i % 500 == 0:
                log(f"  {i:,}/{len(jobs):,} media files")
    elif not include_media:
        for c in chats:
            for m in c["messages"]:
                m.pop("media", None)
    log(f"Media: {copied:,} new, {skipped:,} already in archive, {missing:,} not in backup.")
    title = "WhatsApp" + (" Business" if domain == WA_BUSINESS_DOMAIN else "")
    formats = set(formats or {"web"})
    main = None
    if "web" in formats:
        write_archive(chats, out, binfo or backup_info(reader.path), log, title=title, hub=hub)
        main = "index.html"
    if "excel" in formats:
        import tables
        try:
            tables.write_chats_xlsx(chats, out / f"{title} chats.xlsx", title, log)
        except RuntimeError as e:
            raise PhoneKeepError(str(e))
        main = main or f"{title} chats.xlsx"
    if "csv" in formats:
        import tables
        tables.write_chats_csv(chats, out / "CSV", log)
        main = main or "CSV/_All chats.csv"
    if "pdf" in formats:
        import chat_pdf
        pdf = chat_pdf.write_chats_pdf(chats, out, title, log, combined=pdf_combined)
        main = main or pdf.relative_to(out).as_posix()
    n = sum(len(c["messages"]) for c in chats)
    extra = [f for f, on in (("PDF", "pdf" in formats), ("Excel", "excel" in formats), ("CSV", "csv" in formats)) if on]
    return {"count": n, "main": main,
            "detail": f"{len(chats):,} chats · {n:,} messages" + (f" · {' + '.join(extra)}" if extra else "")}


def export_backup(backup_path: Path | str, out_dir: Path | str = DEFAULT_ARCHIVE_DIR,
                  password: Optional[str] = None, include_media: bool = True,
                  business: bool = False, log: Log = _print,
                  progress: Optional[Callable[[float], None]] = None) -> Path:
    """WhatsApp-only export."""
    out = Path(out_dir)
    with BackupReader(backup_path, password, log) as reader:
        export_whatsapp(reader, out, include_media, business, log, progress)
    if progress:
        progress(100.0)
    return out / "index.html"


# ---------------------------------------------------------------------------
# HTML archive
# ---------------------------------------------------------------------------

CSS = r"""
:root{--bg:#efeae2;--panel:#fff;--ink:#111b21;--muted:#667781;--me:#d9fdd3;--them:#fff;
--accent:#008069;--line:#e9edef;--sys:#ffeecd;--mark:#ffe066}
@media (prefers-color-scheme:dark){:root{--bg:#0b141a;--panel:#111b21;--ink:#e9edef;--muted:#8696a0;
--me:#005c4b;--them:#202c33;--accent:#00a884;--line:#222d34;--sys:#182229;--mark:#8a6d00}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent)}header{position:sticky;top:0;z-index:5;background:var(--accent);color:#fff;
padding:12px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0;flex:1;min-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
header a{color:#fff;text-decoration:none;font-weight:600}
header input{flex:1 1 220px;max-width:420px;padding:8px 12px;border-radius:8px;border:0;font-size:15px}
.wrap{max-width:900px;margin:0 auto;padding:12px 16px 60px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 14px}
.stat{background:var(--panel);border-radius:10px;padding:10px 14px;flex:1;min-width:120px}
.stat b{display:block;font-size:20px}.stat span{color:var(--muted);font-size:13px}
.chat{display:flex;gap:12px;align-items:center;background:var(--panel);padding:12px 14px;
border-bottom:1px solid var(--line);text-decoration:none;color:var(--ink)}
.chat:first-child{border-radius:10px 10px 0 0}.chat:last-child{border-radius:0 0 10px 10px;border:0}
.chat:hover{filter:brightness(.97)}
.av{width:42px;height:42px;border-radius:50%;flex:none;display:grid;place-items:center;
color:#fff;font-weight:700;background:var(--accent)}
.ci{flex:1;min-width:0}.ci b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ci small,.meta{color:var(--muted);font-size:12.5px}
.ci small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.day{text-align:center;margin:14px 0 8px}.day span{background:var(--panel);color:var(--muted);
font-size:12.5px;padding:4px 10px;border-radius:8px}
.m{max-width:min(78%,560px);margin:3px 0;padding:6px 9px 4px;border-radius:8px;background:var(--them);
box-shadow:0 1px .5px rgba(0,0,0,.13);word-wrap:break-word;overflow-wrap:anywhere;scroll-margin-top:80px}
.m.me{margin-left:auto;background:var(--me)}.m.sys{margin:8px auto;background:var(--sys);
text-align:center;font-size:13px;color:var(--muted)}
.m .s{font-size:13px;font-weight:600;color:var(--accent)}.m .t{white-space:pre-wrap}
.m .meta{text-align:right;margin-top:2px}.m:target{outline:3px solid var(--mark)}
.m img,.m video{display:block;max-width:100%;max-height:420px;border-radius:6px;margin:2px 0}
.m audio{width:260px;max-width:100%}.doc{display:inline-block;padding:8px 10px;background:rgba(0,0,0,.06);border-radius:6px}
.missing{color:var(--muted);font-style:italic}mark{background:var(--mark);color:inherit}
.hide{display:none!important}.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px}
.gallery a{display:block;aspect-ratio:1;overflow:hidden;border-radius:6px;background:var(--panel)}
.gallery img{width:100%;height:100%;object-fit:cover}
.res{display:block;background:var(--panel);padding:10px 14px;border-bottom:1px solid var(--line);
color:var(--ink);text-decoration:none}.res b{color:var(--accent)}
.empty{color:var(--muted);text-align:center;padding:30px}
.tabs{display:flex;gap:8px;margin-bottom:10px}.tabs button{border:0;border-radius:16px;padding:6px 12px;
background:var(--panel);color:var(--ink);cursor:pointer}.tabs button.on{background:var(--accent);color:#fff}
"""

CHAT_JS = r"""
(function(){
 var q=document.getElementById('q'),ms=[].slice.call(document.querySelectorAll('.m')),
 days=[].slice.call(document.querySelectorAll('.day')),info=document.getElementById('info');
 function esc(s){return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}
 ms.forEach(function(m){var t=m.querySelector('.t');if(t)t.dataset.raw=t.innerHTML});
 var timer;q&&q.addEventListener('input',function(){clearTimeout(timer);timer=setTimeout(run,150)});
 function run(){var v=q.value.trim(),n=0,re=v?new RegExp('('+esc(v.replace(/[<>&"]/g,''))+')','gi'):null;
  ms.forEach(function(m){var t=m.querySelector('.t'),hit=!v||m.textContent.toLowerCase().indexOf(v.toLowerCase())>=0;
   m.classList.toggle('hide',!hit);if(hit&&v)n++;
   if(t){t.innerHTML=t.dataset.raw;if(re&&hit)t.innerHTML=t.innerHTML.replace(/(^|>)([^<]+)/g,function(_,a,b){return a+b.replace(re,'<mark>$1</mark>')})}});
  days.forEach(function(d){d.classList.toggle('hide',!!v)});
  info.textContent=v?(n+' matching messages'):'';}
 var tabs=document.querySelectorAll('.tabs button'),g=document.getElementById('gallery'),c=document.getElementById('msgs');
 [].forEach.call(tabs,function(b){b.onclick=function(){[].forEach.call(tabs,function(x){x.classList.remove('on')});
  b.classList.add('on');var gal=b.dataset.v==='g';g.classList.toggle('hide',!gal);c.classList.toggle('hide',gal);
  if(q)q.parentNode.classList.toggle('hide',false)}});
})();
"""

SEARCH_JS = r"""
(function(){
 var q=document.getElementById('q'),out=document.getElementById('out'),D=window.WV;
 function esc(s){return s.replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
 function run(){var v=q.value.trim().toLowerCase();if(v.length<2){out.innerHTML='<p class="empty">Type at least 2 letters to search every chat.</p>';return}
  var res=[],i,r;for(i=0;i<D.m.length&&res.length<500;i++){r=D.m[i];if(r[3].toLowerCase().indexOf(v)>=0)res.push(r)}
  if(!res.length){out.innerHTML='<p class="empty">No messages found.</p>';return}
  var re=new RegExp('('+v.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','gi');
  out.innerHTML='<p class="meta">'+res.length+(res.length==500?'+':'')+' results</p>'+res.map(function(r){var c=D.c[r[0]];
   return '<a class="res" href="chats/'+c[1]+'#m'+r[4]+'"><b>'+esc(c[0])+'</b> <span class="meta">'+esc(r[1])+' · '+esc(r[2])+'</span><br>'+
   esc(r[3].length>300?r[3].slice(0,300)+'…':r[3]).replace(re,'<mark>$1</mark>')+'</a>'}).join('')}
 var t;q.addEventListener('input',function(){clearTimeout(t);t=setTimeout(run,200)});
 var p=new URLSearchParams(location.search).get('q');if(p){q.value=p}run();
})();
"""


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _page(title: str, body: str, depth: int, header_extra: str = "", scripts: str = "") -> str:
    up = "../" * depth
    back = f'<a href="{up}index.html">&#8592;</a>' if depth else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} · {APP_NAME}</title><link rel="stylesheet" href="{up}assets/style.css">'
            f'</head><body><header>{back}<h1>{_e(title)}</h1>{header_extra}</header>'
            f'<div class="wrap">{body}</div>{scripts}</body></html>')


def _initials(name: str) -> str:
    parts = [p for p in (re.sub(r"[^\w\s]", "", w) for w in name.split()) if p]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper() if parts else "?"


def _color(name: str) -> str:
    h = sum(ord(c) * (i + 1) for i, c in enumerate(name)) % 360
    return f"hsl({h},45%,42%)"


def _linkify(escaped: str) -> str:
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', escaped)


def _render_media(m: dict) -> str:
    if m.get("location"):
        lat, lon = m["location"]
        return (f'<a class="doc" target="_blank" rel="noopener" '
                f'href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}">'
                f'&#128205; Location {lat:.5f}, {lon:.5f}</a>')
    if m.get("contact"):
        return f'<span class="doc">&#128100; Contact: {_e(m["contact"])}</span>'
    if m.get("media"):
        src = "../" + _e(m["media"])
        ext = os.path.splitext(m["media"])[1].lower()
        if ext in IMG_EXT:
            return f'<a href="{src}" target="_blank"><img loading="lazy" src="{src}" alt=""></a>'
        if ext in VID_EXT:
            return f'<video controls preload="none" src="{src}"></video>'
        if ext in AUD_EXT:
            return f'<audio controls preload="none" src="{src}"></audio>'
        label = m.get("caption") or os.path.basename(m["media"])
        return f'<a class="doc" href="{src}" target="_blank">&#128206; {_e(label)}</a>'
    if m.get("media_src") or m.get("media_missing"):
        return f'<span class="missing">&#128206; {m["type"]} not in backup</span>'
    return ""


def _render_msg(m: dict, group: bool) -> str:
    t = dt.datetime.fromisoformat(m["time"]) if m["time"] else None
    clock = t.strftime("%H:%M") if t else ""
    if m["type"] == "system":
        txt = m["text"] or "Group update"
        return f'<div class="m sys" id="m{m["id"]}"><span class="t">{_e(txt)}</span></div>'
    cls = "m me" if m["from_me"] else "m"
    parts = []
    if group and not m["from_me"]:
        parts.append(f'<div class="s" style="color:{_color(m["sender"])}">{_e(m["sender"])}</div>')
    media_html = _render_media(m)
    if media_html:
        parts.append(media_html)
    text = m["text"]
    if m.get("caption") and m.get("caption") != text and m["type"] != "document":
        text = (text + "\n" + m["caption"]).strip() if text else m["caption"]
    if m["type"] == "deleted" and not text:
        text = "\U0001F6AB This message was deleted"
    if text:
        parts.append(f'<div class="t">{_linkify(_e(text))}</div>')
    if not parts:
        parts.append(f'<div class="t missing">[{_e(m["type"])}]</div>')
    star = "&#11088; " if m.get("starred") else ""
    parts.append(f'<div class="meta">{star}{clock}</div>')
    return f'<div class="{cls}" id="m{m["id"]}">{"".join(parts)}</div>'


def _preview(m: dict) -> str:
    if m["text"]:
        return m["text"].replace("\n", " ")[:90]
    return {"image": "Photo", "video": "Video", "audio": "Audio", "sticker": "Sticker",
            "document": "Document", "location": "Location", "contact": "Contact",
            "gif": "GIF", "system": "Group update",
            "deleted": "This message was deleted"}.get(m["type"], m["type"].capitalize())


def write_archive(chats: list[dict], out: Path, binfo: dict, log: Log = _print,
                  title: str = "WhatsApp Archive", hub: bool = False) -> None:
    log("Writing archive...")
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "chats").mkdir(exist_ok=True)
    (out / "data" / "chats").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    (out / "assets" / "chat.js").write_text(CHAT_JS, encoding="utf-8")
    (out / "assets" / "search.js").write_text(SEARCH_JS, encoding="utf-8")

    used: set[str] = set()
    for c in chats:
        base = _slug(c["name"]) or "chat"
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        c["file"] = slug + ".html"

    search_c, search_m = [], []
    csv_path = out / "data" / "all_messages.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fcsv:
        w = csv.writer(fcsv)
        w.writerow(["chat", "date", "time", "sender", "type", "text", "media_file", "starred"])
        for ci, c in enumerate(chats):
            search_c.append([c["name"], c["file"]])
            body, gallery, last_day = [], [], None
            for m in c["messages"]:
                t = dt.datetime.fromisoformat(m["time"]) if m["time"] else None
                day = t.strftime("%A %d %B %Y") if t else "Unknown date"
                if day != last_day:
                    body.append(f'<div class="day"><span>{day}</span></div>')
                    last_day = day
                body.append(_render_msg(m, c["group"]))
                if m.get("media") and os.path.splitext(m["media"])[1].lower() in IMG_EXT | VID_EXT:
                    src = "../" + _e(m["media"])
                    inner = (f'<img loading="lazy" src="{src}" alt="">'
                             if os.path.splitext(m["media"])[1].lower() in IMG_EXT
                             else '<div class="av" style="width:100%;height:100%;border-radius:0">&#9654;</div>')
                    gallery.append(f'<a href="#m{m["id"]}" onclick="document.querySelector(\'.tabs button\').click()">{inner}</a>')
                w.writerow([_csv_safe(x) for x in [c["name"], t.strftime("%Y-%m-%d") if t else "", t.strftime("%H:%M:%S") if t else "",
                            m["sender"], m["type"], m["text"] or m.get("caption", ""),
                            m.get("media", ""), "yes" if m.get("starred") else ""]])
                txt = m["text"] or m.get("caption") or ""
                if txt:
                    search_m.append([ci, t.strftime("%d %b %Y %H:%M") if t else "", m["sender"], txt, m["id"]])

            first, last = c["messages"][0]["time"], c["messages"][-1]["time"]
            sub = (f'<p class="meta">{len(c["messages"]):,} messages · {first[:10] if first else "?"} '
                   f'→ {last[:10] if last else "?"}{" · group" if c["group"] else ""}</p>')
            tabs = (f'<div class="tabs"><button class="on" data-v="m">Messages</button>'
                    f'<button data-v="g">Media ({len(gallery)})</button></div>')
            gal = (f'<div id="gallery" class="gallery hide">{"".join(gallery) or "<p class=empty>No photos or videos.</p>"}</div>')
            page = _page(c["name"], sub + tabs + gal + f'<div id="msgs">{"".join(body)}</div>', 1,
                         '<span><input id="q" type="search" placeholder="Search this chat"></span>'
                         '<small id="info"></small>',
                         '<script src="../assets/chat.js"></script>')
            (out / "chats" / c["file"]).write_text(page, encoding="utf-8")
            with open(out / "data" / "chats" / (c["file"][:-5] + ".json"), "w", encoding="utf-8") as fj:
                json.dump({k: v for k, v in c.items() if k != "file"}, fj, ensure_ascii=False, indent=1)

    with open(out / "data" / "search.js", "w", encoding="utf-8") as fs:
        fs.write("window.WV=")
        json.dump({"c": search_c, "m": search_m}, fs, ensure_ascii=False, separators=(",", ":"))
        fs.write(";")

    total = sum(len(c["messages"]) for c in chats)
    n_media = sum(1 for c in chats for m in c["messages"] if m.get("media"))
    times = [c["messages"][0]["time"] for c in chats if c["messages"][0]["time"]]
    since = min(times)[:10] if times else "?"
    stats = (f'<div class="stats"><div class="stat"><b>{len(chats):,}</b><span>chats</span></div>'
             f'<div class="stat"><b>{total:,}</b><span>messages</span></div>'
             f'<div class="stat"><b>{n_media:,}</b><span>media files</span></div>'
             f'<div class="stat"><b>{since}</b><span>oldest message</span></div></div>'
             f'<p class="meta">From backup of {_e(binfo.get("name"))} ({_e(binfo.get("date"))}) · '
             f'archive built {dt.datetime.now():%Y-%m-%d %H:%M} · '
             f'<a href="data/all_messages.csv">CSV</a></p>')
    rows = []
    for c in chats:
        lm = c["messages"][-1]
        when = lm["time"][:10] if lm["time"] else ""
        rows.append(f'<a class="chat" href="chats/{c["file"]}" data-n="{_e(c["name"].lower())}">'
                    f'<div class="av" style="background:{_color(c["name"])}">{_e(_initials(c["name"]))}</div>'
                    f'<div class="ci"><b>{_e(c["name"])}</b><small>{_e(lm["sender"] + ": ") if c["group"] and lm["type"] != "system" else ""}'
                    f'{_e(_preview(lm))}</small></div><div class="meta">{when}<br>{len(c["messages"]):,}</div></a>')
    filt = ('<script>var f=document.getElementById("f");f.oninput=function(){var v=f.value.toLowerCase();'
            '[].forEach.call(document.querySelectorAll(".chat"),function(a){a.classList.toggle("hide",'
            'a.dataset.n.indexOf(v)<0)})};</script>')
    home = '<a href="../index.html">&#8962; iPhone</a>' if hub else ""
    (out / "index.html").write_text(_page(
        title, stats + f'<div>{"".join(rows)}</div>', 0,
        '<input id="f" type="search" placeholder="Filter chats">'
        '<a href="search.html">&#128269; Search all messages</a>' + home, filt), encoding="utf-8")
    (out / "search.html").write_text(_page(
        "Search all messages", '<div id="out"></div>', 0,
        '<input id="q" type="search" placeholder="Search every chat" autofocus>'
        '<a href="index.html">Chats</a>',
        '<script src="data/search.js"></script><script src="assets/search.js"></script>'),
        encoding="utf-8")
    log(f"Archive ready: {out / 'index.html'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _pick_backup(arg: Optional[str]) -> Path:
    if arg:
        return Path(arg)
    backups = find_backups()
    if not backups:
        raise PhoneKeepError("No backups found. Run 'backup' first or pass --backup PATH.")
    if len(backups) == 1 or not sys.stdin.isatty():
        return Path(backups[0]["path"])
    for i, b in enumerate(backups, 1):
        print(f"  {i}. {b['name']}  {b['date']}  {'(encrypted)' if b['encrypted'] else ''}\n     {b['path']}")
    choice = input(f"Which backup? [1-{len(backups)}, default 1]: ").strip() or "1"
    return Path(backups[int(choice) - 1]["path"])


def _password_for(backup: Path, a) -> Optional[str]:
    """The password for an encrypted backup: from the keychain, else PHONEKEEP_PASSWORD, else asked
    at the prompt. Never from a command-line option (it would show in the process list)."""
    if not backup_info(backup)["encrypted"]:
        return None
    pw = password_for_backup(backup) or os.environ.get("PHONEKEEP_PASSWORD")
    if not pw:
        pw = getpass.getpass("Backup password: ")
    return pw


def _encryption_cli(a) -> None:
    """Writes to the phone: confirmed by typing the phone's name, then done through phone_write."""
    import keychain
    import phone_write
    devs = [d for d in list_devices() if not a.udid or (d.get("UniqueDeviceID") or d.get("Identifier")) == a.udid]
    if not devs:
        raise PhoneKeepError("No iPhone connected (plug it in, unlock it, tap Trust).")
    d = devs[0]
    udid, name = d.get("UniqueDeviceID") or d.get("Identifier"), d.get("DeviceName") or "iPhone"
    if a.mode == "on":
        what = "Turn on backup encryption"
    elif a.mode == "off":
        what = "Turn off backup encryption (unencrypted backups leave out saved passwords, Health, Wi-Fi networks and call history, and anyone with this computer can read them)"
    else:
        what = "Change the backup password"
    print(f"{what} on {name}.\nType the iPhone's name to confirm: ", end="", flush=True)
    if sys.stdin.readline().strip() != name:
        raise PhoneKeepError("Cancelled: the name didn't match. Nothing was changed.")
    if a.mode == "on":
        pw = getpass.getpass("New backup password: ")
        if not pw or pw != getpass.getpass("Repeat password: "):
            raise PhoneKeepError("Passwords don't match.")
        phone_write.turn_on_encryption(udid, name, pw, confirmed=True)
        keychain.set_password(udid, pw)
    elif a.mode == "off":
        pw = keychain.get_password(udid) or getpass.getpass("Current backup password: ")
        phone_write.turn_off_encryption(udid, name, pw, confirmed=True)
        keychain.delete_password(udid)
    else:
        old = keychain.get_password(udid) or getpass.getpass("Current backup password: ")
        new = getpass.getpass("New backup password: ")
        if not new or new != getpass.getpass("Repeat new password: "):
            raise PhoneKeepError("Passwords don't match.")
        phone_write.change_password(udid, name, old, new, confirmed=True)
        keychain.set_password(udid, new)
    print("Done." if keychain.available() else "Done. (No keychain on this computer: you'll be asked for the password when needed.)")


def _export_cli(backup: Path, a) -> None:
    import sections as sx
    pw = _password_for(backup, a)
    only = [x.strip() for x in a.only.split(",")] if a.only else None
    if only:
        bad = [x for x in only if x not in [k for k, *_ in sx.SECTIONS]]
        if bad:
            raise PhoneKeepError("Unknown section(s): " + ", ".join(bad))
    if a.all_files:
        only = (only or list(sx.DEFAULT_SECTIONS)) + ["files"]
    names = [x for x in (a.chats or "").split(",") if x.strip()] or None
    formats = {f.strip().lower() for f in (a.formats or "web").split(",") if f.strip()}
    if formats - {"web", "excel", "csv"}:
        raise PhoneKeepError("--formats takes web, excel and/or csv")
    dates = (parse_day(a.date_from), parse_day(a.date_to))
    if all(dates) and dates[0] > dates[1]:
        raise PhoneKeepError("--from is after --to")
    index = sx.export_all(backup, a.out, pw, only, include_media=not a.no_media, chat_names=names,
                          formats=formats, dates=dates if any(dates) else None)
    print(f"\nOpen this file in your browser:\n  {index}")


def main(argv=None) -> int:
    import sections as sx
    keys = ",".join(k for k, *_ in sx.SECTIONS)
    p = argparse.ArgumentParser(prog="phonekeep", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"{APP_NAME} {full_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="list connected iPhones")
    sub.add_parser("backups", help="list backups on this computer")
    sp = sub.add_parser("backup", help="back up the connected iPhone")
    sp.add_argument("--dir", default=str(DEFAULT_BACKUP_DIR), help="where backups are stored")
    run = sub.add_parser("run", help="back up the iPhone, then build the full archive")
    run.add_argument("--dir", default=str(DEFAULT_BACKUP_DIR), help="where backups are stored")
    run.add_argument("--photos", action="store_true", help="also copy photos directly off the phone")
    exp = sub.add_parser("export", help="build the full archive from a backup")
    exp.add_argument("--backup", help="path to a backup folder (default: pick one)")
    wa = sub.add_parser("whatsapp", help="build only the WhatsApp archive")
    wa.add_argument("--backup", help="path to a backup folder")
    wa.add_argument("--business", action="store_true", help="prefer WhatsApp Business")
    for x in (run, exp, wa):
        x.add_argument("--out", default=str(DEFAULT_ARCHIVE_DIR), help="archive folder")
        # No --password option on purpose: it would show in the process list. The password comes
        # from the keychain, the PHONEKEEP_PASSWORD variable, or a prompt.
        x.add_argument("--no-media", action="store_true", help="skip photos/videos/attachments")
    for x in (run, exp):
        x.add_argument("--only", help=f"comma-separated sections: {keys}")
        x.add_argument("--all-files", action="store_true", help="also export every raw file in the backup")
        x.add_argument("--chats", help='WhatsApp: export only chats whose name contains one of these, '
                                         'comma-separated, e.g. --chats "Acme,Mum"')
        x.add_argument("--formats", help="chat exports: web, excel and/or csv, comma-separated (default web)")
        x.add_argument("--from", dest="date_from", help="chats: keep messages from this date (2024-01-31)")
        x.add_argument("--to", dest="date_to", help="chats: keep messages up to this date (inclusive)")
    ph = sub.add_parser("photos", help="copy photos & videos straight off the iPhone")
    ph.add_argument("--out", default=str(DEFAULT_ARCHIVE_DIR), help="archive folder")
    enc = sub.add_parser("encryption", help="turn backup encryption on/off, or change the password")
    enc.add_argument("mode", choices=["on", "off", "change-password"])
    enc.add_argument("--udid", help="which iPhone, if several are connected")
    a = p.parse_args(argv)

    try:
        if a.cmd == "devices":
            devs = list_devices()
            if not devs:
                print("No iPhone connected (plug it in, unlock it, tap Trust).")
            for d in devs:
                print(f"{d.get('DeviceName')}  iOS {d.get('ProductVersion')}  "
                      f"{d.get('ConnectionType', '')}  {d.get('UniqueDeviceID') or d.get('Identifier')}")
        elif a.cmd == "backups":
            bs = find_backups()
            if not bs:
                print("No backups found.")
            for b in bs:
                print(f"{b['name']}  {b['date']}  iOS {b['ios']}  "
                      f"{'encrypted' if b['encrypted'] else 'not encrypted'}\n  {b['path']}")
        elif a.cmd == "backup":
            make_backup(Path(a.dir))
        elif a.cmd == "run":
            path = make_backup(Path(a.dir))
            if a.photos:
                sync_photos(Path(a.out) / "Photos" / "Originals")
            _export_cli(path, a)
        elif a.cmd == "export":
            _export_cli(_pick_backup(a.backup), a)
        elif a.cmd == "whatsapp":
            b = _pick_backup(a.backup)
            idx = export_backup(b, a.out, _password_for(b, a), not a.no_media, a.business)
            print(f"\nOpen this file in your browser:\n  {idx}")
        elif a.cmd == "photos":
            sync_photos(Path(a.out) / "Photos" / "Originals")
            print("Run 'export --only photos' to rebuild the photo gallery.")
        elif a.cmd == "encryption":
            _encryption_cli(a)
    except PhoneKeepError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
