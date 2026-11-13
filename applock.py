"""S2: lock PhoneKeep with the computer's own sign-in (docs/spec/04-security.md#s2-app-lock).

Touch ID or the Mac's password (Apple's LocalAuthentication), or Windows Hello. PhoneKeep keeps no password of
its own. Elsewhere (Linux), the lock isn't available and Settings says so.

    available()                -> "touch_id" | "password" | "hello" | None
    authenticate(reason)       -> True only when the person confirmed (cancel or failure -> False)

A test (or a computer without either) can swap the backend with use_backend().
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

_backend: Optional[dict] = None          # {"available": fn, "authenticate": fn}; None = the real system one
last_problem: str = ""                   # why the lock isn't available, for the activity panel and support


def use_backend(available: Callable[[], Optional[str]], authenticate: Callable[[str], bool]) -> None:
    """Tests: replace the system check (never used by the app itself)."""
    global _backend
    _backend = {"available": available, "authenticate": authenticate}


# ---------------------------------------------------------------- Mac: LocalAuthentication
_LA_BIOMETRICS = 1          # LAPolicyDeviceOwnerAuthenticationWithBiometrics
_LA_OWNER = 2               # LAPolicyDeviceOwnerAuthentication (Touch ID, or the computer password)


def _can(ctx, policy) -> bool:
    r = ctx.canEvaluatePolicy_error_(policy, None)
    return bool(r[0] if isinstance(r, tuple) else r)        # pyobjc returns (ok, error)


def _mac_available() -> Optional[str]:
    global last_problem
    try:
        from LocalAuthentication import LAContext
    except Exception as e:
        last_problem = f"LocalAuthentication not available: {type(e).__name__}: {e}"
        return None
    try:
        ctx = LAContext.alloc().init()
        if _can(ctx, _LA_BIOMETRICS):
            return "touch_id"
        owner = _can(ctx, _LA_OWNER)
        # A Mac with Touch ID whose sensor can't be used right now (lid closed, an external keyboard without
        # Touch ID) still counts as a Touch ID Mac: the lock stays on and asks for the password instead
        # (13 Nov: the owner's MacBook, lid closed, reported "password only" and the lock stayed off).
        try:
            has_sensor = int(ctx.biometryType()) == 1          # LABiometryTypeTouchID
        except Exception:
            has_sensor = False
        if owner and has_sensor:
            return "touch_id"
        if owner:
            return "password"
        last_problem = "this Mac has neither Touch ID nor a login password the system will check"
    except Exception as e:
        last_problem = f"LocalAuthentication check failed: {type(e).__name__}: {e}"
    return None


def _mac_authenticate(reason: str) -> bool:
    from LocalAuthentication import LAContext
    ctx = LAContext.alloc().init()
    done, box = threading.Event(), {"ok": False}

    def reply(success, _error):
        box["ok"] = bool(success)
        done.set()
    ctx.evaluatePolicy_localizedReason_reply_(_LA_OWNER, reason, reply)
    done.wait(300)
    return box["ok"]


# ---------------------------------------------------------------- Windows: Windows Hello
def _win_available() -> Optional[str]:
    global last_problem
    try:
        import asyncio
        from winrt.windows.security.credentials.ui import UserConsentVerifier, UserConsentVerifierAvailability
        res = asyncio.run(_await(UserConsentVerifier.check_availability_async()))
        if res == UserConsentVerifierAvailability.AVAILABLE:
            return "hello"
        last_problem = f"Windows Hello is not set up ({res})"
        return None
    except Exception as e:
        last_problem = f"Windows Hello not available: {type(e).__name__}: {e}"
        return None


def _win_authenticate(reason: str) -> bool:
    try:
        import asyncio
        from winrt.windows.security.credentials.ui import UserConsentVerifier, UserConsentVerificationResult
        res = asyncio.run(_await(UserConsentVerifier.request_verification_async(reason)))
        return res == UserConsentVerificationResult.VERIFIED
    except Exception:
        return False


async def _await(op):
    return await op


# ---------------------------------------------------------------- the two calls
def available() -> Optional[str]:
    """What this computer can lock PhoneKeep with, or None."""
    if _backend is not None:
        return _backend["available"]()
    if sys.platform == "darwin":
        return _mac_available()
    if sys.platform == "win32":
        return _win_available()
    return None


def authenticate(reason: str = "unlock PhoneKeep") -> bool:
    """Ask the system to confirm it's the computer's owner. Blocks; call it off the UI thread."""
    if _backend is not None:
        return bool(_backend["authenticate"](reason))
    try:
        if sys.platform == "darwin":
            return _mac_authenticate(reason)
        if sys.platform == "win32":
            return _win_authenticate(reason)
    except Exception:
        return False
    return False


def default_on(kind: Optional[str]) -> bool:
    """Spec: on by default where the computer has Touch ID or Windows Hello; off otherwise (the first-run
    guide offers it on a Mac without Touch ID)."""
    return kind in ("touch_id", "hello")


def describe(kind: Optional[str]) -> str:
    return {"touch_id": "Touch ID or your Mac's password", "password": "your Mac's password",
            "hello": "Windows Hello"}.get(kind or "", "")
