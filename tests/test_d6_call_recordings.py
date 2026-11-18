"""D6: call recordings (docs/spec/08-personal-data.md#d6-call-recordings).

Done when: "A recorded call on a real phone appears with its audio and transcript." (the real phone: real_check).
iOS 18.1 and later keep a recorded call as a note the Phone app made (its ZHOSTAPPLICATIONIDENTIFIER), whatever
the folder is called in the phone's language. On an invented backup (every name, number and word is made up):
- each recorded call is listed with who (the note's title), when and how long, newest first; a FaceTime call too;
- a short part iOS keeps under a recording isn't listed on its own; its length is used if the recording has none;
- a length the database doesn't have is measured from the audio file;
- the transcript is shown when the phone made one; a call without one says so;
- a deleted call, and an ordinary note with a voice recording, are not listed;
- a recording whose file isn't in the backup is listed, and Play says it isn't available;
- an older Notes database (before iOS 18.1) says so in plain words;
- Save everything's Call Recordings: the audio, the transcript as .txt beside it, a page with Play, and a CSV;
- in the phone window: the list, the transcript of the selected call, Play from the private folder, and Save
  selected puts the audio and its transcript side by side.
"""
import datetime as dt, hashlib, io, json, os, plistlib, shutil, sqlite3, struct, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
import sections as sx

W = HERE / "work" / "d6"
shutil.rmtree(W, ignore_errors=True)
E = wv.APPLE_EPOCH
DOM = "AppDomainGroup-group.com.apple.notes"
ACC = "4B1D2C3E-0000-4000-8000-00000000D6AC"


def box(t: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(body)) + t + body


def m4a(seconds: float) -> bytes:
    """The smallest .m4a a player can tell the length of (no sound in it)."""
    def full(t, body):
        return box(t, b"\0\0\0\0" + body)
    mvhd = full(b"mvhd", struct.pack(">IIII", 0, 0, 1000, int(seconds * 1000)) + b"\0" * 80)
    mdhd = full(b"mdhd", struct.pack(">IIII", 0, 0, 1000, int(seconds * 1000)) + b"\0" * 4)
    hdlr = full(b"hdlr", b"\0" * 4 + b"soun" + b"\0" * 13)
    trak = box(b"trak", box(b"mdia", mdhd + hdlr + box(b"minf")))
    return box(b"ftyp", b"M4A \0\0\0\0M4A mp42isom") + box(b"moov", mvhd + trak) + box(b"mdat", b"\0" * 32)


def make_backup(name: str, columns_d6: bool = True) -> Path:
    bk = W / "Backups" / name
    bk.mkdir(parents=True)
    with open(bk / "Info.plist", "wb") as f:
        plistlib.dump({"Device Name": "Test iPhone", "Product Type": "iPhone16,2", "Product Version": "26.1",
                       "Last Backup Date": dt.datetime(2026, 3, 10, 22, 0)}, f)
    with open(bk / "Manifest.plist", "wb") as f:
        plistlib.dump({"IsEncrypted": False}, f)
    man = sqlite3.connect(bk / "Manifest.db")
    man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")

    def add(rel, data: bytes):
        fid = hashlib.sha1(f"{DOM}-{rel}".encode()).hexdigest()
        (bk / fid[:2]).mkdir(exist_ok=True)
        (bk / fid[:2] / fid).write_bytes(data)
        man.execute("INSERT INTO Files VALUES (?,?,?,1,NULL)", (fid, DOM, rel))

    t = dt.datetime(2026, 3, 1, 9, 0).timestamp() - E
    extra = ", ZHOSTAPPLICATIONIDENTIFIER, ZDURATION, ZADDITIONALINDEXABLETEXT, ZTITLE" if columns_d6 else ""
    p = W / f"{name}.sqlite"
    c = sqlite3.connect(p)
    c.executescript(f"""
CREATE TABLE ZICCLOUDSYNCINGOBJECT(Z_PK INTEGER PRIMARY KEY, ZTITLE1, ZTITLE2, ZFOLDER, ZNOTEDATA, ZCREATIONDATE1,
 ZCREATIONDATE3, ZMODIFICATIONDATE1, ZMARKEDFORDELETION, ZIDENTIFIER, ZTYPEUTI, ZMEDIA, ZFILENAME, ZNOTE,
 ZPARENTATTACHMENT{extra});
CREATE TABLE ZICNOTEDATA(Z_PK INTEGER PRIMARY KEY, ZNOTE, ZDATA);""")
    cols = ["Z_PK", "ZTITLE1", "ZTITLE2", "ZFOLDER", "ZNOTEDATA", "ZCREATIONDATE3", "ZMARKEDFORDELETION",
            "ZIDENTIFIER", "ZTYPEUTI", "ZMEDIA", "ZFILENAME", "ZNOTE", "ZPARENTATTACHMENT"]
    d6 = ["ZHOSTAPPLICATIONIDENTIFIER", "ZDURATION", "ZADDITIONALINDEXABLETEXT", "ZTITLE"] if columns_d6 else []

    def row(**v):
        names = cols + d6
        c.execute(f"INSERT INTO ZICCLOUDSYNCINGOBJECT ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                  [v.get(k) for k in names])

    phone, ft = "com.apple.mobilephone", "com.apple.facetime"
    row(Z_PK=1, ZTITLE2="Notes")                                                      # the folder
    # 1. a call with a transcript, and the short part iOS keeps under it
    row(Z_PK=10, ZTITLE1="Call with Alex Example", ZFOLDER=1, ZNOTEDATA=100, ZCREATIONDATE3=t + 3600,
        ZHOSTAPPLICATIONIDENTIFIER=phone)
    row(Z_PK=11, ZIDENTIFIER="A1", ZTYPEUTI="com.apple.m4a-audio", ZMEDIA=12, ZNOTE=10, ZDURATION=95,
        ZADDITIONALINDEXABLETEXT="Hello, it's Alex. The keys are under the blue pot.", ZTITLE="Call Recording")
    row(Z_PK=12, ZIDENTIFIER="D6D6D6D6-0000-4000-8000-000000000001", ZFILENAME="Call Recording.m4a")
    row(Z_PK=13, ZIDENTIFIER="P1", ZTYPEUTI="public.mpeg-4-audio", ZMEDIA=14, ZNOTE=10, ZPARENTATTACHMENT=11,
        ZDURATION=6)
    row(Z_PK=14, ZIDENTIFIER="D6D6D6D6-0000-4000-8000-000000000002", ZFILENAME="part.MOV")
    # 2. no length in the database: the part has none either, so it's measured from the file (42 s)
    row(Z_PK=20, ZTITLE1="Call with +44 7700 900123", ZFOLDER=1, ZNOTEDATA=101, ZCREATIONDATE3=t + 7200,
        ZHOSTAPPLICATIONIDENTIFIER=phone)
    row(Z_PK=21, ZIDENTIFIER="A2", ZTYPEUTI="com.apple.m4a-audio", ZMEDIA=22, ZNOTE=20)
    row(Z_PK=22, ZIDENTIFIER="D6D6D6D6-0000-4000-8000-000000000003", ZFILENAME="Call Recording.m4a")
    # 3. a FaceTime audio call, no transcript; its length from its part
    row(Z_PK=30, ZTITLE1="FaceTime with Sam Sample", ZFOLDER=1, ZNOTEDATA=102, ZCREATIONDATE3=t,
        ZHOSTAPPLICATIONIDENTIFIER=ft)
    row(Z_PK=31, ZIDENTIFIER="A3", ZTYPEUTI="com.apple.m4a-audio", ZMEDIA=32, ZNOTE=30)
    row(Z_PK=32, ZIDENTIFIER="D6D6D6D6-0000-4000-8000-000000000004", ZFILENAME="Call Recording.m4a")
    row(Z_PK=33, ZIDENTIFIER="P3", ZTYPEUTI="public.mpeg-4-audio", ZNOTE=30, ZPARENTATTACHMENT=31, ZDURATION=12)
    # 4. deleted: not listed
    row(Z_PK=40, ZTITLE1="Call with Old Friend", ZFOLDER=1, ZNOTEDATA=103, ZCREATIONDATE3=t + 9000,
        ZMARKEDFORDELETION=1, ZHOSTAPPLICATIONIDENTIFIER=phone)
    row(Z_PK=41, ZIDENTIFIER="A4", ZTYPEUTI="com.apple.m4a-audio", ZNOTE=40, ZDURATION=30)
    # 5. an ordinary note with a voice recording (no Phone app): not listed
    row(Z_PK=50, ZTITLE1="Shopping list", ZFOLDER=1, ZNOTEDATA=104, ZCREATIONDATE3=t + 9500)
    row(Z_PK=51, ZIDENTIFIER="A5", ZTYPEUTI="com.apple.m4a-audio", ZMEDIA=52, ZNOTE=50, ZDURATION=20,
        ZADDITIONALINDEXABLETEXT="milk and bread")
    row(Z_PK=52, ZIDENTIFIER="D6D6D6D6-0000-4000-8000-000000000005", ZFILENAME="New Recording.m4a")
    # 6. a call whose audio isn't in the backup
    row(Z_PK=60, ZTITLE1="Call with Robin Test", ZFOLDER=1, ZNOTEDATA=105, ZCREATIONDATE3=t + 600,
        ZHOSTAPPLICATIONIDENTIFIER=phone)
    row(Z_PK=61, ZIDENTIFIER="A6", ZTYPEUTI="com.apple.m4a-audio", ZMEDIA=62, ZNOTE=60, ZDURATION=8)
    row(Z_PK=62, ZIDENTIFIER="D6D6D6D6-0000-4000-8000-000000000006", ZFILENAME="Call Recording.m4a")
    c.executemany("INSERT INTO ZICNOTEDATA VALUES (?,?,?)", [(100 + i, 0, b"\x00") for i in range(6)])
    c.commit()
    c.close()
    add("NoteStore.sqlite", p.read_bytes())
    add(f"Accounts/{ACC}/Media/D6D6D6D6-0000-4000-8000-000000000001/1_0001/Call Recording.m4a", m4a(95))
    add(f"Accounts/{ACC}/Media/D6D6D6D6-0000-4000-8000-000000000002/1_0002/part.MOV", m4a(6))
    add(f"Accounts/{ACC}/Media/D6D6D6D6-0000-4000-8000-000000000003/1_0003/Call Recording.m4a", m4a(42))
    add(f"Accounts/{ACC}/Media/D6D6D6D6-0000-4000-8000-000000000004/1_0004/Call Recording.m4a", m4a(12))
    add(f"Accounts/{ACC}/Media/D6D6D6D6-0000-4000-8000-000000000005/1_0005/New Recording.m4a", m4a(20))
    man.commit()
    man.close()
    return bk


BK = make_backup("00008030-D6CALLSTEST00000")
reader = wv.BackupReader(BK, None, lambda m: None)
ctx = sx.Ctx(reader, W / "out", lambda m: None, False, {})
calls = sx.load_call_recordings(ctx)
by = {c["title"]: c for c in calls}
check([c["title"] for c in calls] == ["Call with +44 7700 900123", "Call with Alex Example", "Call with Robin Test",
                                     "FaceTime with Sam Sample"],
      f"each recorded call is listed, newest first, a FaceTime call too ({[c['title'] for c in calls]})")
check("Call with Old Friend" not in by and "Shopping list" not in by,
      "a deleted call and an ordinary note with a voice recording are not listed")
check(len(calls) == 4, "the short part iOS keeps under a recording isn't listed on its own")
a = by["Call with Alex Example"]
check(a["length"] == 95 and a["transcript"] == "Hello, it's Alex. The keys are under the blue pot." and a["parts"] == 1,
      "a call has its length and its transcript")
check(a["when"] == dt.datetime.fromtimestamp(dt.datetime(2026, 3, 1, 10, 0).timestamp()), "  and when it was")
check(abs(by["Call with +44 7700 900123"]["length"] - 42) < 0.01,
      f"a length the database doesn't have is measured from the file ({by['Call with +44 7700 900123']['length']})")
check(by["FaceTime with Sam Sample"]["length"] == 12 and by["FaceTime with Sam Sample"]["transcript"] == "",
      "a call without its own length takes its part's; a call without a transcript has none")
check(by["Call with Robin Test"]["file"] is None and by["Call with Robin Test"]["length"] == 8,
      "a recording whose file isn't in the backup is still listed, without a file")
quick = sx.load_call_recordings(ctx, measure=False)
check({c["title"]: c["length"] for c in quick}["Call with +44 7700 900123"] == 0,
      "measure=False reads no audio (the length stays unknown)")
reader.close()

OLD = make_backup("00008030-D6OLDNOTES000000", columns_d6=False)
r2 = wv.BackupReader(OLD, None, lambda m: None)
try:
    sx.load_call_recordings(sx.Ctx(r2, W / "out-old", lambda m: None, False, {}))
    msg = ""
except wv.PhoneKeepError as e:
    msg = str(e)
r2.close()
check("iOS 18.1" in msg and "Traceback" not in msg, f"an older Notes database says so in plain words ({msg!r})")

# ---- Save everything's Call Recordings ----
reader = wv.BackupReader(BK, None, lambda m: None)
ctx = sx.Ctx(reader, W / "export", lambda m: None, False, {})
res = sx.sec_callrecordings(ctx)
d = W / "export" / "Call Recordings"
names = sorted(p.name for p in d.iterdir())
check(res["count"] == 4 and "2026-03-01 1000 Call with Alex Example.m4a" in names
      and "2026-03-01 1000 Call with Alex Example.txt" in names,
      f"the audio and its transcript are saved side by side ({names})")
check((d / "2026-03-01 1000 Call with Alex Example.txt").read_text(encoding="utf-8").strip()
      == "Hello, it's Alex. The keys are under the blue pot.", "  the .txt is the transcript")
check((d / "2026-03-01 1000 Call with Alex Example.m4a").read_bytes() == m4a(95), "  the audio is the same bytes")
check(not any("Robin" in n and n.endswith(".m4a") for n in names), "  a recording not in the backup isn't saved")
page = (d / "index.html").read_text(encoding="utf-8")
check(page.count("<audio") == 3 and "The keys are under the blue pot." in page,
      "the page plays each saved recording and shows the transcript")
csv_text = (d / "call recordings.csv").read_text(encoding="utf-8-sig")
check("Call with Alex Example" in csv_text and "1:35" in csv_text, "the CSV has who, when and how long")
reader.close()

# ---- the phone window ----
import tkinter as tk
import app as appmod
import device as devmod
import phone
import quicklook as ql
import ui


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
opened = []
phone.open_file = lambda p: opened.append(Path(p))           # never opens another app
dest_dir = Path(tempfile.mkdtemp(prefix="pk-d6-"))
ui.ask_folder = lambda parent, title: str(dest_dir)
phone.ask_save_folder = lambda parent, title, start: str(dest_dir)
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(W / "Backups"),
                                            "archive_dir": str(W / "Saved")}), encoding="utf-8")
app = appmod.App()
app.after_cancel(app._timers.pop("first"))


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until():
            return True
        time.sleep(0.01)
    return until()


def find(w, cls):
    for c in w.winfo_children():
        if isinstance(c, cls):
            return c
        f = find(c, cls)
        if f is not None:
            return f
    return None


pump(lambda: False, 0.3)
check(app.open_backup(BK), "the phone window opens on the invented backup")
win = app.phone_windows[-1]
pump(lambda: win.data is not None, 60)
check(pump(lambda: win.counts.get("callrecordings") == "4", 60),
      f"the home screen counts the recordings ({win.counts.get('callrecordings')})")
win.open_app("callrecordings")
check(pump(lambda: find(win.content, tk.Text) is not None and getattr(win, "call_transcript", None) is not None, 60),
      "Call Recordings opens")
tree = find(win.content, phone.ttk.Treeview)
rows = [tree.item(i, "values") for i in tree.get_children()]
check([r[1] for r in rows] == ["Call with +44 7700 900123", "Call with Alex Example", "Call with Robin Test",
                               "FaceTime with Sam Sample"] and rows[1][2] == "1:35" and rows[1][3] == "yes",
      f"the list shows who, when, how long and whether there's a transcript ({rows[1]})")


def select(title):
    iid = next(i for i in tree.get_children() if tree.item(i, "values")[1] == title)
    tree.selection_set(iid)
    tree.focus(iid)
    app.update()
    return iid


def said():
    return win.call_transcript.get("1.0", "end").strip()


select("Call with Alex Example")
check(said() == "Hello, it's Alex. The keys are under the blue pot.", "the selected call's transcript is shown")
select("FaceTime with Sam Sample")
check(said() == "The iPhone made no transcript of this call.", "a call without one says so")

def press(label):
    def walk(w):
        for c in w.winfo_children():
            if getattr(c, "text", None) == label and callable(getattr(c, "command", None)):
                return c
            f = walk(c)
            if f is not None:
                return f
        return None
    b = walk(win.content)
    if b is not None:
        b.command()
    return b


iid = select("Call with Alex Example")
press("▶  Play")
check(pump(lambda: opened, 15) and opened[-1].read_bytes() == m4a(95)
      and ql.private_dir().resolve() in opened[-1].resolve().parents,
      "Play opens it from PhoneKeep's private folder (gone when PhoneKeep closes), the same bytes")
opened.clear()
select("Call with Robin Test")
press("▶  Play")
check(pump(lambda: "isn't available" in str(win.bar_text.cget("text")), 15) and not opened,
      "a recording not in the backup isn't played, and the window says so")


iid = select("Call with Alex Example")
b = press("Save selected")
check(b is not None, "there is a Save selected button")
check(pump(lambda: any(p.suffix == ".txt" for p in dest_dir.iterdir()), 30),
      "Save selected saves the call")
saved = sorted(p.name for p in dest_dir.iterdir())
check(saved == ["2026-03-01 1000 Call with Alex Example.m4a", "2026-03-01 1000 Call with Alex Example.txt"],
      f"  the audio and its transcript side by side ({saved})")
check((dest_dir / "2026-03-01 1000 Call with Alex Example.m4a").read_bytes() == m4a(95)
      and "blue pot" in (dest_dir / "2026-03-01 1000 Call with Alex Example.txt").read_text(encoding="utf-8"),
      "  with the same bytes and the transcript")
win.destroy()
app.update()
shutil.rmtree(dest_dir, ignore_errors=True)

print("\nD6 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
