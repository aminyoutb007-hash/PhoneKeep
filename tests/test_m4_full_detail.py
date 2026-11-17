"""M4: full detail in Excel and CSV (docs/spec/06-messages.md#m4-full-detail-in-excel-and-csv).

Done when: "A chat with replies, reactions and an edited message shows all three in Excel."
Checked on an invented Messages database and an invented WhatsApp database (every name and number is made up):
- the chat spreadsheets keep their first seven columns and add Reply to, Reactions, Edited at, Deleted at,
  Read at, Service and Group sender number, in Excel and in CSV;
- a reply shows the text it quotes; reactions sit on the message they react to (and aren't rows of their own); a
  reaction taken back disappears, a person's later reaction replaces their earlier one;
- an edited message has its edit time, an unsent one says it was deleted and when, read times are there;
- the service is iMessage or SMS per message, WhatsApp for WhatsApp chats; the group sender's number is in groups;
- a reply quoting "=HYPERLINK(...)" stays plain text (Excel: a text cell; CSV: a leading apostrophe);
- the search word filter still matches a message's own words only, not the text a reply quotes;
- an older Messages database without these columns still saves, with those cells blank;
- WhatsApp: only the group sender's number is read (a hidden-number @lid member has none).
"""
import csv, datetime as dt, os, shutil, sqlite3, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

import exportfilter as ef
import phonekeep as wv
import sections as sx
import tables as tb
from openpyxl import load_workbook

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


W = HERE / "work" / "m4"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)


def ns(*when):
    """A local time as Messages stores it: nanoseconds since 1 Jan 2001."""
    return int((dt.datetime(*when).timestamp() - wv.APPLE_EPOCH) * 1e9)


ALEX, ROBIN = "+447700900111", "+447700900222"
NAMES = {ALEX: "Alex Example", ROBIN: "Robin Test"}
FORMULA = '=HYPERLINK("http://example.invalid","click")'


def make_sms(path: Path, new: bool = True):
    c = sqlite3.connect(path)
    extra = ", guid, associated_message_guid, associated_message_emoji, thread_originator_guid, date_edited, " \
            "date_retracted, date_read" if new else ""
    c.executescript(f"""
CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id);
CREATE TABLE chat(ROWID INTEGER PRIMARY KEY, chat_identifier, display_name, style, service_name);
CREATE TABLE chat_message_join(chat_id, message_id);
CREATE TABLE chat_handle_join(chat_id, handle_id);
CREATE TABLE message(ROWID INTEGER PRIMARY KEY, text, attributedBody, handle_id, date, is_from_me, item_type,
  associated_message_type, group_title, service{extra});""")
    c.executemany("INSERT INTO handle VALUES (?,?)", [(1, ALEX), (2, ROBIN)])
    c.executemany("INSERT INTO chat VALUES (?,?,?,?,?)", [(1, ALEX, "", 45, "iMessage"),
                                                          (2, "chat900", "Book club", 43, "iMessage"),
                                                          (3, ALEX, "", 45, "SMS")])
    c.executemany("INSERT INTO chat_handle_join VALUES (?,?)", [(2, 1), (2, 2)])
    #   id, chat, text, handle, from me, minute, service, assoc type, guid, assoc guid, emoji, reply to, edited, retracted, read
    rows = [
        (1, 1, FORMULA, 1, 0, 0, "iMessage", 0, "G1", None, None, None, None, None, ns(2026, 3, 1, 10, 5)),
        (2, 1, "Yes, see you at eight", 0, 1, 1, "iMessage", 0, "G2", None, None, "G1", None, None, ns(2026, 3, 1, 10, 9)),
        (3, 1, "Loved “Yes, see you at eight”", 1, 0, 2, "iMessage", 2000, "R1", "p:0/G2", None, None, None, None, None),
        (4, 1, "Liked", 0, 1, 3, "iMessage", 2001, "R2", "p:0/G1", None, None, None, None, None),
        (5, 1, "Removed a like", 0, 1, 4, "iMessage", 3001, "R3", "p:0/G1", None, None, None, None, None),
        (6, 1, "Laughed", 1, 0, 5, "iMessage", 2003, "R4", "p:0/G1", None, None, None, None, None),
        (7, 1, "Reacted 🎉", 1, 0, 6, "iMessage", 2006, "R5", "p:0/G1", "🎉", None, None, None, None),
        (8, 1, "Running ten minutes late", 0, 1, 7, "iMessage", 0, "G3", None, None, None, ns(2026, 3, 1, 10, 12), None, None),
        (9, 1, None, 0, 1, 8, "iMessage", 0, "G4", None, None, None, ns(2026, 3, 1, 10, 13), ns(2026, 3, 1, 10, 14), None),
        (10, 1, "Sent as a text message", 0, 1, 9, "SMS", 0, "G5", None, None, None, None, None, None),
        (11, 2, "Chapter five next week", 2, 0, 10, "iMessage", 0, "G6", None, None, None, None, None, None),
        (12, 2, "Agreed", 0, 1, 11, "iMessage", 0, "G7", None, None, None, None, None, None),
        (13, 3, "From the SMS thread", 1, 0, 12, "SMS", 0, "G8", None, None, None, None, None, None),
    ]
    for (rid, chat, text, h, me, mins, svc, kind, guid, aguid, emoji, reply, edited, retracted, read) in rows:
        if new:
            c.execute("INSERT INTO message VALUES (?,?,NULL,?,?,?,0,?,NULL,?,?,?,?,?,?,?,?)",
                      (rid, text, h, ns(2026, 3, 1, 10, mins), me, kind, svc, guid, aguid, emoji, reply, edited,
                       retracted, read))
        else:
            c.execute("INSERT INTO message VALUES (?,?,NULL,?,?,?,0,?,NULL,?)",
                      (rid, text, h, ns(2026, 3, 1, 10, mins), me, kind, svc))
        c.execute("INSERT INTO chat_message_join VALUES (?,?)", (chat, rid))
    c.commit()
    c.close()


class Ctx:
    """What load_messages needs from sections.Ctx: the database, the backup's media files and contact names."""
    def __init__(self, path):
        self.path = path

    def db(self, domain, rel):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def files(self, domain):
        return {}

    def label(self, addr):
        return NAMES.get(addr) or addr or "Unknown"


def sheet_rows(path, sheet):
    ws = load_workbook(path)[sheet]
    head = [c.value for c in ws[1]]
    return head, [{h: c for h, c in zip(head, row)} for row in ws.iter_rows(min_row=2)]


def csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = list(csv.reader(f))
    return r[0], [dict(zip(r[0], row)) for row in r[1:]]


# -- Messages ------------------------------------------------------------------------------------------------------
make_sms(W / "sms.db")
chats = sx.load_messages(Ctx(W / "sms.db"))
one = next(c for c in chats if not c["group"])
group = next(c for c in chats if c["group"])
check(len(one["messages"]) == 6,
      f"reactions aren't rows of their own: 6 messages in the chat (its SMS thread merged in) ({len(one['messages'])})")

xlsx = tb.write_chats_xlsx(chats, W / "Messages chats.xlsx", "Messages", lambda m: None)
head, rows = sheet_rows(xlsx, "Alex Example")
check(head[:7] == ["Date", "Time", "Sender", "Message", "Type", "Attachment", "Starred"],
      "Excel: the first seven columns are as before")
check(head[7:] == ["Reply to", "Reactions", "Edited at", "Deleted at", "Read at", "Service", "Group sender number"],
      f"Excel: the seven new columns follow: {head[7:]}")
by = {r["Message"].value: r for r in rows}
reply = by["Yes, see you at eight"]
check(reply["Reply to"].value == FORMULA and reply["Reply to"].data_type == "s",
      "Excel: a reply shows the text it quotes, as a text cell (a quoted formula stays text)")
check(by[FORMULA]["Message"].data_type == "s", "Excel: the formula-looking message itself is a text cell")
check(reply["Reactions"].value == "Love (Alex Example)", f"Excel: a reaction sits on its message: {reply['Reactions'].value!r}")
first = by[FORMULA]
check(first["Reactions"].value == "🎉 (Alex Example)",
      f"Excel: a reaction taken back is gone, a later one by the same person replaces theirs: {first['Reactions'].value!r}")
edited = by["Running ten minutes late"]
check(edited["Edited at"].value == dt.datetime(2026, 3, 1, 10, 12) and edited["Edited at"].number_format == "yyyy-mm-dd hh:mm",
      f"Excel: an edited message has its edit time as a date: {edited['Edited at'].value}")
gone = by["This message was deleted"]
check(gone["Deleted at"].value == dt.datetime(2026, 3, 1, 10, 14) and gone["Type"].value == "deleted"
      and gone["Edited at"].value is None, "Excel: an unsent message says it was deleted, and when")
check(first["Read at"].value == dt.datetime(2026, 3, 1, 10, 5) and reply["Read at"].value == dt.datetime(2026, 3, 1, 10, 9),
      "Excel: read times are there")
check(first["Service"].value == "iMessage" and by["Sent as a text message"]["Service"].value == "SMS"
      and by["From the SMS thread"]["Service"].value == "SMS",
      "Excel: the service is per message (iMessage, SMS)")
check(all(r["Group sender number"].value is None for r in rows), "Excel: no group sender number outside groups")
ghead, grows = sheet_rows(xlsx, "Book club")
gby = {r["Message"].value: r for r in grows}
check(gby["Chapter five next week"]["Group sender number"].value == ROBIN and gby["Agreed"]["Group sender number"].value is None,
      "Excel: in a group, the sender's number (none on your own messages)")

tb.write_chats_csv(chats, W / "CSV", lambda m: None)
chead, crows = csv_rows(W / "CSV" / "Alex Example.csv")
check(chead == tb.HEADERS, "CSV: the same columns as Excel")
cby = {r["Message"]: r for r in crows}
creply = cby["Yes, see you at eight"]
check(creply["Reply to"] == "'" + FORMULA, f"CSV: a quoted formula gets a leading apostrophe: {creply['Reply to']!r}")
check(creply["Reactions"] == "Love (Alex Example)" and cby["'" + FORMULA]["Reactions"] == "🎉 (Alex Example)",
      "CSV: the reactions")
check(cby["Running ten minutes late"]["Edited at"] == "2026-03-01 10:12:00"
      and cby["This message was deleted"]["Deleted at"] == "2026-03-01 10:14:00"
      and cby["'" + FORMULA]["Read at"] == "2026-03-01 10:05:00", "CSV: edited, deleted and read times")
check(cby["Sent as a text message"]["Service"] == "SMS", "CSV: the service")
ahead, arows = csv_rows(W / "CSV" / "_All chats.csv")
check(ahead == ["Chat"] + tb.HEADERS and any(r["Group sender number"] == "'" + ROBIN for r in arows),
      "CSV: all chats in one file, with the group sender's number (a leading + gets the apostrophe, as before)")

kept = ef.Filter(None, "HYPERLINK").chats(chats)
check([m["text"] for c in kept for m in c["messages"]] == [FORMULA],
      "the search word filter matches a message's own words, not the text a reply quotes")

# -- an older Messages database without these columns ---------------------------------------------------------------
make_sms(W / "old.db", new=False)
try:
    old = sx.load_messages(Ctx(W / "old.db"))
    tb.write_chats_xlsx(old, W / "old.xlsx", "Messages", lambda m: None)
    ohead, orows = sheet_rows(W / "old.xlsx", "Alex Example")
    check(ohead == tb.HEADERS and all(r["Reply to"].value is None and r["Edited at"].value is None for r in orows)
          and orows[0]["Service"].value == "iMessage", "an older Messages database still saves; the new cells are blank")
except Exception as e:
    check(False, f"an older Messages database still saves ({type(e).__name__}: {e})")

# -- WhatsApp ----------------------------------------------------------------------------------------------------
wa = W / "ChatStorage.sqlite"
c = sqlite3.connect(wa)
c.executescript("""
CREATE TABLE ZWACHATSESSION(Z_PK INTEGER PRIMARY KEY, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZARCHIVED);
CREATE TABLE ZWAGROUPMEMBER(Z_PK INTEGER PRIMARY KEY, ZMEMBERJID, ZCONTACTNAME, ZFIRSTNAME);
CREATE TABLE ZWAMESSAGE(Z_PK INTEGER PRIMARY KEY, ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,
  ZGROUPMEMBER, ZMEDIAITEM, ZFROMJID, ZSTARRED);""")
c.executemany("INSERT INTO ZWACHATSESSION VALUES (?,?,?,?,0)",
              [(1, "120363000@g.us", "Hiking group", 1), (2, "447700900444@s.whatsapp.net", "Sam Sample", 0)])
c.executemany("INSERT INTO ZWAGROUPMEMBER VALUES (?,?,?,NULL)",
              [(1, "447700900333@s.whatsapp.net", "Jo Invented"), (2, "123456789@lid", "Kim Placeholder")])
base = dt.datetime(2026, 3, 2, 9, 0).timestamp() - wv.APPLE_EPOCH
c.executemany("INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,0,?,NULL,?,0)", [
    (1, 1, 0, base, "Meet at the car park", 1, "120363000@g.us"),
    (2, 1, 0, base + 60, "Running late", 2, "120363000@g.us"),
    (3, 1, 1, base + 120, "On my way", None, None),
    (4, 2, 0, base + 180, "Lunch?", None, "447700900444@s.whatsapp.net")])
c.commit()
c.close()
wchats = wv.parse_whatsapp(wa, lambda m: None)
tb.write_chats_xlsx(wchats, W / "WhatsApp chats.xlsx", "WhatsApp", lambda m: None)
whead, wrows = sheet_rows(W / "WhatsApp chats.xlsx", "Hiking group")
wby = {r["Message"].value: r for r in wrows}
check(wby["Meet at the car park"]["Group sender number"].value == "+447700900333",
      "WhatsApp: a group sender's number")
check(wby["Running late"]["Group sender number"].value is None and wby["On my way"]["Group sender number"].value is None,
      "WhatsApp: no number for a hidden-number (@lid) member or for your own messages")
check(all(r["Service"].value == "WhatsApp" for r in wrows), "WhatsApp: the service says WhatsApp")
check(all(r[k].value is None for r in wrows for k in ("Reply to", "Reactions", "Edited at", "Deleted at", "Read at")),
      "WhatsApp: replies, reactions, edits, deletions and read times are left blank (the backup doesn't say them reliably)")
_, prows = sheet_rows(W / "WhatsApp chats.xlsx", "Sam Sample")
check(prows[0]["Group sender number"].value is None, "WhatsApp: no group number in a one-to-one chat")
tb.write_chats_csv(wchats, W / "WA-CSV", lambda m: None, service="WhatsApp Business")
_, wcsv = csv_rows(W / "WA-CSV" / "Hiking group.csv")
check(all(r["Service"] == "WhatsApp Business" for r in wcsv), "WhatsApp CSV: the service the export passes in")

print("\nM4 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
sys.exit(1 if failures else 0)
