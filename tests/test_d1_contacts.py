"""D1: Contacts (docs/spec/08-personal-data.md#d1-contacts).

Done when: "Contact photos and groups match the phone; a saved .vcf imports into Contacts / Outlook with photos."
In the real phone window, on an invented backup (every name, number, address and picture is made up):
- the same person in two accounts (a linked card, as the phone keeps them) is one contact, with the phone's preferred
  name and photo, and nothing shown twice;
- each contact's photo is the one the phone shows (its own thumbnail; the full-size picture, cropped, when there's no
  thumbnail); a contact without one shows their initials; a photo kept only as a link on the internet isn't fetched;
- the sidebar has the phone's Lists with their counts: All contacts, every account, every group; a click shows only
  that list;
- the contact card shows numbers, emails, addresses, websites, birthday, lists and note; a click copies a number,
  an email, an address or a link (and does nothing else);
- Save as vCard: one file with every contact shown (or the ones selected), each with its photo, address, website,
  custom label and groups, lines folded at 75 bytes; saving where one of the same name is asks Keep both / Replace /
  Skip, and does what was chosen; Excel and CSV have every column, with the text safe from formulas;
- the web export's contacts.vcf has the photos too; the whole-phone search (E4) finds a contact by their address.
"""
import base64, datetime as dt, hashlib, io, json, os, plistlib, shutil, socket, sqlite3, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import faulthandler
faulthandler.dump_traceback_later(240, exit=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


connects = []                                     # nothing may go to the internet (the internet-only photo)
_real_connect = socket.socket.connect


def no_connect(self, addr):
    connects.append(addr)
    raise OSError("no network in this test")


socket.socket.connect = no_connect
socket.create_connection = lambda addr, *a, **k: (connects.append(addr), (_ for _ in ()).throw(OSError("no network")))[1]

import phonekeep as wv
import sections as sx
from PIL import Image

W = HERE / "work" / "d1"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
UDID = "00008030-D1TEST000000000000"
BK = W / "Backups" / UDID
BK.mkdir(parents=True)


def picture(color, size, fmt="JPEG"):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, fmt)
    return b.getvalue()


RED, BLUE, GREEN = (200, 30, 30), (30, 60, 200), (30, 160, 60)

with open(BK / "Info.plist", "wb") as f:
    plistlib.dump({"Device Name": "Test iPhone", "Product Type": "iPhone17,3", "Product Version": "26.5",
                   "Last Backup Date": dt.datetime(2026, 3, 10, 22, 0)}, f)
with open(BK / "Manifest.plist", "wb") as f:
    plistlib.dump({"IsEncrypted": False}, f)
man = sqlite3.connect(BK / "Manifest.db")
man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")


def add_db(rel, script, rows):
    tmp = W / "db.sqlite"
    tmp.unlink(missing_ok=True)
    c = sqlite3.connect(tmp)
    c.executescript(script)
    for sql, values in rows:
        c.executemany(sql, values)
    c.commit()
    c.close()
    fid = hashlib.sha1(f"{sx.HOME}-{rel}".encode()).hexdigest()
    (BK / fid[:2]).mkdir(exist_ok=True)
    shutil.copyfile(tmp, BK / fid[:2] / fid)
    man.execute("INSERT INTO Files VALUES (?,?,?,1,NULL)", (fid, sx.HOME, rel))


# AddressBook as iOS 26 keeps it (the columns PhoneKeep reads; the real one has more)
add_db("Library/AddressBook/AddressBook.sqlitedb", """
CREATE TABLE ABPerson(ROWID INTEGER PRIMARY KEY, First, Last, Middle, Organization, Nickname, JobTitle, Note, Birthday,
  StoreID, PersonLink, ImageURI);
CREATE TABLE ABMultiValue(UID INTEGER PRIMARY KEY, record_id, property, identifier, label, value, guid);
CREATE TABLE ABMultiValueLabel(value);
CREATE TABLE ABMultiValueEntry(parent_id, key, value);
CREATE TABLE ABMultiValueEntryKey(value);
CREATE TABLE ABStore(ROWID INTEGER PRIMARY KEY, Name, Enabled);
CREATE TABLE ABGroup(ROWID INTEGER PRIMARY KEY, Name);
CREATE TABLE ABGroupMembers(UID INTEGER PRIMARY KEY, group_id, member_type, member_id);
CREATE TABLE ABPersonLink(ROWID INTEGER PRIMARY KEY, PreferredImagePersonID, PreferredNamePersonID);""", [
    ("INSERT INTO ABStore VALUES (?,?,?)", [(1, "iCloud", 1), (2, "Gmail", 1)]),
    ("INSERT INTO ABPerson VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "Alex", "Example", None, None, None, None, None,
         (dt.datetime(1990, 1, 1) - dt.datetime(2001, 1, 1)).total_seconds(), 1, None, None),
        (2, "Robin", "Sample", None, None, None, None, None, None, 2, -1, None),
        (3, "Kim", "Test", None, None, None, None, "met at the book fair", None, 1, 1, None),
        (4, "Kimberly", "Test", None, None, None, None, None, None, 2, 1, None),
        (5, None, None, None, "Dentist, Smile & Co", None, None, '=HYPERLINK("http://example.com","x")', None, 1,
         None, "https://example.com/only-online.jpg"),
        (6, "Sam", "Nophoto", None, None, None, None, None, None, 2, None, None)]),
    ("INSERT INTO ABPersonLink VALUES (?,?,?)", [(1, 3, 4)]),       # Kim: name from card 4, photo from card 3
    ("INSERT INTO ABMultiValueLabel(rowid, value) VALUES (?,?)",
     [(1, "_$!<Mobile>!$_"), (2, "_$!<Home>!$_"), (3, "Boat"), (4, "_$!<HomePage>!$_")]),
    ("INSERT INTO ABMultiValueEntryKey(rowid, value) VALUES (?,?)",
     [(1, "Street"), (2, "City"), (3, "ZIP"), (4, "Country"), (5, "CountryCode")]),
    ("INSERT INTO ABMultiValue(UID, record_id, property, label, value) VALUES (?,?,?,?,?)", [
        (1, 1, 3, 1, "+44 7700 900111"), (2, 1, 4, 2, "alex@example.com"), (3, 1, 5, 2, None),
        (4, 1, 22, 4, "https://example.com/alex"),
        (5, 2, 3, 3, "+44 7700 900222"),
        (6, 3, 3, 1, "+44 7700 900333"), (7, 4, 3, 1, "07700 900333"), (8, 4, 4, 2, "kim@example.org"),
        (9, 5, 3, None, "020 7946 0000"), (10, 6, 3, 1, "+44 7700 900666")]),
    ("INSERT INTO ABMultiValueEntry VALUES (?,?,?)",
     [(3, 1, "1 Test Street"), (3, 2, "Testbury"), (3, 3, "TE1 1ST"), (3, 4, "United Kingdom"), (3, 5, "gb")]),
    ("INSERT INTO ABGroup VALUES (?,?)", [(1, "Book club"), (2, "Running")]),
    ("INSERT INTO ABGroupMembers(group_id, member_type, member_id) VALUES (?,?,?)",
     [(1, 0, 1), (1, 0, 2), (2, 0, 6), (2, 1, 1)])])        # the last: a group inside a group, not a person

FULL = Image.new("RGB", (400, 300), BLUE)
FULL.paste(Image.new("RGB", (200, 200), (250, 250, 0)), (150, 60))     # the cropped square: yellow
fb = io.BytesIO()
FULL.save(fb, "JPEG", quality=95)
add_db("Library/AddressBook/AddressBookImages.sqlitedb", """
CREATE TABLE ABThumbnailImage(ROWID INTEGER PRIMARY KEY, record_id, format, derived_from_format, data);
CREATE TABLE ABFullSizeImage(ROWID INTEGER PRIMARY KEY, record_id, crop_x, crop_y, crop_width, data);""", [
    ("INSERT INTO ABThumbnailImage(record_id, format, data) VALUES (?,?,?)", [
        (1, 0, picture(RED, (52, 52))), (1, 5, picture(RED, (320, 320), "PNG")), (1, 4, None),
        (3, 0, picture(GREEN, (126, 126))), (4, 0, b"not a picture")]),
    # Robin: only the full-size picture; the crop is measured from the bottom (y 40 from the bottom = 60 from the top)
    ("INSERT INTO ABFullSizeImage(record_id, crop_x, crop_y, crop_width, data) VALUES (?,?,?,?,?)",
     [(2, 150, 40, 200, fb.getvalue())])])
man.commit()
man.close()

# -- the reader on its own ---------------------------------------------------------------------------------------
r = wv.BackupReader(BK, None, lambda m: None)
ctx = sx.Ctx(r, W / "o", lambda m: None, True, wv.backup_info(BK))
people = sx.load_contacts(ctx)
by = {p["name"]: p for p in people}
check(sorted(by) == ["Alex Example", "Dentist, Smile & Co", "Kimberly Test", "Robin Sample", "Sam Nophoto"],
      f"the linked cards are one contact, with the phone's preferred name: {sorted(by)}")
kim = by.get("Kimberly Test", {})
check(len(kim.get("phones", [])) == 1 and kim.get("emails") == [("home", "kim@example.org")]
      and sorted(kim.get("accounts", [])) == ["Gmail", "iCloud"] and kim.get("note") == "met at the book fair",
      f"…with both cards' details and the same number once: {kim.get('phones')}, {kim.get('emails')}, {kim.get('accounts')}")
alex = by["Alex Example"]
check(alex["addresses"] == [("home", "1 Test Street\nTestbury TE1 1ST\nUnited Kingdom")]
      and alex["urls"] == [("homepage", "https://example.com/alex")] and alex["groups"] == ["Book club"],
      f"addresses, websites and groups are read: {alex['addresses']}, {alex['urls']}, {alex['groups']}")
lists = sx.contact_lists(people)
check(lists == [("All Gmail", 3), ("All iCloud", 3), ("Book club", 2), ("Running", 1)],
      f"the phone's Lists with their counts (a group inside a group isn't a person): {lists}")
n = sx.load_contact_photos(ctx, people)
check(n == 3 and {p["name"] for p in people if p.get("photo")} == {"Alex Example", "Robin Sample", "Kimberly Test"},
      f"three contacts have a photo ({n}); the one kept only on the internet isn't fetched")
check(Image.open(io.BytesIO(alex["photo"])).size == (320, 320), "Alex: the phone's biggest thumbnail is used")
rob = Image.open(io.BytesIO(by["Robin Sample"]["photo"])).convert("RGB")
yellow = [all(abs(c - t) < 40 for c, t in zip(rob.getpixel(xy), (250, 250, 0))) for xy in ((100, 6), (100, 194))]
check(rob.size == (200, 200) and all(yellow),
      f"Robin: no thumbnail, so the full-size picture cropped where the phone crops it, top to bottom ({rob.size}, {yellow})")
check(Image.open(io.BytesIO(kim["photo"])).convert("RGB").getpixel((5, 5))[1] > 120,
      "Kim: the photo of the card the phone prefers for the photo")
check(not connects, f"nothing was fetched from the internet: {connects}")

# vCard text on its own
card = sx.vcard(alex)
lines = card.split("\r\n")
check(card.endswith("END:VCARD\r\n") and all(len(x.encode()) <= 75 for x in lines),
      "a vCard's lines end with CRLF and are folded at 75 bytes")
unfolded = card.replace("\r\n ", "")
check("ADR;TYPE=HOME:;;1 Test Street;Testbury;;TE1 1ST;United Kingdom" in unfolded
      and "URL:https://example.com/alex" in unfolded and "CATEGORIES:Book club" in unfolded
      and "TEL;TYPE=CELL:+44 7700 900111" in unfolded and "BDAY:1990-01-01" in unfolded,
      "Alex's vCard has the address, website, group, number and birthday")
photo_line = next(x for x in unfolded.split("\r\n") if x.startswith("PHOTO;"))
pic = Image.open(io.BytesIO(base64.b64decode(photo_line.split(":", 1)[1])))
check(pic.format == "JPEG" and pic.convert("RGB").getpixel((10, 10))[0] > 150, "…and the photo, as a JPEG")
rcard = sx.vcard(by["Robin Sample"]).replace("\r\n ", "")
check("item1.TEL;TYPE=VOICE:+44 7700 900222" in rcard and "item1.X-ABLabel:Boat" in rcard,
      "a label the owner typed is kept, the way Apple's own vCards keep it")
r.close()


class OneDb:
    """A stand-in for the backup: just a picture database."""
    def __init__(self, rows):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE ABFullSizeImage(ROWID INTEGER PRIMARY KEY, record_id, crop_x, crop_y, crop_width, data)")
        self.con.executemany("INSERT INTO ABFullSizeImage(record_id, crop_x, crop_y, crop_width, data) VALUES (?,?,?,?,?)", rows)

    def db(self, domain, rel):
        return self.con if rel.endswith("AddressBookImages.sqlitedb") else None


edge = Image.new("RGB", (300, 200), (128, 128, 128))
edge.paste(Image.new("RGB", (150, 150), (250, 250, 0)), (0, 50))        # the bottom-left square: yellow
eb = io.BytesIO()
edge.save(eb, "JPEG", quality=95)
jo = {"id": 7, "ids": [7]}
sx.load_contact_photos(OneDb([(7, 0, 0, 150, eb.getvalue())]), [jo])
jim = Image.open(io.BytesIO(jo["photo"])).convert("RGB")
corners = [all(abs(c - t) < 40 for c, t in zip(jim.getpixel(xy), (250, 250, 0))) for xy in ((4, 4), (145, 145))]
check(jim.size == (150, 150) and all(corners),
      f"a picture cropped at the very edge (0, 0: the bottom left) is cropped there, not in the middle ({corners})")
odd = sx.vcard({"name": "Jo Edge", "first": "Jo", "last": "Edge", "org": "", "title": "",
                "note": "line one\r\nline two\rline three", "birthday": "1604-03-05",
                "addresses": [("home", "1 Test Street\r\nTestbury")], "adr": {}})
check("\r" not in odd.replace("\r\n", "") and "NOTE:line one\\nline two\\nline three" in odd.replace("\r\n ", ""),
      "a note or address with Windows or old Mac line ends has no bare CR in the vCard: each line end is \\n")
check("BDAY:--0305" in odd and sx.birthday_text("1604-03-05") == "5 March" and sx.birthday_text("1990-01-01") == "1 January 1990"
      and sx.contact_row({"name": "J", "org": "", "title": "", "note": "", "birthday": "1604-03-05"})[7] == "03-05",
      "a birthday saved without a year (iOS keeps 1604) shows and saves with no year")

# -- the real phone window ---------------------------------------------------------------------------------------
import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import tkinter as tk
import ui
import phone
import contacts_ui
import app as appmod
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
dest_dir = Path(tempfile.mkdtemp(prefix="pk-d1-"))
phone.ask_save_folder = lambda parent, title, start: str(dest_dir)
answers = []
contacts_ui.ask_conflict = lambda parent, name: answers.append(name) or choice
choice = "skip"
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


pump(lambda: False, 0.3)
check(a.open_backup(BK), "the phone window opens on the invented backup")
win = a.phone_windows[-1]
pump(lambda: win.data is not None and "contacts" in win.counts, 60)
check(win.counts.get("contacts") == "5" and not any(p.get("photo") for p in win.data.contacts),
      f"the home screen counts contacts as the phone does ({win.counts.get('contacts')}), without reading photos yet")
win.open_app("contacts")
pump(lambda: getattr(win, "contacts_view", None) is not None, 30)
v = win.contacts_view
check(v is not None, "Contacts opens")
side = [(v.lists.item(i, "text"), v.lists.item(i, "values")[0]) for i in v.lists.get_children()]
check(side == [("All contacts", "5"), ("All Gmail", "3"), ("All iCloud", "3"), ("Book club", "2"), ("Running", "1")],
      f"the sidebar has the phone's Lists with counts: {side}")
rows = [v.tree.item(i, "text").strip() for i in v.tree.get_children()]
check(len(rows) == 5 and all(v.tree.item(i, "image") for i in v.tree.get_children()),
      f"every contact has a picture in the list (a photo or initials): {rows}")
photo_keys = {k[0] for k in v.images if isinstance(k[0], int)}
check(photo_keys == {by[n]["id"] for n in ("Alex Example", "Robin Sample", "Kimberly Test")}
      and "SN" in {k[0] for k in v.images}, "three show their photo; Sam shows his initials")
check(win.view_sub.cget("text") == "5 contacts · 3 with a photo", f"the header: {win.view_sub.cget('text')!r}")

v.lists.selection_set("l3")
a.update()
check([v.tree.item(i, "text").strip() for i in v.tree.get_children()] == ["Alex Example", "Robin Sample"]
      and v.count.cget("text") == "2 of 2", "a click on Book club shows only its two people")
v.lists.selection_set("l1")
a.update()
check(sorted(v.tree.item(i, "text").strip() for i in v.tree.get_children())
      == ["Kimberly Test", "Robin Sample", "Sam Nophoto"], "All Gmail shows that account's contacts")
v.lists.selection_set("l0")
a.update()
v.q.set("boat")
a.update()
check([v.tree.item(i, "text").strip() for i in v.tree.get_children()] == ["Robin Sample"],
      "the search finds a contact by a label")
v.q.set("")
a.update()

# the card
v.tree.selection_set(str(alex["id"]))
a.update()
texts = [w.cget("text") for w in v.card_inner.winfo_children()[0].winfo_children()]
check("Alex Example" in texts and v.card_photo.cget("image"), "a click on Alex shows his card with his photo")
kinds = [(k, val) for k, _w, val in v.links]
check(kinds == [("phone number", "+44 7700 900111"), ("email address", "alex@example.com"),
                ("address", "1 Test Street\nTestbury TE1 1ST\nUnited Kingdom"), ("web address", "https://example.com/alex")],
      f"the number, email, address and website can be clicked: {kinds}")
fields = [w.cget("text") for w in v.card_inner.winfo_children()[1].winfo_children()]
check("1 January 1990" in fields and "iCloud, Book club" in fields, "…the birthday and his lists are there too")
for kind, w, val in v.links:
    w.event_generate("<Button-1>")
    a.update()
    check(a.clipboard_get() == val and win.bar_text.cget("text") == f"✓ Copied the {kind}",
          f"a click on the {kind} copies it and says so")
check(not connects, "copying opened nothing and sent nothing")


# -- saving -----------------------------------------------------------------------------------------------------
def wait_file(p, timeout=20):
    return pump(lambda: p.exists() and not p.with_name(p.name + ".part").exists(), timeout)


dlg = contacts_ui.ConflictDialog(win, "Contacts.vcf")
a.update()
said = [w.cget("text") for w in dlg.winfo_children() if isinstance(w, tk.Label)]
buttons = sorted(b.text for b in dlg.winfo_children()[-1].winfo_children() if hasattr(b, "text"))
dlg.pick("replace")
check("“Contacts.vcf” is already in this folder." in said and buttons == ["Keep both", "Replace", "Skip"]
      and dlg.result == "replace" and not dlg.winfo_exists(),
      f"the question when the file is there: {said[:1]}, buttons {buttons}; a click answers it and closes it")
v.tree.selection_remove(*v.tree.selection())
a.update()
v.save_vcard()
out = dest_dir / "Contacts.vcf"
check(wait_file(out), "Save as vCard with nothing selected saves everything shown, as Contacts.vcf")
text = out.read_bytes().decode("utf-8")
cards = text.count("BEGIN:VCARD")
photos = text.replace("\r\n ", "").count("\r\nPHOTO;ENCODING=b;TYPE=JPEG:")
check(cards == 5 and photos == 3 and text.count("END:VCARD\r\n") == 5,
      f"it has all 5 contacts and the 3 photos ({cards}, {photos})")
first = out.read_bytes()
choice = "skip"
v.save_vcard()
pump(lambda: False, 0.5)
check(answers == ["Contacts.vcf"] and out.read_bytes() == first and sorted(p.name for p in dest_dir.iterdir()) == ["Contacts.vcf"],
      "saving again asks Keep both / Replace / Skip; Skip leaves the file as it was")
choice = "both"
v.save_vcard()
check(wait_file(dest_dir / "Contacts (2).vcf"), "Keep both saves Contacts (2).vcf next to it")
out.write_text("something else", encoding="utf-8")
choice = "replace"
v.save_vcard()
check(pump(lambda: out.read_bytes() == first, 20) and len(answers) == 3, "Replace saves over it")
choice = None
v.save_vcard()
pump(lambda: False, 0.5)
check(out.read_bytes() == first and len(list(dest_dir.iterdir())) == 2, "closing the question saves nothing")
v.tree.selection_set(str(by["Robin Sample"]["id"]))
a.update()
v.save_vcard()
check(wait_file(dest_dir / "Robin Sample.vcf") and (dest_dir / "Robin Sample.vcf").read_text("utf-8").count("BEGIN:VCARD") == 1,
      "one contact selected: saved as Robin Sample.vcf")
v.tree.selection_remove(*v.tree.selection())
v.lists.selection_set("l3")
a.update()
v.save_vcard()
check(wait_file(dest_dir / "Book club.vcf") and (dest_dir / "Book club.vcf").read_text("utf-8").count("BEGIN:VCARD") == 2,
      "a list shown: saved under its name")
v.lists.selection_set("l0")
a.update()

v.save_table("excel")
pump(lambda: list(dest_dir.glob("Contacts *.xlsx")), 20)
x = next(iter(dest_dir.glob("Contacts *.xlsx")), None)
from openpyxl import load_workbook
ws = load_workbook(x).active if x else None
hdr = [c.value for c in ws[1]] if ws else []
dent = next((row for row in ws.iter_rows(min_row=2) if row[0].value == "Dentist, Smile & Co"), None) if ws else None
check(hdr == sx.CONTACT_HEADERS and ws.max_row == 6 and dent is not None and dent[8].data_type == "s"
      and dent[8].value.startswith("=HYPERLINK"),
      f"Excel: every column, every contact, a note that looks like a formula stays text ({hdr})")
alex_row = next(row for row in ws.iter_rows(min_row=2) if row[0].value == "Alex Example")
check(alex_row[3].value == "1 Test Street\nTestbury TE1 1ST\nUnited Kingdom" and alex_row[4].value == "https://example.com/alex"
      and alex_row[6].value == "iCloud, Book club", "…with the address, website and lists")
v.save_table("csv")
pump(lambda: list(dest_dir.glob("Contacts *.csv")), 20)
c = next(iter(dest_dir.glob("Contacts *.csv")), None)
ctext = c.read_text("utf-8-sig") if c else ""
check(ctext.startswith(",".join(sx.CONTACT_HEADERS)) and "'=HYPERLINK" in ctext, "CSV: the same columns, formula-safe")

# E4: the whole-phone search finds a contact by their address, and opens them
import search
hits = [h for h in search.entries("contacts", win.data.contacts) if "testbury" in search.fold(h.text)]
check(len(hits) == 1 and hits[0].title == "Alex Example", "the whole-phone search finds a contact by their address")
win.find_hook[2](hits[0].ref)
a.update()
check(v.selected() == [win.data.contacts[hits[0].ref]] and v.current is win.data.contacts[hits[0].ref],
      "choosing that result shows the contact's card")

# the web export (Save everything / Back up) has the photos in its .vcf too
r2 = wv.BackupReader(BK, None, lambda m: None)
ctx2 = sx.Ctx(r2, W / "web", lambda m: None, True, wv.backup_info(BK))
res = sx.sec_contacts(ctx2, sx.load_contacts(ctx2))
web = (W / "web" / "Contacts" / "contacts.vcf").read_bytes().decode("utf-8").replace("\r\n ", "")
check(res["count"] == 5 and web.count("BEGIN:VCARD") == 5 and web.count("\r\nPHOTO;") == 3,
      "the web export's contacts.vcf has the 5 contacts and their 3 photos")
r2.close()
check(not connects, f"nothing went to the internet in the whole test: {connects}")

a.destroy()
shutil.rmtree(dest_dir, ignore_errors=True)
print("\nD1 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
