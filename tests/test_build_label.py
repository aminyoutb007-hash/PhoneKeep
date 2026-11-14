"""packaging/build-mac.sh puts the committed build_label.py back with git after a build, also when the build fails.

It used to rewrite the file as a bare `BUILD_LABEL = ""`, dropping its docstring and leaving the file modified
after every local build (found after the 5.0.1 release). The script's own label lines run here in a throwaway
git repository, with PyInstaller and codesign stood in for by `true` (a build that works) or `false` (one that fails).
"""
import os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def find_bash():
    """bash to run the script's lines with. On Windows, Git's own (Git Bash): the bash.exe on PATH there is often
    WSL's, which only asks to install a Linux distribution."""
    if sys.platform == "win32":
        git = shutil.which("git")                  # ...\Git\cmd\git.exe
        root = Path(git).resolve().parents[1] if git else None
        for c in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe") if root else ():
            if c.is_file():
                return str(c)
        return None
    return shutil.which("bash")


BASH = find_bash()
if BASH is None or shutil.which("git") is None:
    print("(skipped: needs bash and git)")
    sys.exit(0)


def remove(folder: Path):
    """rmtree that also removes git's read-only object files (Windows won't delete those as they are)."""
    def writable(func, path, _exc):
        os.chmod(path, 0o700)
        func(path)
    if folder.exists():
        shutil.rmtree(folder, onexc=writable)

script = (ROOT / "packaging" / "build-mac.sh").read_text(encoding="utf-8").splitlines()
start = next((i for i, l in enumerate(script) if l.startswith("trap ") and "build_label.py" in l), None)
end = next((i for i, l in enumerate(script) if l.startswith("git checkout -- build_label.py")), None)
check(start is not None and end is not None and start < end,
      "the script restores build_label.py with git checkout, on exit too (trap)")
if start is None or end is None:
    print("\nBUILD LABEL TESTS: FAIL")
    sys.exit(1)
block = script[start:end + 1]
check(not any(re.match(r"printf 'BUILD_LABEL = \"\"", l) for l in script),
      "the script no longer writes an empty label over the committed file")
committed = (ROOT / "build_label.py").read_text(encoding="utf-8")


def run(stand_in: str) -> tuple[int, str]:
    repo = HERE / "work" / "build_label_repo"
    remove(repo)
    repo.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    (repo / "build_label.py").write_text(committed, encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "build_label.py"], ["commit", "-qm", "c"]):
        subprocess.run(["git", *cmd], cwd=repo, env=env, check=True)
    body = [re.sub(r'^(?:"\$V"|codesign) .*', stand_in, l) for l in block]
    sh = "set -e\nV=python\nLABEL=5.1-dev+H1-local\n" + "\n".join(body) + "\n"
    r = subprocess.run([BASH, "-c", sh], cwd=repo, env=env)
    return r.returncode, (repo / "build_label.py").read_text(encoding="utf-8")


code, after = run("true")
check(code == 0 and after == committed, "after a build, build_label.py is the committed file again, docstring and all")
code, after = run("false")
check(code != 0 and after == committed, "after a failed build too")
remove(HERE / "work" / "build_label_repo")

print("\nBUILD LABEL TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
