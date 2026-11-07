"""Model the faceless mannequin head from a front + side silhouette sheet.

    blender -b -P make_mannequin_head.py -- [reference.png] [out.blend]

The sheet (character_kit/heads/mannequin_reference.png) shows the head from the front on the left
half and from the side, facing right, on the right half, light on a dark backdrop. Each image row
gives the head's width (front view) and its front and back (side view); those profiles are lofted
into a head and a neck, joined with a voxel remesh and smoothed where the jaw meets the neck.

Sizes come from the kit head: crown 1.789 m, chin 1.545 m, skull centred front-to-back on the kit
skull, neck bent back to sit on the kit's neck. The result is the mesh object "MannequinHead" in
character_kit/heads/mannequin_head.blend, in Blender coordinates (Z up, face towards -Y). Sculpt
it freely; conform_head.py fits the kit's head onto whatever shape it has.
"""
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
REF = Path(argv[0]) if argv else ROOT / 'character_kit' / 'heads' / 'mannequin_reference.png'
OUT = Path(argv[1]) if len(argv) > 1 else ROOT / 'character_kit' / 'heads' / 'mannequin_head.blend'

CROWN_Z, CHIN_Z = 1.789, 1.545      # kit head
SKULL_MID_Y = 0.0                   # kit skull centre, front-to-back
NECK_Y = 0.012                      # kit neck centre at the bottom of the head (z ~1.49)
NECK_BOTTOM_Z = 1.45                # the kit's own neck takes over below ~1.5 (conform_head.py blends)
NECK_HALF_WIDTH = 0.059             # the reference neck flares into a bust lower down; keep it a neck


def silhouettes(path):
    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1]  # top row first
    lum = px[..., :3].mean(2)
    mask = lum > 90 / 255
    half = w // 2
    rows = {}
    for r in range(h):
        f = np.where(mask[r, :half])[0]
        s = np.where(mask[r, half:])[0] + half
        rows[r] = (f.min() if len(f) else None, f.max() if len(f) else None, s.min() if len(s) else None, s.max() if len(s) else None)
    return rows


rows = silhouettes(REF)
head_rows = [r for r, v in rows.items() if v[0] is not None]
top = head_rows[0]
# Chin: where the side view's front edge steps back from the chin to the neck.
fronts = {r: rows[r][3] for r in head_rows}
chin = next(r for r in head_rows if r > top + 400 and fronts.get(r + 6) is not None and fronts[r] - fronts[r + 6] > 40)
scale = (CROWN_Z - CHIN_Z) / (chin - top)                       # metres per pixel
z_of = lambda r: CROWN_Z - (r - top) * scale
widest = max(head_rows[: chin - top], key=lambda r: rows[r][1] - rows[r][0])
cx = (rows[widest][0] + rows[widest][1]) / 2                      # front view centre line
deep = max(head_rows[: chin - top], key=lambda r: rows[r][3] - rows[r][2])
front_px = max(rows[r][3] for r in head_rows[: chin - top])
back_px = min(rows[r][2] for r in head_rows[: chin - top])
y0 = SKULL_MID_Y - (front_px - back_px) * scale / 2              # y of the face's front-most point
y_of = lambda x: y0 + (front_px - x) * scale
# Lower down the reference neck leans forward; bend it back onto the kit neck.
neck_r = int(round(top + (CROWN_Z - 1.49) / scale))
neck_mid = (y_of(rows[neck_r][2]) + y_of(rows[neck_r][3])) / 2
def shear(z):
    t = np.clip((1.62 - z) / (1.62 - 1.49), 0, 1)
    return (NECK_Y - neck_mid) * t * t * (3 - 2 * t)

print(f'reference: crown row {top}, chin row {chin}, {scale * 1000:.3f} mm/px, centre x {cx:.0f}')


def loft(name, sections, segments=72, power=2.3):
    """A closed tube through cross-sections (z, half-width, y front, y back): rounded-square-ish ellipses."""
    bm = bmesh.new()
    rings = []
    t = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    ex = np.sign(c) * np.abs(c) ** (2 / power)
    ey = np.sign(s) * np.abs(s) ** (2 / power)
    for z, a, yf, yb in sections:
        mid, ry = (yf + yb) / 2, (yb - yf) / 2
        rings.append([bm.verts.new((a * ex[k], mid + ry * ey[k], z)) for k in range(segments)])
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(segments):
            bm.faces.new((r0[k], r0[(k + 1) % segments], r1[(k + 1) % segments], r1[k]))
    for ring in (rings[0], rings[-1]):
        bm.faces.new(ring)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


bpy.ops.wm.read_factory_settings(use_empty=True)

# Head: the face oval and skull, from crown to chin. Below where the neck hides the face's sides
# (front view), the oval is closed off round the chin.
oval_end = next(r for r in range(widest + 150, chin) if (rows[r][1] - rows[r][0]) - (rows[r + 12][1] - rows[r + 12][0]) < 2)
jaw_front = next(r for r in range(chin, chin + 60) if rows[r][3] is not None and fronts[r] < front_px - 120)
smooth = lambda t: t * t * (3 - 2 * t)
head = []
for r in range(top + 2, chin + 1):
    f0, f1, s0, s1 = rows[r]
    z = z_of(r)
    yf = y_of(s1) + shear(z)
    yb = y_of(s0) + shear(z)
    a = (f1 - f0) / 2 * scale
    if r > oval_end:
        # Below where the neck hides the face's sides: the face narrows to the chin (front view), and the
        # head's back comes forward to just behind the neck's front, which carries the silhouette from here.
        k = (r - oval_end) / (chin - oval_end)
        # Carry on the face oval's own curve (an ellipse round its widest row) down to the chin.
        span = chin + 8 - widest
        oval = lambda q: np.sqrt(max(0.0, 1 - ((q - widest) / span) ** 2))
        a = (rows[oval_end][1] - rows[oval_end][0]) / 2 * scale * oval(r) / oval(oval_end)
        yb = yb + (y_of(fronts[jaw_front]) + shear(z) + 0.02 - yb) * smooth(k)
    head.append((z, a, yf, yb))
# Round the underside of the chin off instead of ending on a flat cap.
z_end, a_end, yf_end, yb_end = head[-1]
mid_end, ry_end = (yf_end + yb_end) / 2, (yb_end - yf_end) / 2
for i in range(1, 9):
    t = i / 9
    c = np.sqrt(1 - t * t)
    head.append((z_end - 0.008 * t, a_end * c + 0.002, mid_end - ry_end * c - 0.001, mid_end + ry_end * c + 0.001))
head_ob = loft('head_loft', head)

# Neck: from inside the head down past where the kit's neck takes over.
neck = []
for r in range(oval_end - 40, int(top + (CROWN_Z - NECK_BOTTOM_Z) / scale)):
    f0, f1, s0, s1 = rows[r]
    z = z_of(r)
    a = min((f1 - f0) / 2 * scale, NECK_HALF_WIDTH)
    yf = y_of(rows[max(r, jaw_front)][3]) + shear(z)   # above the jaw line the neck front sits inside the head
    yb = y_of(s0) + shear(z)
    neck.append((z, a, yf, yb))
neck_ob = loft('neck_loft', neck, power=2.0)

# Join, remesh into one closed surface, and soften the jaw-neck join.
bpy.ops.object.select_all(action='DESELECT')
head_ob.select_set(True); neck_ob.select_set(True)
bpy.context.view_layer.objects.active = head_ob
bpy.ops.object.join()
ob = head_ob
ob.name = ob.data.name = 'MannequinHead'
rm = ob.modifiers.new('remesh', 'REMESH'); rm.mode = 'VOXEL'; rm.voxel_size = 0.0018; rm.use_smooth_shade = True
sm = ob.modifiers.new('smooth', 'SMOOTH'); sm.factor = 0.7; sm.iterations = 20
bpy.ops.object.modifier_apply(modifier='remesh')
bpy.ops.object.modifier_apply(modifier='smooth')
# Cut the neck off flat at the bottom (inside the kit's collar).
bm = bmesh.new(); bm.from_mesh(ob.data)
bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, NECK_BOTTOM_Z + 0.005),
                       plane_no=(0, 0, 1), clear_inner=True)
bm.to_mesh(ob.data); bm.free()
for p in ob.data.polygons: p.use_smooth = True

mat = bpy.data.materials.new('mannequin'); mat.diffuse_color = (0.85, 0.85, 0.84, 1)
ob.data.materials.append(mat)
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
dims = ob.dimensions
print(f'MANNEQUIN_OK {OUT} verts {len(ob.data.vertices)} size {dims.x:.3f} x {dims.y:.3f} x {dims.z:.3f}')
