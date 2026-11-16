"""No real names in the repo: the owner's surname and first name appear in no file git tracks.

The repo is public and its test data must be invented (owner, 16 Nov). This test doesn't contain the two words: it
keeps only their salted SHA-256 and compares the hash of every word in every tracked file (and every file's path):
- the surname anywhere, even inside a longer word (an email address, a joined-up name): every 5-letter stretch;
- the first name as a word of its own ("examine" and "determine" are fine).
Images and other binary files are read for their text bits (metadata) too.
A planted test word, kept the same way, proves the check finds a word inside a file, a longer word and a path.
History isn't checked: the owner chose not to rewrite it.

    python tests/test_no_owner_names.py
"""
import hashlib, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SALT = b"phonekeep-names:"
ANYWHERE = {"30a3a961a23ae15fb7af774ba8d5cb441176c4475cf915de00cb7523d177d86a"}   # the surname, 5 letters
WHOLE_WORD = {"1a8f580ec498af5e35b16ef05d6b0578a2bb234fe50d946d73eb152521b172f0"}  # the first name
PLANTED = "zqxjv"                                                                 # a made-up word for the self-check
PLANTED_HASH = "4d557dcdbdf7db92517b28b6b4794e9744a3b2706a1ad6ce846ef4f96aa76e54"
WINDOW = 5
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def h(word: str) -> str:
    return hashlib.sha256(SALT + word.encode()).hexdigest()


def found(text: str, anywhere: set, whole: set) -> bool:
    """True if a word of `whole` is a word of the text, or a word of `anywhere` is inside one."""
    words = set(re.findall(r"[a-z]+", text.casefold()))
    if any(h(w) in whole for w in words):
        return True
    parts = {w[i:i + WINDOW] for w in words if len(w) >= WINDOW for i in range(len(w) - WINDOW + 1)}
    return any(h(p) in anywhere for p in parts)


# the check itself, on a planted word kept only as its hash, like the real ones
check(h(PLANTED) == PLANTED_HASH, "the planted word's hash is the one kept")
check(found(f"a note: {PLANTED.title()} wrote", {PLANTED_HASH}, set()), "a word in a file is found, whatever its case")
check(found(f"mail: x{PLANTED}y@example.com", {PLANTED_HASH}, set()), "  inside a longer word too")
check(not found(f"mail: x{PLANTED}y@example.com", set(), {PLANTED_HASH}), "  a whole-word name inside a longer word isn't")
check(found(f"{PLANTED}'s iPhone", set(), {PLANTED_HASH}), "  a whole-word name on its own is")
check(found(f"tests/{PLANTED}_photo.png", {PLANTED_HASH}, set()), "  and in a file's path")
check(not found("examine, determine, famine; nothing here", ANYWHERE, WHOLE_WORD),
      "ordinary English words aren't taken for the names")

files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
files = [f for f in files if f]
check(len(files) > 100, f"every file git tracks is checked ({len(files)})")
bad = []
for f in files:
    p = ROOT / f
    try:
        data = p.read_bytes()
    except OSError:                         # removed in the working tree, not yet in git
        data = b""
    binary = b"\0" in data[:4096]          # images and the like: their text bits too (metadata)
    text = f + "\n" + data.decode("latin-1" if binary else "utf-8", "replace")
    if found(text, ANYWHERE, WHOLE_WORD):
        bad.append(f)
check(not bad, f"neither name is in any tracked file or path: {bad or 'none'}")

print("\nNO OWNER NAMES TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
