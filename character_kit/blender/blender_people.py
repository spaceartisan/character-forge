"""Blender 5 headless: sculpts the player and townsfolk from signed distance fields and exports human.glb.
Run: python character_kit/build.py (or blender -b -P character_kit/blender/blender_people.py -- <abs path to assets/models>)

Every part is a field: a function giving the distance to its surface. Fields blend, carve and displace easily,
so joints flow into each other and details like lapels are just a raised band. Each is meshed with surface nets,
smoothed and decimated, then weighted by distance to the bones it may follow. Vertex colours hold ambient occlusion
read from the same fields. No base mesh or add-on is involved.

Blender axes: +Z up, the front of the body is -Y, x > 0 is the character's left. Metres, 1.82 tall.
The GLB holds these meshes, which Character (scripts/world/character.gd) shows and hides per person:
  person_m, person_f     head, neck, hands
  legs_m                 trousers and shoes
  legs_coat              the same from mid-thigh down, worn under the trench coat
  outfit_suit, outfit_trench, outfit_shirt, outfit_dress
  hat, hair_short, hair_long, glasses
Surfaces are named by material so Godot dresses them: face, skin, top, shirt, tie, pants, shoes, skirt, hat, band, hair, lens.
"""
import bpy, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_rig import wipe, build_skeleton, build_anims, export

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
H = 1.82


# ------------------------------------------------------------------ field tools
def smin(a, b, k):
    h = np.clip(.5 + .5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def sstep(e0, e1, v):
    t = np.clip((v - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def ell(x, y, z, c, r):
    """Ellipsoid (a good approximation of distance, exact enough to mesh)."""
    px, py, pz = (x - c[0]) / r[0], (y - c[1]) / r[1], (z - c[2]) / r[2]
    k0 = np.sqrt(px * px + py * py + pz * pz)
    k1 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
    return k0 * (k0 - 1) / np.maximum(k1, 1e-6)


def cone(x, y, z, a, b, ra, rb, flat=1.0):
    """Capsule that tapers from radius ra at a to rb at b. flat squashes it along x (hands, ties)."""
    ax, ay, az = a
    dx, dy, dz = b[0] - ax, b[1] - ay, b[2] - az
    px, py, pz = x - ax, y - ay, z - az
    t = np.clip((px * dx + py * dy + pz * dz) / (dx * dx + dy * dy + dz * dz), 0, 1)
    qx, qy, qz = (px - t * dx) / flat, py - t * dy, pz - t * dz
    return np.sqrt(qx * qx + qy * qy + qz * qz) - (ra + (rb - ra) * t)


def _spline(table):
    """A dense, smooth table from a few (z, rx, ry, cy) stations."""
    t = np.array(table, dtype=float)
    z = np.linspace(t[0, 0], t[-1, 0], 240)
    out = [z]
    for c in range(1, t.shape[1]):
        v = np.interp(z, t[:, 0], t[:, c])
        for _ in range(3):
            v = np.convolve(np.pad(v, 7, mode="edge"), np.ones(15) / 15, mode="valid")
        out.append(v)
    return out


def loft(x, y, z, table, power=2.0):
    """Stack of ellipses up the z axis; power above 2 gives a boxier section."""
    zs, rx, ry, cy = _spline(table)
    arx, ary, acy = np.interp(z, zs, rx), np.interp(z, zs, ry), np.interp(z, zs, cy)
    n = (np.abs(x / arx) ** power + np.abs((y - acy) / ary) ** power) ** (1 / power)
    side = (n - 1) * np.minimum(arx, ary)
    return np.maximum(side, np.maximum(zs[0] - z, z - zs[-1]))


def band(v, a, b, soft=.004):
    """1 between a and b, 0 elsewhere."""
    return sstep(a - soft, a + soft, v) * (1 - sstep(b - soft, b + soft, v))


# ------------------------------------------------------------------ meshing
def surface_nets(f, lo, hi, step):
    xs = np.arange(lo[0], hi[0] + step, step)
    ys = np.arange(lo[1], hi[1] + step, step)
    zs = np.arange(lo[2], hi[2] + step, step)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    V = f(X, Y, Z)
    nx, ny, nz = V.shape
    I = V < 0
    corners = [(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    edges = [(p, q) for i, p in enumerate(corners) for q in corners[i + 1:] if sum(abs(p[k] - q[k]) for k in range(3)) == 1]
    s = np.zeros((nx - 1, ny - 1, nz - 1, 3))
    n = np.zeros((nx - 1, ny - 1, nz - 1))
    def cell(arr, o):
        return arr[o[0]:nx - 1 + o[0], o[1]:ny - 1 + o[1], o[2]:nz - 1 + o[2]]
    for p, q in edges:
        vp, vq = cell(V, p), cell(V, q)
        cross = (vp < 0) != (vq < 0)
        t = np.zeros_like(vp)
        t[cross] = vp[cross] / (vp[cross] - vq[cross])
        for k in range(3):
            s[..., k] += cross * (p[k] + (q[k] - p[k]) * t)
        n += cross
    has = n > 0
    idx = -np.ones(n.shape, dtype=np.int64)
    idx[has] = np.arange(has.sum())
    cells = np.argwhere(has)
    verts = (cells + s[has] / n[has][:, None]) * step + np.array([xs[0], ys[0], zs[0]])
    faces = []
    # A quad for each grid edge that crosses the surface, joining the four cells around it.
    c = I[:-1, 1:-1, 1:-1] != I[1:, 1:-1, 1:-1]
    for i, j, k in np.argwhere(c):
        j += 1; k += 1
        q = [idx[i, j - 1, k - 1], idx[i, j, k - 1], idx[i, j, k], idx[i, j - 1, k]]
        faces.append(q if I[i, j, k] else q[::-1])
    c = I[1:-1, :-1, 1:-1] != I[1:-1, 1:, 1:-1]
    for i, j, k in np.argwhere(c):
        i += 1; k += 1
        q = [idx[i - 1, j, k - 1], idx[i - 1, j, k], idx[i, j, k], idx[i, j, k - 1]]
        faces.append(q if I[i, j, k] else q[::-1])
    c = I[1:-1, 1:-1, :-1] != I[1:-1, 1:-1, 1:]
    for i, j, k in np.argwhere(c):
        i += 1; j += 1
        q = [idx[i - 1, j - 1, k], idx[i, j - 1, k], idx[i, j, k], idx[i - 1, j, k]]
        faces.append(q if I[i, j, k] else q[::-1])
    return verts, faces


def relax(verts, faces, rounds=3, amount=.5):
    """Takes the grid's stair-stepping out of the surface."""
    q = np.array(faces)
    a = np.concatenate([q[:, 0], q[:, 1], q[:, 2], q[:, 3]])
    b = np.concatenate([q[:, 1], q[:, 2], q[:, 3], q[:, 0]])
    for _ in range(rounds):
        total = np.zeros_like(verts)
        count = np.zeros(len(verts))
        np.add.at(total, a, verts[b]); np.add.at(count, a, 1)
        np.add.at(total, b, verts[a]); np.add.at(count, b, 1)
        verts = verts + amount * (total / np.maximum(count, 1)[:, None] - verts)
    return verts


def part(f, lo, hi, step, tris, smooth=3):
    """Field to a decimated triangle mesh: (verts Nx3, tris Mx3)."""
    v, q = surface_nets(f, lo, hi, step)
    v = relax(v, q, smooth)
    me = bpy.data.meshes.new("tmp")
    me.from_pydata(v.tolist(), [], q)
    me.update()
    ob = bpy.data.objects.new("tmp", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("d", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = min(1.0, tris / (len(q) * 2))
    dg = bpy.context.evaluated_depsgraph_get()
    done = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    done.calc_loop_triangles()
    nv = np.zeros(len(done.vertices) * 3)
    done.vertices.foreach_get("co", nv)
    nt = np.zeros(len(done.loop_triangles) * 3, dtype=np.int32)
    done.loop_triangles.foreach_get("vertices", nt)
    bpy.data.objects.remove(ob); bpy.data.meshes.remove(me); bpy.data.meshes.remove(done)
    return nv.reshape(-1, 3), nt.reshape(-1, 3)


def occlusion(v, fields):
    """How much of the open air around each vertex is really open, sampled from the fields."""
    f = lambda x, y, z: np.minimum.reduce([g(x, y, z) for g in fields])
    e = .002
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    n = np.stack([f(x + e, y, z) - f(x - e, y, z), f(x, y + e, z) - f(x, y - e, z), f(x, y, z + e) - f(x, y, z - e)], 1)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
    ao = np.zeros(len(v))
    for d, w in ((.008, .35), (.02, .35), (.05, .3)):
        p = v + n * d
        ao += w * np.clip(f(p[:, 0], p[:, 1], p[:, 2]) / d, 0, 1)
    return .32 + .68 * np.clip(ao, 0, 1) ** 1.4


# ------------------------------------------------------------------ assembling a mesh object
class Build:
    def __init__(self, arm):
        self.arm = arm
        self.bones = {b.name: (np.array(b.head_local), np.array(b.tail_local)) for b in arm.data.bones}

    def weights(self, v, allowed, skirt_from=None, skirt_over=.35):
        names = list(allowed)
        d = np.zeros((len(v), len(names)))
        for i, n in enumerate(names):
            a, b = self.bones[n]
            ab = b - a
            t = np.clip(((v - a) @ ab) / (ab @ ab), 0, 1)
            d[:, i] = np.linalg.norm(v - (a + t[:, None] * ab), axis=1)
        w = 1.0 / (d + .012) ** 7
        for i, n in enumerate(names):   # a left limb never follows the right one
            if n.endswith(".L"):
                w[v[:, 0] < -.015, i] = 0
            elif n.endswith(".R"):
                w[v[:, 0] > .015, i] = 0
        w /= w.sum(1)[:, None]
        if skirt_from is not None:      # coats and skirts hang from the hips and only partly follow the legs
            hips = names.index("hips")
            l, r = names.index("upper_leg.L"), names.index("upper_leg.R")
            share = .95 * np.clip((skirt_from - v[:, 2]) / skirt_over, 0, 1)
            side = np.clip(.5 + v[:, 0] / .14, 0, 1)
            w[:] = 0
            w[:, hips] = 1 - share
            w[:, l] = share * side
            w[:, r] = share * (1 - side)
        return names, w

    def object(self, name, pieces):
        """pieces: dicts of field(s), bounds, step, tris, mat, bones, uv, [skirt_from, ao_with]."""
        vs, ts, ms, colors, uvs, gs = [], [], [], [], [], []
        base = 0
        mats = []
        for p in pieces:
            v, t = part(p["f"], p["lo"], p["hi"], p["step"], p["tris"], p.get("smooth", 3))
            if p["mat"] not in mats:
                mats.append(p["mat"])
            vs.append(v); ts.append(t + base)
            ms += [mats.index(p["mat"])] * len(t)
            colors.append(occlusion(v, [p["f"]] + p.get("ao_with", [])))
            uvs.append(p.get("uv", cloth_uv)(v))
            gs.append(self.weights(v, p["bones"], p.get("skirt_from"), p.get("skirt_over", .35)))
            base += len(v)
        verts = np.concatenate(vs); tris = np.concatenate(ts)
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts.tolist(), [], tris.tolist())
        me.update()
        for m in mats:
            me.materials.append(bpy.data.materials.get(m) or bpy.data.materials.new(m))
        me.polygons.foreach_set("material_index", ms)
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        all_uv = np.concatenate(uvs)
        uv = me.uv_layers.new(name="UV")
        li = np.zeros(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", li)
        uv.data.foreach_set("uv", all_uv[li].ravel())
        col = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        ao = np.concatenate(colors)
        col.data.foreach_set("color", np.stack([ao, ao, ao, np.ones_like(ao)], 1).ravel())
        me.color_attributes.active_color = col
        me.update()
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        offset = 0
        for g, v in zip(gs, vs):
            names, w = g
            for i in range(len(v)):
                top = np.argsort(w[i])[-3:]
                total = w[i][top].sum()
                for b in top:
                    if w[i][b] > .004:
                        vg = ob.vertex_groups.get(names[b]) or ob.vertex_groups.new(name=names[b])
                        vg.add([offset + i], float(w[i][b] / total), "REPLACE")
            offset += len(v)
        ob.parent = self.arm
        ob.modifiers.new("arm", "ARMATURE").object = self.arm
        print("MESH", name, "tris", len(tris), "verts", len(verts))
        return ob


def cloth_uv(v):
    """Sheared planar: no seams, and the cloth textures are only fine noise."""
    return np.stack([(v[:, 0] + .55 * v[:, 1]) * 4.5, (v[:, 2] + .55 * v[:, 1]) * 4.5], 1)


def face_uv(v):
    """Straight on from the front, so a face texture reads as a portrait too. See tools/gen_art.py.
    From the ears back it slides onto a clear row of forehead, so the back of the head isn't a mirrored face."""
    u = .5 + v[:, 0] / .24
    front = .5 + (v[:, 2] - 1.665) / .24
    back = sstep(-.005, .035, v[:, 1])
    return np.stack([u, np.clip(front + (.707 - front) * back, .03, .98)], 1)


# ------------------------------------------------------------------ head
def head_field(fem):
    def f(x, y, z):
        ax = np.abs(x)
        d = ell(x, y, z, (0, .012, 1.692), (.077, .098, .097))                      # cranium
        jaw_w = .06 if fem else .068
        d = smin(d, ell(x, y, z, (0, -.022, 1.615), (jaw_w, .07, .062)), .025)       # jaw
        chin = (-.066, 1.569, .018) if fem else (-.07, 1.566, .024)
        d = smin(d, ell(x, y, z, (0, chin[0], chin[1]), (chin[2] * 1.1, chin[2], chin[2])), .022)
        d = smin(d, ell(ax, y, z, (.046, -.058, 1.648), (.02, .024, .017)), .032)    # cheekbones
        brow = .011 if fem else .015
        d = smin(d, ell(x, y, z, (0, -.08, 1.7), (.056, .013, brow)), .022)          # brow ridge
        d = smax(d, -ell(ax, y, z, (.033, -.096, 1.676), (.022, .015, .011)), .012)  # eye sockets
        d = smin(d, ell(ax, y, z, (.033, -.072, 1.677), (.0145, .0145, .0125)), .003)# eyeballs
        # Nose: bridge to tip, then wings
        tip_r = .0092 if fem else .0115
        d = smin(d, cone(x, y, z, (0, -.086, 1.684), (0, -.1 if fem else -.104, 1.642 if fem else 1.639), .0062, tip_r), .009)
        d = smin(d, ell(ax, y, z, (.0115, -.094, 1.634), (.0072, .0082, .0058)), .005)
        d = smax(d, -ell(ax, y, z, (.0062, -.1, 1.6285), (.0034, .0048, .0022)), .002)  # nostrils
        # Mouth
        fuller = 1.25 if fem else 1.0
        d = smin(d, ell(x, y, z, (0, -.0885, 1.612), (.0235, .0095, .0052 * fuller)), .007)
        d = smin(d, ell(x, y, z, (0, -.0865, 1.601), (.021, .0105, .0068 * fuller)), .007)
        d = smax(d, -ell(x, y, z, (0, -.099, 1.6065), (.025, .006, .001)), .0015)
        # Ears
        ear = ell(ax, y, z, (.0815, .014, 1.668), (.0065, .0165, .029))
        ear = smax(ear, -ell(ax, y, z, (.0875, .012, 1.669), (.0045, .0095, .018)), .003)
        d = smin(d, ear, .004)
        # Neck, into the collar
        neck_r = (.045, .043) if fem else (.058, .053)
        return smin(d, cone(x, y, z, (0, .012, 1.47), (0, .012, 1.6), neck_r[0], neck_r[1]), .018)
    return f


def hand_field(sg, fem):
    k = .9 if fem else 1.0
    wx, wy, wz = sg * .245, -.02, .89
    def f(x, y, z):
        # Palm: broad along y, thin across x, hanging and relaxed
        d = ell(x, y, z, (wx + sg * .003, wy - .006, wz - .052 * k), (.017 * k, .04 * k, .05 * k))
        d = smin(d, cone(x, y, z, (wx, wy, wz + .05), (wx, wy - .004, wz - .01), .03 * k, .027 * k), .012)
        # Four fingers from front to back along the palm's end, curling in towards the body and forward
        for i, (oy, ln) in enumerate(((.03, .072), (.01, .082), (-.01, .076), (-.029, .06))):
            kn = (wx + sg * .004, wy - .006 - oy * k, wz - .088 * k)
            mid = (kn[0] - sg * .004, kn[1] - .006, kn[2] - ln * .55 * k)
            tip = (mid[0] - sg * .014, mid[1] - .012, mid[2] - ln * .42 * k)
            r = (.0092 - i * .0003) * k
            d = smin(d, cone(x, y, z, kn, mid, r, r * .92), .004)
            d = smin(d, cone(x, y, z, mid, tip, r * .92, r * .78), .002)
        # Thumb, from the base of the palm towards the front of the body
        b = (wx - sg * .006, wy - .034 * k, wz - .03 * k)
        m = (b[0] - sg * .012, b[1] - .022 * k, b[2] - .03 * k)
        t = (m[0] - sg * .006, m[1] - .012 * k, m[2] - .03 * k)
        d = smin(d, cone(x, y, z, b, m, .014 * k, .0105 * k), .008)
        return smin(d, cone(x, y, z, m, t, .0105 * k, .0085 * k), .003)
    return f


def person(b, name, fem):
    hf = head_field(fem)
    pieces = [dict(f=hf, lo=(-.11, -.14, 1.47), hi=(.11, .125, 1.81), step=.0032, tris=2600, mat="face", bones=["chest", "neck", "head"], uv=face_uv, smooth=2)]
    for side, sg in (("L", 1), ("R", -1)):
        x0, x1 = sorted((sg * .19, sg * .3))
        pieces.append(dict(f=hand_field(sg, fem), lo=(x0, -.09, .72), hi=(x1, .04, .95), step=.0028, tris=620, mat="skin", bones=[f"lower_arm.{side}", f"hand.{side}"], smooth=2))
    return b.object(name, pieces)


# ------------------------------------------------------------------ clothes
JACKET = [(.84, .192, .13, .012), (.96, .19, .128, .012), (1.06, .176, .116, .006), (1.16, .16, .106, .003), (1.26, .168, .112, 0), (1.36, .186, .122, -.005), (1.42, .2, .11, .002), (1.462, .178, .088, .006), (1.492, .112, .072, .012), (1.51, .074, .068, .012), (1.525, .066, .066, .012)]
TRENCH = [(.53, .232, .165, .02), (.72, .208, .142, .016)] + JACKET[1:4:1] + JACKET[4:]
TRENCH[0:0] = []
SHIRT = [(.945, .165, .108, .01), (1.06, .158, .104, .005), (1.16, .152, .1, .003), (1.26, .16, .104, 0), (1.36, .176, .113, -.004), (1.42, .19, .102, .002), (1.462, .165, .082, .006), (1.492, .104, .068, .012), (1.51, .07, .064, .012), (1.525, .06, .062, .012)]
BLOUSE = [(.97, .118, .084, .006), (1.04, .118, .084, .004), (1.12, .124, .086, 0), (1.22, .146, .096, -.004), (1.3, .16, .104, -.006), (1.38, .166, .092, 0), (1.44, .158, .08, .006), (1.48, .1, .066, .012), (1.51, .054, .056, .012)]


def shoulders(x, y, z, d, inset=0.0):
    """The top of the sleeve, blended into the torso so a shoulder flows on instead of a ball sitting beside it."""
    return smin(d, ell(np.abs(x), y, z, (.178 - inset, .002, 1.408), (.05, .076, .058)), .034)


def v_half(z, top, bottom, top_w):
    """Half-width of a coat's V opening at height z."""
    return top_w * np.clip((z - bottom) / (top - bottom), 0, 1)


def sleeve_field(sg, r0, r1, r2, end, x_in=0.0):
    s = (sg * (.197 - x_in), .0, 1.39)
    e = (sg * (.231 - x_in * .5), .012, 1.147)
    w = (sg * .243, -.018, end)
    cap = (sg * (.194 - x_in), .0, 1.385)
    def f(x, y, z):
        d = smin(cone(x, y, z, s, e, r0, r1), cone(x, y, z, e, w, r1, r2), .012)
        d = smin(d, ell(x, y, z, cap, (r0 * 1.02, r0 * 1.12, r0 * 1.1)), .02)
        return np.maximum(d, end - z)
    return f


def coat_field(table, v_top=1.52, v_bottom=1.13, lapel=.052, hem_cut=.98, belt=None, pockets=True, hem_open=.055):
    hem = table[0][0]
    def f(x, y, z):
        ax = np.abs(x)
        d = shoulders(x, y, z, loft(x, y, z, table))
        front = y < 0
        vw = v_half(z, v_top, v_bottom, .068)
        inside = z > v_bottom
        # Lapels: a raised band beside the opening, with the notch cut out of it
        lap = band(ax - vw, -.002, lapel * sstep(v_bottom, v_bottom + .1, z) + .002, .003) * inside * front * (z < v_top - .03)
        notch = band(z, 1.385, 1.4, .003) * (ax - vw > .022)
        d = d - .0065 * lap * (1 - notch)
        # Pocket flaps
        if pockets:
            d = d - .0045 * band(ax, .068, .142, .003) * band(z, .985, 1.012, .003) * front
            d = d - .003 * band(x, .08, .142, .003) * band(z, 1.325, 1.345, .003) * front
        if belt:
            d = d - .007 * band(z, belt - .022, belt + .022, .003)
        # The V itself, cut well in so the shirt shows
        cut = (vw - ax) * inside
        d = smax(d, np.where(front, cut - .001, -1.0) * np.where(inside, 1.0, 0.0) + np.where(inside, 0.0, -1.0), .002)
        # Cutaway at the hem
        low = hem_open * np.clip((hem_cut - z) / (hem_cut - hem), 0, 1)
        d = np.maximum(d, np.where(front & (z < hem_cut), low - ax, -1.0))
        # Collar standing round the back of the neck
        coll = loft(x, y, z, [(1.47, .082, .079, .012), (1.51, .074, .072, .012), (1.545, .066, .066, .014)])
        coll = np.maximum(coll, -loft(x, y, z, [(1.45, .066, .064, .012), (1.56, .058, .058, .014)]))
        coll = np.maximum(coll, np.where(y < -.03, 1.0, -1.0) * .02)
        return smin(d, coll, .006)
    return f


def buttons(ys, front_y):
    def f(x, y, z):
        return np.minimum.reduce([ell(x, y, z, (0, front_y, zb), (.0085, .004, .0085)) for zb in ys])
    return f


def shirt_front(table_scale=1.0, depth=-.006):
    def f(x, y, z):
        t = [(zz, rx, ry + depth, cy) for zz, rx, ry, cy in JACKET if zz > 1.0]
        d = loft(x, y, z, t)
        d = np.maximum(d, np.maximum(.03 - (-y + .03), np.abs(x) - .11))  # only the part that shows
        return d
    return f


def shirt_collar(rx=.066):
    """A band round the neck, closed at the throat, and two flat wings folded down over the chest."""
    def f(x, y, z):
        ax = np.abs(x)
        d = loft(x, y, z, [(1.485, rx + .01, rx + .004, .012), (1.515, rx + .004, rx, .012), (1.542, rx, rx - .004, .014)])
        d = np.maximum(d, -loft(x, y, z, [(1.46, rx - .008, rx - .01, .012), (1.56, rx - .012, rx - .012, .014)]))
        d = np.maximum(d, np.where(y < 0, .005 - ax, -1.0))
        shell = loft(x, y, z, [(1.42, rx + .036, rx + .032, .002), (1.48, rx + .02, rx + .016, .008), (1.54, rx + .008, rx + .006, .012)])
        # Triangle in the front view: throat, neck side, point
        e1 = (1.535 - z) - (ax - .006) * .3
        e2 = (ax - .034) * .8 - (z - 1.445) * .45 - .0
        e3 = .012 * 0 + (.034 - ax) * 2.1 - (z - 1.445) * 1.0 * .75
        tri = np.maximum(np.maximum(-e1, e2 - .018), e3 - .012)
        wing = np.maximum(np.maximum(shell, tri), y + .01)
        return smin(d, wing, .002)
    return f


def tie_field(front):
    def f(x, y, z):
        zt = np.clip((1.47 - z) / .34, 0, 1)
        fy = np.interp(z, front[0], front[1]) - .004
        w = .014 + .022 * zt
        d = np.maximum(np.maximum(np.abs(x) - w * np.minimum(1, (z - 1.122) / .03), np.abs(y - fy) - .0028), np.maximum(1.122 - z, z - 1.47)) - .0015
        return smin(d, ell(x, y, z, (0, -.082, 1.468), (.0115, .0065, .0115)), .003)
    return f


def _front_curve(table, depth):
    zs, rx, ry, cy = _spline([t for t in table if t[0] > 1.0])
    return zs, cy - ry - depth


def legs_pieces(cut=None):
    """cut: for under a long coat. Above this height the trousers are slimmed so the thighs stay inside the coat
    when they swing. (They used to stop dead at the cut, which left a hole at the crotch that showed through the
    trench coat's open front: the person mesh is only head, neck and hands.)"""
    def pants(x, y, z):
        ax = np.abs(x)
        d = loft(x, y, z, [(.86, .176, .116, .008), (.94, .176, .114, .008), (1.02, .162, .104, .006)])
        hip = (.086, -.002, .9); knee = (.086, -.012, .51); ankle = (.086, .006, .11)
        leg = smin(cone(ax, y, z, hip, knee, .094, .063), cone(ax, y, z, knee, ankle, .063, .058), .02)
        d = smin(d, leg, .022)
        # Pressed crease down the shin and thigh
        crease = np.exp(-((ax - .086) / .009) ** 2) * sstep(.1, .15, z) * (1 - sstep(.72, .86, z))
        d = d - .0035 * crease
        # Belt
        d = d - .004 * band(z, .975, 1.005, .002)
        d = np.maximum(d, .085 - z)
        if cut is None:
            return d
        return d + .024 * sstep(cut - .05, cut + .03, z)

    def shoes(x, y, z):
        ax = np.abs(x)
        d = ell(ax, y, z, (.086, -.052, .043), (.05, .138, .047))
        d = smin(d, ell(ax, y, z, (.086, .03, .06), (.046, .06, .06)), .025)
        d = smin(d, cone(ax, y, z, (.086, .008, .06), (.086, .008, .105), .051, .052), .012)
        d = smax(d, -cone(ax, y, z, (.086, .005, .12), (.086, .005, .16), .046, .05), .003)
        d = np.maximum(d, -z)
        sole = np.maximum(np.maximum(d - .0035, -z), z - .018)
        d = smin(d, sole, .002)
        # A shallow groove where the sole meets the upper. (This was smax(d, .003 - .006 * band), which is
        # positive everywhere outside the band and so deleted the whole shoe but a 5 mm slice: no feet.)
        return d + .0015 * band(z, .018, .023, .0015)
    b = ["hips", "upper_leg.L", "upper_leg.R", "lower_leg.L", "lower_leg.R"]
    return [dict(f=pants, lo=(-.2, -.14, .07), hi=(.2, .14, 1.03), step=.0065, tris=1500, mat="pants", bones=b, ao_with=[shoes]),
            dict(f=shoes, lo=(-.16, -.21, -.004), hi=(.16, .12, .16), step=.0048, tris=1100, mat="shoes", bones=["foot.L", "foot.R", "lower_leg.L", "lower_leg.R"], ao_with=[pants], smooth=2)]


TORSO_BONES = ["chest", "spine", "hips"]
ARM_L = ["chest", "upper_arm.L", "lower_arm.L"]
ARM_R = ["chest", "upper_arm.R", "lower_arm.R"]


def sleeves(mat, r0, r1, r2, end, x_in=0.0, tris=620, ao=None):
    out = []
    for side, sg, bones in (("L", 1, ARM_L), ("R", -1, ARM_R)):
        x0, x1 = sorted((sg * .12, sg * .31))
        out.append(dict(f=sleeve_field(sg, r0, r1, r2, end, x_in), lo=(x0, -.1, end - .01), hi=(x1, .1, 1.5), step=.0065, tris=tris, mat=mat, bones=bones, ao_with=ao or []))
    return out


def cuffs(mat, r, top, bottom):
    out = []
    for side, sg, bones in (("L", 1, ARM_L), ("R", -1, ARM_R)):
        def f(x, y, z, sg=sg):
            return cone(x, y, z, (sg * .2415, -.015, top), (sg * .2435, -.019, bottom), r, r * .96)
        x0, x1 = sorted((sg * .19, sg * .3))
        out.append(dict(f=f, lo=(x0, -.08, bottom - .05), hi=(x1, .05, top + .05), step=.004, tris=90, mat=mat, bones=bones))
    return out


def outfit_coat(b, name, table, belt=None, cut=.98, skirt_from=None, extra_tris=0, hem_open=.055):
    coat = coat_field(table, belt=belt, hem_cut=cut, hem_open=hem_open)
    shirt = shirt_front()
    collar = shirt_collar()
    front = _front_curve(JACKET, -.006 + .0)
    tie = tie_field(front)
    lo_z = table[0][0] - .01
    torso_bones = TORSO_BONES if skirt_from is None else None
    btn_y = -.118
    def buttoned(x, y, z, _f=coat):
        d = _f(x, y, z)
        return np.minimum(d, ell(x, y, z, (0, btn_y, 1.105), (.009, .0045, .009)))
    piece = dict(f=buttoned, lo=(-.23, -.19, lo_z), hi=(.23, .19, 1.56), step=.0052, tris=3000 + extra_tris, mat="top", ao_with=[shirt])
    if skirt_from is None:
        piece["bones"] = TORSO_BONES
    else:
        piece["bones"] = ["hips", "upper_leg.L", "upper_leg.R"]
        piece["skirt_from"] = skirt_from
    pieces = []
    if skirt_from is None:
        pieces.append(piece)
    else:
        # Above the skirt line the coat follows the spine; below, the hips and legs. Two pieces split at the waist.
        top = dict(piece); top["bones"] = TORSO_BONES; top.pop("skirt_from")
        top["lo"] = (-.23, -.19, skirt_from); top["tris"] = 2800
        def upper(x, y, z, _f=buttoned):
            return np.maximum(_f(x, y, z), skirt_from - z)
        top["f"] = upper
        bottom = dict(piece); bottom["hi"] = (.27, .2, skirt_from + .03); bottom["tris"] = 900
        bottom["skirt_over"] = .1     # a coat's split skirts go with the legs, or the legs come through it
        def lower(x, y, z, _f=buttoned):
            return np.maximum(_f(x, y, z), z - skirt_from - .01)
        bottom["f"] = lower
        pieces += [top, bottom]
    pieces += [
        dict(f=shirt, lo=(-.12, -.14, 1.1), hi=(.12, -.02, 1.54), step=.005, tris=420, mat="shirt", bones=["chest", "spine"], ao_with=[coat]),
        dict(f=collar, lo=(-.1, -.11, 1.43), hi=(.1, .09, 1.565), step=.0035, tris=620, mat="shirt", bones=["chest", "neck"], ao_with=[coat]),
        dict(f=tie, lo=(-.05, -.135, 1.11), hi=(.05, -.06, 1.5), step=.0028, tris=420, mat="tie", bones=["chest", "spine"], ao_with=[shirt], smooth=1)]
    pieces += sleeves("top", .059, .05, .046, .935, ao=[coat])
    pieces += cuffs("shirt", .0415, .95, .905)
    return b.object(name, pieces)


def outfit_shirt(b):
    def body(x, y, z):
        ax = np.abs(x)
        d = shoulders(x, y, z, loft(x, y, z, SHIRT), .008)
        front = y < 0
        d = d - .002 * band(x, -.014, .014, .002) * front * (z < 1.47)              # placket
        d = d - .003 * band(x, .06, .125, .003) * band(z, 1.3, 1.37, .003) * front   # breast pocket
        # Soft folds where it tucks in
        folds = np.sin(np.arctan2(x, y) * 11) * (1 - sstep(.95, 1.09, z))
        d = d - .001 * folds
        return d
    collar = shirt_collar(.064)
    pieces = [dict(f=body, lo=(-.2, -.15, .935), hi=(.2, .15, 1.54), step=.0052, tris=2000, mat="top", bones=TORSO_BONES),
              dict(f=collar, lo=(-.1, -.11, 1.43), hi=(.1, .09, 1.565), step=.0035, tris=620, mat="top", bones=["chest", "neck"], ao_with=[body])]
    pieces += sleeves("top", .053, .046, .041, .93, tris=560, ao=[body])
    pieces += cuffs("top", .0385, .945, .905)
    return b.object("outfit_shirt", pieces)


def outfit_dress(b):
    def blouse(x, y, z):
        ax = np.abs(x)
        d = shoulders(x, y, z, loft(x, y, z, BLOUSE), .032)
        d = smin(d, ell(ax, y, z, (.064, -.07, 1.312), (.06, .046, .056)), .04)
        d = d - .0018 * band(x, -.012, .012, .002) * (y < 0) * (z < 1.45)
        return d
    def skirt(x, y, z):
        a = np.arctan2(x, y)
        t = np.clip((1.02 - z) / .56, 0, 1)
        d = loft(x, y, z, [(.47, .262, .222, .014), (.6, .232, .194, .012), (.76, .208, .16, .01), (.9, .17, .118, .008), (.98, .143, .106, .006), (1.045, .127, .095, .004), (1.065, .125, .094, .004)])
        return d - .0075 * t * t * np.cos(a * 14)
    def legs(x, y, z):
        ax = np.abs(x)
        thigh = cone(ax, y, z, (.08, -.002, .8), (.082, -.012, .51), .07, .05)
        calf = cone(ax, y, z, (.082, -.012, .51), (.084, .004, .36), .05, .049)
        shin = cone(ax, y, z, (.084, .004, .36), (.085, .008, .1), .049, .032)
        return smin(smin(thigh, calf, .02), shin, .03)
    def shoes(x, y, z):
        # Court shoes: a low block heel
        ax = np.abs(x)
        d = ell(ax, y, z, (.085, -.075, .032), (.04, .105, .034))
        d = smin(d, ell(ax, y, z, (.085, .022, .07), (.037, .05, .042)), .03)
        d = smax(d, -cone(ax, y, z, (.085, -.0, .1), (.085, -.0, .15), .032, .036), .004)
        heel = cone(ax, y, z, (.085, .045, .06), (.085, .052, .0), .022, .014)
        return np.maximum(smin(d, heel, .006), -z)
    collar = shirt_collar(.054)
    leg_bones = ["upper_leg.L", "upper_leg.R", "lower_leg.L", "lower_leg.R"]
    pieces = [dict(f=blouse, lo=(-.19, -.16, .96), hi=(.19, .13, 1.53), step=.0052, tris=2000, mat="top", bones=TORSO_BONES),
              dict(f=collar, lo=(-.09, -.1, 1.42), hi=(.09, .08, 1.565), step=.0035, tris=520, mat="top", bones=["chest", "neck"], ao_with=[blouse]),
              dict(f=skirt, lo=(-.29, -.25, .46), hi=(.29, .25, 1.075), step=.0065, tris=1500, mat="skirt", bones=["hips", "upper_leg.L", "upper_leg.R"], skirt_from=.96, skirt_over=.15, ao_with=[blouse]),
              dict(f=legs, lo=(-.17, -.08, .06), hi=(.17, .08, .9), step=.006, tris=1000, mat="skin", bones=leg_bones),
              dict(f=shoes, lo=(-.14, -.2, -.004), hi=(.14, .11, .16), step=.0042, tris=700, mat="shoes", bones=["foot.L", "foot.R", "lower_leg.L", "lower_leg.R"], ao_with=[legs], smooth=2)]
    pieces += sleeves("top", .047, .04, .035, .925, x_in=.026, tris=500, ao=[blouse])
    pieces += cuffs("top", .0335, .94, .9)
    return b.object("outfit_dress", pieces)


# ------------------------------------------------------------------ hats and hair
HAT_DROP = .038     # the hat's shapes were drawn floating; this seats the band just above the ears


def hat_parts(b):
    crown_table = [(1.742, .098, .118, .012), (1.8, .094, .112, .012), (1.845, .09, .106, .012), (1.868, .074, .09, .014)]
    def crown(x, y, z):
        d = loft(x, y, z, crown_table)
        # Teardrop crease along the top and two pinches at the front
        d = d + .017 * np.exp(-(x / .021) ** 2) * sstep(1.835, 1.865, z)
        d = d + .012 * np.exp(-(((np.abs(x) - .05) / .022) ** 2 + ((y + .075) / .03) ** 2)) * sstep(1.81, 1.86, z)
        return d - .006
    def brim(x, y, z):
        rn = np.sqrt((x / .172) ** 2 + ((y - .012) / .19) ** 2)
        # Curls up at the sides and back, dips over the eyes
        lip = .024 * (x / .172) ** 2 - .014 * np.clip(-(y - .012) / .19, 0, 1) ** 2 + .008 * np.clip((y - .012) / .19, 0, 1) ** 2
        return np.maximum(np.abs(z - (1.748 + lip * np.minimum(rn, 1) ** 2)) - .0032, (rn - 1) * .172) - .001
    def felt(x, y, z):
        return smin(crown(x, y, z), brim(x, y, z), .014)
    def ribbon(x, y, z):
        return np.maximum(loft(x, y, z, [(1.75, .1, .12, .012), (1.79, .097, .116, .012)]) - .0045, np.maximum(1.752 - z, z - 1.788))
    def low(f):
        return lambda x, y, z: f(x, y, z + HAT_DROP)
    dz = HAT_DROP
    b.object("hat", [dict(f=low(felt), lo=(-.2, -.2, 1.71 - dz), hi=(.2, .22, 1.9 - dz), step=.0045, tris=1500, mat="hat", bones=["head"], ao_with=[low(ribbon)]),
                     dict(f=low(ribbon), lo=(-.12, -.13, 1.74 - dz), hi=(.12, .15, 1.8 - dz), step=.0035, tris=360, mat="band", bones=["head"], smooth=1)])


def hair_uv(v):
    return np.stack([(v[:, 0] + .4 * v[:, 1]) * 3.0, (v[:, 2] + .4 * v[:, 1]) * 3.0], 1)


def hair_parts(b):
    def short(x, y, z):
        ax = np.abs(x)
        d = ell(x, y, z, (.0, .012, 1.698), (.0845, .1055, .103))
        # Side part on the left, swept up and over at the front
        d = d - .006 * np.exp(-((x + .02) / .045) ** 2) * sstep(-.03, -.09, y)
        d = d + .003 * np.exp(-((x - .038) / .004) ** 2) * (z > 1.74)
        # Hairline: high on the forehead, down behind the ears, a short sideburn
        line = 1.742 + .002 * np.sin(x * 60) - .12 * sstep(-.06, .05, y)
        burn = band(ax, .068, .1, .004) * band(y, -.035, -.002, .004) * .09
        d = np.maximum(d, line - burn - z)
        # Clear of the ears
        return np.maximum(d, -ell(ax, y, z, (.088, .012, 1.666), (.018, .027, .037)))
    def long(x, y, z):
        ax = np.abs(x)
        d = ell(x, y, z, (0, .014, 1.7), (.09, .11, .103))
        # 1950s set hair: full at the sides, rolled under at the shoulder
        d = smin(d, ell(ax, y, z, (.066, .036, 1.61), (.053, .08, .105)), .035)
        d = smin(d, ell(x, y, z, (0, .07, 1.57), (.085, .05, .09)), .03)
        d = smin(d, ell(ax, y, z, (.075, .03, 1.522), (.048, .07, .033)), .018)
        d = smin(d, ell(x, y, z, (0, .075, 1.51), (.08, .04, .032)), .018)
        # Waves
        d = d - .0035 * np.sin(z * 75 + np.arctan2(y, x) * 3)
        # Leave the face open: a soft-edged oval, plus the neck
        opening = ell(x, y, z, (0, -.075, 1.635), (.073, .085, .105))
        d = smax(d, -opening, .012)
        return smax(d, -cone(x, y, z, (0, .012, 1.46), (0, .012, 1.6), .052, .05), .006)
    b.object("hair_short", [dict(f=short, lo=(-.11, -.13, 1.6), hi=(.11, .13, 1.82), step=.0042, tris=850, mat="hair", bones=["head"], uv=hair_uv)])
    b.object("hair_long", [dict(f=long, lo=(-.15, -.13, 1.47), hi=(.15, .15, 1.82), step=.0052, tris=1600, mat="hair", bones=["head", "neck"], uv=hair_uv)])


def glasses(b):
    z0, y0 = 1.678, -.1035
    def frame(x, y, z):
        ax = np.abs(x)
        rim = np.maximum(np.abs(np.sqrt(((ax - .033) / .026) ** 2 + ((z - z0) / .018) ** 2) - 1) * .018 - .0022, np.abs(y - y0) - .002)
        bridge = cone(ax, y, z, (0, y0, z0 + .006), (.01, y0, z0 + .007), .0022, .0022)
        arm = cone(ax, y, z, (.059, y0, z0 + .004), (.082, .02, z0 + .006), .0018, .0018)
        return np.minimum(np.minimum(rim, bridge), arm)
    def lens(x, y, z):
        return np.maximum(np.sqrt(((np.abs(x) - .033) / .025) ** 2 + ((z - z0) / .0172) ** 2) - 1, np.abs(y - y0) * 40 - .03) * .018
    b.object("glasses", [dict(f=frame, lo=(-.095, -.11, 1.65), hi=(.095, .035, 1.71), step=.0016, tris=500, mat="tie", bones=["head"], smooth=1),
                         dict(f=lens, lo=(-.065, -.11, 1.65), hi=(.065, -.095, 1.71), step=.0014, tris=120, mat="lens", bones=["head"], smooth=1)])


# ------------------------------------------------------------------ build
wipe()
arm = build_skeleton(dict(h=H, sw=.2, hw=.085))
b = Build(arm)
person(b, "person_m", False)
person(b, "person_f", True)
b.object("legs_m", legs_pieces())
b.object("legs_coat", legs_pieces(cut=.8))
outfit_coat(b, "outfit_suit", JACKET)
outfit_coat(b, "outfit_trench", TRENCH, belt=1.13, cut=1.08, skirt_from=.98, hem_open=.15)
outfit_shirt(b)
outfit_dress(b)
hat_parts(b)
hair_parts(b)
glasses(b)
build_anims(arm)
export(os.path.join(OUT, "human.glb"), colors=True)
print("BLENDER_DONE")
