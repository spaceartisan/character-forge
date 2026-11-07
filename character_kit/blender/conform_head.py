"""Fit the kit's head onto a head modelled in Blender, and save the result as a Forge base shape.

    blender -b -P conform_head.py -- <head.blend> "<shape name>" [object name] [--preview out.blend]

The kit's head and neck (person_m and person_f, above the collar) are pulled onto the surface of the
modelled head: each vertex goes to the nearest point on it, then the vertices are relaxed across the
surface (and put back on it) so features the new head doesn't have, like the nose and ears, spread
out flat instead of folding over. Below the neck the kit body is untouched, with a short blend.

Each vertex also gets a texture offset (face_mapping) so painted faces read right on the new shape.
Only vertices and UVs move, so the rig, skin weights and face textures all keep working; the result is
written to data/shapes.json as a base shape (Customize > Body type > Base shape). Re-run it after
sculpting the .blend to update the shape.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
argv = sys.argv[sys.argv.index('--') + 1:]
preview = None
if '--preview' in argv:
    i = argv.index('--preview'); preview = Path(argv[i + 1]); argv = argv[:i] + argv[i + 2:]
target_file, shape_name = Path(argv[0]), argv[1]
if not target_file.is_absolute(): target_file = (ROOT / target_file).resolve()
target_name = argv[2] if len(argv) > 2 else 'MannequinHead'

BLEND_LOW, BLEND_HIGH = 1.47, 1.53   # kit neck below, new head above (metres, Z up)
RELAX_ITER, RELAX = 30, 0.6
FEATURE_FACING, PATCH_RINGS, PATCH_ITER = 0.5, 6, 300
MAP_Z_LOW, MAP_Z_HIGH = 1.60, 1.70   # face mapping: rays leave a vertical axis between these heights  # vertices facing off the new surface, spread out

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(ROOT / 'assets' / 'models' / 'human.glb'))
with bpy.data.libraries.load(str(target_file)) as (src, dst):
    if target_name not in src.objects: raise SystemExit(f'No object "{target_name}" in {target_file}')
    dst.objects = [target_name]
target = dst.objects[0]
bpy.context.scene.collection.objects.link(target)
deps = bpy.context.evaluated_depsgraph_get()
tgt = target.evaluated_get(deps)
tme = tgt.to_mesh()
mw = target.matrix_world
bvh = BVHTree.FromPolygons([mw @ v.co for v in tme.vertices], [p.vertices[:] for p in tme.polygons])


def nearest(points):
    out = np.empty_like(points)
    for i, p in enumerate(points):
        loc, _, _, _ = bvh.find_nearest(Vector(p))
        out[i] = loc if loc is not None else p
    return out


def face_mapping(obj, co, gid, gco, new, w):
    """Where each vertex of the new head should read the face texture: the point of the original kit
    head in the same direction from the head's centre axis (horizontal between the brow and the mouth,
    fanning up over the crown and down under the chin). Painted eyes, nose and mouth then land where they
    look right from outside instead of being stretched with the vertices that were spread over the new
    shape. Returns a UV offset per welded vertex (Blender UV axes), blended out with the neck like the
    move itself. Copies on the UV seam at the back differ by whole tiles, so one offset fits them all."""
    me = obj.data
    uvl = me.uv_layers.active.data
    face = [p for p in me.polygons if obj.material_slots[p.material_index].material
            and obj.material_slots[p.material_index].material.name.split('.')[0] == 'face']
    if not face: return np.zeros((len(gco), 2))
    tri_co = [[co[i] for i in p.vertices] for p in face]
    tri_uv = [[np.array(uvl[li].uv) for li in p.loop_indices] for p in face]
    kit = BVHTree.FromPolygons([Vector(c) for c in co], [p.vertices[:] for p in face])
    vuv = {}
    for p in face:
        for vi, li in zip(p.vertices, p.loop_indices): vuv.setdefault(gid[vi], np.array(uvl[li].uv))
    fz = np.array([c for t in tri_co for c in t])
    band = fz[(fz[:, 2] > 1.64) & (fz[:, 2] < 1.68)]
    cy = (band[:, 1].min() + band[:, 1].max()) / 2
    out = np.zeros((len(gco), 2)); missed = 0
    for g, uv0 in vuv.items():
        if w[g] <= 0: continue
        c = Vector((0.0, cy, float(np.clip(new[g][2], MAP_Z_LOW, MAP_Z_HIGH))))
        d = Vector(new[g]) - c
        if d.length < 1e-6: continue
        loc, _, k, _ = kit.ray_cast(c, d.normalized())
        if loc is None: missed += 1; continue
        a, b, cc = (np.array(v) for v in tri_co[k])
        v0, v1, v2 = b - a, cc - a, np.array(loc) - a
        d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-18: missed += 1; continue
        bv, bw = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
        uv = (1 - bv - bw) * tri_uv[k][0] + bv * tri_uv[k][1] + bw * tri_uv[k][2]
        uv[0] += round(uv0[0] - uv[0])   # same tile as this vertex (seam at the back of the head)
        out[g] = w[g] * (uv - uv0)
    print(f'  face mapping: {len(vuv)} face vertices, {missed} kept their own UVs (no hit)')
    return out


def conform(obj):
    me = obj.data
    if obj.matrix_world != obj.matrix_world.Identity(4):
        raise SystemExit(f'{obj.name} has an object transform; expected mesh space = world space')
    co = np.array([v.co for v in me.vertices])
    # Weld split copies (UV/material seams) so they move together.
    keys = {}
    gid = np.array([keys.setdefault(tuple(np.round(c, 4)), len(keys)) for c in co])
    n = len(keys)
    gco = np.zeros((n, 3)); np.add.at(gco, gid, co); gco /= np.bincount(gid, minlength=n)[:, None]
    nbr = [set() for _ in range(n)]
    for e in me.edges:
        a, b = gid[e.vertices[0]], gid[e.vertices[1]]
        if a != b: nbr[a].add(b); nbr[b].add(a)
    z = gco[:, 2]
    w = np.clip((z - BLEND_LOW) / (BLEND_HIGH - BLEND_LOW), 0, 1); w = w * w * (3 - 2 * w)
    region = np.where(w > 0)[0]
    free = np.array([g for g in region if w[g] >= 1])
    T = gco.copy()
    T[region] = nearest(gco[region])
    # Relax over the surface: features the target lacks (nose, lips, ears) unfold instead of folding.
    # Smooth the *movement* rather than the positions: each vertex moves about as its neighbours do,
    # so the mesh keeps its own spacing (no sliding or bunching) while features the target lacks
    # (nose, lips, ears) are carried along with the surface round them instead of folding.
    nlist = [np.array(sorted(nbr[g])) for g in free]
    for _ in range(RELAX_ITER):
        D = T - gco
        avg = np.array([D[nb].mean(0) if len(nb) else D[g] for g, nb in zip(free, nlist)])
        T[free] = nearest(gco[free] + D[free] + RELAX * (avg - D[free]))
    # Features the new head doesn't have (nose, nostrils, ears) arrive folded: their faces point a
    # different way from the surface they now lie on. Find them (plus a few rings round them, so each
    # patch is a simple disk) and spread their vertices evenly inside the patch's border, which stays
    # put: averaging to convergence with a fixed border can't fold (Tutte), and every step goes back
    # onto the surface.
    tris = [[gid[i] for i in p.vertices] for p in me.polygons]
    tris = [t for t in tris if all(w[g] >= 1 for g in t)]
    is_free = np.zeros(n, bool); is_free[free] = True
    vn = np.zeros((n, 3)); np.add.at(vn, gid, np.array([v.normal for v in me.vertices]))
    vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]
    def facing(g):
        _, tn, _, _ = bvh.find_nearest(Vector(T[g]))
        return 1.0 if tn is None else float(Vector(vn[g]).dot(tn))
    patch = {g for g in free if facing(g) < FEATURE_FACING}
    for _ in range(PATCH_RINGS):
        patch |= {m for g in patch for m in nbr[g] if is_free[m]}
    inner = np.array(sorted(g for g in patch if all(m in patch for m in nbr[g])))  # the border stays fixed
    if len(inner):
        plist = [np.array(sorted(nbr[g])) for g in inner]
        for _ in range(PATCH_ITER):
            T[inner] = nearest(np.array([T[nb].mean(0) for nb in plist]))
    def folded():
        bad = []
        for t in tris:
            p = [Vector(T[g]) for g in t]
            nrm = (p[1] - p[0]).cross(p[2] - p[0])
            _, tn, _, _ = bvh.find_nearest(sum(p, Vector()) / len(p))
            if nrm.length > 1e-12 and tn is not None and nrm.normalized().dot(tn) < 0: bad.append(t)  # collapsed ones have no area
        return bad
    print(f'  spread {len(inner)} vertices of noses/ears flat; {len(folded())} triangles still folded')
    # A few triangles stay folded where the kit mesh doubles back on itself (behind the ear, inside the
    # nostrils): no spreading can lay two layers onto one surface. Collapse each such cluster to a point
    # on the surface, so it has no area left to show.
    for _ in range(10):
        bad = folded()
        if not bad: break
        verts = {g for t in bad for g in t if is_free[g]}
        seen = set()
        for g in verts:
            if g in seen: continue
            stack, cluster = [g], []
            seen.add(g)
            while stack:
                a = stack.pop(); cluster.append(a)
                for m in nbr[a]:
                    if m in verts and m not in seen: seen.add(m); stack.append(m)
            loc, tn, _, _ = bvh.find_nearest(Vector(T[cluster].mean(0)))
            if loc is not None: T[cluster] = np.array(loc)
    print(f'  collapsed what was left; {len(folded())} triangles folded')
    new = gco + w[:, None] * (T - gco)
    # Folded triangles: face normal against the target's outward direction.
    flips = 0
    for poly in me.polygons:
        gs = [gid[i] for i in poly.vertices]
        if min(w[g] for g in gs) < 1: continue
        p = [Vector(new[g]) for g in gs]
        nrm = (p[1] - p[0]).cross(p[2] - p[0])
        c = sum(p, Vector()) / len(p)
        loc, tn, _, _ = bvh.find_nearest(c)
        if tn is not None and nrm.length > 0 and nrm.normalized().dot(tn) < -0.2:
            flips += 1
            if flips <= 8: print('    inward at', tuple(round(v, 3) for v in c), 'was', tuple(round(float(v), 3) for v in gco[gs].mean(0)))
    duv = face_mapping(obj, co, gid, gco, new, w)
    # One row per distinct vertex position (the copies welded above can sit a few hundredths of a mm
    # apart; each row names its own exact position so the Forge and the exporter find it).
    rows, done = [], set()
    for i, c in enumerate(co):
        g = gid[i]
        d = new[g] - gco[g]
        k = tuple(np.round(c, 5))
        if np.abs(d).max() < 1e-6 or k in done: continue
        done.add(k)
        x, y, zz = c
        rows.append([round(float(x), 5), round(float(zz), 5), round(float(-y), 5),
                     round(float(d[0]), 5), round(float(d[2]), 5), round(float(-d[1]), 5),   # Blender -> glTF axes
                     round(float(duv[g][0]), 5), round(float(-duv[g][1]), 5)])               # glTF v runs down
    if preview:
        for i, v in enumerate(me.vertices): v.co = Vector(new[gid[i]])
    print(f'{obj.name}: {len(region)} head/neck vertices fitted, {len(rows)} rows, '
          f'{flips} triangles facing inward, mean move {np.linalg.norm(new - gco, axis=1)[region].mean() * 1000:.1f} mm')
    return rows


shape = {}
for name in ('person_m', 'person_f'):
    obj = bpy.data.objects.get(name)
    if obj: shape[name] = conform(obj)

store = ROOT / 'data' / 'shapes.json'
shapes = json.loads(store.read_text(encoding='utf-8')) if store.is_file() else []
sid = 'shape_' + hashlib.sha1(shape_name.encode()).hexdigest()[:10]
item = {'id': sid, 'name': shape_name, 'parts': sorted(shape), 'vertices': sum(len(r) for r in shape.values()),
        'created': time.strftime('%Y-%m-%d %H:%M'), 'source': str(target_file.relative_to(ROOT)).replace('\\', '/') if target_file.is_relative_to(ROOT) else str(target_file),
        'shape': shape}
shapes = [item] + [s for s in shapes if s.get('id') != sid]
store.parent.mkdir(parents=True, exist_ok=True)
store.write_text(json.dumps(shapes, indent=1), encoding='utf-8')
if preview:
    bpy.data.objects.remove(target)
    bpy.ops.wm.save_as_mainfile(filepath=str(preview))
print(f'CONFORM_OK {sid} "{shape_name}" -> {store}')
