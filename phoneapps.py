"""
PhoneKeep - the phone's app list, fast (5.1.3).

Asking the iPhone for every app with its size takes about half a minute, so the window no longer waits for it:
  * the list is read only when Storage, Apps or the check-up's Storage details are opened;
  * first the names (a fraction of a second), shown at once; then the sizes, a few apps at a time, in the background;
  * the last full list is saved per phone (by UDID) in PhoneKeep's own folder on this computer and shown at once next
    time, marked with its date, while it's quietly refreshed.
Read-only for the phone; the saved copy never leaves this computer.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

import deviceinfo as di
import phonekeep as wv

CHUNK = 20          # apps whose sizes are asked for at once (about 1 s over a cable)


def saved_file(udid: str) -> Path:
    return wv.phone_cache(udid) / "apps.json"


def load_saved(udid: Optional[str]) -> tuple[list[di.AppSize], str]:
    """(apps, the day they were read as "15 Nov 2026") from the last session, or ([], "")."""
    if not udid:
        return [], ""
    try:
        d = json.loads(saved_file(udid).read_text(encoding="utf-8"))
        apps = [di.AppSize(a["bundle"], a["name"], int(a["app"]), int(a["data"])) for a in d["apps"]]
        when = dt.datetime.fromisoformat(d["when"])
        return apps, f"{when.day} {when:%b %Y}"
    except (OSError, ValueError, KeyError, TypeError):
        return [], ""


def save(udid: Optional[str], apps: list[di.AppSize]) -> None:
    if not udid or not apps:
        return
    f = saved_file(udid)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"when": dt.datetime.now().isoformat(timespec="seconds"),
                               "apps": [{"bundle": a.bundle, "name": a.name, "app": a.app_bytes, "data": a.data_bytes}
                                        for a in apps if a.sized]}), encoding="utf-8")
    tmp.replace(f)


def with_names(names: dict[str, str], known: list[di.AppSize]) -> list[di.AppSize]:
    """The phone's apps now (bundle -> name), keeping the sizes already known for each; new ones have no size yet."""
    old = {a.bundle: a for a in known}
    out = []
    for bundle, name in names.items():
        a = old.get(bundle)
        out.append(di.AppSize(bundle, name or bundle, a.app_bytes, a.data_bytes, sized=False) if a
                   else di.AppSize(bundle, name or bundle, 0, 0, sized=False))
    return out


def with_sizes(apps: list[di.AppSize], sizes: dict[str, tuple[int, int]]) -> None:
    for a in apps:
        if a.bundle in sizes:
            a.app_bytes, a.data_bytes = sizes[a.bundle]
            a.sized = True


def chunks(apps: list[di.AppSize]) -> list[list[str]]:
    ids = [a.bundle for a in apps]
    return [ids[i:i + CHUNK] for i in range(0, len(ids), CHUNK)]
