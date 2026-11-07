"""Character Forge: local web UI for the supplied character_kit.
Usage: python server.py  -> http://127.0.0.1:8765
Everything stays local: photographs, face maps, exported models and presets.
"""
from __future__ import annotations
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image

ROOT = Path(__file__).resolve().parent
KIT = ROOT / 'character_kit'
REF_DIR = KIT / 'faces' / 'references'
TEXTURES = ROOT / 'assets' / 'textures'
MODELS = ROOT / 'assets' / 'models'
DATA = ROOT / 'data'
EXPORTS = ROOT / 'exports'
for d in (REF_DIR, TEXTURES, MODELS, DATA, EXPORTS):
    d.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(KIT / 'faces'))
import faces_from_refs as face_pipeline  # noqa: E402  The original warp/fill engine.

app = FastAPI(title='Character Forge', version='1.0.0')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
app.mount('/textures', StaticFiles(directory=TEXTURES), name='textures')
app.mount('/models', StaticFiles(directory=MODELS), name='models')
app.mount('/materials', StaticFiles(directory=ROOT/'assets'/'materials'), name='materials')
app.mount('/references', StaticFiles(directory=REF_DIR), name='references')

PRESET_FILE = DATA/'characters.json'
SHAPES_FILE = DATA/'shapes.json'   # saved base shapes: geometry edits any character can start from
CUSTOM_FILE = DATA/'custom_faces.json'
SOURCES_FILE = DATA/'sources.json'

FACE_NAMES = {
    'agent':'The Pale Agent', 'fed':'Federal Operative',
    'm1':'Townsman 01', 'm2':'Townsman 02', 'm3':'Local 03', 'm4':'Local 04',
    'm5':'Outdoorsman', 'm6':'Creative', 'm7':'Hardcase',
    'f1':'Woman 01', 'f2':'Woman 02', 'f3':'Local 03', 'f4':'Local 04',
    'f5':'Alternative', 'f6':'Professional', 'f7':'Athletic', 'f8':'Academic',
}

# Dressing rules shared by the viewer and the Blender export (copied from the game's character.gd).
RULES = json.loads((DATA/'kit.json').read_text(encoding='utf-8'))
FABRICS = tuple(RULES['fabrics'])
OUTFITS = ('suit','trench','shirt','dress')
HAIRS = ('none','short','long')

# Colours are tints multiplied over the kit's cloth/skin/rubber textures, exactly as in the game.
# Values below are the game's own looks (character.gd agent_look / fed_look / civ_look).
DEFAULTS = {
    'name':'The Pale Agent', 'face':'agent', 'body':'m', 'outfit':'suit',
    'hair':'none', 'hat':True, 'glasses':True, 'animation':'idle','scale':1,
    'fabric':{'top':'suitcloth','pants':'suitcloth'},
    'colors':{
        'skin':'#c2c9c1', 'hair':'#332419', 'top':'#212125',
        'shirt':'#dbd9cc', 'tie':'#080809', 'pants':'#333338',
        'shoes':'#4c4c4c', 'skirt':'#664c4c','hat':'#212125',
        'band':'#0d0d0e','glasses':'#080809'
    }
}
SEEDS = [
    DEFAULTS,
    {**DEFAULTS,'name':'Bureau Man','face':'fed','hair':'short','glasses':False,'fabric':{'top':'cloth','pants':'cloth'},
        'colors':{**DEFAULTS['colors'],'skin':'#6b4530','hair':'#0f0d0d','top':'#4c5259','shirt':'#ccccc4','tie':'#212b47',
                  'pants':'#47474c','shoes':'#4c3829','hat':'#80808a'}},
    {**DEFAULTS,'name':'Bureau Man in Trench','face':'fed','outfit':'trench','hair':'short','glasses':False,'fabric':{'top':'cloth','pants':'cloth'},
        'colors':{**DEFAULTS['colors'],'skin':'#6b4530','hair':'#0f0d0d','top':'#8f7d59','shirt':'#ccccc4','tie':'#332b21',
                  'pants':'#47474c','shoes':'#4c3829','hat':'#9e8c6b'}},
    {**DEFAULTS,'name':'Townsman','face':'m1','outfit':'shirt','hair':'short','hat':False,'glasses':False,'fabric':{'top':'cloth','pants':'cloth'},
        'colors':{**DEFAULTS['colors'],'skin':'#c9805e','hair':'#33241a','top':'#335780','pants':'#571f1c','shoes':'#664733'}},
    {**DEFAULTS,'name':'Deputy','face':'m4','outfit':'shirt','hair':'short','hat':True,'glasses':False,'fabric':{'top':'cloth','pants':'cloth'},
        'colors':{**DEFAULTS['colors'],'skin':'#ab6942','hair':'#120f0d','top':'#80704a','pants':'#4c422e','shoes':'#664733','hat':'#b2996b'}},
    {**DEFAULTS,'name':'Townswoman','face':'f1','body':'f','outfit':'dress','hair':'long','hat':False,'glasses':False,'fabric':{'top':'cloth','pants':'cloth'},
        'colors':{**DEFAULTS['colors'],'skin':'#d68566','hair':'#61381f','top':'#6b4c75','skirt':'#335780','shoes':'#664733'}},
]

def read_json(path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError): return default

def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(path)

def blender_path():
    options = [os.environ.get('BLENDER'), shutil.which('blender')]
    if os.name == 'nt':
        options += [str(Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Blender Foundation'/f'Blender {v}'/'blender.exe')
                    for v in ('5.2','5.1','5.0','4.5')]
    else:
        options += ['/usr/local/bin/blender','/usr/bin/blender','/opt/blender/blender']
    for x in options:
        if x and Path(x).is_file(): return str(x)
    return None

def face_meta(name):
    filename = TEXTURES/f'face_{name}.png'
    if not filename.is_file(): return None
    skin, hair = RULES['face_skin'].get(name), RULES['face_hair'].get(name)
    if not (skin and hair):
        # Custom face: sample a cheek and the hairline. The user can adjust both in the editor.
        im=Image.open(filename).convert('RGB')
        col=lambda p:'#%02x%02x%02x'%p
        skin = skin or col(im.getpixel(face_pipeline.CHEEK))
        hair = hair or col(im.getpixel(face_pipeline.HAIR))
    return {
        'id':name,'name':FACE_NAMES.get(name, name.replace('_',' ').title()),
        'body':'f' if name.startswith('f') and name!='fed' else 'm',
        'texture':f'/textures/face_{name}.png',
        'skin':skin,'hair':hair,
        'reference': f'/references/{face_pipeline.REFS[name][0]}.png' if name in face_pipeline.REFS else None,
        'custom':name not in face_pipeline.REFS,
    }

PRESET_VERSION = 2   # bump to refresh the built-in presets; the user's own characters are kept

def upgrade_face_textures():
    """Custom faces made before the wrapped 1024 layout: rebake from their saved Face Lab settings, or else
    move the old 512 front projection into the new layout. The old file is kept as face_<id>.512.bak.png."""
    custom=read_json(CUSTOM_FILE,{})
    for path in TEXTURES.glob('face_*.png'):
        fid=path.stem[5:]
        if '.' in fid: continue
        with Image.open(path) as im: size=im.size
        if size==(face_pipeline.TEX,face_pipeline.TEX): continue
        backup=path.with_name(f'face_{fid}.512.bak.png')
        try:
            shutil.copy2(path,backup)
            c=custom.get(fid)
            if c and (REF_DIR/f"{c['source_id']}.png").is_file():
                back=tuple(int(c['backdrop'][i:i+2],16) for i in (1,3,5))
                face_pipeline.build(fid,c['source_id'],tuple(c['box']),[tuple(p) for p in c['points']],back,c['tolerance'])
            else:
                with Image.open(backup) as old: face_pipeline.legacy_to_new(old).save(path)
            print(f'upgraded face texture {fid} to the wrapped layout (old copy: {backup.name})')
        except Exception as ex:
            print('could not upgrade face texture',fid,ex)

def seed_data():
    seeds=[{'id':f'preset-{i}','preset_version':PRESET_VERSION,**p} for i,p in enumerate(SEEDS)]
    saved=read_json(PRESET_FILE,None)
    if saved is None:
        write_json(PRESET_FILE,seeds)
    elif any(p.get('id','').startswith('preset-') and p.get('preset_version')!=PRESET_VERSION for p in saved):
        mine=[p for p in saved if not p.get('id','').startswith('preset-')]
        write_json(PRESET_FILE,mine+seeds)
    if not CUSTOM_FILE.is_file(): write_json(CUSTOM_FILE,{})
    if not SOURCES_FILE.is_file(): write_json(SOURCES_FILE,{})
seed_data()
upgrade_face_textures()

@app.get('/')
def index():
    return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/catalog')
def catalog():
    custom=read_json(CUSTOM_FILE,{})
    face_ids=list(face_pipeline.REFS.keys())+list(custom.keys())
    face_ids=list(dict.fromkeys(face_ids))
    faces=[]
    for fid in face_ids:
        f=face_meta(fid)
        if f:
            if fid in custom:
                f['name']=custom[fid]['name']
                f['reference']='/references/'+custom[fid]['source_id']+'.png'
            faces.append(f)
    return {
        'faces':faces,
        'presets':read_json(PRESET_FILE,[]),
        'shapes':read_json(SHAPES_FILE,[]),
        'sources':read_json(SOURCES_FILE,{}),
        'blender_available':bool(blender_path()),
        'model_available':(MODELS/'human.glb').is_file(),
        'animations':['idle','still','walk','run','agent_walk','talk','phone','sit','cower','reach','cuffed','cast','dead'],
        'outfits':['suit','trench','shirt','dress'],
        # Versioned by file time so a rebuilt model is never served from the browser cache.
        'base_model':'/models/human.glb?v='+str(int((MODELS/'human.glb').stat().st_mtime)) if (MODELS/'human.glb').is_file() else '/models/human.glb',
        'starter':DEFAULTS,
        'rules':RULES,
    }

class SourceUpload(BaseModel):
    filename:str='portrait.png'
    content:str=Field(max_length=30_000_000)

@app.post('/api/references')
def upload_reference(body:SourceUpload):
    try:
        raw=base64.b64decode(body.content.split(',')[-1],validate=True)
        if len(raw)>18*1024*1024: raise ValueError('Image too large (18 MB max)')
        image=Image.open(io.BytesIO(raw))
        image.verify()
        image=Image.open(io.BytesIO(raw)).convert('RGB')
        if image.width>6000 or image.height>6000 or image.width<100 or image.height<100:
            raise ValueError('Image must be between 100 and 6000 pixels per side')
    except Exception as ex:
        raise HTTPException(400, f'Could not read image: {ex}')
    source='upload_'+uuid.uuid4().hex[:12]
    image.save(REF_DIR/f'{source}.png', optimize=True)
    srcs=read_json(SOURCES_FILE,{})
    srcs[source]={'label':Path(body.filename).name[:85], 'width':image.width,'height':image.height}
    write_json(SOURCES_FILE,srcs)
    return {'id':source, 'url':f'/references/{source}.png', 'width':image.width,'height':image.height}

class FaceRender(BaseModel):
    id: str
    name: str='Custom face'
    source_id: str
    box: list[int]
    points: list[list[float]]
    backdrop: str='#ffffff'
    tolerance: int=38

@app.post('/api/faces')
def render_face(body:FaceRender):
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,20}',body.id): raise HTTPException(400,'Face ID must be 2–21 lowercase letters/digits/underscores')
    if body.id in face_pipeline.REFS: raise HTTPException(400,'Built-in face IDs are reserved; save under a new ID')
    if body.source_id not in read_json(SOURCES_FILE,{}): raise HTTPException(400,'Unknown source image')
    if len(body.box)!=4 or len(body.points)!=3 or any(len(p)!=2 for p in body.points):
        raise HTTPException(400,'Provide four crop edges and three landmarks')
    if not re.fullmatch('#[0-9a-fA-F]{6}',body.backdrop): raise HTTPException(400,'Invalid backdrop')
    if not 5<=body.tolerance<=80: raise HTTPException(400,'Tolerance outside the supported range')
    try:
        im=Image.open(REF_DIR/f'{body.source_id}.png')
        x0,y0,x1,y1=body.box
        if not (0<=x0<x1<=im.width and 0<=y0<y1<=im.height): raise ValueError('Crop outside source bounds')
        if x1-x0<40 or y1-y0<40: raise ValueError('Crop is too small')
        coords=[(float(p[0]),float(p[1])) for p in body.points]
        if not all(0<=x<=im.width and 0<=y<=im.height for x,y in coords): raise ValueError('Landmarks outside image')
        back=tuple(int(body.backdrop[i:i+2],16) for i in (1,3,5))
        face_pipeline.build(body.id,body.source_id,tuple(body.box),coords,back,body.tolerance)
    except Exception as ex:
        raise HTTPException(400,f'Face processing failed: {ex}')
    custom=read_json(CUSTOM_FILE,{})
    custom[body.id]={'name':body.name.strip()[:60] or body.id,'source_id':body.source_id,
        'box':body.box,'points':body.points,'backdrop':body.backdrop,'tolerance':body.tolerance}
    write_json(CUSTOM_FILE, custom)
    f=face_meta(body.id)
    f['name']=custom[body.id]['name']
    f['texture']+='?v='+str(int(time.time()))
    return {'ok':True,'face':f}

@app.post('/api/faces/{face_id}/open')
def open_face_texture(face_id:str):
    """Open a face texture in the system's default image editor (head mode's 'Open texture').
    The viewer reloads the texture when the file changes, so saving shows up straight away."""
    check_face(face_id)
    path=TEXTURES/f'face_{face_id}.png'
    try:
        if os.name=='nt': os.startfile(str(path))  # noqa: S606  local tool, fixed path inside the project
        elif sys.platform=='darwin': subprocess.Popen(['open',str(path)])
        else: subprocess.Popen(['xdg-open',str(path)])
    except OSError as ex:
        raise HTTPException(500,f'Could not open the texture: {ex}')
    return {'ok':True,'file':str(path.relative_to(ROOT)).replace('\\','/')}

# ---- Face source mapping: which part of the head takes which view of the reference (head mode)
FACE_ID = re.compile(r'[a-z][a-z0-9_]{0,20}')
BAKE_LOCK = threading.Lock()

def face_sources(fid):
    """How a face is baked: (has a profile view, rebake function) or None if it cannot be rebaked."""
    if fid in face_pipeline.REFS:
        return bool(face_pipeline.PROFILES.get(fid)), lambda m: face_pipeline.build_ref(fid, m)
    c=read_json(CUSTOM_FILE,{}).get(fid)
    if c and (REF_DIR/f"{c['source_id']}.png").is_file():
        back=tuple(int(c['backdrop'][i:i+2],16) for i in (1,3,5))
        return False, lambda m: face_pipeline.build(fid,c['source_id'],tuple(c['box']),[tuple(p) for p in c['points']],back,c['tolerance'],mapping=m)
    return None

def check_face(fid):
    if not FACE_ID.fullmatch(fid): raise HTTPException(400,'Invalid face')
    if not (TEXTURES/f'face_{fid}.png').is_file(): raise HTTPException(404,'Face texture missing')

@app.get('/api/faces/{face_id}/mapping')
def get_face_mapping(face_id:str):
    check_face(face_id)
    src=face_sources(face_id)
    return {'mapping':face_pipeline.mapping_for(face_id),'default':face_pipeline.clean_mapping(None),
            'regions':[{'id':k,'label':v} for k,v in face_pipeline.REGIONS],'sources':list(face_pipeline.SOURCES),
            'has_profile':bool(src and src[0]),'can_rebake':src is not None,
            'saved':face_id in face_pipeline.load_mappings()}

@app.get('/api/faces/{face_id}/regions.png')
def face_regions_png(face_id:str, m:str=''):
    """The regions coloured by source over the face texture: a live preview before rebaking."""
    check_face(face_id)
    try: mapping=json.loads(m) if m else face_pipeline.mapping_for(face_id)
    except ValueError: raise HTTPException(400,'Invalid mapping')
    with Image.open(TEXTURES/f'face_{face_id}.png') as tex:
        img=face_pipeline.region_preview(mapping if isinstance(mapping,dict) else None, tex)
    buf=io.BytesIO(); img.save(buf,'PNG')
    return Response(buf.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})

class MappingWrite(BaseModel):
    mapping:dict

@app.post('/api/faces/{face_id}/mapping')
def save_face_mapping(face_id:str, body:MappingWrite):
    """Save the face's source mapping and rebake its texture. The previous texture is kept as face_<id>.prev.png."""
    check_face(face_id)
    src=face_sources(face_id)
    if src is None: raise HTTPException(400,'This face has no saved reference to rebake from')
    mapping=face_pipeline.clean_mapping(body.mapping)
    path=TEXTURES/f'face_{face_id}.png'
    with BAKE_LOCK:
        shutil.copy2(path,path.with_name(f'face_{face_id}.prev.png'))
        try:
            src[1](mapping)
        except Exception as ex:
            raise HTTPException(400,f'Rebake failed: {ex}')
        saved=face_pipeline.load_mappings()
        if mapping==face_pipeline.clean_mapping(None): saved.pop(face_id,None)
        else: saved[face_id]=mapping
        write_json(face_pipeline.MAPPINGS_FILE,saved)
    f=face_meta(face_id)
    f['texture']+='?v='+str(int(time.time()*1000))
    return {'ok':True,'face':f,'mapping':mapping,'backup':f'face_{face_id}.prev.png'}

# ---- Brush touch-ups (head mode): paint, smudge and blur straight onto the 3D head
class PaintWrite(BaseModel):
    image:str          # base64 PNG: the whole touched-up texture
    mask:str=''        # base64 PNG (greyscale): how strongly each texel was touched, kept for rebakes

def decode_png(data, mode):
    try:
        with Image.open(io.BytesIO(base64.b64decode(data.split(',')[-1]))) as im:
            return im.convert(mode)
    except Exception:
        raise HTTPException(400,'Invalid image data')

@app.post('/api/faces/{face_id}/paint')
def save_face_paint(face_id:str, body:PaintWrite):
    """Save brush touch-ups. The texture is replaced (previous kept as face_<id>.prev.png) and the touched
    texels are stored as face_<id>.touch.png, which every later rebake lays back on top."""
    check_face(face_id)
    size=(face_pipeline.TEX,face_pipeline.TEX)
    img=decode_png(body.image,'RGB')
    if img.size!=size: raise HTTPException(400,f'Texture must be {size[0]}x{size[1]}')
    path=TEXTURES/f'face_{face_id}.png'
    touch=path.with_name(f'face_{face_id}.touch.png')
    with BAKE_LOCK:
        shutil.copy2(path,path.with_name(f'face_{face_id}.prev.png'))
        img.save(path)
        if body.mask:
            mask=decode_png(body.mask,'L')
            if mask.size!=size: raise HTTPException(400,'Mask size does not match the texture')
            if mask.getbbox():
                layer=img.convert('RGBA'); layer.putalpha(mask); layer.save(touch)
            elif touch.is_file(): touch.unlink()
    f=face_meta(face_id)
    f['texture']+='?v='+str(int(time.time()*1000))
    return {'ok':True,'face':f,'backup':f'face_{face_id}.prev.png','touch':touch.is_file()}

@app.post('/api/faces/{face_id}/paint/clear')
def clear_face_paint(face_id:str):
    """Drop every saved touch-up and rebake the face from its reference."""
    check_face(face_id)
    src=face_sources(face_id)
    if src is None: raise HTTPException(400,'This face has no saved reference to rebake from, so its touch-ups are part of the texture')
    path=TEXTURES/f'face_{face_id}.png'
    with BAKE_LOCK:
        shutil.copy2(path,path.with_name(f'face_{face_id}.prev.png'))
        touch=path.with_name(f'face_{face_id}.touch.png')
        if touch.is_file(): touch.unlink()
        try: src[1](face_pipeline.mapping_for(face_id))
        except Exception as ex: raise HTTPException(400,f'Rebake failed: {ex}')
    f=face_meta(face_id)
    f['texture']+='?v='+str(int(time.time()*1000))
    return {'ok':True,'face':f,'backup':f'face_{face_id}.prev.png'}

# ---- Base shapes: a character's geometry edits saved by name, for other characters to start from
class ShapeWrite(BaseModel):
    name:str
    shape:dict

@app.post('/api/shapes')
def save_shape(body:ShapeWrite):
    shape=clean_shape(body.shape)
    if not shape: raise HTTPException(400,'There are no shape edits to save')
    name=re.sub(r'\s+',' ',body.name).strip()[:60] or 'Shape'
    shapes=read_json(SHAPES_FILE,[])
    item={'id':'shape_'+uuid.uuid4().hex[:10],'name':name,'parts':sorted(shape),'vertices':sum(len(r) for r in shape.values()),
          'created':time.strftime('%Y-%m-%d %H:%M'),'shape':shape}
    shapes.insert(0,item)
    write_json(SHAPES_FILE,shapes[:200])
    return {'shape':item,'shapes':shapes[:200]}

@app.delete('/api/shapes/{shape_id}')
def delete_shape(shape_id:str):
    shapes=read_json(SHAPES_FILE,[])
    left=[s for s in shapes if s.get('id')!=shape_id]
    if len(left)==len(shapes): raise HTTPException(404,'No such shape')
    write_json(SHAPES_FILE,left)
    return {'shapes':left}

class PresetWrite(BaseModel):
    character:dict

@app.post('/api/presets')
def save_preset(body:PresetWrite):
    obj=normalize_character(body.character)
    profiles=read_json(PRESET_FILE,[])
    new_id='char_'+uuid.uuid4().hex[:10]
    profiles.insert(0,{'id':new_id,**obj})
    write_json(PRESET_FILE, profiles[:200])
    return {'id':new_id,'count':len(profiles)}

@app.delete('/api/presets/{preset_id}')
def delete_preset(preset_id:str):
    profiles=read_json(PRESET_FILE,[])
    remaining=[p for p in profiles if p.get('id')!=preset_id]
    if len(remaining)==len(profiles):raise HTTPException(404,'Character not found')
    write_json(PRESET_FILE,remaining)
    return {'ok':True}

def normalize_character(p):
    if not isinstance(p,dict): raise HTTPException(400,'Invalid character')
    cfg={**DEFAULTS,**p}
    for k,allowed in [('body',('m','f')),('outfit',OUTFITS),('hair',HAIRS)]:
        if cfg[k] not in allowed: raise HTTPException(400,f'Invalid {k}')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,20}',str(cfg.get('face',''))): raise HTTPException(400,'Invalid face')
    if not (TEXTURES/f"face_{cfg['face']}.png").is_file(): raise HTTPException(400,'Face texture missing')
    cfg['hat']=bool(cfg.get('hat'))
    cfg['glasses']=bool(cfg.get('glasses'))
    cfg['name']=str(cfg.get('name') or 'Character')[:80]
    try: cfg['scale']=float(cfg.get('scale',1))
    except (ValueError,TypeError): cfg['scale']=1
    cfg['scale']=max(.75,min(1.3,cfg['scale']))
    fabric={**DEFAULTS['fabric'],**(cfg.get('fabric') or {})}
    cfg['fabric']={k:(fabric[k] if fabric[k] in FABRICS else DEFAULTS['fabric'][k]) for k in DEFAULTS['fabric']}
    given=cfg.get('colors') or {}
    colors={**DEFAULTS['colors'],**given}
    if 'lens' in given and 'glasses' not in given: colors['glasses']=given['lens']  # v1.1 name
    cfg['colors']={k:(colors[k] if isinstance(colors[k],str) and re.fullmatch('#[a-fA-F0-9]{6}',colors[k]) else v)
                   for k,v in DEFAULTS['colors'].items()}
    cfg['shape']=clean_shape(cfg.get('shape'))
    out={k:cfg[k] for k in ('name','face','body','outfit','hair','hat','glasses','scale','animation','fabric','colors')}
    if cfg['shape']:
        out['shape']=cfg['shape']
        base=cfg.get('shape_base')
        if isinstance(base,str) and re.fullmatch(r'shape_[a-f0-9]{10}',base): out['shape_base']=base
    return out

SHAPE_PARTS = {'person_m','person_f','legs_m','legs_coat','outfit_suit','outfit_trench','outfit_shirt','outfit_dress',
               'hair_short','hair_long','hat','glasses'}
def clean_shape(shape):
    """Mesh edits made in the Forge: {part: [[x, y, z, dx, dy, dz], ...]}, where x, y, z is a vertex's original
    position in the part's glTF mesh space and dx, dy, dz how far it moved (metres)."""
    if not isinstance(shape,dict): return {}
    out={}
    for part,rows in shape.items():
        if part not in SHAPE_PARTS or not isinstance(rows,list): continue
        clean=[]
        for r in rows[:30000]:
            if not (isinstance(r,(list,tuple)) and len(r)==6): continue
            try: v=[float(x) for x in r]
            except (TypeError,ValueError): continue
            if not all(abs(x)<3 for x in v[:3]) or not all(abs(x)<.5 for x in v[3:]): continue
            clean.append([round(x,5) for x in v])
        if clean: out[part]=clean
    return out

@app.post('/api/rebuild')
def rebuild_source_model():
    """Rebuild the supplied procedural geometry without needing a Godot project."""
    blender=blender_path()
    if not blender: raise HTTPException(503,'Blender not found')
    cmd=[blender,'-b','-noaudio','-P',str(KIT/'blender'/'blender_people.py'),'--',str(MODELS)]
    try: proc=subprocess.run(cmd,capture_output=True,text=True,timeout=300,cwd=str(ROOT),env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
    except subprocess.TimeoutExpired: raise HTTPException(504,'Model rebuild timed out')
    if proc.returncode !=0 or 'BLENDER_DONE' not in proc.stdout:
        raise HTTPException(500,'Model rebuild failed: '+(proc.stderr[-1200:]+'\n'+proc.stdout[-1000:]).strip())
    return {'ok':True,'bytes':(MODELS/'human.glb').stat().st_size}

class ExportRequest(BaseModel):
    character:dict
    mode:str='glb'

GODOT_ADDON = KIT/'godot'/'addons'/'character_forge'

def godot_import_settings():
    """Import settings Godot reads from the .import file beside a glTF: which clips loop
    (a glTF file cannot store that), and the opt-in for the Character Forge addon's shading fix."""
    anims = ',\n'.join(f'"{a}": {{\n"settings/loop_mode": 1\n}}' for a in RULES['loop'])
    return ('[remap]\n\nimporter="scene"\nimporter_version=1\ntype="PackedScene"\n\n[params]\n\n'
            'character_forge/vertex_shading=true\n'
            '_subresources={\n"animations": {\n' + anims + '\n}\n}\n')

GODOT_README = '''Character Forge character: {name}

Rigged glTF 2.0 model: one outfit, the kit's 17-bone skeleton and 13 animations
(idle, still, walk, run, agent_walk, talk, phone, sit, cower, reach, cuffed, cast, dead).
Textures are embedded in the .glb. The face PNG is included separately for editing.

INSTALL IN GODOT 4.x
1. Copy the addons/ folder into your project root, once per project, then enable
   "Character Forge" under Project > Project Settings > Plugins.
   It fixes a Godot import quirk: without it, the first surface of each mesh (face, coat,
   trousers, hat, hair) loses the model's baked shading and looks flat.
2. Copy the {stem}/ folder anywhere in your project. Keep {stem}.glb.import next to the
   .glb. It marks which animations loop and turns on the addon's fix for this model.
3. If Godot imported the model before you enabled the addon, select the .glb and click
   Reimport in the Import dock.

character.json holds the settings this character was built from.
'''

@app.post('/api/export')
def export_character(body:ExportRequest):
    blender=blender_path()
    if not blender: raise HTTPException(503, 'Blender not found. Set BLENDER to the Blender executable in your environment or run.bat.')
    if not (MODELS/'human.glb').is_file(): raise HTTPException(503,'Source human.glb missing. Rebuild the base model first.')
    if body.mode not in ('glb','zip'): raise HTTPException(400,'Invalid export mode')
    char=normalize_character(body.character)
    stem=re.sub(r'[^a-zA-Z0-9_-]+','_',char['name']).strip('_')[:55] or 'character'
    uid=uuid.uuid4().hex[:7]
    output=EXPORTS/f'{stem}_{uid}.glb'
    cfgfile=EXPORTS/f'_cfg_{uid}.json'
    cfgfile.write_text(json.dumps({**char,'rules':RULES}),encoding='utf-8')
    cmd=[blender,'-b','-noaudio','-P',str(KIT/'blender'/'export_character.py'),'--',str(cfgfile),str(output)]
    try:
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=240, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        raise HTTPException(504,'Blender export timed out')
    finally:
        cfgfile.unlink(missing_ok=True)
    if proc.returncode!=0 or not output.is_file() or 'CHARACTER_EXPORT_OK' not in proc.stdout:
        raise HTTPException(500,'Blender failed: '+(proc.stderr[-1200:]+'\n'+proc.stdout[-1600:]).strip())
    if body.mode=='glb':
        return FileResponse(output,filename=f'{stem}.glb',media_type='model/gltf-binary')
    zipfile_path=EXPORTS/f'{stem}_{uid}.zip'
    with zipfile.ZipFile(zipfile_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(output,f'{stem}/{stem}.glb')
        z.write(TEXTURES/f"face_{char['face']}.png",f'{stem}/face_{char["face"]}.png')
        z.writestr(f'{stem}/character.json',json.dumps(char,indent=2))
        z.writestr(f'{stem}/{stem}.glb.import',godot_import_settings())
        z.writestr('README.txt', GODOT_README.format(name=char['name'], stem=stem))
        for f in sorted(GODOT_ADDON.iterdir()):
            if f.is_file(): z.write(f, f'addons/character_forge/{f.name}')
    return FileResponse(zipfile_path,filename=f'{stem}_godot_ready.zip',media_type='application/zip')

if __name__=='__main__':
    import uvicorn
    uvicorn.run('server:app',host='127.0.0.1',port=int(os.getenv('PORT','8765')),reload=False)
