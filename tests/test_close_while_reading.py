"""Closing a phone window while it is still reading its backup (16 Nov: PhoneKeep crashed).

The home screen counts what's in the backup in the background. Closing the window closed the backup's database
under that read, and the read crashed the whole app (seen as a fatal error in tests/test_e5_all_phones.py).
Now closing waits for the read: checked with the tests' invented backup and a read made slow on purpose.
- closing during the read doesn't make the window wait;
- the read finishes with its answer; the files are let go right after it (`closed`);
- with nothing reading, closing lets go at once;
- after closing, a new read (a section, a file, the file list behind the V3 sizes and Save everything's
  estimate) says the backup was closed instead of touching it.
"""
import os, shutil, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

import keychain
keychain.use_memory()
import phonekeep as wv
import sections as sx
import phone

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

real_apps = sx.load_apps
started = threading.Event()


def slow_apps(ctx):
    started.set()
    time.sleep(1.0)
    return real_apps(ctx)          # reads the backup's database after the window was closed


sx.load_apps = slow_apps
d = phone.BackupData(fake, None)
got = {}
t = threading.Thread(target=lambda: got.update(n=d.count("apps")), daemon=True)
t.start()
started.wait(5)
t0 = time.perf_counter()
d.close()
took = time.perf_counter() - t0
check(took < 0.2 and not d.closed.is_set(), f"closing during a read doesn't wait for it ({took:.2f} s)")
t.join(10)
check(got.get("n") == "3", f"the read finishes with its answer, no crash: {got}")
check(d.closed.wait(5), "the backup's files are let go right after the read")
try:
    d.get("calls")
    check(False, "after closing, a new read says the backup was closed")
except wv.PhoneKeepError as e:
    check("closed" in str(e), "after closing, a new read says the backup was closed")
check(d.read("x", "y") is None and d.copy("x", "y", HERE / "work" / "nothing") is False, "  reading or copying a file too")
try:
    d.file_meta("CameraRollDomain", "Media/DCIM/")
    check(False, "  the backup's file list too (V3 sizes, Save everything's estimate)")
except wv.PhoneKeepError:
    check(True, "  the backup's file list too (V3 sizes, Save everything's estimate)")
import saveall_ui
check(saveall_ui.estimate_sizes(d, fake)["photos"] == 0, "  Save everything's estimate on a closed backup gives 0, no crash")
try:
    phone.PhoneWindow._backup_sizes(d)
    check(False, "  the V3 sizes on a closed backup stop with 'closed'")
except wv.PhoneKeepError:
    check(True, "  the V3 sizes on a closed backup stop with 'closed'")
sx.load_apps = real_apps

d3 = phone.BackupData(fake, None)
check(phone.PhoneWindow._backup_sizes(d3)[0] > 0 and saveall_ui.estimate_sizes(d3, fake)["photos"] > 0,
      "an open backup still gives the V3 sizes and the estimate, through the locked file list")
# the file list waits for a read in progress (it used to query the database without the lock)
src = (HERE.parent / "phone.py").read_text(encoding="utf-8")
check("data.reader" not in src.split("class PhoneWindow")[1].split("def _open_backup")[0]
      and "estimate_sizes(data, data.path)" in src, "the sizes and the estimate go through BackupData, not its reader")
d3.close()

d2 = phone.BackupData(fake, None)
d2.close()
check(d2.closed.is_set(), "with nothing reading, closing lets go at once")

print("\nCLOSE TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
