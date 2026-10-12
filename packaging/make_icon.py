"""Writes packaging/atelier.ico (blue rounded square + white A). Needs Pillow."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("atelier.ico"))
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=56, fill=(37, 99, 235, 255))
try:
    font = ImageFont.load_default(size=170)
except TypeError:
    font = ImageFont.load_default()
d.text((S / 2, S / 2 + 6), "A", fill="white", font=font, anchor="mm")
img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
