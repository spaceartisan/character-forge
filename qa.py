"""Quick static sanity checks for the included GLB, generated textures and source bundle."""
from pathlib import Path
from PIL import Image
import json,struct
r=Path(__file__).resolve().parent
f=r/'assets/models/human.glb'
assert f.is_file(), 'Missing source GLB'
b=f.read_bytes()
assert b[:4]==b'glTF','Not a GLB'
ln=struct.unpack_from('<I',b,12)[0]
j=json.loads(b[20:20+ln])
assert len(j['skins'])==1
assert len(j['animations'])==13
assert len(j['meshes'])==14, 'Expected the 12 kit meshes plus the two Forge wrap bodies'
assert {'rig'} <= set(n.get('name','') for n in j['nodes'])
textures=[t for t in (r/'assets/textures').glob('face_*.png') if '.' not in t.stem]   # skip .prev / .512.bak copies
assert len(textures)>=17, 'Missing included face textures'
for t in textures:
    with Image.open(t) as im:
        assert im.size==(1024,1024),f'Wrong texture size: {t}'
for name in ('wrap_tee_shorts','wrap_tank_jeans','wrap_template_body_wrap_m','wrap_template_body_wrap_f'):
    with Image.open(r/f'assets/textures/{name}.png') as im:
        assert im.size==(4096,2048),f'Wrong wrap size: {name}'
assert (r/'assets/models/wrap_layouts.npz').is_file(), 'Missing wrap layouts (rebuild the models)'
for path in ['character_kit/wraps/wrap_from_front.py','server.py','static/index.html','static/app.js','static/viewer.js',
             'character_kit/blender/blender_people.py','character_kit/blender/blender_rig.py',
             'character_kit/blender/export_character.py']:
    assert (r/path).is_file(),f'Missing {path}'
print(f'PASS: {len(j["meshes"])} source meshes; {len(j["animations"])} animation clips; 1 rig; {len(textures)} face maps; wraps and templates; all project files present.')
