"""D9: Save everything with one date range and one search (docs/spec/08-personal-data.md#d9-export-everything).

Done when: '"Last 30 days, mentioning *invoice*" saves only matching messages, notes and files from those 30 days.'
Checked on the stand-in backup (invented data, all from around 1 June 2025):
- one date range applies to every kind with dates; one search to every kind with text;
- "mentioning dinner" keeps only the matching message; nothing else mentions it;
- "mentioning milk" in a range keeps only the matching note, and only while its date is inside the range;
- kinds without dates (contacts) ignore the range; photos (no text) are left out of a search, and the
  contents page says why;
- the contents page states the phone, the backup's date and the filters used;
- the chat chooser's own dates still only touch chats (nothing changes for the existing exports);
- the Save everything sheet: ticks, dates, search, formats and a size estimate; Save gives what's chosen.
"""
import datetime as dt, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"

import exportfilter as ef
import phonekeep as wv
import sections as sx

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- the rule ---------------------------------------------------------------------------------------------------
D = dt.date
f = ef.Filter((D(2026, 10, 15), D(2026, 11, 13)), "Invoice")
check(f.keep(dt.datetime(2026, 11, 1, 9), "Your INVOICE is attached") and not f.keep(dt.datetime(2026, 9, 1), "invoice")
      and not f.keep(dt.datetime(2026, 11, 1), "hello") and not f.keep(None, "invoice"),
      "in the range AND mentioning the word (any case); undated items are left out while a range is set")
check(f.keep(None, "invoice", dated=False) and not f.keep(None, "hello", dated=False),
      "kinds that never have dates ignore the range, the search still applies")
check(f.in_dates("2026-11-13 23:59") and f.in_dates(1_700_000_000) is False and f.in_dates(D(2026, 10, 15)),
      "dates as text, timestamps and dates all work; both ends are included")
chats = [{"name": "Karim", "messages": [{"time": "2026-11-01 10:00", "text": "hi"}, {"time": "2026-01-01 10:00", "text": "hi"}]},
         {"name": "Shop", "messages": [{"time": "2026-11-02 10:00", "text": "Invoice 42"}, {"time": "2026-11-02 11:00", "text": "thanks"}]}]
check([(c["name"], [m["text"] for m in c["messages"]]) for c in ef.Filter((D(2026, 10, 15), None), "karim").chats(chats)]
      == [("Karim", ["hi"])], "a chat whose name matches keeps its messages in the range")
check([(c["name"], [m["text"] for m in c["messages"]]) for c in f.chats(chats)] == [("Shop", ["Invoice 42"])],
      "otherwise only the matching messages are kept")
check(f.describe() == "from 15 Oct 2026 to 13 Nov 2026, mentioning “Invoice”" and ef.Filter().describe() == "everything",
      f"the filters in words ({f.describe()})")

# -- exports from the stand-in backup -----------------------------------------------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
W = HERE / "work" / "d9"
shutil.rmtree(W, ignore_errors=True)
ALL = [k for k, *_ in sx.SECTIONS]
JUNE = (D(2025, 5, 31), D(2025, 6, 2))


def run(name, dates, search, sections=ALL):
    out = W / name
    sx.export_all(fake, out, None, list(sections), log=lambda m: None, dates=dates, search=search, all_dates=True)
    state = json.loads((out / "assets" / "sections.json").read_text(encoding="utf-8"))
    return out, state


def text_of(folder: Path) -> str:
    return " ".join(p.read_text(encoding="utf-8", errors="replace") for p in folder.rglob("*")
                    if p.is_file() and p.suffix in (".html", ".csv", ".txt", ".vcf", ".ics", ".json"))


out, st = run("dinner", JUNE, "dinner")
msgs = text_of(out / "Messages")
check(st["messages"]["count"] == 1 and "Dinner Friday?" in msgs and "Did you land?" not in msgs,
      f"'mentioning dinner': only the matching message is saved ({st['messages'].get('detail')})")
check(all(st[k]["count"] == 0 for k in ("notes", "calls", "calendar", "whatsapp")) and not (out / "Notes").exists(),
      "and nothing else, because nothing else mentions it")
check(st["photos"]["count"] == 0 and "no text to search" in st["photos"]["note"],
      f"photos are left out of a search, and the contents page says why ({st['photos']['note']})")
hub = (out / "index.html").read_text(encoding="utf-8")
check("<dt>Only</dt><dd>from 31 May 2025 to 02 Jun 2025, mentioning “dinner”</dd>" in hub
      and "Last Backup Date" in hub and "Device Name" in hub,
      "the contents page states the phone, the backup's date and the filters used")

out, st = run("milk", JUNE, "milk")
check(st["notes"]["count"] == 1 and "Milk" in text_of(out / "Notes") and "Bank PINs" not in text_of(out / "Notes")
      and st["messages"]["count"] == 0, "'mentioning milk' in the range: only the matching note")
out, st = run("milk-later", (D(2025, 7, 1), D(2025, 7, 31)), "milk")
check(st["notes"]["count"] == 0, "the same note outside the range is not saved")

out, st = run("dentist", (D(2025, 6, 1), D(2025, 6, 5)), "dentist")
cal = text_of(out / "Calendar")
check(st["calendar"]["count"] == 1 and "Dentist, check-up" in cal and "birthday" not in cal,
      "calendar: the matching event inside the range only")
check(st["contacts"]["count"] == 1 and "Smile & Co" in text_of(out / "Contacts"),
      "contacts have no dates: the range doesn't apply, the search does")

import photos as ph
_r = wv.BackupReader(fake, None, lambda m: None)
_items = ph.BackupPhotoSource(_r, W / "ph-cache").items()
_r.close()
pday = _items[0].when.date()                      # the stand-in backup's own photo dates
same = [i for i in _items if i.when.date() == pday]
out, st = run("one-day", (pday, pday), "", ["photos"])
check(st["photos"]["count"] == len(same) > 0, f"a date range alone keeps the photos of those days ({st['photos'].get('detail')})")
out, st = run("next-day", (pday + dt.timedelta(days=1), pday + dt.timedelta(days=1)), "", ["photos"])
check(st["photos"]["count"] == 0, "and none from another day")
out, st = run("june-only", (D(2025, 6, 1), D(2025, 6, 1)), "", ["calls", "messages"])
check(st["calls"]["count"] == 3, f"calls of that day ({st['calls'].get('detail')})")
check(st["messages"]["count"] > 0 and "Your code is 123456" not in text_of(out / "Messages"),
      "messages from the day before are left out")
out, st = run("2024", (D(2024, 1, 1), D(2024, 12, 31)), "", ["photos", "calls"])
check(st["photos"]["count"] == 0 and st["calls"]["count"] == 0, "a year with nothing saves nothing, and says so")
out, st = run("files", None, "sms.db", ["files"])
check(st["files"]["count"] == 1 and list((out / "All files").rglob("sms.db")), "All files: the search matches file names")

# the chat chooser's dates (existing exports) still only touch chat messages
out = W / "chooser"
sx.export_all(fake, out, None, ["messages", "calls"], log=lambda m: None, dates=(D(2025, 6, 1), D(2025, 6, 1)))
st = json.loads((out / "assets" / "sections.json").read_text(encoding="utf-8"))
check(st["calls"]["count"] == 3 and "Only" not in (out / "index.html").read_text(encoding="utf-8"),
      "the chat chooser's own dates don't filter calls (as before)")

# -- the sheet ------------------------------------------------------------------------------------------------------
try:
    import tkinter as tk
    import saveall_ui
    root = tk.Tk()
    root.withdraw()
    r = wv.BackupReader(fake, None, lambda m: None)
    d = saveall_ui.SaveEverythingDialog(root, {"messages": "3 chats", "voicemail": "nothing found"},
                                        lambda: saveall_ui.estimate_sizes(r, fake))
    for _ in range(100):
        root.update()
        if d.sizes:
            break
        import time; time.sleep(0.02)
    c = d.chosen()
    check(c["sections"] == [k for k in saveall_ui.ON_BY_DEFAULT if k != "voicemail"] and c["dates"] is None
          and c["search"] == "" and c["formats"] == {"web"},
          "the sheet starts with every kind ticked (All files and empty kinds not), all dates, no search, web pages")
    check("About " in d.note.cget("text") and d.sizes.get("photos", 0) > 0, f"with a size estimate: {d.note.cget('text')!r}")
    d.preset.set("Last 30 days")
    d._preset()
    d.search.set("invoice")
    d.vars["photos"].set(True)
    d.fvars["pdf"].set(True)
    c = d.chosen()
    today = dt.date.today()
    check(c["dates"] == (today - dt.timedelta(days=29), today) and c["search"] == "invoice" and c["formats"] == {"web", "pdf"},
          "Last 30 days + 'invoice' + PDF are read from the sheet")
    note = d.note.cget("text")
    check("mentioning “invoice”" in note and "no text to search" in note and "At most about" in note,
          f"it says what will be kept, and that photos are left out of a search: {note!r}")
    d.d_from.set("31/02/2026")
    d._update()
    check("isn't a date" in d.note.cget("text"), "a date that isn't one is pointed out")
    d.d_from.set("")
    d._ok()
    check(d.result is not None and d.result["search"] == "invoice", "Save gives what's chosen")
    check(saveall_ui.folder_name("Test iPhone", dt.datetime(2026, 11, 14, 1, 30)) == "Test iPhone - everything 2026-11-14 0130",
          "everything goes into one new folder named after the phone and the time")
    r.close()
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

src = (HERE.parent / "phone.py").read_text(encoding="utf-8")
check("Save everything…" in src and "all_dates=True" in src, "the phone window has Save everything…")

print("\nD9 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
