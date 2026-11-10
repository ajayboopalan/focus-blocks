"""Draw the app icon (a progress ring like the pill's) as a multi-size .ico. Usage: python make_icon.py OUT.ico"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
BG, TRACK, RING = "#16191e", "#2e343d", "#7cc79a"


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, SIZE - 8, SIZE - 8), fill=BG)
    box, width = (52, 52, SIZE - 52, SIZE - 52), 30
    d.ellipse(box, outline=TRACK, width=width)
    d.arc(box, start=-90, end=-90 + 270, fill=RING, width=width)
    return img


def main() -> None:
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
