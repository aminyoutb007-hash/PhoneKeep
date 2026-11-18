"""Q2: chats as on the phone.

All invented. Voice notes: the length and waveform come from the file alone, read from CAF (Messages), Ogg Opus
(WhatsApp) and MP4 (AAC) built here with a known loud-quiet-loud shape; a file that isn't one, or is broken or
hostile, gives nothing (and never hangs). On a Mac, files made by macOS's own encoder (afconvert) are read too. In a
chat (the real chat preview over an invented Messages database): a reply shows the message it quotes above it;
reactions sit after its time as marks, a mark given twice counted ("❤️ 2"); a link shows its preview card (title,
summary, site) from the rich link Messages kept, never fetched; a voice note shows ▶, its waveform and its length,
read from the backup in memory. WhatsApp's link previews come from ZWAMESSAGEDATAITEM.
"""
import datetime as dt, os, plistlib, shutil, sqlite3, struct, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep

import phonekeep as wv
import sections
import voicenote

W = HERE / "work" / "q2"
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


# -- voice notes: three containers, one shape (quiet, loud, quiet, loud, quiet) ---------------------------------
PATTERN = [20] * 50 + [180] * 50 + [20] * 50 + [180] * 50 + [20] * 100        # 300 packets of 20 ms = 6 s


def ber(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def caf(sizes, rate=48000.0, frames=960) -> bytes:
    desc = struct.pack(">d4sIII", rate, b"opus", 0, 0, frames) + struct.pack(">II", 1, 0)
    table = b"".join(ber(s) for s in sizes)
    pakt = struct.pack(">qqii", len(sizes), len(sizes) * frames, 0, 0) + table
    audio = b"\0" * 4 + bytes(sum(sizes))
    chunk = lambda k, body: k + struct.pack(">q", len(body)) + body
    return b"caff" + struct.pack(">HH", 1, 0) + chunk(b"desc", desc) + chunk(b"pakt", pakt) + chunk(b"data", audio)


def ogg(sizes, pre_skip=312) -> bytes:
    def page(packets, granule, seq, flags=0):
        lacing = b""
        for p in packets:
            n = len(p)
            lacing += b"\xff" * (n // 255) + bytes([n % 255])
        head = b"OggS" + bytes([0, flags]) + struct.pack("<qIII", granule, 7, seq, 0) + bytes([len(lacing)])
        return head + lacing + b"".join(packets)
    head = b"OpusHead" + bytes([1, 1]) + struct.pack("<HIhB", pre_skip, 48000, 0, 0)
    out = page([head], 0, 0, 2) + page([b"OpusTags" + b"\0" * 8], 0, 1)
    for n in range(0, len(sizes), 50):           # 50 packets (1 s) a page
        chunk = sizes[n:n + 50]
        out += page([bytes([0xFC]) * s for s in chunk], pre_skip + (n + len(chunk)) * 960, 2 + n // 50)
    return out


def mp4(sizes, scale=48000, per=1024) -> bytes:
    box = lambda k, body: struct.pack(">I", 8 + len(body)) + k + body
    mdhd = box(b"mdhd", b"\0" * 4 + struct.pack(">IIII", 0, 0, scale, len(sizes) * per) + b"\0" * 4)
    hdlr = box(b"hdlr", b"\0" * 8 + b"soun" + b"\0" * 12)
    stsz = box(b"stsz", b"\0" * 4 + struct.pack(">II", 0, len(sizes)) + struct.pack(f">{len(sizes)}I", *sizes))
    moov = box(b"moov", box(b"trak", box(b"mdia", mdhd + hdlr + box(b"minf", box(b"stbl", stsz)))))
    return box(b"ftyp", b"M4A " + b"\0" * 4) + moov + box(b"mdat", bytes(sum(sizes)))


def loud_quiet(bars):
    """The 12 bars of PATTERN: quiet, loud, quiet, loud, then quiet."""
    loud = [i for i, b in enumerate(bars) if b > 0.7]
    quiet = [i for i, b in enumerate(bars) if b < 0.3]
    return loud == [2, 3, 6, 7] and quiet == [0, 1, 4, 5, 8, 9, 10, 11]


for name, data, seconds in (("CAF (Messages)", caf(PATTERN), 6.0), ("Ogg Opus (WhatsApp)", ogg(PATTERN), 6.0),
                            ("MP4 / M4A (AAC)", mp4(PATTERN), len(PATTERN) * 1024 / 48000)):
    got = voicenote.shape(data, 12)
    check(got is not None and abs(got[0] - seconds) < 0.01 and loud_quiet(got[1]),
          f"a voice note in {name}: its length and its shape from the packet sizes "
          f"({got and round(got[0], 2)} s, {got and [round(b, 1) for b in got[1]]})")

check(voicenote.fmt(7) == "0:07" and voicenote.fmt(65.4) == "1:05" and voicenote.fmt(3723) == "1:02:03",
      "lengths written as the phone writes them (0:07, 1:05, 1:02:03)")
bad = [b"", b"not audio at all", b"caff" + b"\xff" * 40, b"OggS" + b"\0" * 30, caf(PATTERN)[:200],
       ogg(PATTERN)[:300], mp4(PATTERN)[:120], b"\0\0\0\x10ftypM4A " + b"\0\0\0\x08moov",
       b"caff\0\1\0\0pakt" + struct.pack(">q", 40) + struct.pack(">qqii", 10**9, 0, 0, 0) + b"\xff" * 16]
t0 = time.time()
check(all(voicenote.shape(b) is None for b in bad) and time.time() - t0 < 2,
      "a file that isn't a voice note, or is cut short or made to mislead, gives nothing, and quickly")

if sys.platform == "darwin" and shutil.which("afconvert"):
    import math, random, wave
    rate, frames = 48000, []
    for i in range(rate * 6):
        loud = int(i / rate) in (1, 3)
        a = (0.6 * math.sin(2 * math.pi * 220 * i / rate) + 0.3 * random.uniform(-1, 1)) if loud else 0.002 * random.uniform(-1, 1)
        frames.append(int(max(-1, min(1, a)) * 32000))
    with wave.open(str(W / "t.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    subprocess.run(["afconvert", "-f", "caff", "-d", "opus", str(W / "t.wav"), str(W / "t.caf")], check=True)
    got = voicenote.shape((W / "t.caf").read_bytes(), 12)
    check(got is not None and abs(got[0] - 6.0) < 0.1 and loud_quiet(got[1]),
          f"  a voice note made by macOS's own Opus encoder: 6 s, its two loud seconds where they are ({got and round(got[0], 2)} s)")

# -- Messages: replies, reactions, link previews, voice notes ------------------------------------------------------
ALEX = "+447700900111"
NAMES = {ALEX: "Alex Example"}


def ns(minute):
    return int((dt.datetime(2026, 3, 1, 10, minute).timestamp() - wv.APPLE_EPOCH) * 1e9)


def rich_link_payload(title, site, summary, url) -> bytes:
    """A link's payload as Messages archives it (NSKeyedArchiver: RichLink -> LPLinkMetadata -> NSURL)."""
    U = plistlib.UID
    objs = ["$null",
            {"richLinkMetadata": U(2), "richLinkIsPlaceholder": False, "$class": U(9)},
            {"title": U(3), "siteName": U(4), "summary": U(5), "URL": U(6), "originalURL": U(6), "$class": U(8)},
            title, site, summary,
            {"NS.base": U(0), "NS.relative": U(7), "$class": U(10)}, url,
            {"$classname": "LPLinkMetadata", "$classes": ["LPLinkMetadata", "NSObject"]},
            {"$classname": "RichLink", "$classes": ["RichLink", "NSObject"]},
            {"$classname": "NSURL", "$classes": ["NSURL", "NSObject"]}]
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": U(1)},
                           "$objects": objs}, fmt=plistlib.FMT_BINARY)


VOICE_REL = "Library/SMS/Attachments/ab/12/AUDIO/Audio Message.caf"
sms = W / "sms.db"
c = sqlite3.connect(sms)
c.executescript("""
CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id);
CREATE TABLE chat(ROWID INTEGER PRIMARY KEY, chat_identifier, display_name, style, service_name);
CREATE TABLE chat_message_join(chat_id, message_id);
CREATE TABLE chat_handle_join(chat_id, handle_id);
CREATE TABLE attachment(ROWID INTEGER PRIMARY KEY, filename, mime_type, transfer_name);
CREATE TABLE message_attachment_join(message_id, attachment_id);
CREATE TABLE message(ROWID INTEGER PRIMARY KEY, text, attributedBody, handle_id, date, is_from_me, item_type,
  associated_message_type, group_title, service, guid, associated_message_guid, associated_message_emoji,
  thread_originator_guid, balloon_bundle_id, payload_data);""")
c.execute("INSERT INTO handle VALUES (1, ?)", (ALEX,))
c.execute("INSERT INTO chat VALUES (1, ?, '', 45, 'iMessage')", (ALEX,))
URLB = "com.apple.messages.URLBalloonProvider"
rows = [  # id, text, from me, minute, assoc type, guid, assoc guid, emoji, reply to, balloon, payload
    (1, "Dinner at eight?", 0, 0, 0, "G1", None, None, None, None, None),
    (2, "Yes, see you there", 1, 1, 0, "G2", None, None, "G1", None, None),
    (3, "Loved “Dinner at eight?”", 0, 2, 2000, "R1", "p:0/G1", None, None, None, None),
    (4, "Loved “Dinner at eight?”", 1, 3, 2000, "R2", "p:0/G1", None, None, None, None),
    (5, "Reacted 🎉", 0, 4, 2006, "R3", "p:0/G2", "🎉", None, None, None),
    (6, "https://example.invalid/recipes/soup", 0, 5, 0, "G3", None, None, None, URLB,
     rich_link_payload("Tomato soup in 20 minutes", "Example Recipes", "A quick soup for cold evenings.",
                       "https://example.invalid/recipes/soup")),
    (7, None, 0, 6, 0, "G4", None, None, None, None, None),
    (8, "https://example.invalid/broken", 1, 7, 0, "G5", None, None, None, URLB, b"not a plist"),
]
for rid, text, me, minute, kind, guid, aguid, emoji, reply, balloon, payload in rows:
    c.execute("INSERT INTO message VALUES (?,?,NULL,1,?,?,0,?,NULL,'iMessage',?,?,?,?,?,?)",
              (rid, text, ns(minute), me, kind, guid, aguid, emoji, reply, balloon, payload))
    c.execute("INSERT INTO chat_message_join VALUES (1, ?)", (rid,))
c.execute("INSERT INTO attachment VALUES (1, ?, 'audio/x-caf', 'Audio Message.caf')", ("~/" + VOICE_REL,))
c.execute("INSERT INTO message_attachment_join VALUES (7, 1)")
c.commit()
c.close()


class Ctx:
    """What load_messages and the chat preview need: the database, the backup's files, names, its file contents."""
    def __init__(self):
        self.cache = {}
        self.reads = []
        self.tmp = W / "tmp"

    def db(self, domain, rel):
        con = sqlite3.connect(sms)
        con.row_factory = sqlite3.Row
        return con

    def files(self, domain):
        return {VOICE_REL: "f" * 40} if domain == sections.MEDIA else {}

    def label(self, addr):
        return NAMES.get(addr) or addr or "Unknown"

    def read(self, domain, rel):
        self.reads.append((domain, rel))
        return caf(PATTERN) if (domain, rel) == (sections.MEDIA, VOICE_REL) else None


ctx = Ctx()
chats = sections.load_messages(ctx)
ctx.cache["messages"] = chats
msgs = chats[0]["messages"]
by_text = {m.get("text"): m for m in msgs}
check(by_text["Yes, see you there"]["detail"]["reply_to"] == "Dinner at eight?", "a reply knows the message it quotes")
check(by_text["Dinner at eight?"]["detail"]["reacted"] == ["❤️", "❤️"]
      and by_text["Yes, see you there"]["detail"]["reacted"] == ["🎉"],
      "reactions are kept as the marks the phone shows (❤️ for Loved, the emoji itself for an emoji reaction)")
link = by_text["https://example.invalid/recipes/soup"].get("link")
check(link == {"title": "Tomato soup in 20 minutes", "site": "Example Recipes",
               "summary": "A quick soup for cold evenings.", "url": "https://example.invalid/recipes/soup"},
      f"a link's preview comes from the rich link Messages kept: {link}")
check("link" not in by_text["https://example.invalid/broken"], "  a payload that isn't one gives no card")
check(sections.rich_link(b"x" * 3_000_000) is None and sections.rich_link(plistlib.dumps({"$objects": [{"title": 5}]})) is None,
      "  a payload too big or without a link gives none")

# the chat as drawn
import tkinter as tk
import ui

root = tk.Tk()
root.withdraw()
preview = sections.ChatPreview(ctx)
lists = {"messages": ("Messages", [{"id": 1, "name": "Alex Example", "group": False, "messages": len(msgs),
                                    "last": "2026-03-01", "first": "2026-03-01", "days": ["2026-03-01"]}])}
panel = ui.ChatPanel(root, lists, preview=preview)
panel.pack(fill="both", expand=True)
root.update()
panel.show_chat("messages", 1)
end = time.time() + 10
while time.time() < end and not getattr(panel, "voice_canvases", None):
    root.update()
    time.sleep(0.02)
t = panel.text
text = t.get("1.0", "end")


def tagged(tag):
    r = t.tag_ranges(tag)
    return [t.get(r[i], r[i + 1]) for i in range(0, len(r), 2)]


check("▎Dinner at eight?\n" in tagged("quote") and text.index("▎Dinner at eight?") < text.index("Yes, see you there"),
      "a reply shows the message it quotes, above it")
check(any("❤️ 2" in x for x in tagged("react")) and any(x.strip() == "🎉" for x in tagged("react")),
      f"reactions sit after the message's time, a mark given twice counted: {tagged('react')}")
check(tagged("ltitle") == ["▎Tomato soup in 20 minutes\n"]
      and "".join(tagged("lmore")) == "▎A quick soup for cold evenings.\n▎Example Recipes\n",
      f"a link shows its preview card: title, summary and site ({tagged('ltitle')}, {tagged('lmore')})")
check(not any(t.tk.call(t._w, "tag", "bind", g, e) for g in ("ltitle", "lmore") for e in ("<ButtonRelease-1>", "<Button-1>")),
      "  the card doesn't open anything (PhoneKeep never goes online)")
cv = (panel.voice_canvases or [None])[0]
labels = [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"] if cv else []
bars = [i for i in cv.find_all() if cv.type(i) == "line"] if cv else []
check(cv is not None and labels == ["0:06"] and len(bars) == voicenote.BARS and "🎤 Voice note" not in t.get("1.0", "end"),
      f"a voice note shows ▶, its waveform ({len(bars)} bars) and its length {labels}, in place of the label")
check(ctx.reads == [(sections.MEDIA, VOICE_REL)] and not any((W / "tmp").rglob("*.caf")),
      "  read from the backup in memory, once (nothing written to disk)")
opened = []
panel.open_media = lambda k, cid, m: opened.append(m.get("caption"))
root.deiconify()                              # a hidden window gets no clicks
root.update()
cv.event_generate("<ButtonRelease-1>", x=10, y=10)
root.update()
check(opened == ["Audio Message.caf"], "  a click on it opens the voice note (to play it)")
panel.current = None                          # drawn again from the start
panel.show_chat("messages", 1)
root.update()
check(not cv.winfo_exists(), "  drawing the chat again lets go of the old voice note drawing")
root.destroy()

# -- WhatsApp: link previews from ZWAMESSAGEDATAITEM -----------------------------------------------------------
wa = W / "ChatStorage.sqlite"
c = sqlite3.connect(wa)
c.executescript("""
CREATE TABLE ZWACHATSESSION(Z_PK INTEGER PRIMARY KEY, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZARCHIVED);
CREATE TABLE ZWAMESSAGE(Z_PK INTEGER PRIMARY KEY, ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,
 ZGROUPMEMBER, ZMEDIAITEM, ZFROMJID, ZSTARRED);
CREATE TABLE ZWAMESSAGEDATAITEM(Z_PK INTEGER PRIMARY KEY, ZINDEX, ZMESSAGE, ZTITLE, ZSUMMARY, ZMATCHEDTEXT, ZCONTENT1);""")
c.execute("INSERT INTO ZWACHATSESSION VALUES (1, '447700900456@s.whatsapp.net', 'Alex Example', 0, 0)")
c.executemany("INSERT INTO ZWAMESSAGE VALUES (?,1,0,?,?,0,NULL,NULL,'447700900456@s.whatsapp.net',0)",
              [(1, 790000000, "Look: https://example.invalid/a and https://example.invalid/b"), (2, 790000060, "No link")])
c.executemany("INSERT INTO ZWAMESSAGEDATAITEM VALUES (?,?,?,?,?,?,?)",
              [(1, 1, 1, "Second page", None, "https://example.invalid/b", None),
               (2, 0, 1, "First page", "What the first page is about", "https://example.invalid/a", None)])
c.commit()
c.close()
got = {m["text"]: m for m in wv.parse_whatsapp(wa, log=lambda *a: None)[0]["messages"]}
check(got["Look: https://example.invalid/a and https://example.invalid/b"].get("link")
      == {"title": "First page", "summary": "What the first page is about", "url": "https://example.invalid/a"}
      and "link" not in got["No link"],
      "WhatsApp: a link's preview (the first link of the message) from what WhatsApp kept")

print("\nQ2 TESTS:", "FAIL" if failures else "PASS", flush=True)
os._exit(1 if failures else 0)
