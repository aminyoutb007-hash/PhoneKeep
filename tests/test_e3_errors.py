"""E3: plain-language errors (docs/spec/05-ease-of-use.md).

Done when: "Each situation above, reproduced on purpose, shows its message; none shows a raw error."
Every situation in the table is reproduced from the technical text the phone helper or Python actually
produces, and must give exactly the message and button the spec lists. Then the real main window and
phone window are opened (hidden) and the errors shown through them are checked to be the same plain
sentences, with the technical text behind "Show details".
"""
import os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"

import errors
import phonekeep as wv
import keychain

keychain.use_memory()
failures = []


def check(cond, what):
    try:
        print(("ok   " if cond else "FAIL ") + what, flush=True)
    except UnicodeEncodeError:
        print(("ok   " if cond else "FAIL ") + what.encode("ascii", "replace").decode(), flush=True)
    if not cond:
        failures.append(what)


# -- each situation in the spec's table, from real technical text ---------------------------------
CASES = [
    # situation, technical text as it really appears, expected message (or prefix), expected button
    ("Phone locked", "pymobiledevice3.exceptions.DeviceLockedError: device is locked, enter passcode",
     "Unlock your iPhone to continue.", "Try again"),
    ("Not trusted", "2026-11-11 22:00:01 phonekeep[12] ERROR pymobiledevice3.exceptions.NotPairedError: pairing required",
     "Tap Trust on your iPhone and enter your passcode.", "Try again"),
    ("Not trusted (dialog pending)", "PairingDialogResponsePendingError: user hasn't answered the Trust dialog",
     "Tap Trust on your iPhone and enter your passcode.", "Try again"),
    ("Wi-Fi unreachable", "ConnectionFailedError: timed out connecting to device over Wi-Fi",
     "Can't reach your iPhone over Wi-Fi. Make sure it's on the same network, or use a cable.", "Try again"),
    ("Wi-Fi unreachable (no device)", "NoDeviceConnectedError: device not found",
     "Can't reach your iPhone over Wi-Fi. Make sure it's on the same network, or use a cable.", "Try again"),
    ("Disk full (helper text)", "OSError: [Errno 28] No space left on device: '/Volumes/Backup Drive/x'",
     "Not enough space on ", "Change location"),
    ("Disk full (the iPhone's refusal, which begins with its passcode prompt)",
     "Please enter the device passcode to continue the backup\npymobiledevice3.exceptions.NotEnoughDiskSpaceError: Device refused the backup: "
     "it needs more than 59487910309 bytes free at /Users/af/PhoneKeep/Backups/x/current to back up; host reported 45522085096 (13967059214 more needed).",
     "Not enough space on ", "Change location"),
    ("Wrong backup password", "Could not unlock the backup: ValueError: incorrect password (bad decrypt)",
     "That password doesn't open this backup.", "Try again"),
    ("Backup didn't finish", "incomplete backup: no Manifest.db in the backup folder",
     "The last backup didn't finish. Back up again to complete it.", "Back up now"),
    ("Unknown", "Traceback (most recent call last):\n  File x.py line 3\nRuntimeError: frobnicate() went sideways",
     "Something went wrong. Your existing backups are safe.", "Show details"),
]
for name, text, message, button in CASES:
    pr = errors.explain(text)
    ok = pr.message.startswith(message) and pr.button == button
    check(ok, f"{name}: {pr.message!r} / {pr.button}" + ("" if ok else f"  (expected {message!r} / {button})"))
    check(errors.is_plain(pr.message), f"{name}: no technical words in the message")
    check(pr.details == text, f"{name}: technical text kept for Show details")

pr = errors.explain("NotEnoughDiskSpaceError: Device refused the backup: it needs more than 59487910309 bytes free at /x; host reported 45522085096")
check("59.5 GB needed" in pr.message, f"the iPhone's own figure is shown: {pr.message!r}")

# disk full from a real Python exception, with the amount needed
e = OSError(28, "No space left on device")
pr = errors.explain(e, where=Path.home(), needed_bytes=12_000_000_000)
check(pr.key == "disk_full" and "12.0 GB needed" in pr.message and "free." in pr.message,
      f"disk full from OSError(28) names the need and the free space: {pr.message!r}")

# Windows-only wording only on Windows
pr = errors.explain("could not connect to usbmuxd socket")
if os.name == "nt":
    check("Apple Devices" in pr.message and pr.button == "Install Apple Devices", "Windows: Apple Devices app message")
else:
    check(pr.button == "Try again" and "iPhone" in pr.message, "Mac/Linux: reconnect the cable message")

# PhoneKeepError built from helper output carries message, button and details
err = wv.PhoneKeepError.from_problem("ERROR NotPairedError: pairing dialog")
check(str(err) == "Tap Trust on your iPhone and enter your passcode." and err.button == "Try again"
      and "NotPairedError" in err.details, "PhoneKeepError.from_problem: plain message, button, details")

# the old helper-output path gives the same plain sentence
check(wv._explain("usbmuxd: connection refused").startswith("Can't reach"), "_explain goes through the table")

# every message in the table is plain and ends with a full stop
for key, _pats, msg, button, _action in errors.TABLE:
    check(errors.is_plain(msg) and msg.rstrip().endswith(".") and button, f"table row {key}: plain, one button")

# -- the windows show the same sentences --------------------------------------------------------------
try:
    import tkinter as tk
    import app as appmod
    import ui
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="phonekeep-e3-"))
    appmod.SETTINGS_FILE = tmp / "settings.json"
    wv.list_devices = lambda: []
    a = appmod.App()
    a.withdraw()
    a.update()

    def shown():
        a.update()
        return a.bar_frame.winfo_manager() == "pack", a.bar_text.cget("text"), (a.bar_btn.text if a.bar_btn else None)

    a.show_problem(errors.explain("DeviceLockedError: device is locked"), retry=lambda: None)
    m, t, b = shown()
    check(m and t == "Unlock your iPhone to continue." and b == "Try again", f"main window banner: {t!r} / {b}")
    a.show_problem(errors.explain(OSError(28, "No space left on device"), where=tmp))
    m, t, b = shown()
    check(t.startswith("Not enough space on") and b == "Change location", f"main window disk-full banner: {t!r} / {b}")
    a.show_problem(errors.explain("RuntimeError: weird"))
    m, t, b = shown()
    check(t.startswith("Something went wrong") and b == "Show details", f"main window unknown-error banner: {t!r} / {b}")
    a.hide_problem()
    a.update()
    check(a.bar_frame.winfo_manager() == "", "banner hides")

    # errors reaching _finish come out plain, never raw
    a._finish(None, RuntimeError("boom"), None, False, None)
    m, t, b = shown()
    check(t.startswith("Something went wrong") and "boom" not in t and "boom" in a.bar_details_text,
          "a raw exception from a job shows the plain sentence; the text is behind Show details")

    # Show details (13 Nov): where an unexpected error happened, in a window big enough to read and copy
    import zlib
    try:
        zlib.decompress(b"not compressed")
    except zlib.error as ex:
        pr = errors.explain(ex)
    check("Traceback" in pr.details and "zlib" in pr.details and "test_e3_errors.py" in pr.details,
          "an unexpected error's details say where it happened (traceback)")
    check(errors.is_plain(pr.message), "while the sentence on screen stays plain")
    a.log("Backing up 'Test iPhone'…")
    import time as _t
    t_end = _t.time() + 5
    while _t.time() < t_end and "Test iPhone" not in a.log_box.get("1.0", "end"):
        a.update(); _t.sleep(0.02)
    dlg = ui.show_details(a, a.details_for_support(pr.details))
    a.update()
    shown_text = dlg.text.get("1.0", "end")
    check(dlg.winfo_width() >= 700 and dlg.resizable() == (True, True), f"the details window is large and resizable ({dlg.winfo_width()} px)")
    check("Traceback" in shown_text and "what PhoneKeep was doing" in shown_text and "Backing up 'Test iPhone'" in shown_text
          and wv.VERSION in shown_text, "it shows the error, what PhoneKeep was doing and the version")
    dlg.copy()
    check(a.clipboard_get() == dlg.content and "Copied" in dlg.copy_btn.text, "Copy all puts it on the clipboard")
    dlg.destroy()
    src = "".join((HERE.parent / f).read_text(encoding="utf-8") for f in ("app.py", "phone.py"))
    check('messagebox.showinfo("Details for support"' not in src, "no details squeezed into a small message box any more")
    a.destroy()

    # phone window: an app screen failing shows the sentence and a button, not the exception
    import phone
    import device as devmod

    class Dead:
        def __init__(self, udid, cache_dir=None):
            raise RuntimeError("ConnectionFailedError: timed out")
    devmod.LiveDevice = Dead

    class FakeApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.withdraw()
            self.s = {"backup_dir": str(tmp / "nowhere"), "archive_dir": str(tmp / "arch")}
            self.busy = False
            self._backup_password = None

        def detect(self, silent=False):
            pass

        def open_settings(self, focus=None):
            pass
    fa = FakeApp()
    w = phone.PhoneWindow(fa, {"DeviceName": "E3 iPhone"}, "00008030-E3")
    w.withdraw()
    import time
    t0 = time.time()
    while time.time() - t0 < 10 and w.live_error is None:
        fa.update(); time.sleep(0.02)
    check(w.live_error == "Can't reach your iPhone over Wi-Fi. Make sure it's on the same network, or use a cable.",
          f"phone window live error is plain: {w.live_error!r}")
    def walk(widget):
        for x in widget.winfo_children():
            yield x
            yield from walk(x)
    w.open_app("music")
    t0 = time.time()
    while time.time() - t0 < 10:
        fa.update(); time.sleep(0.02)
        if not any(isinstance(x, tk.Label) and x.cget("text") == "Reading from the iPhone…" for x in walk(w.content)):
            break
    texts = [x.cget("text") for x in walk(w.content) if isinstance(x, tk.Label) and str(x.cget("fg")).lower() == phone.RED.lower()]
    btns = [x.text for x in walk(w.content) if hasattr(x, "text")]
    check(texts and texts[0].startswith("Can't reach your iPhone") and "Try again" in btns,
          f"phone window app screen: {texts[:1]} / buttons {btns}")
    w.close()
    fa.destroy()
except tk.TclError as ex:
    print(f"(window checks skipped: no display: {ex})")

# an interrupted backup folder is recognised
import tempfile as _tf
_d = Path(_tf.mkdtemp()) / "00008030-HALF"
(_d / "Snapshot").mkdir(parents=True); (_d / "1a").mkdir()
check(wv.backup_incomplete(_d) and not wv.backup_incomplete(Path(_tf.mkdtemp())), "an interrupted backup folder (Snapshot/blobs, no Manifest.db) is recognised")

print("\nE3 TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
