"""X2: backup redaction tool (docs/spec/12-engineering.md).

Done when: "A redacted copy of a real backup opens in PhoneKeep with every screen populated, and a search of
the copy for any name, number or sentence from the original finds nothing."
The 'real' backup here is the fake full backup (every kind of data); every personal string it contains is
collected first, then the whole output folder is searched for each one. The copy is opened with the normal
readers and every section must still load with the same number of rows. Media and attachments must be
placeholders of the same size with nothing inside.
"""
import json, os, shutil, sqlite3, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tools"))
os.environ["PYTHONUTF8"] = "1"

import phonekeep as wv
import sections as sx
import redact_backup as rb

W = HERE / "work" / "x2"
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


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)

# every personal string in the original: names, numbers, emails, message/note/calendar text, serial
personal = set()
r = wv.BackupReader(fake, None, lambda m: None)
ctx = sx.Ctx(r, W / "o", lambda m: None, True, wv.backup_info(fake))
for c in sx.load_contacts(ctx):
    for k in ("name", "first", "last", "org", "organization"):
        if c.get(k):
            personal.add(str(c[k]))
    for ph in c.get("phones", []) or []:
        personal.add(str(ph[1] if isinstance(ph, (list, tuple)) else ph))
    for em in c.get("emails", []) or []:
        personal.add(str(em[1] if isinstance(em, (list, tuple)) else em))
counts = {}
for key, loader in (("messages", sx.load_messages), ("calls", sx.load_calls), ("notes", sx.load_notes),
                    ("calendar", sx.load_calendar), ("voicemail", sx.load_voicemail), ("safari", sx.load_safari),
                    ("contacts", sx.load_contacts)):
    try:
        v = loader(ctx)
        counts[key] = len(v[0]) + len(v[1]) if key == "safari" else len(v)
        if key == "messages":
            for ch in v:
                for m in ch["messages"]:
                    if m.get("text") and len(m["text"]) > 3:
                        personal.add(m["text"])
                personal.add(ch.get("name", ""))
        elif key == "notes":
            for n in v:
                for k in ("title", "text", "body"):
                    if n.get(k):
                        personal.add(str(n[k]))
        elif key == "calendar":
            for e in v:
                for k in ("title", "summary", "location"):
                    if e.get(k):
                        personal.add(str(e[k]))
    except Exception as e:
        counts[key] = f"error: {e}"
wa = wv.load_whatsapp(r, False, True, lambda x: x, lambda m: None)
counts["whatsapp"] = len(wa["chats"])
for ch in wa["chats"]:
    personal.add(ch.get("name", ""))
    for m in ch["messages"]:
        if m.get("text") and len(m["text"]) > 3:
            personal.add(m["text"])
import plistlib
with open(fake / "Info.plist", "rb") as f:
    info = plistlib.load(f)
for k in ("Phone Number", "Device Name", "Serial Number"):
    if info.get(k):
        personal.add(str(info[k]))
r.close()
personal = {p for p in personal if p and len(p.strip()) > 2 and p not in ("Group update",)}
check(len(personal) > 15, f"{len(personal)} personal strings collected from the original")

# -- redact ----------------------------------------------------------------------------------------------------
out = W / "redacted"
report = rb.redact_backup(fake, out, None, log=lambda m: None)
check(report["databases redacted"] >= 7, f"databases redacted: {report['databases redacted']}")
check(report["photos & videos"] >= 3 and report["attachments & voice notes"] >= 1, f"media replaced: photos {report['photos & videos']}, attachments {report['attachments & voice notes']}")
check(report["names"] >= 3 and report["phone numbers"] >= 3 and report["text passages"] >= 5, f"report: {dict(report)}")

# -- nothing personal survives anywhere in the copy ----------------------------------------------------------------
hits = []
for f in out.rglob("*"):
    if f.is_file():
        data = f.read_bytes()
        for p in personal:
            for enc in (p.encode("utf-8"), p.encode("utf-16-le")):
                if enc in data:
                    hits.append((f.name, p))
check(not hits, f"a search of the copy for every original name, number and sentence finds nothing ({len(hits)} hits: {hits[:5]})")

# -- it opens with every screen populated ------------------------------------------------------------------------
r2 = wv.BackupReader(out, None, lambda m: None)
ctx2 = sx.Ctx(r2, W / "o2", lambda m: None, True, wv.backup_info(out))
for key, loader in (("messages", sx.load_messages), ("calls", sx.load_calls), ("notes", sx.load_notes),
                    ("calendar", sx.load_calendar), ("voicemail", sx.load_voicemail), ("safari", sx.load_safari),
                    ("contacts", sx.load_contacts)):
    v = loader(ctx2)
    n = len(v[0]) + len(v[1]) if key == "safari" else len(v)
    check(n == counts[key], f"{key}: {n} rows in the copy (original {counts[key]})")
wa2 = wv.load_whatsapp(r2, False, True, lambda x: x, lambda m: None)
check(len(wa2["chats"]) == counts["whatsapp"] and all(m.get("text") for ch in wa2["chats"] for m in ch["messages"] if m.get("type") == "text"),
      "WhatsApp chats open with generated text")
msgs2 = sx.load_messages(ctx2)
check(sum(1 for ch in msgs2 for m in ch["messages"] if (m.get("text") or "").strip()) >= 5, "messages have generated text")
r2.close()

# consistent replacements and sizes
m = rb.Mapper()
check(m.name("Sara Fathi") == m.name("Sara Fathi") and m.name("Sara Fathi") != "Sara Fathi", "the same name maps to the same fake name")
check(m.phone("+44 7700 900123") == m.phone("+447700900123".replace("+447700900123", "+44 7700 900123")) and m.phone("07700 900456").startswith("+447700"), "numbers map to the reserved test range")
check(m.email("sara@example.org").endswith("@example.com"), "emails map to example.com")
t = m.text("Did you land? Call me when you can.")
check(abs(len(t) - len("Did you land? Call me when you can.")) <= 2 and "land" not in t, f"text replaced by words of about the same length: {t!r}")
check(m.jid("447700900123@s.whatsapp.net").endswith("@s.whatsapp.net") and "447700900123" not in m.jid("447700900123@s.whatsapp.net"), "WhatsApp ids keep their shape")

# placeholders keep the size, carry no content
man = sqlite3.connect(fake / "Manifest.db")
for fid, rel in man.execute("SELECT fileID, relativePath FROM Files WHERE domain='CameraRollDomain' AND flags=1"):
    a, b = fake / fid[:2] / fid, out / fid[:2] / fid
    same_size = b.exists() and a.stat().st_size == b.stat().st_size
    if rel.lower().endswith((".jpg", ".jpeg", ".png")):
        check(same_size and a.read_bytes() != b.read_bytes(), f"{Path(rel).name}: placeholder of the same size ({b.stat().st_size} bytes), different content")
    else:
        check(same_size, f"{Path(rel).name}: placeholder of the same size ({b.stat().st_size} bytes)")
with open(out / "Info.plist", "rb") as f:
    info2 = plistlib.load(f)
check(info2.get("Phone Number") != info.get("Phone Number") and info2.get("Device Name") != info.get("Device Name"), "phone number and device name replaced in Info.plist")
with open(out / "Manifest.plist", "rb") as f:
    check(plistlib.load(f).get("IsEncrypted") is False, "the copy is an unencrypted backup")

# the command line: output folder must be empty; password never on the command line
rr = subprocess.run([sys.executable, str(HERE.parent / "tools" / "redact_backup.py"), "--help"], capture_output=True, text=True)
check("--password-stdin" in rr.stdout and "--password " not in rr.stdout, "CLI takes the password on stdin only")
rr = subprocess.run([sys.executable, str(HERE.parent / "tools" / "redact_backup.py"), str(fake), str(out)], capture_output=True, text=True)
check(rr.returncode != 0 and "not empty" in (rr.stderr + rr.stdout), "refuses to write into a non-empty folder")

print("\nX2 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
