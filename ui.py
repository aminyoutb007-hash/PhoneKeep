"""
PhoneKeep - shared look & feel and the two pickers (chats, photos).

Built on plain tkinter so it runs everywhere Python does. Custom widgets (rounded buttons,
toggle chips) are drawn on canvases because native macOS buttons ignore custom colours.
"""
from __future__ import annotations

import datetime as dt
import queue
import sys
from pathlib import Path
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from typing import Callable, Optional

import theme

try:
    from PIL import Image, ImageTk
except Exception:  # previews need Pillow; everything else works without it
    Image = ImageTk = None

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
# The colours come from theme.py (Direction A); these are the names the windows have always used.
GREEN = theme.ACCENT
GREEN_DARK = theme.ACCENT_HOVER
SELECT_BLUE = theme.LINK          # selected photos (the system's blue)
GREEN_SOFT = theme.ACCENT_PALE
BG = theme.BG
CARD = theme.CARD
INK = theme.TEXT
MUTED = theme.TEXT_2
LINE = theme.BORDER
ME = theme.ME
RED = theme.RED
AMBER = theme.WARN_TEXT

FONT_FAMILY = None


def font(size: int = theme.BODY_SIZE, weight: str = "normal"):
    global FONT_FAMILY
    if FONT_FAMILY is None:
        try:
            FONT_FAMILY = theme.font_family(tkfont.nametofont("TkDefaultFont").actual("family"))
        except Exception:
            FONT_FAMILY = theme.font_family("Helvetica")
    if sys.platform != "darwin":
        size = max(9, size - 3)  # Windows/Linux points render larger than macOS
    return (FONT_FAMILY, size, weight)


def setup_styles(root: tk.Misc) -> None:
    st = ttk.Style(root)
    if sys.platform != "darwin":
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
    st.configure("Treeview", rowheight=28, font=font(13), background=theme.CARD, fieldbackground=theme.CARD,
                 foreground=theme.TEXT)
    st.configure("Treeview.Heading", font=font(12, "bold"))
    # the selected row in sidebars and lists: the pale accent, with the text unchanged
    st.map("Treeview", background=[("selected", theme.ACCENT_PALE)], foreground=[("selected", theme.TEXT)])
    if theme.DARK:
        dark_defaults(root, st)


def dark_defaults(root: tk.Misc, st: ttk.Style) -> None:
    """E6: the standard widgets in dark colours. On a Mac the system draws ttk's controls dark itself (the window's
    dark appearance); on Windows and Linux they're drawn by Tk, so they get PhoneKeep's colours here. Classic Tk
    widgets (text boxes, lists, spin boxes) get them on every system through the option database."""
    for pattern, value in (("*Text.background", theme.CARD), ("*Text.foreground", theme.TEXT),
                           ("*Text.insertBackground", theme.TEXT), ("*Text.selectBackground", theme.ACCENT_PALE),
                           ("*Text.selectForeground", theme.TEXT), ("*Text.highlightBackground", theme.BORDER),
                           ("*Listbox.background", theme.CARD), ("*Listbox.foreground", theme.TEXT),
                           ("*Listbox.selectBackground", theme.ACCENT_PALE), ("*Listbox.selectForeground", theme.TEXT),
                           ("*Spinbox.background", theme.CARD), ("*Spinbox.foreground", theme.TEXT),
                           ("*Spinbox.buttonBackground", theme.SECONDARY_HOVER),
                           ("*Spinbox.insertBackground", theme.TEXT), ("*Entry.background", theme.CARD),
                           ("*Entry.foreground", theme.TEXT), ("*Entry.insertBackground", theme.TEXT),
                           ("*Label.background", theme.BG), ("*Label.foreground", theme.TEXT),
                           ("*Frame.background", theme.BG), ("*Canvas.background", theme.BG),
                           ("*Checkbutton.background", theme.CARD), ("*Checkbutton.foreground", theme.TEXT),
                           ("*Checkbutton.selectColor", theme.CARD), ("*Radiobutton.background", theme.CARD),
                           ("*Radiobutton.foreground", theme.TEXT), ("*Radiobutton.selectColor", theme.CARD),
                           ("*TCombobox*Listbox.background", theme.CARD), ("*TCombobox*Listbox.foreground", theme.TEXT),
                           ("*TCombobox*Listbox.selectBackground", theme.ACCENT_PALE),
                           ("*TCombobox*Listbox.selectForeground", theme.TEXT)):
        root.option_add(pattern, value)
    if sys.platform == "darwin":
        return
    st.configure(".", background=theme.CARD, foreground=theme.TEXT, fieldbackground=theme.CARD,
                 bordercolor=theme.BORDER, lightcolor=theme.BORDER, darkcolor=theme.BORDER,
                 troughcolor=theme.BG, selectbackground=theme.ACCENT_PALE, selectforeground=theme.TEXT,
                 insertcolor=theme.TEXT, arrowcolor=theme.TEXT_2)
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(w, fieldbackground=theme.CARD, foreground=theme.TEXT, background=theme.SECONDARY_HOVER)
        st.map(w, fieldbackground=[("readonly", theme.CARD), ("disabled", theme.SECONDARY_DISABLED)],
               foreground=[("disabled", theme.TEXT_2)])
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=theme.CARD, foreground=theme.TEXT, indicatorbackground=theme.CARD,
                     indicatorforeground=theme.ACCENT)
        st.map(w, background=[("active", theme.CARD)], indicatorbackground=[("pressed", theme.SECONDARY_HOVER)])
    st.configure("TScrollbar", background=theme.SECONDARY_HOVER, troughcolor=theme.BG, arrowcolor=theme.TEXT_2)
    st.map("TScrollbar", background=[("active", theme.BORDER_HOVER)])
    st.configure("TProgressbar", background=theme.ACCENT, troughcolor=theme.BORDER)
    st.configure("Treeview.Heading", background=theme.SECONDARY_HOVER, foreground=theme.TEXT)



# where the data is and how it is protected, in one line (usability task 5, 13 Nov): the same everywhere
PROTECTED = "🔒 Encrypted with your backup password · never sent online"
PROTECTED_SHORT = "🔒 Encrypted · never sent online"     # the phone window's header, where space is short

def header(parent: tk.Misc) -> tk.Frame:
    """A window's header: light, with a 1 px line along its bottom (inside it, so a banner packed after it stays
    below the line)."""
    head = tk.Frame(parent, bg=theme.HEADER_BG)
    tk.Frame(head, bg=theme.HEADER_LINE, height=1).pack(side="bottom", fill="x")
    return head


class RoundButton(tk.Canvas):
    """A pill-shaped button: kind = primary | secondary | ghost | light."""

    COLORS = {
        "primary": (theme.ACCENT, theme.ACCENT_HOVER, theme.ON_ACCENT, theme.ACCENT_DISABLED),
        "secondary": (theme.CARD, theme.SECONDARY_HOVER, theme.TEXT, theme.SECONDARY_DISABLED),
        "ghost": (theme.HEADER_BG, theme.ACCENT_PALE, theme.HEADER_LINK, theme.HEADER_BG),   # a link in a header
        "light": (theme.ACCENT_PALE, theme.ACCENT_PALE_HOVER, theme.ACCENT_HOVER, theme.ACCENT_PALE),
    }

    def __init__(self, parent, text: str, command: Callable = None, kind: str = "primary",
                 width: int = 160, height: int = 40, size: int = 14, bg: str = None):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0,
                         bg=bg or parent.cget("bg"), cursor="hand2")
        self.text, self.command, self.kind = text, command, kind
        self.w, self.h, self.size = width, height, size
        self.enabled, self.hover = True, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", self._resize)
        self._draw()

    def _resize(self, e):
        if e.width != self.w:
            self.w = e.width
            self._draw()

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def configure_text(self, text: str):
        self.text = text
        self._draw()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _click(self, _e):
        if self.enabled and self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        fill, hover, fg, disabled = self.COLORS[self.kind]
        color = disabled if not self.enabled else (hover if self.hover else fill)
        r, w, h = self.h // 2, self.w, self.h
        outline = LINE if self.kind == "secondary" else color
        self.create_oval(1, 1, 2 * r - 1, h - 1, fill=color, outline=outline)
        self.create_oval(w - 2 * r + 1, 1, w - 1, h - 1, fill=color, outline=outline)
        self.create_rectangle(r, 1, w - r, h - 1, fill=color, outline=color)
        if self.kind == "secondary":
            self.create_line(r, 1, w - r, 1, fill=LINE)
            self.create_line(r, h - 1, w - r, h - 1, fill=LINE)
        tc = fg if self.enabled else (theme.ON_ACCENT if self.kind == "primary" else MUTED)
        self.create_text(w // 2, h // 2, text=self.text, fill=tc,
                         font=font(self.size, "bold" if self.kind == "primary" else "normal"))


ICON_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "icons"
_ICON_CACHE: dict = {}


def app_icon(key: str, small: bool = False, size: int = 0):
    """PhoneKeep's own drawn icon for an app (tools/make_app_icons.py), or None (then the emoji is shown).
    small = the 28 px version; size=48 the main screen's choice icons."""
    k = (key, small, size)
    if _ICON_CACHE.get(k) is not None:
        try:
            _ICON_CACHE[k].width()          # still belongs to a live window (a closed one invalidates it)
            ok = _ICON_CACHE[k].tk is tk._default_root.tk if tk._default_root else True
        except (tk.TclError, RuntimeError):
            ok = False
        if not ok:
            del _ICON_CACHE[k]
    if k not in _ICON_CACHE:
        img = None
        p = ICON_DIR / (f"{key}-28.png" if small else f"{key}-{size}.png" if size else f"{key}.png")
        if p.exists():
            try:
                from PIL import Image as _Image, ImageTk as _itk
                img = _itk.PhotoImage(_Image.open(p))
            except Exception:
                img = None
        _ICON_CACHE[k] = img
    return _ICON_CACHE[k]


class PhoneCard(tk.Canvas):
    """B8: one reachable iPhone in the device area, on one line: a small phone with its own wallpaper, its name,
    model and iOS, and small cable / Wi-Fi and battery marks; the chosen one has a green outline and a ✓
    (owner, 13 Nov: "can the two phones be displayed like this?"; 16 Nov: one line per phone, small pictures, so
    two phones and Back up now fit on a laptop screen)."""

    H = 60
    PW, PH = 24, 48                       # the phone drawing

    def __init__(self, parent, name: str, model: str, ios: str, how: str, command: Callable, bg: str = None):
        super().__init__(parent, height=self.H, highlightthickness=0, bd=0,
                         bg=bg or parent.cget("bg"), cursor="hand2")
        self.name, self.model, self.ios, self.how = name, model, ios, how
        self.chosen = self.hover = False
        self.wall = None
        self.battery: Optional[dict] = None
        self.bind("<ButtonRelease-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def set(self, chosen: bool):
        self.chosen = chosen
        self._draw()

    def set_wallpaper(self, path) -> None:
        """Show the phone's own wallpaper inside the small drawn phone (rounded to the screen)."""
        if not path or Image is None:
            return
        try:
            from PIL import ImageDraw, ImageOps
            sw, sh = self.PW - 4, self.PH - 4
            with Image.open(path) as src:
                im = ImageOps.fit(src.convert("RGB"), (sw, sh))
            mask = Image.new("L", (sw, sh), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), 4, fill=255)
            out = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            out.paste(im, (0, 0), mask)
            self.wall = ImageTk.PhotoImage(out)
            self._draw()
        except Exception:
            pass

    def set_battery(self, battery: Optional[dict]) -> None:
        self.battery = battery
        self._draw()

    def _rr(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(pts, smooth=True, **kw)

    # small drawn icons (the emoji looked dated): Wi-Fi arcs, a cable plug, a battery that fills to its level
    def _wifi(self, x, cy, colour):
        for k, r in enumerate((3, 7, 11)):
            if k == 0:
                self.create_oval(x + 11 - 2, cy + 4 - 2, x + 11 + 2, cy + 4 + 2, fill=colour, outline=colour)
            else:
                self.create_arc(x + 11 - r, cy + 4 - r, x + 11 + r, cy + 4 + r, start=45, extent=90,
                                style="arc", outline=colour, width=2)
        return 22

    def _plug(self, x, cy, colour):
        self.create_line(x + 5, cy - 5, x + 5, cy - 1, fill=colour, width=2)
        self.create_line(x + 11, cy - 5, x + 11, cy - 1, fill=colour, width=2)
        self._rr(x + 2, cy - 1, x + 14, cy + 5, 2, fill=colour, outline=colour)
        self.create_line(x + 8, cy + 5, x + 8, cy + 8, fill=colour, width=2)
        return 16

    def _battery(self, x, cy, level: int, charging: bool):
        w, h = 22, 11
        self._rr(x, cy - h // 2, x + w, cy + h // 2, 3, fill="", outline=MUTED, width=1)
        self.create_rectangle(x + w + 1, cy - 2, x + w + 3, cy + 2, fill=MUTED, outline=MUTED)
        colour = GREEN if charging else (RED if level <= 20 else INK)
        fw = max(1, int((w - 4) * max(0, min(100, level)) / 100))
        self.create_rectangle(x + 2, cy - h // 2 + 2, x + 2 + fw, cy + h // 2 - 2, fill=colour, outline=colour)
        if charging:
            self.create_text(x + w // 2 + 1, cy, text="⚡", fill=theme.ON_ACCENT, font=font(7, "bold"))
        return w + 4

    def _status_row(self, right, cy) -> int:
        """[Wi-Fi or cable] Wi-Fi   [battery] 100%, ending at `right`. Returns where it starts."""
        f = tkfont.Font(font=font(11))
        how = "Wi-Fi" if self.how != "cable" else "Cable"
        batt = self.battery if self.battery and self.battery.get("level", -1) >= 0 else None
        width = (22 if self.how != "cable" else 16) + 5 + f.measure(how)
        if batt:
            width += 16 + 26 + 7 + f.measure(f"{batt['level']}%")
        x = start = right - width
        x += (self._wifi(x, cy, MUTED) if self.how != "cable" else self._plug(x, cy, MUTED)) + 5
        t = self.create_text(x, cy, text=how, fill=MUTED, font=font(11), anchor="w")
        x = self.bbox(t)[2] + 16
        if batt:
            x += self._battery(x, cy, batt["level"], bool(batt.get("charging"))) + 3
            self.create_text(x, cy, text=f"{batt['level']}%", fill=MUTED, font=font(11), anchor="w")
        return start

    def _draw(self):
        self.delete("all")
        W, H, PW, PH = max(self.winfo_width(), 300), self.H, self.PW, self.PH
        if self.chosen or self.hover:
            self._rr(2, 2, W - 2, H - 2, 12, fill=GREEN_SOFT if self.chosen else theme.SUBTLE,
                     outline=GREEN if self.chosen else LINE, width=2 if self.chosen else 1)
        x0, y0 = 12, (H - PH) // 2
        self._rr(x0, y0, x0 + PW, y0 + PH, 6, fill=theme.PHONE_BODY)                         # the phone
        if self.wall is not None:
            self.create_image(x0 + PW // 2, y0 + PH // 2, image=self.wall)
        else:
            self._rr(x0 + 2, y0 + 2, x0 + PW - 2, y0 + PH - 2, 5, fill=theme.PHONE_SCREEN)
            self._rr(x0 + PW // 2 - 5, y0 + 4, x0 + PW // 2 + 5, y0 + 7, 1, fill=theme.PHONE_ISLAND)
        right = W - 12
        if self.chosen:
            self.create_oval(right - 20, H // 2 - 10, right, H // 2 + 10, fill=GREEN, outline=GREEN)
            self.create_text(right - 10, H // 2, text="✓", fill=theme.ON_ACCENT, font=font(11, "bold"))
        right -= 30
        start = self._status_row(right, H // 2)
        # name, then model and iOS on the same line, cut with "…" when the window is narrow
        x, room = x0 + PW + 14, start - 16
        name, fb = self.name, tkfont.Font(font=font(13, "bold"))
        while len(name) > 1 and x + fb.measure(name) > room:          # a long name is cut too (reviewer, #83)
            name = name[:-2] + "…"
        item = self.create_text(x, H // 2, text=name, fill=INK, font=font(13, "bold"), anchor="w")
        rest = f"  ·  {self.model}  ·  iOS {self.ios}"
        x = self.bbox(item)[2]
        f = tkfont.Font(font=font(11))
        while rest and x + f.measure(rest) > room:
            rest = rest[:-2] + "…" if len(rest) > 2 else ""
        if rest:
            self.create_text(x, H // 2, text=rest, fill=MUTED, font=font(11), anchor="w")


class PhoneTile(tk.Frame):
    """E5: one phone in the main window's "Your iPhones" list: a small picture of the phone (its saved home screen),
    its name, model and size, when it was last backed up, a green dot with cable / Wi-Fi while it's connected and
    the lock badge.
    `phone` is one of app.phone_summaries(). Click anywhere to open it."""

    PW, PH = 26, 52

    def __init__(self, parent, phone: dict, command: Callable):
        super().__init__(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        self.phone, self.pic, self.command = phone, None, command
        art = tk.Canvas(self, width=self.PW, height=self.PH, highlightthickness=0, bd=0, bg=CARD)
        art.pack(side="left", padx=(10, 8), pady=10)
        text = tk.Frame(self, bg=CARD)
        text.pack(side="left", fill="x", expand=True, pady=8, padx=(0, 8))
        self._draw_phone(art, phone.get("picture"))
        what = phone["model"]
        if phone.get("size"):
            n = phone["size"]
            what += f" · {n / 1e9:.1f} GB" if n >= 1e9 else f" · {n / 1e6:.0f} MB" if n >= 1e6 else " · under 1 MB"
        lines = [(phone["name"], INK, font(13, "bold")), (what, MUTED, font(11)),
                 (self.when(phone.get("last")), MUTED, font(11))]
        marks = []
        if phone.get("how"):
            marks.append(("● Cable" if phone["how"] == "cable" else "● Wi-Fi", GREEN))
        if phone.get("encrypted") is not None:
            marks.append(("🔒 Encrypted", GREEN) if phone["encrypted"] else ("⚠ Not encrypted", AMBER))
        self.lines = []
        for t, colour, f in lines:
            self.lines.append(tk.Label(text, text=t, bg=CARD, fg=colour, font=f, anchor="w", justify="left"))
            self.lines[-1].pack(fill="x")
        # three cards side by side are narrow: a long name or model wraps instead of being cut off
        text.bind("<Configure>", lambda e: [w.configure(wraplength=max(80, e.width - 2)) for w in self.lines[:3]], add="+")
        row = tk.Frame(text, bg=CARD)
        if marks:
            row.pack(fill="x")
        for t, colour in marks:
            self.lines.append(tk.Label(row, text=t, bg=CARD, fg=colour, font=font(11), anchor="w"))
            self.lines[-1].pack(side="left", padx=(0, 8))
        for w in [self, art, text, row] + self.lines:
            w.bind("<ButtonRelease-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self.configure(highlightbackground=theme.BORDER_HOVER))
            w.bind("<Leave>", lambda e: self.configure(highlightbackground=LINE))

    def click(self) -> None:
        """What a click does (tests: a hidden window gets no pointer events)."""
        self.command()

    @staticmethod
    def when(last: Optional[str]) -> str:
        """'Backed up 5 days ago' from the backup's date ('2026-11-10 22:00'), as the phone card says it."""
        if not last:
            return "Not backed up yet"
        import scheduler
        try:
            return "Backed up " + scheduler._ago(dt.datetime.now(), dt.datetime.strptime(last, "%Y-%m-%d %H:%M"))
        except ValueError:
            return f"Backed up {last}"

    def texts(self) -> list:
        return [w.cget("text") for w in self.lines]

    def _draw_phone(self, c: tk.Canvas, picture) -> None:
        c.create_rectangle(0, 0, self.PW, self.PH, fill=theme.PHONE_BODY, outline=theme.PHONE_BODY)
        if picture and Image is not None:
            try:
                from PIL import ImageOps
                im = ImageOps.fit(Image.open(picture).convert("RGB"), (self.PW - 4, self.PH - 4))
                self.pic = ImageTk.PhotoImage(im)
                c.create_image(2, 2, image=self.pic, anchor="nw")
                return
            except Exception:
                self.pic = None
        c.create_rectangle(2, 2, self.PW - 2, self.PH - 2, fill=theme.PHONE_SCREEN, outline=theme.PHONE_SCREEN)


class ChoiceCard(tk.Canvas):
    """One of the "What do you want to keep?" choices: a soft rounded card with PhoneKeep's drawn icon,
    a title and one line of detail; chosen = green outline, light green fill and a ✓ badge
    (owner, 13 Nov: the old boxes with emoji looked messy)."""

    H = 138

    def __init__(self, parent, icon, title: str, sub: str, command: Callable, bg: str = None):
        super().__init__(parent, height=self.H, highlightthickness=0, bd=0, bg=bg or parent.cget("bg"), cursor="hand2")
        self.icon, self.title, self.sub, self.chosen, self.hover = icon, title, sub, False, False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonRelease-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        self.hover = on
        self._draw()

    def set(self, chosen: bool):
        self.chosen = chosen
        self._draw()

    def _round(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 120), self.H
        fill = GREEN_SOFT if self.chosen else theme.CARD
        line = GREEN if self.chosen else (theme.BORDER_HOVER if self.hover else LINE)
        self._round(2, 2, w - 2, h - 2, 16, fill=fill, outline=line, width=2 if self.chosen else 1)
        if self.icon is not None:
            self.create_image(w // 2, 38, image=self.icon)
        self.create_text(w // 2, 82, text=self.title, fill=INK, font=font(14, "bold"))
        self.create_text(w // 2, 108, text=self.sub, fill=MUTED, font=font(11), width=w - 24, justify="center")
        if self.chosen:
            self.create_oval(w - 30, 10, w - 10, 30, fill=GREEN, outline=GREEN)
            self.create_text(w - 20, 20, text="✓", fill=theme.ON_ACCENT, font=font(11, "bold"))


class Chip(tk.Canvas):
    """A toggle chip: rounded, green with a tick when on, outlined when off."""

    def __init__(self, parent, text: str, variable: tk.BooleanVar, command: Callable = None,
                 size: int = 13, bg: str = None, height: int = 32):
        f = tkfont.Font(font=font(size))
        self.text, self.var, self.command, self.size = text, variable, command, size
        self.w = f.measure("✓ " + text) + 28
        self.h = height
        super().__init__(parent, width=self.w, height=self.h, highlightthickness=0, bd=0,
                         bg=bg or parent.cget("bg"), cursor="hand2")
        self.bind("<ButtonRelease-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        on = self.var.get()
        fill, fg, outline = (GREEN, theme.ON_ACCENT, GREEN) if on else (theme.CARD, INK, theme.SWITCH_OFF)
        r, w, h = self.h // 2, self.w, self.h
        self.create_oval(1, 1, 2 * r - 1, h - 1, fill=fill, outline=outline)
        self.create_oval(w - 2 * r + 1, 1, w - 1, h - 1, fill=fill, outline=outline)
        self.create_rectangle(r, 1, w - r, h - 1, fill=fill, outline=fill)
        self.create_line(r, 1, w - r, 1, fill=outline)
        self.create_line(r, h - 1, w - r, h - 1, fill=outline)
        self.create_text(w // 2, h // 2, text=("✓ " if on else "") + self.text, fill=fg, font=font(self.size))


def card(parent, **kw) -> tk.Frame:
    return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, **kw)


class BgWorker:
    """Runs small jobs (thumbnails) in one background thread and hands results to the UI thread."""

    def __init__(self, widget: tk.Misc):
        self.widget = widget
        self.jobs: queue.Queue = queue.Queue()
        self.done: queue.Queue = queue.Queue()
        self.alive = True
        threading.Thread(target=self._run, daemon=True).start()
        self._poll()

    def submit(self, fn, callback):
        self.jobs.put((fn, callback))

    def clear(self):
        try:
            while True:
                self.jobs.get_nowait()
        except queue.Empty:
            pass

    def stop(self):
        self.alive = False
        self.clear()
        self.jobs.put(None)

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None or not self.alive:
                return
            fn, cb = job
            try:
                res = fn()
            except Exception:
                res = None
            self.done.put((cb, res))

    def _poll(self):
        if not self.alive:
            return
        try:
            while True:
                cb, res = self.done.get_nowait()
                try:
                    cb(res)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        try:
            self.widget.after(60, self._poll)
        except tk.TclError:
            pass


def draw_cloud(c: tk.Canvas, x: int, y: int) -> None:
    """A small drawn iCloud badge (a dark disc with a white cloud), centred on (x, y)."""
    c.create_oval(x - 13, y - 11, x + 13, y + 11, fill=theme.BADGE_GREY, outline="")
    c.create_oval(x - 9, y - 1, x - 1, y + 6, fill=theme.ON_DARK, outline="")
    c.create_oval(x - 5, y - 6, x + 5, y + 4, fill=theme.ON_DARK, outline="")
    c.create_oval(x + 1, y - 3, x + 9, y + 6, fill=theme.ON_DARK, outline="")
    c.create_rectangle(x - 5, y + 1, x + 5, y + 6, fill=theme.ON_DARK, outline="")


def load_photo(path, max_px: int, square: bool = False, faded: bool = False) -> Optional["ImageTk.PhotoImage"]:
    """faded: washed out towards white (a photo whose full version is only in iCloud)."""
    if not path or Image is None:
        return None
    try:
        from PIL import ImageOps
        im = Image.open(path)
        if square:
            im = ImageOps.fit(im.convert("RGB"), (max_px, max_px))
        else:
            im.thumbnail((max_px, max_px))
        if faded:
            im = Image.blend(im.convert("RGB"), Image.new("RGB", im.size, (255, 255, 255)), 0.55)
        return ImageTk.PhotoImage(im)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Chat picker with preview
# ---------------------------------------------------------------------------
MEDIA_TYPES = {"image", "sticker", "gif", "video", "audio", "document"}     # M6: what a chat's Media tab has
TYPE_LABEL = {"image": "📷 Photo", "video": "🎬 Video", "audio": "🎤 Voice note", "document": "📄 Document",
              "sticker": "Sticker", "gif": "GIF", "location": "📍 Location", "contact": "👤 Contact",
              "deleted": "🚫 Deleted message", "system": "Group update", "link": "🔗 Link"}


DATE_PRESETS = ["All dates", "Today", "Last 7 days", "Last 30 days", "Last 3 months",
                "Last 12 months", "This year", "Last year", "Custom dates"]


def preset_range(name: str, today: Optional[dt.date] = None):
    """(from, to) dates for a preset name; (None, None) for all dates."""
    t = today or dt.date.today()
    days = {"Today": 0, "Last 7 days": 6, "Last 30 days": 29, "Last 3 months": 91, "Last 12 months": 364}
    if name in days:
        return t - dt.timedelta(days=days[name]), t
    if name == "This year":
        return dt.date(t.year, 1, 1), t
    if name == "Last year":
        return dt.date(t.year - 1, 1, 1), dt.date(t.year - 1, 12, 31)
    return None, None


def parse_day(text: str) -> Optional[dt.date]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def count_in_range(days: list, lo: Optional[dt.date], hi: Optional[dt.date]) -> int:
    """days: sorted 'YYYY-MM-DD' strings."""
    import bisect
    a = bisect.bisect_left(days, lo.isoformat()) if lo else 0
    b = bisect.bisect_right(days, hi.isoformat()) if hi else len(days)
    return max(0, b - a)


class ChatPanel(tk.Frame):
    """Chats from WhatsApp, WhatsApp Business and/or Messages: search, dates, tick boxes and a
    conversation preview. Used by the export picker and by the phone window."""

    def __init__(self, parent, lists: dict, preview=None, select_all: bool = True, preview_limit: int = 80):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        self.preview = preview
        self.preview_limit = preview_limit
        self.rows = [(k, label, c) for k, (label, chats) in lists.items() for c in chats]
        self.selected = {(k, c["id"]) for k, _l, c in self.rows} if select_all else set()
        self.apps = [label for _k, (label, _c) in lists.items()]
        self.images = []
        self.worker = BgWorker(self)
        self.bind("<Destroy>", lambda e: self.worker.stop() if e.widget is self else None)
        self.current = None
        self.lo = self.hi = None   # date range (None = open)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(bar, text="🔍", bg=BG, font=font(14)).pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._fill())
        ent = ttk.Entry(bar, textvariable=self.q, width=28)
        ent.pack(side="left", padx=(4, 10))
        self.search_hint = tk.Label(bar, text="", bg=BG, fg=MUTED, font=font(11))
        self.app_var = tk.StringVar(value="All apps")
        if len(self.apps) > 1:
            cb = ttk.Combobox(bar, textvariable=self.app_var, values=["All apps"] + self.apps,
                              state="readonly", width=18)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        self.search_hint.pack(side="left", padx=(10, 0))

        dbar = tk.Frame(self, bg=BG)
        dbar.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(dbar, text="📅  Messages from", bg=BG, fg=INK, font=font(13)).pack(side="left")
        self.preset = tk.StringVar(value="All dates")
        pc = ttk.Combobox(dbar, textvariable=self.preset, values=DATE_PRESETS, state="readonly", width=15)
        pc.pack(side="left", padx=(8, 12))
        pc.bind("<<ComboboxSelected>>", lambda e: self._preset())
        tk.Label(dbar, text="From", bg=BG, fg=MUTED, font=font(12)).pack(side="left")
        self.d_from = tk.StringVar()
        self.d_to = tk.StringVar()
        e1 = ttk.Entry(dbar, textvariable=self.d_from, width=11)
        e1.pack(side="left", padx=(4, 8))
        tk.Label(dbar, text="to", bg=BG, fg=MUTED, font=font(12)).pack(side="left")
        e2 = ttk.Entry(dbar, textvariable=self.d_to, width=11)
        e2.pack(side="left", padx=(4, 8))
        for e in (e1, e2):
            e.bind("<Return>", lambda ev: self._typed_dates())
            e.bind("<FocusOut>", lambda ev: self._typed_dates())
        self.date_hint = tk.Label(dbar, text="e.g. 2024-01-31", bg=BG, fg=MUTED,
                                  font=font(11))
        self.date_hint.pack(side="left", padx=6)
        self.hide_empty = tk.BooleanVar(value=True)
        ttk.Checkbutton(dbar, text="Hide empty", variable=self.hide_empty,
                        command=self._fill).pack(side="right")

        body = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bg=BG, bd=0)
        body.pack(fill="both", expand=True, padx=16)
        left = tk.Frame(body, bg=BG)
        # ticking controls sit right above the list they act on (owner, 13 Nov)
        tbar = tk.Frame(left, bg=BG)
        tbar.pack(side="top", fill="x", pady=(0, 6))
        RoundButton(tbar, "Select all", lambda: self._set_all(True), "secondary", 110, 30, 12, bg=BG).pack(side="left")
        RoundButton(tbar, "Select none", lambda: self._set_all(False), "secondary", 120, 30, 12, bg=BG).pack(side="left", padx=6)
        self.tick_count = tk.Label(tbar, text="", bg=BG, fg=MUTED, font=font(12))
        self.tick_count.pack(side="left", padx=(8, 0))
        cols = ("tick", "name") + (("app",) if len(self.apps) > 1 else ()) + ("messages", "last")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        heads = {"tick": ("✓", 36), "name": ("Chat", 230), "app": ("App", 130),
                 "messages": ("Messages", 80), "last": ("Last", 92)}
        for c in cols:
            self.tree.heading(c, text=heads[c][0])
            self.tree.column(c, width=heads[c][1], stretch=(c == "name"),
                             anchor="center" if c in ("tick", "messages") else "w")
        self.tree.heading("tick", command=lambda: self._set_all(not self._all_shown_ticked()))   # ✓ ticks/unticks all shown
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<ButtonRelease-1>", self._click)
        self.tree.bind("<space>", lambda e: (self._toggle(self.tree.focus()), "break")[1])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show(self.tree.focus()))
        body.add(left, minsize=420, width=560)

        right = card(body)
        head = tk.Frame(right, bg=CARD)
        head.pack(fill="x", padx=14, pady=(10, 0))
        self.pv_title = tk.Label(head, text="Preview", bg=CARD, fg=INK, font=font(15, "bold"), anchor="w")
        self.pv_title.pack(side="left", fill="x", expand=True)
        # M5: in a group chat, see (and save) only some people's messages
        self.people = {}                   # (app key, chat id) -> names whose messages are shown and saved
        self.people_win = self.people_tree = None
        self.shown_chat = None
        self.people_btn = RoundButton(head, "People", self.open_people, "secondary", 120, 30, 12, bg=CARD)
        self.pv_sub = tk.Label(right, text="Click a chat on the left to see its latest messages.",
                               bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.pv_sub.pack(fill="x", padx=14, pady=(0, 6))
        # M6: the chat's messages, or all its photos, videos, voice notes and documents
        self.tab = "messages"
        self.tabs = tk.Frame(right, bg=CARD)
        self.tab_btns = {}
        for name, label in (("messages", "Messages"), ("media", "Media")):
            b = RoundButton(self.tabs, label, lambda n=name: self.show_tab(n),
                            "primary" if name == "messages" else "secondary", 104, 28, 12, bg=CARD)
            b.pack(side="left", padx=(0, 6))
            self.tab_btns[name] = b
        self.save_media_btn = RoundButton(self.tabs, "Save all", self.save_all_media, "secondary", 100, 28, 12, bg=CARD)
        if preview is not None and hasattr(preview, "media"):
            self.tabs.pack(fill="x", padx=14, pady=(0, 6))
        self.pv_body = tk.Frame(right, bg=theme.CHAT_BG)
        self.pv_body.pack(fill="both", expand=True)
        self.media_grid = None
        self.saving = None                  # Save all running: its stop flag
        tf = self.text_frame = tk.Frame(self.pv_body, bg=theme.CHAT_BG)
        tf.pack(fill="both", expand=True)
        # fg must be set: in macOS dark mode Tk's default text colour is white, which vanished on the light
        # bubbles (owner, 12 Nov: "all messages look empty")
        self.text = tk.Text(tf, bg=theme.CHAT_BG, fg=INK, insertbackground=INK, selectforeground=INK,
                            relief="flat", wrap="word", font=font(13), padx=10, pady=8,
                            cursor="arrow", highlightthickness=0)
        tsb = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=tsb.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.text.tag_configure("them", foreground=INK, lmargin1=6, lmargin2=6, rmargin=70, background=theme.CARD,
                                spacing1=6, spacing3=2)
        self.text.tag_configure("me", foreground=INK, lmargin1=70, lmargin2=70, rmargin=6, background=ME,
                                spacing1=6, spacing3=2)
        self.text.tag_configure("sender", foreground=GREEN, font=font(11, "bold"))
        self.text.tag_configure("meta", foreground=MUTED, font=font(10))
        self.text.tag_configure("day", justify="center", foreground=MUTED, font=font(11, "bold"),
                                spacing1=12, spacing3=4)
        self.text.tag_configure("sys", justify="center", foreground=AMBER, font=font(11), spacing1=6)
        self.text.tag_configure("hit", background=theme.HIT, foreground=INK)
        self.text.tag_configure("link", foreground=GREEN, font=font(13, "bold"))
        self.text.tag_raise("hit")
        body.add(right, minsize=300)

        self.foot = tk.Frame(self, bg=BG)
        self.foot.pack(side="bottom", fill="x", padx=16, pady=12, before=body)
        self.count = tk.Label(self.foot, bg=BG, fg=INK, font=font(13))
        self.count.pack(side="left")
        self._fill()
        ent.focus_set()
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.focus(kids[0])

    # list ---------------------------------------------------------------
    def _fill(self):
        import search
        q = search.fold(self.q.get()).strip()
        self.at_for = None                  # E4: other words: no longer the one message a search result chose
        app = self.app_var.get()
        self.tree.delete(*self.tree.get_children())
        # the search finds chats by name AND by what was said in them (usability test, 12 Nov:
        # "find a message containing 'merci'" found nothing)
        self.hits = {}
        if q and self.preview is not None and len(q) >= 2:
            for key in {k for k, _l, _c in self.rows}:
                for cid, n in self.preview.matching(key, q).items():
                    self.hits[(key, cid)] = n
        n_hit_chats = 0
        for i, (key, label, c) in enumerate(self.rows):
            if q and q not in search.fold(c["name"]) and (key, c["id"]) not in self.hits:
                continue
            if (key, c["id"]) in self.hits:
                n_hit_chats += 1
            if app != "All apps" and label != app:
                continue
            n_in = self._n_in(c, key)
            if n_in == 0 and self.hide_empty.get() and (self.lo or self.hi):
                continue
            vals = ("☑" if (key, c["id"]) in self.selected else "☐", self._name_cell(key, c))
            if len(self.apps) > 1:
                vals += (label,)
            vals += (f"{n_in:,}", c["last"])
            self.tree.insert("", "end", iid=str(i), values=vals, tags=("dim",) if n_in == 0 else ())
        self.tree.tag_configure("dim", foreground=MUTED)
        if hasattr(self, "search_hint"):
            total = sum(self.hits.values())
            self.search_hint.configure(text=(f"“{self.q.get().strip()}” is in {total:,} message{'s' if total != 1 else ''} "
                                             f"across {n_hit_chats:,} chat{'s' if n_hit_chats != 1 else ''}") if q and total
                                       else (f"No message contains “{self.q.get().strip()}”" if q and len(q) >= 2 and not
                                             any(q in search.fold(c['name']) for _k, _l, c in self.rows) else ""))
        self.current = None
        self._update_count()

    def _toggle(self, iid):
        if not iid:
            return
        key, _label, c = self.rows[int(iid)]
        k = (key, c["id"])
        self.selected.symmetric_difference_update({k})
        self.tree.set(iid, "tick", "☑" if k in self.selected else "☐")
        self._update_count()

    def _click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if self.tree.identify_column(event.x) == "#1":  # the tick column
            self._toggle(iid)

    def _all_shown_ticked(self) -> bool:
        kids = self.tree.get_children()
        return bool(kids) and all((self.rows[int(i)][0], self.rows[int(i)][2]["id"]) in self.selected for i in kids)

    def _set_all(self, on: bool):
        for iid in self.tree.get_children():
            key, _l, c = self.rows[int(iid)]
            (self.selected.add if on else self.selected.discard)((key, c["id"]))
        self._fill()

    def _n_in(self, c, key: Optional[str] = None) -> int:
        names = self.people.get((key, c["id"])) if key else None
        if names:                          # M5: only these people's messages
            ps = [p for p in self._people_of(key, c) if p["name"] in names]
            if not (self.lo or self.hi):
                return sum(p["count"] for p in ps)
            return sum(count_in_range(p["days"], self.lo, self.hi) for p in ps)
        if not (self.lo or self.hi):
            return c["messages"]
        days = c.get("days")
        if days is None:
            return c["messages"]
        return count_in_range(days, self.lo, self.hi)

    def _update_count(self):
        sel = [(k, c) for k, _l, c in self.rows if (k, c["id"]) in self.selected]
        msgs = sum(self._n_in(c, k) for k, c in sel)
        text = f"{len(sel):,} of {len(self.rows):,} chats ticked · {msgs:,} messages"
        if self.lo or self.hi:
            f = lambda d: d.strftime("%d %b %Y")
            when = (f"{f(self.lo)} – {f(self.hi)}" if self.lo and self.hi else
                    f"from {f(self.lo)}" if self.lo else f"up to {f(self.hi)}")
            with_msgs = sum(1 for k, c in sel if self._n_in(c, k) > 0)
            text += f" in {with_msgs:,} chat{'s' if with_msgs != 1 else ''} · {when}"
        self.count.configure(text=text)
        shown = len(self.tree.get_children())
        ticked = sum(1 for i in self.tree.get_children() if (self.rows[int(i)][0], self.rows[int(i)][2]["id"]) in self.selected)
        self.tick_count.configure(text=f"{ticked:,} of {shown:,} shown are ticked")

    # dates --------------------------------------------------------------
    def _preset(self):
        name = self.preset.get()
        if name == "Custom dates":
            self.date_hint.configure(text="Type the dates, then press Return", fg=GREEN)
            return
        lo, hi = preset_range(name)
        self.d_from.set(lo.isoformat() if lo else "")
        self.d_to.set(hi.isoformat() if hi else "")
        self._apply_dates(lo, hi)

    def _typed_dates(self):
        try:
            lo, hi = parse_day(self.d_from.get()), parse_day(self.d_to.get())
        except ValueError as e:
            self.date_hint.configure(text=f"“{e}” isn't a date. Use 2024-01-31.", fg=RED)
            return
        if lo and hi and lo > hi:
            self.date_hint.configure(text="The ‘from’ date is after the ‘to’ date.", fg=RED)
            return
        if (lo, hi) != (self.lo, self.hi):
            self.preset.set("Custom dates" if (lo or hi) else "All dates")
        self._apply_dates(lo, hi)

    def _apply_dates(self, lo, hi):
        self.lo, self.hi = lo, hi
        self.date_hint.configure(text="Only these dates are saved" if (lo or hi)
                                 else "e.g. 2024-01-31", fg=MUTED)
        self._fill()

    # preview ------------------------------------------------------------
    def show_chat(self, key: str, chat_id, at: Optional[str] = None) -> None:
        """E4: choose that chat and show its messages from the one sent `at` (a search result)."""
        iid = next((str(i) for i, (k, _l, c) in enumerate(self.rows) if k == key and c["id"] == chat_id), None)
        if iid is None or not self.tree.exists(iid):
            return
        if self.tab != "messages":              # a search result is a message: show the conversation
            self.text_chat = self.shown_chat    # (drawn just below, at the result)
            self.show_tab("messages")
        self.at_for, self.at_time = (key, chat_id), at
        self.current = None
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)
        self._show(iid)

    def _show(self, iid):
        if not iid or self.preview is None:
            return
        key, label, c = self.rows[int(iid)]
        if self.current == (key, c["id"]):
            return
        self.current = (key, c["id"])
        self.worker.clear()
        q = self.q.get().strip()
        around = q if (key, c["id"]) in getattr(self, "hits", {}) else None
        at = self.at_time if getattr(self, "at_for", None) == (key, c["id"]) else None
        names = self.people.get((key, c["id"]))
        if names:
            msgs, total = self.preview.messages(key, c["id"], self.preview_limit, around=around, at=at, people=names)
        else:
            msgs, total = self.preview.messages(key, c["id"], self.preview_limit, around=around, at=at)
        if self.shown_chat != (key, c["id"]) and self.people_win is not None and self.people_win.winfo_exists():
            self.people_win.destroy()           # its list belongs to the chat shown before
        self.shown_chat = (key, c["id"])
        self.pv_title.configure(text=c["name"])
        shown = f"latest {len(msgs)} of {total:,} messages" if total > len(msgs) else f"{total:,} messages"
        self.pv_sub.configure(text=f"{label} · {shown}" + (" · group" if c["group"] else "")
                              + (f" · only {self._who(names)}" if names else ""))
        if c["group"] and hasattr(self.preview, "people"):
            self.people_btn.configure_text(f"People · {len(names)}" if names else "People")
            self.people_btn.pack(side="right")
        else:
            self.people_btn.pack_forget()
        if self.tab == "media":
            self._show_media()
            self.text_chat = None           # the conversation is drawn when its tab is shown again
            return
        self.text_chat = self.current
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        old = [n for n in t.tag_names() if n.startswith("open")]
        if old:
            t.tag_delete(*old)                  # the chat shown before's attachments (and their clicks)
        self.images.clear()
        import search
        last_day, first = None, None
        for i, m in enumerate(msgs):
            when = dt.datetime.fromisoformat(m["time"]) if m.get("time") else None
            day = when.strftime("%A %d %B %Y") if when else ""
            if day != last_day:
                t.insert("end", day + "\n", "day")
                last_day = day
            if m.get("type") == "system":
                t.insert("end", (m.get("text") or "Group update") + "\n", "sys")
                continue
            tag = "me" if m.get("from_me") else "them"
            if c["group"] and not m.get("from_me"):
                t.insert("end", (m.get("sender") or "") + "\n", (tag, "sender"))
            # M6: a click on a photo, video, voice note or document opens it large
            otag = f"open{i}" if m.get("type") in MEDIA_TYPES and hasattr(self.preview, "media") else None
            if otag:
                t.tag_bind(otag, "<ButtonRelease-1>", lambda e, m=m, k=key, cid=c["id"]: self.open_media(k, cid, m))
                t.tag_bind(otag, "<Enter>", lambda e: t.configure(cursor="hand2"))
                t.tag_bind(otag, "<Leave>", lambda e: t.configure(cursor="arrow"))
            open_tags = (otag,) if otag else ()
            if m.get("type") in ("image", "sticker", "gif"):
                mark = f"img{i}"
                t.mark_set(mark, "end-1c")
                t.mark_gravity(mark, "left")
                t.insert("end", "📷 Photo", (tag, mark + "ph") + open_tags)
                t.insert("end", "\n", tag)
                self.worker.submit(lambda m=m: self.preview.thumbnail(key, m),
                                   lambda path, mark=mark, cur=self.current, ot=otag: self._put_image(path, mark, cur, ot))
            elif otag:
                t.insert("end", TYPE_LABEL[m["type"]], (tag, "link", otag))
                t.insert("end", "\n", tag)
            body = m.get("text") or ""
            if m.get("caption") and m.get("type") not in ("image",):
                body = (body + "\n" + m["caption"]).strip()
            if not body and m.get("type") not in ("image", "sticker", "gif") and not otag:
                body = TYPE_LABEL.get(m.get("type"), m.get("type", ""))
            if body:
                # the searched words marked as the text goes in, matched the way the search matches (accents,
                # Arabic marks); not Tk's own -nocase search, which crashed Tk on Linux with such text (#80)
                done = 0
                for a, b in (search.find_spans(body, around) if around else []):
                    t.insert("end", body[done:a], tag)
                    first = first or t.index("end-1c")
                    t.insert("end", body[a:b], (tag, "hit"))
                    done = b
                t.insert("end", body[done:] + "\n", tag)
            t.insert("end", (when.strftime("%H:%M") if when else "") + "\n", (tag, "meta"))
        if not msgs:
            t.insert("end", "No messages to show.\n", "day")
        t.configure(state="disabled")
        t.see(first or "end")

    def _put_image(self, path, mark, cur, otag=None):
        if cur != self.current or not path:
            return
        img = load_photo(path, 220)
        if img is None:
            return
        self.images.append(img)
        t = self.text
        t.configure(state="normal")
        try:
            rng = t.tag_ranges(mark + "ph")
            if rng:
                t.delete(rng[0], rng[1])
            t.image_create(mark, image=img, padx=4, pady=4)
            if otag:                         # M6: the photo itself opens it large
                t.tag_add(otag, mark, f"{mark} +1c")
        except tk.TclError:
            pass
        t.configure(state="disabled")
        t.see("end")

    # media (M6) ---------------------------------------------------------
    def show_tab(self, name: str) -> None:
        """Messages: the conversation. Media: every photo, video, voice note and document in it, with Save all."""
        self.tab = name
        for n, b in self.tab_btns.items():
            b.kind = "primary" if n == name else "secondary"
            b._draw()
        if name == "media":
            self.text_frame.pack_forget()
            if self.media_grid is None:
                self.media_grid = MediaGrid(self.pv_body, self.preview, self.open_media_list)
            self.media_grid.pack(fill="both", expand=True)
            self.save_media_btn.pack(side="right")
            self._show_media()
        else:
            if self.media_grid is not None:
                self.media_grid.pack_forget()
            self.save_media_btn.pack_forget()
            self.text_frame.pack(fill="both", expand=True)
            if self.shown_chat is not None and getattr(self, "text_chat", None) != self.shown_chat:
                iid, _c = self._row_of(*self.shown_chat)
                self.current = None
                self._show(iid)

    def _show_media(self):
        if self.media_grid is None or self.shown_chat is None:
            return
        key, cid = self.shown_chat
        self.media_grid.show(key, cid, self.people.get((key, cid)))
        self.save_media_btn.set_enabled(bool(self.media_grid.all) and self.saving is None)

    def _viewer_items(self, key: str, media: list) -> list:
        import quicklook
        pv = self.preview
        out = []
        for m in media:
            here = pv.media_source(key, m) is not None
            out.append(quicklook.Item(
                pv.media_name(key, m), kind="" if here else "image",      # not in the backup: say so, don't offer Play
                read=lambda m=m: pv.read_media(key, m),
                to_file=(lambda dest, m=m: pv.copy_media(key, m, dest)) if here else None,
                why=None if here else (lambda: "It isn't in the backup: the iPhone never had it, or left it out.")))
        return out

    def open_media_list(self, key: str, media: list, index: int) -> None:
        """Show one attachment large; the arrow keys go through the others in `media`."""
        import quicklook
        if media:
            self.media_viewer = quicklook.Viewer(self, self._viewer_items(key, media), index)

    def open_media(self, key: str, cid, m: dict) -> None:
        """A click on an attachment in the conversation: it opens large, and the arrows go through the chat's
        other attachments, oldest to newest as in the conversation."""
        media = self.preview.media(key, cid, self.people.get((key, cid)))
        index = next((n for n, x in enumerate(media) if x is m), None)
        if index is None:
            index = next((n for n, x in enumerate(media) if x.get("id") == m.get("id")), 0)
        self.open_media_list(key, media, index)

    def save_all_media(self) -> None:
        """Save all (M6): the shown chat's attachments into a new folder, each dated when it was sent."""
        if self.shown_chat is None or self.saving is not None:
            return
        key, cid = self.shown_chat
        _iid, c = self._row_of(key, cid)
        names = self.people.get((key, cid))
        media = self.preview.media(key, cid, names)
        if c is None or not media:
            return
        where = ask_folder(self, f"Where should the media from {c['name']} go?")
        if not where:
            return
        import re
        base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", f"{c['name']} media").strip(" .")[:80] or "Chat media"
        folder, k = Path(where) / base, 2
        while folder.exists():
            folder, k = Path(where) / f"{base} ({k})", k + 1
        stop = threading.Event()
        self.saving = stop
        self.save_media_btn.set_enabled(False)
        news: queue.Queue = queue.Queue()

        def run():
            try:
                res = self.preview.save_media(key, cid, folder, names, progress=lambda n, of: news.put(("at", (n, of))),
                                              stop=stop.is_set)
                news.put(("done", res))
            except Exception as e:  # noqa: BLE001 - shown under the grid
                news.put(("error", e))

        def poll():
            try:
                while True:
                    what, value = news.get_nowait()
                    if what == "at":
                        self._media_note(f"Saving {value[0]:,} of {value[1]:,}…")
                    else:
                        self.saving = None
                        self.save_media_btn.set_enabled(True)
                        self.saved_media = value
                        import phone
                        self._media_note(self._saved_text(value) if what == "done" else
                                         f"Couldn't save them: {phone.describe_error(value)}")
                        if what == "done" and value["saved"] and self.media_grid is not None:
                            self.media_grid.offer_folder(value["folder"])     # "Show folder", as other saves have
                        return
            except queue.Empty:
                pass
            try:
                self.after(100, poll)
            except tk.TclError:
                stop.set()
        self.bind("<Destroy>", lambda e: stop.set() if e.widget is self else None, add="+")
        threading.Thread(target=run, daemon=True).start()
        self._media_note("Saving…")
        poll()

    @staticmethod
    def _saved_text(res: dict) -> str:
        n, missing, failed = res["saved"], res["missing"], res["failed"]
        text = f"Saved {n:,} file{'s' if n != 1 else ''} to “{res['folder'].name}”, each dated when it was sent."
        if missing:
            text += f" {missing:,} {'weren’t' if missing != 1 else 'wasn’t'} in the backup."
        if failed:
            text += f" {failed:,} couldn't be copied."
        return text

    def _media_note(self, text: str) -> None:
        if self.media_grid is not None:
            self.media_grid.note.configure(text=text)

    # people in a group chat (M5) ---------------------------------------
    def _people_of(self, key, c) -> list:
        if self.preview is None or not hasattr(self.preview, "people"):
            return []
        return self.preview.people(key, c["id"])

    @staticmethod
    def _who(names) -> str:
        names = sorted(names, key=str.casefold)
        return names[0] if len(names) == 1 else f"{len(names)} people"

    def _name_cell(self, key, c) -> str:
        names = self.people.get((key, c["id"]))
        return ("👥 " if c["group"] else "") + c["name"] + (f"  · only {self._who(names)}" if names else "")

    def _row_of(self, key, cid):
        return next(((str(i), c) for i, (k, _l, c) in enumerate(self.rows) if k == key and c["id"] == cid), (None, None))

    def set_people(self, key: str, cid, names) -> None:
        """Show and save only these people's messages in this chat (no one ticked = the whole chat)."""
        iid, c = self._row_of(key, cid)
        if c is None:
            return
        names = set(names or ())
        if not names:
            self.people.pop((key, cid), None)
        else:
            self.people[(key, cid)] = names
        if self.tree.exists(iid):
            self.tree.set(iid, "name", self._name_cell(key, c))
            self.tree.set(iid, "messages", f"{self._n_in(c, key):,}")
        self._update_count()
        if self.shown_chat == (key, cid):
            self.current = None
            self._show(iid)
        if self.people_tree is not None and self.people_tree.winfo_exists():
            chosen = self.people.get((key, cid), set())
            for p_iid in self.people_tree.get_children():
                self.people_tree.set(p_iid, "tick", "☑" if self.people_tree.item(p_iid, "text") in chosen else "☐")

    def open_people(self) -> None:
        """M5: the shown group chat's participants with their message counts; tick one or more to see only
        their messages. Save, Print and the exports use the same choice."""
        if self.shown_chat is None:
            return
        key, cid = self.shown_chat
        iid, c = self._row_of(key, cid)
        if c is None or not c["group"]:
            return
        if self.people_win is not None and self.people_win.winfo_exists():
            self.people_win.destroy()
        w = self.people_win = PeopleWindow(self, f"People in {c['name']}")
        tk.Label(w, text=f"People in {c['name']}", bg=BG, fg=INK, font=font(15, "bold"),
                 anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(w, text="Tick one or more people to see only their messages. Saving this chat keeps the same choice.",
                 bg=BG, fg=MUTED, font=font(11), anchor="w", justify="left", wraplength=380).pack(fill="x", padx=16, pady=(0, 8))
        people = self._people_of(key, c)
        frm = tk.Frame(w, bg=BG)
        frm.pack(fill="both", expand=True, padx=16)
        tree = self.people_tree = ttk.Treeview(frm, columns=("tick", "name", "messages"), show="headings",
                                               selectmode="browse", height=min(12, max(3, len(people))))
        for col, title, width in (("tick", "✓", 36), ("name", "Person", 240), ("messages", "Messages", 90)):
            tree.heading(col, text=title)
            tree.column(col, width=width, stretch=(col == "name"), anchor="w" if col == "name" else "center")
        sb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        chosen = self.people.get((key, cid), set())
        for i, p in enumerate(people):
            tree.insert("", "end", iid=f"p{i}", text=p["name"],
                        values=("☑" if p["name"] in chosen else "☐", p["name"], f"{p['count']:,}"))

        def flip(p_iid):
            if not p_iid:
                return
            names = set(self.people.get((key, cid), ()))
            names.symmetric_difference_update({tree.item(p_iid, "text")})
            self.set_people(key, cid, names)
        tree.bind("<ButtonRelease-1>", lambda e: flip(tree.identify_row(e.y))
                  if tree.identify_region(e.x, e.y) == "cell" else None)
        tree.bind("<space>", lambda e: (flip(tree.focus()), "break")[1])
        bar = tk.Frame(w, bg=BG)
        bar.pack(fill="x", padx=16, pady=12)
        RoundButton(bar, "Done", w.destroy, "primary", 90, 34, 12, bg=BG).pack(side="right")
        RoundButton(bar, "Everyone", lambda: self.set_people(key, cid, set()), "secondary", 110, 34, 12,
                    bg=BG).pack(side="right", padx=6)
        w.bind("<Escape>", lambda e: w.destroy())
        tree.focus_set()

    # result -------------------------------------------------------------
    def selection(self, confirm_empty: bool = True):
        """{app key: set(chat ids)} plus "_dates": (from, to) when a range is set and "_people": {app key: {chat id:
        names}} for ticked group chats shown for only some people (M5); None if not ready."""
        out = {key: set() for key, _l, _c in self.rows}
        for key, cid in self.selected:
            out[key].add(cid)
        people = {}
        for (key, cid), names in self.people.items():     # M5: ticked chats keep their people choice
            if (key, cid) in self.selected:
                people.setdefault(key, {})[cid] = set(names)
        if confirm_empty and not self.selected and not messagebox.askyesno(
                "PhoneKeep", "No chats are ticked, so no chats will be exported. Continue?", parent=self):
            return None
        self._typed_dates()
        if self.date_hint.cget("fg") == RED:
            return None
        if self.lo or self.hi:
            out["_dates"] = (self.lo, self.hi)
            for key, _l, c in self.rows:   # ticked chats with nothing in these dates are left out
                if self._n_in(c, key) == 0:
                    out[key].discard(c["id"])
            if self.selected and not any(out[k] for k in out if not k.startswith("_")):
                if not messagebox.askyesno("PhoneKeep", "The ticked chats have no messages in these dates, "
                                           "so nothing will be exported from them. Continue?", parent=self):
                    return None
        if people:
            out["_people"] = people
        return out


def ask_folder(parent, title: str):
    """The folder dialog for Save all (one place, so the tests can stand in for it)."""
    from tkinter import filedialog
    return filedialog.askdirectory(parent=parent, title=title, initialdir=str(Path.home()), mustexist=True)


class MediaGrid(tk.Frame):
    """M6: a chat's photos, videos, voice notes and documents as tiles, newest first, with a choice of which kind.
    As in the photo grid (E7), only the rows on screen have tiles, so a chat with thousands of attachments scrolls
    like one with ten, and only the thumbnails on screen are made. A click shows one large; the arrows then go
    through the others shown."""

    TILE, GAP = 116, 6
    KEEP_IMAGES = 600
    ICON = {"photo": "🖼", "video": "🎬", "audio": "🎤", "document": "📄"}
    KINDS = (("all", "All media"), ("photo", "Photos"), ("video", "Videos"), ("audio", "Voice notes and audio"),
             ("document", "Documents"))

    def __init__(self, parent, preview, on_open: Callable):
        super().__init__(parent, bg=CARD)
        from sections import MEDIA_KIND
        self.kind_of = lambda m: MEDIA_KIND[m["type"]]
        self.preview, self.on_open = preview, on_open
        self.key = self.chat = None
        self.all: list = []                  # every attachment of the chat, newest first
        self.items: list = []                # those of the kind chosen
        self.here: dict = {}                 # message id -> its file is in the backup
        self.paths: dict = {}
        self.images: dict = {}
        self.tiles: dict = {}
        self.pool: list = []
        self.worker = BgWorker(self)
        self.bind("<Destroy>", lambda e: self.worker.stop() if e.widget is self else None)
        bar = tk.Frame(self, bg=CARD)
        bar.pack(fill="x", padx=10, pady=(0, 6))
        self.kind = tk.StringVar(value=self.KINDS[0][1])
        box = ttk.Combobox(bar, textvariable=self.kind, values=[label for _k, label in self.KINDS], state="readonly",
                           width=20)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self._filter())
        self.summary = tk.Label(bar, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.summary.pack(side="left", padx=10)
        foot = tk.Frame(self, bg=CARD)
        foot.pack(side="bottom", fill="x", padx=10, pady=(4, 6))
        self.show_btn = RoundButton(foot, "Show folder", lambda: None, "secondary", 120, 28, 12, bg=CARD)
        self.note = tk.Label(foot, text="", bg=CARD, fg=INK, font=font(11), anchor="w", justify="left", wraplength=300)
        self.note.pack(side="left", fill="x", expand=True)
        foot.bind("<Configure>", lambda e: self.note.configure(wraplength=max(160, e.width - 140)))
        frame = tk.Frame(self, bg=CARD)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, bg=CARD, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)

        def scrolled(first, last):
            sb.set(first, last)
            if not self._relayout_due:          # once per redraw, however many scroll events came
                self._relayout_due = True
                self.after_idle(self._relayout)
        self._relayout_due = False
        self._laid_out = self._region = None
        self.canvas.configure(yscrollcommand=scrolled)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self._relayout())
        wheel_scroll(self.canvas)

    def show(self, key: str, chat_id, people=None) -> None:
        """The chat's attachments (only those people's, M5)."""
        media = self.preview.media(key, chat_id, people)
        self.key, self.chat = key, chat_id
        self.all = media[::-1]
        self.here = {m["id"]: self.preview.media_source(key, m) is not None for m in media}
        self.paths, self.images = {}, {}
        n = {k: 0 for k, _l in self.KINDS}
        for m in media:
            n[self.kind_of(m)] += 1
        words = (("photo", "photo", "photos"), ("video", "video", "videos"), ("audio", "voice note or audio",
                 "voice notes and audio"), ("document", "document", "documents"))
        parts = [f"{n[k]:,} {one if n[k] == 1 else many}" for k, one, many in words if n[k]]
        gone = sum(1 for v in self.here.values() if not v)
        self.summary.configure(text=(" · ".join(parts) if parts else "No photos, videos, voice notes or documents")
                               + (f" · {gone:,} not in the backup" if gone else ""))
        self.note.configure(text="")
        self.show_btn.pack_forget()
        self._filter()

    def offer_folder(self, folder) -> None:
        """After Save all: a button that shows the folder in Finder / Explorer."""
        import phone
        self.show_btn.command = lambda: phone.reveal(folder)
        self.show_btn.pack(side="right", before=self.note)      # its room first; the note wraps in the rest

    def _filter(self):
        label = self.kind.get()
        k = next((k for k, l in self.KINDS if l == label), "all")
        self.items = [m for m in self.all if k == "all" or self.kind_of(m) == k]
        self.worker.clear()
        self._laid_out = None
        self.canvas.yview_moveto(0)
        self._relayout()

    def _cols(self) -> int:
        return max(2, (self.canvas.winfo_width() - self.GAP) // (self.TILE + self.GAP))

    def _new_tile(self, size: int) -> tk.Canvas:
        c = tk.Canvas(self.canvas, width=size, height=size, bg=theme.TILE_BG, highlightthickness=0, cursor="hand2")
        c.item = None
        c.bind("<ButtonRelease-1>", lambda e, c=c: self.open(c.item) if c.item is not None else None)
        c.win = self.canvas.create_window(0, 0, window=c, anchor="nw")
        self.pool.append(c)
        return c

    def open(self, m: dict) -> None:
        index = next((n for n, x in enumerate(self.items) if x is m), 0)
        self.on_open(self.key, self.items, index)

    def _relayout(self):
        """The rows on screen and one either side get tiles; scrolling moves the same tiles to the new rows."""
        self._relayout_due = False
        try:
            cols = self._cols()
            width, view = self.canvas.winfo_width(), self.canvas.winfo_height()
        except tk.TclError:
            return
        tile = max(self.TILE, (width - self.GAP * (cols + 1)) // cols)
        if tile != getattr(self, "tile", None):
            self.tile = tile
            self.images = {}
            self._laid_out = None
            for c in self.pool:
                c.configure(width=tile, height=tile)
        step = tile + self.GAP
        items = self.items
        rows = -(-len(items) // cols)
        region = (0, 0, width, self.GAP + rows * step + self.GAP)
        if region != self._region:              # setting it reports a scroll, which lays out again
            self._region = region
            self.canvas.configure(scrollregion=region)
        top = self.canvas.canvasy(0)
        r0 = max(0, int(top // step) - 1)
        r1 = min(rows, int((top + max(view, step)) // step) + 2)
        first, last = r0 * cols, min(len(items), r1 * cols)
        key = (id(items), cols, tile, first, last)
        if key == self._laid_out:
            return
        self._laid_out = key
        self.tiles = {}
        want = []
        for n in range(last - first):
            m = items[first + n]
            c = self.pool[n] if n < len(self.pool) else self._new_tile(tile)
            r, col = divmod(first + n, cols)
            self.canvas.coords(c.win, self.GAP + col * step, self.GAP + r * step)
            self.canvas.itemconfigure(c.win, state="normal")
            c.item = m
            self.tiles[m["id"]] = c
            self._draw(m)
            if self.kind_of(m) == "photo" and self.here.get(m["id"]) and m["id"] not in self.paths:
                want.append(m)
        for c in self.pool[last - first:]:
            c.item = None
            self.canvas.itemconfigure(c.win, state="hidden")
        self.worker.clear()                     # only the thumbnails on screen are asked for
        chat = (self.key, self.chat)
        for m in want:
            self.worker.submit(lambda m=m, k=self.key: self.preview.thumbnail(k, m),
                               lambda path, m=m: self._thumb_ready(m, path, chat))
        if len(self.images) > self.KEEP_IMAGES:
            for k in [k for k in self.images if k not in self.tiles][:len(self.images) - self.KEEP_IMAGES]:
                del self.images[k]

    def _thumb_ready(self, m, path, chat):
        if chat != (self.key, self.chat):       # another chat by now
            return
        self.paths[m["id"]] = path
        c = self.tiles.get(m["id"])
        if c is not None and c.item is m:
            self._draw(m)

    def _draw(self, m):
        c = self.tiles.get(m["id"])
        if c is None:
            return
        c.delete("all")
        T = self.tile
        kind, here = self.kind_of(m), self.here.get(m["id"])
        img = self.images.get(m["id"])
        if img is None and self.paths.get(m["id"]):
            img = load_photo(self.paths[m["id"]], T, square=True)
            if img is not None:
                self.images[m["id"]] = img
        when = dt.datetime.fromisoformat(m["time"]).strftime("%d %b %Y") if m.get("time") else ""
        if img is not None:
            c.create_image(T // 2, T // 2, image=img)
        else:
            c.create_text(T // 2, T // 2 - 16, text=self.ICON[kind], font=font(26), fill=INK if here else MUTED)
            name = self.preview.media_name(self.key, m) if kind != "photo" else ""
            if name:
                c.create_text(T // 2, T // 2 + 16, text=name if len(name) <= 18 else name[:17] + "…",
                              fill=INK if here else MUTED, font=font(9))
            c.create_text(T // 2, T - 12, text=when if here else "Not in the backup", fill=MUTED, font=font(9))
        if kind == "video" and img is not None:
            c.create_rectangle(4, T - 20, 30, T - 4, fill=theme.BADGE_BG, outline="")
            c.create_text(17, T - 12, text="▶", fill=theme.ON_DARK, font=font(10))


class PeopleWindow(tk.Toplevel):
    """M5: the small window listing a group chat's people (filled by ChatPanel.open_people)."""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.transient(parent.winfo_toplevel())


class Eta:
    """Progress → 'NN% · about M min left'. The time left comes from the speed over the last few minutes
    (settles quickly, follows changes such as many small files then big videos); until there is enough to
    go on it says 'working out time left…'. Used by every transfer PhoneKeep shows (01-principles.md)."""

    def __init__(self, window: float = 300.0, settle: float = 10.0):
        import time as _t
        self._t, self.window, self.settle = _t, window, settle
        self.points: list = []

    @staticmethod
    def fmt(seconds: float) -> str:
        if seconds < 90:
            return "under 2 min left"
        m = int(seconds // 60)
        return f"about {m} min left" if m < 90 else f"about {m // 60} h {m % 60:02d} min left"

    def feed(self, pct: float) -> str:
        """Record a percentage and return the text to show."""
        now = self._t.time()
        pct = max(0.0, min(100.0, float(pct)))
        self.points.append((now, pct))
        while len(self.points) > 2 and now - self.points[0][0] > self.window:
            self.points.pop(0)
        if pct >= 100:
            return "100%"
        first = self.points[0]
        eta = ""
        if pct > first[1] + 0.5 and now - first[0] >= self.settle:
            rate = (pct - first[1]) / (now - first[0])
            if rate > 0:
                eta = self.fmt((100 - pct) / rate)
        return f"{pct:.0f}%" + (f" · {eta}" if eta else " · working out time left…")


def touchpad_deltas(delta: int) -> tuple[int, int]:
    """Tk 9's <TouchpadScroll> packs the horizontal and vertical pixel deltas in one number (what
    tk::PreciseScrollDeltas unpacks): the high 16 bits are x, the low 16 bits y, both signed."""
    dx = delta >> 16
    dy = ((delta & 0xFFFF) ^ 0x8000) - 0x8000
    if dx >= 0x8000:
        dx -= 0x10000
    return dx, dy


def wheel_scroll(canvas: tk.Canvas) -> None:
    """Scroll `canvas` with a mouse wheel, Linux's buttons 4/5, and a Mac trackpad's two-finger scroll
    (Tk 9 sends that as <TouchpadScroll>, not <MouseWheel>; owner, 13 Nov: two-finger scroll did nothing in
    Photos), wherever the pointer is inside it, including over the tiles and labels it holds."""
    canvas.configure(yscrollincrement=1)                 # scroll in pixels, so a trackpad moves smoothly
    top = canvas.winfo_toplevel()

    def inside(w) -> bool:
        while w is not None:
            if w is canvas:
                return True
            w = getattr(w, "master", None)
        return False

    def pixels(n: float):
        if canvas.winfo_exists() and n:
            canvas.yview_scroll(int(n), "units")

    def on_wheel(e):
        if inside(e.widget):
            d = e.delta
            steps = d / 120 if abs(d) >= 120 else d      # Windows/Tk 9 notches are 120; Tk 8.6 on a Mac sends small ints
            pixels(-steps * 40)

    def on_touchpad(e):
        if inside(e.widget):
            _dx, dy = touchpad_deltas(int(e.delta))
            pixels(-dy)

    top.bind("<MouseWheel>", on_wheel, add="+")
    top.bind("<Button-4>", lambda e: inside(e.widget) and pixels(-120), add="+")
    top.bind("<Button-5>", lambda e: inside(e.widget) and pixels(120), add="+")
    try:
        top.bind("<TouchpadScroll>", on_touchpad, add="+")
    except tk.TclError:                                  # Tk 8.6 has no such event
        pass


def use_light_appearance(win) -> bool:
    """On a Mac the standard controls (lists, text boxes, drop-downs, the title bar) follow the window's appearance.
    Each PhoneKeep window uses the one matching its colours: light ("the chats in black look untidy", owner, 13 Nov)
    or, in dark mode (E6), dark. The name is kept from before E6. Returns True if applied."""
    if sys.platform != "darwin":
        return False
    done = False
    try:                                   # the whole app at once
        from AppKit import NSApplication, NSAppearance
        NSApplication.sharedApplication().setAppearance_(NSAppearance.appearanceNamed_(
            "NSAppearanceNameDarkAqua" if theme.DARK else "NSAppearanceNameAqua"))
        done = True
    except Exception:
        pass
    try:                                   # and this window (works without pyobjc, Tk 8.6.10+)
        win.tk.call("::tk::unsupported::MacWindowStyle", "appearance", win, "darkaqua" if theme.DARK else "aqua")
        done = True
    except Exception:
        pass
    return done


def no_tabs(win) -> bool:
    """Keep a window out of macOS's window tabs: with "Prefer tabs" on, or in full screen, macOS merged
    PhoneKeep's windows into tabs and the tab bar covered the top of the header (5.1.2). Older Tk without
    -tabbingmode is left as it is. Returns True if applied."""
    if sys.platform != "darwin":
        return False
    try:
        win.tk.call("wm", "attributes", win._w, "-tabbingmode", "disallowed")
        return True
    except tk.TclError:
        return False


def _no_tabs_on_create(cls) -> None:
    """Every window, PhoneKeep's own and Tk's (the main window, dialogs, viewers), gets no_tabs() as it's made,
    before macOS first shows it."""
    made = cls.__init__
    if getattr(made, "_pk_no_tabs", False):
        return

    def __init__(self, *args, **kwargs):
        made(self, *args, **kwargs)
        no_tabs(self)
        if theme.DARK and "bg" not in kwargs and "background" not in kwargs:
            try:                           # E6: never a white window before its own colours arrive
                self.configure(bg=theme.BG)
            except tk.TclError:
                pass
    __init__._pk_no_tabs = True
    cls.__init__ = __init__


_no_tabs_on_create(tk.Tk)
_no_tabs_on_create(tk.Toplevel)


def _attach_app_menu(win: tk.Toplevel) -> None:
    """Give a dialog the app's menu bar (macOS shows Tk's default File menu otherwise), and the light look."""
    if isinstance(win, tk.Toplevel):
        use_light_appearance(win)
    w = win.master
    while w is not None and not hasattr(w, "attach_menu"):
        w = getattr(w, "master", None)
    if w is not None:
        w.attach_menu(win)


class ChatPicker(tk.Toplevel):
    """Pick chats from WhatsApp, WhatsApp Business and Messages before an export."""

    def __init__(self, parent, lists: dict, preview=None):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        self.title("Choose chats to export")
        self.geometry("1040x660")
        self.minsize(820, 480)
        self.transient(parent)
        self.result = None
        head = header(self)
        head.pack(fill="x")
        tk.Label(head, text="Choose the chats to export", bg=theme.HEADER_BG, fg=theme.HEADER_TITLE,
                 font=font(17, "bold")).pack(side="left", padx=18, pady=12)
        tk.Label(head, text="Click a chat to preview it · tick the box to keep it", bg=theme.HEADER_BG, fg=theme.HEADER_TEXT,
                 font=font(12)).pack(side="left", pady=12)
        self.panel = ChatPanel(self, lists, preview)
        self.panel.pack(fill="both", expand=True)
        RoundButton(self.panel.foot, "Export selected", self._ok, "primary", 180, 40).pack(side="right")
        RoundButton(self.panel.foot, "Cancel", self._cancel, "secondary", 110, 40).pack(side="right", padx=10)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()

    # handy for tests and older callers
    def __getattr__(self, name):
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)

    def _ok(self):
        out = self.panel.selection()
        if out is None:
            return
        self.result = out
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self.worker.stop()
        self.destroy()


# ---------------------------------------------------------------------------
# Photo picker
# ---------------------------------------------------------------------------
class PhotoPanel(tk.Frame):
    """Photos month by month as thumbnails; click to select. Double-click opens a photo when
    on_open is given. Used by the export picker and by the phone window."""

    TILE = 128

    # P1: collections above the library, like the Photos app (key, label); filled from the phone's Photos library
    COLLECTIONS = (("c:fav", "★ Favourites"), ("c:videos", "▶ Videos"), ("c:shots", "▢ Screenshots"),
                   ("c:live", "◎ Live Photos"))

    def __init__(self, parent, source, items: list, select_all: bool = True, on_open=None, unlock=None, on_preview=None):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        from photos import human_size
        self.human_size = human_size
        self.on_open = on_open
        self.unlock = unlock            # P1: called with a function to run once Hidden may be shown
        self.on_preview = on_preview    # Q1: Space previews the last clicked photo; arrows go through the month
        self.cursor = None
        self.source = source
        self.hidden_items = [i for i in items if getattr(i, "hidden", False)]
        self.hidden_open = False        # Hidden stays closed until the owner confirms (or Touch ID)
        self.items = [i for i in items if not getattr(i, "hidden", False)]
        self.selected = {i.id for i in self.items} if select_all else set()
        self.images: dict = {}          # (item id, tile size) -> image
        self.paths: dict = {}           # item id -> its thumbnail file
        self.tiles: dict = {}
        self.worker = BgWorker(self)
        self.bind("<Destroy>", lambda e: self.worker.stop() if e.widget is self else None)
        self.months: dict[str, list] = {}           # every group the grid can show: months, collections, albums
        for i in self.items:
            self.months.setdefault(i.month, []).append(i)
        self.month_keys = sorted(self.months, reverse=True)
        lib = None
        try:
            lib = source.library() if hasattr(source, "library") else None
        except Exception:
            lib = None
        groups = {"c:fav": [i for i in self.items if getattr(i, "favorite", False)],
                  "c:videos": [i for i in self.items if i.video],
                  "c:shots": [i for i in self.items if getattr(i, "screenshot", False)],
                  "c:live": [i for i in self.items if getattr(i, "live_video", None) or getattr(i, "live_lib", False)]}
        self.collections = [(k, label) for k, label in self.COLLECTIONS if groups[k]]
        for k, _l in self.collections:
            self.months[k] = groups[k]
        self.album_rows = []
        for key, title, _n in (lib.albums if lib else []):
            # every album the Photos app lists, empty ones too (they show 0)
            self.months[key] = [i for i in self.items if key in getattr(i, "albums", ())]
            self.album_rows.append((key, title))
        if self.hidden_items:
            self.months["c:hidden"] = self.hidden_items
        self.shown = 0

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(12, 6))
        # one button that flips between Select all and Select none; a month or a year is (un)ticked with the box in
        # its row of the list (owner, 13 Nov: four buttons were confusing)
        self.all_btn = RoundButton(bar, "Select none", self._flip_all, "secondary", 120, 32, 12)
        self.all_btn.pack(side="left")
        tk.Label(bar, text="Tick a row in the list to select all of it · click a photo to select it",
                 bg=BG, fg=MUTED, font=font(11)).pack(side="left", padx=12)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16)
        side = card(body)
        side.pack(side="left", fill="y")
        tk.Label(side, text="Photos", bg=CARD, fg=MUTED, font=font(11, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        st = ttk.Style(self)                 # PhoneKeep's own colours (macOS dark mode drew this list black)
        st.configure("Months.Treeview", background=CARD, fieldbackground=CARD, foreground=INK, rowheight=28,
                     font=font(12))
        st.map("Months.Treeview", background=[("selected", GREEN_SOFT)], foreground=[("selected", INK)])
        st.configure("Months.Treeview", rowheight=26)
        self.mlist = ttk.Treeview(side, columns=("m", "n"), show="", selectmode="browse", height=18,
                                  style="Months.Treeview")
        self.mlist.column("m", width=180)
        # E7: wide enough for the biggest "selected/total" (a 10,000-photo group read "0/1000" in 64 px)
        most = len(self.items) + len(getattr(self, "hidden_items", []) or [])
        self.mlist.column("n", width=max(64, tkfont.Font(font=font(12, "bold")).measure(f"{most}/{most}") + 14), anchor="e")
        self.mlist.tag_configure("year", font=font(12, "bold"), foreground=INK)
        self.mlist.tag_configure("month", foreground=INK)
        self.mlist.pack(fill="y", expand=True, padx=4, pady=4)
        self.mlist.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.mlist.bind("<ButtonRelease-1>", self._row_click, add="+")

        grid_frame = card(body)
        grid_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.canvas = tk.Canvas(grid_frame, bg=CARD, highlightthickness=0)
        self.canvas.bind("<space>", lambda e: (self.preview_current(), "break")[1])
        gsb = ttk.Scrollbar(grid_frame, orient="vertical", command=self.canvas.yview)
        def scrolled(first, last):
            gsb.set(first, last)
            # E7: the tiles follow the rows on screen (once per redraw, however many scroll events came)
            if not self._relayout_due:
                self._relayout_due = True
                self.after_idle(self._relayout)
        self._relayout_due = False
        self.pool: list = []           # E7: the tiles there are, moved to the rows on screen as the grid scrolls
        self.canvas.configure(yscrollcommand=scrolled)
        self.canvas.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self._laid_out = None          # (month, cols, tile, rows on screen) of the last layout: only redone when it changes,
        self.canvas.bind("<Configure>", lambda e: self._relayout())   # or a Configure storm can loop (macOS)
        wheel_scroll(self.canvas)          # wheel, Linux buttons and the Mac trackpad, over tiles too

        self.foot = tk.Frame(self, bg=BG)
        self.foot.pack(side="bottom", fill="x", padx=16, pady=12, before=body)
        self.count = tk.Label(self.foot, bg=BG, fg=INK, font=font(13))
        self.count.pack(side="left")

        self.mlist.tag_configure("year", font=font(12, "bold"), foreground=INK)
        self._fill_months()
        if self.month_keys:
            self.mlist.selection_set(self.month_keys[0])
        self._update_count()

    def _fill_months(self):
        """The list: collections (Favourites, Videos, Screenshots, Live Photos), Albums, Hidden, then the Library
        as a line per year with its months under it, each with "selected/total" and a box to tick all of it
        (owner, 13 Nov). Rows are updated in place: re-inserting them re-selected the open group and emptied the
        grid (13 Nov: Select none, then Select this month)."""
        def put(iid, parent, label, items, tag, zero=False):
            n = sum(1 for i in items if i.id in self.selected)        # of all, like the Photos app counts them
            can = sum(1 for i in items if not getattr(i, "cloud_only", False))   # what can be ticked and saved
            indent = label[:len(label) - len(label.lstrip())]
            if items and can:
                values = (f"{indent}{self._box(n, can)} {label.lstrip()}", f"{n}/{len(items)}")
            elif items:                                  # all only in iCloud: nothing to tick
                values = (f"{indent}   {label.lstrip()}", f"{len(items)}")
            elif zero:                                   # an empty album: lined up with the others, "0"
                values = (f"{indent}   {label.lstrip()}", "0")
            else:
                values = (label, "")
            if self.mlist.exists(iid):
                self.mlist.item(iid, values=values)
            else:
                self.mlist.insert(parent, "end", iid=iid, values=values, tags=(tag,), open=True)

        for k, label in self.collections:
            put(k, "", label, self.months[k], "year")
        if self.album_rows:
            put("head-albums", "", "Albums", [i for k, _t in self.album_rows for i in self.months[k]], "year")
            for k, title in self.album_rows:
                put(k, "head-albums", "    " + title, self.months[k], "month", zero=True)
        if self.hidden_items:
            label = "🔒 Hidden" if not self.hidden_open else "Hidden"
            put("c:hidden", "", label, self.hidden_items if self.hidden_open else [], "year")
        if self.collections or self.album_rows or self.hidden_items:
            put("head-library", "", "Library", [], "year")
        years: dict = {}
        for m in self.month_keys:
            years.setdefault("Unknown" if m == "1970-01" else m[:4], []).append(m)
        for y, months in years.items():
            put(f"year-{y}", "", y if y != "Unknown" else "Unknown date",
                [i for m in months for i in self.months[m]], "year")
            for m in months:
                label = "    " + (dt.datetime.strptime(m, "%Y-%m").strftime("%B") if m != "1970-01" else "No date")
                put(m, f"year-{y}", label, self.months[m], "month")

    def _group_items(self, row: str) -> list:
        """The photos a list row stands for (a year, the albums heading, a month, a collection or an album)."""
        if row.startswith("year-") or row == "head-albums":
            return [i for m in self.mlist.get_children(row) for i in self.months.get(m, [])]
        if row == "c:hidden" and not self.hidden_open:
            return []
        return self.months.get(row, [])

    @staticmethod
    def _box(n: int, total: int) -> str:
        return "☑" if total and n == total else ("◪" if n else "☐")

    def _row_click(self, e):
        """A click on a row's box (un)ticks that whole month or year; a click elsewhere just opens it."""
        row = self.mlist.identify_row(e.y)
        if not row or row == "head-library":
            return
        x0 = 52 if self.mlist.parent(row) else 30          # the box sits at the start of the row
        if e.x > x0:
            return
        items = [i for i in self._group_items(row) if not getattr(i, "cloud_only", False)]
        if not items:
            return
        on = not all(i.id in self.selected for i in items)
        for i in items:
            (self.selected.add if on else self.selected.discard)(i.id)
        for i in self.months.get(self._month(), []):
            self._draw_tile(i)
        self._fill_months()
        self._update_count()

    def _flip_all(self):
        self._set_all(len(self.selected) < len(self._selectable()))

    def _selectable(self) -> list:
        """What can be ticked and saved: not photos whose full version is only in iCloud."""
        return [i for i in self.items + (self.hidden_items if self.hidden_open else []) if not i.cloud_only]

    def _open_hidden(self):
        """Hidden opens only after Touch ID / the computer's password (app lock on) or a confirmation."""
        def go():
            self.hidden_open = True
            self._fill_months()
            self.mlist.selection_set("c:hidden")
            self._open_month()
        if self.unlock is not None:
            self.unlock(go)
        elif messagebox.askyesno("Show hidden photos?", "These are the photos you hid on the iPhone. Show them here?",
                                 parent=self):
            go()

    def _on_select(self):
        sel = self.mlist.selection()
        if not sel:
            return
        row = sel[0]
        if row == "c:hidden" and not self.hidden_open:
            self._open_hidden()
            return
        if row.startswith("year-") or row.startswith("head-"):     # a heading opens its first group
            kids = self.mlist.get_children(row)
            if kids:
                self.mlist.selection_set(kids[0])
            elif row == "head-library":
                first = next((r for r in self.mlist.get_children("") if r.startswith("year-")), None)
                if first:
                    self.mlist.selection_set(first)
            return
        self._open_month()
    def _month(self) -> Optional[str]:
        s = self.mlist.selection()
        if not s or s[0].startswith(("year-", "head-")) or (s[0] == "c:hidden" and not self.hidden_open):
            return None
        return s[0] if s[0] in self.months else None

    def _open_month(self):
        self.worker.clear()
        self.shown = 0
        self._laid_out = None          # another group: always place the tiles
        self.canvas.yview_moveto(0)
        self._relayout()

    GAP = 6
    KEEP_IMAGES = 1500                 # E7: thumbnails kept in memory (those on screen are always kept)

    def _cols(self) -> int:
        return max(3, (self.canvas.winfo_width() - self.GAP) // (self.TILE + self.GAP))

    def _tile_size(self, cols: int) -> int:
        """Tiles grow so the columns fill the width exactly (owner, 13 Nov: white space on the right)."""
        return max(self.TILE, (self.canvas.winfo_width() - self.GAP * (cols + 1)) // cols)

    def _new_tile(self, size: int) -> tk.Canvas:
        c = tk.Canvas(self.canvas, width=size, height=size, bg=theme.TILE_BG, highlightthickness=0, cursor="hand2")
        c.item = None
        c.bind("<ButtonRelease-1>", lambda e, c=c: (self._point_at(c.item, e.widget), self._toggle(c.item))
               if c.item is not None else None)
        c.bind("<space>", lambda e: (self.preview_current(), "break")[1])
        if self.on_open:
            c.bind("<Double-Button-1>", lambda e, c=c: self.on_open(c.item) if c.item is not None else None)
        c.win = self.canvas.create_window(0, 0, window=c, anchor="nw")
        self.pool.append(c)
        return c

    def _relayout(self):
        """E7 (virtual scrolling): the grid is as tall as all of the group's photos, but tiles are made only for the
        rows on screen and one row either side; as it scrolls, the same tiles move to the new rows and show their
        photos. 10,000 photos scroll like 100, and only the thumbnails on screen are asked for."""
        self._relayout_due = False
        try:
            m = self._month()
            items = self.months.get(m, []) if m else []
            cols = self._cols()
            tile = self._tile_size(cols)
            width, view = self.canvas.winfo_width(), self.canvas.winfo_height()
        except tk.TclError:
            return
        resized = tile != getattr(self, "tile", None)
        if resized:
            self.tile = tile
            self.images = {k: v for k, v in self.images.items() if k[1] == tile}     # drop other sizes
            for c in self.pool:
                c.configure(width=tile, height=tile)
        step = tile + self.GAP
        rows = -(-len(items) // cols)
        region = (0, 0, width, self.GAP + rows * step + self.GAP)
        if region != getattr(self, "_region", None):  # setting it reports a scroll, which lays out again
            self._region = region
            self.canvas.configure(scrollregion=region)
        top = self.canvas.canvasy(0)
        r0 = max(0, int(top // step) - 1)
        r1 = min(rows, int((top + max(view, step)) // step) + 2)
        first, last = r0 * cols, min(len(items), r1 * cols)
        key = (m, cols, tile, first, last)
        if key == self._laid_out:
            return
        moved = self._laid_out is None or self._laid_out[:3] != key[:3]
        self._laid_out = key
        self.tiles = {}
        want = []
        for n in range(last - first):
            item = items[first + n]
            c = self.pool[n] if n < len(self.pool) else self._new_tile(tile)
            r, col = divmod(first + n, cols)
            self.canvas.coords(c.win, self.GAP + col * step, self.GAP + r * step)
            self.canvas.itemconfigure(c.win, state="normal")
            again = c.item is not item or resized or moved
            c.item = item
            self.tiles[item.id] = c
            if again:
                self._draw_tile(item)
            if item.id not in self.paths:
                want.append(item)
        for c in self.pool[last - first:]:
            c.item = None
            self.canvas.itemconfigure(c.win, state="hidden")
        self.shown = max(self.shown, last)
        # thumbnails: only those on screen, the ones asked for while scrolling past are dropped
        self.worker.clear()
        for item in want:
            self.worker.submit(lambda i=item: self.source.thumbnail(i),
                               lambda path, i=item, m=m: self._thumb_ready(i, path, m))
        if len(self.images) > self.KEEP_IMAGES:
            keep = set(self.tiles)
            for k in [k for k in self.images if k[0] not in keep][:len(self.images) - self.KEEP_IMAGES]:
                del self.images[k]

    def _thumb_ready(self, item, path, month):
        self.paths[item.id] = path
        if month == self._month() and item.id in self.tiles:
            self._draw_tile(item)

    def _draw_tile(self, item):
        c = self.tiles.get(item.id)
        if c is None:
            return
        c.delete("all")
        T = getattr(self, "tile", self.TILE)
        cloud = getattr(item, "cloud_only", False)
        img = self.images.get((item.id, T))
        if img is None and self.paths.get(item.id):
            img = load_photo(self.paths[item.id], T, square=True, faded=cloud)
            if img is not None:
                self.images[(item.id, T)] = img
        if img is not None:
            c.create_image(T // 2, T // 2, image=img)
        else:
            c.create_text(T // 2, T // 2 - 8, text="🎬" if item.video else "🖼", font=font(26))
            c.create_text(T // 2, T - 34 if item.video else T - 18, text=item.name[:16], fill=MUTED, font=font(9))
        if item.video:
            c.create_rectangle(4, T - 20, 30, T - 4, fill=theme.BADGE_BG, outline="")
            c.create_text(17, T - 12, text="▶", fill=theme.ON_DARK, font=font(10))
        if item.live_video:
            c.create_rectangle(4, 4, 36, 20, fill=theme.BADGE_BG, outline="")
            c.create_text(20, 12, text="LIVE", fill=theme.ON_DARK, font=font(8, "bold"))
        if cloud:                                     # washed out, with a cloud: the full photo is only in iCloud
            draw_cloud(c, T - 18, 16)
        # selected: a blue frame, nothing else (owner, 13 Nov: no tick circle)
        if item.id in self.selected:
            c.create_rectangle(2, 2, T - 2, T - 2, outline=SELECT_BLUE, width=5)

    def _point_at(self, item, widget=None):
        self.cursor = item
        try:
            (widget or self).focus_set()
        except tk.TclError:
            pass

    def preview_current(self):
        """Q1: Space shows the photo last clicked, large; the arrows move through what's on screen."""
        if self.on_preview is None:
            return
        shown = self.months.get(self._month(), [])
        if not shown:
            return
        idx = next((n for n, i in enumerate(shown) if self.cursor is not None and i.id == self.cursor.id), 0)
        self.on_preview(shown, idx)

    def _toggle(self, item):
        if getattr(item, "cloud_only", False):          # only in iCloud: nothing to save from the iPhone
            return
        self.selected.symmetric_difference_update({item.id})
        self._draw_tile(item)
        self._fill_months()
        self._update_count()

    def _set_all(self, on: bool):
        self.selected = {i.id for i in self._selectable()} if on else set()
        for i in self.months.get(self._month(), []):
            self._draw_tile(i)
        self._fill_months()
        self._update_count()

    def _set_month(self, on: bool):
        for i in self.months.get(self._month(), []):
            if on and getattr(i, "cloud_only", False):
                continue
            (self.selected.add if on else self.selected.discard)(i.id)
            self._draw_tile(i)
        self._fill_months()
        self._update_count()

    def _update_count(self):
        chosen = [i for i in self._selectable() if i.id in self.selected]
        size = sum(i.size for i in chosen)
        nv = sum(1 for i in chosen if i.video)
        n_p = len(chosen) - nv
        cloud = sum(1 for i in self.items if getattr(i, "cloud_only", False))
        self.count.configure(text=f"{n_p:,} photo{'s' if n_p != 1 else ''} and {nv:,} video{'s' if nv != 1 else ''} "
                                  f"selected of {len(self._selectable()):,} · about {self.human_size(size)}"
                                  + (f" · {cloud:,} only in iCloud" if cloud else ""))
        if hasattr(self, "all_btn"):
            self.all_btn.configure_text("Select none" if len(self.selected) == len(self._selectable()) and self.items else "Select all")


class PhotoPicker(tk.Toplevel):
    """Browse photos month by month as thumbnails and pick which to copy."""

    def __init__(self, parent, source, items: list, unlock=None):
        super().__init__(parent, bg=BG)
        _attach_app_menu(self)
        self.title("Choose photos & videos")
        self.geometry("1040x700")
        self.minsize(820, 520)
        self.transient(parent)
        self.result = None
        head = header(self)
        head.pack(fill="x")
        tk.Label(head, text="Choose the photos & videos to keep", bg=theme.HEADER_BG, fg=theme.HEADER_TITLE,
                 font=font(17, "bold")).pack(side="left", padx=18, pady=12)
        tk.Label(head, text=f"from {source.label} · click a photo to select or unselect it", bg=theme.HEADER_BG,
                 fg=theme.HEADER_TEXT, font=font(12)).pack(side="left", pady=12)
        self.panel = PhotoPanel(self, source, items, unlock=unlock)
        self.panel.pack(fill="both", expand=True)
        RoundButton(self.panel.foot, "Continue", self._ok, "primary", 160, 40).pack(side="right")
        RoundButton(self.panel.foot, "Skip photos", self._skip, "secondary", 130, 40).pack(side="right", padx=10)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.grab_set()

    def __getattr__(self, name):
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)

    def _ok(self):
        self.result = set(self.panel.selected)
        self._close()

    def _skip(self):
        self.result = set()
        self._close()

    def _close(self):
        self.worker.stop()
        self.destroy()


# ---------------------------------------------------------------------------
# Password dialogs (S1): choose a backup password, or enter the one the iPhone already uses
# ---------------------------------------------------------------------------

class PasswordDialog(tk.Toplevel):
    """One field with show/hide, a strength hint, and the line about the keychain.

    mode = "choose"  : a new password for a phone whose backups aren't encrypted yet.
                       The main button is the confirmation for writing to the phone ("Turn on encryption").
    mode = "enter"   : the password the iPhone already uses; offers the Reset All Settings help.
    mode = "confirm" : the current password, needed before turning encryption off.
    mode = "change"  : current + new password.
    Result: self.result = password (str), or (old, new) for "change", or None if cancelled.
    """

    TEXT = {
        "choose": ("Choose a backup password", "Turn on encryption",
                   "Your iPhone will encrypt its backups with this password."),
        "enter": ("Enter your backup password", "Continue",
                  "This iPhone already encrypts its backups. PhoneKeep needs the password once."),
        "confirm": ("Enter your backup password", "Turn off encryption",
                    "The iPhone needs the current password to turn encryption off."),
        "change": ("Change the backup password", "Change password",
                   "Your iPhone will switch its backups to the new password."),
    }

    def __init__(self, parent, mode: str = "choose", phone_name: str = "your iPhone",
                 keychain_available: bool = True, help_text: str = ""):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        import keychain as kc
        self.kc, self.mode, self.result = kc, mode, None
        title, verb, sub = self.TEXT[mode]
        self.title(f"{title} — {phone_name}")
        self.resizable(False, False)
        self.transient(parent)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(body, text="🔒", bg=CARD, font=font(28)).pack()
        tk.Label(body, text=title, bg=CARD, fg=INK, font=font(17, "bold")).pack(pady=(2, 4))
        tk.Label(body, text=sub, bg=CARD, fg=MUTED, font=font(12), wraplength=400, justify="center").pack()

        self.vars = []
        labels = ["Current password", "New password"] if mode == "change" else [""]
        for lab in labels:
            if lab:
                tk.Label(body, text=lab, bg=CARD, fg=INK, font=font(12), anchor="w").pack(fill="x", pady=(12, 2))
            row = tk.Frame(body, bg=CARD)
            row.pack(fill="x", pady=(14 if not lab else 0, 0))
            var = tk.StringVar()
            ent = ttk.Entry(row, textvariable=var, show="•", font=font(14), width=28)
            ent.pack(side="left", fill="x", expand=True, ipady=4)
            eye = tk.Label(row, text="Show", bg=CARD, fg=GREEN, font=font(11), cursor="hand2")
            eye.pack(side="left", padx=(8, 0))
            eye.bind("<Button-1>", lambda e, en=ent, ey=eye: self._toggle(en, ey))
            self.vars.append(var)
        self.entry_first = body.winfo_children()[-1].winfo_children()[0]

        self.hint = tk.Label(body, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.hint.pack(fill="x", pady=(4, 0))
        if mode in ("choose", "change"):
            self.vars[-1].trace_add("write", lambda *_: self._strength())
        note = ("Saved in your Keychain. You won't need to type it again.\nIf you forget it, the backup can't be opened."
                if sys.platform == "darwin" else
                "Saved in Windows Credential Manager. You won't need to type it again.\nIf you forget it, the backup can't be opened.")
        if not keychain_available:
            note = "This computer has no keychain, so PhoneKeep will ask for the password when it needs it.\nIf you forget it, the backup can't be opened."
        tk.Label(body, text=note, bg=CARD, fg=MUTED, font=font(11), justify="left", anchor="w").pack(fill="x", pady=(10, 0))
        if help_text:
            lk = tk.Label(body, text="I don't know the password", bg=CARD, fg=GREEN, font=font(11), cursor="hand2", anchor="w")
            lk.pack(fill="x", pady=(8, 0))
            lk.bind("<Button-1>", lambda e: messagebox.showinfo("Forgotten backup password", help_text, parent=self))

        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(18, 0))
        self.ok_btn = RoundButton(btns, verb, self._ok, "primary", 190, 40, bg=CARD)
        self.ok_btn.pack(side="right")
        RoundButton(btns, "Cancel", self._cancel, "secondary", 100, 40, bg=CARD).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.entry_first.focus_set()
        self.grab_set()

    def _toggle(self, ent, eye):
        showing = ent.cget("show") == ""
        ent.configure(show="•" if showing else "")
        eye.configure(text="Show" if showing else "Hide")

    def _strength(self):
        score, word = self.kc.strength(self.vars[-1].get())
        colour = {0: MUTED, 1: RED, 2: AMBER, 3: GREEN, 4: GREEN}[score]
        self.hint.configure(text=f"Strength: {word}" if word else "", fg=colour)

    def _ok(self):
        values = [v.get() for v in self.vars]
        if any(not v for v in values):
            self.hint.configure(text="Please type a password.", fg=RED)
            return
        if self.mode in ("choose", "change") and self.kc.strength(values[-1])[0] < 1:
            self.hint.configure(text="Use at least 8 characters.", fg=RED)
            return
        self.result = tuple(values) if self.mode == "change" else values[0]
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class TextDialog(tk.Toplevel):
    """One line of text with OK/Cancel, in PhoneKeep's own style (Tk's simpledialog misbehaves on macOS:
    it can come up behind the window, or not at all from a popup menu). Result: str, or None if cancelled."""

    def __init__(self, parent, title: str, prompt: str, initial: str = "", ok: str = "Save"):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(body, text=title, bg=CARD, fg=INK, font=font(17, "bold")).pack(pady=(2, 4))
        tk.Label(body, text=prompt, bg=CARD, fg=MUTED, font=font(12), wraplength=400, justify="center").pack()
        self.var = tk.StringVar(value=initial or "")
        self.entry = ttk.Entry(body, textvariable=self.var, font=font(14), width=32)
        self.entry.pack(fill="x", pady=(14, 0), ipady=4)
        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(18, 0))
        RoundButton(btns, ok, self._ok, "primary", 150, 40, bg=CARD).pack(side="right")
        RoundButton(btns, "Cancel", self._cancel, "secondary", 100, 40, bg=CARD).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.lift()
        self.grab_set()

    def _ok(self):
        self.result = self.var.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class ChoiceDialog(tk.Toplevel):
    """Pick one of a few options (radio buttons) with OK/Cancel. Result: the chosen index, or None."""

    def __init__(self, parent, title: str, prompt: str, options: list, initial: int = 0, ok: str = "Save"):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(body, text=title, bg=CARD, fg=INK, font=font(17, "bold")).pack(pady=(2, 4))
        tk.Label(body, text=prompt, bg=CARD, fg=MUTED, font=font(12), wraplength=420, justify="center").pack()
        self.var = tk.IntVar(value=initial)
        box = tk.Frame(body, bg=CARD)
        box.pack(fill="x", pady=(14, 0))
        for n, (label, detail) in enumerate(options):
            ttk.Radiobutton(box, text=label, variable=self.var, value=n).pack(anchor="w", pady=(6, 0))
            if detail:
                tk.Label(box, text=detail, bg=CARD, fg=MUTED, font=font(11), wraplength=400, justify="left",
                         anchor="w").pack(fill="x", padx=(24, 0))
        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(18, 0))
        RoundButton(btns, ok, self._ok, "primary", 150, 40, bg=CARD).pack(side="right")
        RoundButton(btns, "Cancel", self._cancel, "secondary", 100, 40, bg=CARD).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.lift()
        self.grab_set()

    def _ok(self):
        self.result = self.var.get()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


PHOTO_FORMATS = [("Original (HEIC)", "Exactly as on the iPhone: smallest files, best quality."),
                 ("Most compatible (JPG)", "Opens everywhere (older Windows, websites). Keeps the date taken "
                                           "and the location.")]


def ask_photo_format(parent, initial: int = 0):
    """P1: "Original (HEIC) / Most compatible (JPG)". True = JPG, False = original, None = cancelled."""
    d = ChoiceDialog(parent, "Save photos as", "Videos are always saved as they are.", PHOTO_FORMATS, initial)
    parent.wait_window(d)
    return None if d.result is None else d.result == 1


class DetailsDialog(tk.Toplevel):
    """'Show details': the technical text for support, in a window that is big enough to read and can be
    resized, scrolled and copied (13 Nov: the old message box was too small to show a traceback)."""

    def __init__(self, parent, text: str, title: str = "Details for support"):
        super().__init__(parent, bg=CARD)
        _attach_app_menu(self)
        self.title(title)
        self.geometry("780x460")
        self.minsize(420, 240)
        self.transient(parent)
        top = tk.Frame(self, bg=CARD)
        top.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(top, text=title, bg=CARD, fg=INK, font=font(16, "bold")).pack(side="left")
        btns = tk.Frame(self, bg=CARD)
        btns.pack(side="bottom", fill="x", padx=20, pady=(8, 16))
        RoundButton(btns, "Close", self.destroy, "primary", 110, 36, bg=CARD).pack(side="right")
        self.copy_btn = RoundButton(btns, "Copy all", self.copy, "secondary", 120, 36, bg=CARD)
        self.copy_btn.pack(side="right", padx=8)
        box = tk.Frame(self, bg=CARD)
        box.pack(fill="both", expand=True, padx=20)
        bar = ttk.Scrollbar(box, orient="vertical")
        self.text = tk.Text(box, wrap="word", font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10),
                            bg=theme.SUBTLE, fg=INK, relief="flat", padx=10, pady=8, yscrollcommand=bar.set,
                            highlightthickness=1, highlightbackground=LINE)
        bar.configure(command=self.text.yview)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", text or "")
        self.text.configure(state="disabled")      # read-only, but text can still be selected and copied
        self.content = text or ""
        self.bind("<Escape>", lambda e: self.destroy())
        self.lift()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.content)
        self.copy_btn.configure_text("Copied ✓")


def show_details(parent, text: str):
    """Open the details window (not modal: the main window stays usable)."""
    return DetailsDialog(parent, text)


def ask_text(parent, title: str, prompt: str, initial: str = "", ok: str = "Save"):
    """Open a TextDialog and wait for it. Returns the text, or None if cancelled."""
    d = TextDialog(parent, title, prompt, initial, ok)
    parent.wait_window(d)
    return d.result


def ask_password(parent, mode: str, phone_name: str, help_text: str = ""):
    """Open a PasswordDialog and wait for it. Returns the result (see PasswordDialog)."""
    import keychain as kc
    d = PasswordDialog(parent, mode, phone_name, kc.available(), help_text)
    parent.wait_window(d)
    return d.result
