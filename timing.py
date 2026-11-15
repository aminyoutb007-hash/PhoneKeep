"""
PhoneKeep - a timing log for how long a phone takes to appear and fill in (5.1.3, faster Wi-Fi).

Debug only: nothing is written unless PHONEKEEP_TIMING names a file. Each line is a step's name and its seconds,
with "ok" or the error's type. Never the phone's name, UDID, values or anything else from the phone. The launcher's
internal modes write to the same file (the environment is passed on), so steps inside a helper process show too.
Nothing leaves the computer.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time

_lock = threading.Lock()


def path():
    return os.environ.get("PHONEKEEP_TIMING") or ""


def log(step: str, seconds: float, result: str = "ok") -> None:
    p = path()
    if not p:
        return
    line = f"{time.time():.3f}\t{os.getpid()}\t{step}\t{seconds:.2f}\t{result}\n"
    with _lock:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass


@contextlib.contextmanager
def step(name: str):
    """with timing.step("lockdown connect"): ...  - logs the seconds it took, and whether it raised."""
    t = time.perf_counter()
    try:
        yield
    except BaseException as e:
        log(name, time.perf_counter() - t, f"failed: {type(e).__name__}")
        raise
    log(name, time.perf_counter() - t)
