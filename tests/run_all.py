"""Run every test script in order; exits non-zero if any fails.

Usage (from the repository root):  python tests/run_all.py
Generated data goes to tests/work/ (ignored by git).
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    ("Full fake backup (every data type) + export", "test_full_backup.py"),
    ("WhatsApp Business backup", "make_biz.py"),
    ("Rich photo backup (months, Live Photo, video, thumbnails)", "make_rich.py"),
    ("Security: script injection, path escapes, spreadsheet formulas", "test_security.py"),
]
failed = []
for name, script in STEPS:
    print(f"\n=== {name} ({script})", flush=True)
    r = subprocess.run([sys.executable, str(HERE / script)], cwd=HERE.parent)
    if r.returncode:
        failed.append(script)
print("\nALL TESTS PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
