"""run_all starts each test on a Mac through tests/_tk_start.py, so a test that was killed (macOS counts that as a
crash) can't leave the next test's tk.Tk() waiting on the "reopen its windows?" prompt. Here, without opening any
window: a script started through it sees what `python <script>` gives it, its exit code and errors come back, and
on a Mac the prompt is switched off for that process only (nothing in the Mac's settings)."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


PROBE = r'''
import json, sys
out = {"argv": sys.argv, "path0": sys.path[0], "name": __name__, "file": __file__,
       "main": sys.modules["__main__"].__dict__.get("MARK")}
if sys.platform == "darwin":
    from Foundation import NSUserDefaults
    d = NSUserDefaults.standardUserDefaults()
    out["ignore"] = bool(d.boolForKey_("ApplePersistenceIgnoreState"))
    out["kept"] = d.persistentDomainForName_("org.python.python") or {}
    out["kept"] = "ApplePersistenceIgnoreState" in out["kept"]
MARK = 1
print("PROBE " + json.dumps(out))
if "--fail" in sys.argv:
    raise SystemExit(3)
if "--raise" in sys.argv:
    raise ValueError("boom")
'''

with tempfile.TemporaryDirectory(prefix="pk_tkstart_") as tmp:
    probe = Path(tmp) / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")

    def run(*args, wrapped=True):
        cmd = [sys.executable, "-X", "faulthandler"] + ([str(HERE / "_tk_start.py")] if wrapped else []) + [str(probe), *args]
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE.parent)
        line = next((l for l in p.stdout.splitlines() if l.startswith("PROBE ")), None)
        return p.returncode, (json.loads(line[6:]) if line else None), p.stderr

    code_d, direct, _ = run("a", "--b", wrapped=False)
    code_w, wrapped, err = run("a", "--b")
    check(code_w == 0 and wrapped is not None, f"a script started through _tk_start.py runs ({err[-300:]!r})")
    if wrapped and direct:
        for k in ("argv", "path0", "name", "file"):
            check(wrapped[k] == direct[k], f"  its {k} is what `python <script>` gives it ({wrapped[k]!r})")
    check(run("--fail")[0] == 3, "  its exit code comes back")
    c, _o, e = run("--raise")
    check(c == 1 and "ValueError: boom" in e, "  and so does an error, with its traceback")
    if sys.platform == "darwin" and wrapped:
        check(wrapped.get("ignore") is True and direct.get("ignore") is False,
              "on a Mac it switches off the 'reopen windows?' prompt for that process only")
        check(wrapped.get("kept") is False, "  without writing it to the Mac's settings")

src = (HERE / "run_all.py").read_text(encoding="utf-8")
check('"_tk_start.py"' in src and 'sys.platform == "darwin"' in src, "run_all starts each test through it on a Mac")
check('"_tk_start.py"' in (HERE / "test_dnd_start.py").read_text(encoding="utf-8"),
      "  and so does the one test that opens a window in a child of its own (test_dnd_start)")

print("\nTK START TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
