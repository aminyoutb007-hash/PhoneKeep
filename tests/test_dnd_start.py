"""5.2.2: PhoneKeep opens even when drag-and-drop can't load.

tkinterdnd2 loads its tkdnd library only after the window is made, and raises "Unable to load tkdnd library." if it
can't (its Mac library needs macOS 14, so on macOS 11-13 the installed app didn't open at all). Now the window opens
without drag-and-drop, and the Open backup dialog no longer offers dropping a folder.

Runs each case in its own process (one Tk main window per process): "normal" and "no-tkdnd".
"""
import os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
DROP = "drop a backup folder"


def child(mode):
    sys.path.insert(0, str(HERE.parent))
    import shutil
    import keychain
    keychain.use_memory()
    import applock
    applock.use_backend(lambda: None, lambda reason: False)
    W = HERE / "work" / f"dnd-{mode}"
    shutil.rmtree(W, ignore_errors=True)
    W.mkdir(parents=True)
    if mode == "no-tkdnd":
        from tkinterdnd2 import TkinterDnD

        def cant_load(tkroot):                     # what tkinterdnd2 raises when the library won't load
            raise RuntimeError("Unable to load tkdnd library.")
        TkinterDnD._require = cant_load
    import phonekeep as wv
    import device as devmod
    import app as appmod
    appmod.SETTINGS_FILE = W / "settings.json"
    wv.list_devices = lambda: []

    class NoDevice:
        def __init__(self, *a, **k):
            raise wv.PhoneKeepError("no phone")
    devmod.LiveDevice = NoDevice
    a = appmod.App()                               # before the fix: RuntimeError here, no window
    a.withdraw()
    end = time.time() + 2
    while time.time() < end:
        a.update()
        time.sleep(0.02)
    d = appmod.OpenBackupDialog(a)
    a.update()
    texts = []

    def walk(w):
        for c in w.winfo_children():
            try:
                texts.append(str(c.cget("text")))
            except Exception:
                pass
            walk(c)
    walk(d)
    offers = any(DROP in t for t in texts)
    print(f"RESULT opened=1 dnd_ok={int(bool(getattr(a, 'dnd_ok', False)))} offers_drop={int(offers)}", flush=True)
    d.destroy()
    os._exit(0)                                    # the app's own threads don't need a tidy end here


if len(sys.argv) > 1:
    child(sys.argv[1])

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def run(mode):
    p = subprocess.run([sys.executable, __file__, mode], capture_output=True, text=True, timeout=120)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), "")
    if not line:
        print(p.stdout[-2000:], p.stderr[-3000:], sep="\n")
    return dict(kv.split("=") for kv in line.split()[1:]) if line else {}


r = run("no-tkdnd")
check(r.get("opened") == "1", "with tkdnd unable to load (macOS 11-13), PhoneKeep still opens its window")
check(r.get("dnd_ok") == "0", "  and knows drag-and-drop is off")
check(r.get("offers_drop") == "0", "  and the Open backup dialog doesn't offer dropping a folder")

r = run("normal")
check(r.get("opened") == "1", "normally PhoneKeep opens as before")
try:
    import tkinter
    from tkinterdnd2 import TkinterDnD
    t = TkinterDnD.Tk()
    loads = True
    t.destroy()
except Exception:
    loads = False
check(r.get("dnd_ok") == ("1" if loads else "0"),
      f"  drag-and-drop is on exactly when tkdnd loads here ({'loads' if loads else 'does not load'})")
check(r.get("offers_drop") == r.get("dnd_ok"), "  and the dialog offers dropping a folder only then")

print("\nDND START TESTS:", "PASS" if not failures else f"FAIL ({len(failures)})")
sys.exit(1 if failures else 0)
