"""Turn a front-view picture of an outfit (a figure standing on a plain background, arms a little out) into
a full outfit wrap for the Forge's wrap bodies.

    python character_kit/wraps/wrap_from_front.py picture.png out.png [--body m|f]

How it works: the figure is measured (floor, crotch, base of the neck, centre line, each arm's line), which
fixes how the picture lines up with the wrap body. Every pixel of the wrap is then a point on the body
(from assets/models/wrap_layouts.npz, written by the model build) and takes its colour from the picture:
the torso and legs straight on from the front, the arms along the picture's arms, the sides from the
figure's edges, and the back from a smoothed copy of the front (so logos and stripes don't show through
to the back). The bare mannequin (head, neck, arms, hands) is found by its colour, starting from the head
and the hands, and comes out transparent, so the character's own skin shows there."""
import argparse
import os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAYOUTS = os.path.join(ROOT, "assets", "models", "wrap_layouts.npz")
WRAP_SIZE = (4096, 2048)
# Heights on the wrap bodies the picture is pinned to (metres): floor, crotch, base of the neck.
Z_CROTCH, Z_NECK = .80, 1.47
LEG_X = .085                          # the body's legs are centred this far either side
ARM_TOP, ARM_WRIST = 1.40, .935       # the body's arm runs from the shoulder down to the wrist
WRIST_FRACTION = .69                  # wrist, as a fraction of shoulder → fingertip in the picture


def load_layouts(first="m"):
    d = np.load(LAYOUTS)
    order = ("m", "f") if first == "m" else ("f", "m")
    return [dict(uv=d[f"body_wrap_{b}_uv"], pos=d[f"body_wrap_{b}_pos"], tag=d[f"body_wrap_{b}_tag"]) for b in order]


def runs(row, gap=8):
    """Start/end columns of each stretch of True in a 1D mask; stretches closer than gap pixels are joined
    (seams and stitching that happen to match the background don't split a garment)."""
    r = np.concatenate([[0], row.astype(np.int8), [0]])
    d = np.diff(r)
    out = []
    for x0, x1 in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0] - 1):
        if out and x0 - out[-1][1] <= gap:
            out[-1] = (out[-1][0], x1)
        else:
            out.append((x0, x1))
    return out


def grow(seed, allowed, step=1):
    """Flood-fill seed through allowed (8-connected)."""
    m = seed & allowed
    while True:
        g = m.copy()
        g[1:] |= m[:-1]; g[:-1] |= m[1:]; g[:, 1:] |= m[:, :-1]; g[:, :-1] |= m[:, 1:]
        g[1:, 1:] |= m[:-1, :-1]; g[:-1, :-1] |= m[1:, 1:]; g[1:, :-1] |= m[:-1, 1:]; g[:-1, 1:] |= m[1:, :-1]
        g &= allowed
        if (g == m).all():
            return m
        m = g


def fill_out(rgba, known, steps):
    """Spread known pixels' values into the unknown ones around them (a few pixels per step)."""
    rgba = rgba.copy(); known = known.copy()
    for _ in range(steps):
        acc = np.zeros_like(rgba); n = np.zeros(known.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(rgba, (dy, dx), (0, 1)) * k[..., None]; n += k
        new = ~known & (n > 0)
        if not new.any():
            break
        rgba[new] = (acc[new] / n[new][:, None]).astype(rgba.dtype)
        known |= new
    return rgba


class Figure:
    """The measurements of the figure in a front-view picture."""

    def __init__(self, img):
        a = np.asarray(img.convert("RGB")).astype(float)
        self.H, self.W = a.shape[:2]
        border = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
        bg = np.median(border, 0)
        fg = np.abs(a - bg).sum(2) > 24
        # Drop specks: keep only rows/cols belonging to the figure's bounding stretch
        ys = np.nonzero(fg.sum(1) > 2)[0]
        self.top, self.floor = ys[0], ys[-1]
        head = fg[self.top:self.top + max(8, (self.floor - self.top) // 25)]
        self.cx = float(np.mean(np.nonzero(head)[1]))
        c = int(round(self.cx))

        def central(y):
            for x0, x1 in runs(fg[y]):
                if x0 <= c <= x1:
                    return x0, x1
            return None
        self.central = central
        # Neck: the narrowest row under the head; its base: where the figure first widens past 2.2x that.
        span = self.floor - self.top
        widths = [(central(y)[1] - central(y)[0]) if central(y) else 10 ** 6 for y in range(self.top + span // 20, self.top + span // 4)]
        yn = self.top + span // 20 + int(np.argmin(widths)); wn = min(widths)
        y = yn
        while y < self.floor and central(y) and central(y)[1] - central(y)[0] < 2.2 * wn:
            y += 1
        self.neck = y
        # Crotch: going up from the floor, the first row where the centre column is the figure again.
        y = self.floor - span // 8
        while y > self.neck and not fg[y, c - 2:c + 3].all():
            y -= 1
        self.crotch = y
        self.s = (self.crotch - self.neck) / (Z_NECK - Z_CROTCH)        # pixels per metre (torso)
        self.fg = fg

        # Legs: per row below the crotch, the run either side of the centre nearest it.
        self.leg = {}
        hips = central(self.crotch - 2) or (c - .2 * self.s, c + .2 * self.s)
        lo, hi = hips[0] - .06 * self.s, hips[1] + .06 * self.s           # the legs stay under the hips (hands don't count)
        for y in range(self.crotch, self.floor + 1):
            rs = []
            for x0, x1 in runs(fg[y]):
                if x1 < lo or x0 > hi:
                    continue
                rs += [(x0, c - 1), (c + 1, x1)] if x0 < c < x1 else [(x0, x1)]   # legs still touching: split down the middle
            left = [r for r in rs if r[1] < c]; right = [r for r in rs if r[0] > c]
            self.leg[y] = (max(left, key=lambda r: r[1]) if left else None, min(right, key=lambda r: r[0]) if right else None)

        # The same as tables over rows, for sampling many points at once (NaN where there's nothing).
        self.cen = np.full((self.H, 2), np.nan); self.legs = np.full((self.H, 2, 2), np.nan)
        for y in range(self.top, self.floor + 1):
            cr = central(y)
            if cr:
                self.cen[y] = cr
            for k, run in enumerate(self.leg.get(y, (None, None))):
                if run:
                    self.legs[y, k] = run

        # Arms: rows where the outermost run on a side stands apart from the torso.
        self.arm = {}
        for sg in (-1, 1):
            rows = {}
            for y in range(self.neck, self.crotch + (self.floor - self.crotch) // 3):
                rs = runs(fg[y]); cr = central(y)
                if cr is None or len(rs) < 2:
                    continue
                out = [r for r in rs if (r[1] < cr[0] if sg < 0 else r[0] > cr[1])]
                if out:
                    rows[y] = min(out, key=lambda r: r[0]) if sg < 0 else max(out, key=lambda r: r[1])
            ys_ = sorted(rows)
            if len(ys_) < 20:
                self.arm[sg] = None
                continue
            pit, tip = ys_[0], ys_[-1]
            fit = [y for y in ys_ if y < pit + .6 * (tip - pit)]
            m, b = np.polyfit(fit, [(rows[y][0] + rows[y][1]) / 2 for y in fit], 1)
            ysh = self.row(ARM_TOP)
            self.arm[sg] = dict(m=m, b=b, shoulder=ysh, wrist=ysh + WRIST_FRACTION * (tip - ysh), rows=rows)

        # Bare mannequin: its colour from the head, grown from the head and the hands through like colours.
        hd = a[self.top + 2:yn][fg[self.top + 2:yn]]
        ref = np.median(hd, 0)
        lum = a.mean(2); rl = ref.mean()
        chroma = np.abs(a / np.maximum(lum, 1)[..., None] - ref / rl).max(2)
        like = fg & (chroma < .045) & (lum > .45 * rl)
        seed = np.zeros_like(fg); seed[self.top:yn] = True
        for sg in (-1, 1):
            if self.arm[sg]:
                for y, (x0, x1) in self.arm[sg]["rows"].items():
                    if y > self.arm[sg]["wrist"]:
                        seed[y, x0:x1 + 1] = True
        self.skin = grow(seed, like)

        # The picture as RGBA (skin transparent), spread past the figure's outline so edge samples stay clean,
        # and a smoothed copy for the back.
        rgba = np.concatenate([a / 255, (~self.skin)[..., None].astype(float)], 2)
        cloth = fg & ~self.skin
        self.front = fill_out(rgba, fg, 40)
        self.front[..., 3] = fill_out(rgba, fg, 40)[..., 3] > .5
        # The back: each pixel the median of the cloth around it (+-25 cm across, +-12 cm up and down), worked
        # at an eighth of the size. A median keeps straight edges (hems, waistbands) where they are, while
        # stripes and logos are a minority of the window, so they drop out.
        q = 8
        sa = np.asarray(Image.fromarray(a.astype(np.uint8)).resize((self.W // q, self.H // q), Image.BOX)).astype(float) / 255
        sc = np.asarray(Image.fromarray(cloth.astype(np.uint8) * 255).resize((self.W // q, self.H // q), Image.BOX)) > 160
        half = max(2, int(.25 * self.s / q)); vh = max(1, int(.12 * self.s / q)); hs, ws = sc.shape
        sb = sa.copy()
        for yy in range(hs):
            y0, y1 = max(0, yy - vh), min(hs, yy + vh + 1)
            cols = np.nonzero(sc[yy])[0]
            for xx in cols:
                win = sa[y0:y1, max(0, xx - half):xx + half + 1][sc[y0:y1, max(0, xx - half):xx + half + 1]]
                sb[yy, xx] = np.median(win, 0)
        back = np.asarray(Image.fromarray((sb * 255).astype(np.uint8)).resize((self.W, self.H), Image.BILINEAR)).astype(float) / 255
        b4 = np.concatenate([np.where(cloth[..., None], back, 0), cloth[..., None].astype(float)], 2)
        bfill = fill_out(b4, cloth, 40)
        self.back = self.front.copy()
        self.back[..., :3] = np.where(cloth[..., None], bfill[..., :3], self.front[..., :3])

    def row(self, z):
        zs = [0, Z_CROTCH, Z_NECK]
        ps = [self.floor, self.crotch, self.neck]
        z = np.asarray(z, float)
        lo = np.interp(z, zs, ps)
        return np.where(z > Z_NECK, self.neck - (z - Z_NECK) * self.s, lo)

    def locate(self, x, y, z, tag):
        """Picture (column, row) for body points."""
        r = self.row(z)
        ri = np.clip(np.round(r).astype(int), 0, self.H - 1)
        if tag == "arm":
            sg = np.where(x > 0, 1, -1)
            px = np.empty(len(x)); py = np.empty(len(x))
            for s in (-1, 1):
                k = sg == s; arm = self.arm.get(s)
                if not k.any():
                    continue
                if arm is None:                         # no arm found that side: straight on, like the torso
                    px[k] = self.cx + x[k] * self.s; py[k] = r[k]; continue
                t = (ARM_TOP - z[k]) / (ARM_TOP - ARM_WRIST)
                xm = s * (.19 + (.245 - .19) * t)          # the body's arm centre line at that height (near enough)
                py[k] = arm["shoulder"] + t * (arm["wrist"] - arm["shoulder"])
                px[k] = arm["m"] * py[k] + arm["b"] + (x[k] - xm) * self.s
            return px, py
        px = self.cx + x * self.s
        if tag in ("legs", "feet"):
            run = self.legs[ri, (x > 0).astype(int)]                       # that leg's stretch in its row
            ok = (z < Z_CROTCH) & ~np.isnan(run[:, 0])
            cen = run[:, :].mean(1)
            leg_px = np.clip(cen + (x - np.sign(x) * LEG_X) * self.s, run[:, 0] + 1, run[:, 1] - 1)
            px = np.where(ok, leg_px, px)
        body = np.ones(len(x), bool) if tag == "torso" else (z >= Z_CROTCH) if tag == "legs" else np.zeros(len(x), bool)
        cr = self.cen[ri]
        ok = body & ~np.isnan(cr[:, 0])
        px = np.where(ok, np.clip(px, cr[:, 0] + 1, cr[:, 1] - 1), px)
        return px, r

    def paint(self, x, y, z, tag):
        px, py = self.locate(x, y, z, tag)
        xi = np.clip(np.round(px).astype(int), 0, self.W - 1)
        yi = np.clip(np.round(py).astype(int), 0, self.H - 1)
        if tag == "arm":
            backside = y > .0
        else:
            backside = y > 0
        out = np.where(backside[:, None], self.back[yi, xi], self.front[yi, xi])
        return out


def raster(tri_uv, size):
    W, H = size
    for i, t in enumerate(tri_uv * (W, H)):
        x0, y0 = np.maximum(np.floor(t.min(0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(t.max(0)).astype(int), (W - 1, H - 1))
        if x1 < x0 or y1 < y0:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        (ax, ay), (bx, by), (cx, cy) = t
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        l1 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
        l2 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
        l3 = 1 - l1 - l2
        inside = (l1 >= -.02) & (l2 >= -.02) & (l3 >= -.02)
        if inside.any():
            yield i, (Y[inside] - .5).astype(int), (X[inside] - .5).astype(int), np.stack([l1[inside], l2[inside], l3[inside]], 1)


def convert(img, body="m", bleed=24):
    """A front-view outfit picture → the wrap (RGBA PIL image, 4096 x 2048)."""
    fig = Figure(img)
    W, H = WRAP_SIZE
    out = np.zeros((H, W, 4), np.float32); covered = np.zeros((H, W), bool)
    for lay in load_layouts(body):
        for tag in np.unique(lay["tag"]):
            hits = []; sel = lay["tag"] == tag; pos = lay["pos"][sel]
            for i, rows, cols, bary in raster(lay["uv"][sel], WRAP_SIZE):
                new = ~covered[rows, cols]
                if new.any():
                    hits.append((rows[new], cols[new], bary[new] @ pos[i]))
            if hits:
                rows = np.concatenate([h[0] for h in hits]); cols = np.concatenate([h[1] for h in hits]); p = np.concatenate([h[2] for h in hits])
                out[rows, cols] = fig.paint(p[:, 0], p[:, 1], p[:, 2], tag)
        for i, rows, cols, _ in raster(lay["uv"], WRAP_SIZE):
            covered[rows, cols] = True
    out = fill_out(out, covered, bleed)
    out[~covered & (out[..., 3] == 0)] = 0
    img = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGBA")
    return img.transpose(Image.FLIP_TOP_BOTTOM)          # UV v runs up; image rows run down


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("picture"); ap.add_argument("out")
    ap.add_argument("--body", choices=("m", "f"), default="m", help="the body the picture shows (fitted first)")
    ap.add_argument("--debug", help="save the picture with what was found marked on it")
    a = ap.parse_args()
    img = Image.open(a.picture)
    if a.debug:
        fig = Figure(img)
        d = np.asarray(img.convert("RGB")).copy()
        d[fig.skin] = (d[fig.skin] * .4 + np.array([255, 0, 255]) * .6).astype(np.uint8)
        for yy, col in ((fig.neck, (255, 0, 0)), (fig.crotch, (0, 255, 0)), (fig.floor, (0, 0, 255))):
            d[yy - 1:yy + 2] = col
        for sg, arm in fig.arm.items():
            if arm:
                for yy in (arm["shoulder"], arm["wrist"]):
                    xx = int(arm["m"] * yy + arm["b"]); yy = int(yy)
                    d[yy - 4:yy + 5, xx - 4:xx + 5] = (255, 255, 0)
        Image.fromarray(d).save(a.debug)
        print("neck", fig.neck, "crotch", fig.crotch, "floor", fig.floor, "px/m", round(fig.s))
    convert(img, a.body).save(a.out, optimize=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
