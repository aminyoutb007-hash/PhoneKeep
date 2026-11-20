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
tamper._record_file = lambda: W / "seals.json"

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
check(set(seal) == {"version", "files_json", "manifest", "sizes", "key", "mac"} and seal["key"] == tamper.key_id(KEY)
      and seal["key"] != KEY.hex()[:16], "  the seal holds only hashes, sizes and which key signed it (not the key)")
check(tamper._seal_id(Path(s1.path)) in tamper._record(), "  and PhoneKeep's own folder records it")
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
      "a seal rewritten without the key (signature taken off): caught, because it no longer matches the record")

# deleted: once PhoneKeep made a seal, its going missing is a change, and opening doesn't seal it again
s = fresh("deleted")
flip_one_byte(Path(s.path) / "Manifest.db")
(Path(s.path) / tamper.SEAL).unlink()
check(tamper.check(s.path).changed == ["its seal is missing"], "a deleted seal: caught (its record is still there)")

# a backup taken to another computer, or the keychain reset: another key and no record -> can't check, no banner
s = fresh("othermac")
rec_before = tamper._record()
tamper._record_file = lambda: W / "seals-other-computer.json"      # this other computer has no record of it
tamper.key_source = lambda: bytes(reversed(range(32)))
r = tamper.check(s.path)
check(r.state == "can't check" and "another computer" in r.changed[0],
      f"a seal signed with another key, no record: \"can't check\", never the banner ({r.state}: {r.changed})")
blobs(s)[0].unlink()
check(tamper.check(s.path).state == "changed", "  but a missing file is still caught there")
tamper.key_source = lambda: KEY
tamper._record_file = lambda: W / "seals.json"
s = fresh("forged")
seal = json.loads((Path(s.path) / tamper.SEAL).read_text(encoding="utf-8"))
seal["sizes"][next(iter(seal["sizes"]))] += 1
seal["mac"] = "f" * 64
(Path(s.path) / tamper.SEAL).write_text(json.dumps(seal), encoding="utf-8")
check("its seal was rewritten" in tamper.check(s.path).changed, "a seal with a made-up signature: caught")
s = fresh("broken")
(Path(s.path) / tamper.SEAL).write_text("{not json", encoding="utf-8")
check(tamper.check(s.path).changed == ["its seal can't be read"], "a damaged seal: caught")

# the helper has no keychain: its seal is unsigned but recorded; the window signs it later
tamper.key_source = None
s = fresh("helper")
check(json.loads((Path(s.path) / tamper.SEAL).read_text(encoding="utf-8"))["mac"] is None
      and tamper._seal_id(Path(s.path)) in tamper._record(), "the menu bar helper's seal is unsigned, and recorded ...")
tamper.key_source = lambda: KEY
check(tamper.check(s.path).ok, "  and passes (nothing changed)")
check(tamper.sign_pending([s.path]) == 1 and tamper.check(s.path).ok
      and json.loads((Path(s.path) / tamper.SEAL).read_text(encoding="utf-8"))["mac"], "  until the window signs it")

# before the window signs it, someone changes a file and writes a matching unsigned seal: never signed, caught
tamper.key_source = None
s = fresh("helperforged")
with open(blobs(s)[0], "ab") as f:
    f.write(b"x")
tamper.make_seal(s.path, json.loads((Path(s.path) / "files.json").read_text(encoding="utf-8")))
tamper.key_source = lambda: KEY
check(tamper.sign_pending([s.path]) == 0
      and json.loads((Path(s.path) / tamper.SEAL).read_text(encoding="utf-8"))["mac"] is None,
      "an unsigned seal rewritten before the window opens it is never signed ...")
check(tamper.check(s.path).changed == ["its seal was rewritten"], "  and is caught")

# the record: two threads adding seals at once lose nothing; the key is made once
import threading
ids = [W / "Backups" / "00008030-S8REC" / "snapshots" / f"2026111{i}-000000" for i in range(8)]
ts = [threading.Thread(target=tamper._note, args=(d, {"version": 1, "n": i})) for i, d in enumerate(ids)]
[t.start() for t in ts]
[t.join() for t in ts]
check(all(tamper._seal_id(d) in tamper._record() for d in ids) and not list(W.glob("seals*.tmp"))
      and not (W / "seals.lock").exists(), "seals added at the same time are all recorded (a lock, own temporary files)")
# ... and two processes at once (the window and the menu bar helper); five rounds, as a lost write showed only now and
# then on Windows (5.2.2)
code = (f"import sys, os; sys.path.insert(0, {str(HERE.parent)!r}); import tamper, pathlib, time;"
        f"tamper._record_file = lambda: pathlib.Path({str(W / 'seals.json')!r});"
        "time.sleep(max(0, float(sys.argv[2]) - time.time()));"
        "[tamper._note(pathlib.Path('B') / 'U' / 'snapshots' / f'{sys.argv[1]}-{i}', {'n': i}) for i in range(25)]")
lost = []
for rnd in range(5):
    go = time.time() + 1.5
    tags = (f"window{rnd}", f"helper{rnd}")
    ps = [subprocess.Popen([sys.executable, "-c", code, tag, str(go)]) for tag in tags]
    [p.wait(60) for p in ps]
    rec = tamper._record()
    lost += [f"round {rnd + 1}: {50 - sum(f'U/{t}-{i}' in rec for t in tags for i in range(25))} lost"
             for _ in [0] if not all(f"U/{t}-{i}" in rec for t in tags for i in range(25))]
check(not lost, "seals added by two processes at the same time are all recorded, 5 rounds of 50"
      + (f": {'; '.join(lost)}" if lost else ""))
# ... and on Windows, where opening the lock while the other process deletes it raises PermissionError, and the record
# can be held open by a reader for a moment: the seal waits its turn instead of being dropped (5.2.2; a Windows CI flake)
real_open, real_replace, tries = tamper.os.open, Path.replace, {"open": 0, "replace": 0}


def busy_open(path, *a, **k):
    if str(path).endswith(".lock") and tries["open"] < 2:
        tries["open"] += 1
        raise PermissionError(13, "Access is denied", str(path))
    return real_open(path, *a, **k)


def busy_replace(self, target):
    if self.name.endswith(".tmp") and tries["replace"] < 30:      # longer than the old 20 tries
        tries["replace"] += 1
        raise PermissionError(13, "Access is denied", str(target))
    return real_replace(self, target)


tamper.os.open, Path.replace = busy_open, busy_replace
try:
    busy = W / "Backups" / "00008030-S8REC" / "snapshots" / "20261120-000000"
    tamper._note(busy, {"version": 1, "n": "busy"})
finally:
    tamper.os.open, Path.replace = real_open, real_replace
check(tries == {"open": 2, "replace": 30} and tamper._seal_id(busy) in tamper._record()
      and not list(W.glob("seals*.tmp")) and not (W / "seals.lock").exists(),
      "a busy lock or record (Windows: Access is denied for a moment) waits, and the seal is still recorded")
# ... and a record that can't be read for a moment is never written back empty (that wiped every earlier entry)
before = dict(tamper._record())
real_read, reads = Path.read_text, {"n": 0}


def flaky_read(self, *a, **k):
    if self.name == "seals.json" and reads["n"] < 1:
        reads["n"] += 1
        raise PermissionError(13, "Access is denied", str(self))
    return real_read(self, *a, **k)


Path.read_text = flaky_read
try:
    once = W / "Backups" / "00008030-S8REC" / "snapshots" / "20261121-000000"
    tamper._note(once, {"version": 1, "n": "once"})
finally:
    Path.read_text = real_read
rec = tamper._record()
check(reads["n"] == 1 and before and all(rec.get(k) == v for k, v in before.items()) and tamper._seal_id(once) in rec,
      f"a record read that fails once is tried again: the {len(before)} earlier entries stay and the new one is added")


def never_read(self, *a, **k):
    if self.name == "seals.json":
        raise OSError(5, "Input/output error", str(self))
    return real_read(self, *a, **k)


clock = iter([0.0] + [100.0] * 1000)                     # past the 10 s deadline at once: no 10 s wait in the test
real_time = tamper.time
tamper.time = type("T", (), {"time": staticmethod(lambda: next(clock)), "sleep": staticmethod(lambda s: None)})
Path.read_text = never_read
try:
    stuck = W / "Backups" / "00008030-S8REC" / "snapshots" / "20261122-000000"
    tamper._note(stuck, {"version": 1, "n": "stuck"})
finally:
    Path.read_text, tamper.time = real_read, real_time
rec2 = tamper._record()
check(rec2 == rec and tamper._seal_id(stuck) not in rec2 and not (W / "seals.lock").exists()
      and not list(W.glob("seals*.tmp")),
      "a record that can't be read at all is left as it is (nothing lost; that one seal isn't recorded)")
(W / "seals.json").write_text("{not json", encoding="utf-8")
fresh_one = W / "Backups" / "00008030-S8REC" / "snapshots" / "20261123-000000"
tamper._note(fresh_one, {"version": 1, "n": "fresh"})
check((W / "seals.damaged.json").read_text(encoding="utf-8") == "{not json"
      and list(tamper._record()) == [tamper._seal_id(fresh_one)],
      "a record that isn't JSON any more is kept as seals.damaged.json, and a new one is started")
(W / "seals.json").write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")       # as before, for what follows
(W / "seals.damaged.json").unlink()
made = []
_kb = keychain._backend
store = {}


class OnceKeychain:
    def get_password(self, svc, user):
        time.sleep(0.05)
        return store.get((svc, user))

    def set_password(self, svc, user, pw):
        made.append(pw)
        store[(svc, user)] = pw


keychain._backend = lambda: OnceKeychain()
tamper._key_cache.clear()
keys = []
ts = [threading.Thread(target=lambda: keys.append(tamper.keychain_key())) for _ in range(4)]
[t.start() for t in ts]
[t.join() for t in ts]
keychain._backend = _kb
tamper._key_cache.clear()
check(len(made) == 1 and len(set(keys)) == 1 and keys[0], "the keychain key is made once, even when asked for at once")

# moved to another drive (B4): dates change, nothing is reported
s = fresh("moved")
for p in blobs(s) + [Path(s.path) / n for n in ("Manifest.db", "files.json")]:
    os.utime(p, (time.time() - 86400 * 30, time.time() - 86400 * 30))
check(tamper.check(s.path).ok, "files with other dates only (a copy to another drive): no banner")

check(tamper.banner_text(MADE) == "This backup was changed after it was made on 3 Nov. It may not be reliable.",
      "the banner's words are the spec's")

# -- in the phone window ---------------------------------------------------------------------------------------
import app as appmod
from tkcompat import hide                                   # Tk 8.6 on a Mac: a withdrawn phone window hangs update()
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


def window(udid: str, seal_backups=True):
    check(a.open_backup(W / "Backups" / udid, udid=udid), f"  the snapshot opens in a phone window")
    w = a.phone_windows[-1]
    w.seal_backups = seal_backups
    hide(w)
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
w.banner("Saved 2 files to ~/Desktop.")
w.banner("")
check(banner(w).startswith("This backup was changed after it was made on 3 Nov")
      and str(w.bar_frame.cget("bg")) == str(appmod.theme.WARN_BG),
      "  another message (a save) comes and goes: the amber banner comes back")
w.destroy()

# the full check stops when the window closes, and a stopped check says nothing
r = tamper.check(sw.path, full=True, cancel=lambda: True)
check(r.state == "can't check" and r.changed == ["the check was stopped"], "a full check can be stopped")
u = "00008030-S8WINDOWSTOP0000"
sw = snapshot(u)
w = window(u)
asked, _check = [], tamper.check
tamper.check = lambda path, **k: asked.append(k) or Result_stopped
Result_stopped = tamper.Result("can't check", ["the check was stopped"])
told.clear()
w.check_backup_fully()
pump(lambda: asked, 20)
pump(lambda: False, 1)
tamper.check = _check
check(asked and asked[0].get("full") and asked[0]["cancel"]() is False and not told,
      "  the window's full check can be stopped, and a stopped check says nothing")
w.check_runner.alive = False
check(asked and asked[0]["cancel"]() is True, "  (it stops once the window's runners stop, as on closing)")
w.check_runner.alive = True
w.destroy()

# sealed on another computer (or the keychain was reset): "can't be sure", never the banner
u = "00008030-S8WINDOWOTHER000"
tamper.key_source = lambda: bytes(reversed(range(32)))
sw = snapshot(u)
tamper.key_source = lambda: KEY
rec = tamper._record()
rec.pop(tamper._seal_id(Path(sw.path)))
(W / "seals.json").write_text(json.dumps(rec), encoding="utf-8")
w = window(u)
check(w.tamper_state.state == "can't check" and banner(w) == "", "a backup sealed with another key opens with no banner")
told.clear()
w.check_backup_fully()
check(pump(lambda: told, 60) and told[0][0] == "info" and "can't be sure" in told[0][1] and banner(w) == "",
      f"  and its full check says PhoneKeep can't be sure, without the banner: {told}")
w.destroy()


def made_before_s8(snap):
    (Path(snap.path) / tamper.SEAL).unlink()
    rec = tamper._record()
    rec.pop(tamper._seal_id(Path(snap.path)))
    (W / "seals.json").write_text(json.dumps(rec), encoding="utf-8")

# made before S8: sealed when first opened; the helper's seal: signed when opened
u = "00008030-S8WINDOWOLD00000"
sw = snapshot(u)
made_before_s8(sw)
w = window(u)
check((Path(sw.path) / tamper.SEAL).exists() and w.tamper_state.ok and banner(w) == ""
      and tamper._seal_id(Path(sw.path)) in tamper._record(),
      "a snapshot made before S8 gets its seal (and record) when it's first opened (no banner)")
w.destroy()
u = "00008030-S8WINDOWREAD0000"
sw = snapshot(u)
made_before_s8(sw)
w = window(u, seal_backups=False)
check(not (Path(sw.path) / tamper.SEAL).exists() and w.tamper_state.state == "no seal",
      "with seal_backups off (real_check), opening writes nothing into the backup")
w.destroy()
u = "00008030-S8WINDOWHELPER00"
tamper.key_source = None
sw = snapshot(u)
tamper.key_source = lambda: KEY
w = window(u)
check(pump(lambda: json.loads((Path(sw.path) / tamper.SEAL).read_text(encoding="utf-8"))["mac"], 10),
      "the helper's unsigned seal is signed when a window opens the snapshot")
w.destroy()

# the record loses a snapshot's entry when PhoneKeep deletes the snapshot (Delete… or the automatic clean-up), and
# only then: a snapshot that is just missing (its drive unplugged) keeps it (it used to grow for ever)
gone = [snapshot("00008030-S8GONE", MADE + dt.timedelta(hours=h)) for h in range(5)]
ids_gone = [tamper._seal_id(Path(g.path)) for g in gone]
check(all(i in tamper._record() for i in ids_gone), "five more snapshots, all in the record")
sn.delete_snapshot(W / "Backups", "00008030-S8GONE", gone[0].id, to_trash=False)
removed = sn.prune(W / "Backups", "00008030-S8GONE", keep=3)
rec3 = tamper._record()
check(ids_gone[0] not in rec3 and all(tamper._seal_id(Path(sn.snapshots_dir(W / "Backups", "00008030-S8GONE") / r))
                                      not in rec3 for r in removed) and len(removed) == 1
      and all(i in rec3 for i in ids_gone if i.split("/")[1] not in removed + [gone[0].id]),
      f"a deleted snapshot and one the clean-up removed leave the record; the other three stay ({len(removed)} removed)")
away = Path(gone[-1].path)
away.rename(away.with_name("elsewhere"))
check(ids_gone[-1] in tamper._record(), "  a snapshot that is just missing keeps its entry")
away.with_name("elsewhere").rename(away)
before_bytes = (W / "seals.json").read_bytes()
tamper.forget(W / "Backups" / "00008030-S8GONE" / "snapshots" / "never-made")
check((W / "seals.json").read_bytes() == before_bytes and not (W / "seals.lock").exists(),
      "  forgetting one that isn't there writes nothing")

print("\nS8 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures))
sys.exit(1 if failures else 0)
