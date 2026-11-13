"""M3: chats to PDF and print (docs/spec/06-messages.md#m3-chats-to-pdf-and-print).

Done when:
- "A 2,000-message chat with photos produces a PDF in under 30 seconds that opens in Preview / Acrobat
  and prints correctly."  → a synthetic 2,000-message group chat with 200 full-size photos is written
  and timed; the file is a well-formed PDF with one page header per page and "Page N of M" footers.
- "Arabic, French and emoji render correctly." → every character drawn is in the embedded font (Arabic
  shaped into its joined forms, nothing left as a missing glyph); emoji (skin tones, flags, ZWJ
  families, keycaps) become colour images; French accents are kept.
Also: one PDF per chat or one combined, through the real export for Messages and WhatsApp.
"""
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

from PIL import Image

import chat_pdf as cp

W = HERE / "work" / "m3"
shutil.rmtree(W, ignore_errors=True)
(W / "media").mkdir(parents=True)
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


def pdf_pages(p: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", p.read_bytes()))


def pdf_text(p: Path):
    if not shutil.which("pdftotext"):
        return None
    r = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(p), "-"], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


# -- text handling ---------------------------------------------------------------------------------------------
runs = cp.split_runs("Salut 👋🏽 ça va? 🇲🇦 👨‍👩‍👧 1️⃣ ✓")
emoji = [s for k, s in runs if k == "emoji"]
check(emoji == ["👋🏽", "🇲🇦", "👨‍👩‍👧", "1️⃣"], f"emoji sequences kept whole (skin tone, flag, family, keycap); ✓ stays text: {emoji}")
check([s for k, s in cp.split_runs("❤️ ❤ ✅ ☕") if k == "emoji"] == ["❤️", "✅", "☕"], "a symbol is an emoji when it is one by default or asks to be")
check("".join(s for _k, s in runs) == "Salut 👋🏽 ça va? 🇲🇦 👨‍👩‍👧 1️⃣ ✓", "splitting loses nothing")

cache = cp.EmojiCache(W / "emoji")
for e in emoji:
    png = cache.png(e)
    ok = bool(png) and Image.open(png).getbbox() is not None
    check(ok, f"{e} drawn in colour")

cp._register_fonts()
from reportlab.pdfbase.ttfonts import TTFont
covered = set(TTFont("chk", str(cp._font_file("DejaVuSans.ttf"))).face.charToGlyph)
samples = ["مرحبا كيف حالك؟ إن شاء الله نلتقي غدا", "بسم الله الرحمن الرحيم", "لا إله إلا الله ﷺ",
           "Ça va très bien, à demain chez Hélène — œuf, garçon, naïve"]
for t in samples:
    shown = cp._shape_arabic(cp.drawable(t)) if cp.is_rtl(t) else cp.drawable(t)
    missing = {hex(ord(c)) for c in shown if ord(c) not in covered and c != " "}
    check(not missing, f"every character of {t[:24]!r}… is in the font {sorted(missing)}")
shaped = cp._shape_arabic("مرحبا")
check(any(0xFE70 <= ord(c) <= 0xFEFF for c in shaped), "Arabic letters take their joined forms")
check(cp._shape_arabic("مرحبا")[-1] in "ﻣﻡم", "and are laid out right to left (first letter on the right)")
lines = cp._wrap_logical("كلمة " * 60, 120, 10.5)
check(len(lines) > 3 and lines[0].startswith("كلمة"), "long Arabic text wraps in reading order")

# -- done-when: 2,000 messages with photos in under 30 s -----------------------------------------------------
for i in range(20):
    Image.new("RGB", (3024, 4032) if i % 2 else (4032, 3024), (20 * i % 255, 120, 200)).save(W / "media" / f"p{i}.jpg", quality=88)
texts = ["Bonjour ! Ça va très bien, merci 😊", "مرحبا كيف حالك؟ إن شاء الله نلتقي غدا", "Rendez-vous à 18h 🚉",
         "👍🏽", "On se voit demain? 🇲🇦❤️", "شكرا جزيلا 🙏 à demain",
         "Voici le document pour l'appartement, je t'envoie aussi les photos de la cuisine et de la salle de bain."]
t0 = dt.datetime(2025, 1, 1, 8, 0)
msgs = []
for i in range(2000):
    m = {"time": (t0 + dt.timedelta(minutes=137 * i)).isoformat(), "from_me": i % 3 == 0,
         "sender": ("Karim", "Salma", "Yassine")[i % 3], "type": "text", "text": texts[i % len(texts)]}
    if i % 10 == 5:
        m.update(type="image", text="", media=f"media/p{i % 20}.jpg", caption="La vue 🌅" if i % 4 == 1 else "")
    elif i % 37 == 7:
        m.update(type="audio", text="", duration=42)
    elif i % 53 == 9:
        m.update(type="video", text="", media="media/clip.mp4")
    msgs.append(m)
msgs.insert(3, {"type": "system", "text": "Salma added Karim", "time": msgs[2]["time"]})
big = {"name": "Famille 🏡 العائلة", "group": True, "messages": msgs}
n_photos = sum(1 for m in msgs if m.get("type") == "image")
start = time.time()
out = cp.write_pdf([big], W / "big.pdf", W, "WhatsApp")
secs = time.time() - start
data = out.read_bytes()
pages = pdf_pages(out)
check(secs < 30, f"2,000 messages with {n_photos} photos: PDF in {secs:.1f} s (under 30 s)")
check(data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF") and pages > 20, f"a well-formed PDF, {pages} pages")
check(len(re.findall(rb"/Subtype\s*/Image", data)) >= 20, "the photos are in it")
txt = pdf_text(out)
if txt is not None:
    check(txt.count("Famille") >= pages, "the chat name is at the top of every page")
    check(f"Page 1 of {pages}" in txt and f"Page {pages} of {pages}" in txt, "pages are numbered 'Page N of M'")
    check("Ça va très bien" in txt and "Rendez-vous à 18h" in txt, "French text and accents are in the PDF")
    check("Voice message · 0:42" in txt, "voice notes show as 'Voice message · 0:42'")
    check("Saturday" in txt or "Monday" in txt, "day lines between days")
else:
    print("(pdftotext not installed: text checks of the PDF skipped)")
if shutil.which("pdftoppm"):
    r = subprocess.run(["pdftoppm", "-r", "30", "-png", "-f", "1", "-l", "1", str(out), str(W / "page")], capture_output=True)
    check(r.returncode == 0 and any(W.glob("page*.png")), "the PDF renders (as a viewer or printer would)")

# -- through the real export: Messages and WhatsApp, one per chat or combined -----------------------------------
import keychain
import sections as sx

keychain.use_memory()
fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
exp = W / "export"
sx.export_all(fake, exp, None, ["messages", "whatsapp"], include_media=True, log=lambda m: None, formats={"pdf"})
per_chat = sorted((exp / "Messages" / "PDF").glob("*.pdf"))
wa = sorted((exp / "WhatsApp" / "PDF").glob("*.pdf"))
check(len(per_chat) >= 2 and all(pdf_pages(p) >= 1 for p in per_chat), f"Messages: one PDF per chat ({len(per_chat)})")
check(len(wa) >= 1 and all(pdf_pages(p) >= 1 for p in wa), f"WhatsApp: one PDF per chat ({len(wa)})")
exp2 = W / "export2"
sx.export_all(fake, exp2, None, ["messages"], include_media=True, log=lambda m: None, formats={"pdf"}, pdf_combined=True)
one = sorted((exp2 / "Messages" / "PDF").glob("*.pdf"))
check(len(one) == 1 and pdf_pages(one[0]) >= len(per_chat), f"or one PDF with all chats, each from a new page ({[p.name for p in one]})")
check(one and one[0].name.endswith(f" and {len(per_chat) - 1} more chat.pdf" if len(per_chat) == 2 else " more chats.pdf"),
      f"the combined PDF is named after its chats: {[p.name for p in one]}")
txt = pdf_text(one[0]) if one else None
if txt is not None:
    names = [p.stem for p in per_chat]
    check(all(n.split(",")[0] in txt for n in names), f"the combined PDF has each chat's name at the top ({names})")

# Print only ever shows a dialog: never a script that tells another app to print, never "print" verbs that
# print straight away (12 Nov: scripting Preview printed at once and macOS kept relaunching the queue)
src = (HERE.parent / "chat_pdf.py").read_text(encoding="utf-8") + (HERE.parent / "phone.py").read_text(encoding="utf-8")
check("osascript" not in src and 'startfile(str(path), "print")' not in src and "lpr" not in src.split(),
      "Print never scripts another app or prints without a dialog")
opened = []
real_popen = subprocess.Popen
subprocess.Popen = lambda args, **k: opened.append(args)
try:
    said = cp.print_pdf(out) if sys.platform.startswith("linux") else "skipped"
finally:
    subprocess.Popen = real_popen
if sys.platform.startswith("linux"):
    check(opened and opened[0][0] == "xdg-open" and "Print" in said, f"on Linux it opens the PDF and says how to print: {said!r}")

print("\nM3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
