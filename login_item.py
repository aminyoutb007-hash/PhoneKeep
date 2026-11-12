"""Start the helper at login (E2): a LaunchAgent on the Mac, a Run key on Windows. Asked once (E1
step 5); switchable in Settings → Backups. Nothing is installed without that choice."""
from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

LABEL = "app.phonekeep.helper"


def helper_command() -> list[str]:
    """How to start the helper process. In the packaged app it is the bundled `phonekeep-cli` binary (the
    same code, a separate executable): if the helper were the app's own binary, macOS would treat a later
    click on PhoneKeep as "already running" and show no window. Otherwise python launcher.py."""
    if getattr(sys, "frozen", False):
        import phonekeep as wv
        return [wv._launcher_cmd()[0], "--pk-helper"]
    return [sys.executable, str(Path(__file__).with_name("launcher.py")), "--pk-helper"]


def plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_content(cmd: list[str]) -> bytes:
    return plistlib.dumps({"Label": LABEL, "ProgramArguments": cmd, "RunAtLoad": True,
                           "KeepAlive": False, "ProcessType": "Background"})


def install(home: Path | None = None, cmd: list[str] | None = None) -> str:
    """Register the helper to start at login. Returns where it was registered (for the activity log)."""
    cmd = cmd or helper_command()
    if sys.platform == "darwin" or home is not None:          # a given home = a test on any platform
        p = plist_path(home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(plist_content(cmd))
        return str(p)
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "PhoneKeep helper", 0, winreg.REG_SZ, " ".join(f'"{c}"' for c in cmd))
        return r"HKCU\...\Run\PhoneKeep helper"
    return ""


def remove(home: Path | None = None) -> None:
    if sys.platform == "darwin" or home is not None:
        try:
            plist_path(home).unlink()
        except OSError:
            pass
        return
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "PhoneKeep helper")
        except OSError:
            pass


def installed(home: Path | None = None) -> bool:
    if sys.platform == "darwin" or home is not None:
        return plist_path(home).exists()
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "PhoneKeep helper")
                return True
        except OSError:
            return False
    return False
