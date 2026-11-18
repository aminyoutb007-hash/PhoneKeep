"""S6: saves protected with a password, on the invented FULLTEST backup.

protect.py: a password PDF (AES-256) opens only with its password (pypdf, and PDFKit on a Mac); an AES-256 ZIP
reads only with it, and the zip that comes with the Mac can't open it; nothing is left half-written; a weak or
mistyped password is refused in plain words.
The phone window: the password switch (off by default); with it on, Save all notes, Save ticked chats as PDF, a
Save from a list and Save everything go into the folder chosen only as protected files, are made in the private
folder (no readable copy in Saved files or anywhere else), and the password is never written anywhere. Cancelling
the password or the folder saves nothing and leaves nothing behind. With the switch off, saves are as before.
"""
import json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import keychain
keychain._backend = lambda: None                      # no real keychain in a test
import phonekeep as wv
import protect

failures = []
PW = "correct horse 42"


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
W = HERE / "work" / "s6"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)

# -- protect.py ----------------------------------------------------------------------------------------------
from pypdf import PdfReader
from reportlab.pdfgen import canvas
import pyzipper


def pdf_locked(p: Path) -> bool:
    """Encrypted with AES-256, refuses a wrong password, opens with the right one."""
    r = PdfReader(str(p))
    if not r.is_encrypted or r.decrypt("wrong password") != 0:
        return False
    r = PdfReader(str(p))
    return r.decrypt(PW) != 0 and r._encryption is not None and r._encryption.V == 5


def zip_reads(p: Path) -> dict:
    with pyzipper.AESZipFile(p) as z:
        z.setpassword(PW.encode())
        return {n: z.read(n) for n in z.namelist()}


def zip_refuses_wrong(p: Path) -> bool:
    with pyzipper.AESZipFile(p) as z:
        z.setpassword(b"wrong password")
        try:
            z.read(z.namelist()[0])
        except RuntimeError:
            return True
    return False


check(protect.password_problem("short", "short") == "Use at least 8 characters."
      and protect.password_problem(PW, PW + "x") == "The two passwords aren't the same."
      and "space" in protect.password_problem(" " + PW, " " + PW)
      and protect.password_problem(PW, PW) is None,
      "a short, mistyped or space-edged password is refused in plain words; a good one is taken")

st = W / "stage"
st.mkdir()
c = canvas.Canvas(str(st / "Chat with Alex Example.pdf"))
c.drawString(72, 720, "Invented: the keys are under the blue pot")
c.save()
(W / "dest").mkdir()
(W / "dest" / "Chat with Alex Example.pdf").write_bytes(b"already here")
out = protect.protect_folder(st, W / "dest", PW, "Messages")
check([p.name for p in out] == ["Chat with Alex Example (2).pdf"] and pdf_locked(out[0]) and not st.exists()
      and (W / "dest" / "Chat with Alex Example.pdf").read_bytes() == b"already here",
      "only PDFs: each saved as a PDF that opens only with its password (AES-256), next to a file of the same name "
      "without replacing it; the private folder is emptied")
check(b"blue pot" not in out[0].read_bytes(), "  the PDF's text can't be read without the password")
if sys.platform == "darwin":
    from Foundation import NSURL
    from Quartz import PDFDocument
    d = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(out[0])))
    check(d.isLocked() and not d.unlockWithPassword_("wrong password") and d.unlockWithPassword_(PW)
          and "blue pot" in (d.string() or ""),
          "  the Mac's own PDF reader (PDFKit, as Preview) finds it locked and opens it with the password")

st.mkdir()
(st / "Photos").mkdir()
(st / "Photos" / "IMG_0001.JPG").write_bytes(b"\xff\xd8 invented" * 500)
(st / "contacts.csv").write_bytes(b"Name\nAlex Example\n")          # bytes: the same on Windows
out = protect.protect_folder(st, W / "dest", PW, "Contacts 2026-03-01")
got = zip_reads(out[0]) if out else {}
check([p.name for p in out] == ["Contacts 2026-03-01.zip"] and set(got) == {"Photos/IMG_0001.JPG", "contacts.csv"}
      and got["contacts.csv"] == b"Name\nAlex Example\n" and zip_refuses_wrong(out[0]) and not st.exists(),
      "anything else: one AES-256 ZIP with the same folders inside, read only with the password")
with zipfile.ZipFile(out[0]) as z:
    check({i.compress_type for i in z.infolist()} == {99} and b"Alex Example" not in out[0].read_bytes(),
          "  every file in it is AES-encrypted (method 99): no plain copy of any file inside")
if shutil.which("unzip"):
    r = subprocess.run(["unzip", "-o", "-P", "", str(out[0]), "-d", str(W / "plain")], capture_output=True, text=True)
    check(not (W / "plain" / "contacts.csv").exists(), "  the zip that comes with the computer can't open it")

real_write = pyzipper.AESZipFile.write


def broken(self, *a, **k):
    raise OSError(28, "No space left on device")


st.mkdir()
(st / "a.txt").write_text("invented", encoding="utf-8")
pyzipper.AESZipFile.write = broken
try:
    protect.protect_folder(st, W / "dest", PW, "Broken")
    raised = False
except OSError:
    raised = True
finally:
    pyzipper.AESZipFile.write = real_write
check(raised and not list((W / "dest").glob("Broken*")) and not st.exists(),
      "a save that stops (disk full) leaves no half-written file and no private copy")

# a file named .pdf that no PDF reader opens (an app's own file, a damaged one) beside a real PDF: the save becomes one
# ZIP holding both, still protected, instead of an error that saves nothing (F3: Save selected of a search's PDFs)
st = W / "staging-mixed"
(st / "Pages").mkdir(parents=True)
(st / "VLC").mkdir()
c = canvas.Canvas(str(st / "Pages" / "Invoice.pdf"))
c.drawString(72, 720, "Invented invoice")
c.save()
(st / "VLC" / "Invoice.pdf").write_bytes(b"not a PDF at all")
before = set((W / "dest").iterdir())
out = protect.protect_folder(st, W / "dest", PW, "App Files")
got = zip_reads(out[0]) if out else {}
check([p.name for p in out] == ["App Files.zip"] and set(got) == {"Pages/Invoice.pdf", "VLC/Invoice.pdf"}
      and got["VLC/Invoice.pdf"] == b"not a PDF at all" and set((W / "dest").iterdir()) - before == set(out)
      and not st.exists(),
      "a .pdf that isn't one: everything goes into one protected ZIP (each app's folder kept), no stray PDF, nothing "
      f"lost ({[p.name for p in out]})")

# -- the phone window ----------------------------------------------------------------------------------------
import tkinter as tk
from tkinter import messagebox as mb
import app as appmod
import phone
import protect_ui
import quicklook as ql
import ui

a = appmod.App()
a.withdraw()


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


BK = W / "open" / "00008030-S6OPEN0000000000"
shutil.copytree(fake, BK)
check(a.open_backup(BK), "the invented backup opens in a phone window")
win = a.phone_windows[-1]
win.withdraw()
check(pump(lambda: win.data is not None), "  its backup is read")
win.out_root = W / "Saved files" / "From iPhone"                       # PhoneKeep's own Saved files folder
check(not win.protect_saves and "off" in win.protect_btn.text, "the password switch is there, off by default")
win.toggle_protect()
check(win.protect_saves and "on" in win.protect_btn.text and "never kept" in str(win.bar_text.cget("text")),
      "  turned on, it says what it does")

asked, folders = [], []
phone.reveal = lambda *a, **k: None                    # no Finder in a test
mb.askyesnocancel = lambda *a, **k: False              # chats: one PDF each


def answer(pw):
    def ask(parent, what):
        asked.append(what)
        return pw
    protect_ui.ask_save_password = ask


def dest(name):
    d = W / name
    d.mkdir(exist_ok=True)
    phone.ask_save_folder = lambda parent, title, start: (folders.append(title), str(d))[1]
    return d


def readable_left() -> list:
    """Files a protected save left readable outside the folder chosen: in Saved files, or in the private folder."""
    left = [p for p in (W / "Saved files").rglob("*") if p.is_file()] if (W / "Saved files").exists() else []
    left += [p for p in Path(ql.private_dir()).glob("protect-*")] + [p for p in Path(ql.private_dir()).glob("build-*")]
    return left


def banner():
    return str(win.bar_text.cget("text"))


# 1. Save all notes (one app's web export): one ZIP
answer(PW)
d = dest("Notes out")
win.export_section("notes", {"web"})
check(pump(lambda: list(d.glob("*.zip")), 60), "Save all notes with the switch on ...")
z = list(d.glob("*.zip"))
names = zip_reads(z[0]) if z else {}
check(asked == ["Notes"] and folders and folders[-1].endswith("(with a password)") and len(z) == 1
      and list(d.iterdir()) == z and any(n.endswith("index.html") for n in names),
      f"  asks for the password, then where, and saves one encrypted ZIP there, nothing else ({[p.name for p in z]})")
check(pump(lambda: "with a password" in banner() and "7-Zip" in banner(), 10) and not readable_left(),
      "  says how to open it (Keka, The Unarchiver, 7-Zip), and no readable copy is left in Saved files or the "
      "private folder")

# 2. Save ticked chats as PDF: password PDFs
asked.clear()
d = dest("Chats out")
win.open_app("messages")
check(pump(lambda: any(isinstance(w, ui.ChatPanel) for w in win.content.winfo_children())), "Messages opens")
panel = next(w for w in win.content.winfo_children() if isinstance(w, ui.ChatPanel))
panel.selected = {("messages", c["id"]) for _k, _l, c in panel.rows[:2]}


def find_button(w, text):
    for c in w.winfo_children():
        if isinstance(c, ui.RoundButton) and c.text == text:
            return c
        r = find_button(c, text)
        if r is not None:
            return r


find_button(panel, "Save ticked as PDF").command()
check(pump(lambda: len(list(d.glob("*.pdf"))) == 2 and "with a password" in banner(), 120),
      "Save ticked chats as PDF with the switch on ...")
pdfs = sorted(d.glob("*.pdf"))
check(len(pdfs) == 2 and all(pdf_locked(p) for p in pdfs) and list(d.glob("*.zip")) == [],
      "  each chat is a PDF that opens only with the password (no ZIP for PDFs)")
check(not readable_left(), "  built in the private folder: no readable PDF in Saved files (the usual place it's "
                           "built) or anywhere else")

# 3. a save from a list (a Save that goes through the folder question): a ZIP
asked.clear()
d = dest("List out")
staging = win.out_dir("calls")
(staging / "Calls 2026-03-01.csv").write_text("Date,Name\n2026-03-01,Alex Example\n", encoding="utf-8")
win.saved([staging / "Calls 2026-03-01.csv"], staging, "file")
check(pump(lambda: list(d.glob("*.zip")), 30) and asked == ["Call History"]
      and Path(ql.private_dir()) in Path(staging).parents,
      "a Save from a list goes to the private folder first, then into one encrypted ZIP")
check(not readable_left() and b"Alex Example" not in list(d.glob("*.zip"))[0].read_bytes(),
      "  nothing readable left behind")

# 3b. App Files (a save into a folder inside the private one, named after the app): one ZIP, nothing left
asked.clear()
d = dest("Files out")
inner = win.out_dir("files")
sub = inner / "Pages"


def pull(app_id, path, into):
    Path(into).mkdir(parents=True, exist_ok=True)
    (Path(into) / Path(path).name).write_bytes(b"invented document")
    return True


win.live = type("Live", (), {"app_pull": staticmethod(pull)})()
win.run_save("1 item(s)", lambda: [sub / "Letter.pages"] if pull("x", "/Documents/Letter.pages", sub) else [],
             sub, "item", win.backup_runner)    # the app's folder inside the private one, as the old code passed
check(pump(lambda: list(d.glob("*.zip")), 30), "Save selected in App Files (the app's own folder inside) ...")
z = list(d.glob("*.zip"))
check(len(z) == 1 and set(zip_reads(z[0])) == {"Pages/Letter.pages"} and not readable_left() and not win._protected,
      f"  is one encrypted ZIP with the app's folder inside, nothing left behind ({sorted(zip_reads(z[0])) if z else []})")
check(win.is_protected(Path(inner) / "Pages" / "deeper") is False and not win._protected,
      "  a folder inside a finished save's private folder is no longer taken for a protected one")

# 3c. a save that fails: its private folder goes, and the password with it
d = dest("Failed out")
inner = win.out_dir("calls")


def boom():
    (Path(inner) / "half.csv").write_text("half", encoding="utf-8")
    raise OSError(28, "No space left on device")


win.run_save("rows", boom, inner, "file")
check(pump(lambda: "Couldn't save" in banner(), 30) and not win._protected and not readable_left()
      and list(d.iterdir()) == [],
      "a protected save that fails leaves no private copy, keeps no password and puts nothing in the folder chosen")

# 4. Save everything: one ZIP of the whole export
asked.clear()
d = dest("Everything out")
win.save_everything(choice={"sections": ["notes", "calls"], "formats": ["web"], "dates": None, "search": ""})
check(pump(lambda: list(d.glob("*.zip")) and "with a password" in banner(), 120), "Save everything with the switch on ...")
z = list(d.glob("*.zip"))
names = zip_reads(z[0]) if z else {}
check(asked == ["everything"] and len(z) == 1 and list(d.iterdir()) == z
      and any(n.endswith("/index.html") for n in names) and not readable_left(),
      f"  one encrypted ZIP with the whole export inside its folder, nothing readable left ({z[0].name if z else ''})")

# 5. cancelling saves nothing and leaves nothing
before = sorted(p.name for p in W.iterdir())
answer(None)
check(win.out_dir("calls") is None and not readable_left(), "cancelling the password: nothing is saved")
answer(PW)
phone.ask_save_folder = lambda parent, title, start: ""
check(win.out_dir("calls") is None and not readable_left() and not win._protected,
      "cancelling the folder after the password: nothing is saved, the private folder is removed")
win.save_everything(choice={"sections": ["notes"], "formats": ["web"], "dates": None, "search": ""})
check(not readable_left() and not win._protected and sorted(p.name for p in W.iterdir()) == before,
      "  the same for Save everything")

# 6. switched off: saves are as before
win.toggle_protect()
asked.clear()
d = dest("Plain out")
check(win.out_dir("calls") == d and not asked and "no longer" in banner(),
      "switched off: no password asked, the save goes straight to the folder chosen")

# 7. the password is never written anywhere
home = Path(os.environ["PHONEKEEP_HOME"])
hits = [p for p in home.rglob("*") if p.is_file() and p.stat().st_size < 50_000_000 and PW.encode() in p.read_bytes()]
hits += [p for p in W.rglob("*") if p.is_file() and PW.encode() in p.read_bytes()]
check(not hits, f"the password isn't in the settings, the activity log or any file ({[str(p) for p in hits][:3]})")

# 8. Photo clean-up's save before deleting isn't zipped (its copies are checked against the phone's)
win.toggle_protect()
asked.clear()
phone.ask_save_folder = lambda parent, title, start: str(d)
check(win.out_dir("photos", protectable=False) == d and not asked,
      "Photo clean-up's save keeps its photos as they are, to be checked before anything is deleted")

win.destroy()
a.destroy()
print("\nS6 TESTS:", "FAIL" if failures else "PASS", flush=True)
sys.exit(1 if failures else 0)
