"""E7: a very large invented backup (docs/spec/05-ease-of-use.md#e7-fast-with-very-large-phones).

300,000 messages in 400 chats (one chat with 10,000, the size the speed target names) and 50,000 photos and videos
over six years (every fifth a video, so the Videos collection has 10,000 to scroll through). Every name, number and word is invented. The photos are one small JPEG hard-linked 50,000 times, so the backup
takes little disk space; each has its own date. Not encrypted (the speed is the app's, not the decryption's).
Messages have M4's detail as on a real phone: most have a read time, one in 100 is a reply, one in 100 was edited,
and 3,000 reactions are rows of their own.

    python tests/make_big.py            # builds tests/work/Big/00008030-BIGTEST... once; again only if missing
"""
import datetime as dt, hashlib, io, os, plistlib, random, shutil, sqlite3, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
import phonekeep as wv
import sections as sx

MESSAGES, CHATS, BIG_CHAT, PHOTOS = 300_000, 400, 10_000, 50_000
ROOT = HERE / "work" / "Big"
UDID = "00008030-BIGTEST000000000000"
BK = ROOT / UDID
WORDS = ("see you at the station tomorrow morning", "running late, five minutes", "the holiday photos are lovely",
         "can you pick up some bread", "meeting moved to Thursday", "happy birthday!", "ok", "thanks a lot",
         "where did we park", "the film starts at eight", "call me when you can", "lunch on Friday?",
         "just landed", "the train is cancelled again", "good luck with the exam", "sounds good")


def build() -> Path:
    if (BK / "Manifest.db").exists() and (BK / "done-m4").exists():
        return BK
    shutil.rmtree(BK, ignore_errors=True)
    BK.mkdir(parents=True)
    rnd = random.Random(7)
    E = wv.APPLE_EPOCH
    start = dt.datetime(2020, 1, 1).timestamp()
    end = dt.datetime(2026, 11, 1).timestamp()
    with open(BK / "Info.plist", "wb") as f:
        plistlib.dump({"Device Name": "Big Test iPhone", "Product Type": "iPhone17,3", "Product Version": "26.5",
                       "Last Backup Date": dt.datetime(2026, 11, 10, 22, 0)}, f)
    with open(BK / "Manifest.plist", "wb") as f:
        plistlib.dump({"IsEncrypted": False}, f)
    man = sqlite3.connect(BK / "Manifest.db")
    man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")

    def fid_of(domain, rel):
        return hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()

    links: dict = {}
    copies: dict = {}

    def add(domain, rel, path: Path, mtime=None, link=False):
        fid = fid_of(domain, rel)
        (BK / fid[:2]).mkdir(exist_ok=True)
        dest = BK / fid[:2] / fid
        if link:
            # Windows (NTFS) allows 1,023 links to one file: link to a fresh copy every 1,000
            n = links[path] = links.get(path, 0) + 1
            if n % 1000 == 1:
                copies[path] = path.with_name(f"{path.stem}-{n // 1000}{path.suffix}")
                shutil.copyfile(path, copies[path])
            os.link(copies[path], dest)
        else:
            shutil.move(str(path), dest)
        blob = None
        if mtime:
            blob = plistlib.dumps({"$objects": ["$null", {"LastModified": int(mtime), "Size": path.stat().st_size
                                                          if path.exists() else dest.stat().st_size}]},
                                  fmt=plistlib.FMT_BINARY)
        return (fid, domain, rel, 1, blob)

    # Messages: 400 chats; chat 1 has 10,000 messages, the rest share the others
    tmp = ROOT / "sms.db"
    tmp.unlink(missing_ok=True)
    c = sqlite3.connect(tmp)
    c.executescript("""
CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id);
CREATE TABLE chat(ROWID INTEGER PRIMARY KEY, chat_identifier, display_name, style, service_name);
CREATE TABLE chat_message_join(chat_id, message_id);
CREATE TABLE chat_handle_join(chat_id, handle_id);
CREATE TABLE message(ROWID INTEGER PRIMARY KEY, text, attributedBody, handle_id, date, is_from_me,
  item_type, associated_message_type, group_title, service, guid UNIQUE, associated_message_guid, associated_message_emoji,
  thread_originator_guid, date_edited, date_retracted, date_read);
CREATE TABLE attachment(ROWID INTEGER PRIMARY KEY, filename, mime_type, transfer_name);
CREATE TABLE message_attachment_join(message_id, attachment_id);""")
    c.executemany("INSERT INTO handle VALUES (?,?)", [(i, f"+44770090{i:04d}") for i in range(1, CHATS + 1)])
    c.executemany("INSERT INTO chat VALUES (?,?,?,?,?)",
                  [(i, f"+44770090{i:04d}", "", 45, "iMessage") for i in range(1, CHATS + 1)])
    c.executemany("INSERT INTO chat_handle_join VALUES (?,?)", [(i, i) for i in range(1, CHATS + 1)])
    # M4's detail as on a real phone: most messages have a read time, one in 100 is a reply, one in 100 edited,
    # and 3,000 reactions (rows of their own, on top of the 300,000)
    rows, joins, chat_of = [], [], {}
    for m in range(1, MESSAGES + 1):
        chat = 1 if m <= BIG_CHAT else 2 + rnd.randrange(CHATS - 1)
        chat_of[m] = chat
        when = int((start + (end - start) * (m / MESSAGES if chat == 1 else rnd.random()) - E) * 1e9)
        rows.append((m, rnd.choice(WORDS), None, chat, when, rnd.random() < 0.5, 0, 0, None, "iMessage", f"M{m}",
                     None, None, f"M{m - 1}" if m % 100 == 0 else None, when + 60_000_000_000 if m % 100 == 50 else 0,
                     0, when + 30_000_000_000 if rnd.random() < 0.8 else 0))
        joins.append((chat, m))
    for k in range(3000):
        target = rnd.randrange(1, MESSAGES + 1)
        rid = MESSAGES + 1 + k
        rows.append((rid, "Loved a message", None, chat_of[target], rows[target - 1][4] + 1, rnd.random() < 0.5, 0,
                     2000 + rnd.randrange(6), None, "iMessage", f"R{k}", f"p:0/M{target}", None, None, 0, 0, 0))
        joins.append((chat_of[target], rid))
    c.executemany("INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.executemany("INSERT INTO chat_message_join VALUES (?,?)", joins)
    c.commit()
    c.close()
    entries = [add(sx.HOME, "Library/SMS/sms.db", tmp)]

    # Photos: one small JPEG, hard-linked, each with its own date
    from PIL import Image
    pic = ROOT / "pic.jpg"
    b = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 140, 180)).save(b, "JPEG", quality=60)
    pic.write_bytes(b.getvalue())
    mov = ROOT / "clip.mov"
    mov.write_bytes(b"\0\0\0\x18ftypqt  " + b"\0" * 64)
    for n in range(PHOTOS):                          # every fifth one a video: a Videos collection of 10,000
        when = start + (end - start) * n / PHOTOS
        video = n % 5 == 4
        entries.append(add(sx.CAMERA, f"Media/DCIM/{100 + n // 1000}APPLE/IMG_{n:05d}.{'MOV' if video else 'JPG'}",
                           mov if video else pic, when, link=True))
    man.executemany("INSERT INTO Files VALUES (?,?,?,?,?)", entries)
    man.commit()
    man.close()
    (BK / "done-m4").write_text("ok")   # done-m4: built with M4's detail (older builds are made again)
    return BK


if __name__ == "__main__":
    import time
    t = time.time()
    print("built", build(), f"in {time.time() - t:.0f} s")
