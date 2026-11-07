/* Edit shape: select vertices, edges or faces on a character part and move them.
 *
 * Each part (person_m, outfit_suit, ...) is welded by position first: the GLB splits
 * vertices along UV and material seams, and moving one copy without the others would
 * tear the mesh. Edits are stored as [x, y, z, dx, dy, dz] rows per part, x, y, z being
 * the vertex's original position in the part's mesh space; export_character.py applies
 * the same rows in Blender. While editing, the rig holds its rest pose, so a vertex's
 * mesh-space position is exactly where it is drawn.
 */
import * as THREE from 'three';

const Q = 1e4; // weld/match positions to 0.1 mm
const keyOf = (x, y, z) => Math.round(x * Q) + ',' + Math.round(y * Q) + ',' + Math.round(z * Q);

// ---------------------------------------------------------------------------------------------
export class PartShape {
  constructor(id, node) {
    this.id = id;
    this.meshes = [];
    node.traverse(o => { if (o.isMesh) this.meshes.push(o); });
    const wid = new Map(), wpos = [], members = [];
    this.vidToW = this.meshes.map((m, mi) => {
      const g = m.geometry, p = g.attributes.position;
      g.userData.orig ??= Float32Array.from(p.array);
      if (g.attributes.normal) g.userData.origNormal ??= Float32Array.from(g.attributes.normal.array);
      const o = g.userData.orig, map = new Int32Array(p.count);
      for (let i = 0; i < p.count; i++) {
        const k = keyOf(o[i * 3], o[i * 3 + 1], o[i * 3 + 2]);
        let w = wid.get(k);
        if (w === undefined) { w = wpos.length / 3; wid.set(k, w); wpos.push(o[i * 3], o[i * 3 + 1], o[i * 3 + 2]); members.push([]); }
        members[w].push(mi, i); map[i] = w;
      }
      return map;
    });
    this.key = wid; this.orig = Float32Array.from(wpos); this.cur = Float32Array.from(wpos); this.members = members;
    this.count = members.length;
    // Triangles (welded), per-vertex triangle lists and unique edges.
    const tris = [], triSrc = [];
    this.meshes.forEach((m, mi) => {
      const g = m.geometry, idx = g.index ? g.index.array : null, n = idx ? idx.length : g.attributes.position.count;
      for (let k = 0; k < n; k += 3) {
        const a = idx ? idx[k] : k, b = idx ? idx[k + 1] : k + 1, c = idx ? idx[k + 2] : k + 2, map = this.vidToW[mi];
        tris.push(map[a], map[b], map[c]); triSrc.push(mi, k / 3);
      }
    });
    this.tris = Int32Array.from(tris);
    this.triOf = Array.from({ length: this.count }, () => []);
    const edges = new Map();
    for (let t = 0; t < this.tris.length / 3; t++) for (let e = 0; e < 3; e++) {
      const a = this.tris[t * 3 + e], b = this.tris[t * 3 + (e + 1) % 3];
      this.triOf[a].push(t);
      const k = a < b ? a * 1e7 + b : b * 1e7 + a;
      if (!edges.has(k)) edges.set(k, [Math.min(a, b), Math.max(a, b)]);
    }
    this.edges = Int32Array.from([...edges.values()].flat());
    this.applied = '[]';
  }

  // Welded id of a mesh triangle's corners.
  triangle(mesh, face) {
    const mi = this.meshes.indexOf(mesh), map = this.vidToW[mi];
    return [map[face.a], map[face.b], map[face.c]];
  }
  neighbours(w) {
    const out = new Set();
    for (const t of this.triOf[w]) for (let k = 0; k < 3; k++) out.add(this.tris[t * 3 + k]);
    out.delete(w); return out;
  }
  set(w, x, y, z) {
    this.cur[w * 3] = x; this.cur[w * 3 + 1] = y; this.cur[w * 3 + 2] = z;
    const m = this.members[w];
    for (let k = 0; k < m.length; k += 2) {
      const p = this.meshes[m[k]].geometry.attributes.position;
      p.setXYZ(m[k + 1], x, y, z);
    }
  }
  // Recompute smooth normals round the given vertices (and their neighbours); the rest keep the model's own.
  refresh(changed) {
    const ring = new Set(changed);
    for (const w of changed) for (const n of this.neighbours(w)) ring.add(n);
    const A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3(), N = new THREE.Vector3();
    for (const w of ring) {
      const moved = this.isMoved(w) || [...this.neighbours(w)].some(n => this.isMoved(n));
      const acc = new THREE.Vector3();
      if (moved) for (const t of this.triOf[w]) {
        A.fromArray(this.cur, this.tris[t * 3] * 3); B.fromArray(this.cur, this.tris[t * 3 + 1] * 3); C.fromArray(this.cur, this.tris[t * 3 + 2] * 3);
        acc.add(N.subVectors(C, B).cross(A.clone().sub(B)));
      }
      const m = this.members[w];
      for (let k = 0; k < m.length; k += 2) {
        const g = this.meshes[m[k]].geometry, nrm = g.attributes.normal, i = m[k + 1];
        if (!nrm) continue;
        if (moved && acc.lengthSq() > 1e-20) {
          const n = acc.clone().normalize();
          const o = g.userData.origNormal; // keep the original facing (winding may be either way)
          if (n.x * o[i * 3] + n.y * o[i * 3 + 1] + n.z * o[i * 3 + 2] < 0) n.negate();
          nrm.setXYZ(i, n.x, n.y, n.z);
        } else nrm.setXYZ(i, g.userData.origNormal[i * 3], g.userData.origNormal[i * 3 + 1], g.userData.origNormal[i * 3 + 2]);
      }
    }
    for (const m of this.meshes) {
      const g = m.geometry;
      g.attributes.position.needsUpdate = true;
      if (g.attributes.normal) g.attributes.normal.needsUpdate = true;
      g.computeBoundingSphere(); g.computeBoundingBox();
      if (m.isSkinnedMesh) { m.boundingSphere = null; m.boundingBox = null; }
      g.userData.shapeVersion = (g.userData.shapeVersion || 0) + 1;
    }
  }
  isMoved(w) {
    return Math.abs(this.cur[w * 3] - this.orig[w * 3]) + Math.abs(this.cur[w * 3 + 1] - this.orig[w * 3 + 1]) + Math.abs(this.cur[w * 3 + 2] - this.orig[w * 3 + 2]) > 1e-7;
  }
  rows() {
    const out = [], r = v => Math.round(v * 1e5) / 1e5;
    for (let w = 0; w < this.count; w++) if (this.isMoved(w)) {
      const i = w * 3;
      out.push([r(this.orig[i]), r(this.orig[i + 1]), r(this.orig[i + 2]), r(this.cur[i] - this.orig[i]), r(this.cur[i + 1] - this.orig[i + 1]), r(this.cur[i + 2] - this.orig[i + 2])]);
    }
    return out;
  }
  // Show the stored edits (from a saved character): back to the original, then each row moved.
  apply(rows) {
    const json = JSON.stringify(rows || []);
    if (json === this.applied) return false;
    const changed = [];
    for (let w = 0; w < this.count; w++) if (this.isMoved(w)) { changed.push(w); this.set(w, this.orig[w * 3], this.orig[w * 3 + 1], this.orig[w * 3 + 2]); }
    for (const [x, y, z, dx, dy, dz] of rows || []) {
      const w = this.key.get(keyOf(x, y, z));
      if (w === undefined) continue;
      this.set(w, this.orig[w * 3] + dx, this.orig[w * 3 + 1] + dy, this.orig[w * 3 + 2] + dz); changed.push(w);
    }
    this.refresh(changed);
    this.applied = json;
    return true;
  }
}

// ---------------------------------------------------------------------------------------------
export class ShapeEditor {
  constructor(ctx) {
    Object.assign(this, ctx); // scene, camera, renderer, controls, stage, shapeFor(part), visibleMeshes(), onChange, onEdit
    this.mode = 'vertex'; this.part = null; this.sel = new Set();
    this.mirrorX = false; this.soft = 0; this.step = 1; // soft radius and nudge step in mm
    this.undo = []; this.redo = []; this.grab = null; this.active = false; this.hover = null;
    this.raycaster = new THREE.Raycaster();
    this.overlay = new THREE.Group(); this.overlay.renderOrder = 998;
    const mat = (color, opacity, extra = {}) => ({ color, transparent: true, opacity, depthWrite: false, ...extra });
    this.wire = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial(mat(0x9fd3ff, 0.28)));
    this.selLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial(mat(0xffb347, 1)));
    this.selFaces = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial(mat(0xff9a2e, 0.35, { side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 })));
    this.points = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial(mat(0xffc266, 1, { size: 7, sizeAttenuation: false })));
    this.hoverLine = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial(mat(0xffffff, 0.95, { depthTest: false })));
    this.hoverPts = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial(mat(0xffffff, 1, { size: 9, sizeAttenuation: false, depthTest: false })));
    this.overlay.add(this.wire, this.selFaces, this.selLines, this.points, this.hoverLine, this.hoverPts);
    for (const o of this.overlay.children) { o.frustumCulled = false; o.renderOrder = 998; }
    this.handlers = {
      down: e => this.pointerDown(e), move: e => this.pointerMove(e), up: e => this.pointerUp(e),
      key: e => this.keyDown(e), ctx: e => { if (this.grab) e.preventDefault(); },
    };
  }

  start() {
    if (this.active) return;
    this.active = true;
    this.scene.add(this.overlay);
    this.stage.addEventListener('pointerdown', this.handlers.down, true);
    this.stage.addEventListener('pointermove', this.handlers.move, true);
    this.stage.addEventListener('pointerup', this.handlers.up, true);
    this.stage.addEventListener('contextmenu', this.handlers.ctx, true);
    window.addEventListener('keydown', this.handlers.key);
    this.draw(); this.onChange();
  }
  stop() {
    if (!this.active) return;
    if (this.grab) this.cancelGrab();
    this.active = false; this.hover = null;
    this.scene.remove(this.overlay);
    this.stage.removeEventListener('pointerdown', this.handlers.down, true);
    this.stage.removeEventListener('pointermove', this.handlers.move, true);
    this.stage.removeEventListener('pointerup', this.handlers.up, true);
    this.stage.removeEventListener('contextmenu', this.handlers.ctx, true);
    window.removeEventListener('keydown', this.handlers.key);
  }
  // The character changed from outside (another saved character loaded): drop history that no longer applies.
  forget() { this.undo = []; this.redo = []; this.sel.clear(); this.part = null; this.draw(); this.onChange(); }

  // ---- picking
  pick(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
    const h = this.raycaster.intersectObjects(this.visibleMeshes(), false)[0];
    if (!h || !h.face) return null;
    const shape = this.shapeFor(h.object.userData.part);
    if (!shape) return null;
    const tri = shape.triangle(h.object, h.face);
    // Barycentric weights of the hit, in mesh space (the rig is in its rest pose while editing).
    const local = h.object.worldToLocal(h.point.clone());
    const p = tri.map(w => new THREE.Vector3().fromArray(shape.cur, w * 3));
    const bary = new THREE.Triangle(...p).getBarycoord(local, new THREE.Vector3()) || new THREE.Vector3(1 / 3, 1 / 3, 1 / 3);
    const b = [bary.x, bary.y, bary.z], order = [0, 1, 2].sort((i, j) => b[j] - b[i]);
    let ids;
    if (this.mode === 'vertex') ids = [tri[order[0]]];
    else if (this.mode === 'edge') ids = [tri[order[0]], tri[order[1]]];
    else ids = tri;
    return { shape, ids };
  }

  // ---- pointer
  pointerDown(e) {
    if (this.grab) {
      e.stopPropagation(); e.preventDefault();
      if (e.button === 0) this.confirmGrab(); else this.cancelGrab();
      return;
    }
    if (e.button !== 0) return;
    this.press = { x: e.clientX, y: e.clientY, shift: e.shiftKey || e.ctrlKey }; // a click selects; a drag still orbits
  }
  pointerMove(e) {
    this.mouse = { clientX: e.clientX, clientY: e.clientY };
    if (this.grab) { e.stopPropagation(); this.updateGrab(); return; }
    if (e.buttons) return;
    const h = this.pick(e);
    const key = h ? h.shape.id + ':' + h.ids.join(',') : null;
    if (key !== this.hover?.key) { this.hover = h ? { ...h, key } : null; this.drawHover(); }
  }
  pointerUp(e) {
    const p = this.press; this.press = null;
    if (!p || this.grab || e.button !== 0 || Math.hypot(e.clientX - p.x, e.clientY - p.y) > 4) return;
    const h = this.pick(e);
    if (!h) { if (!p.shift) this.select(null); return; }
    this.select(h, p.shift);
  }
  select(h, add) {
    if (!h) { this.sel.clear(); }
    else {
      if (this.part !== h.shape) { this.part = h.shape; this.sel.clear(); }
      else if (!add) this.sel.clear();
      const all = h.ids.every(w => this.sel.has(w));
      for (const w of h.ids) add && all ? this.sel.delete(w) : this.sel.add(w);
    }
    this.draw(); this.onChange();
  }
  grow() {
    if (!this.part) return;
    for (const w of [...this.sel]) for (const n of this.part.neighbours(w)) this.sel.add(n);
    this.draw(); this.onChange();
  }

  keyDown(e) {
    if (e.target.closest?.('input, textarea, [contenteditable="true"]') && e.target.type !== 'range' && e.target.type !== 'checkbox') return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? this.redoStep() : this.undoStep(); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); this.redoStep(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (this.grab) {
      if (k === 'escape') { e.preventDefault(); this.cancelGrab(); }
      else if (k === 'enter') { e.preventDefault(); this.confirmGrab(); }
      else if (k === 'x' || k === 'y' || k === 'z') { this.grab.axis = this.grab.axis === k ? null : k; this.updateGrab(); this.onChange(); }
      return;
    }
    if (k === 'g') { e.preventDefault(); this.startGrab(); }
    else if (k === '1' || k === '2' || k === '3') { this.mode = ['vertex', 'edge', 'face'][+k - 1]; this.onChange(); }
    else if (k === 'escape') this.select(null);
  }

  // ---- moving
  // The vertices a move affects and how much, as [welded id, x factor, y/z factor]: the selection fully,
  // soft-falloff neighbours partly, and with mirroring the same pattern reflected across the centre
  // (x flipped). The kit's meshes are not vertex-for-vertex symmetric, so the reflection picks the
  // vertices nearest each reflected point rather than exact twins. Where both sides overlap (the
  // centre line) the x moves cancel, so the middle stays in the middle.
  weights() {
    const s = this.part, R = this.soft / 1000, sel = [...this.sel];
    const pts = sel.map(w => [s.cur[w * 3], s.cur[w * 3 + 1], s.cur[w * 3 + 2]]);
    const field = (points, hard) => {
      const f = new Map(hard.map(w => [w, 1]));
      if (R > 0) for (let w = 0; w < s.count; w++) {
        if (f.has(w)) continue;
        let d = Infinity;
        for (const [x, y, z] of points) d = Math.min(d, Math.hypot(s.cur[w * 3] - x, s.cur[w * 3 + 1] - y, s.cur[w * 3 + 2] - z));
        if (d < R) { const t = 1 - d / R; f.set(w, t * t * (3 - 2 * t)); }
      }
      return f;
    };
    const main = field(pts, sel);
    if (!this.mirrorX) return [...main].map(([w, f]) => [w, f, f]);
    const mpts = pts.map(([x, y, z]) => [-x, y, z]);
    const twins = mpts.map(p => this.nearestVertex(p)).filter(w => w >= 0);
    const mirror = field(mpts, twins);
    const out = new Map();
    for (const [w, f] of main) out.set(w, [w, f, f]);
    for (const [w, f] of mirror) {
      const o = out.get(w);
      if (o) { o[1] -= f; o[2] = Math.max(o[2], f); } else out.set(w, [w, -f, f]);
    }
    return [...out.values()];
  }
  nearestVertex([x, y, z]) {
    const s = this.part; let best = -1, bd = 0.008 ** 2; // within 8 mm
    for (let w = 0; w < s.count; w++) {
      const dx = s.cur[w * 3] - x, dy = s.cur[w * 3 + 1] - y, dz = s.cur[w * 3 + 2] - z, d = dx * dx + dy * dy + dz * dz;
      if (d < bd) { bd = d; best = w; }
    }
    return best;
  }
  begin() {
    const wts = this.weights();
    return { wts, before: Float32Array.from(wts.flatMap(([w]) => [this.part.cur[w * 3], this.part.cur[w * 3 + 1], this.part.cur[w * 3 + 2]])) };
  }
  // Move by a mesh-space offset.
  place(job, d) {
    const s = this.part;
    job.wts.forEach(([w, fx, f], i) => {
      s.set(w, job.before[i * 3] + d.x * fx, job.before[i * 3 + 1] + d.y * f, job.before[i * 3 + 2] + d.z * f);
    });
    s.refresh(job.wts.map(([w]) => w));
    this.draw();
  }
  commit(job) {
    const s = this.part, ids = Int32Array.from(job.wts.map(([w]) => w));
    const after = Float32Array.from([...ids].flatMap(w => [s.cur[w * 3], s.cur[w * 3 + 1], s.cur[w * 3 + 2]]));
    this.undo.push({ part: s, ids, before: job.before, after }); if (this.undo.length > 100) this.undo.shift();
    this.redo = [];
    this.emit();
  }
  emit() { this.part.applied = JSON.stringify(this.part.rows()); this.onEdit(this.part.id, this.part.rows()); this.onChange(); }

  worldToLocalDir(v) {
    const m = new THREE.Matrix3().setFromMatrix4(this.part.meshes[0].matrixWorld).invert();
    return v.clone().applyMatrix3(m);
  }
  startGrab() {
    if (!this.part || !this.sel.size || this.grab) return;
    const s = this.part, c = new THREE.Vector3();
    for (const w of this.sel) c.add(new THREE.Vector3().fromArray(s.cur, w * 3));
    c.divideScalar(this.sel.size);
    const centre = this.part.meshes[0].localToWorld(c);
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(this.camera.getWorldDirection(new THREE.Vector3()), centre);
    this.grab = { ...this.begin(), plane, start: null, axis: null };
    this.controls.enabled = false;
    this.grab.start = this.planePoint() || centre;
    this.onChange();
  }
  planePoint() {
    if (!this.mouse) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(((this.mouse.clientX - r.left) / r.width) * 2 - 1, -((this.mouse.clientY - r.top) / r.height) * 2 + 1), this.camera);
    return this.raycaster.ray.intersectPlane(this.grab.plane, new THREE.Vector3());
  }
  updateGrab() {
    const g = this.grab, p = this.planePoint(); if (!p) return;
    let d = p.sub(g.start);
    if (g.axis) {
      const axis = new THREE.Vector3(g.axis === 'x' ? 1 : 0, g.axis === 'y' ? 1 : 0, g.axis === 'z' ? 1 : 0);
      // Along the axis: how far the pointer moved along its on-screen direction.
      d = axis.multiplyScalar(d.dot(axis));
    }
    g.world = d;
    this.place(g, this.worldToLocalDir(d));
    this.onChange();
  }
  confirmGrab() { const g = this.grab; this.grab = null; this.controls.enabled = true; this.commit(g); }
  cancelGrab() { const g = this.grab; this.grab = null; this.controls.enabled = true; this.place(g, new THREE.Vector3()); this.onChange(); }
  nudge(axis, sign) {
    if (!this.part || !this.sel.size || this.grab) return;
    const d = new THREE.Vector3(); d[axis] = sign * this.step / 1000; // world axes: x right, y up, z towards the front
    const job = this.begin();
    this.place(job, this.worldToLocalDir(d)); this.commit(job);
  }

  undoStep() { const s = this.undo.pop(); if (!s) return; this.restore(s, s.before); this.redo.push(s); }
  redoStep() { const s = this.redo.pop(); if (!s) return; this.restore(s, s.after); this.undo.push(s); }
  restore(step, vals) {
    this.part = step.part;
    step.ids.forEach((w, i) => step.part.set(w, vals[i * 3], vals[i * 3 + 1], vals[i * 3 + 2]));
    step.part.refresh([...step.ids]); this.emit(); this.draw();
  }
  resetPart() {
    const s = this.part; if (!s) return;
    const ids = []; for (let w = 0; w < s.count; w++) if (s.isMoved(w)) ids.push(w);
    if (!ids.length) return;
    const job = { wts: ids.map(w => [w, 1, 1]), before: Float32Array.from(ids.flatMap(w => [s.cur[w * 3], s.cur[w * 3 + 1], s.cur[w * 3 + 2]])) };
    ids.forEach(w => s.set(w, s.orig[w * 3], s.orig[w * 3 + 1], s.orig[w * 3 + 2]));
    s.refresh(ids); this.commit(job); this.draw();
  }

  // ---- drawing
  // The wireframe shows the selected part, or before any selection the part under the pointer.
  draw() {
    if (!this.active) return;
    const s = this.part || this.hover?.shape;
    this.shown = s;
    if (!s) { for (const o of this.overlay.children) o.visible = false; return; }
    s.meshes[0].updateMatrixWorld();
    this.overlay.matrixAutoUpdate = false; this.overlay.matrix.copy(s.meshes[0].matrixWorld); this.overlay.matrixWorldNeedsUpdate = true;
    const lift = this.lifted(s), sel = s === this.part ? this.sel : new Set();
    set(this.wire, gather(lift, s.edges));
    const se = []; for (let k = 0; k < s.edges.length; k += 2) if (sel.has(s.edges[k]) && sel.has(s.edges[k + 1])) se.push(s.edges[k], s.edges[k + 1]);
    set(this.selLines, gather(lift, se));
    const sf = []; for (let t = 0; t < s.tris.length; t += 3) if (sel.has(s.tris[t]) && sel.has(s.tris[t + 1]) && sel.has(s.tris[t + 2])) sf.push(s.tris[t], s.tris[t + 1], s.tris[t + 2]);
    set(this.selFaces, gather(s.cur, sf));
    set(this.points, gather(lift, [...sel]));
    this.drawHover(lift);
  }
  drawHover(lift) {
    const h = this.hover;
    if (!this.active) return;
    if ((this.part || h?.shape) !== this.shown) { this.draw(); return; }
    if (!h || this.grab || h.shape !== this.shown) { this.hoverLine.visible = this.hoverPts.visible = false; return; }
    lift ??= this.lifted(h.shape);
    const ids = h.ids, pairs = ids.length === 1 ? [] : ids.length === 2 ? ids : [ids[0], ids[1], ids[1], ids[2], ids[2], ids[0]];
    set(this.hoverLine, gather(lift, pairs));
    set(this.hoverPts, gather(lift, ids));
  }
  // Positions nudged 0.4 mm out along the surface, so lines and points sit on top of it.
  lifted(s) {
    const out = new Float32Array(s.cur.length), m = s.members;
    for (let w = 0; w < s.count; w++) {
      const g = s.meshes[m[w][0]].geometry, n = g.attributes.normal, i = m[w][1];
      const nx = n ? n.getX(i) : 0, ny = n ? n.getY(i) : 0, nz = n ? n.getZ(i) : 0;
      out[w * 3] = s.cur[w * 3] + nx * 4e-4; out[w * 3 + 1] = s.cur[w * 3 + 1] + ny * 4e-4; out[w * 3 + 2] = s.cur[w * 3 + 2] + nz * 4e-4;
    }
    return out;
  }
}

function set(obj, arr) {
  obj.geometry.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  obj.geometry.computeBoundingSphere();
  obj.visible = arr.length > 0;
}
function gather(src, ids) {
  const out = new Float32Array(ids.length * 3);
  for (let k = 0; k < ids.length; k++) { out[k * 3] = src[ids[k] * 3]; out[k * 3 + 1] = src[ids[k] * 3 + 1]; out[k * 3 + 2] = src[ids[k] * 3 + 2]; }
  return out;
}
