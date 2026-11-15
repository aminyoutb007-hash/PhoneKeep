"""
PhoneKeep - when the iPhone's connection drops (5.1.3).

After the iPhone is unplugged and plugged back in (even into another USB port), the old connection is dead:
every live read fails with ConnectionTerminatedError and the like. Here:

  * is_dropped(e): is this a dropped connection (not some other problem)?
  * retry_once: a live read that fails with a dropped connection reconnects once (to the same phone, by its
    UDID) and tries once more; if that fails too, Disconnected says so in plain words;
  * where(udid): is this phone reachable now, and how ("USB" or "Network")? A light, read-only question to
    Apple's USB service; the phone window asks it every few seconds.

Read-only: nothing here writes to the phone. A different phone is never picked up in place of this one.
"""
from __future__ import annotations

import asyncio
import functools
from typing import Callable, Optional

import phonekeep as wv
from errors import DISCONNECTED          # worded once, in the errors table
GONE = "Not connected · plug your iPhone back in"         # the phone window's header while it's gone
PLUG_BACK = "Plug your iPhone back in to see this"         # a live-only section while it's gone

# what a dropped connection raises: Python's own, pymobiledevice3's and usbmux's (by name, so nothing has to be
# imported to check)
DROPPED_NAMES = {"ConnectionTerminatedError", "ConnectionAbortedError", "BrokenPipeError", "ConnectionResetError",
                 "MuxException", "NoDeviceConnectedError", "NotConnectedError", "DeviceNotFoundError",
                 "IncompleteReadError", "ConnectionFailedError"}
DROPPED_WORDS = ("terminated abruptly", "connection was terminated", "broken pipe", "connection reset",
                 "connection aborted")


class NotConnected:
    """Stands in for a connection that's gone while a new one can't be made yet: anything asked of it is a dropped
    connection, so the next read retries (and says so plainly) instead of failing on None."""

    def __getattr__(self, name):
        raise ConnectionAbortedError("the iPhone isn't connected")


class Disconnected(wv.PhoneKeepError):
    """The phone went and didn't come back for the retry."""

    def __init__(self, details: str = ""):
        super().__init__(DISCONNECTED, details=details, key="disconnected")


def is_dropped(e: BaseException) -> bool:
    """True for a dropped connection to the iPhone, also when it's the cause of another error."""
    seen = 0
    while e is not None and seen < 6:
        if isinstance(e, Disconnected):
            return True
        if any(c.__name__ in DROPPED_NAMES for c in type(e).__mro__):
            return True
        if any(w in str(e).lower() for w in DROPPED_WORDS):
            return True
        e = e.__cause__ or e.__context__
        seen += 1
    return False


def retry_once(method: Callable) -> Callable:
    """For a live-read method of an object with reconnect(seen) and a `generation` count: on a dropped connection,
    reconnect once and try once more. Never shows the exception's name: what's left is Disconnected."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        seen = getattr(self, "generation", 0)
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            if not is_dropped(e):
                raise
            first = e
        try:
            self.reconnect(seen)
        except Exception as e:
            raise Disconnected(f"{type(first).__name__}: {first}\nreconnecting: {type(e).__name__}: {e}") from e
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            if is_dropped(e):
                raise Disconnected(f"{type(e).__name__}: {e}") from e
            raise
    return wrapper


def where(udid: Optional[str]) -> Optional[str]:
    """"USB" or "Network" when this phone (and only this one) is reachable now, else None. Raises when Apple's USB
    service itself can't be asked (then nothing is known either way)."""
    if not udid:
        return None
    from pymobiledevice3 import usbmux

    async def ask():
        return await usbmux.list_devices()
    found = [d for d in asyncio.run(ask()) if d.matches_udid(udid)]
    if not found:
        return None
    return "USB" if any(d.connection_type == "USB" for d in found) else "Network"
