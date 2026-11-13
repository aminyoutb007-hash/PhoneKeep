"""Build a simulated iPhone backup with every supported data type, then run the full export."""
import datetime as dt, gzip, hashlib, io, plistlib, shutil, sqlite3, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
import os
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
import phonekeep as wv
import sections as sx

W = HERE / "work"
shutil.rmtree(W, ignore_errors=True)
root = W / "Backups" / "00008030-FULLTEST"
root.mkdir(parents=True)
E = wv.APPLE_EPOCH
t0 = dt.datetime(2025, 6, 1, 10, 0).timestamp() - E

with open(root / "Info.plist", "wb") as f:
    plistlib.dump({"Device Name": "Amine's iPhone", "Product Type": "iPhone16,2", "Product Version": "26.1",
                   "Last Backup Date": dt.datetime(2026, 11, 10, 22, 0), "Phone Number": "+44 7700 900000",
                   "Installed Applications": ["net.whatsapp.WhatsApp", "com.spotify.client"]}, f)
with open(root / "Manifest.plist", "wb") as f:
    plistlib.dump({"IsEncrypted": False}, f)

man = sqlite3.connect(root / "Manifest.db")
man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")


def add(domain, rel, data: bytes, mtime=None):
    fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
    (root / fid[:2]).mkdir(exist_ok=True)
    (root / fid[:2] / fid).write_bytes(data)
    blob = None
    if mtime:
        blob = plistlib.dumps({"$objects": ["$null", {"LastModified": int(mtime), "Size": len(data)}]},
                              fmt=plistlib.FMT_BINARY)
    man.execute("INSERT INTO Files VALUES (?,?,?,1,?)", (fid, domain, rel, blob))


def db(script, rows=()):
    p = W / "tmp.sqlite"
    p.unlink(missing_ok=True)
    c = sqlite3.connect(p)
    c.executescript(script)
    for sql, vals in rows:
        c.executemany(sql, vals)
    c.commit(); c.close()
    return p.read_bytes()


# Contacts
add(sx.HOME, "Library/AddressBook/AddressBook.sqlitedb", db("""
CREATE TABLE ABPerson(ROWID INTEGER PRIMARY KEY, First, Last, Middle, Organization, Nickname, JobTitle, Note, Birthday);
CREATE TABLE ABMultiValue(UID INTEGER PRIMARY KEY, record_id, property, identifier, label, value);
CREATE TABLE ABMultiValueLabel(ROWID INTEGER PRIMARY KEY, value);""", [
    ("INSERT INTO ABPerson VALUES (?,?,?,?,?,?,?,?,?)",
     [(1, "Sara", "Fathi", None, None, None, None, "Sister", str((dt.datetime(1995, 4, 12) - dt.datetime(2001, 1, 1)).total_seconds())),
      (2, "Karim", "B", None, "Acme Ltd", None, "CTO", None, None),
      (3, None, None, None, "Dentist, Smile & Co", None, None, None, None)]),
    ("INSERT INTO ABMultiValueLabel VALUES (?,?)", [(1, "_$!<Mobile>!$_"), (2, "_$!<Work>!$_")]),
    ("INSERT INTO ABMultiValue(record_id,property,label,value) VALUES (?,?,?,?)",
     [(1, 3, 1, "+44 7700 900123"), (1, 4, 2, "sara@example.com"), (2, 3, 1, "07700 900456"),
      (3, 3, 2, "020 7946 0000")])]))

# Messages
add(sx.HOME, "Library/SMS/sms.db", db("""
CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id);
CREATE TABLE chat(ROWID INTEGER PRIMARY KEY, chat_identifier, display_name, style, service_name);
CREATE TABLE chat_message_join(chat_id, message_id);
CREATE TABLE chat_handle_join(chat_id, handle_id);
CREATE TABLE message(ROWID INTEGER PRIMARY KEY, text, attributedBody, handle_id, date, is_from_me,
  item_type, associated_message_type, group_title, service);
CREATE TABLE attachment(ROWID INTEGER PRIMARY KEY, filename, mime_type, transfer_name);
CREATE TABLE message_attachment_join(message_id, attachment_id);""", [
    ("INSERT INTO handle VALUES (?,?)", [(1, "+447700900123"), (2, "+447700900456"), (3, "+447700900789")]),
    ("INSERT INTO chat VALUES (?,?,?,?,?)", [(1, "+447700900123", "", 45, "iMessage"),
                                           (2, "+447700900123", "", 45, "SMS"),
                                           (3, "chat99", "", 43, "iMessage")]),
    ("INSERT INTO chat_handle_join VALUES (?,?)", [(3, 1), (3, 2), (3, 3)]),
    ("INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (1, "Did you land?", None, 1, int(t0 * 1e9), 0, 0, 0, None, "iMessage"),
        (2, None, b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+\x0eYes, just now!\x86", 0, int((t0 + 60) * 1e9), 1, 0, 0, None, "iMessage"),
        (3, "￼", None, 1, int((t0 + 120) * 1e9), 0, 0, 0, None, "iMessage"),
        (4, "Loved “Yes”", None, 1, int((t0 + 130) * 1e9), 0, 0, 2000, None, "iMessage"),
        (5, "Your code is 123456", None, 1, int((t0 - 86400) * 1e9), 0, 0, 0, None, "SMS"),
        (6, "Dinner Friday?", None, 2, int((t0 + 500) * 1e9), 0, 0, 0, None, "iMessage"),
        (7, None, None, 3, int((t0 + 400) * 1e9), 0, 2, 0, "Friends 🎉", "iMessage")]),
    ("INSERT INTO chat_message_join VALUES (?,?)", [(1, 1), (1, 2), (1, 3), (1, 4), (2, 5), (3, 6), (3, 7)]),
    ("INSERT INTO attachment VALUES (?,?,?,?)", [(1, "~/Library/SMS/Attachments/ab/01/G1/IMG_0001.jpeg", "image/jpeg", "IMG_0001.jpeg")]),
    ("INSERT INTO message_attachment_join VALUES (?,?)", [(3, 1)])]))

from PIL import Image
def jpeg(color, size=(800, 600), exif_date=None):
    im = Image.new("RGB", size, color)
    b = io.BytesIO()
    kw = {}
    if exif_date:
        ex = Image.Exif(); ex[306] = exif_date; kw["exif"] = ex.tobytes()
    im.save(b, "JPEG", **kw)
    return b.getvalue()
add(sx.MEDIA, "Library/SMS/Attachments/ab/01/G1/IMG_0001.jpeg", jpeg((200, 80, 60)))

# Photos (camera roll) incl. a Live Photo pair and a video
add(sx.CAMERA, "Media/DCIM/100APPLE/IMG_0100.JPG", jpeg((30, 120, 200), exif_date="2024:08:15 14:20:00"), t0)
add(sx.CAMERA, "Media/DCIM/100APPLE/IMG_0101.JPG", jpeg((60, 180, 90), exif_date="2025:06:01 09:00:00"), t0)
add(sx.CAMERA, "Media/DCIM/100APPLE/IMG_0101.MOV", b"\0\0\0\x18ftypqt  " + b"\0" * 64, t0)
add(sx.CAMERA, "Media/DCIM/100APPLE/IMG_0102.MOV", b"\0\0\0\x18ftypqt  " + b"\0" * 64, t0 + 3600)
add(sx.CAMERA, "Media/DCIM/100APPLE/IMG_0100.AAE", b"<plist/>", t0)

# Calls
add(sx.HOME, "Library/CallHistoryDB/CallHistory.storedata", db("""
CREATE TABLE ZCALLRECORD(Z_PK INTEGER PRIMARY KEY, ZADDRESS, ZDATE, ZDURATION, ZORIGINATED, ZANSWERED,
 ZSERVICE_PROVIDER, ZNAME, ZCALLTYPE, ZLOCATION);""", [
    ("INSERT INTO ZCALLRECORD VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (1, b"+447700900123", t0, 125.4, 1, 1, "com.apple.Telephony", None, 1, "United Kingdom"),
        (2, "+447700900456", t0 + 900, 0, 0, 0, "com.apple.Telephony", None, 1, None),
        (3, "sara@example.com", t0 + 1800, 3700, 0, 1, "com.apple.FaceTime", None, 8, None)])]))

# Notes (gzipped protobuf: 2 -> 3 -> 2 = text)
def pb_len(field, payload: bytes) -> bytes:
    def varint(n):
        out = b""
        while True:
            b7 = n & 0x7F; n >>= 7
            out += bytes([b7 | (0x80 if n else 0)])
            if not n: return out
    return varint((field << 3) | 2) + varint(len(payload)) + payload
note_body = "Shopping\nMilk\nEggs\nhttps://example.org/recipe"
proto = pb_len(2, b"\x08\x00" + pb_len(3, b"\x08\x00" + pb_len(2, note_body.encode())))
add("AppDomainGroup-group.com.apple.notes", "NoteStore.sqlite", db("""
CREATE TABLE ZICCLOUDSYNCINGOBJECT(Z_PK INTEGER PRIMARY KEY, ZTITLE1, ZTITLE2, ZSNIPPET, ZFOLDER, ZNOTEDATA,
 ZCREATIONDATE1, ZCREATIONDATE3, ZMODIFICATIONDATE1, ZISPASSWORDPROTECTED, ZMARKEDFORDELETION);
CREATE TABLE ZICNOTEDATA(Z_PK INTEGER PRIMARY KEY, ZNOTE, ZDATA);""", [
    ("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (1, None, "Personal", None, None, None, None, None, None, 0, 0),
        (2, "Shopping", None, "Milk", 1, 10, t0, None, t0 + 50, 0, 0),
        (3, "Bank PINs", None, "", 1, 11, t0, None, t0, 1, 0)]),
    ("INSERT INTO ZICNOTEDATA VALUES (?,?,?)", [(10, 2, gzip.compress(proto)), (11, 3, b"\x00encrypted")])]))

# Calendar
add(sx.HOME, "Library/Calendar/Calendar.sqlitedb", db("""
CREATE TABLE CalendarItem(ROWID INTEGER PRIMARY KEY, summary, start_date, end_date, all_day, location_id,
 description, calendar_id, unique_identifier);
CREATE TABLE Location(ROWID INTEGER PRIMARY KEY, title);
CREATE TABLE Calendar(ROWID INTEGER PRIMARY KEY, title);""", [
    ("INSERT INTO Location VALUES (?,?)", [(1, "Cheshunt, UK")]),
    ("INSERT INTO Calendar VALUES (?,?)", [(1, "Home")]),
    ("INSERT INTO CalendarItem VALUES (?,?,?,?,?,?,?,?,?)", [
        (1, "Dentist, check-up", t0 + 86400 * 3, t0 + 86400 * 3 + 1800, 0, 1, "Bring card; arrive early", 1, "UID-1"),
        (2, "Sara's birthday", t0 + 86400 * 10, t0 + 86400 * 11, 1, None, None, 1, "UID-2")])]))

# Voicemail
add(sx.HOME, "Library/Voicemail/voicemail.db", db("""
CREATE TABLE voicemail(ROWID INTEGER PRIMARY KEY, remote_uid, date, sender, callback_num, duration, trashed_date);""",
    [("INSERT INTO voicemail VALUES (?,?,?,?,?,?,?)", [(7, 1, int(t0 + E), "+447700900456", None, 21, 0)])]))
add(sx.HOME, "Library/Voicemail/7.amr", b"#!AMR\n" + b"\0" * 32)

# Voice memos
vm = "AppDomainGroup-group.com.apple.VoiceMemos.shared"
add(vm, "Recordings/20250601 100000-ABCD.m4a", b"\0\0\0\x18ftypM4A " + b"\0" * 64, t0 + E)
add(vm, "Recordings/CloudRecordings.db", db("""
CREATE TABLE ZCLOUDRECORDING(Z_PK INTEGER PRIMARY KEY, ZPATH, ZCUSTOMLABEL, ZENCRYPTEDTITLE, ZDATE, ZDURATION);""",
    [("INSERT INTO ZCLOUDRECORDING VALUES (?,?,?,?,?,?)",
      [(1, "/var/mobile/Recordings/20250601 100000-ABCD.m4a", "Song idea: chorus", None, t0, 42.5)])]))

# Safari
add(sx.HOME, "Library/Safari/Bookmarks.db", db("""
CREATE TABLE bookmarks(id INTEGER PRIMARY KEY, title, url, type, parent, special_id);""",
    [("INSERT INTO bookmarks VALUES (?,?,?,?,?,?)",
      [(1, "Favorites", None, 1, 0, 0), (2, "BBC News", "https://www.bbc.co.uk/news", 0, 1, 0),
       (3, "bm", "javascript:alert(1)", 0, 1, 0)])]))
add("AppDomain-com.apple.mobilesafari", "Library/Safari/History.db", db("""
CREATE TABLE history_items(id INTEGER PRIMARY KEY, url);
CREATE TABLE history_visits(id INTEGER PRIMARY KEY, history_item, visit_time, title);""", [
    ("INSERT INTO history_items VALUES (?,?)", [(1, "https://github.com/doronz88/pymobiledevice3")]),
    ("INSERT INTO history_visits VALUES (?,?,?,?)", [(1, 1, t0 + 100, "pymobiledevice3 on GitHub")])]))

# Apps + WhatsApp (reuse a tiny WhatsApp DB with an unnamed chat that Contacts should name)
add("AppDomain-com.spotify.client", "Documents/settings.plist", b"<plist/>")
add(wv.WA_DOMAIN, "ChatStorage.sqlite", db("""
CREATE TABLE ZWACHATSESSION(Z_PK INTEGER PRIMARY KEY, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZARCHIVED);
CREATE TABLE ZWAMESSAGE(Z_PK INTEGER PRIMARY KEY, ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,
 ZGROUPMEMBER, ZMEDIAITEM, ZFROMJID, ZSTARRED);""", [
    ("INSERT INTO ZWACHATSESSION VALUES (?,?,?,?,?)", [(1, "447700900456@s.whatsapp.net", None, 0, 0)]),
    ("INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,?,?,?,?,?)",
     [(1, 1, 0, t0, "Salam! WhatsApp test", 0, None, None, "447700900456@s.whatsapp.net", 0)])]))
man.commit(); man.close()

out = W / "Archive"
idx = sx.export_all(root, out, sections=sx.DEFAULT_SECTIONS + ["files"])
print("INDEX", idx)
# second run should be incremental and still work
sx.export_all(root, out, sections=["photos", "notes"], log=lambda m: None)
print("SECOND RUN OK")
