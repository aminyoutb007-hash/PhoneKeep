"""E4: one search across the phone (docs/spec/05-ease-of-use.md#e4-one-search-across-the-phone).

Done when:
- "On a backup with 200,000 messages, first results show in under 1 second."  → 200,000 invented messages (with
  French and Arabic among them) searched: every query answers in well under 1 second once the search is ready.
- "Usability test task 3 passes."  → the owner's usability test (5.3), not checked here.
Also, with the tests' invented backup in a real phone window (no iPhone):
- "Search everything" on the home screen; typing shows results grouped by app (Messages, WhatsApp, Notes, Calls…)
  with the matching words highlighted and dates; one letter shows nothing; nothing found says so;
- clicking a result opens that app with the item chosen and its own search box showing the same words; a chat
  opens at the message that was clicked;
- partial words, any case, accents and Arabic vowel marks are ignored (fold), and the per-screen searches match
  the same way;
- the search holds everything in memory: no file is written for it.
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
import search

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- matching -----------------------------------------------------------------------------------------------
f = search.fold
check(f("École") == "ecole" and f("ÇA va") == "ca va" and f("Straße") == "strasse", "case and accents are ignored")
check(f("مَدْرَسَة") == f("مدرسة") and f("أحمد") == f("احمد") == f("إحمد") and f("كتـــاب") == f("كتاب"),
      "Arabic: vowel marks, hamza on alef and the stretching line are ignored")
check(f("a \n  b") == "a b", "spaces and line breaks count as one space")
b, m, a = search.snippet("Rendez-vous à l'école demain", "ECOL")
check(m == "écol" and b.endswith("l'") and a.startswith("e demain"), f"a partial word is found and marked as written: {(b, m, a)}")
b, m, a = search.snippet("سأذهب إلى المَدْرَسَة غداً", "مدرسة")
check(m == "مَدْرَسَة", "  an Arabic word typed without vowel marks is found and marked with them")
check(search.snippet("x" * 300 + " needle " + "y" * 300, "needle", 60)[0].startswith("…"), "  long text is cut around the match")

# -- 200,000 messages ----------------------------------------------------------------------------------------
words = ["dinner", "train", "école", "merci", "رسالة", "bonjour", "meeting", "photo", "مدرسة", "weekend"]
chats = []
for c in range(400):
    msgs = [{"text": f"message {c}-{i} about {words[(c + i) % len(words)]} and more words to read", "time":
             f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}T10:{i % 60:02d}:00", "type": "text"} for i in range(500)]
    chats.append({"id": c, "name": f"Invented chat {c}", "messages": msgs})
chats[7]["messages"][123]["text"] = "Le rendez-vous à l'ÉCOLE est à 9h"
big = {"messages": chats}


def get(key):
    if key not in big:
        raise wv.PhoneKeepError("Not in this backup.")
    return big[key]


s = search.PhoneSearch(get)
s.build()
n = sum(len(c["messages"]) for c in chats)
check(n == 200_000 and s.ready and s.missing == [k for k, _l in search.SOURCES if k != "messages"],
      f"200,000 messages ready to search in {s.build_seconds:.1f} s (apps the backup lacks are left out)")
slowest = 0.0
for q in ("dinner", "ECOLE", "مدرسة", "about", "zzzz", "Rendez-vous à"):
    t0 = time.perf_counter()
    res = s.find(q)
    slowest = max(slowest, time.perf_counter() - t0)
check(slowest < 1.0, f"Done when: first results in under 1 second on 200,000 messages (slowest query {slowest:.2f} s)")
res = dict((k, (cnt, hits)) for k, cnt, hits in s.find("rendez-vous a l'ecole"))
check("messages" in res and res["messages"][0] == 1 and res["messages"][1][0].ref == (7, chats[7]["messages"][123]["time"]),
      "  typed without accents, the one message with accents is found, and the hit knows its chat and message")
check(s.find("e") == [], "  one letter finds nothing (too much to be useful)")
del big, chats, s

# -- the phone window, on the invented backup ------------------------------------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
W = HERE / "work" / "e4"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
shutil.copytree(fake, W / "00008030-E4TEST000000000000")
BK = W / "00008030-E4TEST000000000000"

import tkinter as tk
from tkinter import ttk
import app as appmod
import device as devmod
import phone


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


def files_now():
    return sorted(str(p) for p in W.rglob("*") if p.is_file())


check(a.open_backup(BK), "the invented backup opens in a phone window")
win = a.phone_windows[-1]
win.withdraw()
check(pump(lambda: win.data is not None, 60), "  its backup is read")
win.show_home()
before = files_now()


def find_box_entries(w):
    out = []
    for c in w.winfo_children():
        if hasattr(c, "entry"):
            out.append(c.entry)
        out.extend(find_box_entries(c))
    return out


check(len(find_box_entries(win.content)) == 1, "the home screen has the 'Search everything' box")


def type_(text):
    win.find_q.set(text)
    pump(lambda: False, 0.4)                                       # the box waits a moment for more typing
    pump(lambda: win.current != "search" or (win.searcher and win.searcher.ready and not getattr(win, "_find_building", False)), 60)
    pump(lambda: False, 0.2)


def results():
    return win.find_text.get("1.0", "end")


type_("d")
check(win.current is None, "one letter: still the home screen")
type_("dinner FRI")
check(win.current == "search" and "Messages" in results() and "Dinner Friday?" in results(),
      f"typing shows the results grouped by app, with the matching message: {results()[:80]!r}")
ranges = win.find_text.tag_ranges("match")
check(ranges and win.find_text.get(ranges[0], ranges[1]) == "Dinner Fri", "  the matching words are highlighted")
check(len(find_box_entries(win.content)) == 1 and find_box_entries(win.content)[0].cget("textvariable") == str(win.find_q),
      "  the results keep their own search box, with the same words")
when_ranges = win.find_text.tag_ranges("when")
check(any(win.find_text.get(x, y).strip()[:2] == "20" for x, y in zip(when_ranges[::2], when_ranges[1::2])), "  with dates")
type_("milk")
check("Notes" in results() and "Shopping" in results(), "Notes are searched")
type_("WHATSAPP te")
check("WhatsApp" in results() and "Salam! WhatsApp test" in results(), "WhatsApp is searched")
type_("0900456")
check("Calls" in results(), f"Calls are searched: {results()[:120]!r}")
type_("example.org")
check("Notes" in results(), "  a part of an address in a note is found")
type_("qqqzzz")
check("Nothing found" in results(), "nothing found says so")


def click_first(app_label):
    t = win.find_text
    idx = t.search(app_label, "1.0")
    hit = next(n for n in t.tag_names(f"{idx} + 1 line linestart") if n.startswith("h"))
    check(bool(t.tk.call(t._w, "tag", "bind", hit, "<Button-1>")), f"  a result under {app_label} can be clicked")
    key = next(k for k, l in search.SOURCES if l == app_label)
    h = [hh for k, _c, hs in win.find_hits if k == key for hh in hs][0]
    win.open_hit(h, win.find_q.get())        # what the click on that line does (a hidden window gets no clicks)
    return h


asked_at = []
real_messages = win.data.preview.messages
win.data.preview.messages = lambda *a, **k: (asked_at.append(k.get("at")), real_messages(*a, **k))[1]
type_("dinner")
h = click_first("Messages")
check(pump(lambda: win.current == "messages" and win.find_hook is not None, 30), "clicking a message opens Messages")
panel = next(w for w in win.content.winfo_children() if isinstance(w, phone.ui.ChatPanel))
check(panel.q.get() == "dinner" and panel.current == ("messages", h.ref[0]),
      f"  with the same words in its search box and that chat chosen ({panel.q.get()!r}, {panel.current})")
shown = panel.text.get("1.0", "end")
check("Dinner Friday?" in shown and h.ref[1] and asked_at and asked_at[-1] == h.ref[1],
      f"  showing the message that was clicked (the chat is asked for the one sent at {h.ref[1]})")
win.data.preview.messages = real_messages

win.find_q.set("")
win.show_home()
type_("milk")
h = click_first("Notes")
check(pump(lambda: win.current == "notes" and win.find_hook is not None, 30), "clicking a note opens Notes")


def trees(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, ttk.Treeview):
            out.append(c)
        out.extend(trees(c))
    return out


t = trees(win.content)[0]
check(t.selection() == (str(h.ref),) and win.find_hook[1].get() == "milk", "  with that note chosen and 'milk' in its search box")

win.show_home()
type_("0900456")
h = click_first("Calls")
check(pump(lambda: win.current == "calls" and win.find_hook is not None, 30), "clicking a call opens Calls")
t = trees(win.content)[0]
sel = t.selection()
check(len(sel) == 1 and "0900456" in " ".join(t.item(sel[0], "values")), f"  with that call chosen: {[t.item(i, 'values') for i in sel]}")
check(win.find_hook[1].get() == "0900456" and len(t.get_children()) >= 1, "  and the list narrowed to the same words")

# the per-screen searches match the same way (accents and case), on invented accented rows
win.current = "calls"
win._clear()
win.table_view("calls", ["Name", "Place"], [["Café Lumière", "Montréal"], ["Other", "Paris"]])
win.find_hook[1].set("cafe LUMIERE")
t = trees(win.content)[0]
check([t.item(i, "values")[0] for i in t.get_children()] == ["Café Lumière"], "a table's own search ignores accents and case")
win._clear()
win.view_header("notes")
win.v_notes("notes", [{"title": "Réunion à l'école", "folder": "Notes", "created": None, "modified": None,
                       "text": "Ordre du jour", "locked": False},
                      {"title": "Courses", "folder": "Notes", "created": None, "modified": None, "text": "lait",
                       "locked": False}])
win.find_hook[1].set("RÉUNION à L'ÉCOLE")
t = trees(win.content)[0]
check(len(t.get_children()) == 1, "the notes' own search ignores accents and case")
win.find_hook[1].set("reunion a l'ecole")
check(len(t.get_children()) == 1, "  typed without accents too")

# the chats' own search and the jump inside a chat match the same way
import sections as sx


class _Ctx:
    cache = {"messages": [{"id": 1, "name": "Invented", "group": False, "messages":
                           [{"text": f"filler {i}", "time": f"2026-01-01T10:{i % 60:02d}:00"} for i in range(200)]
                           + [{"text": "Rendez-vous à l'ÉCOLE", "time": "2026-01-02T09:00:00"}]
                           + [{"text": f"after {i}", "time": f"2026-01-03T10:{i % 60:02d}:00"} for i in range(200)]}]}


pv = sx.ChatPreview(_Ctx())
check(pv.matching("messages", "ecole") == {1: 1} and pv.matching("messages", "École") == {1: 1},
      "a chat's own search ignores accents and case, whichever side has them")
msgs, _n = pv.messages("messages", 1, 20, around="l'ecole")
check(any("ÉCOLE" in m["text"] for m in msgs), "  and the chat opens at that message")

# "Show all N in …": the app opens with the same words in its search box, nothing chosen for the user
win.show_home()
type_("milk")
win.open_hit(search.Hit("notes", "", ""), "milk")
pump(lambda: win.current == "notes" and win.find_hook is not None, 30)
check(win.find_hook and win.find_hook[1].get() == "milk", "'Show all' opens the app with the same words in its search box")

spec = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"search"' in spec, "the packaged app includes the search")
check(files_now() == before, "searching wrote no file (everything stays in memory)")
win.close()
a.destroy()
print("\nE4 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
