"""S8: tamper check (docs/spec/04-security.md#s8-tamper-check).

Done when: "Editing one byte of a backup file triggers the banner on the full check."
- each snapshot gets a seal when it's made (file hashes, sizes), signed with a key from the keychain (here an invented
  key in memory: tests never touch the real keychain);
- the fast check (when a snapshot opens) catches a file with another size, a missing file, a changed manifest or list
  of files, and a seal that was rewritten or had its signature taken off;
- the full check (⋯ → Check for changes…) also catches one byte changed inside a file of the same size;
- in the phone window: the amber banner, in the spec's words, with the snapshot's date;
- snapshots made before S8 get their seal when a window opens them; the helper's unsigned seal is signed then.
"""
import datetime as dt, json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
import snapshots as sn
import tamper

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
W = HERE / "work" / "s8"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
tamper._signed_file = lambda: W / "seals.json"

KEY = bytes(range(32))                     # an invented key: the real one lives in the keychain
tamper.key_source = lambda: KEY
MADE = dt.datetime(2026, 11, 3, 21, 4)


def snapshot(udid: str, when=MADE) -> sn.Snapshot:
    return sn.make_snapshot(W / "Backups", udid, source=fake, when=when)


def blobs(snap) -> list:
    store = Path(snap.path).parent.parent / "store"
    files = json.loads((Path(snap.path) / "files.json").read_text(encoding="utf-8"))
    return [store / sha[:2] / sha for sha in sorted(set(files.values()))]


def flip_one_byte(p: Path) -> None:
    b = bytearray(p.read_bytes())
    b[len(b) // 2] ^= 0x01
    p.write_bytes(bytes(b))


# -- the seal ------------------------------------------------------------------------------------------------
s1 = snapshot("00008030-S8SEAL0000000000")
seal = json.loads((Path(s1.path) / tamper.SEAL).read_text(encoding="utf-8"))
check(seal.get("mac") and len(seal["sizes"]) == len(blobs(s1)) and "Manifest.db" in seal["manifest"],
      f"each new snapshot has a signed seal: its {len(seal['sizes'])} files' sizes, the manifest and the list of files")
check(set(seal) == {"version", "files_json", "manifest", "sizes", "mac"},
      "  the seal holds only hashes and sizes (nothing from inside the backup)")
check(tamper._seal_id(Path(s1.path)) in tamper._signed(), "  and PhoneKeep notes that it signed it")
r = tamper.check(s1.path)
check(r.ok and r.checked == len(blobs(s1)), f"an untouched snapshot passes the fast check ({r.state}, {r.changed})")
check(tamper.check(s1.path, full=True).ok, "  and the full check")

# -- Done when: one byte changed ---------------------------------------------------------------------------------
target = max(blobs(s1), key=lambda p: p.stat().st_size)
flip_one_byte(target)
r_fast, r_full = tamper.check(s1.path), tamper.check(s1.path, full=True)
check(r_fast.ok, "one byte changed in a file (same size): the fast check can't see it (sizes only) ...")
check(r_full.state == "changed" and r_full.changed == ["1 file with other contents"],
      f"  but the full check does: {r_full.changed}")

# -- what the fast check catches -------------------------------------------------------------------------------
def fresh(name: str) -> sn.Snapshot:
    return snapshot("00008030-S8" + name.upper().ljust(14, "0"))


s = fresh("size")
with open(blobs(s)[0], "ab") as f:
    f.write(b"x")
check(tamper.check(s.path).changed == ["1 file with another size"], "a file with another size: caught on opening")
s = fresh("gone")
blobs(s)[0].unlink()
check(tamper.check(s.path).changed == ["1 file missing"], "a missing file: caught on opening")
s = fresh("manifest")
with open(Path(s.path) / "Manifest.plist", "ab") as f:
    f.write(b" ")
check("Manifest.plist" in tamper.check(s.path).changed, "a changed manifest file: caught on opening")
s = fresh("list")
files = json.loads((Path(s.path) / "files.json").read_text(encoding="utf-8"))
fid = next(iter(files))
files[fid] = "0" * 64
(Path(s.path) / "files.json").write_text(json.dumps(files), encoding="utf-8")
got = tamper.check(s.path).changed
check("its list of files" in got and "files not in its seal" in got, f"a changed list of files: caught ({got})")

# a new seal written by someone without the key
s = fresh("reseal")
flip_one_byte(Path(s.path) / "Manifest.db")
tamper.key_source = lambda: None                    # whoever changed it has no key
tamper.make_seal(s.path, json.loads((Path(s.path) / "files.json").read_text(encoding="utf-8")))
tamper.key_source = lambda: KEY
check(tamper.check(s.path).changed == ["its seal was rewritten"],
      "a seal rewritten without the key (signature taken off): caught, because PhoneKeep noted it had signed it")
s = fresh("forged")
seal = json.loads((Path(s.path) / tamper.SEAL).read_text(encoding="utf-8"))
seal["sizes"][next(iter(seal["sizes"]))] += 1
seal["mac"] = "f" * 64
(Path(s.path) / tamper.SEAL).write_text(json.dumps(seal), encoding="utf-8")
check("its seal was rewritten" in tamper.check(s.path).changed, "a seal with a made-up signature: caught")
s = fresh("broken")
(Path(s.path) / tamper.SEAL).write_text("{not json", encoding="utf-8")
check(tamper.check(s.path).changed == ["its seal can't be read"], "a damaged seal: caught")

# the helper has no keychain: its seal is unsigned, the window signs it later
tamper.key_source = None
s = fresh("helper")
check(json.loads((Path(s.path) / tamper.SEAL).read_text(encoding="utf-8"))["mac"] is None
      and tamper._seal_id(Path(s.path)) not in tamper._signed(), "the menu bar helper's seal is unsigned ...")
tamper.key_source = lambda: KEY
check(tamper.check(s.path).ok, "  and passes (nothing changed)")
check(tamper.sign_pending([s.path]) == 1 and tamper.check(s.path).ok
      and tamper._seal_id(Path(s.path)) in tamper._signed(), "  until the window signs it")

# moved to another drive (B4): dates change, nothing is reported
s = fresh("moved")
for p in blobs(s) + [Path(s.path) / n for n in ("Manifest.db", "files.json")]:
    os.utime(p, (time.time() - 86400 * 30, time.time() - 86400 * 30))
check(tamper.check(s.path).ok, "files with other dates only (a copy to another drive): no banner")

check(tamper.banner_text(MADE) == "This backup was changed after it was made on 3 Nov. It may not be reliable.",
      "the banner's words are the spec's")

# -- in the phone window ---------------------------------------------------------------------------------------
import app as appmod
import device as devmod
from tkinter import messagebox


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
appmod.SETTINGS_FILE = W / "settings.json"
told = []
messagebox.showinfo = lambda *a, **k: told.append(("info", a[1] if len(a) > 1 else k.get("message")))
messagebox.showwarning = lambda *a, **k: told.append(("warning", a[1] if len(a) > 1 else k.get("message")))
a = appmod.App()
a.withdraw()
a.after_cancel(a._timers.pop("first"))
check(tamper.key_source() == KEY, "with PHONEKEEP_HOME set (tests), PhoneKeep doesn't use the real keychain's key")
a.s["backup_dir"] = str(W / "Backups")


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


def window(udid: str):
    check(a.open_backup(W / "Backups" / udid, udid=udid), f"  the snapshot opens in a phone window")
    w = a.phone_windows[-1]
    w.withdraw()
    pump(lambda: w.data is not None and w.tamper_state is not None, 90)
    return w


def banner(w) -> str:
    return w.bar_text.cget("text") if w.bar_frame.winfo_manager() else ""     # packed (the window is hidden)


u = "00008030-S8WINDOW00000000"
sw = snapshot(u)
w = window(u)
check(w.tamper_state.ok and banner(w) == "", "an untouched backup opens with no banner")
flip_one_byte(max(blobs(sw), key=lambda p: p.stat().st_size))
w.check_backup_fully()
check(pump(lambda: told, 120), "⋯ → Check for changes… reads every file again ...")
check(banner(w) == "This backup was changed after it was made on 3 Nov. It may not be reliable."
      and str(w.bar_frame.cget("bg")) == str(appmod.theme.WARN_BG),
      f"  one byte changed: the amber banner (Done when): {banner(w)!r}")
check(told and told[0][0] == "warning" and "1 file with other contents" in told[0][1], f"  and what differs: {told}")
# the snapshot's ⋯ menu offers it
popped = []
appmod.tk.Menu.tk_popup = lambda self, x, y: popped.append(self)
told.clear()
w._snapshot_menu(type("E", (), {"x_root": 0, "y_root": 0})(), w.snaps[0])
check(popped and popped[-1].entrycget(0, "label") == "Check for changes…", "the snapshot's ⋯ menu offers Check for changes…")
popped[-1].invoke(0)
check(pump(lambda: told, 120) and told[0][0] == "warning", "  which runs the same full check")
w.destroy()

u = "00008030-S8WINDOWSIZE0000"
sw = snapshot(u)
with open(blobs(sw)[0], "ab") as f:
    f.write(b"x")
w = window(u)
check(w.tamper_state.state == "changed" and banner(w).startswith("This backup was changed after it was made on 3 Nov"),
      f"a file with another size: the banner as soon as the snapshot opens: {banner(w)!r}")
w.destroy()

# made before S8: sealed when first opened; the helper's seal: signed when opened
u = "00008030-S8WINDOWOLD00000"
sw = snapshot(u)
(Path(sw.path) / tamper.SEAL).unlink()
w = window(u)
check((Path(sw.path) / tamper.SEAL).exists() and w.tamper_state.ok and banner(w) == "",
      "a snapshot made before S8 gets its seal when it's first opened (no banner)")
w.destroy()
u = "00008030-S8WINDOWHELPER00"
tamper.key_source = None
sw = snapshot(u)
tamper.key_source = lambda: KEY
w = window(u)
check(pump(lambda: json.loads((Path(sw.path) / tamper.SEAL).read_text(encoding="utf-8"))["mac"], 10),
      "the helper's unsigned seal is signed when a window opens the snapshot")
w.destroy()

print("\nS8 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures))
sys.exit(1 if failures else 0)
