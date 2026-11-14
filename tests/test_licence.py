"""Licence: PhoneKeep is GPL-3.0-or-later, and the built app carries LICENSE and THIRD_PARTY_NOTICES.md.

Checks:
- LICENSE is the GNU GPL version 3 text exactly as gnu.org publishes it;
- THIRD_PARTY_NOTICES.md names every library the app depends on (requirements.txt and everything they pull in, as
  installed here; IPython is left out of the build by the spec);
- the PyInstaller recipe and the Windows installer ship both files, and the About box says the licence and the source;
- the built app contains both files, unchanged: the app given with --built (build-mac.sh and GitHub's builds pass it),
  or else dist/PhoneKeep.app or dist/PhoneKeep when there is one.

    python tests/test_licence.py [--built dist/PhoneKeep.app | dist/PhoneKeep]
"""
import hashlib, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md")
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"   # gnu.org/licenses/gpl-3.0.txt
NOT_BUILT = {"ipython"}                     # the spec's excludes; what only it needs isn't built in either
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependencies() -> set:
    """Every installed distribution requirements.txt brings in on this computer."""
    import importlib.metadata as md
    from packaging.requirements import Requirement
    todo, seen = [], set()
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            r = Requirement(line)
            if r.marker is None or r.marker.evaluate():
                todo.append(r.name)
    while todo:
        n = todo.pop()
        if norm(n) in seen or norm(n) in NOT_BUILT:
            continue
        try:
            d = md.distribution(n)
        except md.PackageNotFoundError:
            continue
        seen.add(norm(n))
        for q in d.requires or []:
            r = Requirement(q)
            if r.marker is None or r.marker.evaluate({"extra": ""}):
                todo.append(r.name)
    return seen


def built_folder(built: Path) -> Path:
    """Where the data files are in a built app: Contents/Resources on a Mac, _internal next to the .exe otherwise."""
    if built.suffix == ".app":
        return built / "Contents" / "Resources"
    return built / "_internal" if (built / "_internal").is_dir() else built


def check_built(built: Path):
    where = built_folder(built)
    for f in FILES:
        p = where / f
        check(p.is_file(), f"the built app has {f} ({p.relative_to(built.parent)})")
        if p.is_file():
            check(p.read_bytes() == (ROOT / f).read_bytes(), f"{f} in the built app is the one in the repository")


# 1. the licence
lic = ROOT / "LICENSE"
check(lic.is_file() and hashlib.sha256(lic.read_bytes()).hexdigest() == GPL3_SHA256,
      "LICENSE is the GNU GPL v3 text from gnu.org, unchanged")

# 2. the notices
notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
listed = {norm(m) for m in re.findall(r"^\| \[([^\]]+)\]", notices, re.M)}
deps = dependencies()
missing = sorted(deps - listed)
check(len(deps) > 10 and not missing, f"THIRD_PARTY_NOTICES.md lists all {len(deps)} libraries the app depends on"
      + (f"; missing: {', '.join(missing)}" if missing else ""))
for name, licence in (("pymobiledevice3", "GPL-3.0-or-later"), ("pystray", "LGPL-3.0"), ("reportlab", "BSD-3-Clause"),
                      ("pillow", "MIT-CMU"), ("pillow_heif", "BSD-3-Clause"), ("libheif", "LGPL-3.0"),
                      ("pyobjc-core", "MIT"), ("iphone_backup_decrypt", "MIT")):
    check(re.search(rf"^\| \[{re.escape(name)}\]\([^)]*\) \|(?: [^|]* \|)? {re.escape(licence)}\b", notices, re.M | re.I)
          is not None, f"THIRD_PARTY_NOTICES.md: {name} under {licence}")
check("GPL-3.0-or-later" in notices and "trademarks of the author" in notices,
      "THIRD_PARTY_NOTICES.md says PhoneKeep's licence and that the name and logo are trademarks")

# 3. packaging, the About box and the README
spec = (ROOT / "packaging" / "PhoneKeep.spec").read_text()
check(all(f'"{f}"' in spec for f in FILES) and 'for f in ("LICENSE", "THIRD_PARTY_NOTICES.md")' in spec,
      "the PyInstaller recipe puts both files in the app")
iss = (ROOT / "packaging" / "PhoneKeep.iss").read_text()
for f in FILES:
    check(re.search(rf'^Source: "\.\.\\{re.escape(f)}"; DestDir: "\{{app\}}"', iss, re.M) is not None,
          f"the Windows installer puts {f} next to PhoneKeep.exe")
import app
about = app.about_lines()
check("Free software under the GNU GPL v3 · Source: github.com/aminyoutb007-hash/PhoneKeep" in about,
      "the About box says the licence and where the source is")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
check("## Licence" in readme and "GPL-3.0-or-later" in readme and
      '"PhoneKeep" and the PhoneKeep logo are trademarks of the author. They are not licensed under the GPL.' in readme,
      "README has a Licence section with the trademark note")

# 4. the built app
if "--built" in sys.argv:
    check_built(Path(sys.argv[sys.argv.index("--built") + 1]).resolve())
else:
    found = [p for p in (ROOT / "dist" / "PhoneKeep.app", ROOT / "dist" / "PhoneKeep") if p.is_dir()]
    if found:
        check_built(found[0])
    else:
        print("skip no built app in dist/ (build-mac.sh and GitHub's builds run this with --built)")

print()
print("FAILED: " + "; ".join(failures) if failures else "All licence checks passed.")
sys.exit(1 if failures else 0)
