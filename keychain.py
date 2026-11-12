"""The backup password, kept in the computer's own keychain (S1 in docs/spec/04-security.md).

Mac: Keychain. Windows: Credential Manager. One entry per iPhone, named by the phone's UDID.
The password is read silently when a backup needs opening and is never written to a file, a log
or a command line by any module of PhoneKeep.

If the computer has no usable keychain (some Linux machines), PhoneKeep still works: it asks for
the password each time, and `available()` says so to the UI.
"""
from __future__ import annotations

from typing import Optional

SERVICE = "PhoneKeep backup password"


def _backend():
    import keyring
    return keyring


def available() -> bool:
    """True when a real keychain backend can store passwords on this computer."""
    try:
        import keyring
        from keyring.backends import fail, null
        kr = keyring.get_keyring()
        return not isinstance(kr, (fail.Keyring, null.Keyring))
    except Exception:
        return False


def get_password(udid: str) -> Optional[str]:
    try:
        return _backend().get_password(SERVICE, udid) or None
    except Exception:
        return None


def set_password(udid: str, password: str) -> bool:
    """Store the password; returns False if the keychain refused (the caller asks again next time)."""
    try:
        _backend().set_password(SERVICE, udid, password)
        return True
    except Exception:
        return False


def delete_password(udid: str) -> None:
    try:
        _backend().delete_password(SERVICE, udid)
    except Exception:
        pass


def use_memory() -> None:
    """Tests only: keep passwords in memory for this process instead of the real keychain."""
    import keyring
    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 1

        def __init__(self):
            self.store = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    keyring.set_keyring(Memory())


def strength(password: str) -> tuple[int, str]:
    """0–4 and a plain word for the strength hint under the password field."""
    if not password:
        return 0, ""
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    kinds = sum(bool(s) for s in (any(c.islower() for c in password), any(c.isupper() for c in password),
                                   any(c.isdigit() for c in password), any(not c.isalnum() for c in password)))
    if kinds >= 2:
        score += 1
    if kinds >= 3 and len(password) >= 10:
        score += 1
    words = ["Too short", "Weak", "OK", "Good", "Strong"]
    return score, words[score]
