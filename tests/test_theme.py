"""Theme: Direction A ("Calm"), 15 Nov. Colours only; no widget moved or renamed.

Checks:
- theme.py has Direction A's values exactly;
- no window file writes a colour out: every colour comes from theme.py (saved files, the web archive and chat PDFs,
  keep their own look and aren't checked);
- the main button is accent with white text, a secondary button white with the border colour, and the selected row in
  sidebars and lists the pale accent;
- the font is the system font: Segoe UI on Windows, Tk's default (San Francisco) on a Mac; body 13 pt;
- window headers are light (15 Nov): card background, title in the text colour, second line in the secondary text
  colour, header links (Settings, Refresh from iPhone, Saved files) in the accent, a 1 px border line under each; every
  window that had the green header makes it with ui.header().
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


import theme

A = {"BG": "#F5F5F7", "CARD": "#FFFFFF", "BORDER": "#E5E5EA", "TEXT": "#1D1D1F", "TEXT_2": "#6E6E73",
     "ACCENT": "#0F766E", "ACCENT_HOVER": "#0B5A54", "ACCENT_PALE": "#E8F5F2", "WARN_TEXT": "#9A5B00",
     "WARN_BG": "#FFF7E6"}
wrong = {k: getattr(theme, k, None) for k, v in A.items() if str(getattr(theme, k, "")).upper() != v}
check(not wrong, f"theme.py has Direction A's colours exactly{': ' + str(wrong) if wrong else ''}")
check(13 <= theme.BODY_SIZE <= 14, f"body text 13-14 pt ({theme.BODY_SIZE})")
check(theme.font_family("X") == ("Segoe UI" if sys.platform == "win32" else "X"),
      "the system font: Segoe UI on Windows, Tk's default (San Francisco) on a Mac")

# every window's code: no colour written out
WINDOWS = ["app.py", "phone.py", "ui.py", "checkup_ui.py", "cleanup_ui.py", "saveall_ui.py", "overview_ui.py",
           "firstrun.py", "quicklook.py", "helper_ui.py", "applock.py", "deviceinfo.py"]
literal = re.compile(r"""["']#[0-9A-Fa-f]{6}["']|(?:fg|bg|fill|outline|background|foreground)=["']"""
                     r"""(?:white|black|red|green|blue|grey|gray)["']""")
found = []
for f in WINDOWS:
    p = ROOT / f
    if p.exists():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0] if not re.search(r"""["']#""", line) else line
            if literal.search(code) and not line.lstrip().startswith("#") and "colour_hex" not in line:
                found.append(f"{f}:{n}")
check(not found, "no window writes a colour out; all come from theme.py" + (f": {found}" if found else ""))

import ui
check((ui.GREEN, ui.BG, ui.CARD, ui.INK, ui.MUTED, ui.LINE, ui.GREEN_SOFT, ui.AMBER) ==
      (theme.ACCENT, theme.BG, theme.CARD, theme.TEXT, theme.TEXT_2, theme.BORDER, theme.ACCENT_PALE, theme.WARN_TEXT),
      "the windows' colour names are the theme's")
fill, hover, fg, _ = ui.RoundButton.COLORS["primary"]
check((fill, hover, fg.upper()) == (theme.ACCENT, theme.ACCENT_HOVER, "#FFFFFF"),
      "main button: accent fill, darker on hover, white text")
fill, _, fg, _ = ui.RoundButton.COLORS["secondary"]
check(fill.upper() == "#FFFFFF" and fg == theme.TEXT, "secondary button: white with the text colour")
src = (ROOT / "ui.py").read_text(encoding="utf-8")
check('outline = LINE if self.kind == "secondary"' in src, "secondary button: the border colour around it")

check((theme.HEADER_BG, theme.HEADER_TITLE, theme.HEADER_TEXT, theme.HEADER_LINK, theme.HEADER_LINE) ==
      (theme.CARD, theme.TEXT, theme.TEXT_2, theme.ACCENT, theme.BORDER),
      "headers: card background, title text, secondary second line, accent links, border line")
fill, hover, fg, _ = ui.RoundButton.COLORS["ghost"]
check((fill, fg) == (theme.HEADER_BG, theme.HEADER_LINK), "header links: accent on the header's background")
HEADERS = {"app.py": 2, "phone.py": 1, "ui.py": 2}          # main, Open a backup; phone; chats and photos choosers
green_head = []
for f, n in HEADERS.items():
    code = (ROOT / f).read_text(encoding="utf-8")
    made = code.count("head = ui.header(self)") + code.count("head = header(self)")
    if made != n:
        green_head.append(f"{f}: {made} of {n}")
    for k, line in enumerate(code.splitlines(), 1):
        if re.search(r"\bbg=(ui\.)?GREEN\b|theme\.ON_ACCENT_2", line):
            green_head.append(f"{f}:{k}")
check(not green_head, "every window that had the green header has the light one" +
      (f": {green_head}" if green_head else ""))

try:
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.withdraw()
    ui.setup_styles(root)
    sel = ttk.Style(root).map("Treeview", "background")
    check(any("selected" in str(state) and str(c).upper() == theme.ACCENT_PALE for *state, c in sel),
          f"the selected row in sidebars and lists is the pale accent: {sel}")
    head = ui.header(root)
    kids = head.winfo_children()
    check(head.cget("bg") == theme.HEADER_BG and len(kids) == 1 and kids[0].cget("bg") == theme.HEADER_LINE
          and int(kids[0].cget("height")) == 1 and kids[0].pack_info()["side"] == "bottom",
          "ui.header(): the header's background with a 1 px border line along its bottom")
    root.destroy()
except tk.TclError as ex:
    print(f"(style check skipped: no display: {ex})")

print("\nTHEME TESTS: " + ("PASS" if not failures else f"FAIL ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
