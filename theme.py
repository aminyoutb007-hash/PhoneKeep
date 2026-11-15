"""PhoneKeep's colours and font, in one place: Direction A ("Calm"), 15 Nov. Windows use these names, never a colour
written out. Saved files (the web archive, chat PDFs) keep their own look and don't read this.

The first block is Direction A as agreed. The rest are colours the windows already had (status, banners, the drawn
phone, PhoneKeep's own app tiles, the dark preview viewer), named here so nothing is written out anywhere else.
"""
from __future__ import annotations

import sys

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

# -- derived from Direction A ----------------------------------------------------------------------------------------------
ON_ACCENT = "#FFFFFF"          # text and ticks on the accent
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

# -- PhoneKeep's own app tiles in the phone window (its drawings, not Apple's) and the storage bar ----------------------
APP_TILE = {"photos": "#FFF4E0", "messages": "#34C759", "whatsapp": "#25D366", "whatsappbusiness": "#0F7C6C",
            "calls": "#30D158", "contacts": "#9A9AA0", "voicemail": "#0A84FF", "notes": "#FFD60A",
            "calendar": "#FFFFFF", "voicememos": "#3A3A3C", "safari": "#0A84FF", "music": "#FA2D48",
            "books": "#FF9500", "files": "#1E90FF", "apps": "#5E5CE6", "allfiles": "#8E8E93", "checkup": "#34C759"}
STORAGE = {"Apps": "#4F7CFF", "Photos": "#F2A93B", "Messages": "#34C759", "System": "#8E8E93", "Other": "#C7C7CC",
           "Free": "#ECECF0"}

# -- the preview viewer (Space) is dark, like Quick Look ---------------------------------------------------------------------
VIEWER_BG, VIEWER_TEXT, VIEWER_TEXT_2 = "#1C1C1E", "#F2F2F7", "#A1A1AA"
VIEWER_PANEL, VIEWER_ERROR, VIEWER_BUTTON = "#2C2C2E", "#FF6B6B", "#0A84FF"


def font_family(default: str) -> str:
    """The system font: San Francisco on a Mac (Tk's default font there), Segoe UI on Windows."""
    if sys.platform == "win32":
        return "Segoe UI"
    return default
