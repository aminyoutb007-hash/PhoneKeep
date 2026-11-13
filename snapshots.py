"""B3. Snapshots over time (docs/spec/03-backup.md) and the on-disk format behind them.

Layout of one phone's folder, <backup_dir>/<UDID>/   (format 1)
    format.json                 {"format": 1}
    current/<UDID>/             the live iTunes-style backup the phone updates incrementally
    store/<aa>/<sha256>         every file blob once, named by the SHA-256 of its content
    store/hashes.json           fileID -> [size, mtime_ns, sha256], so unchanged blobs aren't re-hashed
    snapshots/<YYYYMMDD-HHMMSS>/
        snapshot.json           the five unencrypted fields: date, size, ios, name, model
        Manifest.db, Manifest.plist, Info.plist, Status.plist
        files.json              fileID -> sha256 (this snapshot's view of the store)
    snapshots.json              the owner's choices: {"<id>": {"locked": true, "label": "Before the holiday"}}

Hashes, not hard links, so it works the same on internal disks, external drives, exFAT and network
drives. FAT32 is refused (files over 4 GB can't be stored). Older layouts (4.x: Manifest.db at the top of
the phone folder) are converted on first use: snapshot made, verified, then the old backup becomes `current`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

FORMAT = 1
KEEP_DEFAULT = 10
MANIFEST_FILES = ("Manifest.db", "Manifest.plist", "Info.plist", "Status.plist")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FormatTooNew(Exception):
    pass


class FileSystemRefused(Exception):
    pass


# -- paths ------------------------------------------------------------------------------------------------

def phone_dir(backup_dir: Path, udid: str) -> Path:
    return Path(backup_dir) / udid


def current_dir(backup_dir: Path, udid: str) -> Path:
    """Where the phone's live backup lives (the folder pymobiledevice3 updates)."""
    return phone_dir(backup_dir, udid) / "current" / udid


def live_root(backup_dir: Path, udid: str) -> Path:
    """The backup_root to hand pymobiledevice3 (it appends the UDID itself)."""
    return phone_dir(backup_dir, udid) / "current"


def store_dir(backup_dir: Path, udid: str) -> Path:
    return phone_dir(backup_dir, udid) / "store"


def snapshots_dir(backup_dir: Path, udid: str) -> Path:
    return phone_dir(backup_dir, udid) / "snapshots"


def is_old_layout(pdir: Path) -> bool:
    return (pdir / "Manifest.db").exists() and not (pdir / "format.json").exists()


def read_format(pdir: Path) -> Optional[int]:
    try:
        return int(json.loads((pdir / "format.json").read_text(encoding="utf-8"))["format"])
    except Exception:
        return None


def check_format(pdir: Path) -> None:
    f = read_format(pdir)
    if f is not None and f > FORMAT:
        raise FormatTooNew(f"This backup folder was made by a newer PhoneKeep (format {f}). Update PhoneKeep to open it.")


def latest_backup_path(backup_dir: Path, udid: str) -> Optional[Path]:
    """The folder to open for 'the latest backup' of a phone, in either layout; None if there is none."""
    pdir = phone_dir(backup_dir, udid)
    snaps = list_snapshots(backup_dir, udid)
    if snaps:
        return snaps[0].path
    if (current_dir(backup_dir, udid) / "Manifest.db").exists():
        return current_dir(backup_dir, udid)
    if (pdir / "Manifest.db").exists():
        return pdir
    return None


def has_backup(backup_dir: Path, udid: str) -> bool:
    return latest_backup_path(backup_dir, udid) is not None


# -- the file system ------------------------------------------------------------------------------------------

def filesystem_name(path: Path) -> str:
    """'apfs', 'exfat', 'fat32', 'ntfs', 'smbfs', ... (lower case), or '' when unknown."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        if sys.platform == "win32":
            import ctypes
            buf = ctypes.create_unicode_buffer(64)
            root = os.path.splitdrive(str(p.resolve()))[0] + "\\"
            if ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, None, None, None, buf, 64):
                return buf.value.lower()
            return ""
        if sys.platform == "darwin":
            out = subprocess.run(["diskutil", "info", str(p)], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"Type \(Bundle\):\s+(\S+)", out) or re.search(r"File System Personality:\s+(.+)", out)
            name = (m.group(1) if m else "").strip().lower()
            return "fat32" if name in ("msdos", "ms-dos fat32", "fat32") else name
        # Linux: longest matching mount point in /proc/mounts
        best, fs = "", ""
        target = str(p.resolve())
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and target.startswith(parts[1]) and len(parts[1]) > len(best):
                best, fs = parts[1], parts[2]
        return "fat32" if fs in ("vfat", "msdos") else fs.lower()
    except Exception:
        return ""


FAT32_MESSAGE = ("This drive uses an old format (FAT32) that can't hold files over 4 GB. "
                 "Format it as exFAT or APFS, or choose another drive.")


def check_filesystem(path: Path, name: Optional[str] = None) -> None:
    """Refuse FAT32 with the plain message from the spec. `name` lets tests inject a file system."""
    fs = name if name is not None else filesystem_name(path)
    if fs in ("fat32", "vfat", "msdos", "fat"):
        raise FileSystemRefused(FAT32_MESSAGE)


# -- snapshots ------------------------------------------------------------------------------------------------

@dataclass
class Snapshot:
    id: str
    path: Path
    when: dt.datetime
    size: int
    ios: str
    name: str
    model: str
    encrypted: bool
    locked: bool = False
    label: str = ""

    @property
    def title(self) -> str:
        """'Today', 'Yesterday', '3 Nov', '27 Oct 2025' — or the owner's label."""
        if self.label:
            return self.label
        d, today = self.when.date(), dt.date.today()
        if d == today:
            return "Today"
        if d == today - dt.timedelta(days=1):
            return "Yesterday"
        day = self.when.strftime("%d").lstrip("0")
        return f"{day} {self.when.strftime('%b')}" + ("" if d.year == today.year else f" {d.year}")


def timeline_titles(snaps: list) -> list[str]:
    """Titles for the timeline: the day, plus the time when there are several snapshots that day
    ("Today 11:33", "Today 12:11"; owner, 13 Nov: four buttons all said "Today")."""
    per_day: dict = {}
    for s in snaps:
        per_day[s.when.date()] = per_day.get(s.when.date(), 0) + 1
    out = []
    for s in snaps:
        if s.label or per_day[s.when.date()] == 1:
            out.append(s.title)
        else:
            out.append(f"{s.title} {s.when.strftime('%H:%M')}")
    return out


def _choices(backup_dir: Path, udid: str) -> dict:
    try:
        return json.loads((phone_dir(backup_dir, udid) / "snapshots.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_choices(backup_dir: Path, udid: str, data: dict) -> None:
    (phone_dir(backup_dir, udid) / "snapshots.json").write_text(json.dumps(data, indent=1), encoding="utf-8")


def list_snapshots(backup_dir: Path, udid: str) -> list[Snapshot]:
    """Newest first."""
    sdir = snapshots_dir(backup_dir, udid)
    out = []
    choices = _choices(backup_dir, udid)
    try:
        entries = sorted(sdir.iterdir(), reverse=True)
    except OSError:
        return out
    for p in entries:
        try:
            side = json.loads((p / "snapshot.json").read_text(encoding="utf-8"))
            enc = False
            try:
                import plistlib
                with open(p / "Manifest.plist", "rb") as f:
                    enc = bool(plistlib.load(f).get("IsEncrypted", False))
            except Exception:
                pass
            c = choices.get(p.name, {})
            out.append(Snapshot(p.name, p, dt.datetime.fromisoformat(side["date"]), int(side["size"]),
                                str(side.get("ios") or ""), str(side.get("name") or ""), str(side.get("model") or ""),
                                enc, bool(c.get("locked")), str(c.get("label") or "")))
        except Exception:
            continue
    out.sort(key=lambda s: s.when, reverse=True)
    return out


def _blob_path(store: Path, sha: str) -> Path:
    return store / sha[:2] / sha


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_blobs(backup: Path):
    """(fileID, path) for every file blob in an iTunes-style backup folder."""
    for sub in backup.iterdir():
        if sub.is_dir() and len(sub.name) == 2:
            for f in sub.iterdir():
                if f.is_file() and _HEX40.match(f.name):
                    yield f.name, f
        elif sub.is_file() and _HEX40.match(sub.name):
            yield sub.name, sub


def make_snapshot(backup_dir: Path, udid: str, source: Optional[Path] = None,
                  log: Callable[[str], None] = lambda m: None,
                  progress: Optional[Callable[[float], None]] = None, when: Optional[dt.datetime] = None) -> Snapshot:
    """Record the live backup (or `source`) as a new snapshot: every blob into the store once, then the
    manifest files and the fileID -> hash list. Verified: every blob of the snapshot exists in the store
    with the right size."""
    pdir = phone_dir(backup_dir, udid)
    check_format(pdir)
    check_filesystem(pdir)
    source = source or current_dir(backup_dir, udid)
    if not (source / "Manifest.db").exists():
        raise FileNotFoundError(f"No backup to snapshot in {source}")
    store = store_dir(backup_dir, udid)
    store.mkdir(parents=True, exist_ok=True)
    cache_file = store / "hashes.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    blobs = list(_iter_blobs(source))
    files, total, copied = {}, 0, 0
    for i, (fid, path) in enumerate(blobs):
        st = path.stat()
        c = cache.get(fid)
        if c and c[0] == st.st_size and c[1] == st.st_mtime_ns and _HEX64.match(c[2]) and _blob_path(store, c[2]).exists():
            sha = c[2]
        else:
            sha = _sha256(path)
            cache[fid] = [st.st_size, st.st_mtime_ns, sha]
        dest = _blob_path(store, sha)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            shutil.copyfile(path, tmp)
            os.replace(tmp, dest)
            copied += 1
        files[fid] = sha
        total += st.st_size
        if progress and i % 200 == 0:
            progress(100.0 * i / max(1, len(blobs)))
    cache_file.write_text(json.dumps(cache), encoding="utf-8")

    when = when or dt.datetime.now()
    sid = when.strftime("%Y%m%d-%H%M%S")
    while (snapshots_dir(backup_dir, udid) / sid).exists():      # two in the same second (tests, quick retries)
        when += dt.timedelta(seconds=1)
        sid = when.strftime("%Y%m%d-%H%M%S")
    sdir = snapshots_dir(backup_dir, udid) / sid
    tmpdir = sdir.with_name(sid + ".part")
    shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True)
    for name in MANIFEST_FILES:
        if (source / name).exists():
            shutil.copyfile(source / name, tmpdir / name)
    (tmpdir / "files.json").write_text(json.dumps(files), encoding="utf-8")
    import phonekeep as wv
    info = wv.backup_info(source)
    model = ""
    try:
        import plistlib
        with open(source / "Info.plist", "rb") as f:
            model = str(plistlib.load(f).get("Product Type") or "")
    except Exception:
        pass
    side = {"date": when.isoformat(timespec="seconds"), "size": total, "ios": info.get("ios") or "",
            "name": info.get("name") or "", "model": model}
    (tmpdir / "snapshot.json").write_text(json.dumps(side), encoding="utf-8")
    # verify before it counts
    missing = [fid for fid, sha in files.items() if not _blob_path(store, sha).exists()]
    if missing:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise OSError(f"Snapshot not complete: {len(missing)} files missing from the store")
    os.replace(tmpdir, sdir)
    (pdir / "format.json").write_text(json.dumps({"format": FORMAT}), encoding="utf-8")
    log(f"Snapshot {sid}: {len(files):,} files, {copied:,} new in the store.")
    if progress:
        progress(100.0)
    return next(s for s in list_snapshots(backup_dir, udid) if s.id == sid)


def resolve(snapshot_dir: Path, file_id: str) -> Optional[Path]:
    """The store blob behind a file ID of a snapshot (None if this folder isn't a snapshot or has no such file)."""
    try:
        files = _files_cache.get(snapshot_dir)
        if files is None:
            files = json.loads((Path(snapshot_dir) / "files.json").read_text(encoding="utf-8"))
            _files_cache[snapshot_dir] = files
        sha = files.get(file_id)
        if not sha or not _HEX64.match(sha):
            return None
        return _blob_path(Path(snapshot_dir).parent.parent / "store", sha)
    except Exception:
        return None


_files_cache: dict = {}


def is_snapshot(path: Path) -> bool:
    return (Path(path) / "files.json").exists() and (Path(path) / "snapshot.json").exists()


# -- the owner's choices ------------------------------------------------------------------------------------------

def set_locked(backup_dir: Path, udid: str, sid: str, locked: bool) -> None:
    c = _choices(backup_dir, udid)
    c.setdefault(sid, {})["locked"] = bool(locked)
    _save_choices(backup_dir, udid, c)


def set_label(backup_dir: Path, udid: str, sid: str, label: str) -> None:
    c = _choices(backup_dir, udid)
    c.setdefault(sid, {})["label"] = label.strip()[:80]
    _save_choices(backup_dir, udid, c)


def delete_snapshot(backup_dir: Path, udid: str, sid: str, to_trash: bool = True) -> None:
    """Remove one snapshot (its list goes to the Trash where possible), then drop blobs nobody uses."""
    sdir = snapshots_dir(backup_dir, udid) / sid
    if not sdir.exists():
        return
    if to_trash:
        try:
            from send2trash import send2trash
            send2trash(str(sdir))
        except Exception:
            shutil.rmtree(sdir, ignore_errors=True)
    else:
        shutil.rmtree(sdir, ignore_errors=True)
    _files_cache.pop(sdir, None)
    c = _choices(backup_dir, udid)
    if c.pop(sid, None) is not None:
        _save_choices(backup_dir, udid, c)
    collect_garbage(backup_dir, udid)


def collect_garbage(backup_dir: Path, udid: str) -> int:
    """Delete store blobs no snapshot refers to. Returns how many were removed."""
    store = store_dir(backup_dir, udid)
    if not store.exists():
        return 0
    used = set()
    for s in list_snapshots(backup_dir, udid):
        try:
            used.update(json.loads((s.path / "files.json").read_text(encoding="utf-8")).values())
        except Exception:
            return 0            # a snapshot we can't read: better keep everything
    removed = 0
    for sub in store.iterdir():
        if sub.is_dir() and len(sub.name) == 2:
            for f in sub.iterdir():
                if f.is_file() and f.name not in used and _HEX64.match(f.name):
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
    return removed


# -- keeping the right number -------------------------------------------------------------------------------------

def prune(backup_dir: Path, udid: str, keep: int = KEEP_DEFAULT, until_disk_full: bool = False,
          disk_full_fraction: float = 0.90, log: Callable[[str], None] = lambda m: None) -> list[str]:
    """Automatic clean-up after a backup. Locked snapshots are never removed; the oldest unlocked goes first.
    keep: 3..100 snapshots, or until_disk_full: keep everything until the disk is 90% full."""
    snaps = list_snapshots(backup_dir, udid)
    removed = []
    if until_disk_full:
        while len(snaps) > 1:
            try:
                u = shutil.disk_usage(str(phone_dir(backup_dir, udid)))
            except OSError:
                break
            if u.used / u.total < disk_full_fraction:
                break
            victim = next((s for s in reversed(snaps) if not s.locked), None)
            if victim is None:
                break
            delete_snapshot(backup_dir, udid, victim.id, to_trash=False)
            removed.append(victim.id)
            snaps = [s for s in snaps if s.id != victim.id]
        return removed
    keep = max(3, min(100, int(keep)))
    unlocked = [s for s in snaps if not s.locked]
    while len(snaps) > keep and unlocked:
        victim = unlocked.pop()        # oldest unlocked
        delete_snapshot(backup_dir, udid, victim.id, to_trash=False)
        removed.append(victim.id)
        snaps = [s for s in snaps if s.id != victim.id]
    if removed:
        log(f"Removed {len(removed)} old snapshot{'s' if len(removed) != 1 else ''} (keeping {keep}).")
    return removed


# -- upgrading a 4.x phone folder -----------------------------------------------------------------------------

def upgrade(backup_dir: Path, udid: str, log: Callable[[str], None] = lambda m: None) -> Optional[Snapshot]:
    """Turn a 4.x backup (Manifest.db at the top of the phone folder) into snapshot 1.
    Converted and verified first; only then is the old backup moved to become `current`. If anything
    fails, the old backup is left exactly as it was."""
    pdir = phone_dir(backup_dir, udid)
    if not is_old_layout(pdir):
        return None
    check_filesystem(pdir)
    log("Converting your existing backup into the first snapshot…")
    snap = make_snapshot(backup_dir, udid, source=pdir, log=log)
    # verify: every blob of the old backup is in the store with the same checksum
    files = json.loads((snap.path / "files.json").read_text(encoding="utf-8"))
    for fid, path in _iter_blobs(pdir):
        sha = files.get(fid)
        if not sha or not _blob_path(store_dir(backup_dir, udid), sha).exists() \
                or _blob_path(store_dir(backup_dir, udid), sha).stat().st_size != path.stat().st_size:
            shutil.rmtree(snap.path, ignore_errors=True)
            raise OSError("The converted snapshot didn't match the backup; nothing was changed.")
    # now move the old backup under current/<udid>: a rename on the same volume, nothing copied or deleted
    cur = current_dir(backup_dir, udid)
    cur.parent.mkdir(parents=True, exist_ok=True)
    cur.mkdir(exist_ok=True)
    for item in list(pdir.iterdir()):
        if item.name in ("format.json", "store", "snapshots", "snapshots.json", "current", "health.json", "backup.lock"):
            continue
        os.replace(item, cur / item.name)
    log("Done: snapshot 1 made and verified; the backup now lives in its snapshot store.")
    return snap


# -- making the readers store-aware ------------------------------------------------------------------------------

_hooked = False


def install_decrypt_hook() -> None:
    """iphone_backup_decrypt finds blobs by <folder>/<aa>/<fileID>. For a snapshot, point it at the store blob
    instead. One small patch, here and nowhere else; the original (safe) lookup is kept for real backups."""
    global _hooked
    if _hooked:
        return
    try:
        import iphone_backup_decrypt.utils as u
    except ImportError:
        return
    original = u.backup_file_path

    def patched(backup_folder, file_id):
        if is_snapshot(Path(backup_folder)):
            r = resolve(Path(backup_folder), file_id)
            if r is not None:
                return str(r)
        return original(backup_folder, file_id)
    u.backup_file_path = patched
    try:
        import iphone_backup_decrypt.iphone_backup as ib
        ib.utils.backup_file_path = patched
    except Exception:
        pass
    _hooked = True
