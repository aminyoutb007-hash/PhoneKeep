"""M5: show one person in a group chat (docs/spec/06-messages.md#m5-show-one-person-in-a-group-chat).

Done when: "Filtering a group to one person shows only their messages, in preview and in the saved Excel and PDF."
In the real phone window, on an invented backup (every name, number and message is made up):
- a group chat has a People button; it lists the participants with their message counts;
- ticking one person shows only their messages in the preview (no group updates), and the chat's row and the
  footer count only theirs; ticking a second adds theirs; Everyone shows the whole chat again;
- a chat with one person has no People button;
- saving the ticked group (Excel, CSV, Save ticked as PDF) keeps only that person's messages; other ticked chats
  are saved whole; with a date range too, only that person's messages in those dates are saved;
- the same in WhatsApp, where group members come from the group's member list.
"""
import csv, datetime as dt, hashlib, json, os, plistlib, shutil, sqlite3, sys, tempfile, time
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


import phonekeep as wv
import sections as sx
import exportfilter as ef

W = HERE / "work" / "m5"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
UDID = "00008030-M5TEST000000000000"
BK = W / "Backups" / UDID
BK.mkdir(parents=True)

ALEX, ROBIN, KIM = "+447700900111", "+447700900222", "+447700900333"
T0 = dt.datetime(2026, 3, 1, 10, 0)


def ns(minutes):
    return int(((T0 + dt.timedelta(minutes=minutes)).timestamp() - wv.APPLE_EPOCH) * 1e9)


# -- an invented backup: Messages with a group and a one-to-one chat; WhatsApp with a group ---------------------
with open(BK / "Info.plist", "wb") as f:
    plistlib.dump({"Device Name": "Test iPhone", "Product Type": "iPhone17,3", "Product Version": "26.5",
                   "Last Backup Date": dt.datetime(2026, 3, 10, 22, 0)}, f)
with open(BK / "Manifest.plist", "wb") as f:
    plistlib.dump({"IsEncrypted": False}, f)
man = sqlite3.connect(BK / "Manifest.db")
man.execute("CREATE TABLE Files(fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")


def add(domain, rel, build):
    fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
    (BK / fid[:2]).mkdir(exist_ok=True)
    con = sqlite3.connect(BK / fid[:2] / fid)
    build(con)
    con.commit()
    con.close()
    man.execute("INSERT INTO Files VALUES (?,?,?,1,NULL)", (fid, domain, rel))


# Messages: "Book club" (Alex, Robin, Kim and you) on 1 and 20 March, plus a one-to-one chat with Alex
BOOK = [  # minute, handle (0 = you), text
    (0, 1, "Alex: shall we start chapter five?"), (1, 2, "Robin: yes, chapter five"), (2, 0, "Me: fine by me"),
    (3, 3, "Kim: I'm a bit behind"), (4, 1, "Alex: no rush"), (5, 2, "Robin: Thursday then"),
    (27365, 2, "Robin: running late on the 20th"), (27366, 1, "Alex: see you all soon")]


def sms(c):
    c.executescript("""
CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id);
CREATE TABLE chat(ROWID INTEGER PRIMARY KEY, chat_identifier, display_name, style, service_name);
CREATE TABLE chat_message_join(chat_id, message_id);
CREATE TABLE chat_handle_join(chat_id, handle_id);
CREATE TABLE message(ROWID INTEGER PRIMARY KEY, text, attributedBody, handle_id, date, is_from_me, item_type,
  associated_message_type, group_title, service);""")
    c.executemany("INSERT INTO handle VALUES (?,?)", [(1, ALEX), (2, ROBIN), (3, KIM)])
    c.executemany("INSERT INTO chat VALUES (?,?,?,?,?)", [(1, "chat900", "Book club", 43, "iMessage"),
                                                          (2, ALEX, "", 45, "iMessage")])
    c.executemany("INSERT INTO chat_handle_join VALUES (?,?)", [(1, 1), (1, 2), (1, 3), (2, 1)])
    rid = 0
    for mins, h, text in BOOK:
        rid += 1
        c.execute("INSERT INTO message VALUES (?,?,NULL,?,?,?,0,0,NULL,'iMessage')", (rid, text, h, ns(mins), int(h == 0)))
        c.execute("INSERT INTO chat_message_join VALUES (1,?)", (rid,))
    rid += 1                                     # a group update: nobody's message
    c.execute("INSERT INTO message VALUES (?,NULL,NULL,1,?,0,2,0,'Book club 📚','iMessage')", (rid, ns(6)))
    c.execute("INSERT INTO chat_message_join VALUES (1,?)", (rid,))
    for k, (text, me) in enumerate((("Alex alone: are you coming?", 0), ("Me alone: on my way", 1))):
        rid += 1
        c.execute("INSERT INTO message VALUES (?,?,NULL,1,?,?,0,0,NULL,'iMessage')", (rid, text, ns(10 + k), me))
        c.execute("INSERT INTO chat_message_join VALUES (2,?)", (rid,))


add(sx.HOME, "Library/SMS/sms.db", sms)

WALK = [(0, 1, "Sam: the walk starts at nine"), (1, 2, "Jo: I'll bring the map"), (2, 0, "Me: see you there"),
        (3, 1, "Sam: bring water"), (4, 2, "Jo: and snacks")]


def whatsapp(c):
    c.executescript("""
CREATE TABLE ZWACHATSESSION(Z_PK INTEGER PRIMARY KEY, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZARCHIVED);
CREATE TABLE ZWAGROUPMEMBER(Z_PK INTEGER PRIMARY KEY, ZMEMBERJID, ZCONTACTNAME, ZFIRSTNAME);
CREATE TABLE ZWAMESSAGE(Z_PK INTEGER PRIMARY KEY, ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,
 ZGROUPMEMBER, ZMEDIAITEM, ZFROMJID, ZSTARRED);""")
    c.execute("INSERT INTO ZWACHATSESSION VALUES (1, '120363000000000001@g.us', 'Walking group', 1, 0)")
    c.executemany("INSERT INTO ZWAGROUPMEMBER VALUES (?,?,?,?)",
                  [(1, "447700900444@s.whatsapp.net", "Sam Example", None), (2, "447700900555@s.whatsapp.net", "Jo Test", None)])
    t0 = T0.timestamp() - wv.APPLE_EPOCH
    for k, (mins, member, text) in enumerate(WALK, 1):
        c.execute("INSERT INTO ZWAMESSAGE VALUES (?,1,?,?,?,0,?,NULL,'120363000000000001@g.us',0)",
                  (k, int(member == 0), t0 + mins * 60, text, member or None))


add(wv.WA_DOMAIN, "ChatStorage.sqlite", whatsapp)
man.commit()
man.close()

# -- the rule on its own -----------------------------------------------------------------------------------------
msgs = [{"from_me": False, "sender": "A", "time": "2026-03-01T10:00:00", "type": "text"},
        {"from_me": True, "sender": "You", "time": "2026-03-02T10:00:00", "type": "text"},
        {"from_me": False, "sender": "A", "time": "2026-03-03T10:00:00", "type": "text"},
        {"from_me": False, "sender": "A", "time": "2026-03-03T11:00:00", "type": "system", "text": "Group update"}]
ppl = ef.people_in(msgs)
check([(p["name"], p["count"]) for p in ppl] == [("A", 2), ("You", 1)] and ppl[0]["days"] == ["2026-03-01", "2026-03-03"],
      f"participants with their message counts, most first; a group update is nobody's: {[(p['name'], p['count']) for p in ppl]}")
kept = ef.only_people([{"id": 1, "messages": msgs}, {"id": 2, "messages": msgs[:1]}], {1: {"You"}})
check([len(c["messages"]) for c in kept] == [1, 1] and kept[0]["messages"][0]["from_me"],
      "only that chat keeps only that person's messages; other chats are untouched")

# -- the real phone window ---------------------------------------------------------------------------------------
import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import tkinter as tk
import ui
import phone
import app as appmod
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
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


def preview_text(panel):
    return panel.text.get("1.0", "end")


def click_person(panel, name):
    tree = panel.people_tree
    iid = next(i for i in tree.get_children() if tree.item(i, "text") == name)
    tree.see(iid)
    a.update()
    x, y, w, h = tree.bbox(iid, "name")
    tree.event_generate("<ButtonRelease-1>", x=x + 5, y=y + h // 2)
    a.update()


def button(panel, text):
    return next(w for w in panel.foot.winfo_children() if getattr(w, "text", "") == text)


def sheet_senders(path, sheet):
    from openpyxl import load_workbook
    ws = load_workbook(path)[sheet]
    head = [c.value for c in ws[1]]
    i, j = head.index("Sender"), head.index("Message")
    return [(r[i].value, r[j].value) for r in ws.iter_rows(min_row=2)]


def pdf_text(path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    try:
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    finally:
        doc.close()


pump(lambda: False, 0.3)
check(a.open_backup(BK), "the phone window opens on the invented backup")
win = a.phone_windows[-1]
pump(lambda: win.data is not None, 60)

asked, revealed = [], []
dest_dir = Path(tempfile.mkdtemp(prefix="pk-m5-"))
phone.ask_save_folder = lambda parent, title, start: asked.append(title) or str(dest_dir)
phone.reveal = lambda p: revealed.append(Path(p))
out_root = Path(win.out_root)

# ---- Messages ----
win.open_app("messages")
pump(lambda: find(win.content, ui.ChatPanel) is not None, 60)
panel = find(win.content, ui.ChatPanel)
rows = {c["name"]: str(i) for i, (_k, _l, c) in enumerate(panel.rows)}
group_iid, one_iid = rows["Book club"], next(i for n, i in rows.items() if n != "Book club")
panel.tree.selection_set(one_iid)
panel.tree.focus(one_iid)
panel._show(one_iid)
a.update()
check(not panel.people_btn.winfo_ismapped(), "a chat with one person has no People button")
panel.tree.selection_set(group_iid)
panel.tree.focus(group_iid)
panel._show(group_iid)
a.update()
check(panel.people_btn.winfo_ismapped() and panel.people_btn.text == "People", "a group chat has a People button")
full = preview_text(panel)
check(all(t in full for _m, _h, t in BOOK) and "Book club 📚" in full, "before: the preview shows everyone's messages")
panel.people_btn.command()
pump(lambda: panel.people_tree is not None and panel.people_tree.winfo_ismapped(), 10)
listed = {panel.people_tree.item(i, "text"): panel.people_tree.set(i, "messages") for i in panel.people_tree.get_children()}
check(listed == {ALEX: "3", ROBIN: "3", "You": "1", KIM: "1"}, f"People lists the participants with message counts: {listed}")
check(panel.people_win.cget("bg") == ui.BG, "the People list uses the app's own colours (light and dark)")

click_person(panel, ROBIN)
text = preview_text(panel)
robin = [t for _m, h, t in BOOK if h == 2]
check(all(t in text for t in robin) and not any(t in text for _m, h, t in BOOK if h != 2) and "Book club 📚" not in text,
      "ticking one person: the preview shows only their messages (no group updates)")
check(panel.tree.set(group_iid, "messages") == "3" and f"only {ROBIN}" in panel.tree.set(group_iid, "name")
      and f"only {ROBIN}" in panel.pv_sub.cget("text") and panel.people_btn.text == "People · 1",
      f"the chat's row, the preview's subtitle and the button say so: {panel.tree.set(group_iid, 'name')!r}, "
      f"{panel.pv_sub.cget('text')!r}")
check(panel.people_tree.set(next(i for i in panel.people_tree.get_children()
                                 if panel.people_tree.item(i, "text") == ROBIN), "tick") == "☑", "the person is ticked")
click_person(panel, KIM)
text = preview_text(panel)
check("Kim: I'm a bit behind" in text and "Robin: Thursday then" in text and "Alex: no rush" not in text
      and panel.tree.set(group_iid, "messages") == "4", "ticking a second person adds their messages")
click_person(panel, KIM)
check(panel.tree.set(group_iid, "messages") == "3", "unticking them takes theirs away again")

# save: the group (Robin only) and the one-to-one chat (whole), as Excel, CSV and PDF
panel._toggle(group_iid)
panel._toggle(one_iid)
check(panel.count.cget("text").startswith("2 of 2 chats ticked · 5 messages"), f"the footer counts only theirs: "
      f"{panel.count.cget('text')!r}")
sel = panel.selection(confirm_empty=False)
group_id = panel.rows[int(group_iid)][2]["id"]
check(sel.get("_people") == {"messages": {group_id: {ROBIN}}}, f"the choice goes with the save: {sel.get('_people')}")

shutil.rmtree(out_root, ignore_errors=True)
button(panel, "Excel").command()
pump(lambda: str(win.bar_text.cget("text")).startswith(("✓", "Couldn't")), 120)
xlsx = next(out_root.rglob("Messages chats.xlsx"), None)
saved = sheet_senders(xlsx, "Book club") if xlsx else []
check(xlsx and saved and all(s == ROBIN for s, _t in saved) and [t for _s, t in saved] == robin,
      f"Excel: the group's sheet has only that person's messages: {saved}")
alone = sheet_senders(xlsx, next(n for n in rows if n != "Book club")[:28]) if xlsx else []
check(len(alone) == 2, f"Excel: the other ticked chat is saved whole ({len(alone)})")

win.bar_text.configure(text="")
button(panel, "CSV").command()
pump(lambda: str(win.bar_text.cget("text")).startswith(("✓", "Couldn't")), 120)
csvf = next(out_root.rglob("CSV/Book club.csv"), None)
with open(csvf, encoding="utf-8-sig", newline="") if csvf else open(os.devnull) as f:
    crow = list(csv.DictReader(f))
check(csvf and [r["Sender"] for r in crow] == ["'" + ROBIN] * 3, f"CSV: only that person's messages ({len(crow)})")

win.bar_text.configure(text="")
before = set(dest_dir.glob("*.pdf"))
real_yes = phone.messagebox.askyesnocancel
phone.messagebox.askyesnocancel = lambda *a, **k: False          # one PDF for each chat
try:
    button(panel, "Save ticked as PDF").command()
    pump(lambda: len(set(dest_dir.glob("*.pdf")) - before) >= 2, 120)
finally:
    phone.messagebox.askyesnocancel = real_yes
pdfs = sorted(set(dest_dir.glob("*.pdf")) - before)
gpdf = next((p for p in pdfs if p.name.startswith("Book club")), None)
ptxt = pdf_text(gpdf) if gpdf else ""
check(gpdf and all(t in ptxt for t in robin) and not any(t in ptxt for _m, h, t in BOOK if h != 2),
      f"PDF: the group's PDF has only that person's messages ({[p.name for p in pdfs]})")

# with a date range too: only that person's messages in those dates
panel.d_from.set("2026-03-15")
panel.d_to.set("2026-03-31")
panel._typed_dates()
a.update()
check(panel.tree.set(group_iid, "messages") == "1", f"with dates too, the row counts that person's messages in them "
      f"({panel.tree.set(group_iid, 'messages')})")
shutil.rmtree(out_root, ignore_errors=True)
win.bar_text.configure(text="")
button(panel, "Excel").command()
pump(lambda: str(win.bar_text.cget("text")).startswith(("✓", "Couldn't")), 120)
xlsx = next(out_root.rglob("Messages chats.xlsx"), None)
saved = sheet_senders(xlsx, "Book club") if xlsx else []
check([t for _s, t in saved] == ["Robin: running late on the 20th"], f"Excel with dates: that person in those dates: {saved}")
panel.d_from.set("")
panel.d_to.set("")
panel._typed_dates()

# Everyone: the whole chat again
pump(lambda: False, 0.1)
if not (panel.people_win and panel.people_win.winfo_exists()):
    panel.people_btn.command()
    a.update()
everyone = next(w for w in panel.people_win.winfo_children()[-1].winfo_children() if getattr(w, "text", "") == "Everyone")
everyone.command()
a.update()
check(panel.tree.set(group_iid, "messages") == "9" and panel.people_btn.text == "People"
      and "Alex: no rush" in preview_text(panel) and "_people" not in panel.selection(confirm_empty=False),
      "Everyone shows the whole chat again, and the save is whole")
panel.people_win.destroy()

# ---- WhatsApp ----
win.show_home()
pump(lambda: False, 0.2)
win.open_app("whatsapp")
pump(lambda: find(win.content, ui.ChatPanel) is not None, 60)
wp = find(win.content, ui.ChatPanel)
wiid = next(str(i) for i, (_k, _l, c) in enumerate(wp.rows) if c["name"] == "Walking group")
wp.tree.selection_set(wiid)
wp.tree.focus(wiid)
wp._show(wiid)
a.update()
wp.people_btn.command()
pump(lambda: wp.people_tree is not None and wp.people_tree.winfo_ismapped(), 10)
wl = {wp.people_tree.item(i, "text"): wp.people_tree.set(i, "messages") for i in wp.people_tree.get_children()}
check(wl == {"Sam Example": "2", "Jo Test": "2", "You": "1"}, f"WhatsApp: the group's members from its member list: {wl}")
click_person(wp, "Jo Test")
check("Jo: I'll bring the map" in preview_text(wp) and "Sam: bring water" not in preview_text(wp),
      "WhatsApp: the preview shows only that person")
wp._toggle(wiid)
shutil.rmtree(out_root, ignore_errors=True)
win.bar_text.configure(text="")
button(wp, "Excel").command()
pump(lambda: str(win.bar_text.cget("text")).startswith(("✓", "Couldn't")), 120)
xlsx = next(out_root.rglob("WhatsApp chats.xlsx"), None)
saved = sheet_senders(xlsx, "Walking group") if xlsx else []
check([t for _s, t in saved] == ["Jo: I'll bring the map", "Jo: and snacks"], f"WhatsApp Excel: only that person: {saved}")
before = set(dest_dir.glob("*.pdf"))
button(wp, "Save ticked as PDF").command()
pump(lambda: set(dest_dir.glob("*.pdf")) - before, 120)
new = sorted(set(dest_dir.glob("*.pdf")) - before)
wtxt = pdf_text(new[0]) if new else ""
check(new and "Jo: and snacks" in wtxt and "Sam: bring water" not in wtxt, "WhatsApp PDF: only that person")
wp.people_win.destroy()

a.destroy()
shutil.rmtree(dest_dir, ignore_errors=True)
print("\nM5 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures), flush=True)
os._exit(1 if failures else 0)
