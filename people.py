"""Q3: everything about one person (docs/spec/11-previews.md#q3-contact-cards).

A contact's numbers and email addresses are matched against what the backup already has: the chats in Messages,
WhatsApp and WhatsApp Business (a one-to-one chat by its number or address; a group chat by the messages they sent in
it), the calls and the voicemails. Numbers are compared by their last nine digits (sections.phone_key), so "+44 7700
900123" and "07700 900123" are the same person. Nothing here reads the backup itself or the phone: it works on what
the phone window has loaded.
"""
from __future__ import annotations

from typing import Optional

import re

import phonekeep as wv
import sections as sx

CHAT_APPS = (("messages", "Messages"), ("whatsapp", "WhatsApp"), ("whatsappbusiness", "WhatsApp Business"))


def _number(s: str) -> str:
    """sections.phone_key, and a short number (a service's) by its digits too: "123 45" is "12345"."""
    k = sx.phone_key(s)
    if "@" in k:
        return k
    d = re.sub(r"\D", "", k)
    return d or k


def keys_of(p: dict) -> set[str]:
    """The person's numbers and email addresses, as compared."""
    out = {_number(v) for _l, v in p.get("phones", ()) if (v or "").strip()}
    out |= {v.strip().lower() for _l, v in p.get("emails", ()) if (v or "").strip()}
    return {k for k in out if k}


def key_of(addr: Optional[str]) -> str:
    """One address as compared: a number, an email address, or a WhatsApp id ("447700900123@s.whatsapp.net").
    A WhatsApp group or a hidden-number id gives ""."""
    addr = (addr or "").strip()
    if addr.endswith(("@s.whatsapp.net", "@g.us", "@lid", "@broadcast")):
        addr = wv.jid_number(addr)
    return _number(addr) if addr else ""


def _sender_key(m: dict) -> str:
    return key_of((m.get("detail") or {}).get("number"))


def chats_with(app: str, chats: list, keys: set[str]) -> list[dict]:
    """[{"app", "chat", "group", "count", "last"}]: one-to-one chats with them, and group chats they wrote in
    ("count" and "last" are then their own messages)."""
    out = []
    if not keys:
        return out
    for c in chats or ():
        msgs = c.get("messages") or []
        if c.get("group"):
            msgs = [m for m in msgs if not m.get("from_me") and _sender_key(m) in keys]
            if not msgs:
                continue
        elif key_of(c.get("jid")) not in keys:
            continue
        last = max((m.get("time") or "" for m in msgs), default="")
        out.append({"app": app, "chat": c, "group": bool(c.get("group")), "count": len(msgs), "last": last})
    return out


def all_chats_with(loaded: dict, keys: set[str]) -> list[dict]:
    """loaded: {app key: its chats}. Every app's chats with them, newest first."""
    out = []
    for app, _label in CHAT_APPS:
        out += chats_with(app, loaded.get(app) or [], keys)
    return sorted(out, key=lambda x: x["last"], reverse=True)


def calls_with(rows: list, keys: set[str]) -> list[tuple[int, list]]:
    """[(place in `rows`, row)]: the calls with them (rows in CALL_HEADERS order, newest first already)."""
    return [(i, r) for i, r in enumerate(rows or ()) if keys and key_of(str(r[3])) in keys]


def voicemails_with(items: list, keys: set[str]) -> list[tuple[int, dict]]:
    """[(place in `items`, voicemail)]: the voicemails they left (newest first already)."""
    return [(i, v) for i, v in enumerate(items or ()) if keys and key_of(v.get("number")) in keys]


def person_for(people: list, addr: Optional[str]) -> Optional[int]:
    """The place in `people` of the contact with that number or address, or None (also when two contacts have it:
    PhoneKeep then can't tell whose card it is)."""
    k = key_of(addr)
    if not k:
        return None
    found = [i for i, p in enumerate(people or ()) if k in keys_of(p)]
    return found[0] if len(found) == 1 else None


def contacts_with(people: list, addr: Optional[str]) -> int:
    """How many contacts have that number or address (person_for finds one only when this is 1)."""
    k = key_of(addr)
    return sum(1 for p in people or () if k in keys_of(p)) if k else 0


def find_all(get, keys: set[str]) -> dict:
    """get(key) -> what the phone window loads for that app (BackupData.get). Returns {"chats", "calls",
    "voicemail", "missing", "unread"}: what's with them in each, newest first; the apps this backup doesn't have
    (PhoneKeep says so for them); and the ones that are there but couldn't be read."""
    loaded, missing, unread = {}, [], []

    def load(key, label):
        try:
            return get(key)
        except wv.PhoneKeepError:
            missing.append(label)
        except Exception:
            unread.append(label)
        return None
    for app, label in CHAT_APPS:
        v = load(app, label)
        if v is not None:
            loaded[app] = v if app == "messages" else v["chats"]
    calls = load("calls", "Calls")
    vms = load("voicemail", "Voicemail")
    return {"chats": all_chats_with(loaded, keys), "calls": calls_with(calls or [], keys),
            "voicemail": voicemails_with(vms or [], keys), "missing": missing, "unread": unread}
