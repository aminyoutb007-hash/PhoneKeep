"""Draw PhoneKeep's app icons for the phone window (assets/icons/<key>.png).

An original set in today's iOS style: a rounded square with a soft two-colour gradient and one clean white
symbol, all in the same line weight. They are deliberately PhoneKeep's own drawings, not copies of Apple's or
WhatsApp's icons (those are their designs). Run:  python tools/make_app_icons.py
Each icon is drawn at 4x and scaled down, so edges are smooth at 92 px (the tile) and 28 px (the screen title).
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets" / "icons"
S = 368                      # drawing size (4 x 92)
W = (255, 255, 255, 255)
LINE = 22                    # stroke width at 4x

# key: (top colour, bottom colour)
COLOURS = {
    "photos": ("#ffb347", "#ff5e7e"),
    "messages": ("#5ac8fa", "#2f6bff"),
    "whatsapp": ("#3ddc84", "#0b9e6f"),
    "whatsappbusiness": ("#1fa58a", "#0b5c55"),
    "calls": ("#2fd3a8", "#0f8f86"),
    "contacts": ("#b8c0cc", "#6e7a8a"),
    "voicemail": ("#a58bff", "#6a3fe0"),
    "notes": ("#ffd84d", "#f5a623"),
    "calendar": ("#ff7a6b", "#e5383b"),
    "voicememos": ("#ff6f91", "#c2185b"),
    "safari": ("#4fc3ff", "#1d6fe8"),
    "music": ("#c86dd7", "#7b2ff7"),
    "books": ("#ffa94d", "#e8590c"),
    "files": ("#6ab7ff", "#2b7de9"),
    "apps": ("#7f7cff", "#4b47d6"),
    "allfiles": ("#9aa5b1", "#55606e"),
    "checkup": ("#5fd068", "#1c9b4a"),
    # the four "What do you want to keep?" choices on the main screen
    "keep_chats": ("#3ddc84", "#0b9e6f"),
    "keep_chats_photos": ("#ffb347", "#ff5e7e"),
    "keep_everything": ("#7f7cff", "#4b47d6"),
    "keep_custom": ("#9aa5b1", "#55606e"),
}


def _hex(c: str):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (255,)


def _base(top: str, bottom: str) -> Image.Image:
    a, b = _hex(top), _hex(bottom)
    grad = Image.new("RGBA", (S, S))
    px = grad.load()
    for y in range(S):
        t = y / (S - 1)
        row = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))
        for x in range(S):
            px[x, y] = row
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.225), fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    # a faint light edge at the top, as on current iOS icons
    hi = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hi).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.225), outline=60, width=4)
    hi = Image.composite(hi, Image.new("L", (S, S), 0), mask)
    out.paste(Image.new("RGBA", (S, S), (255, 255, 255, 255)), (0, 0), hi.point(lambda v: v // 2))
    return out


def _glyph() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    return g, ImageDraw.Draw(g)


def _bubble(d, box, tail="left", fill=W):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=int((y1 - y0) * 0.45), fill=fill)
    if tail == "left":
        d.polygon([(x0 + 30, y1 - 30), (x0 + 6, y1 + 26), (x0 + 74, y1 - 8)], fill=fill)
    else:
        d.polygon([(x1 - 30, y1 - 30), (x1 - 6, y1 + 26), (x1 - 74, y1 - 8)], fill=fill)


def draw(key: str) -> Image.Image:
    g, d = _glyph()
    c = S // 2
    if key == "photos":                      # a landscape: sun and two hills, in a frame
        d.rounded_rectangle((84, 104, 284, 264), radius=30, outline=W, width=LINE)
        d.ellipse((214, 132, 254, 172), fill=W)
        d.polygon([(96, 252), (160, 176), (212, 236), (240, 206), (272, 252)], fill=W)
    elif key == "messages":                  # two overlapping speech bubbles
        _bubble(d, (70, 96, 238, 212), "left")
        g2, d2 = _glyph()
        _bubble(d2, (148, 168, 298, 268), "right")
        cut = Image.new("L", (S, S), 0)
        ImageDraw.Draw(cut).rounded_rectangle((136, 156, 310, 280), radius=56, fill=255)
        g.paste((0, 0, 0, 0), (0, 0), cut)
        g.alpha_composite(g2)
    elif key in ("whatsapp", "whatsappbusiness"):   # one round bubble with three dots (not WhatsApp's mark)
        d.ellipse((76, 80, 292, 280), fill=W)
        d.polygon([(96, 230), (70, 300), (150, 268)], fill=W)
        col = _hex(COLOURS[key][1])
        for x in (128, 184, 240):
            d.ellipse((x - 16, 164, x + 16, 196), fill=col)
        if key == "whatsappbusiness":        # a small briefcase badge in a white circle
            d.ellipse((214, 206, 320, 312), fill=W)
            dark = _hex("#0b5c55")
            d.rounded_rectangle((238, 238, 296, 286), radius=10, fill=dark)
            d.rounded_rectangle((254, 224, 280, 244), radius=6, outline=dark, width=7)
            d.rectangle((238, 256, 296, 260), fill=W)
    elif key == "calls":                     # a list of recent calls: arrows in/out, and a handset badge
        for n, (y, out) in enumerate(((104, False), (172, True), (240, False))):
            x0 = 78
            if out:                          # outgoing: arrow up-right
                d.line((x0 + 8, y + 40, x0 + 44, y + 4), fill=W, width=14)
                d.polygon([(x0 + 22, y), (x0 + 50, y - 2), (x0 + 48, y + 26)], fill=W)
            else:                            # incoming: arrow down-left
                d.line((x0 + 44, y + 4, x0 + 8, y + 40), fill=W, width=14)
                d.polygon([(x0 + 2, y + 18), (x0 + 4, y + 46), (x0 + 30, y + 44)], fill=W)
            d.rounded_rectangle((x0 + 74, y + 12, 290 if n != 2 else 214, y + 34), radius=11, fill=W)
        # handset badge: white circle, handset drawn as a thick curved stroke with rounded ends
        d.ellipse((216, 216, 320, 320), fill=W)
        col = _hex(COLOURS[key][1])
        pts = []
        for k in range(41):                  # a quarter-ellipse from the ear piece to the mouth piece
            t = math.pi * (0.5 + k / 40 * 0.5)
            pts.append((268 + 30 * math.cos(t) + 6, 268 + 30 * math.sin(t) - 6))
        pts = [(x - 4, y + 4) for x, y in pts]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            d.line((x1, y1, x2, y2), fill=col, width=16)
        for (x, y) in (pts[0], pts[-1]):
            d.ellipse((x - 13, y - 13, x + 13, y + 13), fill=col)
    elif key == "contacts":                  # a person in a circle
        d.ellipse((74, 74, 294, 294), outline=W, width=LINE)
        d.ellipse((144, 110, 224, 190), fill=W)
        d.pieslice((104, 196, 264, 340), start=180, end=360, fill=W)
        m = Image.new("L", (S, S), 0)
        ImageDraw.Draw(m).ellipse((74 + LINE, 74 + LINE, 294 - LINE, 294 - LINE), fill=255)
        ring = Image.new("L", (S, S), 0)
        ImageDraw.Draw(ring).ellipse((74, 74, 294, 294), outline=255, width=LINE)
        keep = Image.composite(Image.new("L", (S, S), 255), m, ring)
        g.putalpha(Image.composite(g.getchannel("A"), Image.new("L", (S, S), 0), keep))
    elif key == "voicemail":                 # the reel symbol: two circles joined at the bottom
        d.ellipse((70, 132, 170, 232), outline=W, width=LINE)
        d.ellipse((198, 132, 298, 232), outline=W, width=LINE)
        d.line((120, 232 - LINE // 2, 248, 232 - LINE // 2), fill=W, width=LINE)
    elif key == "notes":                     # a page with lines and a folded corner
        d.polygon([(100, 72), (230, 72), (276, 118), (276, 296), (100, 296)], fill=W)
        col = _hex(COLOURS[key][1])
        d.polygon([(230, 72), (230, 118), (276, 118)], fill=_hex("#ffe9a6"))
        for y in (152, 196, 240):
            d.rounded_rectangle((128, y, 248, y + 14), radius=7, fill=col)
    elif key == "calendar":                  # a calendar page with two rings and a grid of days
        d.rounded_rectangle((76, 96, 292, 290), radius=30, fill=W)
        col = _hex(COLOURS[key][1])
        d.rectangle((76, 140, 292, 150), fill=col)
        for x in (132, 236):
            d.rounded_rectangle((x - 10, 72, x + 10, 120), radius=10, fill=W)
            d.rounded_rectangle((x - 6, 78, x + 6, 114), radius=6, fill=col)
        for r in range(3):
            for k in range(4):
                x, y = 110 + k * 46, 172 + r * 38
                d.rounded_rectangle((x, y, x + 26, y + 22), radius=6, fill=col if (r, k) != (1, 2) else _hex("#ffb4a8"))
    elif key == "voicememos":                # a sound wave
        hs = [40, 90, 150, 110, 190, 120, 70, 130, 60]
        for i, h in enumerate(hs):
            x = 84 + i * 25
            d.rounded_rectangle((x, c - h // 2, x + 14, c + h // 2), radius=7, fill=W)
    elif key == "safari":                    # a globe (the browser)
        d.ellipse((74, 74, 294, 294), outline=W, width=LINE)
        d.ellipse((136, 74, 232, 294), outline=W, width=LINE - 6)
        d.line((84, c, 284, c), fill=W, width=LINE - 6)
        d.arc((90, 40, 278, 150), start=40, end=140, fill=W, width=LINE - 8)
        d.arc((90, 218, 278, 328), start=220, end=320, fill=W, width=LINE - 8)
    elif key == "music":                     # two joined notes
        d.polygon([(150, 104), (282, 76), (282, 108), (150, 136)], fill=W)
        d.rectangle((150, 104, 170, 252), fill=W)
        d.rectangle((262, 80, 282, 224), fill=W)
        d.ellipse((92, 222, 172, 280), fill=W)
        d.ellipse((204, 194, 284, 252), fill=W)
    elif key == "books":                     # an open book
        d.polygon([(184, 112), (80, 92), (80, 266), (184, 288)], fill=W)
        d.polygon([(184, 112), (288, 92), (288, 266), (184, 288)], fill=W)
        col = _hex(COLOURS[key][1])
        d.line((184, 112, 184, 288), fill=col, width=10)
        for y in (138, 172, 206):
            d.line((104, y, 166, y + 10), fill=col, width=8)
            d.line((202, y + 10, 264, y), fill=col, width=8)
    elif key == "files":                     # a folder
        d.rounded_rectangle((72, 110, 296, 276), radius=26, fill=W)
        d.rounded_rectangle((72, 90, 170, 140), radius=20, fill=W)
        d.rectangle((72, 140, 296, 150), fill=_hex(COLOURS[key][0]))
    elif key == "apps":                      # four app squares
        for x, y in ((90, 90), (196, 90), (90, 196), (196, 196)):
            d.rounded_rectangle((x, y, x + 82, y + 82), radius=22, fill=W)
    elif key == "allfiles":                  # a stack of documents
        d.rounded_rectangle((132, 70, 268, 238), radius=18, fill=(255, 255, 255, 140))
        d.rounded_rectangle((112, 96, 248, 264), radius=18, fill=(255, 255, 255, 200))
        d.rounded_rectangle((92, 122, 228, 290), radius=18, fill=W)
        col = _hex(COLOURS[key][1])
        for y in (162, 196, 230):
            d.rounded_rectangle((116, y, 204, y + 12), radius=6, fill=col)
    elif key == "checkup":                   # a clipboard with a tick (H1)
        d.rounded_rectangle((96, 82, 272, 300), radius=26, outline=W, width=LINE)
        d.rounded_rectangle((144, 64, 224, 108), radius=14, fill=W)
        d.line([(132, 196), (172, 236), (240, 154)], fill=W, width=LINE + 6, joint="curve")
    elif key == "keep_chats":               # two speech bubbles
        _bubble(d, (70, 100, 250, 216), "left")
        _bubble(d, (150, 176, 300, 266), "right", fill=(255, 255, 255, 200))
    elif key == "keep_chats_photos":        # a photo with a speech bubble in front
        d.rounded_rectangle((70, 80, 262, 232), radius=26, outline=W, width=LINE)
        d.ellipse((190, 104, 226, 140), fill=W)
        d.polygon([(84, 220), (140, 156), (186, 206), (210, 184), (248, 220)], fill=W)
        _bubble(d, (160, 196, 304, 284), "right")
    elif key == "keep_everything":          # a phone with its app grid
        d.rounded_rectangle((116, 60, 252, 308), radius=30, outline=W, width=LINE)
        d.rounded_rectangle((164, 76, 204, 88), radius=6, fill=W)
        for r in range(3):
            for k in range(3):
                x, y = 142 + k * 32, 110 + r * 36
                d.rounded_rectangle((x, y, x + 22, y + 22), radius=6, fill=W)
        d.rounded_rectangle((162, 270, 206, 280), radius=5, fill=W)
    elif key == "keep_custom":              # three sliders
        for n, (y, kx) in enumerate(((112, 220), (184, 136), (256, 196))):
            d.rounded_rectangle((76, y - 9, 292, y + 9), radius=9, fill=(255, 255, 255, 150))
            d.ellipse((kx - 26, y - 26, kx + 26, y + 26), fill=W)
    # a soft shadow under the symbol, then the symbol
    sh = g.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: v * 0.22)
    base = _base(*COLOURS[key])
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    shadow.putalpha(sh)
    base.alpha_composite(shadow, (0, 6))
    base.alpha_composite(g)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.225), fill=255)
    base.putalpha(Image.composite(base.getchannel("A"), Image.new("L", (S, S), 0), mask))
    return base


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (8 * 100, 3 * 100), (242, 244, 247, 255))
    for n, key in enumerate(COLOURS):
        big = draw(key)
        big.resize((92, 92), Image.LANCZOS).save(OUT / f"{key}.png")
        big.resize((28, 28), Image.LANCZOS).save(OUT / f"{key}-28.png")
        big.resize((48, 48), Image.LANCZOS).save(OUT / f"{key}-48.png")
        sheet.alpha_composite(big.resize((92, 92), Image.LANCZOS), ((n % 8) * 100 + 4, (n // 8) * 100 + 4))
    sheet.save(OUT.parent / "icons-sheet.png")
    print(f"{len(COLOURS)} icons in {OUT}")


if __name__ == "__main__":
    main()
