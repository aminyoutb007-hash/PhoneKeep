"""B4. Backup location and moving backups (docs/spec/03-backup.md).

- Where backups live, how much they use and how much room is left (for Settings → Backups → Location).
- Moving backups to another folder or drive: copy everything, verify (file count and checksums), then
  remove the old copy; the old copy is kept if anything fails.
- Before a backup: the free-space warning; when the drive is unplugged: "Connect <drive> to back up."
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional


def drive_name(path: Path) -> str:
    """'Backup Drive' for /Volumes/Backup Drive/…, 'D:' on Windows, 'this disk' for the internal disk."""
    p = Path(path)
    parts = p.parts
    if sys.platform == "darwin" and len(parts) >= 3 and parts[1] == "Volumes":
        return parts[2]
    if os.name == "nt":
        drive = os.path.splitdrive(str(p))[0]
        if drive and not drive.upper().startswith("C"):
            return drive.upper()
        if str(p).startswith("\\\\"):
            return "the network drive " + str(p).split("\\")[2]
    mp = _linux_mount(p)
    if mp is not None:
        return mp.name
    return "this disk"


def _linux_mount(p: Path):
    """The removable mount point under a path like /media/<user>/<drive>/… or /mnt/<drive>/…, else None."""
    parts = p.parts
    if len(parts) >= 4 and parts[1] == "media":
        return Path(*parts[:4])            # /media/<user>/<drive>
    if len(parts) >= 3 and parts[1] in ("mnt", "media"):
        return Path(*parts[:3])            # /mnt/<drive>
    if len(parts) >= 5 and parts[1] == "run" and parts[2] == "media":
        return Path(*parts[:5])            # /run/media/<user>/<drive>
    return None


def is_available(path: Path) -> bool:
    """Is the drive holding `path` connected? The folder itself may not exist yet; its volume must."""
    p = Path(path)
    if sys.platform == "darwin" and len(p.parts) >= 3 and p.parts[1] == "Volumes":
        return Path(*p.parts[:3]).exists()
    if os.name == "nt":
        drive = os.path.splitdrive(str(p))[0]
        if drive:
            return Path(drive + "\\").exists()
        return True
    mp = _linux_mount(p)
    if mp is not None:
        return mp.exists()
    return True


def connect_message(path: Path) -> str:
    return f"Connect {drive_name(path)} to back up."


def usage(path: Path) -> dict:
    """{'used': bytes used by backups, 'free': bytes free on the drive, 'total': drive size, 'drive': name}."""
    p = Path(path)
    used = 0
    try:
        used = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        pass
    free = total = 0
    try:
        q = p
        while not q.exists() and q.parent != q:
            q = q.parent
        u = shutil.disk_usage(str(q))
        free, total = u.free, u.total
    except OSError:
        pass
    return {"used": used, "free": free, "total": total, "drive": drive_name(p)}


def human(n: float) -> str:
    gb = n / 1e9
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{n / 1e6:.1f} MB"


def estimate_needed(current_backup: Optional[Path], phone_used_bytes: Optional[int]) -> int:
    """How much room the next backup may need: a first backup needs about what the phone uses; an
    incremental one a share of the existing backup. Generous on purpose."""
    if current_backup and (Path(current_backup) / "Manifest.db").exists():
        try:
            size = sum(f.stat().st_size for f in Path(current_backup).rglob("*") if f.is_file())
        except OSError:
            size = 0
        return max(2_000_000_000, int(size * 0.15))
    if phone_used_bytes:
        return int(phone_used_bytes * 1.05)
    return 10_000_000_000


def space_warning(backup_root: Path, needed: int) -> Optional[str]:
    """None when there is room; otherwise the sentence from the spec."""
    u = usage(backup_root)
    if u["total"] and u["free"] < needed:
        return f"Not enough space on {u['drive']}: {human(needed)} needed, {human(u['free'])} free."
    return None


# -- moving -------------------------------------------------------------------------------------------------

def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def move_backups(old_root: Path, new_root: Path, log: Callable[[str], None] = lambda m: None,
                 progress: Optional[Callable[[float], None]] = None, verify: bool = True) -> dict:
    """Copy every file from old_root to new_root, verify count and checksums, then remove the old copy.
    Returns {'files': n, 'bytes': b}. Raises on any failure, leaving the old copy in place."""
    old_root, new_root = Path(old_root), Path(new_root)
    if not old_root.exists():
        return {"files": 0, "bytes": 0}
    if new_root.resolve() == old_root.resolve():
        return {"files": 0, "bytes": 0}
    if str(new_root.resolve()).startswith(str(old_root.resolve()) + os.sep):
        raise ValueError("The new folder can't be inside the old one.")
    import snapshots as sn
    sn.check_filesystem(new_root)
    files = [f for f in old_root.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    if usage(new_root)["total"] and usage(new_root)["free"] < total + 500_000_000:
        raise OSError(f"Not enough space on {drive_name(new_root)}: {human(total)} needed, {human(usage(new_root)['free'])} free.")
    new_root.mkdir(parents=True, exist_ok=True)
    done_bytes = 0
    log(f"Copying {len(files):,} files ({human(total)}) to {new_root}…")
    for f in files:
        rel = f.relative_to(old_root)
        dest = new_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        done_bytes += f.stat().st_size
        if progress and total:
            progress(90.0 * done_bytes / total)
    if verify:
        log("Checking the copy…")
        new_files = [f for f in new_root.rglob("*") if f.is_file()]
        if len(new_files) < len(files):
            raise OSError(f"The copy has {len(new_files):,} files, the original {len(files):,}; the original was kept.")
        for i, f in enumerate(files):
            dest = new_root / f.relative_to(old_root)
            if not dest.exists() or dest.stat().st_size != f.stat().st_size or _sha(dest) != _sha(f):
                raise OSError(f"{f.relative_to(old_root)} didn't copy correctly; the original was kept.")
            if progress and i % 50 == 0:
                progress(90.0 + 10.0 * i / max(1, len(files)))
    shutil.rmtree(old_root)
    if progress:
        progress(100.0)
    log("Done. The old copy has been removed.")
    return {"files": len(files), "bytes": total}
