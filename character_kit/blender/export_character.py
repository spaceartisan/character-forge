"""Build a game-ready, single-person rigged GLB from the original human.glb.
Run with Blender headless: blender -b -P export_character.py -- config.json result.glb
The original mesh, rig and animation data are reused verbatim; only outfit, materials
and unselected objects change. No third-party Blender add-ons required.
"""
import bpy
import json
import os
import sys
from pathlib import Path

config_path, out_file = sys.argv[sys.argv.index('--')+1:][:2]
cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))
root = Path(__file__).resolve().parents[2]
base = root / 'assets' / 'models' / 'human.glb'
if not base.is_file():
    raise RuntimeError('No base model found: '+str(base))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(base))

sex = cfg.get('body', 'm')
outfit = cfg.get('outfit', 'suit')
hair = cfg.get('hair', 'short')
if sex not in ('m','f'): raise ValueError('Invalid body')
if outfit not in ('suit','trench','shirt','dress'): raise ValueError('Invalid outfit')
if hair not in ('none','short','long'): raise ValueError('Invalid hairstyle')
# Same rule as the game (character.gd) and static/character-parts.mjs: the dress has its own
# legs and shoes, so no legs mesh goes under it; the trench wears legs_coat.
keep = {f'person_{sex}', f'outfit_{outfit}'}
if outfit == 'trench': keep.add('legs_coat')
elif outfit != 'dress': keep.add('legs_m')
if hair != 'none': keep.add('hair_'+hair)
if cfg.get('hat'): keep.add('hat')
if cfg.get('glasses'): keep.add('glasses')

for obj in list(bpy.data.objects):
    if obj.type == 'MESH' and obj.name not in keep:
        bpy.data.objects.remove(obj, do_unlink=True)
    elif obj.type in ('CAMERA', 'LIGHT'):
        bpy.data.objects.remove(obj, do_unlink=True)

def apply_shape(obj, rows):
    """Mesh edits from the Forge's Edit shape mode. Each row is [x, y, z, dx, dy, dz] in the part's glTF
    mesh space (Y up); every vertex at x, y, z (split copies included) moves by dx, dy, dz. Normals
    round the moved vertices are recomputed smooth; the rest keep the model's own."""
    from mathutils import Vector, kdtree
    me = obj.data
    tree = kdtree.KDTree(len(me.vertices))
    for v in me.vertices: tree.insert(v.co, v.index)
    tree.balance()
    moved = set()
    for x, y, z, dx, dy, dz in rows:
        for _, i, _ in tree.find_range(Vector((x, -z, y)), 2e-4):   # glTF Y-up -> Blender Z-up
            me.vertices[i].co += Vector((dx, -dz, dy))
            moved.add(i)
    if not moved:
        print('shape edits matched no vertices on', obj.name); return
    me.update()
    # Smooth normals over the moved area, shared by vertices that sit at the same place (UV seams).
    key = lambda co: (round(co.x, 4), round(co.y, 4), round(co.z, 4))
    ring = set(moved)
    for poly in me.polygons:
        if any(i in moved for i in poly.vertices): ring.update(poly.vertices)
    acc = {}
    for poly in me.polygons:
        if not any(i in ring for i in poly.vertices): continue
        n = poly.normal * poly.area
        for i in poly.vertices:
            acc.setdefault(key(me.vertices[i].co), Vector()).__iadd__(n)
    loops = [Vector(n.vector) for n in me.corner_normals] if hasattr(me, 'corner_normals') else [l.normal.copy() for l in me.loops]
    for li, loop in enumerate(me.loops):
        if loop.vertex_index in ring:
            n = acc.get(key(me.vertices[loop.vertex_index].co))
            if n is not None and n.length > 1e-12: loops[li] = n.normalized()
    me.normals_split_custom_set(loops)
    print(f'shape: moved {len(moved)} vertices on {obj.name}')

for part, rows in (cfg.get('shape') or {}).items():
    obj = bpy.data.objects.get(part)
    if obj is not None and obj.type == 'MESH': apply_shape(obj, rows)

def linear_rgb(value, fallback):
    """UI hex colours are sRGB; Blender colour sockets are linear."""
    v = str(value or fallback).strip().lstrip('#')
    if len(v)!=6 or any(c not in '0123456789abcdefABCDEF' for c in v):
        v = fallback.lstrip('#')
    def linear(c):
        c = c/255.0
        return c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4
    return tuple(linear(int(v[i:i+2],16)) for i in (0,2,4))

# Dressing rules from data/kit.json (copied from the game's character.gd), passed in by server.py.
rules = cfg['rules']
colors = cfg.get('colors') or {}
fabric = cfg.get('fabric') or {}
face_id = cfg.get('face', 'agent')
if not isinstance(face_id,str) or not face_id.replace('_','').isalnum():
    raise ValueError('Invalid face id')
face_file = root/'assets'/'textures'/f'face_{face_id}.png'
if not face_file.is_file(): raise RuntimeError('Missing face texture: '+str(face_file))

images = {}
def image_for(tex):
    """Texture name from the rules -> packed Blender image (each file loaded once)."""
    if tex == '@face': path = face_file
    else:
        if tex == '@top': tex = fabric.get('top', 'cloth')
        elif tex == '@pants': tex = fabric.get('pants', 'cloth')
        if tex not in ('cloth','suitcloth','skin','rubber','hair'): raise ValueError('Unknown texture '+tex)
        path = root/'assets'/'materials'/f'{tex}.png'
    key = str(path)
    if key not in images:
        img = bpy.data.images.load(key, check_existing=True)
        img.pack()
        images[key] = img
    return images[key]

def build_material(name, rule, tint_hex):
    """Texture x tint, as the game's StandardMaterial3D does (albedo_texture * albedo_color).
    The model's baked vertex colours are exported as COLOR_0, which glTF multiplies in too."""
    old = bpy.data.materials.get(name)
    if old: old.name = name + '_source'   # keep the exported surface names clean ('top', not 'top.001')
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = rule['rough']
    bsdf.inputs['Metallic'].default_value = 0.0
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image_for(rule['tex'])
    tex.extension = 'REPEAT'   # face maps wrap round the head; the seam at the back relies on it
    if rule['tex'] == '@face':
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    else:
        mix = nt.nodes.new('ShaderNodeMix')   # the glTF exporter turns Multiply x colour into baseColorFactor
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        nt.links.new(tex.outputs['Color'], mix.inputs['A'])
        mix.inputs['B'].default_value = (*linear_rgb(tint_hex, '#ffffff'), 1)
        nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat

built = {}
for obj in bpy.data.objects:
    if obj.type != 'MESH': continue
    part_rule = rules['part_surfaces'].get(obj.name)
    for slot in obj.material_slots:
        if not slot.material: continue
        surface = slot.material.name.split('.')[0]
        rule = part_rule or rules['surfaces'].get(surface)
        if not rule: continue
        # Glasses share the 'tie' slot with the suit in the source file; give them their own material.
        mat_name = f'{obj.name}_{surface}' if part_rule else surface
        if mat_name not in built:
            built[mat_name] = build_material(mat_name, rule, colors.get(rule.get('color', surface)))
        slot.material = built[mat_name]

scale = float(cfg.get('scale',1))
if not .75 <= scale <= 1.3: scale=1.0
# Scaling the armature along with its bound objects preserves skinning.
for o in bpy.data.objects:
    if o.parent is None and o.type == 'ARMATURE':
        o.scale=(scale,)*3

out_file = Path(out_file).resolve()
out_file.parent.mkdir(parents=True, exist_ok=True)
# Use animation ACTIONS mode so all of the existing 13 named clips survive.
bpy.ops.export_scene.gltf(filepath=str(out_file), export_format='GLB', export_animations=True,
    export_animation_mode='ACTIONS', export_skins=True,
    export_materials='EXPORT', export_force_sampling=True, export_frame_step=1,
    export_optimize_animation_size=True, export_yup=True,
    export_vertex_color='ACTIVE')
if not out_file.is_file() or out_file.stat().st_size < 10000:
    raise RuntimeError('GLB was not produced')
print('CHARACTER_EXPORT_OK', out_file, out_file.stat().st_size)
