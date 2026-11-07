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

export async function startViewer(stage, src, rules) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.08, 80);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.setClearColor(0x000000, 0);
  stage.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, {
    enableDamping: true, dampingFactor: 0.085, minDistance: 0.8, maxDistance: 6,
    maxPolarAngle: Math.PI * 0.89, minPolarAngle: Math.PI * 0.1, enablePan: false,
  });

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
  let triangles = 0;
  root.traverse(o => {
    if (!o.isMesh) return;
    meshes.push(o);
    const geo = o.geometry;
    triangles += Math.floor((geo.index ? geo.index.count : geo.attributes.position.count) / 3);
    if (o.isSkinnedMesh) o.frustumCulled = false; // animated poses leave the bind-pose bounds
    // Material instances are shared between outfits in the GLB; give each mesh its own.
    o.material = Array.isArray(o.material) ? o.material.map(m => m.clone()) : o.material.clone();
  });

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
    if (playing) mixer.update(dt * speed);
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

  function textureFor(tex, cfg) {
    if (tex === '@face') return '/textures/face_' + encodeURIComponent(cfg.face) + '.png';
    if (tex === '@top') tex = cfg.fabric?.top || 'cloth';
    if (tex === '@pants') tex = cfg.fabric?.pants || 'cloth';
    return '/materials/' + tex + '.png';
  }

  function update(cfg) {
    const result = applyCharacterParts(parts, cfg);
    if (result.missing.length) console.warn('Optional GLB parts not found:', result.missing);
    root.scale.setScalar(cfg.scale || 1);
    for (const o of meshes) {
      for (const mat of Array.isArray(o.material) ? o.material : [o.material]) {
        const slot = mat.name.split('.')[0];
        const rule = surfaceRule(o.userData.part, slot);
        if (!rule) continue;
        const tint = rule.tex === '@face' ? '#ffffff' : (cfg.colors[rule.color || slot] || '#ffffff');
        mat.color.set(tint);
        mat.roughness = rule.rough;
        mat.metalness = 0;
        mat.transparent = false; mat.opacity = 1; mat.depthWrite = true;
        mat.vertexColors = Boolean(o.geometry.attributes.color); // baked crease shading
        const url = textureFor(rule.tex, cfg);
        if (mat.userData.url !== url) {
          mat.userData.url = url;
          textures.get(url, rule.tex === '@face').then(t => {
            if (mat.userData.url !== url) return; // changed again while loading
            mat.map = t; mat.needsUpdate = true;
          });
        }
        mat.needsUpdate = true;
      }
    }
    play(cfg.animation || 'idle');
    return result;
  }

  function setView(v) {
    const d = 3.4;
    if (v === 'front') camera.position.set(0, 1.48, d);
    else if (v === 'side') camera.position.set(d, 1.48, 0);
    else if (v === 'back') camera.position.set(0, 1.48, -d);
    else camera.position.set(2.2, 1.65, 2.65);
    controls.target.set(0, 1.03, 0); camera.lookAt(controls.target); controls.update();
  }
  function zoom(delta) {
    const dir = camera.position.clone().sub(controls.target);
    dir.setLength(THREE.MathUtils.clamp(dir.length() + delta, 0.8, 6));
    camera.position.copy(controls.target).add(dir); controls.update();
  }
  setView('front');

  return {
    update, play, setView, zoom,
    setPlaying: v => { playing = v; },
    setSpeed: v => { speed = v; },
    stats: `${(triangles / 1000).toFixed(1)}K SOURCE TRIS`,
  };
}

class TextureCache {
  constructor() { this.loader = new THREE.TextureLoader(); this.cache = new Map(); }
  get(url, isFace) {
    const key = isFace ? url + '?v=' + Date.now() : url; // faces can be regenerated in Face Lab
    if (!isFace && this.cache.has(key)) return this.cache.get(key);
    const p = this.loader.loadAsync(key).then(t => {
      t.flipY = false; // glTF UV convention
      t.colorSpace = THREE.SRGBColorSpace;
      t.wrapS = t.wrapT = isFace ? THREE.ClampToEdgeWrapping : THREE.RepeatWrapping;
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
