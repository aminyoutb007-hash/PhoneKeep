"""H2: the Storage card's clean-up suggestions and the storage forecast
(docs/spec/13-phone-health.md#h2-storage-card-and-clean-up-suggestions).

Done when:
- suggestions are listed largest first, each with a size and either a working button or exact steps;
- on a real iPhone, following the WhatsApp and Messages steps frees roughly the space shown (the owner's check);
- the forecast appears with 4+ snapshots of rising use, and not otherwise.
Sizes come from a copy of the test backup with WhatsApp media and Messages attachments added to its Manifest;
nothing touches a real phone. Names are invented.
"""
import datetime as dt
import json, os, plistlib, shutil, sqlite3, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE / "work" / "h2"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)
os.environ["PHONEKEEP_HOME"] = str(W / "home")
sys.path.insert(0, str(HERE.parent))

import checkup as cu
import deviceinfo as di
import phonekeep as wv
import storage_advice as sa

failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


GB, MB = 1000 ** 3, 1000 ** 2

# -- the list: biggest saving first, 500 MB at least, each with exact steps ---------------------------------------
apps = [di.AppSize(f"com.example.app{i}", f"Example App {i}", (i + 1) * 40 * MB, (i + 1) * 20 * MB) for i in range(25)]
sugg = sa.build(wa_chats=[("Family Group", int(4.2 * GB)), ("Football Club", int(1.1 * GB)), ("Sam", 300 * MB),
                          ("Old Friend", 0)],
                wab_chats=[("Shop Orders", 200 * MB)], attachments=int(2.6 * GB), apps=apps, music=900 * MB,
                backup_day="3 Nov")
check([s.key for s in sugg] == ["apps", "whatsapp", "messages", "music"], f"largest first: {[s.key for s in sugg]}")
check(all(s.size > 0 and s.steps.startswith("On the iPhone: ") and "about" in s.title for s in sugg),
      "each has a size marked 'about' and exact steps on the phone")
check("wab" not in [s.key for s in sugg] and "whatsappbusiness" not in [s.key for s in sugg],
      "WhatsApp Business media under 500 MB isn't suggested")
wa = next(s for s in sugg if s.key == "whatsapp")
check(wa.title == "WhatsApp media: about 5.6 GB in 3 chats", f"WhatsApp title: {wa.title}")
check([n for n, _ in wa.items] == ["Family Group", "Football Club", "Sam"], "its chats, most media first (empty ones left out)")
check("WhatsApp → Settings → Storage and Data → Manage Storage" in wa.steps and "backup of 3 Nov" in wa.note,
      "the spec's steps, and where the media is kept")
msg = next(s for s in sugg if s.key == "messages")
check(msg.title == "Message attachments: about 2.6 GB"
      and "Settings → General → iPhone Storage → Messages → Review Large Attachments" in msg.steps, f"Messages: {msg.title}")
ap = next(s for s in sugg if s.key == "apps")
check(len(ap.items) == 20 and ap.items[0][0] == "Example App 24" and ap.title.startswith("Large apps: the 20 largest use about"),
      f"the 20 largest apps with sizes: {ap.title}")
check("Offload App" in ap.steps and "Delete App" in ap.steps, "apps: offload or delete, in Settings")
mu = next(s for s in sugg if s.key == "music")
check(mu.title == "Downloaded music: about 900 MB" and "Remove Download" in mu.steps, f"music: {mu.title}")
check(sa.build(wa_chats=[("A", 499 * MB)], attachments=499 * MB, music=499 * MB) == [], "nothing under 500 MB is suggested")
check(sa.build() == [], "nothing known: no suggestions")
check([sa.about(x) for x in (12.4 * GB, 1.04 * GB, 640 * MB, 42 * MB)] == ["about 12 GB", "about 1 GB", "about 640 MB", "about 42 MB"],
      "estimates are rounded and say 'about'")

# -- the forecast: 4+ backups of rising use, and not otherwise ---------------------------------------------------
def hist(used_gb, every_days=14, total=128):
    t0 = dt.datetime(2026, 8, 1)
    return [{"when": (t0 + dt.timedelta(days=i * every_days)).isoformat(), "total": total * GB,
             "free": int((total - u) * GB)} for i, u in enumerate(used_gb)]


check(sa.forecast(hist([100, 103, 106])) is None, "3 backups: no forecast yet")
f = sa.forecast(hist([100, 103, 106, 109]))
check(f == "At this rate the iPhone will be full in about 3 months.", f"4 backups rising 3 GB a fortnight, 19 GB free: {f}")
check(sa.forecast(hist([100, 100.1, 99.9, 100.2])) is None, "flat use: no forecast")
check(sa.forecast(hist([110, 107, 104, 101])) is None, "falling use: no forecast")
check(sa.forecast(hist([120, 122, 124, 126])) == "At this rate the iPhone will be full in about 2 weeks.",
      f"close to full: {sa.forecast(hist([120, 122, 124, 126]))}")
check(sa.forecast(hist([20, 20.8, 21.6, 22.4])) is None, "years away: no line")
check(sa.forecast(hist([100, 103]) + [{"when": "bad"}, {"total": 1}]) is None, "broken entries are ignored")

# -- sizes from a backup -----------------------------------------------------------------------------------------
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
bk = W / "Backups" / "00008030-H2TEST"
shutil.copytree(fake, bk)
man = sqlite3.connect(bk / "Manifest.db")
fid = man.execute("SELECT fileID FROM Files WHERE domain=? AND relativePath=?", (wv.WA_DOMAIN, wv.WA_DB)).fetchone()[0]
chat_db = sqlite3.connect(bk / fid[:2] / fid)
chat_db.execute("INSERT INTO ZWACHATSESSION (ZCONTACTJID, ZPARTNERNAME) VALUES (?, ?)",
                ("120363000000000001@g.us", "Family Group"))
chat_db.commit()
chat_db.close()


def add(domain, rel, size):
    blob = plistlib.dumps({"$objects": ["$null", {"LastModified": 1_760_000_000, "Size": size}]}, fmt=plistlib.FMT_BINARY)
    man.execute("INSERT INTO Files VALUES (?, ?, ?, 1, ?)",
                (os.urandom(20).hex(), domain, rel, blob))


for i in range(3):
    add(wv.WA_DOMAIN, f"Message/Media/120363000000000001@g.us/a/b/photo{i}.jpg", 400 * MB)
add(wv.WA_DOMAIN, "Message/Media/447700900456@s.whatsapp.net/c/d/video.mp4", 250 * MB)
add(wv.WA_DOMAIN, "Message/Media/447700900456@s.whatsapp.net/c/d/thumb.jpg", 0)
add("HomeDomain", "Library/SMS/Attachments/aa/01/IMG_0001.HEIC", 700 * MB)
add("HomeDomain", "Library/SMS/Attachments/ab/02/clip.mov", 300 * MB)
add("HomeDomain", "Library/SMS/sms.db-extra", 5 * GB)                     # not an attachment
man.commit()
man.close()

r = wv.BackupReader(bk, None, lambda m: None)
found = sa.from_backup(r)
r.close()
chats = dict(found["wa_chats"])
check(chats.get("Family Group") == 1200 * MB, f"WhatsApp media per chat, named from the chat list: {found['wa_chats']}")
check(any(n == 250 * MB and "7700" in name for name, n in found["wa_chats"]), "a chat with no name shows its number")
check(found["wab_chats"] is None, "no WhatsApp Business in the backup: not known")
check(found["attachments"] == 1000 * MB, f"Messages attachments only: {found['attachments']}")
sugg = sa.build(found["wa_chats"], found["wab_chats"], found["attachments"])
check([s.key for s in sugg] == ["whatsapp", "messages"] and sugg[0].title == "WhatsApp media: about 1.4 GB in 2 chats",
      f"from the backup: {[s.title for s in sugg]}")

# the apps' own databases record each item's size, also when the file isn't in the backup: those come first
man = sqlite3.connect(bk / "Manifest.db")
chat_db = sqlite3.connect(bk / fid[:2] / fid)
chat_db.execute("CREATE TABLE ZWAMEDIAITEM (Z_PK INTEGER PRIMARY KEY, ZMEDIALOCALPATH TEXT, ZFILESIZE INTEGER)")
fam = chat_db.execute("SELECT Z_PK FROM ZWACHATSESSION WHERE ZPARTNERNAME = 'Family Group'").fetchone()[0]
for i, (path, size) in enumerate((("Media/a.jpg", 2 * GB), ("Media/b.mp4", 1 * GB), (None, 5 * GB))):  # the last isn't on the phone
    chat_db.execute("INSERT INTO ZWAMEDIAITEM VALUES (?, ?, ?)", (100 + i, path, size))
    chat_db.execute("INSERT INTO ZWAMESSAGE (ZCHATSESSION, ZMEDIAITEM, ZMESSAGEDATE) VALUES (?, ?, 0)", (fam, 100 + i))
chat_db.commit()
chat_db.close()
sms_fid = man.execute("SELECT fileID FROM Files WHERE relativePath = 'Library/SMS/sms.db'").fetchone()[0]
man.close()
sms = sqlite3.connect(bk / sms_fid[:2] / sms_fid)
sms.execute("ALTER TABLE attachment ADD COLUMN total_bytes INTEGER")
sms.execute("UPDATE attachment SET total_bytes = 900000000 WHERE ROWID = (SELECT MIN(ROWID) FROM attachment)")
sms.commit()
sms.close()
r = wv.BackupReader(bk, None, lambda m: None)
found = sa.from_backup(r)
r.close()
check(dict(found["wa_chats"]) == {"Family Group": 3 * GB}, f"WhatsApp: the sizes its database records for media on the phone: {found['wa_chats']}")
check(found["attachments"] == 900 * MB, f"Messages: the sizes sms.db records: {found['attachments']}")

# -- the Storage details screen ----------------------------------------------------------------------------------
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    import checkup_ui
    import phone

    class Now:
        """Runs a job at once (the window's background runners, made synchronous for the test)."""
        def submit(self, fn, ok=None, err=None):
            try:
                v = fn()
            except Exception as e:
                return err and err(e)
            return ok and ok(v)

    class Live:
        def music(self):
            return [type("T", (), {"size": 400 * MB})(), type("T", (), {"size": 350 * MB})()]

    class Data:
        def __init__(self):
            self.reader = wv.BackupReader(bk, None, lambda m: None)

    class Win(tk.Toplevel):
        def __init__(self):
            super().__init__(root)
            self.content = tk.Frame(self)
            self.content.pack(fill="both", expand=True)
            self.backup_dir, self.udid, self.current = W / "Backups", "00008030-H2TEST", None
            self.backup_path = bk
            self.overview = di.Overview(name="Test iPhone", total=128 * GB, free=19 * GB, apps=apps)
            self.overview.battery = di.Battery(health=90)
            self.data, self.live = Data(), Live()
            self.backup_runner = self.live_runner = Now()
            self.view_header = lambda key, sub="": phone.PhoneWindow.view_header(self, key, sub)

        def _clear(self):
            for w in self.content.winfo_children():
                w.destroy()

        def show_home(self):
            pass

    pd = W / "Backups" / "00008030-H2TEST"
    for e in hist([100, 103, 106, 109]):
        cu.record(pd, di.Overview(total=e["total"], free=e["free"], battery=di.Battery(health=90)),
                  dt.datetime.fromisoformat(e["when"]))
    win = Win()
    checkup_ui.view(win)
    checkup_ui.details(win, "storage")
    win.update()
    texts = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                texts.append(c.cget("text"))
            walk(c)
    walk(win.content)
    keys = [s.key for s in win.storage_suggestions or []]
    check(keys == ["apps", "whatsapp", "messages", "music"], f"the Storage details list them, largest first: {keys}")
    shown = [t for t in texts if any(t == s.title for s in win.storage_suggestions)]
    check(shown == [s.title for s in win.storage_suggestions], "in that order on the screen")
    check(any(t.startswith("On the iPhone: WhatsApp → Settings") for t in texts) and any("Family Group" in t for t in texts),
          "with the steps and the chats")
    check("Downloaded music: about 750 MB" in texts, "music from the phone")
    check(win.storage_forecast == "At this rate the iPhone will be full in about 3 months."
          and win.storage_forecast in texts, f"the forecast under the bar: {win.storage_forecast}")
    check("Working out what takes the space…" not in texts, "the 'working it out' line goes once they're in")
    win.data.reader.close()

    # with the phone away and no backup open: say what isn't included, rather than a short list that looks complete
    win.data, win.live, win.overview = None, None, None
    checkup_ui.details(win, "storage")
    win.update()
    texts.clear()
    walk(win.content)
    check(any(t.startswith("Not included yet: chat sizes") and "app sizes and music" in t for t in texts),
          "what isn't included yet is said")
    root.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

spec = (HERE.parent / "packaging" / "PhoneKeep.spec").read_text(encoding="utf-8")
check('"storage_advice"' in spec, "the packaged app includes the suggestions")

print("\nH2 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
