import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import { collectCharacterParts, applyCharacterParts, desiredCharacterParts, CHARACTER_PARTS } from '../static/character-parts.mjs';

// Reconstruct the hierarchy from the real included glTF: the affected parts
// are mesh nodes which Three.js expands into group + primitive children.
const file = fs.readFileSync(new URL('../assets/models/human.glb', import.meta.url));
assert.equal(file.toString('ascii',0,4),'glTF');
const chunkLen = file.readUInt32LE(12);
const gltf=JSON.parse(file.toString('utf8',20,20+chunkLen));
const nodes=[];
for(const info of gltf.nodes){
  const mesh = info.mesh === undefined ? null : gltf.meshes[info.mesh];
  const n = {name: info.name||'', isMesh:Boolean(mesh&&mesh.primitives.length===1), visible:true, children:[],
    getObjectByName(name){ if(this.name===name)return this;for(const c of this.children){const x=c.getObjectByName(name);if(x)return x}return undefined; }};
  if(mesh&&mesh.primitives.length>1){n.children=mesh.primitives.map((_,i)=>({name:`${n.name}_${i}`,isMesh:true,visible:true,children:[],getObjectByName(name){return this.name===name?this:undefined}}));}
  nodes.push(n);
}
for(let i=0;i<gltf.nodes.length;i++){nodes[i].children.push(...(gltf.nodes[i].children||[]).map(j=>nodes[j]));}
const root={name:'Scene',children:gltf.scenes[gltf.scene].nodes.map(i=>nodes[i]),getObjectByName:nodes[0].getObjectByName};
const parts=collectCharacterParts(root);
const initial={body:'m',outfit:'trench',hair:'none',hat:true,glasses:true};

function isEffectivelyVisible(mesh){
  // Whether every ancestor (group, primitive) permits render.
  let visible=false;
  for(const node of parts.values()){
    if(!node.visible)continue;
    if(node===mesh || node.children.includes(mesh)){visible=true;break;}
  }
  return visible;
}

test('all 12 character parts can be found by exported node name',()=>{
 assert.equal(parts.size,CHARACTER_PARTS.length);
 for(const part of CHARACTER_PARTS)assert.ok(parts.has(part),part);
});
test('agent outfit uses multi-primitive groups, not leaf names',()=>{
 assert.ok(!parts.get('person_m').isMesh);
 assert.ok(parts.get('person_m').children.length>=2);
 assert.ok(!parts.get('outfit_trench').isMesh);
 assert.ok(parts.get('outfit_trench').children.length>=3);
 assert.equal(parts.get('outfit_shirt').isMesh,true);
});
test('agent: visible head, body, coat legs, trench, hat, glasses',()=>{
 const info=applyCharacterParts(parts,initial);
 assert.equal(info.visible.length,5);
 for(const id of info.selected){assert.equal(parts.get(id).visible,true,id);for(const mesh of parts.get(id).children)assert.equal(isEffectivelyVisible(mesh),true,mesh.name)}
 for(const [id,p] of parts)if(!info.selected.includes(id))assert.equal(p.visible,false,id);
});
test('changing face body, outfit, hair reveals new part meshes',()=>{
 const info=applyCharacterParts(parts,{body:'f',outfit:'dress',hair:'long',hat:false,glasses:false});
 assert.deepEqual(info.visible,['person_f','outfit_dress','hair_long']);
 assert.equal(parts.get('legs_m').visible,false,'the dress has its own legs; trousers under it poke through');
 assert.equal(parts.get('legs_coat').visible,false);
 assert.equal(parts.get('person_m').visible,false);
 assert.equal(parts.get('person_f').visible,true);
 assert.equal(parts.get('outfit_trench').visible,false);
 assert.equal(parts.get('outfit_dress').visible,true);
});
test('outfit toggles retain a visible body and legs',()=>{
 for(const outfit of ['suit','trench','shirt','dress'])for(const body of ['m','f']){
  const selected=desiredCharacterParts({body,outfit,hair:'short',hat:false,glasses:false});
  assert.ok(selected.has(body==='f'?'person_f':'person_m'));
  assert.equal(applyCharacterParts(parts,{body,outfit,hair:'short',hat:false,glasses:false}).visible.length,outfit==='dress'?3:4);
 }
});
test('missing mandatory groups fails loudly instead of reporting model loaded',()=>{
 const copy=new Map(parts);copy.delete('person_m');
 assert.throws(()=>applyCharacterParts(copy,initial),/person_m/);
});
