"""Mac window tabs (5.1.2): macOS merged PhoneKeep's windows into tabs (full screen, or "Prefer tabs" on) and the tab
bar covered the top of the header.

Checks:
- on a Mac every window gets -tabbingmode disallowed as it's made: the main window (tk.Tk, and TkinterDnD's when
  installed), a plain Toplevel and a PhoneKeep-style Toplevel subclass;
- every window class in PhoneKeep's code is a Toplevel (or the main window), so the hook reaches it;
- Tk 8.6 without -tabbingmode (the installers bundle it): AppKit's switch turns window tabs off for the whole app
  instead, and every window is marked "no tabs" (5.2.2: before, the fix did nothing in the installed app);
- off a Mac nothing is called.
"""
import os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))
sys.path.insert(0, str(ROOT))
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


import tkinter as tk
import ui

# every window class in PhoneKeep's code is made from tk.Toplevel or is the main window
WINDOWS = [p for p in ROOT.glob("*.py")]
classes, other = [], []
for p in WINDOWS:
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r"\s*class (\w+)\((.*)\):", line)
        if m and ("Toplevel" in m.group(2) or re.search(r"\bTk\b|_dnd_root", m.group(2))):
            classes.append(f"{p.name}:{m.group(1)}")
        if re.search(r"(?<![\w.])(tk\.)?Toplevel\(|tk\.Tk\(\)", line) and not m and not line.lstrip().startswith("#"):
            other.append(f"{p.name}:{n}")
need = {"app.py:App", "app.py:OpenBackupDialog", "app.py:SettingsWindow", "phone.py:PhoneWindow", "quicklook.py:Viewer",
        "saveall_ui.py:SaveEverythingDialog", "ui.py:ChoiceDialog", "ui.py:TextDialog", "ui.py:PasswordDialog"}
check(need <= set(classes), f"the main, phone, Open a backup, viewer and dialog windows are Toplevel classes or the "
      f"main window ({len(classes)}: {', '.join(c.split(':')[1] for c in classes)})")
check(not other, "no window is made another way" + (f": {other}" if other else ""))


class FakeTk:
    def __init__(self, error):
        self.calls, self.error = [], error

    def call(self, *a):
        self.calls.append(a)
        if self.error:
            raise tk.TclError('bad attribute "-tabbingmode"')


class FakeWin:
    def __init__(self, error=False):
        self.tk, self._w = FakeTk(error), ".fake"


real, real_appkit = sys.platform, ui._appkit_no_tabs
try:
    sys.platform = "darwin"
    appkit_calls = []
    ui._appkit_no_tabs = lambda: appkit_calls.append(1) or True
    old = FakeWin(error=True)
    check(ui.no_tabs(old) is True and len(old.tk.calls) == 1 and appkit_calls == [1],
          "Tk 8.6 without -tabbingmode: no crash, AppKit's switch is used instead")
    new = FakeWin()
    appkit_calls.clear()
    ui.no_tabs(new)
    check(not appkit_calls, "with -tabbingmode, AppKit isn't needed")
    ui._appkit_no_tabs = real_appkit                # the live check below uses the real one
    new = FakeWin()
    check(ui.no_tabs(new) is True and new.tk.calls == [("wm", "attributes", ".fake", "-tabbingmode", "disallowed")],
          "on a Mac: wm attributes <win> -tabbingmode disallowed")
    sys.platform = "win32"
    off = FakeWin()
    check(ui.no_tabs(off) is False and not off.tk.calls, "off a Mac: nothing is called")
finally:
    sys.platform, ui._appkit_no_tabs = real, real_appkit

try:
    root = tk.Tk()
    root.withdraw()
except tk.TclError as ex:
    root = None
    print(f"(live check skipped: no display: {ex})")

if root is not None and sys.platform == "darwin":
    try:
        root.tk.call("wm", "attributes", root._w, "-tabbingmode")
        HAS_MODE = True
    except tk.TclError:
        HAS_MODE = False                 # Tk 8.6, as in the installers
    print(f"(Tk {root.tk.call('info', 'patchlevel')}: {'-tabbingmode' if HAS_MODE else 'no -tabbingmode, AppKit switch'})")

    def mode(w):
        if HAS_MODE:
            return str(w.tk.call("wm", "attributes", w._w, "-tabbingmode"))
        from AppKit import NSApplication, NSWindow
        w.update_idletasks()
        modes = {int(n.tabbingMode()) for n in NSApplication.sharedApplication().windows()}
        return ("disallowed" if not NSWindow.allowsAutomaticWindowTabbing() and modes == {ui.NS_TABBING_DISALLOWED}
                else f"allowed (automatic {bool(NSWindow.allowsAutomaticWindowTabbing())}, modes {sorted(modes)})")

    class Window(tk.Toplevel):          # like PhoneWindow, OpenBackupDialog, Viewer, ...
        def __init__(self, parent):
            super().__init__(parent)
            self.title("Test")

    plain, sub = tk.Toplevel(root), Window(root)
    for w in (plain, sub):
        w.withdraw()
    check((mode(root), mode(plain), mode(sub)) == ("disallowed",) * 3,
          f"every window is made with tabs off: main {mode(root)}, Toplevel {mode(plain)}, subclass {mode(sub)}")
    root.destroy()
    try:
        from tkinterdnd2 import TkinterDnD
        dnd = TkinterDnD.Tk()
        dnd.withdraw()
        check(mode(dnd) == "disallowed", f"the main window with drag and drop: {mode(dnd)}")
        dnd.destroy()
    except ImportError:
        print("(tkinterdnd2 not installed: drag-and-drop main window not checked)")
elif root is not None:
    check(ui.no_tabs(root) is False, "off a Mac the real windows are left as they are")
    root.destroy()

print("\nMAC TABS TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
