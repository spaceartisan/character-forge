"""Zoom into a reference sheet with a labelled pixel grid, to read off pupil and mouth positions.

    python character_kit/faces/grid.py <sheet name> <x> <y> [half=100] [step=10]

<x>, <y> is roughly the middle of the face in sheet pixels. Writes character_kit/faces/grid_<sheet>_<x>_<y>.png
(scaled up 4x). Red lines every 5 steps, each labelled with its sheet coordinate, so you can read
pupil and lip-line positions straight off it. Delete the grid images when you're done.
"""
import pathlib, sys
from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
sheet, x, y = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
half = int(sys.argv[4]) if len(sys.argv) > 4 else 100
step = int(sys.argv[5]) if len(sys.argv) > 5 else 10
Z = 4
im = Image.open(HERE / "references" / f"{sheet}.png").convert("RGB").crop((x - half, y - half, x + half, y + half))
im = im.resize((im.width * Z, im.height * Z), Image.LANCZOS)
d = ImageDraw.Draw(im)
for i in range(0, 2 * half + 1, step):
    major = (i // step) % 5 == 0
    col = (255, 0, 0) if major else (0, 200, 255)
    d.line([(i * Z, 0), (i * Z, im.height)], fill=col, width=2 if major else 1)
    d.line([(0, i * Z), (im.width, i * Z)], fill=col, width=2 if major else 1)
    if major:
        d.text((i * Z + 3, 3), str(x - half + i), fill=(255, 255, 0))
        d.text((3, i * Z + 3), str(y - half + i), fill=(255, 255, 0))
out = HERE / f"grid_{sheet}_{x}_{y}.png"
im.save(out)
print(out)
