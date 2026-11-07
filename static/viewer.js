/* Browser 3D preview of a kit character.
 *
 * Materials follow the game's character.gd: every surface is a tiling texture
 * (cloth, suitcloth, skin, rubber, hair) multiplied by a tint and by the model's
 * baked vertex-colour shading. The rules come from data/kit.json, which the Blender
 * export reads too, so the preview and the exported GLB match.
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { collectCharacterParts, applyCharacterParts } from './character-parts.mjs';
import { PartShape, ShapeEditor } from './shape.js?v=2.8.2';

export async function startViewer(stage, src, rules) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 80); // near plane small enough for head close-ups
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.setClearColor(0x000000, 0);
  stage.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  // Whole-body framing vs. head focus (for checking painted face textures up close).
  const BODY_LIMITS = { minDistance: 0.8, maxDistance: 6, maxPolarAngle: Math.PI * 0.89, minPolarAngle: Math.PI * 0.1, zoomSpeed: 1 };
  const HEAD_LIMITS = { minDistance: 0.12, maxDistance: 1.6, maxPolarAngle: Math.PI * 0.97, minPolarAngle: Math.PI * 0.03, zoomSpeed: 0.6 };
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.085, enablePan: false }, BODY_LIMITS);

  // Neutral studio light: a soft sky, one warm key and a cool rim.
  scene.add(new THREE.HemisphereLight(0xdfe8ee, 0x3a3d40, 1.1));
  const key = new THREE.DirectionalLight(0xfff3e0, 2.4); key.position.set(-2.5, 5, 4); scene.add(key);
  const rim = new THREE.DirectionalLight(0xd8e6f0, 1.2); rim.position.set(2.5, 3.5, -3.5); scene.add(rim);
  const fill = new THREE.DirectionalLight(0xc8d4f7, 0.4); fill.position.set(4, 1.4, 3); scene.add(fill);
  addFloor(scene);

  const gltf = await new GLTFLoader().loadAsync(src);
  const root = gltf.scene;
  scene.add(root);

  const parts = collectCharacterParts(root);
  if (!parts.has('person_m') || !parts.has('outfit_trench')) {
    throw new Error('GLB loaded but essential named character parts could not be found.');
  }
  // Remember which wearable each leaf mesh belongs to (glasses use their own rule).
  for (const [id, node] of parts) node.traverse(o => { o.userData.part = id; });

  const meshes = [];
  const skeletons = new Set();
  let triangles = 0;
  root.traverse(o => {
    if (!o.isMesh) return;
    meshes.push(o);
    const geo = o.geometry;
    triangles += Math.floor((geo.index ? geo.index.count : geo.attributes.position.count) / 3);
    if (o.isSkinnedMesh) { o.frustumCulled = false; skeletons.add(o.skeleton); } // animated poses leave the bind-pose bounds
    // Material instances are shared between outfits in the GLB; give each mesh its own.
    o.material = Array.isArray(o.material) ? o.material.map(m => m.clone()) : o.material.clone();
  });

  // The painted head's centre, in the head bone's space (bone at 1.547 m, face spans 1.47-1.79 m).
  const headBone = root.getObjectByName('head');
  const HEAD_CENTRE = new THREE.Vector3(0, 0.113, 0.005);
  let mode = 'body';
  let editor = null;
  let paintTexture = null; // the live texture while touching up with brushes
  const headView = { flat: false, hideHair: false };
  let current = null;

  function headCentre() {
    if (!headBone) return new THREE.Vector3(0, 1.66 * root.scale.y, 0);
    root.updateMatrixWorld();
    return headBone.localToWorld(HEAD_CENTRE.clone());
  }
  // Keep the orbit centred on the head while it moves with the animation.
  function followHead() {
    const next = headCentre();
    const delta = next.clone().sub(controls.target);
    if (delta.lengthSq() < 1e-10) return;
    camera.position.add(delta);
    controls.target.copy(next);
  }

  const textures = new TextureCache();
  const loops = new Set(rules.loop);
  const mixer = new THREE.AnimationMixer(root);
  const actions = new Map((gltf.animations || []).map(c => [c.name, mixer.clipAction(c)]));
  let currentAction = null, playing = true, speed = 1;

  const clock = new THREE.Clock();
  new ResizeObserver(resize).observe(stage);
  function resize() {
    const w = Math.max(1, stage.clientWidth), h = Math.max(1, stage.clientHeight);
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  function render() {
    const dt = Math.min(0.1, clock.getDelta());
    if (editor?.active) for (const s of skeletons) s.pose(); // rest pose while editing the shape
    else if (playing && !paintTexture) mixer.update(dt * speed); // the pose holds still while touching up
    if (mode === 'head') followHead();
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(render);
  }
  resize(); render();

  function play(name) {
    const next = actions.get(name) || actions.get('idle');
    if (!next || currentAction === next) return;
    if (currentAction) currentAction.fadeOut(0.2);
    next.reset().setEffectiveWeight(1).setEffectiveTimeScale(1);
    // Same as the game: listed clips loop, the rest (reach, cast, dead) play once and hold.
    next.setLoop(loops.has(name) ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    next.clampWhenFinished = true;
    next.fadeIn(0.2).play();
    currentAction = next;
  }

  function surfaceRule(part, slot) {
    if (rules.part_surfaces[part]) return rules.part_surfaces[part];
    return rules.surfaces[slot];
  }

  let faceOverride = null; // e.g. the source-mapping region preview, shown in place of the face texture
  function textureFor(tex, cfg) {
    if (tex === '@face') return faceOverride || '/textures/face_' + encodeURIComponent(cfg.face) + '.png';
    if (tex === '@top') tex = cfg.fabric?.top || 'cloth';
    if (tex === '@pants') tex = cfg.fabric?.pants || 'cloth';
    return '/materials/' + tex + '.png';
  }

  function update(cfg) {
    current = cfg;
    const result = applyCharacterParts(parts, cfg);
    if (result.missing.length) console.warn('Optional GLB parts not found:', result.missing);
    // Head mode can hide hair, hat and glasses for a clear view of the forehead and eyes (display only, not saved).
    if (mode === 'head' && headView.hideHair) {
      for (const id of ['hair_short', 'hair_long', 'hat', 'glasses']) parts.get(id) && (parts.get(id).visible = false);
    }
    const flatFace = mode === 'head' && headView.flat;
    root.scale.setScalar(cfg.scale || 1);
    for (const o of meshes) {
      for (const mat of Array.isArray(o.material) ? o.material : [o.material]) {
        const slot = mat.name.split('.')[0];
        const rule = surfaceRule(o.userData.part, slot);
        if (!rule) continue;
        const isFace = rule.tex === '@face';
        const tint = isFace ? '#ffffff' : (cfg.colors[rule.color || slot] || '#ffffff');
        mat.color.set(tint);
        mat.roughness = rule.rough;
        mat.metalness = 0;
        mat.transparent = false; mat.opacity = 1; mat.depthWrite = true;
        mat.vertexColors = Boolean(o.geometry.attributes.color); // baked crease shading
        // "True colour": the painted pixels exactly, with no light or baked shading on top.
        const flat = isFace && flatFace;
        if (flat) { mat.color.set('#000000'); mat.emissive.set('#ffffff'); mat.vertexColors = false; }
        else mat.emissive.set('#000000');
        mat.emissiveMap = flat ? mat.map : null;
        mat.toneMapped = !flat; // tone mapping would shift the painted colours
        mat.userData.flat = flat;
        mat.userData.isFace = isFace;
        if (isFace && paintTexture) {
          mat.userData.url = '@paint';
          mat.map = paintTexture; if (flat) mat.emissiveMap = paintTexture;
          mat.needsUpdate = true;
          continue;
        }
        const url = textureFor(rule.tex, cfg);
        if (mat.userData.url !== url) {
          mat.userData.url = url;
          textures.get(url, isFace).then(t => {
            if (mat.userData.url !== url) return; // changed again while loading
            mat.map = t;
            if (mat.userData.flat) mat.emissiveMap = t;
            mat.needsUpdate = true;
          });
        }
        mat.needsUpdate = true;
      }
    }
    // Shape edits stored with the character (Edit shape mode).
    for (const id of parts.keys()) {
      const rows = cfg.shape?.[id];
      if ((rows && rows.length) || shapes.has(id)) shapeFor(id).apply(rows || []);
    }
    if (editor?.active) editor.draw();
    play(cfg.animation || 'idle');
    return result;
  }

  function setView(v) {
    const wasHead = mode === 'head';
    mode = v === 'head' ? 'head' : 'body';
    if (mode === 'head') {
      Object.assign(controls, HEAD_LIMITS);
      const c = headCentre();
      controls.target.copy(c);
      camera.position.set(c.x, c.y + 0.03, c.z + 0.6);
    } else {
      Object.assign(controls, BODY_LIMITS);
      const d = 3.4;
      if (v === 'front') camera.position.set(0, 1.48, d);
      else if (v === 'side') camera.position.set(d, 1.48, 0);
      else if (v === 'back') camera.position.set(0, 1.48, -d);
      else camera.position.set(2.2, 1.65, 2.65);
      controls.target.set(0, 1.03, 0);
    }
    camera.lookAt(controls.target); controls.update();
    if (current && wasHead !== (mode === 'head')) update(current); // head-only display options on/off
  }
  // Orbit the head to a fixed side in head mode: front, left, right, back, top, under.
  function headAngle(name) {
    if (mode !== 'head') return;
    const c = controls.target, r = camera.position.distanceTo(c);
    const dirs = { front: [0, 0.05, 1], left: [1, 0.05, 0], right: [-1, 0.05, 0], back: [0, 0.05, -1], top: [0, 1, 0.12], under: [0, -1, 0.35] };
    const d = new THREE.Vector3(...(dirs[name] || dirs.front)).normalize().multiplyScalar(r);
    camera.position.copy(c).add(d); controls.update();
  }
  function zoom(delta) {
    const scale = mode === 'head' ? 0.25 : 1; // finer steps up close
    const dir = camera.position.clone().sub(controls.target);
    dir.setLength(THREE.MathUtils.clamp(dir.length() + delta * scale, controls.minDistance, controls.maxDistance));
    camera.position.copy(controls.target).add(dir); controls.update();
  }
  function setFaceOverride(url) {
    faceOverride = url || null;
    if (current) update(current);
  }
  function setHeadOptions(opts) {
    Object.assign(headView, opts);
    if (current) update(current);
  }

  // Reload the face texture whenever its PNG changes on disk, so painting in an
  // external editor shows up here on save.
  let faceStamp = { face: null, stamp: null };
  async function checkFace() {
    if (!current || document.hidden || faceOverride || paintTexture) return;
    const face = current.face, url = '/textures/face_' + encodeURIComponent(face) + '.png';
    try {
      const r = await fetch(url, { method: 'HEAD', cache: 'no-store' });
      const stamp = r.headers.get('last-modified') + '|' + r.headers.get('etag');
      if (faceStamp.face === face && faceStamp.stamp !== stamp && current.face === face) {
        for (const o of meshes) for (const m of [o.material].flat()) if (m.userData.url === url) m.userData.url = null;
        update(current);
        onFaceReload?.(face);
      }
      faceStamp = { face, stamp };
    } catch { /* server gone; try again next tick */ }
  }
  // ---- Edit shape (see shape.js)
  const shapes = new Map();
  function shapeFor(id) {
    if (!parts.has(id)) return null;
    if (!shapes.has(id)) shapes.set(id, new PartShape(id, parts.get(id)));
    return shapes.get(id);
  }
  function startEdit(callbacks) {
    editor ??= new ShapeEditor({
      scene, camera, renderer, controls, stage, shapeFor,
      visibleMeshes: () => meshes.filter(o => { for (let n = o; n; n = n.parent) if (!n.visible) return false; return true; }),
      onChange: () => {}, onEdit: () => {},
    });
    Object.assign(editor, callbacks);
    for (const s of skeletons) s.pose();
    root.updateMatrixWorld(true);
    editor.start();
    return editor;
  }
  function stopEdit() { if (!editor?.active) return; editor.stop(); mixer.update(0); }

  // ---- Brush touch-ups (see painter.js)
  const raycaster = new THREE.Raycaster();
  const OCCLUDERS = new Set(['hair_short', 'hair_long', 'hat', 'glasses']);
  const shown = o => { for (let n = o; n; n = n.parent) if (!n.visible) return false; return true; };
  const isFaceMesh = o => [o.material].flat().some(m => m.userData.isFace);
  // The face point under the pointer: the mesh, its triangle and barycentric weights (so the painter can
  // work in the rest pose), plus the world point, normal and scale for the cursor.
  function paintHit(clientX, clientY) {
    const r = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
    const targets = meshes.filter(o => shown(o) && (isFaceMesh(o) || OCCLUDERS.has(o.userData.part)));
    const h = raycaster.intersectObjects(targets, false)[0];
    if (!h || !isFaceMesh(h.object) || !h.face) return null; // hair or a hat is in front
    const o = h.object, f = h.face, v = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
    [f.a, f.b, f.c].forEach((vi, k) => o.localToWorld(o.getVertexPosition(vi, v[k])));
    const tri = new THREE.Triangle(...v), bary = tri.getBarycoord(h.point, new THREE.Vector3());
    if (!bary) return null;
    const normal = tri.getNormal(new THREE.Vector3());
    if (normal.dot(raycaster.ray.direction) > 0) normal.negate();
    return { mesh: o, tri: [f.a, f.b, f.c], bary: [bary.x, bary.y, bary.z], point: h.point, normal, scale: o.getWorldScale(new THREE.Vector3()).x };
  }
  const cursor = new THREE.Group();
  const ringMat = opacity => new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity, depthTest: false, depthWrite: false, side: THREE.DoubleSide });
  const outer = new THREE.Mesh(new THREE.RingGeometry(0.93, 1, 48), ringMat(0.9));
  const shadow = new THREE.Mesh(new THREE.RingGeometry(1, 1.07, 48), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.5, depthTest: false, depthWrite: false, side: THREE.DoubleSide }));
  const inner = new THREE.Mesh(new THREE.RingGeometry(0.96, 1, 48), ringMat(0.35));
  cursor.add(outer, shadow, inner); cursor.visible = false; cursor.renderOrder = 999;
  for (const m of [outer, shadow, inner]) m.renderOrder = 999;
  scene.add(cursor);
  function setPaintCursor(c) {
    if (!c) { cursor.visible = false; return; }
    cursor.visible = true;
    cursor.position.copy(c.point).addScaledVector(c.normal, 0.0004);
    cursor.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), c.normal);
    cursor.scale.setScalar(c.radius);
    inner.visible = c.inner > 0.05 && c.inner < 0.97; inner.scale.setScalar(c.inner);
  }
  function setPaintTexture(t) {
    paintTexture = t || null;
    controls.mouseButtons.RIGHT = paintTexture ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN; // right-drag orbits while painting
    if (!paintTexture) for (const o of meshes) for (const m of [o.material].flat()) if (m.userData.url === '@paint') m.userData.url = null;
    if (current) update(current);
  }

  let onFaceReload = null;
  setInterval(checkFace, 1200);
  setView('front');

  return {
    update, play, setView, zoom, headAngle, setHeadOptions, setFaceOverride, paintHit, setPaintCursor, setPaintTexture, startEdit, stopEdit,
    onFaceReload: fn => { onFaceReload = fn; },
    setPlaying: v => { playing = v; },
    setSpeed: v => { speed = v; },
    stats: `${(triangles / 1000).toFixed(1)}K SOURCE TRIS`,
  };
}

class TextureCache {
  constructor() { this.loader = new THREE.TextureLoader(); this.cache = new Map(); }
  get(url, isFace) {
    const key = isFace ? url + (url.includes('?') ? '&' : '?') + 'v=' + Date.now() : url; // faces can be regenerated in Face Lab
    if (!isFace && this.cache.has(key)) return this.cache.get(key);
    const p = this.loader.loadAsync(key).then(t => {
      t.flipY = false; // glTF UV convention
      t.colorSpace = THREE.SRGBColorSpace;
      // Face maps wrap round the head: u repeats across the seam at the back, v clamps.
      t.wrapS = THREE.RepeatWrapping;
      t.wrapT = isFace ? THREE.ClampToEdgeWrapping : THREE.RepeatWrapping;
      t.anisotropy = 8;
      return t;
    });
    if (!isFace) this.cache.set(key, p);
    return p;
  }
}

function addFloor(scene) {
  const floor = new THREE.Mesh(new THREE.CircleGeometry(1.08, 96),
    new THREE.MeshBasicMaterial({ color: 0x111b21, transparent: true, opacity: 0.48, depthWrite: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = 0.004; scene.add(floor);
  const ring = new THREE.Mesh(new THREE.RingGeometry(1.16, 1.165, 96),
    new THREE.MeshBasicMaterial({ color: 0x668b7f, transparent: true, opacity: 0.32, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.006; scene.add(ring);
  const grid = new THREE.GridHelper(3.5, 18, 0x3e5455, 0x364a4e); grid.position.y = -0.005;
  for (const m of [grid.material].flat()) { m.transparent = true; m.opacity = 0.25; m.depthWrite = false; }
  scene.add(grid);
}
