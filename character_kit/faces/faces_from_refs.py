"""Face textures from the painted reference sheets in character_kit/faces/references/.

Each sheet is a front view (left half) and a profile (right half). The front view is warped so its
pupils and mouth land where blender/blender_people.py's head has them in the face texture
(512 px spans 24 cm, centred 1.665 m up), the white background is filled from the surrounding
skin and hair, and the result is written to assets/textures/face_<name>.png.

    python character_kit/faces/faces_from_refs.py      (character_kit/build.py runs it)
Prints each face's cheek and hair colour for FACE_SKIN / FACE_HAIR in scripts/world/character.gd.
"""
import pathlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent          # the game
px = lambda x: 256 + x * 2133
py = lambda z: 256 - (z - 1.665) * 2133
# Where the head's pupils and lip line sit in the texture.
TARGET = [(px(-.033), py(1.6775)), (px(.033), py(1.6775)), (256, py(1.6065))]
# name: (sheet, front-view box in the sheet, pupils left/right and lip-line centre), picked by eye.
# The box keeps out the profile, panel frames and the shirt.
SHEET1 = (0, 0, 768, 1024)
REFS = {
    "m1": ("m1", SHEET1, [(275, 362), (462, 362), (375, 570)]),
    "m2": ("m2", SHEET1, [(282, 366), (467, 365), (375, 575)]),
    "f1": ("f1", SHEET1, [(281, 381), (470, 380), (377, 566)]),
    "f2": ("f2", SHEET1, [(282, 382), (470, 381), (375, 575)]),
    "m3": ("sheet2", (10, 50, 390, 388), [(161, 211), (255, 211), (210, 302)]),
    "m4": ("sheet2", (775, 50, 1155, 388), [(924, 206), (1020, 205), (974, 302)]),
    "f3": ("sheet2", (10, 555, 395, 895), [(167, 736), (259, 736), (212, 825)]),
    "f4": ("sheet2", (775, 555, 1155, 895), [(921, 714), (1017, 714), (970, 808)]),
    # Studio sheets: plain grey or black backdrop, given as the last entry. Painted sunglasses
    # stand in for pupils (lens centres).
    "fed": ("sheet3", (0, 0, 345, 190), [(167, 95), (225, 95), (195, 148)], (84, 85, 87)),
    "f5": ("sheet3", (655, 0, 985, 182), [(817, 90), (867, 90), (845, 137)], (84, 85, 87)),
    "m5": ("sheet3", (0, 300, 345, 480), [(162, 382), (212, 382), (187, 435)], (84, 85, 87), 22),   # grey beard: tighter match
    "f6": ("sheet3", (655, 300, 985, 490), [(810, 393), (863, 393), (838, 447)], (84, 85, 87)),
    "m6": ("sheet3", (0, 600, 345, 780), [(175, 687), (223, 687), (200, 735)], (84, 85, 87)),
    "f7": ("sheet3", (655, 600, 985, 800), [(810, 703), (863, 703), (837, 753)], (84, 85, 87)),
    "f8": ("sheet3", (0, 900, 345, 1095), [(172, 1002), (222, 1002), (197, 1050)], (84, 85, 87)),
    "m7": ("sheet3", (655, 900, 985, 1085), [(817, 975), (870, 976), (840, 1028)], (84, 85, 87)),
    "agent": ("agent", (0, 262, 505, 545), [(185, 325), (324, 325), (265, 447)], (22, 22, 24)),
}
# Points sampled for the colour report (texture px): cheek and the hair above the temple.
CHEEK, HAIR = (150, 300), (60, 40)


def affine(dst, src):
    """Coefficients mapping output (dst) pixels to input (src) pixels, as PIL wants."""
    a = np.array([[x, y, 1] for x, y in dst], float)
    cx = np.linalg.solve(a, [p[0] for p in src])
    cy = np.linalg.solve(a, [p[1] for p in src])
    return (*cx, *cy)


def push_pull(img, w):
    """Fill pixels where weight w is 0 from their surroundings."""
    if min(w.shape) <= 1:
        tot = w.sum()
        return np.broadcast_to((img * w[..., None]).sum((0, 1)) / max(tot, 1e-6), img.shape).copy()
    h2, w2 = (img.shape[0] + 1) // 2, (img.shape[1] + 1) // 2
    pi = np.zeros((h2 * 2, w2 * 2, 3)); pi[:img.shape[0], :img.shape[1]] = img * w[..., None]
    pw = np.zeros((h2 * 2, w2 * 2)); pw[:w.shape[0], :w.shape[1]] = w
    si = pi.reshape(h2, 2, w2, 2, 3).sum((1, 3)); sw = pw.reshape(h2, 2, w2, 2).sum((1, 3))
    small = push_pull(si / np.maximum(sw, 1e-6)[..., None], np.minimum(sw, 1))
    up = small.repeat(2, 0).repeat(2, 1)[:img.shape[0], :img.shape[1]]
    up = np.asarray(Image.fromarray(np.clip(up, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)), float)
    return img * w[..., None] + up * (1 - w[..., None])


def build(name, sheet, box, pts, backdrop=(255, 255, 255), tol=38):
    src = Image.open(HERE / "references" / f"{sheet}.png").convert("RGB")
    front = Image.new("RGB", src.size, backdrop)
    front.paste(src.crop(box), box[:2])
    out = front.transform((512, 512), Image.AFFINE, affine(TARGET, pts), Image.BICUBIC, fillcolor=backdrop)
    a = np.asarray(out, float)
    lum, sat = a.mean(2), a.max(2) - a.min(2)
    if backdrop == (255, 255, 255):
        # Paper-white background, plus a margin so the light fringe around hair strands goes too.
        bg = (lum > 195) & (sat < 45)
    else:
        # Studio backdrop: backdrop-coloured pixels joined to the edge (dark hair inside stays).
        near = (np.abs(lum - np.mean(backdrop)) < tol) & (sat < 18)   # the backdrop is vignetted
        m = Image.fromarray(np.where(near, 255, 0).astype(np.uint8))
        m = Image.fromarray(np.pad(np.asarray(m), 1, constant_values=255)).copy()   # an array-backed image ignores floodfill
        ImageDraw.floodfill(m, (0, 0), 128)
        bg = np.asarray(m)[1:-1, 1:-1] == 128
    keep = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8)).filter(ImageFilter.MinFilter(11)).filter(ImageFilter.GaussianBlur(2))
    w = np.asarray(keep, float) / 255
    filled = push_pull(a, w)
    res = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8))
    (ROOT / "assets/textures").mkdir(parents=True, exist_ok=True)
    res.save(ROOT / "assets/textures" / f"face_{name}.png")
    c, h = res.getpixel(CHEEK), res.getpixel(HAIR)
    f = lambda col: "Color(%.2f, %.2f, %.2f)" % tuple(v / 255 for v in col)
    print(f"{name}: skin {f(c)}  hair {f(h)}")


if __name__ == "__main__":
    for name, ref in REFS.items():
        build(name, *ref)
