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
assert len(j['meshes'])==16, 'Expected the 12 kit meshes plus the Forge garments (T-shirt, tank top, shorts, jeans)'
assert {'rig'} <= set(n.get('name','') for n in j['nodes'])
textures=[t for t in (r/'assets/textures').glob('face_*.png') if '.' not in t.stem]   # skip .prev / .512.bak copies
assert len(textures)>=17, 'Missing included face textures'
for t in textures:
    with Image.open(t) as im:
        assert im.size==(1024,1024),f'Wrong texture size: {t}'
for pid in ('cotton','twill'):
    assert (r/f'assets/textures/print_{pid}.png').is_file(), f'Missing built-in print {pid}'
for part in ('outfit_tshirt','outfit_tank','legs_shorts','legs_jeans'):
    assert (r/f'assets/textures/print_template_{part}.png').is_file(), f'Missing print template for {part}'
for path in ['server.py','static/index.html','static/app.js','static/viewer.js',
             'character_kit/blender/blender_people.py','character_kit/blender/blender_rig.py',
             'character_kit/blender/export_character.py']:
    assert (r/path).is_file(),f'Missing {path}'
print(f'PASS: {len(j["meshes"])} source meshes; {len(j["animations"])} animation clips; 1 rig; {len(textures)} face maps; prints and templates; all project files present.')
