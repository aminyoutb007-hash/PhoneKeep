"""B4: backup location and moving backups (docs/spec/03-backup.md).

Done when:
  - Backups move to an external drive and still open afterwards (here: to another folder; copy, verify, remove old).
  - Unplugging the drive gives the "Connect…" message, not an error.
  - The Location screen shows the folder, the Show button and the "where is my data" line (checked in the window).
Plus: a failed copy keeps the old backups; the free-space warning wording; drive names; the helper waits
quietly for an unplugged drive.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import location as loc
import phonekeep as wv
import snapshots as sn

keychain.use_memory()

import applock

applock.use_backend(lambda: None, lambda reason: False)   # no Touch ID prompts in tests (S2 has its own)
W = HERE / "work" / "b4"
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


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
UD = "00008030-B4TEST"
old_root = W / "Backups"
shutil.copytree(fake, sn.current_dir(old_root, UD))
snap = sn.make_snapshot(old_root, UD)
check(sn.has_backup(old_root, UD), "a phone with a snapshot in the old location")

# the owner may pick the top of a drive that also holds their own files: those are never ours
theirs = old_root / "Holiday photos"
theirs.mkdir()
(theirs / "big.bin").write_bytes(b"\0" * 5_000_000)
(old_root / "notes.txt").write_text("mine")
check([d.name for d in loc.phone_dirs(old_root)] == [UD], f"only the phone folder counts as ours: {[d.name for d in loc.phone_dirs(old_root)]}")
check(loc.usage(old_root)["used"] < 5_000_000, "'Backups use' leaves the owner's own files out")

# -- moving: copy, verify, remove old -----------------------------------------------------------------------------
new_root = W / "External Drive" / "PhoneKeep Backups"
logs = []
r = loc.move_backups(old_root, new_root, log=logs.append)
check(r["files"] > 0 and not (old_root / UD).exists(), f"moved {r['files']} files; the old copy is gone only after the check")
check((theirs / "big.bin").exists() and (old_root / "notes.txt").exists() and not (new_root / "Holiday photos").exists(),
      "the owner's own files in the old folder are neither moved nor removed")
shutil.rmtree(theirs); (old_root / "notes.txt").unlink(); old_root.rmdir()

# a verified copy whose old copy can't be removed is still a successful move (found on NTFS through FUSE)
r2_old = W / "Flaky" / "root"
shutil.copytree(sn.phone_dir(new_root, UD), r2_old / UD)
real_rmtree = shutil.rmtree
shutil.rmtree = lambda p, ignore_errors=False, **k: None          # the driver 'loses' the delete
try:
    r2 = loc.move_backups(r2_old, W / "Flaky" / "dest", log=logs.append)
finally:
    shutil.rmtree = real_rmtree
check(r2["files"] == r["files"] and r2["left_behind"] == [str(r2_old / UD)] and sn.has_backup(W / "Flaky" / "dest", UD),
      "copy checked but old copy not removable: the move still succeeds and says what was left behind")
check(any("couldn't be fully removed" in l for l in logs), "and the log says so")
check(any("Checking the copy" in l for l in logs), "the copy was verified")
check(sn.has_backup(new_root, UD) and sn.list_snapshots(new_root, UD)[0].id == snap.id, "the snapshot is there in the new location")
reader = wv.BackupReader(sn.list_snapshots(new_root, UD)[0].path, None, lambda m: None)
check(reader.has_file("HomeDomain", "Library/SMS/sms.db"), "and it still opens (messages database readable from the store)")
reader.close()

# a failing move keeps the old copy
bad_root = W / "Bad"
shutil.copytree(new_root, bad_root)
real = loc._sha
loc._sha = lambda p: "x" if "Bad" not in str(p) else real(p)     # the copy 'differs'
try:
    loc.move_backups(bad_root, W / "Elsewhere")
    check(False, "a bad copy raises")
except OSError as e:
    check("original was kept" in str(e), f"a bad copy raises and says the original was kept: {e}")
finally:
    loc._sha = real
check(bad_root.exists() and sn.has_backup(bad_root, UD), "the old copy is untouched after a failed move")

# refuse moving into itself; refuse FAT32
try:
    loc.move_backups(new_root, new_root / "inside")
    check(False, "moving into the old folder refused")
except ValueError:
    check(True, "moving into the old folder refused")
real_check = sn.check_filesystem
sn.check_filesystem = lambda p, name=None: real_check(p, name="fat32")
try:
    loc.move_backups(new_root, W / "Stick")
    check(False, "FAT32 target refused")
except sn.FileSystemRefused as e:
    check("FAT32" in str(e), "FAT32 target refused with the spec's message")
finally:
    sn.check_filesystem = real_check

# -- the drive is unplugged: "Connect <drive> to back up.", not an error ----------------------------------------
if sys.platform == "darwin":
    gone = Path("/Volumes/Backup Drive/PhoneKeep")
    check(loc.drive_name(gone) == "Backup Drive" and not loc.is_available(gone), "Mac: unplugged volume detected")
elif os.name == "nt":
    gone = Path("Q:\\PhoneKeep")
    check(loc.drive_name(gone) == "Q:" and not loc.is_available(gone), "Windows: missing drive letter detected")
else:
    gone = Path("/media/amin/Backup Drive/PhoneKeep")
    check(loc.drive_name(gone) == "Backup Drive" and not loc.is_available(gone), "Linux: unplugged media detected")
check(loc.connect_message(gone).startswith("Connect ") and loc.connect_message(gone).endswith(" to back up."), f"wording: {loc.connect_message(gone)!r}")
wv.list_devices = lambda: [{"DeviceName": "Amin's iPhone", "UniqueDeviceID": UD, "ConnectionType": "USB"}]
wv.check_pmd3 = lambda: None
try:
    wv.make_backup(gone, UD, log=lambda m: None)
    check(False, "backup waits for the drive")
except wv.PhoneKeepError as e:
    check(e.key == "drive_unavailable" and str(e) == loc.connect_message(gone) and e.button == "Try again",
          f"backup waits with the Connect message and a Try again button: {e}")

# the main window shows it amber (waiting), not red (failed)
import errors
import app as appmod
pr = appmod.App.problem_of(wv.PhoneKeepError(loc.connect_message(gone), button="Try again", action=errors.TRY_AGAIN, key="drive_unavailable"))
check(pr.failure is False, "the window shows the Connect message as waiting (amber), not as a failure")

# the helper waits quietly: status line, no failure notification
import helper_core as hc
hc.SETTINGS_FILE = W / "settings.json"
hc.LOCK_FILE = W / "helper.lock"
notes = []
h = hc.Helper(notify=lambda t, m: notes.append((t, m)), backup_dir=gone)
h.devices = wv.list_devices()
h._backup(UD, "Amin's iPhone")
check(not notes and h.last_error == loc.connect_message(gone), f"helper: no notification, the menu line says {h.last_error!r}")
check(not gone.exists() and not Path(*gone.parts[:3]).exists(), "nothing was created on the unplugged drive's path")

# -- the free-space warning ----------------------------------------------------------------------------------------
w = loc.space_warning(W, needed=10**18)
check(w and w.startswith("Not enough space on ") and "needed" in w and "free." in w, f"space warning: {w!r}")
check(loc.space_warning(W, needed=1) is None, "no warning when there's room")
check(loc.estimate_needed(sn.current_dir(new_root, UD), None) >= 2_000_000_000, "incremental estimate is at least 2 GB")
check(loc.estimate_needed(None, 60_000_000_000) == 63_000_000_000, "first backup estimate ≈ the phone's used space")
check(loc.human(1_386_700_000_000) == "1.4 TB" and loc.human(53_900_000_000) == "53.9 GB" and loc.human(170_800_000) == "170.8 MB", "sizes read as MB / GB / TB")
u = loc.usage(new_root)
check(u["used"] > 0 and u["free"] > 0 and u["drive"], f"usage: backups use {loc.human(u['used'])}, {loc.human(u['free'])} free on {u['drive']}")

# -- the Location screen ------------------------------------------------------------------------------------------
try:
    import tkinter as tk
    import tempfile
    appmod.SETTINGS_FILE = W / "settings-app.json"
    wv.list_devices = lambda: []
    a = appmod.App()
    a.withdraw()
    a.s["backup_dir"] = str(new_root)
    a.open_settings()
    a.update()
    win = [w for w in a.winfo_children() if isinstance(w, appmod.SettingsWindow)][0]
    win.withdraw()
    import time
    t0 = time.time()
    while time.time() - t0 < 10 and "free on" not in win.loc_space.cget("text"):
        a.update(); time.sleep(0.02)
    check("PhoneKeep Backups" in win.loc_line.cget("text"), f"Location shows the folder: {win.loc_line.cget('text')!r}")
    check("Backups use" in win.loc_space.cget("text") and "free on" in win.loc_space.cget("text"), f"and the space line: {win.loc_space.cget('text')!r}")

    def texts(w):
        for c in w.winfo_children():
            if hasattr(c, "text"):
                yield c.text
            elif isinstance(c, tk.Label):
                yield c.cget("text")
            yield from texts(c)
    all_t = list(texts(win))
    check(any(t in ("Show in Finder", "Show folder") for t in all_t) and "Change…" in all_t, "Show and Change buttons present")
    check(any(t.startswith("🔒 Encrypted · stays on this computer") for t in all_t), "the 'where is my data' line")
    a.destroy()
except tk.TclError as e:
    print(f"(window checks skipped: no display: {e})")

print("\nB4 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
