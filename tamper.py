"""S8: tamper check (docs/spec/04-security.md#s8-tamper-check).

Each snapshot gets a seal when it's made (seal.json next to its files.json): the SHA-256 of files.json and of the
four manifest files, and the size of every store blob it uses. Blobs are already named by their SHA-256 (B3), so
the seal adds no new hashing at backup time. Two things make a seal hard to replace:
- PhoneKeep's own folder (not the backup folder) keeps a record, seals.json, of every seal it made: the hash of
  the seal. A seal that was deleted or rewritten no longer matches it. The menu bar helper writes this record too,
  and a snapshot PhoneKeep deletes leaves it;
- the seal is signed (HMAC-SHA256) with a key PhoneKeep keeps in the computer's keychain, with the key's id, so
  a backup taken to another computer can still be checked against its signature when the record isn't there.
The menu bar helper never reads the keychain (a background keychain prompt on a Mac would be confusing): its seal
is unsigned, and the window signs it the next time it opens that snapshot, only if it still matches the record.

Checks:
- fast, when a snapshot is opened: the seal against the record and its signature, files.json, the manifest files,
  and every blob there at its size;
- full, on demand: the fast check, then every blob read again and compared with its name.
Dates aren't compared (the spec said "sizes + dates"): copying backups to another drive (B4) and some file systems
(exFAT, network drives) change dates, which would raise the banner for nothing.

A seal signed with another key (another computer, or the keychain was reset) can't be verified: "can't check",
never the banner. Snapshots made before S8 (no seal, not in the record) get their seal when a window opens them.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

SEAL = "seal.json"
KEY_SERVICE = "PhoneKeep backup seal"
KEY_USER = "seal-key"
MANIFEST_FILES = ("Manifest.db", "Manifest.plist", "Info.plist", "Status.plist")

# where the signing key comes from: None in the helper and in tests' engine; the window sets keychain_key
key_source: Optional[Callable[[], Optional[bytes]]] = None
_key_lock = threading.Lock()
_key_cache: dict = {}
_record_lock = threading.Lock()


def keychain_key() -> Optional[bytes]:
    """The signing key from the keychain, made the first time (32 random bytes). None without a keychain.
    Read once per run, behind a lock, so two threads never make two different keys."""
    with _key_lock:
        if "key" in _key_cache:
            return _key_cache["key"]
        key = None
        try:
            import keychain
            kr = keychain._backend()
            k = kr.get_password(KEY_SERVICE, KEY_USER)
            if not k:
                kr.set_password(KEY_SERVICE, KEY_USER, secrets.token_hex(32))
                k = kr.get_password(KEY_SERVICE, KEY_USER)      # what the keychain kept is the key
            key = bytes.fromhex(k) if k else None
        except Exception:
            key = None
        if key is not None:
            _key_cache["key"] = key
        return key


def _key() -> Optional[bytes]:
    try:
        return key_source() if key_source else None
    except Exception:
        return None


def key_id(key: bytes) -> str:
    """Which key signed a seal (not the key: a hash of it)."""
    return hashlib.sha256(b"phonekeep-seal-id:" + key).hexdigest()[:16]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _body(seal: dict) -> bytes:
    """What the signature and the record cover: the seal without its signature, in one fixed order."""
    return json.dumps({k: v for k, v in seal.items() if k not in ("mac", "key")}, sort_keys=True,
                      separators=(",", ":")).encode()


def _body_hash(seal: dict) -> str:
    return hashlib.sha256(_body(seal)).hexdigest()


def _store(snapshot_dir: Path) -> Path:
    return Path(snapshot_dir).parent.parent / "store"


def _blob(store: Path, sha: str) -> Path:
    return store / sha[:2] / sha


# -- the record of seals, in PhoneKeep's own folder ----------------------------------------------------------------

def _record_file() -> Path:
    import phonekeep as wv
    return wv.DEFAULT_HOME / "seals.json"


def _seal_id(sdir: Path) -> str:
    return f"{Path(sdir).parent.parent.name}/{Path(sdir).name}"         # <UDID>/<snapshot id>


def _record() -> dict:
    try:
        d = json.loads(_record_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_to_update(end: float) -> Optional[dict]:
    """The record as it is, for adding to it under the lock: {} only when there's none yet. A read that fails for a
    moment (Windows: a virus checker or a reader holding it) is tried again until `end`; if it still fails, None, so
    nothing is written and no earlier entry is lost. A record that isn't JSON any more is kept as seals.damaged.json
    and a new one is started (otherwise no seal could be recorded again)."""
    f = _record_file()
    while True:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except OSError:
            if time.time() > end:
                return None
            time.sleep(0.05)
            continue
        except ValueError:
            d = None
        if isinstance(d, dict):
            return d
        try:
            f.replace(f.with_name("seals.damaged.json"))
        except OSError:
            return None
        return {}


def _note(sdir: Path, seal: dict) -> None:
    """Add a seal to the record."""
    _change_record(lambda rec: rec.__setitem__(_seal_id(sdir), _body_hash(seal)) or True)


def forget(sdir: Path) -> None:
    """Drop a snapshot PhoneKeep deleted from the record (it only grew). Only for PhoneKeep's own deletes: a
    snapshot that is just missing (its drive unplugged, B4) keeps its entry, or it couldn't be checked later."""
    _change_record(lambda rec: rec.pop(_seal_id(sdir), None) is not None)


def _change_record(change: Callable[[dict], bool]) -> None:
    """Change the record with `change` (True: it changed, write it). One writer at a time: a thread lock here, a
    lock file across processes (the window and the menu bar helper), and each write through its own temporary
    file."""
    f = _record_file()
    lock = f.with_suffix(".lock")
    with _record_lock:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        end = time.time() + 10
        fd = None
        while fd is None:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):    # Windows: PermissionError while the other's is deleted
                try:
                    if time.time() - lock.stat().st_mtime > 30:      # left by a process that died
                        lock.unlink()
                        continue
                except OSError:
                    pass
                if time.time() > end:
                    return
                time.sleep(0.05)
            except OSError:
                return
        try:
            rec = _record_to_update(end)
            if rec is None or not change(rec):
                return                               # the record couldn't be read (leave it as it is), or no change
            tmp = f.with_name(f"seals.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")
            while True:                              # Windows: a reader may have it open for a moment
                try:
                    tmp.replace(f)
                    break
                except PermissionError:
                    if time.time() > end:
                        tmp.unlink()
                        break
                    time.sleep(0.05)
        except OSError:
            pass
        finally:
            os.close(fd)
            try:
                lock.unlink()
            except OSError:
                pass


def _write(path: Path, seal: dict) -> None:
    tmp = path.with_name(f"{SEAL}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(seal), encoding="utf-8")
    tmp.replace(path)


def make_seal(snapshot_dir: Path, files: dict, store: Optional[Path] = None) -> dict:
    """Write seal.json for a snapshot folder (signed if a key is at hand). `files`: its fileID -> sha256."""
    sdir = Path(snapshot_dir)
    store = store or _store(sdir)
    seal = {"version": 1,
            "files_json": _sha256(sdir / "files.json"),
            "manifest": {n: _sha256(sdir / n) for n in MANIFEST_FILES if (sdir / n).exists()},
            "sizes": {sha: _blob(store, sha).stat().st_size for sha in sorted(set(files.values()))}}
    key = _key()
    seal["key"] = key_id(key) if key else None
    seal["mac"] = hmac.new(key, _body(seal), hashlib.sha256).hexdigest() if key else None
    _write(sdir / SEAL, seal)
    return seal


def note_made(sdir: Path) -> None:
    """After the snapshot folder has its final name: add its seal to the record."""
    try:
        _note(Path(sdir), json.loads((Path(sdir) / SEAL).read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError):
        pass


def sign_pending(snapshot_dirs) -> int:
    """Sign the seals the helper left unsigned (window only), only if each still matches the record (a seal
    rewritten meanwhile is never signed). Returns how many were signed."""
    key = _key()
    if not key:
        return 0
    rec = _record()
    n = 0
    for d in snapshot_dirs:
        p = Path(d) / SEAL
        try:
            seal = json.loads(p.read_text(encoding="utf-8"))
            if seal.get("mac") is None and rec.get(_seal_id(Path(d))) == _body_hash(seal):
                seal["key"] = key_id(key)
                seal["mac"] = hmac.new(key, _body(seal), hashlib.sha256).hexdigest()
                _write(p, seal)
                n += 1
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return n


@dataclass
class Result:
    state: str                          # "ok", "changed", "no seal" (made before S8), "can't check"
    changed: list = field(default_factory=list)       # plain words: what differs, or why it can't be checked
    checked: int = 0                    # blobs looked at

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def check(snapshot_dir: Path, full: bool = False, progress: Optional[Callable[[float], None]] = None,
          cancel: Callable[[], bool] = lambda: False) -> Result:
    """Fast (sizes) or full (contents) check of one snapshot against its seal."""
    sdir = Path(snapshot_dir)
    recorded = _record().get(_seal_id(sdir))
    try:
        seal = json.loads((sdir / SEAL).read_text(encoding="utf-8"))
        sizes, manifest = dict(seal["sizes"]), dict(seal["manifest"])
    except FileNotFoundError:
        return Result("changed", ["its seal is missing"]) if recorded else Result("no seal")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return Result("changed", ["its seal can't be read"])
    changed, unsure = [], []
    key = _key()
    if recorded is not None and recorded != _body_hash(seal):
        changed.append("its seal was rewritten")
    if seal.get("mac") is not None:
        if key is not None and seal.get("key") == key_id(key):
            if not hmac.compare_digest(str(seal["mac"]), hmac.new(key, _body(seal), hashlib.sha256).hexdigest()):
                changed.append("its seal was rewritten")
        elif recorded is None:
            unsure.append("it was sealed on another computer (or this computer's keychain was reset)")
    elif recorded is None:
        unsure.append("its seal isn't signed and PhoneKeep has no record of making it")
    changed = list(dict.fromkeys(changed))
    try:
        if _sha256(sdir / "files.json") != seal.get("files_json"):
            changed.append("its list of files")
        files = json.loads((sdir / "files.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Result("changed", changed + ["its list of files can't be read"])
    for n in MANIFEST_FILES:
        p = sdir / n
        if (n in manifest) != p.exists() or (p.exists() and _sha256(p) != manifest.get(n)):
            changed.append(n)
    if set(files.values()) - set(sizes):
        changed.append("files not in its seal")
    store = _store(sdir)
    missing = wrong_size = wrong_content = 0
    shas = sorted(sizes)
    for i, sha in enumerate(shas):
        if cancel():
            return Result("can't check", ["the check was stopped"], i)
        p = _blob(store, sha)
        try:
            st = p.stat()
        except OSError:
            missing += 1
            continue
        if st.st_size != sizes[sha]:
            wrong_size += 1
        elif full and _sha256(p) != sha:
            wrong_content += 1
        if progress and i % 200 == 0:
            progress(100.0 * i / max(1, len(shas)))
    if missing:
        changed.append(f"{missing:,} file{'s' if missing != 1 else ''} missing")
    if wrong_size:
        changed.append(f"{wrong_size:,} file{'s' if wrong_size != 1 else ''} with another size")
    if wrong_content:
        changed.append(f"{wrong_content:,} file{'s' if wrong_content != 1 else ''} with other contents")
    if progress:
        progress(100.0)
    if changed:
        return Result("changed", changed, len(shas))
    return Result("can't check", unsure, len(shas)) if unsure else Result("ok", [], len(shas))


def banner_text(when) -> str:
    """The amber banner's words (spec): "This backup was changed after it was made on 3 Nov. It may not be reliable." """
    return f"This backup was changed after it was made on {when.day} {when.strftime('%b')}. It may not be reliable."
