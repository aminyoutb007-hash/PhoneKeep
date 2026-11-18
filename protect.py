"""S6: saves protected with a password.

The owner's choice (18 Nov): documents are saved as password-protected PDFs (AES-256), which open on any Mac or PC
(Preview, Edge, Acrobat) once the password is typed; everything else goes into one encrypted ZIP (AES-256). A
stock Mac or Windows PC can't open an AES ZIP by double-clicking (Finder and Explorer only know the weak old ZIP
password scheme), so it needs 7-Zip (Windows), Keka or The Unarchiver (Mac); PhoneKeep says so where it saves one.

A protected save is made in PhoneKeep's private temporary folder (gone when PhoneKeep closes) and only the protected
files go to the folder the owner chose, each written next to its name and then renamed, so a stopped save leaves
nothing half-written and no unprotected copy outside the private folder. The password is used for that one save and
never kept, logged or shown.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Optional

MIN_LENGTH = 8
# already squeezed: deflating them again costs time and saves nothing
STORED = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".m4a", ".mp3",
          ".aac", ".caf", ".amr", ".opus", ".ogg", ".zip", ".gz", ".pdf", ".docx", ".xlsx", ".pptx", ".pages"}
ZIP_NOTE = ("It's an encrypted ZIP (AES-256). To open it on a Mac use Keka or The Unarchiver, on Windows 7-Zip; "
            "Finder and File Explorer can't open it by double-clicking.")


class ProtectError(Exception):
    pass


def password_problem(password: str, again: str) -> Optional[str]:
    """What's wrong with a new password, in plain words, or None."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if password != again:
        return "The two passwords aren't the same."
    if password.strip() != password:
        return "The password starts or ends with a space. Take it out, so it's easy to type again."
    return None


def _unique(p: Path) -> Path:
    k = 2
    out = p
    while out.exists() or out.with_name(out.name + ".part").exists():
        out = p.with_name(f"{p.stem} ({k}){p.suffix}")
        k += 1
    return out


def protect_pdf(src: Path, dest: Path, password: str) -> Path:
    """`src` as a PDF that opens only with `password` (AES-256, the PDF 2.0 way that Preview, Edge and Acrobat
    read), at `dest` or the next free name beside it. Written as .part first, then renamed."""
    from pypdf import PdfReader, PdfWriter
    dest = _unique(dest)
    part = dest.with_name(dest.name + ".part")
    try:
        writer = PdfWriter(clone_from=PdfReader(str(src)))
        writer.encrypt(user_password=password, owner_password=None, algorithm="AES-256")
        with open(part, "wb") as f:
            writer.write(f)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dest


def zip_files(items: list, dest: Path, password: str,
              progress: Optional[Callable[[float], None]] = None) -> Path:
    """[(file, name in the ZIP)] into one AES-256 ZIP at `dest` (or the next free name). Big files are fine
    (ZIP64); pictures, videos and other already-compressed files are stored, the rest deflated."""
    import pyzipper
    dest = _unique(dest)
    part = dest.with_name(dest.name + ".part")
    total = sum(max(1, Path(f).stat().st_size) for f, _n in items) or 1
    done = 0
    try:
        with pyzipper.AESZipFile(part, "w", compression=pyzipper.ZIP_DEFLATED, allowZip64=True,
                                 encryption=pyzipper.WZ_AES) as z:
            z.setpassword(password.encode("utf-8"))
            z.setencryption(pyzipper.WZ_AES, nbits=256)
            for f, name in items:
                stored = Path(f).suffix.lower() in STORED
                z.write(f, name, compress_type=pyzipper.ZIP_STORED if stored else pyzipper.ZIP_DEFLATED)
                done += max(1, Path(f).stat().st_size)
                if progress:
                    progress(100.0 * done / total)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dest


def protect_folder(staging: Path, dest_folder: Path, password: str, zip_name: str,
                   progress: Optional[Callable[[float], None]] = None) -> list:
    """Everything a save made in `staging`, protected into `dest_folder`: only PDFs -> each a password PDF;
    anything else -> one AES-256 ZIP named `zip_name`.zip with the same folders inside. Returns what was
    written. `staging` is emptied afterwards (it's in the private folder anyway)."""
    staging, dest_folder = Path(staging), Path(dest_folder)
    files = sorted(p for p in staging.rglob("*") if p.is_file() and not p.name.endswith(".part"))
    if not files:
        return []
    dest_folder.mkdir(parents=True, exist_ok=True)
    out = []
    try:
        if all(p.suffix.lower() == ".pdf" for p in files):
            try:
                for i, p in enumerate(files):
                    out.append(protect_pdf(p, dest_folder / p.name, password))
                    if progress:
                        progress(100.0 * (i + 1) / len(files))
                return out
            except Exception:
                # a file named .pdf that isn't one a PDF reader can open (an app's own file, a damaged one): the
                # whole save goes into the ZIP instead, still protected, never lost to an error
                for q in out:
                    Path(q).unlink(missing_ok=True)
                out = []
        safe = "".join(ch for ch in zip_name if ch not in '/\\:*?"<>|').strip() or "PhoneKeep"
        out.append(zip_files([(p, p.relative_to(staging).as_posix()) for p in files],
                             dest_folder / f"{safe}.zip", password, progress))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return out
