"""Adds photos (several months, a Live Photo, a video, iOS thumbnails) and WhatsApp picture messages
to tests/work/biz/backup, for picker screenshots and tests."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import sys, sqlite3, hashlib, io, plistlib, datetime as dt, math, random
import phonekeep as pk
from pathlib import Path
from PIL import Image, ImageDraw
root = Path('tests/work/biz/backup')
man = sqlite3.connect(root / 'Manifest.db')
def add(dom, rel, data, mtime):
    fid = hashlib.sha1(f"{dom}-{rel}".encode()).hexdigest(); (root / fid[:2]).mkdir(exist_ok=True)
    (root / fid[:2] / fid).write_bytes(data)
    blob = plistlib.dumps({"$objects": ["$null", {"LastModified": int(mtime), "Size": len(data)}]}, fmt=plistlib.FMT_BINARY)
    man.execute("insert or replace into Files values (?,?,?,1,?)", (fid, dom, rel, blob))
def pic(seed, size=(1200, 900)):
    random.seed(seed); im = Image.new("RGB", size); d = ImageDraw.Draw(im)
    a = [random.randint(40, 230) for _ in range(6)]
    for y in range(size[1]):
        t = y / size[1]; d.line([(0, y), (size[0], y)], fill=tuple(int(a[i] * (1 - t) + a[i + 3] * t) for i in range(3)))
    for _ in range(5):
        x, y, r = random.randint(0, size[0]), random.randint(0, size[1]), random.randint(60, 260)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(random.randint(30, 255) for _ in range(3)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=80); return b.getvalue()
n = 0
for month, count in ((dt.datetime(2026, 11, 3), 14), (dt.datetime(2026, 10, 12), 9), (dt.datetime(2026, 8, 20), 7)):
    for k in range(count):
        n += 1; name = f"IMG_{1000 + n:04d}"
        when = (month + dt.timedelta(hours=k * 7)).timestamp()
        add(pk_dom := "CameraRollDomain", f"Media/DCIM/100APPLE/{name}.JPG", pic(n), when)
        if k % 3 == 0:  # iOS's own small thumbnail
            add(pk_dom, f"Media/PhotoData/Thumbnails/V2/DCIM/100APPLE/{name}.JPG/5005.JPG", pic(n, (320, 240)), when)
        if k == 1:  # Live Photo companion
            add(pk_dom, f"Media/DCIM/100APPLE/{name}.MOV", b"\0\0\0\x18ftypqt  " + b"\0" * 64, when)
    add("CameraRollDomain", f"Media/DCIM/100APPLE/IMG_{1100 + n:04d}.MOV", b"\0\0\0\x18ftypqt  " + b"\0" * 64, month.timestamp())
# WhatsApp Business: a customer chat with photos and longer conversation
fid = man.execute("select fileID from Files where domain=? and relativePath='ChatStorage.sqlite'", (pk.WA_BUSINESS_DOMAIN,)).fetchone()[0]
db = sqlite3.connect(root / fid[:2] / fid)
db.execute("CREATE TABLE IF NOT EXISTS ZWAMEDIAITEM(Z_PK INTEGER PRIMARY KEY, ZMESSAGE, ZMEDIALOCALPATH, ZTITLE, ZLATITUDE, ZLONGITUDE, ZVCARDNAME)")
t0 = dt.datetime(2026, 11, 9, 9, 15).timestamp() - pk.APPLE_EPOCH
conv = [(0, "Hi! Do you have the blue sofa in stock?"), (1, "Yes we do 😊 here's a photo"), (1, "@img1"),
        (0, "Lovely. What's the delivery time to Cheshunt?"), (1, "2–3 working days. Delivery is £25."),
        (0, "Great, I'll take it. Can I pay by card on delivery?"), (1, "Of course. Order #4471 confirmed ✅"),
        (0, "@img2"), (0, "This is the space where it'll go"), (1, "Perfect, it'll fit nicely!")]
for i, (me, txt) in enumerate(conv):
    pkid = 100 + i; media = None
    if txt.startswith("@img"):
        rel = f"Message/Media/447700900111@s.whatsapp.net/a/b/{txt[1:]}.jpg"
        add(pk.WA_BUSINESS_DOMAIN, rel, pic(500 + i, (900, 700)), t0)
        db.execute("insert into ZWAMEDIAITEM(Z_PK,ZMESSAGE,ZMEDIALOCALPATH) values (?,?,?)", (pkid, pkid, rel[len('Message/'):]))
        media = pkid; txt = None
    db.execute("insert into ZWAMESSAGE(Z_PK,ZCHATSESSION,ZISFROMME,ZMESSAGEDATE,ZTEXT,ZMESSAGETYPE,ZMEDIAITEM) values (?,?,?,?,?,?,?)",
               (pkid, 1, me, t0 + i * 240, txt, 1 if media else 0, media))
db.commit(); db.close(); man.commit(); print("rich data ok")
