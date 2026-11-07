/* Character Forge — UI and asset pipeline. No build step required. */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const fallback = {name:'The Pale Agent',face:'agent',body:'m',outfit:'suit',hair:'none',hat:true,glasses:true,animation:'idle',scale:1,fabric:{top:'suitcloth',pants:'suitcloth'},colors:{skin:'#c2c9c1',hair:'#332419',top:'#212125',shirt:'#dbd9cc',tie:'#080809',pants:'#333338',shoes:'#4c4c4c',skirt:'#664c4c',hat:'#212125',band:'#0d0d0e',glasses:'#080809'}};
// Fill gaps in characters saved by older versions (no fabric, 'lens' instead of 'glasses').
function upgrade(c){const base=structuredClone(catalog?.starter||fallback);const colors={...base.colors,...(c.colors||{})};if(c.colors?.lens&&!c.colors?.glasses)colors.glasses=c.colors.lens;delete colors.lens;const {id,preset_version,...plain}=c;return {...base,...structuredClone(plain),fabric:{...base.fabric,...(c.fabric||{})},colors}}
let catalog = null, chosen = structuredClone(fallback), activeFaceFilter='all', activeTab='appearance';
let viewer=null, playing=true, faceLab=null, notifyTimeout=0;
const PALETTE_LABELS = {skin:'Hands / skin',hair:'Hair',top:'Outer garment',shirt:'Shirt & collar',tie:'Tie',pants:'Trousers',shoes:'Shoes',skirt:'Skirt',hat:'Hat felt',band:'Hat band',glasses:'Glasses'};
const safeText=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const uid=()=>Math.random().toString(36).slice(2,10);
function toast(msg,isError=false){const el=$('#toast'); el.textContent=msg;el.classList.toggle('error',isError);el.classList.add('visible');clearTimeout(notifyTimeout);notifyTimeout=setTimeout(()=>el.classList.remove('visible'),4800)}
async function api(path,opts={}) {const r=await fetch(path,{...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}});if(!r.ok){let message='Request failed';try{const d=await r.json();message=d.detail||message}catch{}throw new Error(typeof message==='string'?message:JSON.stringify(message))}return r.json()}
function faceById(id){return catalog?.faces.find(f=>f.id===id)}
function modelChange(){try{const v=viewer?.update(chosen);if(v)$('#meshStatus').textContent=`${v.visible.length} PARTS VISIBLE`;setStatus('LIVE MATERIAL & OUTFIT PREVIEW')}catch(e){toast('Preview issue: '+e.message,true);console.error(e)}}
function setStatus(text){$('#bottomStatus').textContent=text}
function dirty(){modelChange(); $('#crumbName').textContent=chosen.name}
function chooseFace(id){const f=faceById(id);if(!f)return;if(paintFace&&paintFace!==id&&!closePaintPanel())return;if(mapState&&mapState.face!==id)closeMapPanel();chosen.face=f.id;chosen.body=f.body;chosen.colors.skin=f.skin;chosen.colors.hair=f.hair; if(id==='agent'){chosen.outfit='suit';chosen.hair='none';chosen.hat=true;chosen.glasses=true;chosen.fabric={top:'suitcloth',pants:'suitcloth'}} else if(id==='fed'){chosen.outfit='suit';chosen.hair='short';chosen.glasses=false;chosen.fabric={top:'cloth',pants:'cloth'}} else if(chosen.body==='f'&&chosen.outfit!=='dress'&&chosen.hair==='none'){chosen.hair='long'} else if(chosen.face!==id){ /* Keep outfit otherwise */ }
chosen.name=f.name;syncControls();dirty();updateHeadPath()}
function faceResults(){const q=$('#faceSearch').value.trim().toLowerCase();return catalog.faces.filter(f=>{const filter=activeFaceFilter==='all'||(activeFaceFilter==='custom'?f.custom:f.body===activeFaceFilter);return filter&&(`${f.name} ${f.id}`).toLowerCase().includes(q)})}
function renderFaceGrid(){if(!catalog)return;let list=faceResults();$('#faceCount').textContent=catalog.faces.length;$('#faceGrid').innerHTML=list.map(f=>`<button class="face-tile ${f.id===chosen.face?'active':''}" data-face="${safeText(f.id)}" title="${safeText(f.name)}"><img loading="lazy" src="${safeText(f.texture)}" alt="${safeText(f.name)}"><span class="tile-label">${safeText(f.name)}</span><span class="tile-id">${safeText(f.id)} ${f.custom?'· CUSTOM':''}</span></button>`).join('')||'<div class="loading-cards">No matching faces.</div>'; $$('.face-tile').forEach(t=>t.addEventListener('click',()=>chooseFace(t.dataset.face)));}
function syncControls(){renderBaseShape();
 $('#characterName').textContent=chosen.name;
 $('#crumbName').textContent=chosen.name;
 $('#hatToggle').checked=chosen.hat;$('#glassesToggle').checked=chosen.glasses;
 $('#scaleInput').value=chosen.scale;$('#scaleLabel').textContent=Number(chosen.scale).toFixed(2)+'×';
 $('#animationSelect').value=chosen.animation;
 $$('[data-body]').forEach(x=>x.classList.toggle('active',x.dataset.body===chosen.body));
 $$('[data-outfit]').forEach(x=>x.classList.toggle('active',x.dataset.outfit===chosen.outfit));
 $$('[data-hair]').forEach(x=>x.classList.toggle('active',x.dataset.hair===chosen.hair));
 $$('[data-clip]').forEach(x=>x.classList.toggle('active',x.dataset.clip===chosen.animation));
 $$('.color-field input').forEach(i=>{i.value=chosen.colors[i.dataset.color]||'#ffffff';i.closest('.color-field').querySelector('.hex-label').textContent=i.value.toUpperCase()});
 $$('[data-fabric]').forEach(el=>{el.value=chosen.fabric?.[el.dataset.fabric]||'cloth'});
 renderFaceGrid();viewer?.update(chosen);updateHeadPath();
}
// Head mode: close orbit around the head, for checking painted face textures.
let headMode=false;
function setView(v){if(v!=='head'&&paintFace&&!closePaintPanel())return;headMode=v==='head';if(!headMode)closeMapPanel();$$('.view-button').forEach(x=>x.classList.toggle('active',x.dataset.view===v));$('#headTools').classList.toggle('hidden',!headMode);$('#viewLabel').textContent=headMode?'HEAD FOCUS / LIVE VIEW':'PERSPECTIVE / LIVE VIEW';updateHeadPath();viewer?.setView(v)}
function updateHeadPath(){const el=$('#headPath');if(el)el.textContent='Painting: assets/textures/face_'+chosen.face+'.png  ·  saves reload here automatically'}
async function openFaceTexture(){try{const r=await api('/api/faces/'+encodeURIComponent(chosen.face)+'/open',{method:'POST',body:'{}'});toast('Opened '+r.file+' in your image editor. Save it and the preview updates.')}catch(e){toast(e.message,true)}}
// Source mapping (head mode): which view of the reference paints which part of the head.
let mapState=null;
const SOURCE_LABEL={front:'Front',side:'Side',both:'Both',fill:'Fill'};
const SOURCE_HINT={front:'Front view only',side:'Profile only',both:'Blend front and profile',fill:'Neither: smooth fill from around it'};
async function openMapPanel(){
 if(paintFace&&!closePaintPanel())return;
 closeShapePanel();
 const face=chosen.face;
 try{
  const d=await api('/api/faces/'+encodeURIComponent(face)+'/mapping');
  mapState={face,...d,mapping:structuredClone(d.mapping),show:true,busy:false};
  $('#mapSources').classList.add('active');$('#mapSources').setAttribute('aria-expanded','true');
  renderMapPanel();previewMap();
 }catch(e){toast(e.message,true)}
}
function closeMapPanel(){
 if(!mapState)return;mapState=null;clearTimeout(previewMap.t);
 mapPanelEl().classList.add('hidden');$('#mapSources').classList.remove('active');$('#mapSources').setAttribute('aria-expanded','false');
 viewer?.setFaceOverride(null);
}
function mapPanelEl(){let el=$('#mapPanel');if(!el){el=document.createElement('aside');el.id='mapPanel';el.className='map-panel hidden';el.setAttribute('aria-label','Face source mapping');$('.inspector-panel').appendChild(el)}return el}
function renderMapPanel(){
 const s=mapState,m=s.mapping,noSide=!s.has_profile;mapPanelEl();
 $('#mapPanel').innerHTML=`<div class="map-head"><div><span class="map-kicker">FACE ${safeText(s.face.toUpperCase())}</span><h3>Map sources</h3></div><button class="x-close" id="mapClose" aria-label="Close">×</button></div>
 <p class="map-note">Pick which view of the reference paints each part of the head, so two views never draw the same feature.${noSide?' This face has no profile view, so only Front and Fill apply.':''}</p>
 <label class="map-reach">Front view reaches back <strong id="reachValue">${Math.round(m.reach)}°</strong><input type="range" id="reachInput" min="30" max="90" step="1" value="${m.reach}"></label>
 <div class="map-rows">${s.regions.map(r=>`<div class="map-row"><span>${safeText(r.label)}</span><div class="map-seg" role="group" aria-label="${safeText(r.label)}">${s.sources.map(src=>`<button data-region="${r.id}" data-src="${src}" class="src-${src} ${m.regions[r.id]===src?'active':''}" title="${SOURCE_HINT[src]}" ${noSide&&(src==='side'||src==='both')?'disabled':''}>${SOURCE_LABEL[src]}</button>`).join('')}</div></div>`).join('')}</div>
 <label class="map-show"><input type="checkbox" id="mapShow" ${s.show?'checked':''}> Show regions on the head</label>
 <div class="map-legend">${s.sources.map(src=>`<span><i class="src-dot src-${src}"></i>${SOURCE_LABEL[src]}</span>`).join('')}</div>
 <div class="map-actions"><button class="btn btn-ghost small" id="mapDefaults">Defaults</button><button class="btn btn-accent small" id="mapBake" ${s.can_rebake&&!s.busy?'':'disabled'}>${s.busy?'Rebaking…':'Rebake texture'}</button></div>
 <p class="map-note">Rebaking replaces face_${safeText(s.face)}.png with a new bake from the reference; the previous file is kept as face_${safeText(s.face)}.prev.png.${s.can_rebake?'':' This face has no saved reference, so it cannot be rebaked.'}</p>`;
 $('#mapPanel').classList.remove('hidden');
 $('#mapClose').onclick=closeMapPanel;
 $('#reachInput').oninput=e=>{m.reach=Number(e.target.value);$('#reachValue').textContent=m.reach+'°';previewMap()};
 $$('#mapPanel [data-region]').forEach(b=>b.onclick=()=>{m.regions[b.dataset.region]=b.dataset.src;$$(`#mapPanel [data-region="${b.dataset.region}"]`).forEach(x=>x.classList.toggle('active',x===b));previewMap()});
 $('#mapShow').onchange=e=>{s.show=e.target.checked;previewMap()};
 $('#mapDefaults').onclick=()=>{s.mapping=structuredClone(s.default);renderMapPanel();previewMap()};
 $('#mapBake').onclick=rebakeMapped;
}
function previewMap(){
 clearTimeout(previewMap.t);
 previewMap.t=setTimeout(()=>{if(!mapState)return;viewer?.setFaceOverride(mapState.show?'/api/faces/'+encodeURIComponent(mapState.face)+'/regions.png?m='+encodeURIComponent(JSON.stringify(mapState.mapping)):null)},120);
}
async function rebakeMapped(){
 const s=mapState;if(!s||s.busy)return;s.busy=true;renderMapPanel();setStatus('REBAKING FACE '+s.face.toUpperCase()+'…');
 try{
  const r=await api('/api/faces/'+encodeURIComponent(s.face)+'/mapping',{method:'POST',body:JSON.stringify({mapping:s.mapping})});
  const i=catalog.faces.findIndex(f=>f.id===s.face);if(i>=0)catalog.faces[i]={...catalog.faces[i],texture:r.face.texture};
  renderFaceGrid();
  s.mapping=r.mapping;s.show=false;
  if(mapState===s)viewer?.setFaceOverride(null);
  toast('Rebaked face '+s.face+'. The previous texture is kept as '+r.backup+'.');setStatus('FACE '+s.face.toUpperCase()+' REBAKED');
 }catch(e){toast(e.message,true)}
 finally{s.busy=false;if(mapState===s)renderMapPanel()}
}
// Brush touch-ups (head mode): paint, smudge and blur straight onto the 3D head (painter.js).
let painter=null,paintFace=null,paintMod=null;
const hex=c=>'#'+c.map(v=>v.toString(16).padStart(2,'0')).join('');
const unhex=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
async function openPaintPanel(){
 if(!viewer)return toast('The 3D view is not ready',true);
 closeMapPanel();closeShapePanel();
 try{
  paintMod=paintMod||await import('/static/painter.js?v=2.6.0');
  if(!painter)painter=new paintMod.FacePainter(viewer,$('#stage'),{onChange:renderPaintPanel,onPick:()=>{if(painter.tool==='pick')painter.tool='paint'}});
  paintFace=chosen.face;setStatus('LOADING FACE '+paintFace.toUpperCase()+' FOR TOUCH-UPS…');
  await painter.start(paintFace);
  $('#touchUp').classList.add('active');$('#touchUp').setAttribute('aria-expanded','true');
  setStatus('TOUCH-UP: LEFT-DRAG ON THE HEAD TO PAINT, RIGHT-DRAG TO ORBIT');
 }catch(e){paintFace=null;toast('Could not start touch-ups: '+e.message,true)}
}
function closePaintPanel(force){
 if(!paintFace)return true;
 if(!force&&painter.dirty&&!confirm('Discard the unsaved touch-ups on face '+paintFace+'?'))return false;
 painter.stop();paintFace=null;
 $('#paintPanel')?.classList.add('hidden');$('#touchUp').classList.remove('active');$('#touchUp').setAttribute('aria-expanded','false');
 return true;
}
function renderPaintPanel(){
 if(!painter?.active)return;
 let el=$('#paintPanel');if(!el){el=document.createElement('aside');el.id='paintPanel';el.className='map-panel paint-panel hidden';el.setAttribute('aria-label','Brush touch-ups');$('.inspector-panel').appendChild(el)}
 const P=painter,T=paintMod.TOOLS,brush=P.tool!=='pick';
 el.innerHTML=`<div class="map-head"><div><span class="map-kicker">FACE ${safeText(paintFace.toUpperCase())}${P.dirty?' · UNSAVED':''}</span><h3>Touch up</h3></div><button class="x-close" id="paintClose" aria-label="Close">×</button></div>
 <p class="map-note">Left-drag on the head to brush. Right-drag orbits, scroll zooms. The pose holds still while you work.</p>
 <div class="map-seg paint-tools" role="group" aria-label="Brush">${Object.entries(T).map(([k,t])=>`<button data-tool="${k}" class="${P.tool===k?'active':''}" title="${t.label} (${t.key.toUpperCase()})">${t.label}</button>`).join('')}</div>
 <label class="paint-color">Colour <input type="color" id="paintColor" value="${hex(P.color)}"><span>Alt-click the head to pick</span></label>
 <label class="map-reach">Size <strong>${P.size.toFixed(P.size<10?1:0)} mm</strong><input type="range" id="paintSize" min="0" max="100" value="${Math.round(Math.log(P.size)/Math.log(40)*100)}"></label>
 <label class="map-reach ${brush?'':'muted-off'}">Strength <strong>${Math.round(P.strength*100)}%</strong><input type="range" id="paintStrength" min="5" max="100" value="${Math.round(P.strength*100)}" ${brush?'':'disabled'}></label>
 <label class="map-reach ${brush?'':'muted-off'}">Softness <strong>${Math.round(P.softness*100)}%</strong><input type="range" id="paintSoft" min="0" max="100" value="${Math.round(P.softness*100)}" ${brush?'':'disabled'}></label>
 <p class="map-note paint-tip">${{paint:'Paint lays the colour on; one stroke never builds up past its strength.',smudge:'Smudge drags colour along the stroke, like a finger through wet paint.',blur:'Blur softens what it passes over; go over a spot again to soften more.',pick:'Click the head to take its colour, then go back to Paint.'}[P.tool]}</p>
 <div class="map-actions paint-history"><button class="btn btn-ghost small" id="paintUndo" ${P.undo.length?'':'disabled'} title="Ctrl+Z">Undo</button><button class="btn btn-ghost small" id="paintRedo" ${P.redo.length?'':'disabled'} title="Ctrl+Shift+Z">Redo</button></div>
 <div class="map-actions"><button class="btn btn-ghost small" id="paintDiscard" ${P.dirty?'':'disabled'}>Discard</button><button class="btn btn-accent small" id="paintSave" ${P.dirty&&!P.saving?'':'disabled'}>${P.saving?'Saving…':'Save texture'}</button></div>
 <p class="map-note">Saving replaces face_${safeText(paintFace)}.png (the previous file is kept as face_${safeText(paintFace)}.prev.png). Your strokes are also kept in face_${safeText(paintFace)}.touch.png, so rebaking from the reference in Map sources lays them back on top.</p>
 ${P.hadTouch?`<div class="map-actions"><button class="btn btn-ghost small" id="paintClear">Remove all saved touch-ups</button></div>`:''}
 <p class="map-note paint-keys">Keys: P paint · S smudge · B blur · I pick · [ ] size · Ctrl+Z undo</p>`;
 el.classList.remove('hidden');
 $('#paintClose').onclick=()=>closePaintPanel();
 $$('#paintPanel [data-tool]').forEach(b=>b.onclick=()=>{P.tool=b.dataset.tool;renderPaintPanel()});
 $('#paintColor').oninput=e=>{P.color=unhex(e.target.value)};
 $('#paintColor').onchange=()=>{if(P.tool==='pick'){P.tool='paint';renderPaintPanel()}};
 const live=(id,fn)=>{const i=$(id);i.oninput=e=>{fn(Number(e.target.value));const strong=i.parentElement.querySelector('strong');strong.textContent=id==='#paintSize'?P.size.toFixed(P.size<10?1:0)+' mm':Math.round(Number(e.target.value))+'%'}};
 live('#paintSize',v=>{P.size=Math.max(1,Math.pow(40,v/100))});
 live('#paintStrength',v=>{P.strength=v/100});
 live('#paintSoft',v=>{P.softness=v/100});
 $('#paintUndo').onclick=()=>P.undoStep();$('#paintRedo').onclick=()=>P.redoStep();
 $('#paintDiscard').onclick=()=>{while(P.undo.length)P.undoStep();P.redo=[];P.savedAt=P.version;renderPaintPanel()};
 $('#paintSave').onclick=savePaint;
 if($('#paintClear'))$('#paintClear').onclick=clearPaint;
}
function refreshFaceTexture(face,texture){const i=catalog.faces.findIndex(f=>f.id===face);if(i>=0)catalog.faces[i]={...catalog.faces[i],texture};renderFaceGrid()}
async function savePaint(){
 const P=painter;if(!P||P.saving)return;P.saving=true;renderPaintPanel();setStatus('SAVING TOUCH-UPS ON FACE '+paintFace.toUpperCase()+'…');
 try{const r=await P.save(api);refreshFaceTexture(paintFace,r.face.texture);toast('Saved face '+paintFace+'. The previous texture is kept as '+r.backup+'.');setStatus('FACE '+paintFace.toUpperCase()+' TOUCH-UPS SAVED')}
 catch(e){toast('Could not save: '+e.message,true)}
 finally{P.saving=false;renderPaintPanel()}
}
async function clearPaint(){
 const face=paintFace;
 if(!confirm('Remove every saved touch-up on face '+face+' and rebake it from the reference? The current texture is kept as face_'+face+'.prev.png.'))return;
 try{const r=await api('/api/faces/'+encodeURIComponent(face)+'/paint/clear',{method:'POST',body:'{}'});closePaintPanel(true);refreshFaceTexture(face,r.face.texture);toast('Rebaked face '+face+' without touch-ups.');openPaintPanel()}
 catch(e){toast(e.message,true)}
}
// Edit shape: select vertices, edges or faces and move them (shape.js). Edits belong to the character.
let shapeEd=null;
const PART_LABEL={person_m:'Body (masculine)',person_f:'Body (feminine)',legs_m:'Legs',legs_coat:'Legs (coat)',outfit_suit:'Suit',outfit_trench:'Trench coat',outfit_shirt:'Shirt',outfit_dress:'Dress',hair_short:'Short hair',hair_long:'Long hair',hat:'Hat',glasses:'Glasses'};
function openShapePanel(){
 if(!viewer)return toast('The 3D view is not ready',true);
 if(paintFace&&!closePaintPanel())return;
 closeMapPanel();
 shapeEd=viewer.startEdit({onChange:renderShapePanel,onEdit:(part,rows)=>{chosen.shape={...(chosen.shape||{})};if(rows.length)chosen.shape[part]=rows;else delete chosen.shape[part];if(!Object.keys(chosen.shape).length){delete chosen.shape;delete chosen.shape_base}dirty();renderBaseShape()}});
 $('#editShape').classList.add('active');$('#editShape').setAttribute('aria-expanded','true');
 setStatus('EDIT SHAPE: CLICK THE MODEL TO SELECT, G TO MOVE');
 renderShapePanel();
}
function closeShapePanel(){
 if(!shapeEd?.active)return;
 viewer.stopEdit();$('#shapePanel')?.classList.add('hidden');
 $('#editShape').classList.remove('active');$('#editShape').setAttribute('aria-expanded','false');
}
function renderShapePanel(){
 const E=shapeEd;if(!E?.active)return;
 let el=$('#shapePanel');if(!el){el=document.createElement('aside');el.id='shapePanel';el.className='map-panel shape-panel hidden';el.setAttribute('aria-label','Edit shape');$('.inspector-panel').appendChild(el)}
 const n=E.sel.size,part=E.part?.id,g=E.grab,edited=Object.keys(chosen.shape||{});
 const modes=[['vertex','Vertex','1'],['edge','Edge','2'],['face','Face','3']];
 const nudge=[['x','Left','Right'],['y','Down','Up'],['z','Back','Forward']];
 el.innerHTML=`<div class="map-head"><div><span class="map-kicker">${part?safeText((PART_LABEL[part]||part).toUpperCase()):'NO PART SELECTED'}</span><h3>Edit shape</h3></div><button class="x-close" id="shapeClose" aria-label="Close">×</button></div>
 <p class="map-note">Click the model to select. Shift-click adds or removes. Drag still orbits. The rig holds its rest pose while you edit.</p>
 <div class="map-seg shape-modes" role="group" aria-label="Select">${modes.map(([k,l,key])=>`<button data-smode="${k}" class="${E.mode===k?'active':''}" title="${l} select (${key})">${l}</button>`).join('')}</div>
 <div class="shape-count">${n?`${n} vert${n===1?'ex':'ices'} selected`:'Nothing selected'}<span><button class="link-btn" id="shapeGrow" ${n?'':'disabled'}>Grow</button><button class="link-btn" id="shapeClear" ${n?'':'disabled'}>Clear</button></span></div>
 <button class="btn ${g?'btn-ghost':'btn-accent'} small shape-move" id="shapeMove" ${n&&!g?'':'disabled'}>${g?(g.axis?'Moving along '+g.axis.toUpperCase():'Moving…'):'Move (G)'}</button>
 <p class="map-note">${g?'Move the mouse, then click (or Enter) to place it. Right-click or Esc cancels. X, Y or Z locks the move to that axis.':'Move follows the mouse across the screen. X, Y or Z while moving locks it to one axis.'}</p>
 <div class="shape-nudge"><span class="shape-sub">Nudge by <input type="number" id="shapeStep" min="0.1" max="20" step="0.1" value="${E.step}"> mm</span>${nudge.map(([a,neg,pos])=>`<div class="map-seg"><button data-nudge="${a}" data-sign="-1" ${n&&!g?'':'disabled'}>${neg}</button><button data-nudge="${a}" data-sign="1" ${n&&!g?'':'disabled'}>${pos}</button></div>`).join('')}</div>
 <label class="map-show"><input type="checkbox" id="shapeMirror" ${E.mirrorX?'checked':''}> Mirror left / right</label>
 <label class="map-reach">Soft falloff <strong>${E.soft?E.soft+' mm':'off'}</strong><input type="range" id="shapeSoft" min="0" max="60" step="1" value="${E.soft}"></label>
 <p class="map-note">Soft falloff drags nearby vertices along, less the further they are, for smooth bumps instead of spikes.</p>
 <div class="map-actions paint-history"><button class="btn btn-ghost small" id="shapeUndo" ${E.undo.length?'':'disabled'} title="Ctrl+Z">Undo</button><button class="btn btn-ghost small" id="shapeRedo" ${E.redo.length?'':'disabled'} title="Ctrl+Shift+Z">Redo</button></div>
 <div class="map-actions"><button class="btn btn-ghost small" id="shapeResetPart" ${part&&edited.includes(part)?'':'disabled'}>Reset this part</button><button class="btn btn-ghost small" id="shapeResetAll" ${edited.length?'':'disabled'}>Reset all</button></div>
 <p class="map-note">Edits belong to this character: <strong>Save character</strong> keeps them and the exported GLB includes them.${edited.length?' Edited: '+edited.map(x=>safeText(PART_LABEL[x]||x)).join(', ')+'.':''}</p>
 <div class="shape-library"><h4>Base shapes</h4>
 <p class="map-note">Save this character's edits as a base shape to start other characters from it (Customize › Body type).</p>
 <div class="shape-save"><input id="shapeSaveName" maxlength="60" placeholder="Name, e.g. Heavy brow"><button class="btn btn-accent small" id="shapeSave" ${chosen.shape?'':'disabled'}>Save</button></div>
 ${(catalog.shapes||[]).length?`<ul class="shape-list">${catalog.shapes.map(x=>`<li class="${chosen.shape_base===x.id?'current':''}"><span><strong>${safeText(x.name)}</strong><small>${x.vertices} vertices · ${x.parts.map(q=>safeText(PART_LABEL[q]||q)).join(', ')}</small></span><button class="link-btn" data-use-shape="${safeText(x.id)}">${chosen.shape_base===x.id?'In use':'Use'}</button><button class="link-btn danger" data-del-shape="${safeText(x.id)}" aria-label="Delete ${safeText(x.name)}">Delete</button></li>`).join('')}</ul>`:'<p class="map-note">No saved shapes yet.</p>'}</div>
 <p class="map-note paint-keys">Keys: 1 2 3 vertex / edge / face · G move · X Y Z axis · Esc clear · Ctrl+Z undo</p>`;
 el.classList.remove('hidden');
 $('#shapeClose').onclick=closeShapePanel;
 $('#shapeSave').onclick=saveBaseShape;$('#shapeSaveName').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();saveBaseShape()}};
 $$('#shapePanel [data-use-shape]').forEach(b=>b.onclick=()=>useBaseShape(b.dataset.useShape));
 $$('#shapePanel [data-del-shape]').forEach(b=>b.onclick=()=>deleteBaseShape(b.dataset.delShape));
 $$('#shapePanel [data-smode]').forEach(b=>b.onclick=()=>{E.mode=b.dataset.smode;renderShapePanel()});
 $('#shapeGrow').onclick=()=>E.grow();$('#shapeClear').onclick=()=>E.select(null);
 $('#shapeMove').onclick=()=>{const r=$('#stage').getBoundingClientRect();E.mouse??={clientX:r.left+r.width/2,clientY:r.top+r.height/2};E.startGrab()};
 $('#shapeStep').onchange=e=>{E.step=Math.min(20,Math.max(.1,Number(e.target.value)||1))};
 $$('#shapePanel [data-nudge]').forEach(b=>b.onclick=()=>E.nudge(b.dataset.nudge,Number(b.dataset.sign)));
 $('#shapeMirror').onchange=e=>{E.mirrorX=e.target.checked};
 $('#shapeSoft').oninput=e=>{E.soft=Number(e.target.value);e.target.parentElement.querySelector('strong').textContent=E.soft?E.soft+' mm':'off'};
 $('#shapeUndo').onclick=()=>E.undoStep();$('#shapeRedo').onclick=()=>E.redoStep();
 $('#shapeResetPart').onclick=()=>E.resetPart();
 $('#shapeResetAll').onclick=()=>{if(!confirm('Undo every shape edit on this character (back to the kit default)?'))return;delete chosen.shape;delete chosen.shape_base;dirty();E.forget();renderBaseShape()};
}
// Base shapes: a character's geometry edits saved by name, for other characters to start from.
const shapeJSON=x=>JSON.stringify(x||{});
function baseShapeState(){
 const base=(catalog.shapes||[]).find(x=>x.id===chosen.shape_base);
 if(!chosen.shape)return{base:null,edited:false};
 if(!base)return{base:null,edited:true};
 return{base,edited:shapeJSON(base.shape)!==shapeJSON(chosen.shape)};
}
function renderBaseShape(){
 const sel=$('#baseShape');if(!sel||!catalog)return;
 const {base,edited}=baseShapeState(),shapes=catalog.shapes||[];
 sel.innerHTML=`<option value="">Kit default (human.glb)</option>${shapes.map(x=>`<option value="${safeText(x.id)}">${safeText(x.name)}</option>`).join('')}${chosen.shape&&!base?'<option value="@custom">Custom edits (not saved as a shape)</option>':''}`;
 sel.value=base?base.id:chosen.shape?'@custom':'';
 $('#baseShapeHint').textContent=!chosen.shape?'The kit\'s geometry, unchanged. Save shapes from Edit shape to reuse them here.':base?(edited?`Starts from "${base.name}", with further edits on this character.`:`Uses the saved shape "${base.name}".`):'This character has its own shape edits. Save them as a base shape in Edit shape to reuse them.';
}
function useBaseShape(id){
 const item=(catalog.shapes||[]).find(x=>x.id===id);
 const {base,edited}=baseShapeState();
 if(chosen.shape&&(edited||!base)&&!confirm(item?`Replace this character's shape edits with "${item.name}"?`:'Remove all shape edits from this character?'))return renderBaseShape();
 if(item){chosen.shape=structuredClone(item.shape);chosen.shape_base=item.id}else{delete chosen.shape;delete chosen.shape_base}
 shapeEd?.forget();dirty();renderBaseShape();renderShapePanel();
 setStatus(item?'BASE SHAPE: '+item.name.toUpperCase():'BASE SHAPE: KIT DEFAULT');
}
async function saveBaseShape(){
 const input=$('#shapeSaveName'),name=(input?.value||'').trim();
 if(!chosen.shape)return toast('Edit the shape first, then save it',true);
 if(!name){input?.focus();return toast('Give the shape a name',true)}
 try{const r=await api('/api/shapes',{method:'POST',body:JSON.stringify({name,shape:chosen.shape})});catalog.shapes=r.shapes;chosen.shape_base=r.shape.id;renderBaseShape();renderShapePanel();toast(`Saved base shape "${r.shape.name}". Any character can now start from it under Body type.`)}
 catch(e){toast(e.message,true)}
}
async function deleteBaseShape(id){
 const item=(catalog.shapes||[]).find(x=>x.id===id);if(!item)return;
 if(!confirm(`Delete the saved shape "${item.name}"? Characters already using it keep their own copy of the edits.`))return;
 try{const r=await api('/api/shapes/'+encodeURIComponent(id),{method:'DELETE'});catalog.shapes=r.shapes;if(chosen.shape_base===id)delete chosen.shape_base;renderBaseShape();renderShapePanel()}
 catch(e){toast(e.message,true)}
}
function setTab(t){activeTab=t;$$('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===t));$$('.tab-page').forEach(x=>x.classList.toggle('active',x.dataset.page===t))}
function setupControls(){
 $$('.filter').forEach(b=>b.onclick=()=>{activeFaceFilter=b.dataset.filter;$$('.filter').forEach(x=>x.classList.toggle('active',x===b));renderFaceGrid()});
 $('#faceSearch').oninput=renderFaceGrid;
 $$('.tab').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
 $$('[data-body]').forEach(b=>b.onclick=()=>{chosen.body=b.dataset.body;syncControls();dirty()});
 $$('[data-outfit]').forEach(b=>b.onclick=()=>{chosen.outfit=b.dataset.outfit;syncControls();dirty()});
 $$('[data-hair]').forEach(b=>b.onclick=()=>{chosen.hair=b.dataset.hair;syncControls();dirty()});
 $('#hatToggle').onchange=e=>{chosen.hat=e.target.checked;dirty()};
 $('#glassesToggle').onchange=e=>{chosen.glasses=e.target.checked;dirty()};
 $('#scaleInput').oninput=e=>{chosen.scale=Number(e.target.value);$('#scaleLabel').textContent=chosen.scale.toFixed(2)+'×';dirty()};
 const name=$('#characterName');name.onblur=()=>{const value=name.textContent.replaceAll('\n',' ').trim().slice(0,80);chosen.name=value||'Character';name.textContent=chosen.name;$('#crumbName').textContent=chosen.name};name.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();name.blur()}};
 $$('.view-button').forEach(b=>b.onclick=()=>setView(b.dataset.view));
 $$('[data-angle]').forEach(b=>b.onclick=()=>viewer?.headAngle(b.dataset.angle));
 $('#headFlat').onchange=e=>viewer?.setHeadOptions({flat:e.target.checked});
 $('#headHideHair').onchange=e=>viewer?.setHeadOptions({hideHair:e.target.checked});
 $('#openFaceTexture').onclick=openFaceTexture;
 $('#mapSources').onclick=()=>mapState?closeMapPanel():openMapPanel();
 $('#touchUp').onclick=()=>paintFace?closePaintPanel():openPaintPanel();
 $('#baseShape').onchange=e=>useBaseShape(e.target.value);
 $('#editShape').onclick=()=>shapeEd?.active?closeShapePanel():openShapePanel();
 window.addEventListener('beforeunload',e=>{if(painter?.active&&painter.dirty){e.preventDefault();e.returnValue=''}});
 $('#zoomIn').onclick=()=>viewer?.zoom(-.35);$('#zoomOut').onclick=()=>viewer?.zoom(.35);$('#resetView').onclick=()=>setView(headMode?'head':'front');
 $('#playToggle').onclick=()=>{playing=!playing;viewer?.setPlaying(playing);$('#playToggle').textContent=playing?'❚❚':'▶'};
 $('#animationSelect').onchange=e=>selectClip(e.target.value);
 $('#speedRange').oninput=e=>{$('#speedLabel').textContent=Number(e.target.value).toFixed(2)+'×';viewer?.setSpeed(Number(e.target.value))};
 $('#paletteReset').onclick=()=>{const f=faceById(chosen.face);chosen.colors=structuredClone((catalog?.starter||fallback).colors);if(f){chosen.colors.skin=f.skin;chosen.colors.hair=f.hair}syncControls();dirty()};
 $$('[data-fabric]').forEach(el=>el.onchange=e=>{chosen.fabric={...chosen.fabric,[e.target.dataset.fabric]:e.target.value};dirty()});
 $('#resetCharacter').onclick=()=>{chosen=structuredClone(catalog?.starter||fallback);syncControls();dirty();toast('Character reset to default')};
 $('#exportTop').onclick=showExport;$('#exportBottom').onclick=showExport;
 $('#saveTop').onclick=savePreset;$('#savePreset').onclick=savePreset;
 $('#addFace').onclick=showFaceLab;$('#navFaces').onclick=showFaceLab;
 $('#navStudio').onclick=()=>{closeModal();setTab('appearance')};
 $('#navLibrary').onclick=showSaved;$('#navHelp').onclick=showHelp;
 $('#modalBackdrop').addEventListener('click',e=>{if(e.target.id==='modalBackdrop')closeModal()});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});
 const colorPanel=$('#colorFields'); colorPanel.innerHTML=Object.entries(PALETTE_LABELS).map(([k,label])=>`<div class="color-field"><label for="color_${k}">${label}</label><span class="hex-label"></span><input id="color_${k}" type="color" data-color="${k}" /></div>`).join('');
 $$('.color-field input').forEach(el=>el.addEventListener('input',e=>{chosen.colors[e.target.dataset.color]=e.target.value;e.target.closest('.color-field').querySelector('.hex-label').textContent=e.target.value.toUpperCase();dirty()}));
}
function selectClip(name){chosen.animation=name;$('#animationSelect').value=name;$$('[data-clip]').forEach(b=>b.classList.toggle('active',b.dataset.clip===name));viewer?.play(name);setStatus(`ANIMATION: ${name.toUpperCase()}`)}
function setupClips(){const list=catalog.animations;$('#animationSelect').innerHTML=list.map(k=>`<option value="${safeText(k)}">${safeText(k.replaceAll('_',' '))}</option>`).join('');$('#motionList').innerHTML=list.map(k=>`<button data-clip="${safeText(k)}"><span>${safeText(k.replaceAll('_',' '))}</span><span>▶ PREVIEW</span></button>`).join('');$$('[data-clip]').forEach(el=>el.onclick=()=>selectClip(el.dataset.clip))}
function openModal(contents){$('#dialogContent').innerHTML=contents;$('#modalBackdrop').classList.remove('hidden');$('#modalBackdrop').setAttribute('aria-hidden','false');$('#dialogContent').scrollTop=0;$('#dialogContent').querySelector('.x-close')?.addEventListener('click',closeModal)}
function closeModal(){faceLab?.destroy();faceLab=null;$('#modalBackdrop').classList.add('hidden');$('#modalBackdrop').setAttribute('aria-hidden','true');$('#dialogContent').innerHTML=''}
function heading(k,title,sub){return `<div class="dialog-head"><div><div class="panel-kicker">${k}</div><h2>${safeText(title)}</h2><p>${sub}</p></div><button class="x-close" title="Close">×</button></div>`}
async function savePreset(){try{const result=await api('/api/presets',{method:'POST',body:JSON.stringify({character:chosen})});catalog.presets.unshift({id:result.id,...structuredClone(chosen)});toast(`Saved “${chosen.name}” to your local library`)}catch(e){toast(e.message,true)}}
function showSaved(){openModal(heading('CHARACTER LIBRARY','Saved characters','Reopen any saved character. All settings are stored locally in this workspace.')+`<div class="modal-body"><div class="modal-list">${catalog.presets.map(p=>`<button class="saved-card" data-preset="${safeText(p.id)}"><img src="/textures/face_${safeText(p.face)}.png"><span><strong>${safeText(p.name)}</strong><small>${safeText(p.outfit)} · ${safeText(p.face)} · ${p.body==='m'?'masculine':'feminine'}</small></span></button>`).join('')||'<p>No saved characters yet.</p>'}</div><div class="dialog-actions"><button class="btn btn-ghost" id="cancelSaved">Close</button></div></div>`);$$('[data-preset]').forEach(b=>b.onclick=()=>{const p=catalog.presets.find(x=>x.id===b.dataset.preset);if(p){chosen=upgrade(p);syncControls();dirty();closeModal();toast(`Loaded “${chosen.name}”`)}});$('#cancelSaved').onclick=closeModal}
function showHelp(){openModal(heading('ABOUT CHARACTER FORGE','Built around your character_kit','A local workstation for the original NOBODY CAME procedural Blender and face-texturing pipeline.')+`<div class="modal-body" style="font-size:13px;line-height:1.8;color:#b7c8c4"><p>The source kit provides 2 body meshes, 4 clothing variants, 2 hair meshes, a fedora, glasses, 17 face references, a shared skeleton and 13 motion clips.</p><p>Choose a portrait at left, customize on the right, orbit the 3D preview, and export a single assembled GLB with skin weights, textures and the animations.</p><p><strong>Face Lab:</strong> upload a painted image, crop the front view and mark the left eye, right eye and lip center. The original image-warp algorithm bakes those onto the head as a 1024×1024 texture that wraps all the way round, adding it to the face library.</p><p><strong>Requirements:</strong> Python 3.10+, Pillow, NumPy, FastAPI, and Blender 4.5+ or 5.x for exports. Internet is used to load the Three.js 3D viewer in your browser.</p><p>All data remains on your machine at <code>data/</code>, <code>assets/</code> and <code>exports/</code>.</p></div><div class="dialog-actions"><button class="btn btn-ghost" id="rebuildBase">Rebuild base geometry</button><button class="btn btn-accent" id="helpClose">Got it</button></div>`);$('#helpClose').onclick=closeModal;$('#rebuildBase').onclick=rebuildBase}
async function rebuildBase(){const btn=$('#rebuildBase');btn.disabled=true;btn.textContent="Building source geometry…";try{await api("/api/rebuild",{method:"POST",body:"{}"});toast("Source geometry rebuilt. Reloading viewport…");setTimeout(()=>location.reload(),1000)}catch(e){toast(e.message,true);btn.disabled=false;btn.textContent="Rebuild base geometry"}}
function showExport(){const ready=catalog.blender_available;
openModal(heading('04 / EXPORT','Deliver game-ready geometry','Choose a format. Blender assembles the selected meshes and embeds the face texture while retaining the armature and animation actions.')+`<div class="modal-body"><div class="export-choice"><button class="export-format" data-export="glb" ${ready?'':'disabled'}><span class="format-symbol">◇</span><strong>Rigged GLB</strong><small>Single glTF 2.0 binary. Ideal for Blender, Godot, Unreal import or other pipelines.</small><span class="format-tag">.GLB · GEOMETRY + MATERIALS + ANIMATIONS</span></button><button class="export-format" data-export="zip" ${ready?'':'disabled'}><span class="format-symbol">▧</span><strong>Godot-ready package</strong><small>GLB, editable face PNG, original build configuration and import notes.</small><span class="format-tag">.ZIP · PROJECT HANDOFF</span></button></div><div class="export-checklist"><span>Shared skeleton</span><span>13 animation clips</span><span>Embedded PBR materials</span><span>Selective mesh export</span></div>${ready?'':`<p class="hint" style="color:#e0a9a0">Blender is not detected. Set the BLENDER environment variable in your launcher to the full executable path, then restart the web tool.</p>`}<div id="exportProgress" style="font-size:11px;color:#a6b9b3;margin-top:17px"></div></div>`);
$$('[data-export]').forEach(b=>b.onclick=()=>performExport(b.dataset.export));}
async function performExport(format){const buttons=$$('[data-export]');buttons.forEach(b=>b.disabled=true);$('#exportProgress').textContent='Preparing mesh, materials, armature and 13 animations…';setStatus('EXPORTING CHARACTER VIA BLENDER…');try{const res=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({character:chosen,mode:format})});if(!res.ok){const e=await res.json().catch(()=>({detail:'Export failed'}));throw Error(e.detail||'Export failed')}
const blob=await res.blob();const disposition=res.headers.get('Content-Disposition')||'';let file=(/filename\*?=(?:UTF-8''|"?)([^";]+)/i.exec(disposition)||[])[1];file=file?decodeURIComponent(file.replaceAll('"','')):chosen.name.replace(/\W+/g,'_')+(format==='glb'?'.glb':'.zip');const a=document.createElement('a');const link=URL.createObjectURL(blob);a.href=link;a.download=file;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(link),10000);closeModal();toast(`Export complete: ${file} (${(blob.size/1024/1024).toFixed(2)} MB)`);setStatus('CHARACTER EXPORT FINISHED');}catch(e){toast(`Export failed: ${e.message}`,true);$('#exportProgress').textContent=e.message;buttons.forEach(b=>b.disabled=false);setStatus('EXPORT FAILED')}}
function showFaceLab(){const modal=heading('FACE PIPELINE / REFERENCE ALIGNMENT','Create a face texture','Import a front-view reference and align eye centers and lip line. The character kit bakes it onto the head as a 1024 × 1024 map that wraps all the way round.')+`<div class="modal-body"><label class="file-drop" id="faceDrop"><span style="font-size:31px">⊕</span><strong>Drop or choose a portrait reference</strong><small>PNG, JPG or WebP · up to 18 MB. Works with front/profile contact sheets.</small><input type="file" id="faceFile" accept="image/png,image/jpeg,image/webp"></label><div id="labEditor" style="display:none"><div class="face-lab-layout"><div class="lab-canvas-wrap"><canvas id="labCanvas"></canvas><div class="lab-canvas-note" id="labHint">Drag the crop corners, or click a landmark tool then click the face.</div></div><div class="lab-controls"><label class="form-field">FACE NAME <input id="newFaceName" value="New character" maxlength="60" placeholder="New character" /></label><label class="form-field">FACE ID <input id="newFaceId" value="c_${uid().slice(0,6)}" maxlength="21" pattern="[a-z][a-z0-9_]+"></label><div class="form-field">LANDMARK TOOL</div><div class="lab-points"><button data-point="-1" class="active">Crop / move</button><button data-point="0">Left eye</button><button data-point="1">Right eye</button><button data-point="2">Lip center</button></div><div class="lab-instructions">Adjust the green crop to contain only the front of the head, keeping profile panels and clothing out. Mark eye centers left-to-right in the image, then the lip-line center.</div><label class="form-field">BACKDROP COLOR <input type="color" id="backdropColor" value="#ffffff"></label><label class="form-field">BACKGROUND TOLERANCE <input type="range" id="tolerance" value="38" min="5" max="80"><span style="text-align:right;color:#9db3a4" id="tolValue">38</span></label><div class="lab-preview"><img id="generatedThumb" alt="Texture preview" src="/static/face_placeholder.svg"><span id="generatedStatus">Face texture will appear here after generation.</span></div></div></div></div><div class="dialog-actions"><button class="btn btn-ghost" id="faceCancel">Cancel</button><button class="btn btn-accent" id="generateFace" disabled>Generate face texture ↗</button></div></div>`;
openModal(modal);$('#faceCancel').onclick=closeModal;const upload=$('#faceFile');upload.addEventListener('change',e=>{const file=e.target.files?.[0];if(file)loadFaceImage(file)});const drop=$('#faceDrop');drop.addEventListener('dragover',e=>{e.preventDefault();drop.style.borderColor='#e5ffd7'});drop.addEventListener('dragleave',()=>{drop.style.borderColor=''});drop.addEventListener('drop',e=>{e.preventDefault();drop.style.borderColor='';const f=e.dataTransfer.files?.[0];if(f)loadFaceImage(f)});$('#generateFace').onclick=generateFace;
}
async function loadFaceImage(file){if(!file.type.startsWith('image/'))return toast('Choose an image file',true);if(file.size>18*1024*1024)return toast('Maximum image size is 18MB',true);const input=$('#faceFile');const drop=$('#faceDrop');drop.querySelector('strong').textContent=`Uploading ${file.name}…`;try{const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file)});const upload=await api('/api/references',{method:'POST',body:JSON.stringify({filename:file.name,content:data})});const img=await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=upload.url});drop.style.display='none';$('#labEditor').style.display='block';$('#generateFace').disabled=false;faceLab=new FaceLab($('#labCanvas'),img,upload.id);$$('[data-point]').forEach(btn=>btn.onclick=()=>{faceLab.tool=Number(btn.dataset.point);$$('[data-point]').forEach(x=>x.classList.toggle('active',x===btn));$('#labHint').textContent=faceLab.tool>=0?'Click the image to set '+['left eye','right eye','lip center'][faceLab.tool]+'.':'Drag a crop corner or drag inside the rectangle to move it.'});$('#tolerance').oninput=e=>$('#tolValue').textContent=e.target.value;toast('Reference loaded. Align the three landmarks and crop.')}catch(e){drop.querySelector('strong').textContent='Drop or choose a portrait reference';toast('Could not upload: '+e.message,true)}}
async function generateFace(){if(!faceLab)return;const id=$('#newFaceId').value.trim().toLowerCase().replace(/[^a-z0-9_]/g,'');if(!/^[a-z][a-z0-9_]{1,20}$/.test(id))return toast('Face ID must start with a letter and contain 2–21 lowercase characters.',true);const el=$('#generateFace');el.disabled=true;el.textContent='Generating texture…';try{const body={id,name:$('#newFaceName').value.trim()||id,source_id:faceLab.source,box:faceLab.box.map(Math.round),points:faceLab.points.map(p=>p.map(Math.round)),backdrop:$('#backdropColor').value,tolerance:Number($('#tolerance').value)};const data=await api('/api/faces',{method:'POST',body:JSON.stringify(body)});catalog.faces=catalog.faces.filter(f=>f.id!==id);catalog.faces.unshift(data.face);$('#generatedThumb').src=data.face.texture;$('#generatedStatus').textContent='Texture generated · 1024 × 1024';chosen.face=id;chosen.name=body.name;chosen.body=id.startsWith('f')?'f':chosen.body;chosen.hair='short';chosen.hat=false;chosen.glasses=false;chosen.colors.skin=data.face.skin;chosen.colors.hair=data.face.hair;syncControls();dirty();toast('Face '+body.name+' added to the library.');setTimeout(closeModal,850)}catch(e){toast(e.message,true)}finally{el.disabled=false;el.textContent='Generate face texture ↗'}}
class FaceLab{
 constructor(canvas,img,source){this.canvas=canvas;this.ctx=canvas.getContext('2d');this.img=img;this.source=source;this.tool=-1;this.drag=null;const w=img.width,h=img.height;let cw=w>h*1.2?Math.min(w*.50,h*.77):w*.8;this.box=[Math.max(0,w*.06),h*.07,Math.min(w,w*.06+cw),h*.84];const [x0,y0,x1,y1]=this.box;this.points=[[x0+(x1-x0)*.37,y0+(y1-y0)*.36],[x0+(x1-x0)*.64,y0+(y1-y0)*.36],[x0+(x1-x0)*.5,y0+(y1-y0)*.65]];this.boundDown=e=>this.down(e);this.boundMove=e=>this.move(e);this.boundUp=e=>this.up(e);this.canvas.addEventListener('pointerdown',this.boundDown);this.canvas.addEventListener('pointermove',this.boundMove);this.canvas.addEventListener('pointerup',this.boundUp);this.canvas.addEventListener('pointercancel',this.boundUp);this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(canvas);this.resize()}
 resize(){const rect=this.canvas.getBoundingClientRect();this.canvas.width=Math.round(rect.width*devicePixelRatio);this.canvas.height=Math.round(rect.height*devicePixelRatio);const w=this.canvas.width,h=this.canvas.height;this.sf=Math.min((w-35)/this.img.width,(h-35)/this.img.height);this.ox=(w-this.img.width*this.sf)/2;this.oy=(h-this.img.height*this.sf)/2;this.draw()}
 xy(e){const r=this.canvas.getBoundingClientRect();const dx=(e.clientX-r.left)*this.canvas.width/r.width,dy=(e.clientY-r.top)*this.canvas.height/r.height;return [(dx-this.ox)/this.sf,(dy-this.oy)/this.sf]}
 screen(p){return [this.ox+p[0]*this.sf,this.oy+p[1]*this.sf]}
 draw(){const g=this.ctx,w=this.canvas.width,h=this.canvas.height;g.fillStyle='#101920';g.fillRect(0,0,w,h);g.drawImage(this.img,this.ox,this.oy,this.img.width*this.sf,this.img.height*this.sf);const [x0,y0,x1,y1]=this.box,[sx,sy]=this.screen([x0,y0]),[ex,ey]=this.screen([x1,y1]);g.save();g.fillStyle='#07111699';g.fillRect(this.ox,this.oy,this.img.width*this.sf,this.img.height*this.sf);g.beginPath();g.rect(sx,sy,ex-sx,ey-sy);g.clip();g.drawImage(this.img,this.ox,this.oy,this.img.width*this.sf,this.img.height*this.sf);g.restore();g.strokeStyle='#d0edbd';g.lineWidth=2*devicePixelRatio;g.setLineDash([6*devicePixelRatio,5*devicePixelRatio]);g.strokeRect(sx,sy,ex-sx,ey-sy);g.setLineDash([]);for(const [x,y] of [[sx,sy],[ex,sy],[ex,ey],[sx,ey]]){g.fillStyle='#d6f2bc';g.fillRect(x-5*devicePixelRatio,y-5*devicePixelRatio,10*devicePixelRatio,10*devicePixelRatio)}this.points.forEach((p,i)=>{const [x,y]=this.screen(p);const c=['#d2eab6','#bfdbf6','#f3c3b7'][i];g.strokeStyle='#151e22';g.lineWidth=5*devicePixelRatio;g.beginPath();g.arc(x,y,9*devicePixelRatio,0,Math.PI*2);g.stroke();g.strokeStyle=c;g.lineWidth=2*devicePixelRatio;g.beginPath();g.arc(x,y,9*devicePixelRatio,0,Math.PI*2);g.stroke();g.beginPath();g.moveTo(x-15*devicePixelRatio,y);g.lineTo(x+15*devicePixelRatio,y);g.moveTo(x,y-15*devicePixelRatio);g.lineTo(x,y+15*devicePixelRatio);g.stroke();g.font=`${10*devicePixelRatio}px sans-serif`;g.fillStyle='#fff';g.fillText(['L','R','M'][i],x+13*devicePixelRatio,y-13*devicePixelRatio)})}
 down(e){e.preventDefault();const p=this.xy(e);if(this.tool>=0){this.points[this.tool]=p;this.draw();return}const radius=14*devicePixelRatio/this.sf;const corners=[[this.box[0],this.box[1]],[this.box[2],this.box[1]],[this.box[2],this.box[3]],[this.box[0],this.box[3]]];let corner=corners.findIndex(q=>Math.hypot(q[0]-p[0],q[1]-p[1])<radius);this.drag={kind:corner>=0?'corner':'move',corner,start:p,orig:[...this.box],oldPts:this.points.map(x=>[...x])};this.canvas.setPointerCapture(e.pointerId)}
 move(e){if(!this.drag)return;const p=this.xy(e),d=this.drag,dx=p[0]-d.start[0],dy=p[1]-d.start[1];let [x0,y0,x1,y1]=d.orig;if(d.kind==='move'){const width=x1-x0,height=y1-y0;x0=Math.max(0,Math.min(this.img.width-width,x0+dx));y0=Math.max(0,Math.min(this.img.height-height,y0+dy));x1=x0+width;y1=y0+height;this.points=d.oldPts.map(pt=>[pt[0]+x0-d.orig[0],pt[1]+y0-d.orig[1]])}else{const c=d.corner;if(c===0||c===3)x0=Math.max(0,Math.min(x1-42,x0+dx));else x1=Math.min(this.img.width,Math.max(x0+42,x1+dx));if(c===0||c===1)y0=Math.max(0,Math.min(y1-42,y0+dy));else y1=Math.min(this.img.height,Math.max(y0+42,y1+dy))}this.box=[x0,y0,x1,y1];this.draw()}
 up(){this.drag=null}
 destroy(){this.resizeObserver.disconnect();this.canvas.removeEventListener('pointerdown',this.boundDown);this.canvas.removeEventListener('pointermove',this.boundMove);this.canvas.removeEventListener('pointerup',this.boundUp);this.canvas.removeEventListener('pointercancel',this.boundUp)}
}
async function initViewer(){try{const mod=await import('/static/viewer.js?v=2.6.0');viewer=await mod.startViewer($('#stage'),catalog.base_model,catalog.rules);viewer.onFaceReload(face=>{$$(`.face-tile[data-face="${face}"] img`).forEach(img=>{img.src='/textures/face_'+encodeURIComponent(face)+'.png?v='+Date.now()});setStatus('FACE TEXTURE RELOADED: '+face.toUpperCase())});const visible=viewer.update(chosen);viewer.play(chosen.animation);viewer.setPlaying(playing);$('#viewerHint').style.display='none';$('#previewFallback').style.display='none';$('#viewLabel').textContent='PERSPECTIVE / LIVE VIEW';$('#engineState').textContent='LIVE 3D / LOCAL FILES';setStatus('LIVE 3D / ASSET PIPELINE CONNECTED');$('#polyReadout').textContent=viewer.stats;$('#meshStatus').textContent=`${visible.visible.length} PARTS VISIBLE`}catch(e){console.error('3D viewer:',e);$('#stage canvas')?.remove();$('#previewFallback').style.display='block';$('#viewerHint').textContent='3D preview failed: '+(e.message||String(e)).slice(0,95);$('#viewerHint').style.top='92%';$('#viewerHint').style.fontSize='10px';$('#viewLabel').textContent='REFERENCE / STATIC PREVIEW';$('#meshStatus').textContent='STATIC PREVIEW / CHECK CONSOLE';}}
async function init(){setupControls();try{catalog=await api('/api/catalog');chosen=structuredClone(catalog.starter||fallback);setupClips();syncControls();$('#faceFoot').textContent=`${catalog.faces.length} UV textures available`;$('#engineState').textContent=catalog.blender_available?'BLENDER READY':'BLENDER NOT DETECTED';setStatus(catalog.model_available?'SOURCE MODEL READY — NOBODY CAME / character_kit':'BASE MODEL NOT BUILT');if(catalog.model_available)initViewer();else {$('#viewerHint').textContent='Base model missing. Follow README to rebuild human.glb.';toast('Source human.glb is missing',true)} }catch(e){console.error(e);toast('Could not load character data: '+e.message,true);$('#viewerHint').textContent='Unable to connect to character pipeline.'}}
init();
