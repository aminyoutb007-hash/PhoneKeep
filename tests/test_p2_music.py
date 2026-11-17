"""P2: music saved with its tags and artwork (docs/spec/07-photos-media.md#p2-music).

Done when:
- Saved songs show correct title, artist, album and artwork in Music / Windows Media Player.
- Songs that only stream (not on the phone) are not listed, and a note says why.

An invented iPhone's media folder (a Music library database laid out like a real one, songs, artwork) is served by
a stand-in for Apple's file service, and the real LiveDevice code reads it: the library, the walk of the Music
folder, a song's copy, its artwork. Saved files are opened with mutagen, the library Music and Windows Media Player
read the same tags from. Then the phone window's Music screen: the note, the artwork panel, Save selected.
Every song, artist and album name is invented. The m4a in tests/fixtures/music is a third of a second of silence.

Needs a display: on Mac and Windows there is one; on Linux run it under `xvfb-run`.
"""
import hashlib, io, os, shutil, sqlite3, subprocess, sys, time, wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
import faulthandler
faulthandler.dump_traceback_later(240, exit=True)

import mutagen
from PIL import Image

import device as devmod
import music_tags

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


W = HERE / "work" / "p2-music"
shutil.rmtree(W, ignore_errors=True)
PHONE = W / "phone"                          # the iPhone's media folder (what Apple's file service shows)
LIB = "iTunes_Control/iTunes/MediaLibrary.sqlitedb"
ART = devmod.ARTWORK_ROOT
M4A = (HERE / "fixtures" / "music" / "silence.m4a").read_bytes()


def picture(fmt, colour) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (60, 60), colour).save(b, fmt)
    return b.getvalue()


def mp3() -> bytes:
    """Twenty silent MPEG-1 Layer III frames (128 kbit/s, 44.1 kHz): enough for any MP3 reader."""
    return (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 20


def wav() -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    return b.getvalue()


JPEG, PNG, GIF = picture("JPEG", (200, 80, 40)), picture("PNG", (40, 90, 200)), picture("GIF", (20, 160, 90))
FILES = {
    "iTunes_Control/Music/F01/ABCD.m4a": M4A,
    "iTunes_Control/Music/F02/EFGH.mp3": mp3(),
    "iTunes_Control/Music/F05/SEAL.m4p": M4A,
    "iTunes_Control/Music/F06/FLD1.wav": wav(),
    "iTunes_Control/Music/F07/BAD1.m4a": b"not really a song" * 40,
    "iTunes_Control/Music/F08/LOOSE.mp3": mp3(),          # on the phone, but the library doesn't describe it
    f"{ART}/a1/111": JPEG,
    f"{ART}/b2/222": PNG,
    f"{ART}/c3/333": GIF,
}
# (pid, title, artist, album artist, album, genre, year, track, of, disc, of, base location, file, protected)
SONGS = [
    (1, "Lantern Street", "Mira Calloway", "Mira Calloway", "Northbound Tides", "Folk", 2019, 3, 11, 1, 2, 0,
     "F01/ABCD.m4a", 0),
    (2, "Quiet Engines", "Juno Vale feat. Tarik Osei", "Juno Vale", "Paper Satellites: Part 1/2", "Electronic", 2022,
     1, 9, 0, 0, 0, "F02/EFGH.mp3", 0),
    (3, "Ninth Wave", "Orla Brenn", "Orla Brenn", "Saltwater", "Pop", 2024, 2, 10, 1, 1, 0, "", 0),   # streams only
    (4, "Gone Song", "Orla Brenn", "Orla Brenn", "Saltwater", "Pop", 2024, 5, 10, 1, 1, 0, "F03/GONE.m4a", 0),
    (5, "Sealed Song", "Mira Calloway", "Mira Calloway", "Northbound Tides", "Folk", 2019, 4, 11, 1, 2, 0,
     "F05/SEAL.m4p", 1),
    (6, "Field Recording", "", "", "", "", 0, 0, 0, 0, 0, 0, "F06/FLD1.wav", 0),
    (7, "Bad / File?", "Kit Marlow", "Kit Marlow", "Odd Ends", "Rock", 2015, 7, 12, 0, 0, 0, "F07/BAD1.m4a", 0),
]


def make_library(path: Path, songs=SONGS, full=True):
    """A MediaLibrary.sqlitedb with the tables and columns a real one has (iOS 26), or, full=False, an older,
    smaller one: no album artist, genre, track numbers, artwork or protection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    if full:
        con.executescript("""
CREATE TABLE item (item_pid INTEGER PRIMARY KEY, media_type INTEGER, item_artist_pid INTEGER, album_pid INTEGER,
  album_artist_pid INTEGER, genre_id INTEGER, disc_number INTEGER, track_number INTEGER, base_location_id INTEGER);
CREATE TABLE item_extra (item_pid INTEGER PRIMARY KEY, title TEXT, disc_count INTEGER, track_count INTEGER,
  total_time_ms REAL, year INTEGER, location TEXT, file_size INTEGER);
CREATE TABLE base_location (base_location_id INTEGER PRIMARY KEY, path TEXT);
CREATE TABLE item_artist (item_artist_pid INTEGER PRIMARY KEY, item_artist TEXT);
CREATE TABLE album (album_pid INTEGER PRIMARY KEY, album TEXT, album_artist_pid INTEGER);
CREATE TABLE album_artist (album_artist_pid INTEGER PRIMARY KEY, album_artist TEXT);
CREATE TABLE genre (genre_id INTEGER PRIMARY KEY, genre TEXT);
CREATE TABLE item_store (item_pid INTEGER PRIMARY KEY, is_protected INTEGER);
CREATE TABLE artwork_token (entity_pid INTEGER, artwork_token TEXT, artwork_source_type INTEGER, artwork_type INTEGER,
  entity_type INTEGER);
CREATE TABLE artwork (artwork_token TEXT PRIMARY KEY, artwork_source_type INTEGER, relative_path TEXT,
  artwork_type INTEGER);""")
    else:
        con.executescript("""
CREATE TABLE item (item_pid INTEGER PRIMARY KEY, media_type INTEGER, item_artist_pid INTEGER, album_pid INTEGER,
  base_location_id INTEGER);
CREATE TABLE item_extra (item_pid INTEGER PRIMARY KEY, title TEXT, total_time_ms REAL, location TEXT);
CREATE TABLE base_location (base_location_id INTEGER PRIMARY KEY, path TEXT);
CREATE TABLE item_artist (item_artist_pid INTEGER PRIMARY KEY, item_artist TEXT);
CREATE TABLE album (album_pid INTEGER PRIMARY KEY, album TEXT);""")
    con.execute("INSERT INTO base_location VALUES (0, '')")
    names: dict = {}

    def pid(table, value):
        if not value:
            return 0
        k = (table, value)
        if k not in names:
            names[k] = 100 + len(names)
            col = {"item_artist": "item_artist", "album": "album", "album_artist": "album_artist", "genre": "genre"}[table]
            key = {"item_artist": "item_artist_pid", "album": "album_pid", "album_artist": "album_artist_pid",
                   "genre": "genre_id"}[table]
            con.execute(f"INSERT INTO {table} ({key}, {col}) VALUES (?, ?)", (names[k], value))
        return names[k]
    for (p, title, artist, aartist, album, genre, year, tn, tc, dn, dc, base, loc, prot) in songs:
        if full:
            con.execute("INSERT INTO item VALUES (?,?,?,?,?,?,?,?,?)",
                        (p, 8, pid("item_artist", artist), pid("album", album), pid("album_artist", aartist),
                         pid("genre", genre), dn, tn, base))
            con.execute("INSERT INTO item_extra VALUES (?,?,?,?,?,?,?,?)", (p, title, dc, tc, 200500.0, year, loc, 0))
            con.execute("INSERT INTO item_store VALUES (?,?)", (p, prot))
        else:
            con.execute("INSERT INTO item VALUES (?,?,?,?,?)", (p, 8, pid("item_artist", artist), pid("album", album),
                                                                base))
            con.execute("INSERT INTO item_extra VALUES (?,?,?,?)", (p, title, 200500.0, loc))
    if full and songs is SONGS:
        # song 1 has its own artwork (entity type 0); song 2's comes from its album (type 4); song 6: a GIF
        album2 = names[("album", SONGS[1][4])]
        for ent, token, typ, rel in ((1, "tok-1", 0, "a1/111"), (album2, "tok-2", 4, "b2/222"),
                                     (6, "tok-3", 0, "c3/333"), (7, "tok-4", 0, "")):
            con.execute("INSERT INTO artwork_token VALUES (?,?,?,?,?)", (ent, token, 500, 1, typ))
            con.execute("INSERT INTO artwork VALUES (?,?,?,?)", (token, 500, rel, 1))
    con.commit()
    con.close()


def put_phone(songs=SONGS, files=FILES, full=True):
    shutil.rmtree(PHONE, ignore_errors=True)
    for rel, data in files.items():
        (PHONE / rel).parent.mkdir(parents=True, exist_ok=True)
        (PHONE / rel).write_bytes(data)
    make_library(PHONE / LIB, songs, full)


def phone_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(PHONE.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(PHONE).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


class FakeAfc:
    """Apple's file service (AFC) over the invented media folder: read-only, like PhoneKeep's use of it."""
    def __init__(self):
        self.pulled = []

    async def pull(self, src, dest, progress_bar=False):
        p = PHONE / src
        if not p.is_file():
            raise FileNotFoundError(src)
        self.pulled.append(src)
        Path(dest).write_bytes(p.read_bytes())

    async def walk(self, top):
        for root, dirs, files in os.walk(PHONE / top):
            yield "/" + Path(root).relative_to(PHONE).as_posix(), dirs, files

    def stat(self, rel):
        return {"st_size": (PHONE / rel).stat().st_size}

    async def __aexit__(self, *a):
        pass


class FakeLive(devmod.LiveDevice):
    """The real LiveDevice, with the connection and the file service replaced."""
    def __init__(self, udid=None, cache_dir=None):
        self.afcs = []
        super().__init__(udid, W / "live-cache")

    async def _connect(self):
        self.lockdown = object()

    async def _afc(self):
        a = FakeAfc()
        self.afcs.append(a)
        return a

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


put_phone()
before = phone_hash()

# -- the library ----------------------------------------------------------------------------------------------------
tracks = devmod._tracks_from_db(PHONE / LIB)
by = {t.title: t for t in tracks}
check(sorted(by) == sorted(["Lantern Street", "Quiet Engines", "Gone Song", "Sealed Song", "Field Recording",
                            "Bad / File?"]) and tracks.streaming == 1,
      f"the library's songs with a file are read; the one that only streams is counted, not listed "
      f"({sorted(by)}, streaming {tracks.streaming})")
t1 = by["Lantern Street"]
check((t1.artist, t1.album_artist, t1.album, t1.genre, t1.year, t1.track_no, t1.track_count, t1.disc_no,
       t1.disc_count, t1.path, t1.artwork, t1.protected) ==
      ("Mira Calloway", "Mira Calloway", "Northbound Tides", "Folk", 2019, 3, 11, 1, 2,
       "iTunes_Control/Music/F01/ABCD.m4a", f"{ART}/a1/111", False),
      f"every detail of a song is read: {t1}")
check(by["Quiet Engines"].artwork == f"{ART}/b2/222" and by["Quiet Engines"].album_artist == "Juno Vale",
      "a song without artwork of its own gets its album's; the album artist is read apart from the artist")
check(by["Sealed Song"].protected and not by["Lantern Street"].protected,
      "a song Apple protects (FairPlay) is marked so, and only that one")
check(by["Bad / File?"].artwork == "", "an artwork entry with no file is ignored")
make_library(W / "old" / "MediaLibrary.sqlitedb", SONGS, full=False)
old = devmod._tracks_from_db(W / "old" / "MediaLibrary.sqlitedb")
check(len(old) == 6 and old.streaming == 1 and all(t.artwork == "" and t.track_no == 0 and t.genre == "" for t in old)
      and {t.album for t in old} >= {"Northbound Tides"},
      "an older, smaller library (no album artist, genre, numbers or artwork) still lists its songs")

# -- reading the phone: the library plus the Music folder -------------------------------------------------------------
live = FakeLive("00008030-P2TEST")
songs = live.music()
names = sorted(t.title for t in songs)
check(names == sorted(["Lantern Street", "Quiet Engines", "Sealed Song", "Field Recording", "Bad / File?", "LOOSE"])
      and songs.streaming == 2,
      f"the Music screen lists what's on the phone (a file the library doesn't describe too); the song that "
      f"streams and the one whose file isn't there are counted, not listed ({names}, {songs.streaming})")
check(all(t.size > 0 for t in songs), "each listed song has its size")

# -- saving: Artist / Album folders, tags and artwork -----------------------------------------------------------------
OUT = W / "saved"
by = {t.title: t for t in songs}
want_paths = {
    "Lantern Street": "Mira Calloway/Northbound Tides/1-03 Lantern Street.m4a",
    "Quiet Engines": "Juno Vale/Paper Satellites_ Part 1_2/01 Quiet Engines.mp3",
    "Field Recording": "Unknown Artist/Unknown Album/Field Recording.wav",
    "Bad / File?": "Kit Marlow/Odd Ends/07 Bad _ File_.m4a",
    "Sealed Song": "Mira Calloway/Northbound Tides/1-04 Sealed Song.m4p",
    "LOOSE": "Unknown Artist/Unknown Album/LOOSE.mp3",
}
for title, want in want_paths.items():
    got = music_tags.save_path(by[title])
    check(got == want, f"{title!r} is saved as {got!r}")
saved = {}
for title in want_paths:
    dest = OUT / music_tags.save_path(by[title])
    ok = live.copy_song(by[title], dest)
    saved[title] = dest
    check(ok and dest.is_file(), f"{title!r} is copied from the iPhone")

f = mutagen.File(saved["Lantern Street"])
tags = f.tags
check(tags["\xa9nam"] == ["Lantern Street"] and tags["\xa9ART"] == ["Mira Calloway"]
      and tags["\xa9alb"] == ["Northbound Tides"] and tags["aART"] == ["Mira Calloway"] and tags["\xa9gen"] == ["Folk"]
      and tags["\xa9day"] == ["2019"] and tags["trkn"] == [(3, 11)] and tags["disk"] == [(1, 2)],
      "an m4a gets the title, artist, album, album artist, genre, year, track and disc")
check(bytes(tags["covr"][0]) == JPEG and tags["covr"][0].imageformat == 13,
      "and its artwork (JPEG), exactly as the iPhone keeps it")
check(f.info.length > 0.3 and "----:com.apple.iTunes:iTunSMPB" in tags, "the sound and the file's own tags are kept")

f = mutagen.File(saved["Quiet Engines"])
check(str(f.tags["TIT2"]) == "Quiet Engines" and str(f.tags["TPE1"]) == "Juno Vale feat. Tarik Osei"
      and str(f.tags["TALB"]) == "Paper Satellites: Part 1/2" and str(f.tags["TPE2"]) == "Juno Vale"
      and str(f.tags["TRCK"]) == "1/9" and str(f.tags["TCON"]) == "Electronic",
      "an MP3 gets ID3 tags (the album's name as it is, though its folder can't hold / or :)")
apic = f.tags.getall("APIC")
check(len(apic) == 1 and apic[0].data == PNG and apic[0].mime == "image/png" and apic[0].type == 3,
      "and its album's artwork as the front cover (PNG)")

f = mutagen.File(saved["Field Recording"])
apic = f.tags.getall("APIC") if f.tags is not None else []
check(f.tags is not None and str(f.tags["TIT2"]) == "Field Recording" and "TPE1" not in f.tags
      and len(apic) == 1 and apic[0].data[:3] == b"\xff\xd8\xff",
      "a WAV gets its title, no made-up artist, and its GIF artwork as a JPEG cover")

check(saved["Sealed Song"].read_bytes() == M4A, "a song Apple protects is saved exactly as it is (no tags written)")
check(saved["Bad / File?"].read_bytes() == FILES["iTunes_Control/Music/F07/BAD1.m4a"],
      "a file the tagger can't read is still saved, untouched")
f = mutagen.File(saved["LOOSE"])
check(f is not None and str(f.tags["TIT2"]) == "LOOSE" and "TPE1" not in f.tags,
      "a song the library doesn't describe is saved under its file's name")
left = [p.name for p in OUT.rglob("*") if p.suffix in (".part", ".tagging") or ".part" in p.name]
check(not left, f"no half-written files are left ({left})")
check(phone_hash() == before, "nothing on the iPhone changed (Apple's file service was only read)")

# the artwork alone (the Music screen's panel)
check(live.artwork(by["Lantern Street"]) == JPEG and live.artwork(by["LOOSE"]) is None,
      "a song's artwork is read on its own; a song without any has none")
live.close()

# -- the phone window's Music screen ---------------------------------------------------------------------------------
BACKUPS = HERE / "work" / "Backups"
UDID = "00008030-FULLTEST"
if not (BACKUPS / UDID / "Manifest.db").exists():
    print("fake backup missing: building it with test_full_backup.py first", flush=True)
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

import tkinter as tk
from tkinter import ttk
import keychain
import phonekeep as wv
import photos as ph
import phone
import ui
keychain.use_memory()


class SimPhone:
    """What the phone window asks a connected iPhone; music goes through the real code above."""
    def __init__(self, udid, cache_dir=None):
        self.udid = udid
        self.real = FakeLive(udid)
        self.music = self.real.music
        self.copy_song = self.real.copy_song
        self.copy_media = self.real.copy_media
        self.artwork = self.real.artwork

    def wallpaper(self, which="homescreen"):
        return None

    def books(self):
        return []

    def apps(self):
        return []

    def close(self):
        self.real.close()


class NoDevicePhotos:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("not simulated")


devmod.LiveDevice = SimPhone
wv.device_overview = lambda udid=None, apps=True, **k: None
ph.DevicePhotoSource = NoDevicePhotos


class FakeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.s = {"backup_dir": str(BACKUPS), "archive_dir": str(W / "archive")}
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
        time.sleep(0.02)
    return until()


def widgets(w, cls):
    out = []
    for c in w.winfo_children():
        if isinstance(c, cls):
            out.append(c)
        out.extend(widgets(c, cls))
    return out


def texts(w):
    return [l.cget("text") for l in widgets(w, tk.Label)]


def loading(win):
    return any(t in ("Loading…", "Reading from the iPhone…") for t in texts(win.content))


app = FakeApp()
win = phone.PhoneWindow(app, {"DeviceName": "Test iPhone"}, UDID)
check(pump(lambda: win.live is not None, 30), "the phone window connects to the invented iPhone")
win.open_app("music")
check(pump(lambda: not loading(win) and widgets(win.content, ttk.Treeview), 120), "the Music screen opens")
tree = widgets(win.content, ttk.Treeview)[0]
rows = tree.get_children()
shown = sorted(tree.item(i, "values")[0] for i in rows)
check(shown == sorted(["Lantern Street", "Quiet Engines", "Sealed Song", "Field Recording", "Bad / File?", "LOOSE"]),
      f"it lists the songs on the phone, and not the ones that aren't ({shown})")
note = " ".join(texts(win.content))
check("2 more songs in the Music library are not listed" in note and "stream from Apple Music or iCloud" in note,
      f"a note says why some songs aren't listed: {win.music_note!r}")
first = next(i for i in rows if tree.item(i, "values")[0] == "Lantern Street")
tree.selection_set(first)
check(pump(lambda: str(win.music_art.cget("image")) != "", 20) and win.music_art.image.width() == 60,
      "choosing a song shows its artwork")
check("Northbound Tides" in win.music_info.cget("text") and "Folk · 2019" in win.music_info.cget("text"),
      f"and its details: {win.music_info.cget('text')!r}")
loose = next(i for i in rows if tree.item(i, "values")[0] == "LOOSE")
tree.selection_set(loose)
check(pump(lambda: str(win.music_art.cget("image")) == "" and win.music_art.cget("text") == "🎵", 20),
      "a song without artwork shows the music note instead")

dest_dir = W / "chosen"
shutil.rmtree(dest_dir, ignore_errors=True)
dest_dir.mkdir(parents=True)
phone.ask_save_folder = lambda parent, title, start: str(dest_dir)
phone.reveal = lambda p: None
tree.selection_set(rows)
save = next(b for b in widgets(win.content, ui.RoundButton) if b.text == "Save selected")
save.command()
check(pump(lambda: str(win.bar_text.cget("text")).startswith("✓ Saved"), 60),
      f"Save selected saves them: {win.bar_text.cget('text')!r}")
got = sorted(p.relative_to(dest_dir).as_posix() for p in dest_dir.rglob("*") if p.is_file())
check(got == sorted(want_paths.values()), f"into Artist / Album folders: {got}")
f = mutagen.File(dest_dir / want_paths["Lantern Street"])
check(f.tags["\xa9nam"] == ["Lantern Street"] and bytes(f.tags["covr"][0]) == JPEG,
      "with the tags and artwork in each file")

# Play and Space still copy the song as it is on the phone, into the private folder
import quicklook
quicklook.play = lambda p: None
tree.selection_set(first)
win.table_preview()
app.update()
v = quicklook.Viewer.current
check(v is not None and v.items[v.index].name == "Mira Calloway - Lantern Street.m4a",
      f"Space previews the song ({v.items[v.index].name if v else None})")
if v is not None:
    pump(lambda: v.shown_kind == "play", 20)
    p = v.open_from_file(wait=True)
    check(p is not None and p.read_bytes() == M4A and quicklook.private_dir() in p.parents,
          "Play copies it, untouched, into the private folder")
    v.close()

# a phone whose library only streams: nothing listed, and the reason
put_phone(songs=[SONGS[2]], files={})
win.show_home()
win.open_app("music")
check(pump(lambda: not loading(win) and any(t.startswith("No music is stored") for t in texts(win.content)), 60),
      "with only streaming songs, the Music screen says no music is stored on this iPhone")
msg = next(t for t in texts(win.content) if t.startswith("No music is stored"))
check("only stream from Apple Music" in msg and "(1 song in the library streams this way.)" in msg,
      f"and why: {msg!r}")
win.destroy()
app.destroy()

print("\nP2 MUSIC TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
