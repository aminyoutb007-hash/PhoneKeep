"""No network (S3 in docs/spec/04-security.md), enforced in the process itself.

Once `install()` runs, every outbound connection the process tries to make is checked:
  - the phone (usbmuxd's local socket, loopback, and private/link-local Wi-Fi addresses) is allowed;
  - anything on the internet is refused with a plain error,
    except inside `allow("Check for updates")`, which the one opt-in action uses for one request.
Every decision is recorded in `EVENTS` so a test can prove a whole session made no internet
connection. The guard is installed by launcher.py for the app and for its helper processes.
"""
from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading
from typing import Optional

EVENTS: list[dict] = []          # {"host": ..., "port": ..., "allowed": bool, "why": str}
_installed = False
_allow_reason = threading.local()
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex


class NetworkRefused(OSError):
    """Raised when PhoneKeep would have connected to the internet. It never does, by design."""


def _is_local(host: str) -> bool:
    if not host or host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return host.endswith(".local")    # the phone over Wi-Fi, found by Bonjour
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def _check(sock, address) -> Optional[str]:
    """Return the reason to refuse, or None when allowed. Records the decision."""
    if getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object()):
        EVENTS.append({"host": str(address), "port": None, "allowed": True, "why": "usbmuxd socket"})
        return None
    host, port = (address[0], address[1]) if isinstance(address, tuple) and len(address) >= 2 else (str(address), None)
    reason = getattr(_allow_reason, "why", None)
    if _is_local(host):
        EVENTS.append({"host": host, "port": port, "allowed": True, "why": "phone / this computer"})
        return None
    if reason:
        EVENTS.append({"host": host, "port": port, "allowed": True, "why": reason})
        return None
    EVENTS.append({"host": host, "port": port, "allowed": False, "why": "internet: refused"})
    return f"PhoneKeep doesn't connect to the internet (refused {host}:{port})."


def _connect(self, address):
    why = _check(self, address)
    if why:
        raise NetworkRefused(why)
    return _orig_connect(self, address)


def _connect_ex(self, address):
    why = _check(self, address)
    if why:
        return 111   # ECONNREFUSED
    return _orig_connect_ex(self, address)


def install() -> None:
    """Turn the guard on for this process. Safe to call more than once."""
    global _installed
    if _installed:
        return
    socket.socket.connect = _connect           # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex     # type: ignore[method-assign]
    _installed = True


def installed() -> bool:
    return _installed


@contextlib.contextmanager
def allow(reason: str):
    """Let the enclosed code reach the internet, for exactly the opt-in actions the spec names."""
    _allow_reason.why = reason
    try:
        yield
    finally:
        _allow_reason.why = None


def internet_events() -> list[dict]:
    """Every connection attempt that was not to the phone or this computer, allowed or refused."""
    return [e for e in EVENTS if e["why"] not in ("phone / this computer", "usbmuxd socket")]
