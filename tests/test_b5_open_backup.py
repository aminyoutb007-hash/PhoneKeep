"""B5: open any backup and browse its files (docs/spec/03-backup.md).

Done when:
  - A Finder-made encrypted backup opens and its Messages appear (the encrypted part is the owner's on-device
    check; here a Finder-style unencrypted folder, and a PhoneKeep snapshot, open with NO phone connected).
  - A single file can be previewed and saved from All files (saved with its folder structure).
Plus: the Open backup dialog lists what PhoneKeep finds; a folder that isn't a backup is refused in plain words;
a stored password is used silently; the window title and header say which backup is open.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phonekeep as wv
import snapshots as sn

keychain.use_memory()

import applock

applock.use_backend(lambda: None, lambda reason: False)   # no Touch ID prompts in tests (S2 has its own)
W = HERE / "work" / "b5"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

# a Finder-style backup: a folder named by UDID in MobileSync's layout, no PhoneKeep files at all
finder_root = W / "MobileSync" / "Backup"
finder = finder_root / "00008030-FINDERTEST0000000000000000"
shutil.copytree(fake, finder)
# and a PhoneKeep phone folder with a snapshot
BD = W / "Backups"
UD = "00008030-B5TEST"
shutil.copytree(fake, sn.current_dir(BD, UD))
snap = sn.make_snapshot(BD, UD)

import tkinter as tk
import app as appmod
import phone
import device as devmod

appmod.SETTINGS_FILE = W / "settings.json"
wv.list_devices = lambda: []                       # no phone connected at all (journey J5)


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
a = appmod.App()
a.withdraw()
a.s["backup_dir"] = str(BD)
a.s["archive_dir"] = str(W / "Archive")


def pump(until, timeout=60, what=""):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    print(f"timed out waiting for {what}", flush=True)
    return False


def labels(widget):
    out = []
    for c in widget.winfo_children():
        if isinstance(c, tk.Label):
            out.append(c)
        out.extend(labels(c))
    return out


# -- open a Finder backup with no phone -------------------------------------------------------------------------
check(a.open_backup(finder), "a Finder-made backup folder opens")
win = a.phone_windows[-1]
win.withdraw()
check(win.live_wanted is False and win.udid == finder.name, "opened for browsing: no live phone, UDID from the folder name")
check("Amine's iPhone" in win.title() and "no iPhone connected" in win.sub.cget("text"), f"title and header name the backup: {win.sub.cget('text')!r}")
backup_apps = [k for k, *_r, where in phone.APPS if where == "backup"]
check(pump(lambda: all(k in win.counts for k in backup_apps), 90, "counts"), "home screen counts fill in from the Finder backup")
win.open_app("messages")
pump(lambda: not any(l.cget("text") == "Loading…" for l in labels(win.content)), 60, "messages")
texts = [l.cget("text") for l in labels(win.content)]
check(any("chats" in t and "messages" in t for t in texts), f"Messages appear: {win.view_sub.cget('text')!r}")

# -- All files: preview and save a single file --------------------------------------------------------------------
win.open_app("allfiles")
pump(lambda: not any(l.cget("text") == "Loading…" for l in labels(win.content)), 60, "all files")
check("areas" in win.view_sub.cget("text") and "file" in win.view_sub.cget("text"), f"All files screen: {win.view_sub.cget('text')!r}")


def find_tree(widget):
    from tkinter import ttk
    for c in widget.winfo_children():
        if isinstance(c, ttk.Treeview):
            return c
        t = find_tree(c)
        if t:
            return t
    return None


tree = find_tree(win.content)
check(tree is not None and len(tree.get_children("")) >= 5, f"tree shows the backup's areas ({len(tree.get_children('')) if tree else 0})")
home = next(i for i in tree.get_children("") if "Home" in tree.item(i, "text"))
tree.focus(home)
tree.event_generate("<<TreeviewOpen>>")
a.update()
check(len(tree.get_children(home)) >= 1 and any("Library" in tree.item(c, "text") for c in tree.get_children(home)), "expanding Home shows its folders")


def descend(iid, name):
    for c in tree.get_children(iid):
        if tree.item(c, "text").endswith(name):
            return c
    return None


lib = descend(home, "Library")
sms = descend(lib, "SMS")
db = descend(sms, "sms.db")
check(db is not None and tree.item(db, "values")[0].endswith(("KB", "MB", "B")), f"a single file with its size and date: {tree.item(db, 'values') if db else None}")
tree.selection_set(db)
opened = []
phone.open_file = lambda p: opened.append(p)
win.allfiles_preview()               # what Space and double-click call
a.update()
check(opened and Path(opened[0]).name == "sms.db" and Path(opened[0]).stat().st_size > 0, "preview: the file is copied to a private temp folder and opened")

# save keeps the folder structure (the folder dialog is answered with the default folder here)
phone.ask_save_folder = lambda parent, title, start: str(start)
tree.selection_set(db)
btn = next(w for w in win.content.winfo_children()[-1].winfo_children() if hasattr(w, "text") and w.text == "Save selected")
btn.command()
pump(lambda: str(win.bar_text.cget("text")).startswith("✓ Saved"), 60, "save")
saved = list((W / "Archive" / "From iPhone" / "All files").rglob("sms.db"))
check(saved and saved[0].parent.name == "SMS" and saved[0].parent.parent.name == "Library", f"saved with its folder structure: {saved[0].relative_to(W) if saved else None}")
win.close()

# -- a PhoneKeep snapshot opens the same way; a non-backup folder is refused -----------------------------------------
check(a.open_backup(snap.path), "a PhoneKeep snapshot opens from its folder")
w2 = a.phone_windows[-1]
w2.withdraw()
check(w2.udid == UD and sn.is_snapshot(w2.backup_path), "snapshot: UDID recovered from the phone folder")
w2.close()
check(a.open_backup(sn.phone_dir(BD, UD)), "a phone folder opens its latest snapshot")
a.phone_windows[-1].withdraw(); a.phone_windows[-1].close()
check(not a.open_backup(W) and "isn't an iPhone backup" in a.bar_text.cget("text"), f"a folder that isn't a backup: {a.bar_text.cget('text')!r}")

# -- the Open backup dialog lists what PhoneKeep finds -----------------------------------------------------------------
wv.backup_search_roots = lambda: [BD, finder_root]
d = appmod.OpenBackupDialog(a)
d.withdraw()
pump(lambda: d.backups, 30, "dialog scan")
items = [d.lb.get(i) for i in range(d.lb.size())]
check(len(items) == 2 and all("Amine's iPhone" in t for t in items), f"dialog lists the PhoneKeep snapshot and the Finder backup: {items}")
d.destroy()

# -- a stored password would be used silently (keychain lookup by UDID) --------------------------------------------
keychain.set_password(finder.name, "pw-for-finder")
check(wv.password_for_backup(finder) == "pw-for-finder", "the keychain entry for a Finder backup's phone is found by UDID")

a.destroy()
print("\nB5 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
