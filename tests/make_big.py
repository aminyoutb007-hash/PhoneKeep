"""E7: a very large invented backup (docs/spec/05-ease-of-use.md#e7-fast-with-very-large-phones).

300,000 messages in 400 chats (one chat with 10,000, the size the speed target names) and 50,000 photos and videos
over six years (every fifth a video, so the Videos collection has 10,000 to scroll through). Every name, number and word is invented. The photos are one small JPEG hard-linked 50,000 times, so the backup
takes little disk space; each has its own date. Not encrypted (the speed is the app's, not the decryption's).

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
    if (BK / "Manifest.db").exists() and (BK / "done").exists():
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

    def add(domain, rel, path: Path, mtime=None, link=False):
        fid = fid_of(domain, rel)
        (BK / fid[:2]).mkdir(exist_ok=True)
        dest = BK / fid[:2] / fid
        if link:
            os.link(path, dest)
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
  item_type, associated_message_type, group_title, service);
CREATE TABLE attachment(ROWID INTEGER PRIMARY KEY, filename, mime_type, transfer_name);
CREATE TABLE message_attachment_join(message_id, attachment_id);""")
    c.executemany("INSERT INTO handle VALUES (?,?)", [(i, f"+44770090{i:04d}") for i in range(1, CHATS + 1)])
    c.executemany("INSERT INTO chat VALUES (?,?,?,?,?)",
                  [(i, f"+44770090{i:04d}", "", 45, "iMessage") for i in range(1, CHATS + 1)])
    c.executemany("INSERT INTO chat_handle_join VALUES (?,?)", [(i, i) for i in range(1, CHATS + 1)])
    rows, joins = [], []
    for m in range(1, MESSAGES + 1):
        chat = 1 if m <= BIG_CHAT else 2 + rnd.randrange(CHATS - 1)
        when = start + (end - start) * (m / MESSAGES if chat == 1 else rnd.random())
        rows.append((m, rnd.choice(WORDS), None, chat, int((when - E) * 1e9), rnd.random() < 0.5, 0, 0, None,
                     "iMessage"))
        joins.append((chat, m))
    c.executemany("INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
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
    (BK / "done").write_text("ok")
    return BK


if __name__ == "__main__":
    import time
    t = time.time()
    print("built", build(), f"in {time.time() - t:.0f} s")
