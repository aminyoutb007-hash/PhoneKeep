"""S8: tamper check (docs/spec/04-security.md#s8-tamper-check).

Each snapshot gets a seal when it's made (seal.json next to its files.json): the SHA-256 of files.json and of the
four manifest files, and the size of every store blob it uses. Blobs are already named by their SHA-256 (B3), so
the seal adds no new hashing at backup time. The seal is signed (HMAC-SHA256) with a key PhoneKeep keeps in the
computer's keychain, so whoever can change the backup folder can't simply write a new seal.

Checks:
- fast, when a snapshot is opened: the signature, files.json, the manifest files, and every blob there at its size;
- full, on demand: the fast check, then every blob read again and compared with its name.
Dates aren't compared: moving backups to another drive (B4) changes them and would raise false alarms.

The menu bar helper never reads the keychain (a background keychain prompt on a Mac would be confusing): it writes
the seal unsigned, and the window signs it the next time it opens that phone. Which seals were signed is also noted
in PhoneKeep's own folder (seals.json), so a signed seal whose signature was simply removed is caught too.
Snapshots made before S8 get their seal the first time a window opens them.

Fast mode compares sizes, not dates (the spec said "sizes + dates"): copying backups to another drive (B4) and
some file systems (exFAT, network drives) change dates, which would raise the banner for nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

SEAL = "seal.json"
KEY_SERVICE = "PhoneKeep backup seal"
KEY_USER = "seal-key"
MANIFEST_FILES = ("Manifest.db", "Manifest.plist", "Info.plist", "Status.plist")

# where the signing key comes from: None in the helper and in tests' engine; the window sets keychain_key
key_source: Optional[Callable[[], Optional[bytes]]] = None


def _signed_file() -> Path:
    import phonekeep as wv
    return wv.DEFAULT_HOME / "seals.json"


def _seal_id(sdir: Path) -> str:
    return f"{sdir.parent.parent.name}/{sdir.name}"         # <UDID>/<snapshot id>


def _signed() -> set:
    try:
        return set(json.loads(_signed_file().read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def _note_signed(sdir: Path) -> None:
    try:
        ids = _signed() | {_seal_id(Path(sdir))}
        f = _signed_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(ids)), encoding="utf-8")
        tmp.replace(f)
    except OSError:
        pass


def keychain_key() -> Optional[bytes]:
    """The signing key from the keychain, made the first time (32 random bytes). None without a keychain."""
    try:
        import keychain
        kr = keychain._backend()
        k = kr.get_password(KEY_SERVICE, KEY_USER)
        if not k:
            k = secrets.token_hex(32)
            kr.set_password(KEY_SERVICE, KEY_USER, k)
            if kr.get_password(KEY_SERVICE, KEY_USER) != k:
                return None
        return bytes.fromhex(k)
    except Exception:
        return None


def _key() -> Optional[bytes]:
    try:
        return key_source() if key_source else None
    except Exception:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _body(seal: dict) -> bytes:
    """What the signature covers: everything in the seal but the signature, in one fixed order."""
    return json.dumps({k: v for k, v in seal.items() if k != "mac"}, sort_keys=True, separators=(",", ":")).encode()


def _store(snapshot_dir: Path) -> Path:
    return Path(snapshot_dir).parent.parent / "store"


def _blob(store: Path, sha: str) -> Path:
    return store / sha[:2] / sha


def make_seal(snapshot_dir: Path, files: dict, store: Optional[Path] = None) -> dict:
    """Write seal.json for a snapshot folder (signed if a key is at hand). `files`: its fileID -> sha256."""
    sdir = Path(snapshot_dir)
    store = store or _store(sdir)
    seal = {"version": 1,
            "files_json": _sha256(sdir / "files.json"),
            "manifest": {n: _sha256(sdir / n) for n in MANIFEST_FILES if (sdir / n).exists()},
            "sizes": {sha: _blob(store, sha).stat().st_size for sha in sorted(set(files.values()))}}
    key = _key()
    seal["mac"] = hmac.new(key, _body(seal), hashlib.sha256).hexdigest() if key else None
    (sdir / SEAL).write_text(json.dumps(seal), encoding="utf-8")
    return seal


def note_signed(sdir: Path) -> None:
    """After the snapshot folder has its final name: remember that its seal was signed."""
    try:
        if json.loads((Path(sdir) / SEAL).read_text(encoding="utf-8")).get("mac"):
            _note_signed(Path(sdir))
    except (OSError, ValueError, AttributeError):
        pass


def sign_pending(snapshot_dirs) -> int:
    """Sign the seals the helper left unsigned (window only). Returns how many were signed."""
    key = _key()
    if not key:
        return 0
    n = 0
    for d in snapshot_dirs:
        p = Path(d) / SEAL
        try:
            seal = json.loads(p.read_text(encoding="utf-8"))
            if seal.get("mac") is None:
                seal["mac"] = hmac.new(key, _body(seal), hashlib.sha256).hexdigest()
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(seal), encoding="utf-8")
                tmp.replace(p)
                _note_signed(Path(d))
                n += 1
        except (OSError, ValueError, AttributeError):
            continue
    return n


@dataclass
class Result:
    state: str                          # "ok", "changed", "no seal" (made before S8), "can't check"
    changed: list = field(default_factory=list)       # plain words: what differs
    checked: int = 0                    # blobs looked at

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def check(snapshot_dir: Path, full: bool = False, progress: Optional[Callable[[float], None]] = None,
          cancel: Callable[[], bool] = lambda: False) -> Result:
    """Fast (sizes) or full (contents) check of one snapshot against its seal."""
    sdir = Path(snapshot_dir)
    try:
        seal = json.loads((sdir / SEAL).read_text(encoding="utf-8"))
        sizes, manifest = dict(seal["sizes"]), dict(seal["manifest"])
    except FileNotFoundError:
        return Result("no seal")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return Result("changed", ["its seal can't be read"])
    changed = []
    key = _key()
    if seal.get("mac") is not None and key is not None:
        if not hmac.compare_digest(str(seal["mac"]), hmac.new(key, _body(seal), hashlib.sha256).hexdigest()):
            changed.append("its seal was rewritten")
    elif seal.get("mac") is None and _seal_id(sdir) in _signed():
        changed.append("its seal was rewritten")      # it was signed, and the signature was taken off
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
            return Result("can't check", ["stopped"], i)
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
    return Result("changed" if changed else "ok", changed, len(shas))


def banner_text(when) -> str:
    """The amber banner's words (spec): "This backup was changed after it was made on 3 Nov. It may not be reliable." """
    return f"This backup was changed after it was made on {when.day} {when.strftime('%b')}. It may not be reliable."
