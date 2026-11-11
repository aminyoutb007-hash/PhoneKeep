"""The menu bar / tray helper's brain (E2 in docs/spec/05-ease-of-use.md), with no UI toolkit in it.

The platform menus (helper_ui.py) call into one `Helper` object: it knows the phones, their last
backups, runs a backup in the background with a progress ring, sends notifications, and later (B2)
runs the schedule. Everything here is testable with a stub phone.

Talking to the main window: the main app listens on a loopback port (written to ~/PhoneKeep/app.port);
the helper asks it to open the phone window, or launches the app if it isn't running. Loopback only,
which the network guard allows.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import keychain
import phonekeep as wv
import scheduler as sch

HOME = wv.DEFAULT_HOME
PORT_FILE = HOME / "app.port"
LOCK_FILE = HOME / "helper.lock"
SETTINGS_FILE = HOME / "settings.json"


def settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ago(when: Optional[dt.datetime]) -> str:
    """'2 hours ago', 'just now', 'yesterday', '3 Nov'."""
    if not when:
        return "never"
    d = dt.datetime.now() - when
    s = int(d.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        m = s // 60
        return f"{m} min ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if s < 2 * 86400:
        return "yesterday"
    if s < 7 * 86400:
        return f"{s // 86400} days ago"
    return when.strftime("%-d %b" if sys.platform != "win32" else "%#d %b")


def size_text(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class Helper:
    def __init__(self, notify: Callable[[str, str], None], backup_dir: Optional[Path] = None,
                 on_change: Optional[Callable[[], None]] = None, log: Callable[[str], None] = lambda m: None):
        self.notify = notify
        self.backup_dir = Path(backup_dir or settings().get("backup_dir") or wv.DEFAULT_BACKUP_DIR)
        self.on_change = on_change or (lambda: None)
        self.log = log
        self.devices: list[dict] = []
        self.busy = False
        self.progress: Optional[float] = None       # 0-100 while a backup runs
        self.paused = bool(settings().get("auto_backup_paused", False))
        self.last_error: Optional[str] = None
        self.lock = threading.Lock()
        self._refresh_at = 0.0
        self.clock = None                             # tests set a fake clock

    # -- status -----------------------------------------------------------------------------
    def phones(self) -> list[dict]:
        """One entry per phone ever backed up or connected: name, udid, last backup, encrypted, connected."""
        seen = {}
        try:
            for p in self.backup_dir.iterdir():
                if (p / "Manifest.db").exists():
                    info = wv.backup_info(p)
                    when = None
                    try:
                        when = dt.datetime.strptime(info["date"], "%Y-%m-%d %H:%M") if info["date"] else None
                    except ValueError:
                        pass
                    try:        # the helper's own record of the last finished backup is the freshest
                        h = json.loads((p / "health.json").read_text(encoding="utf-8"))
                        ok = dt.datetime.fromisoformat(h["last_ok"])
                        when = max(when, ok) if when else ok
                    except Exception:
                        pass
                    seen[p.name] = {"udid": p.name, "name": info["name"], "last": when,
                                    "encrypted": info["encrypted"], "connected": False, "how": ""}
        except OSError:
            pass
        for d in self.devices:
            udid = d.get("UniqueDeviceID") or d.get("Identifier")
            e = seen.setdefault(udid, {"udid": udid, "name": d.get("DeviceName") or "iPhone", "last": None,
                                       "encrypted": False, "connected": False, "how": ""})
            e["connected"], e["how"] = True, ("cable" if d.get("ConnectionType") == "USB" else "Wi-Fi")
            e["name"] = d.get("DeviceName") or e["name"]
        return sorted(seen.values(), key=lambda e: (not e["connected"], e["name"]))

    def status_lines(self) -> list[str]:
        """The lines at the top of the menu, e.g. "Amin's iPhone · backed up 2 hours ago 🔒"."""
        out = []
        for p in self.phones():
            lock = " 🔒" if p["encrypted"] else ""
            line = f"{p['name']} · backed up {ago(p['last'])}{lock}" if p["last"] else f"{p['name']} · not backed up yet"
            if p["connected"]:
                line += f" · connected by {p['how']}"
            out.append(line)
            plan = sch.Plan.from_settings(settings())
            state, extra = sch.card_state(plan, sch.Health.load(self.backup_dir / (p["udid"] or "-")), self.now())
            if state == "amber":
                out.append("⚠ " + extra)
            elif plan.mode != "off":
                nxt = plan.next_run_text(self.now(), p["last"])
                if nxt:
                    out.append("   " + nxt)
        if not out:
            out.append("No iPhone backed up yet")
        if self.busy and self.progress is not None:
            out.append(f"Backing up… {self.progress:.0f}%")
        if self.last_error:
            out.append(self.last_error)
        return out

    def refresh_devices(self, force: bool = False):
        """Ask usbmux which phones are reachable; at most every few minutes unless forced (idle = cheap)."""
        if not force and time.time() - self._refresh_at < 300:
            return
        self._refresh_at = time.time()
        try:
            self.devices = wv.list_devices()
        except Exception:
            self.devices = []
        self.on_change()

    # -- backing up ---------------------------------------------------------------------------------
    def back_up_now(self, udid: Optional[str] = None) -> bool:
        """Start a backup in the background. Returns False if one is already running or no phone is reachable."""
        with self.lock:
            if self.busy:
                return False
            self.busy = True
        self.refresh_devices(force=True)
        if not self.devices:
            self.busy = False
            self.notify("iPhone not reachable", "Plug it in or put it on the same Wi-Fi, then try again.")
            return False
        d = self.devices[0] if not udid else next((x for x in self.devices if (x.get("UniqueDeviceID") or x.get("Identifier")) == udid), self.devices[0])
        udid = d.get("UniqueDeviceID") or d.get("Identifier")
        name = d.get("DeviceName") or "iPhone"
        threading.Thread(target=self._backup, args=(udid, name), daemon=True).start()
        return True

    def _backup(self, udid: str, name: str):
        self.progress, self.last_error = 0.0, None
        self.on_change()
        t0 = time.time()
        before = wv._folder_bytes(self.backup_dir / udid) if (self.backup_dir / udid).exists() else 0
        try:
            # S1: the helper never asks for a password; if the phone isn't encrypted yet, the window must do it
            on = wv.backup_will_encrypt(udid)
            if on is False:
                raise wv.PhoneKeepError("Open PhoneKeep once to choose a backup password, then backups run from here.")

            def progress(p):
                self.progress = float(p)
                self.on_change()
            wv.make_backup(self.backup_dir, udid, log=self.log, progress=progress)
            took = int(time.time() - t0)
            after = wv._folder_bytes(self.backup_dir / udid)
            mins = max(1, round(took / 60))
            self.notify("iPhone backed up",
                        f"{name} · {mins} min · {size_text(max(0, after - before))} of changes")
            self.write_health(udid, ok=True)
        except Exception as e:
            import errors
            pr = errors.explain(e) if not isinstance(e, wv.PhoneKeepError) else None
            msg = pr.message if pr else str(e)
            self.last_error = msg
            self.write_health(udid, ok=False, reason=msg)
            self.notify("Backup didn't finish", msg)
        finally:
            self.busy, self.progress = False, None
            self.on_change()

    # -- backup health (the scheduler and the phone card read this) ----------------------------------
    def write_health(self, udid: str, ok: bool, reason: str = ""):
        h = sch.Health.load(self.backup_dir / udid)
        now = self.now()
        h.last_try = now
        if ok:
            h.last_ok, h.failed_days, h.last_reason = now, [], ""
        else:
            today = now.date().isoformat()
            h.failed_days = [d for d in (h.failed_days or []) if d != today] + [today]
            h.last_reason = reason
        h.save(self.backup_dir / udid)

    # -- the schedule (B2) -----------------------------------------------------------------------------
    def now(self) -> dt.datetime:
        return self.clock() if self.clock else dt.datetime.now()

    def tick(self) -> str:
        """Called every minute by the helper. Decides from the plan, the phone and the health file.
        Returns what it did, for the tests and the log."""
        plan = sch.Plan.from_settings(settings())
        if plan.mode == "off" or plan.paused:
            return "off"
        now = self.now()
        start = plan.window_start(now)
        if start is not None and now >= start and not self.busy and any(
                not sch.is_fresh(now, sch.Health.load(self.backup_dir / p["udid"]).last_ok)
                for p in self.phones() if p["udid"] and (self.backup_dir / p["udid"] / "Manifest.db").exists()):
            self.refresh_devices(force=True)          # look for the phone only while a backup is due
        done = []
        for ph in self.phones():
            udid = ph["udid"]
            if not udid or not (self.backup_dir / udid / "Manifest.db").exists():
                continue                          # the first backup is made from the window (S1 password)
            health = sch.Health.load(self.backup_dir / udid)
            charging = None
            if plan.only_when_charging and ph["connected"]:
                b = wv.battery_state(udid)
                charging = b["charging"] if b else None
            what, why = sch.decide(plan, health, now, ph["connected"], charging, self.busy)
            if what == "backup":
                self.log(f"Scheduled backup of {ph['name']}")
                if self.back_up_now(udid):
                    done.append(f"backup:{udid}")
            else:
                done.append(f"wait:{why}")
                if not ph["connected"] and now >= dt.datetime.combine(now.date(), dt.time(plan.hour)) \
                        and not sch.is_fresh(now, health.last_ok):
                    # a missed slot counts as a failed try of the day (for the 3-days notice)
                    if (health.last_try is None or health.last_try.date() != now.date()) and now.hour >= 23:
                        self.write_health(udid, ok=False, reason="PhoneKeep couldn't reach your iPhone.")
            notice = sch.failure_notice(sch.Health.load(self.backup_dir / udid), now.date())
            if notice:
                self.notify(*notice)
                h = sch.Health.load(self.backup_dir / udid)
                h.noticed_failure_on = now.date().isoformat()
                h.save(self.backup_dir / udid)
        return ", ".join(done) if done else "nothing"

    # -- the main window ---------------------------------------------------------------------------
    def open_app(self, what: str = "window") -> None:
        """Ask a running PhoneKeep window to show itself (or the phone window), else launch it."""
        if self._ask_app(what):
            return
        cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).with_name("launcher.py"))]
        if what == "phone":
            cmd.append("--open-phone")
        try:
            subprocess.Popen(cmd, close_fds=True)
        except OSError as e:
            self.notify("Couldn't open PhoneKeep", str(e))

    @staticmethod
    def _ask_app(what: str) -> bool:
        try:
            port = int(PORT_FILE.read_text().strip())
            with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
                s.sendall((what + "\n").encode())
                return s.recv(8).startswith(b"ok")
        except Exception:
            return False

    # -- pause --------------------------------------------------------------------------------------
    def set_paused(self, paused: bool):
        self.paused = paused
        try:
            data = settings()
            data["auto_backup_paused"] = paused
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass
        self.on_change()


# -- single instance ------------------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259                       # STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def take_lock() -> bool:
    """True if this process is now the one helper; False if another is already running."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
                if pid != os.getpid() and _pid_alive(pid):
                    return False
            except ValueError:
                pass
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except OSError:
        return True


def release_lock():
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except OSError:
        pass


def helper_running() -> bool:
    try:
        pid = int(LOCK_FILE.read_text().strip())
        return pid != os.getpid() and _pid_alive(pid)
    except Exception:
        return False


# -- the icon --------------------------------------------------------------------------------------------

def icon_image(progress: Optional[float] = None, size: int = 64, template: bool = False):
    """The menu bar / tray icon: the PhoneKeep lock, with a thin progress ring while a backup runs.
    template=True draws it in black for the Mac menu bar (macOS tints template images itself)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ink = (0, 0, 0, 255) if template else (0, 128, 105, 255)
    s = size
    d.rounded_rectangle([s * 0.30, s * 0.14, s * 0.70, s * 0.86], radius=s * 0.08, outline=ink, width=max(2, s // 16))
    d.rounded_rectangle([s * 0.40, s * 0.46, s * 0.60, s * 0.64], radius=s * 0.03, fill=ink)
    d.arc([s * 0.42, s * 0.34, s * 0.58, s * 0.52], start=180, end=360, fill=ink, width=max(2, s // 20))
    if progress is not None:
        d.arc([2, 2, s - 3, s - 3], start=-90, end=-90 + 360 * max(0.0, min(100.0, progress)) / 100,
              fill=ink, width=max(2, s // 14))
    return im
