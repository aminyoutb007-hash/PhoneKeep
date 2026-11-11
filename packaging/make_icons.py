"""Draws the PhoneKeep app icon (icon.png for Mac, icon.ico for Windows). Run before building."""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S, GREEN = 1024, (0, 128, 105)
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=GREEN)
d.rounded_rectangle([330, 170, 694, 854], radius=70, outline="white", width=44)   # phone
d.rounded_rectangle([450, 215, 574, 245], radius=15, fill="white")                # speaker
d.rounded_rectangle([392, 500, 632, 700], radius=34, fill="white")                # lock body
d.arc([432, 380, 592, 560], start=180, end=360, fill="white", width=40)           # shackle
d.line([432, 470, 432, 505], fill="white", width=40)
d.line([592, 470, 592, 505], fill="white", width=40)
d.ellipse([491, 560, 533, 602], fill=GREEN)                                       # keyhole
d.rectangle([503, 590, 521, 650], fill=GREEN)
im.save(HERE / "icon.png")
im.save(HERE / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icons written")
