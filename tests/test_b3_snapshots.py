"""B3: snapshots over time (docs/spec/03-backup.md).

Done when:
  - 5 backups on different days → 5 snapshots, total size well under 5 full copies.
  - Opening an older snapshot shows a message deleted on the phone since then.
  - A locked snapshot survives automatic clean-up.
  - An existing 4.x backup becomes snapshot 1, opens, and the old copy is gone only after verification;
    a simulated failure leaves it untouched.
  - A FAT32 drive is refused with the message above; an exFAT drive works.
Plus the format version, the five-field sidecar, garbage collection, rename, delete, and reading a
snapshot through the normal readers (export from an older snapshot).
"""
import datetime as dt, json, os, shutil, sqlite3, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

import phonekeep as wv
import sections as sx
import snapshots as sn

W = HERE / "work" / "b3"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


def folder_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
UD = "00008030-B3TEST"
BD = W / "Backups"
cur = sn.current_dir(BD, UD)
shutil.copytree(fake, cur)                      # the phone's live backup after the first run
full = folder_size(cur)

# -- 5 backups on different days, each changing one file ------------------------------------------------------
def change_messages(text: str, delete_rowid=None):
    """Simulate the phone: edit sms.db in the live backup (and bump its mtime)."""
    fid = next(r[0] for r in sqlite3.connect(cur / "Manifest.db").execute(
        "SELECT fileID FROM Files WHERE relativePath='Library/SMS/sms.db'"))
    db = cur / fid[:2] / fid
    c = sqlite3.connect(db)
    if delete_rowid:
        c.execute("DELETE FROM message WHERE ROWID=?", (delete_rowid,))
    else:
        cur_ = c.execute("INSERT INTO message(text, handle_id, date, is_from_me, service) VALUES (?,1,?,1,'iMessage')",
                         (text, int((dt.datetime(2026, 11, 12).timestamp() - wv.APPLE_EPOCH) * 1e9)))
        c.execute("INSERT INTO chat_message_join VALUES (1, ?)", (cur_.lastrowid,))
    c.commit(); c.close()
    os.utime(db, None)


days = [dt.datetime(2026, 11, d, 21, 0) for d in (8, 9, 10, 11, 12)]
s1 = sn.make_snapshot(BD, UD, when=days[0])
check(s1.id == "20261108-210000" and sn.read_format(sn.phone_dir(BD, UD)) == 1, "first snapshot made; format.json says 1")
side = json.loads((s1.path / "snapshot.json").read_text())
check(set(side) == {"date", "size", "ios", "name", "model"}, f"sidecar has exactly the five fields: {sorted(side)}")
check(side["name"] == "Amine's iPhone" and side["ios"] == "26.1" and side["model"] == "iPhone16,2", "sidecar values from the backup")
change_messages("Invoice 4471 sent")
s2 = sn.make_snapshot(BD, UD, when=days[1])
change_messages("Thanks, received")
s3 = sn.make_snapshot(BD, UD, when=days[2])
change_messages(None, delete_rowid=1)              # the phone's owner deleted "Did you land?"
s4 = sn.make_snapshot(BD, UD, when=days[3])
change_messages("See you Friday")
s5 = sn.make_snapshot(BD, UD, when=days[4])
snaps = sn.list_snapshots(BD, UD)
check([s.id for s in snaps] == [s5.id, s4.id, s3.id, s2.id, s1.id], "5 snapshots, newest first")
store_size = folder_size(sn.store_dir(BD, UD))
snap_meta = folder_size(sn.snapshots_dir(BD, UD))
check(store_size + snap_meta < 2.5 * full, f"5 snapshots (each changing the whole messages database) take {store_size + snap_meta:,} bytes vs {5 * full:,} for 5 full copies (one copy = {full:,})")
check([s.title for s in snaps][-1] == "8 Nov", f"titles: {[s.title for s in snaps]}")

# -- opening an older snapshot shows the deleted message ------------------------------------------------------
def messages_in(path):
    r = wv.BackupReader(path, None, lambda m: None)
    ctx = sx.Ctx(r, W / "out", lambda m: None, True, wv.backup_info(path))
    try:
        chats = sx.load_messages(ctx)
        return {m["text"] for c in chats for m in c["messages"] if m.get("text")}
    finally:
        r.close()


latest, older = messages_in(s5.path), messages_in(s3.path)
check("Did you land?" not in latest and "Did you land?" in older, "the message deleted on the phone is in the older snapshot and gone from the latest")
check("See you Friday" in latest and "See you Friday" not in older, "and the newest message only in the latest")
check(sn.latest_backup_path(BD, UD) == s5.path, "latest_backup_path is the newest snapshot")

# export from an older snapshot through the normal export
index = sx.export_all(s3.path, W / "Archive-s3", None, ["messages"], include_media=True, log=lambda m: None)
check(Path(index).exists(), "a full export from an older snapshot works through the store")

# -- lock survives clean-up; oldest unlocked goes first --------------------------------------------------------
sn.set_locked(BD, UD, s1.id, True)
removed = sn.prune(BD, UD, keep=3)
left = [s.id for s in sn.list_snapshots(BD, UD)]
check(s1.id in left and s2.id in removed and s3.id in removed and len(left) == 3, f"keep 3: locked first snapshot kept, the two oldest unlocked removed: left {left}")
check(sn.list_snapshots(BD, UD)[-1].locked, "lock shown on the snapshot")
# blobs nobody uses are gone, blobs still used are kept
used = set()
for s in sn.list_snapshots(BD, UD):
    used |= set(json.loads((s.path / "files.json").read_text()).values())
on_disk = {f.name for f in sn.store_dir(BD, UD).rglob("*") if f.is_file() and len(f.name) == 64}
check(on_disk == used, f"store holds exactly the blobs the remaining snapshots use ({len(on_disk)})")
check(sn.prune(BD, UD, keep=1) == [] or len(sn.list_snapshots(BD, UD)) >= 3, "keep is never below 3")

# rename and delete
sn.set_label(BD, UD, s5.id, "Before the holiday")
check(sn.list_snapshots(BD, UD)[0].title == "Before the holiday", "renamed snapshot shows its label")
sn.delete_snapshot(BD, UD, s4.id, to_trash=False)
check(s4.id not in [s.id for s in sn.list_snapshots(BD, UD)], "deleted snapshot gone")

# -- format version ----------------------------------------------------------------------------------------------
(sn.phone_dir(BD, UD) / "format.json").write_text(json.dumps({"format": 99}))
try:
    sn.make_snapshot(BD, UD, when=dt.datetime(2026, 11, 13, 21))
    check(False, "a newer format is refused")
except sn.FormatTooNew as e:
    check("newer PhoneKeep" in str(e), f"a newer format is refused: {e}")
(sn.phone_dir(BD, UD) / "format.json").write_text(json.dumps({"format": 1}))

# -- FAT32 refused, exFAT fine ------------------------------------------------------------------------------------
try:
    sn.check_filesystem(W, name="fat32")
    check(False, "FAT32 refused")
except sn.FileSystemRefused as e:
    check(str(e) == sn.FAT32_MESSAGE and "exFAT or APFS" in str(e), f"FAT32 refused with the spec's message")
for ok_fs in ("exfat", "apfs", "ntfs", "smbfs", "ext4", ""):
    sn.check_filesystem(W, name=ok_fs)
check(True, "exFAT, APFS, NTFS, network drives accepted")
check(isinstance(sn.filesystem_name(W), str), f"this computer's file system detected as {sn.filesystem_name(W)!r}")

# -- upgrading a 4.x backup -------------------------------------------------------------------------------------------
UD2 = "00008030-OLDTEST"
old = sn.phone_dir(BD, UD2)
shutil.copytree(fake, old)
old_size = folder_size(old)
old_names = sorted(p.name for p in old.iterdir())
check(sn.is_old_layout(old) and sn.latest_backup_path(BD, UD2) == old, "4.x layout recognised and still opens as is")
snap = sn.upgrade(BD, UD2)
check(snap is not None and sn.list_snapshots(BD, UD2)[0].id == snap.id, "upgrade made snapshot 1")
check(not (old / "Manifest.db").exists() and (sn.current_dir(BD, UD2) / "Manifest.db").exists(), "the old backup now lives under current/ (moved, not copied)")
check(sorted(p.name for p in sn.current_dir(BD, UD2).iterdir()) == old_names, "every file of the old backup is there")
check(messages_in(snap.path) == messages_in(sn.current_dir(BD, UD2)), "snapshot 1 reads the same as the backup")
check(sn.upgrade(BD, UD2) is None, "upgrade is a no-op the second time")

# a failing upgrade leaves the old backup untouched
UD3 = "00008030-FAILTEST"
old3 = sn.phone_dir(BD, UD3)
shutil.copytree(fake, old3)
before = sorted(str(p.relative_to(old3)) for p in old3.rglob("*"))
real = sn._sha256
sn._sha256 = lambda path: "0" * 64                     # every blob 'hashes' to one bogus value: the store can't hold it right
try:
    sn.upgrade(BD, UD3)
    check(False, "a failed conversion raises")
except OSError as e:
    check("nothing was changed" in str(e) or "missing from the store" in str(e) or "didn't match" in str(e), f"a failed conversion raises: {e}")
finally:
    sn._sha256 = real
after = sorted(str(p.relative_to(old3)) for p in old3.rglob("*") if "store" not in str(p) and "snapshots" not in str(p) and p.name != "format.json")
check((old3 / "Manifest.db").exists() and before == after, "the old backup is exactly as it was")

print("\nB3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
