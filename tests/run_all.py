"""Run every test script in order; exits non-zero if any fails.

Usage (from the repository root):  python tests/run_all.py
Generated data goes to tests/work/ (ignored by git).
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

# The app and its exports are UTF-8 everywhere; make Python on Windows read and print them that way too.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ["PHONEKEEP_NO_HELPER"] = "1"      # tests open the real window; it must not start a real helper

HERE = Path(__file__).resolve().parent
STEPS = [
    ("Full fake backup (every data type) + export", "test_full_backup.py", False),
    ("WhatsApp Business backup", "make_biz.py", False),
    ("Rich photo backup (months, Live Photo, video, thumbnails)", "make_rich.py", False),
    ("Security: script injection, path escapes, spreadsheet formulas", "test_security.py", False),
    ("Phone window with a simulated iPhone", "test_phone_window.py", True),   # needs a display
    ("S1: encryption by default, keychain, no password on command lines or in logs", "test_s1_encryption.py", True),
    ("S3: no network during backup + export + phone window", "test_s3_no_network.py", True),
    ("E3: plain-language errors, each situation reproduced", "test_e3_errors.py", True),
    ("B1: a running backup can be cancelled (engine, main window, guide, helper)", "test_b1_cancel.py", True),
    ("E1: first-run guide walked end to end with a stub iPhone", "test_e1_first_run.py", True),
    ("E2: menu bar / tray helper backs up and notifies with no window open", "test_e2_helper.py", True),
    ("B2: scheduled automatic backups with a fake clock", "test_b2_schedule.py", False),
    ("B3: snapshots over time, content store, upgrade, FAT32", "test_b3_snapshots.py", False),
    ("B4: backup location, moving backups, unplugged drive, free space", "test_b4_location.py", True),
    ("X2: backup redaction tool leaves nothing personal and still opens", "test_x2_redaction.py", False),
    ("B5: open any backup with no phone; All files preview and save", "test_b5_open_backup.py", True),
]
# On Linux (no desktop) the window tests run under a virtual display if xvfb-run is installed.
XVFB = [] if sys.platform in ("darwin", "win32") else (["xvfb-run", "-a"] if shutil.which("xvfb-run") else None)
# A script that hangs fails after this long (and faulthandler prints where it was stuck).
TIMEOUT = int(os.environ.get("PHONEKEEP_TEST_TIMEOUT", "420"))
failed = []
for name, script, needs_display in STEPS:
    print(f"\n=== {name} ({script})", flush=True)
    cmd = [sys.executable, "-X", "faulthandler", str(HERE / script)]
    if needs_display:
        if XVFB is None:
            print("skipped: no display (install xvfb to run it on Linux)", flush=True)
            continue
        cmd = XVFB + cmd
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=HERE.parent, timeout=TIMEOUT)
        code = r.returncode
    except subprocess.TimeoutExpired:
        print(f"TIMED OUT after {TIMEOUT} s", flush=True)
        code = 1
    print(f"--- {script}: {'ok' if not code else 'FAILED'} in {time.time() - t0:.0f} s", flush=True)
    if code:
        failed.append(script)
print("\nALL TESTS PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
