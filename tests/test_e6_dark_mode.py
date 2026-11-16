"""E6: dark mode (docs/spec/05-ease-of-use.md#e6-dark-mode).

Done when: "Every screen is readable in dark mode; no white flashes; screenshots of all screens in both modes are
attached to the pull request." (The screenshots are in docs/evidence/e6-dark-mode; this test checks the rest.)
- the mode: Settings → Appearance (System, Light, Dark) or, with System, the computer's own setting; tests stay light
  unless they ask (so every other test's pictures don't depend on the computer);
- dark colours: text on every background PhoneKeep uses is at least 4.5:1 (WCAG AA);
- every widget of the main window, a phone window (home, a chat, the check-up, Storage) and Settings, in dark mode:
  no light background left, and every label readable on its own background;
- a new window is dark from the moment it's made (no white flash before its own colours arrive);
- Settings → Appearance saves the choice and says it shows the next time PhoneKeep opens;
- light mode is Direction A exactly as before (test_theme checks its values).
"""
import importlib, json, os, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PHONEKEEP_HOME", str(HERE / "work" / "home"))   # never the real ~/PhoneKeep
os.environ["PHONEKEEP_APPEARANCE"] = "dark"                            # this test looks at dark mode
sys.path.insert(0, str(HERE.parent))
os.environ["PYTHONUTF8"] = "1"
os.environ["PHONEKEEP_NO_HELPER"] = "1"
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def lum(c: str) -> float:
    c = c.lstrip("#")
    v = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


import theme
check(theme.MODE == "dark" and theme.DARK, "PHONEKEEP_APPEARANCE=dark gives dark mode")

# -- the mode PhoneKeep chooses ----------------------------------------------------------------------------------
W = HERE / "work" / "e6"
shutil.rmtree(W, ignore_errors=True)
W.mkdir(parents=True)


def mode_with(forced=None, saved=None, system_dark=False, test_home=True) -> str:
    env = dict(os.environ)
    try:
        os.environ.pop("PHONEKEEP_APPEARANCE", None)
        if forced:
            os.environ["PHONEKEEP_APPEARANCE"] = forced
        home = W / "home"
        shutil.rmtree(home, ignore_errors=True)
        home.mkdir()
        if saved:
            (home / "settings.json").write_text(json.dumps({"appearance": saved}), encoding="utf-8")
        os.environ["PHONEKEEP_HOME"] = str(home)
        if not test_home:
            os.environ.pop("PHONEKEEP_HOME")
            theme.saved_choice = lambda: saved or "system"
        theme.system_is_dark = lambda: system_dark
        return theme.choose_mode()
    finally:
        os.environ.clear()
        os.environ.update(env)


_saved, _sys = theme.saved_choice, theme.system_is_dark
check(mode_with(saved="dark") == "dark" and mode_with(saved="light", system_dark=True) == "light",
      "Settings → Appearance: Dark or Light is used whatever the computer is set to")
theme.saved_choice = _saved
check(mode_with(saved="system", system_dark=True, test_home=False) == "dark"
      and mode_with(saved="system", system_dark=False, test_home=False) == "light",
      "Same as this computer: dark when the computer is dark, light when it's light")
theme.saved_choice = _saved
check(mode_with(saved=None, system_dark=True) == "light",
      "tests (a test home folder) stay light even on a computer in dark mode, unless they ask")
check(mode_with(forced="dark", saved="light") == "dark", "PHONEKEEP_APPEARANCE overrides (screenshots)")
theme.saved_choice, theme.system_is_dark = _saved, _sys
(W / "home" / "settings.json").write_text("{not json", encoding="utf-8")
os.environ["PHONEKEEP_HOME"], keep_home = str(W / "home"), os.environ["PHONEKEEP_HOME"]
check(theme.saved_choice() == "system", "a damaged settings file means System")
os.environ["PHONEKEEP_HOME"] = keep_home

# -- dark colours read well ------------------------------------------------------------------------------------
pairs = [("TEXT", "BG"), ("TEXT", "CARD"), ("TEXT_2", "CARD"), ("TEXT_2", "BG"), ("TEXT_2", "SUBTLE"),
         ("ACCENT", "CARD"), ("ACCENT", "BG"), ("ON_ACCENT", "ACCENT"), ("ON_ACCENT", "ACCENT_HOVER"),
         ("TEXT", "ACCENT_PALE"), ("ACCENT", "ACCENT_PALE"), ("WARN_TEXT", "WARN_BG"), ("TEXT", "WARN_BG"),
         ("RED", "CARD"), ("TEXT", "ERROR_BG"), ("LINK", "CARD"), ("TEXT", "HIT"), ("TEXT", "CHAT_BG"), ("TEXT", "ME"),
         ("TEXT", "NOTE_BG"), ("TEXT", "SECONDARY_HOVER"), ("GOOD", "CARD"), ("CAUTION", "CARD"), ("BAD", "CARD"),
         ("ON_ACCENT_2", "PHONE_SCREEN"), ("HEADER_TITLE", "HEADER_BG"), ("HEADER_LINK", "HEADER_BG")]
low = [(a, b, round(contrast(getattr(theme, a), getattr(theme, b)), 2)) for a, b in pairs
       if contrast(getattr(theme, a), getattr(theme, b)) < 4.5]
check(not low, f"dark mode: text on every background is at least 4.5:1 ({len(pairs)} pairs){': ' + str(low) if low else ''}")
check(contrast(theme.DRAW_INK, theme.BG) >= 3 and contrast(theme.BORDER, theme.CARD) > 1.15,
      "  and the drawn phone's outline and the cards' borders can be seen")

# -- every widget, in the windows ------------------------------------------------------------------------------
import keychain
keychain.use_memory()
import applock
applock.use_backend(lambda: None, lambda reason: False)
import phonekeep as wv
import tkinter as tk
import ui

fake = HERE / "work" / "Backups" / "00008030-FULLTEST"
if not (fake / "Manifest.db").exists():
    import subprocess
    subprocess.run([sys.executable, str(HERE / "test_full_backup.py")], cwd=HERE.parent, check=True)
import app as appmod
import device as devmod


class NoDevice:
    def __init__(self, *a, **k):
        raise wv.PhoneKeepError("no phone")


devmod.LiveDevice = NoDevice
wv.list_devices = lambda: []
appmod.SETTINGS_FILE = W / "settings.json"
appmod.SETTINGS_FILE.write_text(json.dumps({"first_run_done": True, "backup_dir": str(W / "Backups")}), encoding="utf-8")
a = appmod.App()
a.after_cancel(a._timers.pop("first"))


def pump(until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


# light backgrounds left over, and labels that can't be read on their own background
BRIGHT = 0.35            # relative luminance: anything above is a light background in a dark window


def hexcolour(w, c):
    try:
        r, g, b = (v // 257 for v in w.winfo_rgb(c))
        return f"#{r:02x}{g:02x}{b:02x}"
    except tk.TclError:
        return None


# PhoneKeep's own drawings keep their colours: app tiles, buttons on the accent, the drawn phone, photo tiles, the
# storage bar, the status dots and the dark preview viewer
ALLOWED = {c.lower() for c in list(theme.APP_TILE.values()) + list(theme.STORAGE.values()) + list(theme.PHONE_ICON.values())
           + [theme.ACCENT, theme.ACCENT_HOVER, theme.PHONE_SCREEN, theme.PHONE_SCREEN_SOFT, theme.PHONE_HOME_BAR,
              theme.HIT, theme.ON_DARK]}


def audit(root, where: str):
    bright, unreadable, n = [], [], 0
    stack = [root]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if isinstance(w, (tk.Menu,)) or w.winfo_class().startswith("T"):        # menus and ttk: drawn by the system
            continue
        try:
            bg = hexcolour(w, w.cget("bg"))
        except tk.TclError:
            continue
        n += 1
        if bg and bg.lower() not in ALLOWED and lum(bg) > BRIGHT:
            bright.append(f"{w.winfo_class()} {bg} {str(w)[-40:]}")
        if isinstance(w, tk.Label) and str(w.cget("text")).strip() and bg:
            fg = hexcolour(w, w.cget("fg"))
            if fg and contrast(fg, bg) < 3:
                unreadable.append(f"{w.cget('text')[:30]!r} {fg} on {bg}")
    check(not bright, f"{where}: no light background among {n} widgets{': ' + str(bright[:6]) if bright else ''}")
    check(not unreadable, f"{where}: every label readable on its background{': ' + str(unreadable[:6]) if unreadable else ''}")


pump(lambda: False, 1)
audit(a, "the main window")
check(str(a.cget("bg")).lower() == theme.BG.lower(), "  its background is the dark one")

BK = W / "open" / "00008030-E6OPEN0000000000"
shutil.copytree(fake, BK)
check(a.open_backup(BK), "a phone window opens on the invented backup")
win = a.phone_windows[-1]
check(pump(lambda: win.data is not None and win.counts), "  its backup is read")
pump(lambda: False, 1)
audit(win, "the phone window's home")
for key in ("messages", "checkup", "notes"):
    win.open_app(key)
    pump(lambda: False, 2)
    audit(win, f"the phone window's {key}")

import deviceinfo as di, overview_ui
G = 1000 ** 3
win.overview = di.Overview(name="Test iPhone", model="iPhone 16", ios="26.5", total=128 * G, free=78 * G,
                           apps=[di.AppSize("com.example.maps", "Example Maps", 3 * G, 6 * G)])
win._apps_state = "done"
overview_ui.storage_view(win, win.overview)
pump(lambda: False, 1)
audit(win, "the phone window's Storage")

s = appmod.SettingsWindow(a)
pump(lambda: False, 1)
audit(s, "Settings")

# no white flash: a window is dark from the moment it's made
t = tk.Toplevel(a)
check(hexcolour(t, t.cget("bg")).lower() == theme.BG.lower(), "a new window is dark from the start (no white flash)")
t.destroy()
check(ui.use_light_appearance(a) == (sys.platform == "darwin"), "on a Mac the window takes the dark system look too")
if sys.platform == "darwin":
    from AppKit import NSApplication
    check(str(NSApplication.sharedApplication().appearance().name()) == "NSAppearanceNameDarkAqua",
          "  (dark aqua: the Mac draws its own controls dark)")

# Settings → Appearance
check("Appearance" in appmod.SETTINGS_GROUPS and s.appearance_var.get() == "system",
      "Settings has Appearance, Same as this computer by default")
s.appearance_var.set("light")
s.set_appearance("light")
check(json.loads(appmod.SETTINGS_FILE.read_text(encoding="utf-8"))["appearance"] == "light"
      and s.appearance_note.cget("text") == "PhoneKeep will be light the next time it opens.",
      f"choosing Light saves it and says when it shows: {s.appearance_note.cget('text')!r}")
s.set_appearance("dark")
check(s.appearance_note.cget("text") == "", "choosing what's showing now says nothing more")
os.environ["PHONEKEEP_HOME"] = str(W)
os.environ.pop("PHONEKEEP_APPEARANCE")
check(theme.saved_choice() == "dark", "  and the next start reads the saved choice")
os.environ["PHONEKEEP_HOME"] = keep_home

print("\nE6 TESTS:", "PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures))
sys.exit(1 if failures else 0)
