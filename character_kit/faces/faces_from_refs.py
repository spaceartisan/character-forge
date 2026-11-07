"""Face textures from the painted reference sheets in character_kit/faces/references/.

Each sheet has a front view and, to its right, a profile. The texture is baked onto the head's own
UV layout (blender/blender_people.py face_uv: 1024 px square, 2133 px per metre, the face a straight-on
portrait in the middle, sides and back wrapped round it, crown unwrapped over the top):

  1. Every texel is traced back to the point on the head it covers, with that point's normal
     (rasterised from the person_m face surface in assets/models/human.glb).
  2. Front-facing points take their colour from the front view, warped so its pupils and lip line
     land on the head's. Side-facing points (ears, temples, jaw, the hair at the sides) take it from
     the profile, scaled to match and aligned on the nose tip. Points in between blend the two.
  3. Whatever neither view shows well (the back and top of the head, under the chin, the neck below
     the collar line) is filled smoothly from its surroundings, as is the backdrop.

The old process projected the front view only, straight on, and clamped the crown, the neck and
everything behind the ears to single rows of pixels: the face was fine, everything else stretched.

    python character_kit/faces/faces_from_refs.py      (character_kit/build.py runs it)
"""
import json
import os
import pathlib
import struct

import numpy as np
from PIL import Image, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TEX = 1024                       # texture size (px)
PPM = 2133.0                     # pixels per metre, as in face_uv
# Old 512 portrait space, still used to place the front view: x, z (metres) -> pixels.
px = lambda x: 256 + x * PPM
py = lambda z: 256 - (z - 1.665) * PPM
# Where the head's pupils and lip line sit, in that portrait space.
TARGET = [(px(-.033), py(1.6775)), (px(.033), py(1.6775)), (256, py(1.6065))]
EYE_Z, NOSE_Z, NOSE_Y = 1.6775, 1.639, -.104      # head landmarks (blender_people.head_field), -Y is forward
COLLAR = (1.52, 1.565)          # below this the views show shirts: fade out and fill with neck skin
COLLAR_BACK = .045              # shirt collars sit higher at the back of the neck
SHIRT_Z = 1.625                 # below this, near-white low-colour pixels are shirt, not skin
FACE_OVAL = (1.64, .05, .06)    # centre z, half width, half height (m): the inner face, never backdrop
# Sheets whose crown is under a hat: above this height everything is hat, so paint short hair instead.
HATS = {"agent": (1.695, (14, 12, 12))}

# name: (sheet, front-view box, pupils left/right and lip-line centre[, backdrop[, tolerance]]).
# Front points picked by eye; the box keeps out the profile, panel frames and the shirt.
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
# Profile boxes (the side view, facing right, beside each front view). The profile is scaled like the
# front view, its eye line put level with the front's, and aligned on the nose tip, found automatically.
PROFILES = {
    "m1": (768, 0, 1536, 1024), "m2": (768, 0, 1536, 1024), "f1": (768, 0, 1536, 1024), "f2": (768, 0, 1536, 1024),
    "m3": (390, 50, 765, 388), "m4": (1155, 50, 1530, 388), "f3": (395, 555, 765, 895), "f4": (1155, 555, 1530, 895),
    "fed": (345, 0, 650, 190), "f5": (985, 0, 1312, 182), "m5": (345, 300, 650, 480), "f6": (985, 300, 1312, 490),
    "m6": (345, 600, 650, 780), "f7": (985, 600, 1312, 800), "f8": (345, 900, 650, 1095), "m7": (985, 900, 1312, 1085),
    "agent": (1024, 262, 1536, 545),
}
# Texel positions (new layout) sampled for colour reports: a cheek, and hair above the forehead.
CHEEK, HAIR = (406, 557), (512, 205)


# ------------------------------------------------------------------ the head, texel by texel
_HEAD = None


def head_map():
    """(points Hx Wx3, normals Hx Wx3, covered HxW) for every texel, in Blender axes (+Z up, -Y front)."""
    global _HEAD
    glb = pathlib.Path(os.environ.get("FORGE_HEAD_GLB") or ROOT / "assets" / "models" / "human.glb")
    stamp = glb.stat().st_mtime
    if _HEAD and _HEAD[0] == stamp:
        return _HEAD[1]
    b = glb.read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    o = 20 + n
    blob = b[o + 8:o + 8 + struct.unpack("<I", b[o:o + 4])[0]]

    def acc(i):
        a = j["accessors"][i]
        v = j["bufferViews"][a["bufferView"]]
        dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}[a["componentType"]]
        nc = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        return np.frombuffer(blob, dtype=dt, count=a["count"] * nc, offset=start).reshape(a["count"], nc)

    mats = [m["name"] for m in j["materials"]]
    mesh = next(m for m in j["meshes"] if m["name"] == "person_m")
    prim = next(p for p in mesh["primitives"] if mats[p["material"]] == "face")
    g = acc(prim["attributes"]["POSITION"]).astype(float)
    gn = acc(prim["attributes"]["NORMAL"]).astype(float)
    uv = acc(prim["attributes"]["TEXCOORD_0"]).astype(float)
    tri = acc(prim["indices"]).reshape(-1, 3).astype(int)
    pos = np.stack([g[:, 0], -g[:, 2], g[:, 1]], 1)      # glTF (Y up, +Z front) -> Blender
    nrm = np.stack([gn[:, 0], -gn[:, 2], gn[:, 1]], 1)
    P = np.zeros((TEX, TEX, 3)); N = np.zeros((TEX, TEX, 3)); cover = np.zeros((TEX, TEX), bool)
    pix = uv * TEX - .5                                   # glTF v already runs top to bottom
    for t in tri:
        q = pix[t]
        x0, x1 = int(np.floor(q[:, 0].min())), int(np.ceil(q[:, 0].max()))
        y0, y1 = int(np.floor(q[:, 1].min())), int(np.ceil(q[:, 1].max()))
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        (ax, ay), (bx, by), (cx, cy) = q
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / den
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / den
        l3 = 1 - l1 - l2
        inside = (l1 >= -.02) & (l2 >= -.02) & (l3 >= -.02)   # a hair generous, so islands have no cracks
        if not inside.any():
            continue
        X, Y = xs[inside] % TEX, ys[inside]
        ok = (Y >= 0) & (Y < TEX)
        L = np.stack([l1[inside], l2[inside], l3[inside]], 1)[ok]
        X, Y = X[ok], Y[ok]
        P[Y, X] = L @ pos[t]
        N[Y, X] = L @ nrm[t]
        cover[Y, X] = True
    N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-9)
    _HEAD = (stamp, (P, N, cover))
    return _HEAD[1]


# ------------------------------------------------------------------ image helpers
def affine(dst, src):
    """Coefficients mapping output (dst) pixels to input (src) pixels."""
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


def subject_mask(crop, backdrop, tol):
    """1 on the person, 0 on the backdrop, for a crop of a sheet (float HxW)."""
    a = np.asarray(crop, float)
    lum, sat = a.mean(2), a.max(2) - a.min(2)
    if backdrop == (255, 255, 255):
        # Paper-white background, plus a margin so the light fringe around hair strands goes too.
        bg = (lum > 195) & (sat < 45)
    else:
        # Studio backdrop: backdrop-coloured pixels joined to the crop's edge (dark hair inside stays).
        near = (np.abs(lum - np.mean(backdrop)) < tol) & (sat < 18)   # the backdrop is vignetted
        bg = np.zeros_like(near)
        bg[0, :], bg[-1, :], bg[:, 0], bg[:, -1] = near[0, :], near[-1, :], near[:, 0], near[:, -1]
        while True:
            grown = bg.copy()
            grown[1:] |= bg[:-1]; grown[:-1] |= bg[1:]; grown[:, 1:] |= bg[:, :-1]; grown[:, :-1] |= bg[:, 1:]
            grown &= near
            if (grown == bg).all():
                break
            bg = grown
    keep = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8)).filter(ImageFilter.MinFilter(7)).filter(ImageFilter.GaussianBlur(1.5))
    return np.asarray(keep, float) / 255


def sample(img, mask, sx, sy):
    """Bilinear colour and mask at float source pixel positions; outside the image the mask is 0."""
    h, w = mask.shape
    x0 = np.floor(sx).astype(int); y0 = np.floor(sy).astype(int)
    fx = (sx - x0)[..., None]; fy = (sy - y0)[..., None]
    inside = (x0 >= 0) & (y0 >= 0) & (x0 < w - 1) & (y0 < h - 1)
    x0 = np.clip(x0, 0, w - 2); y0 = np.clip(y0, 0, h - 2)
    def at(arr, yy, xx):
        return arr[yy, xx]
    c = (at(img, y0, x0) * (1 - fx) * (1 - fy) + at(img, y0, x0 + 1) * fx * (1 - fy)
         + at(img, y0 + 1, x0) * (1 - fx) * fy + at(img, y0 + 1, x0 + 1) * fx * fy)
    m2 = mask[..., None]
    m = (at(m2, y0, x0) * (1 - fx) * (1 - fy) + at(m2, y0, x0 + 1) * fx * (1 - fy)
         + at(m2, y0 + 1, x0) * (1 - fx) * fy + at(m2, y0 + 1, x0 + 1) * fx * fy)[..., 0]
    return c, m * inside


def find_profile(src, box, backdrop, tol, scale, eye_row):
    """Nose-tip column of a right-facing profile in box, at the height the front view's scale gives."""
    crop = src.crop(box)
    mask = subject_mask(crop, backdrop, tol) > .5
    row = int(round(eye_row + (EYE_Z - NOSE_Z) * scale)) - box[1]
    band = max(2, int(.006 * scale))
    rows = mask[max(0, row - band):row + band + 1]
    cols = np.nonzero(rows.any(0))[0]
    if not len(cols):
        raise ValueError("No profile found beside the front view")
    return box[0] + cols.max()


# ------------------------------------------------------------------ the bake
def blur_norm(c, w, r):
    """Weighted Gaussian blur of colour c (HxWx3) by weights w: the local weighted mean."""
    def box(a, ax):
        # Running-sum box filter; wraps round in u (the texture's seam), clamps in v.
        k = 2 * r + 1
        pad = [(0, 0)] * a.ndim; pad[ax] = (r + 1, r)
        a = np.pad(a, pad, mode="wrap" if ax == 1 else "edge")
        c = np.cumsum(a, ax)
        return (np.take(c, range(k, c.shape[ax]), ax) - np.take(c, range(0, c.shape[ax] - k), ax)) / k

    def g(a):
        for _ in range(3):                       # three box passes ~ a Gaussian
            a = box(box(a, 0), 1)
        return a
    sw = g(w)
    return np.stack([g(c[..., i] * w) for i in range(3)], 2) / np.maximum(sw, 1e-6)[..., None], sw


def bake(src, box, pts, backdrop=(255, 255, 255), tol=38, profile=None, hat=None):
    """Face texture (TEX x TEX RGB uint8) for a sheet, given its front box and points, optional profile box."""
    P, N, cover = head_map()
    x, y, z = P[..., 0], P[..., 1], P[..., 2]
    back = np.clip((y + .02) / .07, 0, 1)
    lo = COLLAR[0] + COLLAR_BACK * back
    neck = np.clip((z - lo) / (COLLAR[1] - COLLAR[0]), 0, 1)

    # Front view: head (x, z) -> old portrait space -> sheet pixels.
    a = affine(TARGET, pts)
    X, Y = px(x), py(z)
    fx, fy = a[0] * X + a[1] * Y + a[2], a[3] * X + a[4] * Y + a[5]
    full = np.asarray(src, float)
    front_mask = np.zeros(full.shape[:2])
    front_mask[box[1]:box[3], box[0]:box[2]] = subject_mask(src.crop(box), backdrop, tol)
    cf, mf = sample(full, front_mask, fx, fy)
    # Dark sunglasses or a hat brim can join the backdrop in a studio shot; the inner face never is one.
    oval = ((x / FACE_OVAL[1]) ** 2 + ((z - FACE_OVAL[0]) / FACE_OVAL[2]) ** 2 < 1) & (N[..., 1] < -.5)
    mf = np.where(oval, 1, mf)
    views = [(cf, np.clip(-N[..., 1], 0, 1) * mf * neck * cover)]
    if profile:
        # Scale and eye line from the front view; nose tip found in the profile.
        scale = np.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]) / .066
        eye_row = (pts[0][1] + pts[1][1]) / 2
        nose_col = find_profile(src, profile, backdrop, tol, scale, eye_row)
        side_mask = np.zeros(full.shape[:2])
        side_mask[profile[1]:profile[3], profile[0]:profile[2]] = subject_mask(src.crop(profile), backdrop, tol)
        sx = nose_col + (NOSE_Y - y) * scale          # forward (-y) is to the right in the profile
        sy = eye_row - (z - EYE_Z) * scale
        cp, mp = sample(full, side_mask, sx, sy)
        views.append((cp, np.clip(np.abs(N[..., 0]), 0, 1) * mp * neck * cover))

    # A white shirt collar can reach above the collar line; keep it off the neck.
    skin = np.median(cf[oval & (np.abs(x) > .03) & (z < 1.66) & (z > 1.6)], 0)
    def shirtless(c, w):
        lum, sat = c.mean(2), c.max(2) - c.min(2)
        shirt = (z < SHIRT_Z) & (lum > skin.mean() + 35) & (sat < 30)
        return np.where(shirt, 0, w)
    views = [(c, shirtless(c, w)) for c, w in views]

    # Two-band blend: broad colour from both views with soft weights (no tone seam where they meet),
    # fine detail from whichever view faces the point best (no ghosted double features).
    lows, details, soft, sharp = [], [], [], []
    for c, w in views:
        low, _ = blur_norm(c, w ** 2, 6)
        lows.append(low); details.append(c - low)
        soft.append(w ** 2); sharp.append(w ** 12)
    sw, hw = sum(soft), sum(sharp)
    colour = sum(l * s[..., None] for l, s in zip(lows, soft)) / np.maximum(sw, 1e-9)[..., None]
    colour += sum(d * h[..., None] for d, h in zip(details, sharp)) / np.maximum(hw, 1e-12)[..., None]
    confidence = np.clip(sum(w ** 4 for _, w in views) * 6, 0, 1)
    if hat:
        z_hat, hair = hat
        crown = (z > z_hat) & cover
        colour[crown] = hair
        confidence = np.where(crown, 1, confidence)
    return np.clip(push_pull(colour, confidence * cover), 0, 255).astype(np.uint8)


def build(name, sheet, box, pts, backdrop=(255, 255, 255), tol=38, profile=None):
    """Bake one face and write assets/textures/face_<name>.png."""
    src = Image.open(HERE / "references" / f"{sheet}.png").convert("RGB")
    res = Image.fromarray(bake(src, tuple(box), pts, tuple(backdrop), tol, tuple(profile) if profile else None,
                               HATS.get(name)))
    out = ROOT / "assets" / "textures"
    out.mkdir(parents=True, exist_ok=True)
    res.save(out / f"face_{name}.png")
    f = lambda col: "#%02x%02x%02x" % col
    print(f"{name}: cheek {f(res.getpixel(CHEEK))}  hair {f(res.getpixel(HAIR))}")
    return res


def build_ref(name):
    ref = REFS[name]
    sheet, box, pts = ref[:3]
    return build(name, sheet, box, pts, *ref[3:], profile=PROFILES.get(name))


def legacy_to_new(old):
    """A face texture painted for the old 512 front-projection layout, moved into the new layout.
    Shows exactly what the old model showed (including its stretched sides), so nothing painted is lost."""
    P, _, cover = head_map()
    x, y, z = P[..., 0], P[..., 1], P[..., 2]
    u = .5 + x / .24
    front = .5 + (z - 1.665) / .24
    t = np.clip((y + .005) / .04, 0, 1); back = t * t * (3 - 2 * t)
    v = np.clip(front + (.707 - front) * back, .03, .98)
    img = np.asarray(old.convert("RGB").resize((512, 512)), float)
    c, m = sample(img, np.ones((512, 512)), u * 512 - .5, (1 - v) * 512 - .5)
    return Image.fromarray(np.clip(push_pull(c, m * cover), 0, 255).astype(np.uint8))


if __name__ == "__main__":
    for name in REFS:
        build_ref(name)
