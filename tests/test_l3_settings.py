"""L3 (5.2): Settings in the Direction A layout (docs/spec/14-layouts.md#l3-settings-layout).

With a test home folder (no real phone, no real settings), checks:
- the list on the left: Backups, Automatic backups, Security, Saving, Activity, About;
- every card from before is still there (the Location card is now called "Where backups are kept"), plus Activity
  and About, in the list's order;
- every setting from before can still be found and changed, including the app lock (S2) and "Only when charging" (B2);
- each item in the list scrolls its cards into view and is highlighted;
- Activity shows the newest lines of the record kept on this computer, newest first.
"""
import json, os, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
import phonekeep as wv

keychain.use_memory()
import applock

applock.use_backend(lambda: "password", lambda reason: True)       # a computer that can lock PhoneKeep (S2)
W = HERE / "work" / "l3settings"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


wv.list_devices = lambda: []
import phone_write
import activity

activity.ACTIVITY_FILE = W / "activity.jsonl"
activity.ACTIVITY_FILE.write_text("".join(json.dumps({"when": f"2026-11-1{d}T10:00:00", "kind": "settings", "phone": None,
                                                        "summary": f"Test change {d}"}) + "\n" for d in range(7)),
                                     encoding="utf-8")
import app as appmod

appmod.SETTINGS_FILE = W / "settings-app.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(W / "Backups")}), encoding="utf-8")
a = appmod.App()
a.update()
win = appmod.SettingsWindow(a)           # drawn, so the list can scroll it
win.update()

GROUPS = ["Backups", "Automatic backups", "Security", "Saving", "Activity", "About"]
check(list(getattr(win, "nav", {})) == GROUPS, f"the list on the left: {list(getattr(win, 'nav', {}))}")
helper = "Menu bar helper" if sys.platform == "darwin" else "System tray helper"
before = {"What to include (Custom)", "Options", "Security", "Internet", "Automatic backups", "Snapshots", helper,
          "Where backups are kept", "Folders", "Use an existing backup"}
titles = [t for _g, _c, t in win.cards]
check(before <= set(titles) and {"Activity", "About"} <= set(titles) and len(titles) == len(before) + 2,
      f"every card from before is there, plus Activity and About ({len(titles)})")
order = [c for c in win.cards[0][1].master.pack_slaves() if c in [x[1] for x in win.cards]]
check(order == [c for _g, c, _t in win.cards] and [g for g, *_ in win.cards] == sorted([g for g, *_ in win.cards], key=GROUPS.index),
      "  in the list's order")
cards = {t: (g, c) for g, c, t in win.cards}
check(titles[:2] == ["Where backups are kept", "Snapshots"], f"  Backups starts with where they're kept, then snapshots ({titles[:2]})")
check(cards["Where backups are kept"][0] == "Backups" and cards["Snapshots"][0] == "Backups"
      and cards["Automatic backups"][0] == "Automatic backups" and cards["Security"][0] == "Security",
      "  each under its item (Backups: where they're kept, snapshots; Security: password, lock)")

# every setting from before, still there and still saving
names = ["picks", "media", "direct", "lock_var", "idle_var", "mode_var", "hour_var", "day_var", "charging_var",
         "phone_vars", "keep_mode", "keep_var", "login_var", "loc_line", "combo", "update_line", "sched_line"]
check(all(hasattr(win, n) for n in names), f"every setting from before is there ({[n for n in names if not hasattr(win, n)]} missing)")


def texts(w, out):
    for c in w.winfo_children():
        try:
            out.append(str(c.cget("text")))
        except Exception:
            pass
        texts(c, out)
    return out


words = texts(cards["Security"][1], [])
check(any(t.startswith("Lock PhoneKeep with") for t in words) and any("Lock again after" in t for t in words),
      "  the app lock (S2) is kept in Security")
all_chips = []
for _g, c, _t in win.cards:
    def walk(w):
        for k in w.winfo_children():
            all_chips.append(getattr(k, "text", None))
            walk(k)
    walk(c)
check("Only when charging" in all_chips, "  \"Only when charging\" (B2) is kept in Automatic backups")
chip = None


def find_chip(w):
    global chip
    for k in w.winfo_children():
        if getattr(k, "text", None) == "Only when charging":
            chip = k
        find_chip(k)


find_chip(cards["Automatic backups"][1])
was = bool(a.s["auto_backup_charging"])
chip.event_generate("<ButtonRelease-1>", x=4, y=4)      # a real click on the switch
win.update()
saved = json.loads(appmod.SETTINGS_FILE.read_text(encoding="utf-8")).get("auto_backup_charging")
check(bool(a.s["auto_backup_charging"]) == (not was) and saved == (not was),
      f"  a setting changed in the window is saved (Only when charging: {was} → {saved})")
chip.event_generate("<ButtonRelease-1>", x=4, y=4)
win.update()

# the list reaches each card
seen = []
for g in GROUPS:
    win.go_to(g)
    win.update()
    first = next(c for gg, c, _t in win.cards if gg == g)
    top, h = win.canvas.canvasy(0), win.canvas.winfo_height()
    inview = top - 1 <= first.winfo_y() <= top + h - 20
    lit = win.nav[g].cget("bg") == appmod.theme.ACCENT_PALE and all(
        win.nav[o].cget("bg") != appmod.theme.ACCENT_PALE for o in GROUPS if o != g)
    seen.append((g, inview, lit))
check(all(v and l for _g, v, l in seen), f"each item in the list scrolls its cards into view and is highlighted: {seen}")
win.go_to("Activity")
win.update()
sec_y = cards["Security"][1].winfo_y()
win.canvas.yview_moveto((sec_y + 5) / cards["Security"][1].master.winfo_height())       # scrolled by hand
win.update()
check(win.nav["Security"].cget("bg") == appmod.theme.ACCENT_PALE, "  scrolling by hand moves the highlight to the cards in view")
win.go_to("Backups")
win.update()
check(win.canvas.yview()[0] == 0.0, "  Backups goes back to the top")

# activity: the newest lines, newest first
act = win.activity_lines.get("1.0", "end").strip().splitlines()
check(len(act) == 7 and act[0].endswith("Test change 6") and act[-1].endswith("Test change 0")
      and act[0].startswith("16 Nov 2026 10:00 · "),
      f"Activity lists the record (S7: the last 12 months), newest first: {act[:2]}")
with open(activity.ACTIVITY_FILE, "a", encoding="utf-8") as f:     # damaged lines are skipped
    f.write('{"when": 5, "summary": "x"}\nnot json\n["a list"]\n')
check(appmod.activity_summary().splitlines()[0].endswith("Test change 6"), "  a damaged line in the record is skipped")
activity.ACTIVITY_FILE.write_bytes(b"\xff\xfe not utf-8")
check(appmod.activity_summary() == "Nothing recorded yet.", "  an unreadable record doesn't stop Settings opening")
activity.ACTIVITY_FILE.unlink()
check(appmod.activity_summary() == "Nothing recorded yet.", "  and says so when there's nothing yet")

win.destroy()
a.destroy()
print("\nL3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)), flush=True)
os._exit(1 if failures else 0)
