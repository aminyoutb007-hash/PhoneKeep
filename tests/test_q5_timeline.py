"""Q5: the backup timeline slider.

Three invented snapshots on three days, each with one more message than the one before. In the phone window's
Snapshot card the slider has the oldest on the left and the latest on the right. Moving it shows the date under the
handle, and once it stops the open screen (Messages) changes to that snapshot within 2 seconds, with the "Viewing …"
badge. Moving quickly across several snapshots opens only the one it stops on, and back at the right end it's the
latest again, with no badge. One snapshot alone has no slider.
"""
import datetime as dt, os, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import phonekeep as wv
import snapshots as sn

W = HERE / "work" / "q5"
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
UD = "00008030-Q5TEST"
UD1 = "00008030-Q5ONE"
BD = W / "Backups"
cur = sn.current_dir(BD, UD)
shutil.copytree(fake, cur)


def add_message(text: str):
    """The phone, a day later: one more message in sms.db in the live backup."""
    fid = next(r[0] for r in sqlite3.connect(cur / "Manifest.db").execute(
        "SELECT fileID FROM Files WHERE relativePath='Library/SMS/sms.db'"))
    db = cur / fid[:2] / fid
    c = sqlite3.connect(db)
    row = c.execute("INSERT INTO message(text, handle_id, date, is_from_me, service) VALUES (?,1,?,1,'iMessage')",
                    (text, int((dt.datetime(2026, 11, 12).timestamp() - wv.APPLE_EPOCH) * 1e9)))
    c.execute("INSERT INTO chat_message_join VALUES (1, ?)", (row.lastrowid,))
    c.commit()
    c.close()
    os.utime(db, None)


days = [dt.datetime(2026, 11, d, 21, 0) for d in (3, 6, 9)]
for n, day in enumerate(days):
    if n:
        add_message(f"Q5 test message {n}")
    sn.make_snapshot(BD, UD, when=day)
shutil.copytree(fake, sn.current_dir(BD, UD1))
sn.make_snapshot(BD, UD1, when=days[0])

# -- opening another snapshot of an encrypted backup reuses the key made from the password (memory only) ---------
import hashlib, plistlib, struct
from Crypto.Cipher import AES
import iphone_backup_decrypt.utils as bu

PW = "invented test password"


def tlv(tag: bytes, data) -> bytes:
    data = struct.pack(">L", data) if isinstance(data, int) else data
    return tag + struct.pack(">L", len(data)) + data


def make_encrypted(folder: Path, dpsl: bytes, rows: int):
    """An encrypted backup made the way iOS makes one (few iterations, so it's quick): a keybag whose class key is
    wrapped with the key made from PW, and Manifest.db encrypted with a key wrapped by that class key."""
    folder.mkdir(parents=True)
    salt = hashlib.sha1(dpsl).digest()
    made = hashlib.pbkdf2_hmac("sha1", hashlib.pbkdf2_hmac("sha256", PW.encode(), dpsl, 1000, 32), salt, 10, 32)
    class_key, manifest_key = os.urandom(32), os.urandom(32)
    bag = (tlv(b"VERS", 4) + tlv(b"TYPE", 1) + tlv(b"UUID", os.urandom(16)) + tlv(b"WRAP", 0) + tlv(b"SALT", salt)
           + tlv(b"ITER", 10) + tlv(b"DPWT", 1) + tlv(b"DPIC", 1000) + tlv(b"DPSL", dpsl)
           + tlv(b"UUID", os.urandom(16)) + tlv(b"CLAS", 3) + tlv(b"WRAP", 2) + tlv(b"KTYP", 0)
           + tlv(b"WPKY", AES.new(made, AES.MODE_KW).seal(class_key)))
    with open(folder / "Manifest.plist", "wb") as f:
        plistlib.dump({"IsEncrypted": True, "BackupKeyBag": bag,
                       "ManifestKey": struct.pack("<l", 3) + AES.new(class_key, AES.MODE_KW).seal(manifest_key)}, f)
    with open(folder / "Info.plist", "wb") as f:
        plistlib.dump({"Device Name": "Test iPhone"}, f)
    plain = folder / "plain.db"
    c = sqlite3.connect(plain)
    c.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    c.executemany("INSERT INTO Files VALUES (?, 'HomeDomain', ?, 1, ?)",
                  [(f"{n:040x}", f"f{n}", plistlib.dumps({"n": n}, fmt=plistlib.FMT_BINARY)) for n in range(rows)])
    c.commit()
    c.close()
    data = plain.read_bytes()
    plain.unlink()
    pad = 16 - len(data) % 16
    (folder / "Manifest.db").write_bytes(AES.new(manifest_key, AES.MODE_CBC, iv=b"\0" * 16).encrypt(data + bytes([pad]) * pad))


enc_a, enc_b, enc_c = W / "enc-a", W / "enc-b", W / "enc-c"
make_encrypted(enc_a, b"S" * 20, 3)
make_encrypted(enc_b, b"S" * 20, 5)            # the next snapshot: the same password and salts, new keys
make_encrypted(enc_c, b"T" * 20, 7)            # the password set again: new salts
made = []
real_kdf = bu.pbkdf2_hmac
bu.pbkdf2_hmac = lambda *a, **k: (made.append(1), real_kdf(*a, **k))[1]
wv._KEYS.clear()


def files_in(path: Path, password: str):
    r = wv.BackupReader(path, password, log=lambda *a: None)
    try:
        return r.db.execute("SELECT COUNT(*) FROM Files").fetchone()[0]
    finally:
        r.close()


check(files_in(enc_a, PW) == 3 and len(made) == 2, "an encrypted backup opens with its password (the key made once)")
check(files_in(enc_b, PW) == 5 and len(made) == 2, "  another snapshot with the same password and salts opens without making it again")
try:
    files_in(enc_b, "not the password")
    wrong = False
except wv.PhoneKeepError:
    wrong = True
check(wrong, "  a wrong password still doesn't open it (the kept key is only for the same password)")
for kid in wv._KEYS:
    wv._KEYS[kid] = os.urandom(32)             # a kept key that no longer fits
n = len(made)
check(files_in(enc_b, PW) == 5 and len(made) == n + 2, "  a kept key that doesn't fit: the password opens it, and the key is made again")
n = len(made)
check(files_in(enc_c, PW) == 7 and len(made) == n + 2, "  new salts (the password set again): the key is made again")
check(not any(PW.encode() in p.read_bytes() for d in (enc_a, enc_b, enc_c) for p in d.iterdir()),
      "  nothing about the password is written next to the backups")
bu.pbkdf2_hmac = real_kdf

# backup_info is kept while the backup's files stay the same, and read again when one changes
first = wv.backup_info(enc_a)
with open(enc_a / "Info.plist", "wb") as f:
    plistlib.dump({"Device Name": "Renamed Test iPhone"}, f)
check(first["name"] == "Test iPhone" and wv.backup_info(enc_a)["name"] == "Renamed Test iPhone",
      "a backup's details are read again when its Info.plist changes")

import tkinter as tk
import device as devmod
import phone


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
wv.device_overview = lambda udid=None, apps=True, **k: None


class FakeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(BD), "archive_dir": str(W / "Archive")}
        self.busy = False
        self._backup_password = None

    def detect(self, silent=False):
        pass


def pump(until, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until():
            return True
        time.sleep(0.01)
    return until()


def messages_count():
    """The number of messages the open Messages screen says it shows ("2 chats · 6 messages · …")."""
    try:
        text = win.view_sub.cget("text")
    except tk.TclError:
        return None
    part = next((p for p in text.split("·") if "message" in p), "")
    digits = "".join(ch for ch in part if ch.isdigit())
    return int(digits) if digits else None


app = FakeApp()
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone"}, UD)
win.withdraw()
check(pump(lambda: win.data is not None, 60), "the window opens on the latest of three invented snapshots")
win.open_app("messages")
check(pump(lambda: messages_count() is not None, 30), "Messages is open")
latest = messages_count()

scale, at, old_first, let_go = win.snap_slider
check([s.when.day for s in old_first] == [3, 6, 9] and at.get() == 2,
      "the slider has the oldest snapshot on the left and the latest on the right, and starts at the latest")
check(not bool(win.viewing.winfo_manager()), "  no 'Viewing' badge on the latest")

# drag to the oldest: the date under the handle at once, then the whole screen
opened = []
real_open = win.open_snapshot
win.open_snapshot = lambda snap: (opened.append(snap.id if snap else None), real_open(snap))[1]
t0 = time.time()
at.set(0)
app.update()
shown = win.snap_var.get()
check(shown == "3 Nov", f"moving it shows the date under the handle at once, in the list above ({shown!r})")
check(pump(lambda: messages_count() == latest - 2, 10), "  and Messages changes to that snapshot (two messages fewer)")
took = time.time() - t0
check(took <= 2.0, f"  within 2 seconds ({took:.1f} s)")
check(bool(win.viewing.winfo_manager()) and win.viewing.cget("text") == "Viewing 3 Nov",
      f"  with the badge ({win.viewing.cget('text')!r})")
check(win.current == "messages", "  the same screen stays open")

# a quick move across two snapshots opens only the one it stops on
opened.clear()
scale, at, old_first, let_go = win.snap_slider
at.set(1)
app.update()
at.set(2)
pump(lambda: messages_count() == latest and not bool(win.viewing.winfo_manager()), 10)
check(opened == [old_first[2].id], f"moving quickly past a snapshot opens only the one it stops on ({len(opened)} opened)")
check(messages_count() == latest and not bool(win.viewing.winfo_manager()),
      "back at the right end it's the latest again, with no badge")

# letting go opens it at once, without waiting for the pause
opened.clear()
scale, at, old_first, let_go = win.snap_slider
at.set(1)
t0 = time.time()
let_go()
pump(lambda: bool(opened), 1)
check(opened == [old_first[1].id] and time.time() - t0 < 0.3, "letting go of the handle opens that snapshot at once")
check(pump(lambda: messages_count() == latest - 1, 10), "  (the middle one: one message fewer than the latest)")

# the mouse and the keys (on a shown window: a hidden one gets no events)
win.deiconify()
win.geometry("1220x800+40+40")
pump(lambda: win.snap_slider[0].winfo_ismapped() and win.snap_slider[0].winfo_width() > 100, 10)
scale, at, old_first, let_go = win.snap_slider
was = at.get()
scale.focus_force()
app.update()
scale.event_generate("<Right>")
app.update()
right = at.get()
scale.event_generate("<Left>")
app.update()
check(right == was + 1 and at.get() == was, f"the arrow keys move it one snapshot ({was} -> {right} -> {at.get()})")
opened.clear()
scale.event_generate("<Button-1>", x=2, y=12)
scale.event_generate("<ButtonRelease-1>", x=2, y=12)
check(pump(lambda: messages_count() == latest - 2 and bool(opened), 10) and opened == [old_first[0].id],
      "clicking its left end opens the oldest snapshot")
win.destroy()

# one snapshot alone: no slider
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone"}, UD1)
win.withdraw()
pump(lambda: win.data is not None, 60)
check(len(win.snaps) == 1 and not any(isinstance(w, tk.Canvas) for w in win.timeline.winfo_children()
                                      for w in [w, *w.winfo_children()]),
      "with only one snapshot there's no slider")
win.destroy()

app.destroy()
print("\nQ5 TESTS:", "FAIL" if failures else "PASS", flush=True)
os._exit(1 if failures else 0)
