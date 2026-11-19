"""Q3: contact cards with everything about a person (docs/spec/11-previews.md#q3-contact-cards).

Done when: "A person's card lists their chats in all three messaging apps, their calls and voicemails."
First the matching (people.py), on invented data: numbers written differently are the same person, an email address
counts, a WhatsApp id gives its number, a group chat counts by the messages they sent in it, someone else's messages
don't. Then the real phone window on the invented backup (tests/test_full_backup.py: every name and number is made
up): the card lists the person's chats (Messages and WhatsApp), calls (a phone call and a FaceTime by email) and
voicemail, newest first; a click on one opens it in its own view; and the other way round, a one-to-one chat, a call
or a voicemail opens the person's card.
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
import faulthandler
faulthandler.dump_traceback_later(240, exit=True)

import phonekeep as wv
import people as pp

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- matching -------------------------------------------------------------------------------------------------------
sam = {"phones": [("mobile", "+44 7700 900111"), ("home", "")], "emails": [("home", " Sam@Example.org ")]}
keys = pp.keys_of(sam)
check(keys == {"700900111", "sam@example.org"}, f"a person's keys: their numbers' last nine digits, their email ({keys})")
check(pp.key_of("07700 900111") in keys and pp.key_of("+447700900111") in keys
      and pp.key_of("447700900111@s.whatsapp.net") in keys and pp.key_of("SAM@example.org") in keys,
      "  the same number written three ways, a WhatsApp id and the email in capitals all match")
check(pp.key_of("123 45") == pp.key_of("12345") == "12345", "  a short number with spaces is the same number without")
check(pp.key_of("123456789@g.us") == "" and pp.key_of("98765@lid") == "" and pp.key_of("") == "",
      "  a WhatsApp group id or a hidden-number id matches nobody")

chats = [
    {"id": 1, "jid": "+447700900111", "group": False, "name": "Sam",
     "messages": [{"time": "2026-03-01T10:00:00"}, {"time": "2026-03-04T09:00:00"}]},
    {"id": 2, "jid": "sam@example.org", "group": False, "name": "Sam", "messages": [{"time": "2026-02-01T10:00:00"}]},
    {"id": 3, "jid": "chat77", "group": True, "name": "Film club", "messages": [
        {"time": "2026-03-05T20:00:00", "from_me": False, "detail": {"number": "07700 900111"}},
        {"time": "2026-03-06T20:00:00", "from_me": False, "detail": {"number": "+447700900222"}},
        {"time": "2026-03-02T20:00:00", "from_me": True}]},
    {"id": 4, "jid": "chat78", "group": True, "name": "Other group", "messages": [
        {"time": "2026-03-07T20:00:00", "from_me": False, "detail": {"number": "+447700900222"}}]},
    {"id": 5, "jid": "+447700900222", "group": False, "name": "Someone else", "messages": [{"time": "2026-03-08T10:00:00"}]},
]
found = pp.chats_with("messages", chats, keys)
by_id = {x["chat"]["id"]: x for x in found}
check(sorted(by_id) == [1, 2, 3], f"their chats: by number, by email, and a group they wrote in ({sorted(by_id)})")
check(by_id[3]["count"] == 1 and by_id[3]["last"] == "2026-03-05T20:00:00",
      "  in a group, their own messages count (not others', not mine)")
check(by_id[1]["count"] == 2 and by_id[1]["last"] == "2026-03-04T09:00:00", "  a one-to-one chat: all its messages")
wa = [{"id": 9, "jid": "447700900111@s.whatsapp.net", "group": False, "name": "Sam",
       "messages": [{"time": "2026-03-09T08:00:00"}]}]
every = pp.all_chats_with({"messages": chats, "whatsapp": wa}, keys)
check([(x["app"], x["chat"]["id"]) for x in every] == [("whatsapp", 9), ("messages", 3), ("messages", 1),
                                                         ("messages", 2)],
      "  every app's chats together, newest first")
check(pp.chats_with("messages", chats, set()) == [], "  a contact with no number or email has no chats")
calls = [["10 Mar 2026 10:00", "Outgoing", "Sam", "+447700900111", "Phone", "1:00", ""],
         ["9 Mar 2026 10:00", "Missed", "", "+447700900222", "Phone", "0:00", ""],
         ["8 Mar 2026 10:00", "Incoming", "Sam", "sam@example.org", "FaceTime video", "5:00", ""]]
check([i for i, _r in pp.calls_with(calls, keys)] == [0, 2], "their calls, by number and by email (FaceTime)")
vms = [{"number": "07700900111"}, {"number": ""}, {"number": "+447700900222"}]
check([i for i, _v in pp.voicemails_with(vms, keys)] == [0], "their voicemails")
people_list = [sam, {"phones": [("mobile", "+44 7700 900222")], "emails": []},
               {"phones": [("work", "020 7946 0001")], "emails": []}, {"phones": [("mobile", "020 7946 0001")]}]
check(pp.person_for(people_list, "447700900222@s.whatsapp.net") == 1 and pp.person_for(people_list, "x@y.z") is None
      and pp.person_for(people_list, "02079460001") is None,
      "the contact with a number: found; unknown: none; two contacts with it: none (whose card is unclear)")


def boom(key):
    if key in ("whatsappbusiness", "voicemail"):
        raise wv.PhoneKeepError("not in this backup")
    if key == "calls":
        raise OSError("disk error")
    return {"messages": chats, "whatsapp": {"chats": wa}, "calls": calls}[key]


res = pp.find_all(boom, keys)
check(len(res["chats"]) == 4 and res["calls"] == [] and res["voicemail"] == []
      and res["missing"] == ["WhatsApp Business", "Voicemail"] and res["unread"] == ["Calls"],
      f"what a backup doesn't have is said apart from what couldn't be read, the rest still found "
      f"({res['missing']}, {res['unread']})")

# -- the phone window, on the invented backup ------------------------------------------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
W = HERE / "work" / "q3"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
shutil.copytree(fake, W / "00008030-Q3TEST000000000000")
BK = W / "00008030-Q3TEST000000000000"

import app as appmod
import device as devmod
import phone
from tkcompat import hide


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
appmod.SETTINGS_FILE = W / "settings.json"
a = appmod.App()
a.withdraw()
a.after_cancel(a._timers.pop("first"))
a.s["backup_dir"] = str(W / "Backups")
a.s["archive_dir"] = str(W / "Archive")


def pump(until, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


check(a.open_backup(BK), "the invented backup opens in a phone window")
win = a.phone_windows[-1]
hide(win)
check(pump(lambda: win.data is not None, 60), "  its backup is read")
win.open_app("contacts")
check(pump(lambda: getattr(win, "contacts_view", None) is not None, 30), "Contacts opens")
cv = win.contacts_view
by_name = {p["name"]: i for i, p in enumerate(cv.people)}


def card_of(name):
    cv.pick(by_name[name])
    return pump(lambda: cv.with_found is not None, 30)


def rows():
    return [cv.with_list.item(i, "text") for i in cv.with_list.get_children()]


check(card_of("Karim B"), "Karim's card: his chats, calls and voicemail are found")
res = cv.with_found
apps = sorted(x["app"] for x in res["chats"])
check(apps == ["messages", "whatsapp"], f"  chats in Messages (a group he wrote in) and WhatsApp ({apps})")
grp = next(x for x in res["chats"] if x["app"] == "messages")
check(grp["group"] and grp["count"] == 1, "  the Messages group counts his own message")
check(any(r.endswith(" · WhatsApp · 1 message") for r in rows())
      and any(" · Messages group · 1 of theirs · " in r for r in rows()),
      f"  the Chats tab says when, which app and how many, a group's name last ({rows()})")
check([x["last"] for x in res["chats"]] == sorted((x["last"] for x in res["chats"]), reverse=True),
      "  newest first")
check(len(res["calls"]) == 1 and res["calls"][0][1][1] == "Missed", "  his call (missed), though his card writes "
      "the number 07700… and the call +44 7700…")
check(len(res["voicemail"]) == 1, "  his voicemail")
check(cv.with_note.cget("text").startswith("2 chats · 1 call · 1 voicemail"), f"  the counts ({cv.with_note.cget('text')!r})")
cv.with_tab("voicemail")
check(len(rows()) == 1, f"  the Voicemail tab lists it ({rows()})")
cv.with_tab("calls")
check(len(rows()) == 1 and "Missed" in rows()[0], f"  the Calls tab lists it ({rows()})")

# a click opens the call in Calls, chosen
cv.open_with(cv.with_list.get_children()[0])
check(pump(lambda: win.current == "calls" and win.find_hook and win.find_hook[0] == "calls", 30), "a click on the call opens Calls")
pump(lambda: False, 0.3)


def tree_in(w):
    for c in w.winfo_children():
        if c.winfo_class() == "Treeview":
            return c
        t = tree_in(c)
        if t is not None:
            return t
    return None


t = tree_in(win.content)
chosen = [t.item(i, "values") for i in t.selection()] if t is not None else []
check(len(chosen) == 1 and chosen[0][1] == "Missed", f"  with that call chosen ({chosen})")

# ... and from a call, the person's card
old = win.contacts_view
win.open_card_for(chosen[0][3], "call")
check(pump(lambda: win.current == "contacts" and win.contacts_view is not old
           and win.contacts_view.current is not None, 30)
      and win.contacts_view.current["name"] == "Karim B", "the call's Contact card opens Karim's card")

# a click on the voicemail opens Voicemail with it chosen, and its Contact card opens Karim's card
cv = win.contacts_view
by_name = {p["name"]: i for i, p in enumerate(cv.people)}
check(card_of("Karim B"), "Karim's card again")
cv.with_tab("voicemail")
cv.open_with(cv.with_list.get_children()[0])
check(pump(lambda: win.current == "voicemail" and win.find_hook and win.find_hook[0] == "voicemail", 30),
      "a click on the voicemail opens Voicemail")
pump(lambda: False, 0.3)
t = tree_in(win.content)
chosen = [t.item(i, "values") for i in t.selection()] if t is not None else []
check(len(chosen) == 1 and chosen[0][2] == "+447700900456", f"  with that voicemail chosen ({chosen})")
old = win.contacts_view
win.open_card_for(chosen[0][2], "voicemail")
check(pump(lambda: win.current == "contacts" and win.contacts_view is not old
           and win.contacts_view.current is not None, 30)
      and win.contacts_view.current["name"] == "Karim B", "  its Contact card opens Karim's card")

# Alex: a Messages chat (iMessage and SMS together), a phone call and a FaceTime by email; no voicemail
cv = win.contacts_view
by_name = {p["name"]: i for i, p in enumerate(cv.people)}
check(card_of("Alex Example"), "Alex's card")
res = cv.with_found
one = [x for x in res["chats"] if x["app"] == "messages" and not x["group"]]
check(len(one) == 1 and one[0]["count"] == 4,
      f"  his one-to-one Messages chat: iMessage and SMS, as one chat as Messages shows them ({[x['count'] for x in one]})")
check(len(res["calls"]) == 2 and {r[4] for _i, r in res["calls"]} == {"Phone", "FaceTime video"},
      "  a phone call and a FaceTime by email")
check(res["voicemail"] == [], "  no voicemail")
cv.with_tab("chats")
first = cv.with_list.get_children()[0]
app_key, ref = cv.with_items[first]
cv.open_with(first)
check(pump(lambda: win.current == "messages" and getattr(win, "find_hook", None) and win.find_hook[0] == "messages", 30),
      "a click on a chat opens Messages")
panel = getattr(win, "chat_panel", None) or next((c for c in win.content.winfo_children() if hasattr(c, "show_chat")), None)
pump(lambda: panel is not None and panel.shown_chat == ("messages", ref[0]), 10)
check(panel is not None and panel.shown_chat == ("messages", ref[0]), f"  with that chat shown ({panel and panel.shown_chat})")
check(panel is not None and bool(panel.card_btn.winfo_manager()), "  a one-to-one chat with a contact has Contact card")
old = win.contacts_view
panel.card_btn.command()
check(pump(lambda: win.current == "contacts" and win.contacts_view is not old
           and win.contacts_view.current is not None, 30)
      and win.contacts_view.current["name"] == "Alex Example", "  which opens Alex's card")

# a number in no contact: said, nothing opened
old = win.contacts_view
win.open_card_for("+447700900999", "call")
pump(lambda: False, 0.5)
check(win.contacts_view is old and win.current == "contacts" and "isn't in the iPhone's Contacts" in win.bar_text.cget("text"),
      f"a number in no contact opens nothing, and says so ({win.bar_text.cget('text')!r})")

# arrowing down the list: only the card on screen is looked for, not every one passed on the way
cv = win.contacts_view
calls_made = []
real_find = pp.find_all
pp.find_all = lambda get, keys: (calls_made.append(1), time.sleep(0.3), real_find(get, keys))[2]
cv.bg.submit(lambda: time.sleep(0.5), lambda _r: None)          # the worker is busy when the clicks come
for name in ("Alex Example", "Dentist, Smile & Co", "Karim B", "Alex Example", "Karim B"):
    cv.pick(next(i for i, p in enumerate(cv.people) if p["name"] == name))
check(pump(lambda: cv.with_found is not None and cv.current["name"] == "Karim B", 30) and len(calls_made) == 1,
      f"five cards in a row: only the last is looked for ({len(calls_made)} looked for)")
pp.find_all = real_find

check(not any(p.is_file() for p in (W / "Archive").rglob("*")) if (W / "Archive").exists() else True,
      "nothing was saved anywhere")
for w in list(a.phone_windows):
    w.destroy()
a.destroy()
print()
if failures:
    print(f"Q3 TESTS: FAIL ({len(failures)})")
    sys.exit(1)
print("Q3 TESTS: PASS")
