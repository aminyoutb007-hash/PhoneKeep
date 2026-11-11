"""Run every test script in order; exits non-zero if any fails.

Usage (from the repository root):  python tests/run_all.py
Generated data goes to tests/work/ (ignored by git).
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

# The app and its exports are UTF-8 everywhere; make Python on Windows read and print them that way too.
os.environ.setdefault("PYTHONUTF8", "1")

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
