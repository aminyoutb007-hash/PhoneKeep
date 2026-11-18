"""PhoneKeep's colours and font, in one place: Direction A ("Calm"), 15 Nov. Windows use these names, never a colour
written out. Saved files (the web archive, chat PDFs) keep their own look and don't read this.

The first block is Direction A as agreed. The rest are colours the windows already had (status, banners, the drawn
phone, PhoneKeep's own app tiles, the dark preview viewer), named here so nothing is written out anywhere else.

E6, dark mode: the same names, chosen once as PhoneKeep starts (every window reads them as it's built):
Settings → Appearance (System, Light, Dark; "system" by default) or, with System, the computer's own setting.
PHONEKEEP_APPEARANCE=light|dark overrides both (screenshots); tests (PHONEKEEP_HOME set) stay light unless they ask.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def system_is_dark() -> bool:
    """The computer's own light/dark setting: macOS's AppleInterfaceStyle, Windows' AppsUseLightTheme. Light
    elsewhere or if it can't be read."""
    try:
        if sys.platform == "darwin":
            from Foundation import NSUserDefaults
            return str(NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle") or "") == "Dark"
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False


def saved_choice() -> str:
    """Settings → Appearance: "system", "light" or "dark" (read from settings.json before any window exists)."""
    home = Path(os.environ.get("PHONEKEEP_HOME") or Path.home() / "PhoneKeep")
    try:
        v = json.loads((home / "settings.json").read_text(encoding="utf-8")).get("appearance", "system")
        return v if v in ("system", "light", "dark") else "system"
    except (OSError, ValueError, AttributeError):
        return "system"


def choose_mode() -> str:
    forced = os.environ.get("PHONEKEEP_APPEARANCE", "").lower()
    if forced in ("light", "dark"):
        return forced
    choice = saved_choice()
    if choice != "system":
        return choice
    if os.environ.get("PHONEKEEP_HOME"):          # tests: the same pictures whatever the computer is set to
        return "light"
    return "dark" if system_is_dark() else "light"


MODE = choose_mode()
DARK = MODE == "dark"

# -- Direction A ---------------------------------------------------------------------------------------------------------
BG = "#F5F5F7"                 # window background
CARD = "#FFFFFF"
BORDER = "#E5E5EA"             # card and secondary-button border
TEXT = "#1D1D1F"
TEXT_2 = "#6E6E73"             # secondary text
ACCENT = "#0F766E"             # main buttons, headers, ticks
ACCENT_HOVER = "#0B5A54"
ACCENT_PALE = "#E8F5F2"        # the selected row in sidebars and lists; soft accent areas
WARN_TEXT = "#9A5B00"
WARN_BG = "#FFF7E6"
BODY_SIZE = 13                 # body text in points on a Mac (13-14); fonts are scaled for Windows in ui.font()
if DARK:                       # E6: Direction A at night: the same calm teal, lifted so it reads on dark grey
    BG, CARD, BORDER = "#1C1C1E", "#2C2C2E", "#3A3A3C"
    TEXT, TEXT_2 = "#F5F5F7", "#A1A1A6"
    ACCENT, ACCENT_HOVER, ACCENT_PALE = "#2BB3A3", "#4CC7B8", "#1E3B38"
    WARN_TEXT, WARN_BG = "#F2B65A", "#3A2F1C"

# -- derived from Direction A ----------------------------------------------------------------------------------------------
ON_ACCENT = "#06201D" if DARK else "#FFFFFF"   # text and ticks on the accent (dark text on the lighter dark-mode teal)
HEADER_BG = CARD               # window headers are light (Direction A, 15 Nov)
HEADER_TITLE = TEXT
HEADER_TEXT = TEXT_2           # a header's second line
HEADER_LINK = ACCENT           # header links and icons (Settings, Refresh from iPhone, Saved files)
HEADER_LINE = BORDER           # the 1 px line under a header
ON_DARK = "#FFFFFF"            # text on a drawn phone screen or a dark badge
ON_ACCENT_2 = ACCENT_PALE      # quieter text on the accent (a header's second line)
ACCENT_DISABLED = "#9FCBC6"    # a main button that can't be clicked yet
ACCENT_PALE_HOVER = "#D3EBE6"  # a light (pale accent) button under the pointer
SECONDARY_HOVER = "#F2F2F4"
SECONDARY_DISABLED = "#F7F7F8"
BORDER_HOVER = "#C7C7CC"       # a card's border under the pointer
SWITCH_OFF = "#C7C7CC"         # a switch's outline when off
SUBTLE = "#FAFAFB"             # quiet panels inside a card (details text, file lists)
TILE_BG = "#EBEBEF"            # a photo tile before its thumbnail comes
if DARK:
    ON_ACCENT_2 = "#CFEDE8"
    ACCENT_DISABLED, ACCENT_PALE_HOVER = "#2D5450", "#27504B"
    SECONDARY_HOVER, SECONDARY_DISABLED = "#3A3A3C", "#252527"
    BORDER_HOVER, SWITCH_OFF = "#5A5A5E", "#5A5A5E"
    SUBTLE, TILE_BG = "#242426", "#3A3A3C"

# -- kept as they were: meaning, not decoration ---------------------------------------------------------------------------
LINK = "#0A84FF"               # links ("See details ›") and selected photos: the system's blue
RED = "#C5221F"
ERROR_BG = "#FDECEA"           # a banner saying something went wrong
GOOD, CAUTION, BAD = "#1F9D55", "#C77700", "#C0392B"   # the device overview's status dots
STRENGTH = {0: TEXT_2, 1: RED, 2: WARN_TEXT, 3: ACCENT, 4: ACCENT}  # password strength hint
HIT = "#FFE58F"                # a search hit inside a chat
CHAT_BG, ME = "#EFEAE2", "#D9FDD3"                      # a chat preview looks like the phone's
NOTE_BG = "#FFFDF3"            # a note, as on the phone
BADGE_BG = "#000000"           # the small dark badge on a photo tile (▶ 0:12, ⚡ Live)
BADGE_GREY = "#3A3A3C"
if DARK:
    LINK, RED, ERROR_BG = "#4DA3FF", "#FF7A70", "#3D2321"
    GOOD, CAUTION, BAD = "#34C76F", "#E8A23B", "#FF6F61"
    HIT = "#7A5F12"                                      # under light text
    CHAT_BG, ME = "#14191B", "#0D4D40"                   # as the phone's chats look at night
    NOTE_BG = "#2B2920"
    STRENGTH = {0: TEXT_2, 1: RED, 2: WARN_TEXT, 3: ACCENT, 4: ACCENT}

# -- drawings: the phone in the windows and the first-run guide -----------------------------------------------------------
PHONE_BODY = "#1C1C1E"
PHONE_SCREEN = "#2F6F63"
PHONE_SCREEN_TEXT = ON_ACCENT_2
PHONE_ISLAND = "#000000"
PHONE_HOME_BAR = "#FFFFFF"
PHONE_SCREEN_SOFT = "#CFE3DD"   # the first-run guide's phone showing the Trust question
DRAW_INK = "#111B21"            # the first-run guide's phone outline
DRAW_GREY, DRAW_LIGHT, DRAW_PANEL = "#8A949A", "#C9CFD3", "#E8ECEF"
PHONE_ICON = {"ok": ACCENT, "searching": "#9AA5AB", "none": "#C3CBCF"}   # the main window's phone picture
PHONE_ICON_RING = "#D6EFE8"
if DARK:                       # the drawn phones stay phones; their outlines and panels turn light enough to see
    PHONE_BODY = "#0B0B0C"
    PHONE_SCREEN_TEXT = ON_ACCENT_2
    PHONE_SCREEN_SOFT = "#2E4A45"
    DRAW_INK = "#C9D1D6"
    DRAW_GREY, DRAW_LIGHT, DRAW_PANEL = "#8A949A", "#4A5257", "#33393D"
    PHONE_ICON = {"ok": ACCENT, "searching": "#6E7A80", "none": "#4F585D"}
    PHONE_ICON_RING = "#1E3B38"

# -- PhoneKeep's own app tiles in the phone window (its drawings, not Apple's) and the storage bar ----------------------
APP_TILE = {"photos": "#FFF4E0", "messages": "#34C759", "whatsapp": "#25D366", "whatsappbusiness": "#0F7C6C",
            "calls": "#30D158", "contacts": "#9A9AA0", "voicemail": "#0A84FF", "notes": "#FFD60A",
            "calendar": "#FFFFFF", "voicememos": "#3A3A3C", "callrecordings": "#E0452B", "safari": "#0A84FF", "music": "#FA2D48",
            "books": "#FF9500", "files": "#1E90FF", "apps": "#5E5CE6", "allfiles": "#8E8E93", "checkup": "#34C759"}
STORAGE = {"Apps": "#4F7CFF", "Photos": "#F2A93B", "Messages": "#34C759", "System": "#8E8E93", "System and other": "#8E8E93", "Other": "#C7C7CC",
           "Free": "#ECECF0"}
if DARK:
    STORAGE["Free"], STORAGE["Other"] = "#3A3A3C", "#636366"

# -- the preview viewer (Space) is dark, like Quick Look ---------------------------------------------------------------------
VIEWER_BG, VIEWER_TEXT, VIEWER_TEXT_2 = "#1C1C1E", "#F2F2F7", "#A1A1AA"
VIEWER_PANEL, VIEWER_ERROR, VIEWER_BUTTON = "#2C2C2E", "#FF6B6B", "#0A84FF"


def font_family(default: str) -> str:
    """The system font: San Francisco on a Mac (Tk's default font there), Segoe UI on Windows."""
    if sys.platform == "win32":
        return "Segoe UI"
    return default
