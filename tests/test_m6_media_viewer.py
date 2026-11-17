"""M6: media viewer for chat attachments (docs/spec/06-messages.md#m6-media-viewer-for-chat-attachments).

Done when: "A chat's Media tab shows every attachment; Save all saves them with their original dates."
In the real phone window, on an invented backup (every name, number, photo and file is made up):
- in a chat, a click on a photo, video, voice note or document opens it large; the arrow keys go through the
  chat's other attachments; one that isn't in the backup says so;
- the chat's Media tab shows every attachment (photos, videos, voice notes, documents, and those not in the
  backup), newest first, with a choice of kind; a click on a tile opens that one large;
- Save all saves every attachment the backup has into a new folder, each named and dated when it was sent, with
  the same bytes; those not in the backup are counted, not saved; a second Save all makes a second folder;
- a group shown for one person (M5): the Media tab and Save all have only their attachments;
- the same for WhatsApp (a photo, a voice note, and a photo never downloaded);
- what's shown large is read in memory; a video plays from PhoneKeep's private folder only;
- a chat with 3,000 photos: the Media tab opens fast and scrolls smoothly, with tiles only for the rows on screen;
- once the phone window is closed, nothing more is read from the backup.
"""
import datetime as dt, hashlib, io, json, os, plistlib, shutil, sqlite3, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
failures = []
SLACK = 5.0 if os.environ.get("CI") else 1.0          # GitHub's shared runners: only a big miss fails


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


import phonekeep as wv
import sections as sx
from PIL import Image

W = HERE / "work" / "m6"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
UDID = "00008030-M6TEST000000000000"
BK = W / "Backups" / UDID
BK.mkdir(parents=True)
ALEX, ROBIN, KIM = "+447700900111", "+447700900222", "+447700900333"
T0 = dt.datetime(2026, 3, 1, 10, 0)
BIG = 3000


def when(minutes):
    return T0 + dt.timedelta(minutes=minutes)


def ns(minutes):
    return int((when(minutes).timestamp() - wv.APPLE_EPOCH) * 1e9)


def jpeg(color):
    b = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(b, "JPEG", quality=70)
    return b.getvalue()


# -- an invented backup ------------------------------------------------------------------------------------------
with open(BK / "Info.plist", "wb") as f:
    plistlib.dump({"Device Name": "Test iPhone", "Product Type": "iPhone17,3", "Product Version": "26.5",
                   "Last Backup Date": dt.datetime(2026, 3, 10, 22, 0)}, f)
with open(BK / "Manifest.plist", "wb") as f:
    plistlib.dump({"IsEncrypted": False}, f)
man = sqlite3.connect(BK / "Manifest.db")
man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
ORIGINAL = {}                                  # file name -> its bytes, to compare with what's saved


def add_file(domain, rel, data=None, link=None):
    fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
    (BK / fid[:2]).mkdir(exist_ok=True)
    dest = BK / fid[:2] / fid
    if link is not None:
        os.link(link, dest)
    else:
        dest.write_bytes(data)
    blob = plistlib.dumps({"$objects": ["$null", {"LastModified": int(dt.datetime(2026, 3, 10).timestamp()),
                                                  "Size": dest.stat().st_size}]}, fmt=plistlib.FMT_BINARY)
    man.execute("INSERT INTO Files VALUES (?,?,?,1,?)", (fid, domain, rel, blob))
    return dest


def add_db(domain, rel, build):
    tmp = W / "db.sqlite"
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    build(con)
    con.commit()
    con.close()
    add_file(domain, rel, tmp.read_bytes())


# Messages: "Film club" (Alex) with a photo, a video, a voice note, a document and one not in the backup;
# "Book club" (a group: Alex, Robin, Kim) where Alex and Robin each send a photo; "Holiday" with 3,000 photos
FILM = [  # minute, from me, mime, file name, in the backup
    (0, 0, "image/jpeg", "IMG_0001.JPG", True), (1, 1, "video/quicktime", "IMG_0002.MOV", True),
    (2, 0, "audio/x-caf", "Audio Message.caf", True), (3, 1, "application/pdf", "Tickets.pdf", True),
    (4, 0, "image/jpeg", "IMG_0005.JPG", False)]
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
CONTENT = {"image/jpeg": None, "video/quicktime": b"\0\0\0\x18ftypqt  " + b"\0" * 64,
           "audio/x-caf": b"caff\0\x01\0\0" + b"\0" * 40, "application/pdf": PDF}
big_pic = W / "big.jpg"
big_pic.write_bytes(jpeg((200, 120, 40)))


def sms(c):
    c.executescript("""
CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id);
CREATE TABLE chat(ROWID INTEGER PRIMARY KEY, chat_identifier, display_name, style, service_name);
CREATE TABLE chat_message_join(chat_id, message_id);
CREATE TABLE chat_handle_join(chat_id, handle_id);
CREATE TABLE message(ROWID INTEGER PRIMARY KEY, text, attributedBody, handle_id, date, is_from_me, item_type,
  associated_message_type, group_title, service);
CREATE TABLE attachment(ROWID INTEGER PRIMARY KEY, filename, mime_type, transfer_name);
CREATE TABLE message_attachment_join(message_id, attachment_id);""")
    c.executemany("INSERT INTO handle VALUES (?,?)", [(1, ALEX), (2, ROBIN), (3, KIM)])
    c.executemany("INSERT INTO chat VALUES (?,?,?,?,?)", [(1, ALEX, "Film club", 45, "iMessage"),
                                                          (2, "chat900", "Book club", 43, "iMessage"),
                                                          (3, KIM, "Holiday", 45, "iMessage")])
    c.executemany("INSERT INTO chat_handle_join VALUES (?,?)", [(1, 1), (2, 1), (2, 2), (2, 3), (3, 3)])
    rid = aid = 0

    def msg(chat, minutes, handle, me, text, mime=None, name=None, here=True, k=None):
        nonlocal rid, aid
        rid += 1
        c.execute("INSERT INTO message VALUES (?,?,NULL,?,?,?,0,0,NULL,'iMessage')", (rid, text, handle, ns(minutes), me))
        c.execute("INSERT INTO chat_message_join VALUES (?,?)", (chat, rid))
        if mime:
            aid += 1
            rel = f"Library/SMS/Attachments/{aid % 100:02x}/{aid:02d}/AT{aid:05d}/{name}"
            c.execute("INSERT INTO attachment VALUES (?,?,?,?)", (aid, "~/" + rel, mime, name))
            c.execute("INSERT INTO message_attachment_join VALUES (?,?)", (rid, aid))
            if here:
                if mime == "image/jpeg" and k is None:
                    data = jpeg((40 + aid * 30, 90, 160))
                elif k is not None:
                    data = None
                else:
                    data = CONTENT[mime]
                if k is None:
                    ORIGINAL[(chat, name)] = data
                    add_file(sx.MEDIA, rel, data)
                else:                           # the big chat: one invented photo, linked (a fresh copy every 900)
                    if k % 900 == 0:
                        shutil.copyfile(W / "big.jpg", W / f"big-{k // 900}.jpg")
                    add_file(sx.MEDIA, rel, link=W / f"big-{k // 900}.jpg")

    msg(1, -1, 1, 0, "here's what I promised")
    for mins, me, mime, name, here in FILM:
        msg(1, mins, 1, me, None, mime, name, here)
    msg(2, 10, 1, 0, None, "image/jpeg", "Alex.JPG")
    msg(2, 11, 2, 0, None, "image/jpeg", "Robin.JPG")
    msg(2, 12, 3, 0, "Kim: no photo from me")
    for k in range(BIG):
        msg(3, 20 + k, 3, 0, None, "image/jpeg", f"IMG_{k:05d}.JPG", True, k)


add_db(sx.HOME, "Library/SMS/sms.db", sms)


# WhatsApp: "Running group" with a photo, a voice note and a photo never downloaded to the iPhone
def whatsapp(c):
    c.executescript("""
CREATE TABLE ZWACHATSESSION(Z_PK INTEGER PRIMARY KEY, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZARCHIVED);
CREATE TABLE ZWAMEDIAITEM(Z_PK INTEGER PRIMARY KEY, ZMEDIALOCALPATH, ZTITLE, ZLATITUDE, ZLONGITUDE, ZVCARDNAME,
 ZFILESIZE);
CREATE TABLE ZWAMESSAGE(Z_PK INTEGER PRIMARY KEY, ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,
 ZGROUPMEMBER, ZMEDIAITEM, ZFROMJID, ZSTARRED);""")
    c.execute("INSERT INTO ZWACHATSESSION VALUES (1, '447700900444@s.whatsapp.net', 'Running group', 0, 0)")
    c.executemany("INSERT INTO ZWAMEDIAITEM VALUES (?,?,?,NULL,NULL,NULL,NULL)",
                  [(1, "Media/447700900444@s.whatsapp.net/a/b/run-photo.jpg", "at the start"),
                   (2, "Media/447700900444@s.whatsapp.net/c/d/voice.opus", None),
                   (3, None, None)])
    t0 = T0.timestamp() - wv.APPLE_EPOCH
    for pk, mins, mtype, media in ((1, 0, 0, None), (2, 1, 1, 1), (3, 2, 3, 2), (4, 3, 1, 3)):
        c.execute("INSERT INTO ZWAMESSAGE VALUES (?,1,0,?,?,?,NULL,?,'447700900444@s.whatsapp.net',0)",
                  (pk, t0 + mins * 60, "see you at the park" if pk == 1 else None, mtype, media))


add_db(wv.WA_DOMAIN, "ChatStorage.sqlite", whatsapp)
WA_PHOTO, WA_VOICE = jpeg((10, 200, 90)), b"OggS" + b"\0" * 60
add_file(wv.WA_DOMAIN, "Message/Media/447700900444@s.whatsapp.net/a/b/run-photo.jpg", WA_PHOTO)
add_file(wv.WA_DOMAIN, "Message/Media/447700900444@s.whatsapp.net/c/d/voice.opus", WA_VOICE)
man.commit()
man.close()

# -- the real phone window ---------------------------------------------------------------------------------------
import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import tkinter as tk
import ui
import phone
import quicklook as ql
import app as appmod
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
played, revealed = [], []
ql.play = lambda p: played.append(Path(p))          # never opens another app
phone.reveal = lambda p: revealed.append(Path(p))
dest_dir = Path(tempfile.mkdtemp(prefix="pk-m6-"))
asked = []
ui.ask_folder = lambda parent, title: asked.append(title) or str(dest_dir)
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(W / "Backups"),
                                            "archive_dir": str(W / "Saved")}), encoding="utf-8")
a = appmod.App()
a.after_cancel(a._timers.pop("first"))


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
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


def choose(panel, name):
    iid = next(str(i) for i, (_k, _l, c) in enumerate(panel.rows) if c["name"] == name)
    panel.tree.selection_set(iid)
    panel.tree.focus(iid)
    panel._show(iid)
    a.update()


def viewer_shown(kind, timeout=15):
    return pump(lambda: ql.Viewer.current is not None and ql.Viewer.current.shown_kind == kind, timeout)


def tiles(grid):
    return [c for c in grid.pool if c.item is not None]


def saved_files(folder):
    return sorted(p.name for p in folder.iterdir())


pump(lambda: False, 0.3)
check(a.open_backup(BK), "the phone window opens on the invented backup")
win = a.phone_windows[-1]
pump(lambda: win.data is not None, 60)

# ---- Messages: clicks in the conversation ----
win.open_app("messages")
pump(lambda: find(win.content, ui.ChatPanel) is not None, 60)
panel = find(win.content, ui.ChatPanel)
choose(panel, "Film club")
text = panel.text.get("1.0", "end")
check("🎬 Video" in text and "🎤 Voice note" in text and "📄 Document" in text,
      "the conversation shows the video, the voice note and the document as links")
opens = sorted({t for t in panel.text.tag_names() if t.startswith("open")})
check(len(opens) == len(FILM), f"each of the {len(FILM)} attachments in the conversation can be clicked ({len(opens)})")
pump(lambda: panel.images, 15)
img_tagged = any(panel.text.tag_names(f"{m}") and any(t.startswith("open") for t in panel.text.tag_names(m))
                 for m in [panel.text.index(f"img{i}") for i in range(10) if f"img{i}" in panel.text.mark_names()])
check(img_tagged, "the photo itself (its thumbnail in the conversation) opens it large")

vid = next(t for t in opens if "🎬" in panel.text.get(*panel.text.tag_ranges(t)[:2]))
x, y, _w, h = panel.text.bbox(panel.text.tag_ranges(vid)[0])
panel.text.event_generate("<Motion>", x=x + 3, y=y + h // 2)      # Tk finds the tag under the pointer
panel.text.event_generate("<ButtonRelease-1>", x=x + 3, y=y + h // 2)
a.update()
v = ql.Viewer.current
check(v is not None and v.name_lbl.cget("text") == "IMG_0002.MOV" and v.pos_lbl.cget("text").startswith("2 of 5"),
      f"a click on the video opens it large, 2 of the chat's 5 attachments "
      f"({v and v.name_lbl.cget('text')!r}, {v and v.pos_lbl.cget('text')!r})")
check(viewer_shown("play"), "a video offers Play")
path = v.open_from_file(wait=True)
check(path is not None and ql.private_dir() in path.parents and path.read_bytes() == ORIGINAL[(1, "IMG_0002.MOV")]
      and played == [path], "it plays from PhoneKeep's private folder (gone when PhoneKeep closes), the same bytes")
v.event_generate("<Left>")
a.update()
check(v.name_lbl.cget("text") == "IMG_0001.JPG" and viewer_shown("image"),
      "← goes to the chat's photo before it, shown large (read in memory)")
v.event_generate("<Left>")
a.update()
check(v.name_lbl.cget("text") == "IMG_0005.JPG" and viewer_shown("error"),
      "← again wraps round to the newest, which isn't in the backup")
err = " ".join(w.cget("text") for w in v.body.winfo_children() if isinstance(w, tk.Label))
check("isn't in the backup" in err, f"  and it says so: {err!r}")
v.event_generate("<Right>")
v.event_generate("<Right>")
v.event_generate("<Right>")
a.update()
check(v.name_lbl.cget("text") == "Audio Message.caf" and viewer_shown("play"), "→ goes on to the voice note, which plays")
v.close()
a.update()

# ---- the Media tab ----
check(panel.tabs.winfo_ismapped(), "the chat has a Messages and a Media tab")
t0 = time.perf_counter()
panel.show_tab("media")
a.update()
grid = panel.media_grid
check(grid is not None and grid.winfo_ismapped() and not panel.text_frame.winfo_ismapped(),
      "the Media tab shows a grid instead of the conversation")
summary = grid.summary.cget("text")
check(summary == "2 photos · 1 video · 1 voice note or audio · 1 document · 1 not in the backup",
      f"it counts every attachment by kind: {summary!r}")
shown = [c.item.get("caption") for c in tiles(grid)]
check(shown == ["IMG_0005.JPG", "Tickets.pdf", "Audio Message.caf", "IMG_0002.MOV", "IMG_0001.JPG"],
      f"every attachment has a tile, newest first: {shown}")
pump(lambda: grid.images, 15)
check(len(grid.images) == 1, "the photo in the backup has its thumbnail; the one not in the backup has none")
gone = next(c for c in tiles(grid) if c.item.get("caption") == "IMG_0005.JPG")
check("Not in the backup" in [gone.itemcget(k, "text") for k in gone.find_all() if gone.type(k) == "text"],
      "  the one not in the backup says so on its tile")
grid.kind.set("Documents")
grid._filter()
a.update()
check([c.item.get("caption") for c in tiles(grid)] == ["Tickets.pdf"], "choosing Documents shows only the document")
grid.kind.set("All media")
grid._filter()
a.update()
pdf_tile = next(c for c in tiles(grid) if c.item.get("caption") == "Tickets.pdf")
pdf_tile.event_generate("<ButtonRelease-1>", x=5, y=5)
a.update()
v = ql.Viewer.current
check(v is not None and v.name_lbl.cget("text") == "Tickets.pdf" and v.pos_lbl.cget("text").startswith("2 of 5"),
      f"a click on a tile opens that one large, in the grid's order ({v and v.pos_lbl.cget('text')!r})")
v.event_generate("<Right>")
a.update()
check(v.name_lbl.cget("text") == "Audio Message.caf", "  → goes to the next tile")
v.close()

# ---- Save all ----
check(panel.save_media_btn.winfo_ismapped() and panel.save_media_btn.enabled, "the Media tab has Save all")
panel.save_all_media()
check(pump(lambda: panel.saving is None and getattr(panel, "saved_media", None), 30), "Save all finishes")
res = panel.saved_media
folder = dest_dir / "Film club media"
check(res["folder"] == folder and folder.is_dir() and asked and "Film club" in asked[0],
      f"it asks where, and saves into a new folder named after the chat ({res['folder']})")
names = saved_files(folder)
want = [f"{when(m):%Y-%m-%d %H.%M.%S} {n}" for m, _me, _mi, n, here in FILM if here]
check(names == sorted(want), f"every attachment in the backup is saved, named when it was sent: {names}")
dated = all(abs((folder / f"{when(m):%Y-%m-%d %H.%M.%S} {n}").stat().st_mtime - when(m).timestamp()) < 1
            for m, _me, _mi, n, here in FILM if here)
check(dated, "each file is dated when it was sent (its original date)")
check(all((folder / f"{when(m):%Y-%m-%d %H.%M.%S} {n}").read_bytes() == ORIGINAL[(1, n)]
          for m, _me, _mi, n, here in FILM if here), "each file is the attachment as it is in the backup, byte for byte")
check(res["saved"] == 4 and res["missing"] == 1 and res["failed"] == 0, f"4 saved, 1 not in the backup: {res}")
a.update()
note = grid.note.cget("text")
check("Saved 4 files" in note and "1 wasn’t in the backup" in note and not revealed
      and grid.show_btn.winfo_ismapped(), f"it says what it did, with a Show folder button: {note!r}")
grid.show_btn.event_generate("<ButtonRelease-1>")
a.update()
check(revealed == [folder], "Show folder shows the new folder")
panel.save_all_media()
pump(lambda: panel.saving is None and panel.saved_media["folder"] != folder, 30)
check((dest_dir / "Film club media (2)").is_dir() and len(saved_files(dest_dir / "Film club media (2)")) == 4,
      "a second Save all makes a second folder, never mixing into the first")

# ---- a group shown for one person (M5) ----
choose(panel, "Book club")
check(grid.summary.cget("text") == "2 photos", f"the group's Media tab: {grid.summary.cget('text')!r}")
bk_id = next(c["id"] for _k, _l, c in panel.rows if c["name"] == "Book club")
person = next(m["sender"] for m in win.data.preview.media("messages", bk_id) if m.get("caption") == "Alex.JPG")
panel.set_people("messages", bk_id, {person})
a.update()
check(grid.summary.cget("text") == "1 photo" and [c.item.get("caption") for c in tiles(grid)] == ["Alex.JPG"],
      f"shown for one person, only their attachment ({person}): {[c.item.get('caption') for c in tiles(grid)]}")
panel.save_all_media()
pump(lambda: panel.saving is None and panel.saved_media["folder"].name.startswith("Book club"), 30)
check(saved_files(panel.saved_media["folder"]) == [f"{when(10):%Y-%m-%d %H.%M.%S} Alex.JPG"],
      "Save all keeps the same choice: only their attachment is saved")
panel.set_people("messages", bk_id, set())

# ---- 3,000 photos ----
t0 = time.perf_counter()
choose(panel, "Holiday")
a.update_idletasks()
took = time.perf_counter() - t0
check(took < 1.0 * SLACK and len(grid.all) == BIG, f"a chat with {BIG:,} photos: its Media tab is filled in "
                                                    f"{took * 1000:.0f} ms (under 1 s)")
worst = 0.0
for i in range(1, 121):
    t1 = time.perf_counter()
    grid.canvas.yview_moveto(i / 120)
    a.update()
    worst = max(worst, time.perf_counter() - t1)
check(worst < 0.1 * SLACK, f"  scrolling it to the end, the slowest step takes {worst * 1000:.0f} ms (under 100 ms)")
check(len(grid.pool) < 120, f"  only the rows on screen have tiles ({len(grid.pool)} for {BIG:,})")
last_row = [c.item.get("caption") for c in tiles(grid)]
check("IMG_00000.JPG" in last_row, "  the end of the grid is the oldest photo")
panel.show_tab("messages")
a.update()
check(panel.text_frame.winfo_ismapped() and not grid.winfo_ismapped() and not panel.save_media_btn.winfo_ismapped()
      and panel.text.get("1.0", "end").count("📷 Photo") + len(panel.images) >= 600,
      "back on Messages, the conversation shows again: the chat chosen on the Media tab, drawn now")
panel.show_tab("media")
film_id = next(c["id"] for _k, _l, c in panel.rows if c["name"] == "Film club")
panel.show_chat("messages", film_id)
a.update()
check(panel.tab == "messages" and "here's what I promised" in panel.text.get("1.0", "end"),
      "a search result (E4) chosen while the Media tab is open shows its message in the conversation")

# ---- WhatsApp ----
win.show_home()
pump(lambda: False, 0.2)
win.open_app("whatsapp")
pump(lambda: find(win.content, ui.ChatPanel) is not None and find(win.content, ui.ChatPanel) is not panel, 60)
wpanel = find(win.content, ui.ChatPanel)
choose(wpanel, "Running group")
wpanel.show_tab("media")
a.update()
wgrid = wpanel.media_grid
check(wgrid.summary.cget("text") == "2 photos · 1 voice note or audio · 1 not in the backup",
      f"WhatsApp's Media tab: {wgrid.summary.cget('text')!r}")
wpanel.save_all_media()
pump(lambda: wpanel.saving is None and getattr(wpanel, "saved_media", None), 30)
wf = wpanel.saved_media["folder"]
check(saved_files(wf) == [f"{when(1):%Y-%m-%d %H.%M.%S} run-photo.jpg", f"{when(2):%Y-%m-%d %H.%M.%S} voice.opus"]
      and (wf / f"{when(1):%Y-%m-%d %H.%M.%S} run-photo.jpg").read_bytes() == WA_PHOTO
      and abs((wf / f"{when(2):%Y-%m-%d %H.%M.%S} voice.opus").stat().st_mtime - when(2).timestamp()) < 1,
      f"WhatsApp: the photo and the voice note are saved, dated when they were sent: {saved_files(wf)}")
photo_msg = next(m for m in wgrid.all if m.get("media_src", "").endswith("run-photo.jpg"))
wpanel.open_media_list("whatsapp", [photo_msg], 0)
check(viewer_shown("image"), "a WhatsApp photo opens large")
ql.Viewer.current.close()

# ---- closed: nothing more is read ----
data = win.data
pv = data.preview
m0 = pv.media("messages", next(c["id"] for _k, _l, c in panel.rows if c["name"] == "Film club"))[0]
check(pv.read_media("messages", m0) is not None, "while the window is open the attachment can be read")
data.close()
check(pump(lambda: data.closed.is_set(), 10) and pv.read_media("messages", m0) is None
      and not pv.copy_media("messages", m0, W / "after.jpg") and not (W / "after.jpg").exists(),
      "once the backup is closed, nothing more is read or copied from it")

a.destroy()
shutil.rmtree(dest_dir, ignore_errors=True)
print("\nM6 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
