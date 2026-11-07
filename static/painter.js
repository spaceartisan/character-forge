/* Brush touch-ups on the 3D head: paint, smudge, blur and pick colour.
 *
 * Brushes work on the head's surface, not in texture space: the face map is several
 * unwrapped pieces (front portrait, sides, crown), so a round dab in the texture would
 * break at every seam. Instead, the face triangles are rasterised once into the
 * texture to give each texel its rest-pose position and normal, and a dab touches
 * every texel within its radius on the surface, whichever piece it lies in.
 * Sizes are in millimetres on the head.
 */
import * as THREE from 'three';

const TEX = 1024;
const GUTTER = 4;        // texels round each piece that copy their nearest painted texel (filtering/mipmaps)
const CELL = 0.004;      // spatial grid for dab lookups (m)
const UNDO_LIMIT = 40;

export const TOOLS = {
  paint:  { label: 'Paint',  key: 'p', strength: 0.6, spacing: 0.25 },
  smudge: { label: 'Smudge', key: 's', strength: 0.7, spacing: 0.25 }, // each dab pulls from a few texels back
  blur:   { label: 'Blur',   key: 'b', strength: 0.5, spacing: 0.3 },
  pick:   { label: 'Pick',   key: 'i' },
};

export class FacePainter {
  constructor(viewer, stage, { onChange, onPick } = {}) {
    this.viewer = viewer; this.stage = stage;
    this.onChange = onChange || (() => {}); this.onPick = onPick || (() => {});
    this.tool = 'paint'; this.color = [200, 150, 120];
    this.size = 8; this.softness = 0.5;
    this.strengths = Object.fromEntries(Object.entries(TOOLS).map(([k, t]) => [k, t.strength ?? 1]));
    this.maps = new Map(); // geometry uuid -> surface maps
    this.undo = []; this.redo = []; this.savedAt = 0; this.version = 0;
    this.stroke = null; this.active = false;
    this.strokePos = new Int32Array(TEX * TEX).fill(-1);
    this.handlers = {
      down: e => this.pointerDown(e), move: e => this.pointerMove(e),
      up: e => this.pointerUp(e), leave: () => this.viewer.setPaintCursor(null),
      key: e => this.keyDown(e),
    };
  }

  get dirty() { return this.version !== this.savedAt; }
  get strength() { return this.strengths[this.tool] ?? 1; }
  set strength(v) { this.strengths[this.tool] = v; }

  async start(face) {
    this.face = face;
    const bust = '?v=' + Date.now();
    const bitmap = await loadBitmap('/textures/face_' + encodeURIComponent(face) + '.png' + bust);
    if (!bitmap) throw new Error('Could not load the face texture');
    this.data = new Uint8Array(readPixels(bitmap).buffer);
    for (let i = 3; i < this.data.length; i += 4) this.data[i] = 255;
    // Earlier touch-ups: their coverage is kept so later rebakes lay them back on.
    this.mask = new Uint8Array(TEX * TEX);
    const touch = await loadBitmap('/textures/face_' + encodeURIComponent(face) + '.touch.png' + bust);
    if (touch) { const px = readPixels(touch); for (let i = 0; i < this.mask.length; i++) this.mask[i] = px[i * 4 + 3]; }
    this.hadTouch = Boolean(touch);
    this.texture = new THREE.DataTexture(this.data, TEX, TEX, THREE.RGBAFormat);
    Object.assign(this.texture, {
      flipY: false, colorSpace: THREE.SRGBColorSpace, wrapS: THREE.RepeatWrapping, wrapT: THREE.ClampToEdgeWrapping,
      magFilter: THREE.LinearFilter, minFilter: THREE.LinearMipmapLinearFilter, generateMipmaps: true, anisotropy: 8,
    });
    this.texture.needsUpdate = true;
    this.undo = []; this.redo = []; this.version = this.savedAt = 0;
    this.viewer.setPaintTexture(this.texture);
    this.active = true;
    this.stage.addEventListener('pointerdown', this.handlers.down, true);
    this.stage.addEventListener('pointermove', this.handlers.move, true);
    this.stage.addEventListener('pointerup', this.handlers.up, true);
    this.stage.addEventListener('pointercancel', this.handlers.up, true);
    this.stage.addEventListener('pointerleave', this.handlers.leave);
    window.addEventListener('keydown', this.handlers.key);
    this.onChange();
  }

  stop() {
    if (!this.active) return;
    this.active = false; this.stroke = null;
    this.stage.removeEventListener('pointerdown', this.handlers.down, true);
    this.stage.removeEventListener('pointermove', this.handlers.move, true);
    this.stage.removeEventListener('pointerup', this.handlers.up, true);
    this.stage.removeEventListener('pointercancel', this.handlers.up, true);
    this.stage.removeEventListener('pointerleave', this.handlers.leave);
    window.removeEventListener('keydown', this.handlers.key);
    this.viewer.setPaintCursor(null);
    this.viewer.setPaintTexture(null);
    this.texture?.dispose(); this.texture = null; this.data = null; this.mask = null;
  }

  // ---- surface maps: rest position + normal per texel, gutters, spatial grid
  surfaceFor(mesh) {
    const geo = mesh.geometry;
    const key = geo.uuid + ':' + (geo.userData.shapeVersion || 0); // rebuilt after shape edits
    let m = this.maps.get(key);
    if (!m) { for (const k of this.maps.keys()) if (k.startsWith(geo.uuid)) this.maps.delete(k); m = buildSurface(geo); this.maps.set(key, m); }
    return m;
  }

  // ---- input
  hitAt(e) {
    const h = this.viewer.paintHit(e.clientX, e.clientY);
    if (!h) return null;
    const s = this.surfaceFor(h.mesh);
    const geo = h.mesh.geometry, pos = geo.attributes.position, nrm = geo.attributes.normal, uv = geo.attributes.uv;
    const X = [0, 0, 0], N = [0, 0, 0], U = [0, 0];
    h.tri.forEach((vi, k) => {
      const w = h.bary[k];
      X[0] += pos.getX(vi) * w; X[1] += pos.getY(vi) * w; X[2] += pos.getZ(vi) * w;
      if (nrm) { N[0] += nrm.getX(vi) * w; N[1] += nrm.getY(vi) * w; N[2] += nrm.getZ(vi) * w; }
      U[0] += uv.getX(vi) * w; U[1] += uv.getY(vi) * w;
    });
    normalise(N);
    // Texels per metre here, from the triangle's area in the texture vs. on the head.
    const [a, b, c] = h.tri;
    const ra = triArea(pos, a, b, c), ua = uvArea(uv, a, b, c) * TEX * TEX;
    const density = ra > 1e-12 && ua > 1e-6 ? Math.sqrt(ua / ra) : 2133;
    return { ...h, surface: s, X, N, U, density, unit: h.scale };
  }

  pointerDown(e) {
    if (!this.active || e.button !== 0) return;
    const hit = this.hitAt(e);
    if (!hit) return; // off the head: leave the drag to the orbit controls
    e.stopPropagation(); e.preventDefault();
    if (this.tool === 'pick' || e.altKey) { this.pick(hit); return; }
    this.stage.setPointerCapture(e.pointerId);
    this.stroke = { tool: this.tool, surface: hit.surface, idx: [], old: [], oldMask: [], alpha: [], last: null, density: hit.density, screen: [e.clientX, e.clientY] };
    this.dabTo(hit);
    this.showCursor(hit);
  }

  pointerMove(e) {
    if (!this.active) return;
    if (this.stroke) e.stopPropagation();
    const hit = this.hitAt(e);
    this.showCursor(hit);
    if (!this.stroke) return;
    // Fast strokes: follow the pointer's path across the screen, a few pixels at a time, so the
    // stroke stays on the surface (over the nose, round the jaw) instead of cutting through it.
    const from = this.stroke.screen, to = [e.clientX, e.clientY];
    const steps = from ? Math.min(32, Math.floor(Math.hypot(to[0] - from[0], to[1] - from[1]) / 4)) : 0;
    for (let i = 1; i < steps; i++) {
      const t = i / steps, h = this.hitAt({ clientX: from[0] + (to[0] - from[0]) * t, clientY: from[1] + (to[1] - from[1]) * t });
      if (h && h.surface === this.stroke.surface) this.dabTo(h);
    }
    this.stroke.screen = to;
    if (hit && hit.surface === this.stroke.surface) this.dabTo(hit);
  }

  pointerUp(e) {
    if (!this.stroke) return;
    e.stopPropagation();
    try { this.stage.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    this.endStroke();
  }

  keyDown(e) {
    if (e.target.closest?.('input, textarea, [contenteditable="true"]') && e.target.type !== 'range') return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? this.redoStep() : this.undoStep(); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); this.redoStep(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (k === '[' || k === ']') { this.size = clamp(this.size * (k === ']' ? 1.15 : 1 / 1.15), 1, 40); this.onChange(); return; }
    const tool = Object.entries(TOOLS).find(([, t]) => t.key === k);
    if (tool) { this.tool = tool[0]; this.onChange(); }
  }

  showCursor(hit) {
    if (!hit) { this.viewer.setPaintCursor(null); return; }
    const r = this.size / 2000;
    this.viewer.setPaintCursor({ point: hit.point, normal: hit.normal, radius: r * hit.unit, inner: this.tool === 'pick' ? 0 : 1 - this.softness });
  }

  pick(hit) {
    const x = ((Math.floor(hit.U[0] * TEX) % TEX) + TEX) % TEX, y = clamp(Math.floor(hit.U[1] * TEX), 0, TEX - 1);
    const i = (y * TEX + x) * 4;
    this.color = [this.data[i], this.data[i + 1], this.data[i + 2]];
    this.onPick(this.color);
    this.onChange();
  }

  // ---- strokes
  dabTo(hit) {
    const st = this.stroke, R = this.size / 2000;
    // Smudge must move at least ~3 texels per dab, or "the colour just behind" rounds to the texel itself.
    const spacing = Math.max(R * TOOLS[st.tool].spacing, st.tool === 'smudge' ? 3 / st.density : 0.0002);
    if (!st.last) { this.dab(hit.X, hit.N, null); st.last = { X: hit.X, N: hit.N }; this.flush(); return; }
    const a = st.last.X, d = dist(a, hit.X);
    if (d > R * 4) { this.dab(hit.X, hit.N, null); st.last = { X: hit.X, N: hit.N }; this.flush(); return; } // jumped (e.g. over an ear)
    if (d < spacing) return;
    const steps = Math.floor(d / spacing);
    let prev = a;
    for (let i = 1; i <= steps; i++) {
      const t = (i * spacing) / d;
      const X = lerp3(a, hit.X, t), N = normalise(lerp3(st.last.N, hit.N, t));
      this.dab(X, N, [X[0] - prev[0], X[1] - prev[1], X[2] - prev[2]]);
      prev = X;
    }
    st.last = { X: prev, N: hit.N };
    this.flush();
  }

  dab(X, N, delta) {
    const st = this.stroke, s = st.surface, R = this.size / 2000, hard = 1 - this.softness;
    const strength = this.strength, tool = st.tool;
    const reach = tool === 'smudge' && delta ? R + Math.hypot(...delta) : R;
    const near = s.query(X, reach);
    const hits = []; // [texel, falloff]
    for (const t of near) {
      const px = s.pos[t * 3] - X[0], py = s.pos[t * 3 + 1] - X[1], pz = s.pos[t * 3 + 2] - X[2];
      const q = Math.sqrt(px * px + py * py + pz * pz) / R;
      if (q >= 1) continue;
      // Skip the far side of thin parts (lips, ears, nostrils).
      if (s.nrm[t * 3] * N[0] + s.nrm[t * 3 + 1] * N[1] + s.nrm[t * 3 + 2] * N[2] < 0.1) continue;
      hits.push(t, falloff(q, hard));
    }
    if (!hits.length) return;
    const d = this.data, out = new Float32Array(hits.length / 2 * 4); // r, g, b, amount
    if (tool === 'paint') {
      const [cr, cg, cb] = this.color;
      for (let k = 0; k < hits.length; k += 2) {
        const t = hits[k], j = this.touch(t), a = Math.max(st.alpha[j], strength * hits[k + 1]);
        st.alpha[j] = a;
        const o = j * 3, w = (k / 2) * 4;
        out[w] = st.old[o] + (cr - st.old[o]) * a; out[w + 1] = st.old[o + 1] + (cg - st.old[o + 1]) * a;
        out[w + 2] = st.old[o + 2] + (cb - st.old[o + 2]) * a; out[w + 3] = a;
      }
    } else if (tool === 'blur') {
      // Average the texels around each one on the surface (a small window in the texture,
      // keeping only neighbours that really are next to it on the head).
      const kpx = clamp(Math.round(R * 0.35 * st.density), 1, 4), lim = (kpx + 1.5) / st.density, lim2 = lim * lim;
      for (let k = 0; k < hits.length; k += 2) {
        const t = hits[k], tx = t % TEX, ty = (t / TEX) | 0;
        let sr = 0, sg = 0, sb = 0, n = 0;
        for (let dy = -kpx; dy <= kpx; dy++) {
          const y = ty + dy; if (y < 0 || y >= TEX) continue;
          for (let dx = -kpx; dx <= kpx; dx++) {
            const u = y * TEX + ((tx + dx + TEX) % TEX);
            if (!s.covered[u]) continue;
            const ex = s.pos[u * 3] - s.pos[t * 3], ey = s.pos[u * 3 + 1] - s.pos[t * 3 + 1], ez = s.pos[u * 3 + 2] - s.pos[t * 3 + 2];
            if (ex * ex + ey * ey + ez * ez > lim2) continue;
            sr += d[u * 4]; sg += d[u * 4 + 1]; sb += d[u * 4 + 2]; n++;
          }
        }
        const a = strength * hits[k + 1], w = (k / 2) * 4, i = t * 4;
        out[w] = d[i] + (sr / n - d[i]) * a; out[w + 1] = d[i + 1] + (sg / n - d[i + 1]) * a;
        out[w + 2] = d[i + 2] + (sb / n - d[i + 2]) * a; out[w + 3] = a;
      }
    } else if (tool === 'smudge') {
      if (!delta) return; // the first dab has no direction yet
      // Pull colour along the stroke: each texel takes the colour from where the brush just was.
      const grid = new FineGrid(s, near), dx = delta[0], dy = delta[1], dz = delta[2];
      for (let k = 0; k < hits.length; k += 2) {
        const t = hits[k], i = t * 4, w = (k / 2) * 4;
        const src = grid.nearest(s.pos[t * 3] - dx, s.pos[t * 3 + 1] - dy, s.pos[t * 3 + 2] - dz);
        const a = src < 0 ? 0 : strength * hits[k + 1];
        const j = src < 0 ? i : src * 4;
        out[w] = d[i] + (d[j] - d[i]) * a; out[w + 1] = d[i + 1] + (d[j + 1] - d[i + 1]) * a;
        out[w + 2] = d[i + 2] + (d[j + 2] - d[i + 2]) * a; out[w + 3] = a;
      }
    }
    for (let k = 0; k < hits.length; k += 2) {
      const w = (k / 2) * 4;
      if (out[w + 3] <= 0.002) continue;
      const t = hits[k]; this.touch(t);
      this.write(t, out[w], out[w + 1], out[w + 2], Math.max(this.mask[t], Math.round(out[w + 3] * 255)));
    }
  }

  touch(t) {
    const st = this.stroke;
    let j = this.strokePos[t];
    if (j < 0) {
      j = st.idx.length; this.strokePos[t] = j; st.idx.push(t);
      st.old.push(this.data[t * 4], this.data[t * 4 + 1], this.data[t * 4 + 2]); st.oldMask.push(this.mask[t]); st.alpha.push(0);
    }
    return j;
  }

  write(t, r, g, b, m, surface = this.stroke.surface) {
    const d = this.data;
    d[t * 4] = r; d[t * 4 + 1] = g; d[t * 4 + 2] = b; this.mask[t] = m;
    for (let k = surface.gStart[t]; k < surface.gStart[t + 1]; k++) {
      const g = surface.gItems[k];
      d[g * 4] = d[t * 4]; d[g * 4 + 1] = d[t * 4 + 1]; d[g * 4 + 2] = d[t * 4 + 2]; this.mask[g] = m;
    }
  }

  flush() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => { this.pending = 0; if (this.texture) this.texture.needsUpdate = true; });
  }

  endStroke() {
    const st = this.stroke; this.stroke = null;
    if (!st || !st.idx.length) return;
    const n = st.idx.length, idx = Int32Array.from(st.idx), neu = new Uint8Array(n * 3), newMask = new Uint8Array(n);
    for (let j = 0; j < n; j++) {
      const t = idx[j]; this.strokePos[t] = -1;
      neu[j * 3] = this.data[t * 4]; neu[j * 3 + 1] = this.data[t * 4 + 1]; neu[j * 3 + 2] = this.data[t * 4 + 2]; newMask[j] = this.mask[t];
    }
    this.undo.push({ surface: st.surface, idx, old: Uint8Array.from(st.old), oldMask: Uint8Array.from(st.oldMask), neu, newMask, version: ++this.version });
    if (this.undo.length > UNDO_LIMIT) this.undo.shift();
    this.redo = [];
    this.onChange();
  }

  apply(step, which) {
    const rgb = which === 'old' ? step.old : step.neu, m = which === 'old' ? step.oldMask : step.newMask;
    for (let j = 0; j < step.idx.length; j++) this.write(step.idx[j], rgb[j * 3], rgb[j * 3 + 1], rgb[j * 3 + 2], m[j], step.surface);
    this.flush();
  }
  undoStep() {
    const s = this.undo.pop(); if (!s) return;
    this.apply(s, 'old'); this.redo.push(s);
    this.version = this.undo.length ? this.undo[this.undo.length - 1].version : 0;
    this.onChange();
  }
  redoStep() {
    const s = this.redo.pop(); if (!s) return;
    this.apply(s, 'neu'); this.undo.push(s); this.version = s.version;
    this.onChange();
  }

  // ---- saving
  async save(api) {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = TEX;
    const g = canvas.getContext('2d');
    g.putImageData(new ImageData(new Uint8ClampedArray(this.data), TEX, TEX), 0, 0);
    const image = canvas.toDataURL('image/png');
    const m = new Uint8ClampedArray(TEX * TEX * 4);
    for (let i = 0; i < this.mask.length; i++) { m[i * 4] = m[i * 4 + 1] = m[i * 4 + 2] = this.mask[i]; m[i * 4 + 3] = 255; }
    g.putImageData(new ImageData(m, TEX, TEX), 0, 0);
    const mask = canvas.toDataURL('image/png');
    const r = await api('/api/faces/' + encodeURIComponent(this.face) + '/paint', { method: 'POST', body: JSON.stringify({ image, mask }) });
    this.savedAt = this.version; this.hadTouch = r.touch;
    this.onChange();
    return r;
  }
}

// ---------------------------------------------------------------------------------------------
function buildSurface(geo) {
  const pos = geo.attributes.position, nrm = geo.attributes.normal, uv = geo.attributes.uv;
  const index = geo.index ? geo.index.array : null;
  const triCount = index ? index.length / 3 : pos.count / 3;
  const P = new Float32Array(TEX * TEX * 3), Nm = new Float32Array(TEX * TEX * 3), covered = new Uint8Array(TEX * TEX);
  const vi = k => (index ? index[k] : k);
  for (let f = 0; f < triCount; f++) {
    const a = vi(f * 3), b = vi(f * 3 + 1), c = vi(f * 3 + 2);
    const ax = uv.getX(a) * TEX, ay = uv.getY(a) * TEX, bx = uv.getX(b) * TEX, by = uv.getY(b) * TEX, cx = uv.getX(c) * TEX, cy = uv.getY(c) * TEX;
    const den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
    if (Math.abs(den) < 1e-9) continue;
    const x0 = Math.floor(Math.min(ax, bx, cx)), x1 = Math.ceil(Math.max(ax, bx, cx));
    const y0 = Math.max(0, Math.floor(Math.min(ay, by, cy))), y1 = Math.min(TEX - 1, Math.ceil(Math.max(ay, by, cy)));
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const px = x + 0.5, py = y + 0.5;
      const w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den;
      const w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den;
      const w2 = 1 - w0 - w1;
      if (w0 < -1e-4 || w1 < -1e-4 || w2 < -1e-4) continue;
      const t = y * TEX + (((x % TEX) + TEX) % TEX);
      covered[t] = 1;
      for (let k = 0; k < 3; k++) {
        P[t * 3 + k] = pos.getComponent(a, k) * w0 + pos.getComponent(b, k) * w1 + pos.getComponent(c, k) * w2;
        Nm[t * 3 + k] = nrm ? nrm.getComponent(a, k) * w0 + nrm.getComponent(b, k) * w1 + nrm.getComponent(c, k) * w2 : 0;
      }
      const l = Math.hypot(Nm[t * 3], Nm[t * 3 + 1], Nm[t * 3 + 2]) || 1;
      Nm[t * 3] /= l; Nm[t * 3 + 1] /= l; Nm[t * 3 + 2] /= l;
    }
  }
  // Gutters: texels just outside each piece copy their nearest painted texel.
  const owner = new Int32Array(TEX * TEX).fill(-1);
  let frontier = [];
  for (let t = 0; t < covered.length; t++) if (covered[t]) { owner[t] = t; frontier.push(t); }
  for (let ring = 0; ring < GUTTER; ring++) {
    const next = [];
    for (const t of frontier) {
      const x = t % TEX, y = (t / TEX) | 0;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const yy = y + dy; if (yy < 0 || yy >= TEX) continue;
        const u = yy * TEX + ((x + dx + TEX) % TEX);
        if (owner[u] < 0) { owner[u] = owner[t]; next.push(u); }
      }
    }
    frontier = next;
  }
  const gStart = new Int32Array(TEX * TEX + 1);
  for (let t = 0; t < owner.length; t++) if (owner[t] >= 0 && !covered[t]) gStart[owner[t] + 1]++;
  for (let t = 0; t < TEX * TEX; t++) gStart[t + 1] += gStart[t];
  const gItems = new Int32Array(gStart[TEX * TEX]), fillAt = gStart.slice(0, TEX * TEX);
  for (let t = 0; t < owner.length; t++) if (owner[t] >= 0 && !covered[t]) gItems[fillAt[owner[t]]++] = t;

  // Spatial grid of the painted texels.
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let t = 0; t < covered.length; t++) if (covered[t]) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[t * 3 + k]); hi[k] = Math.max(hi[k], P[t * 3 + k]); }
  const dim = lo.map((l, k) => Math.max(1, Math.ceil((hi[k] - l) / CELL) + 1));
  const cellOf = t => {
    const i = Math.floor((P[t * 3] - lo[0]) / CELL), j = Math.floor((P[t * 3 + 1] - lo[1]) / CELL), k = Math.floor((P[t * 3 + 2] - lo[2]) / CELL);
    return (k * dim[1] + j) * dim[0] + i;
  };
  const ncell = dim[0] * dim[1] * dim[2], cStart = new Int32Array(ncell + 1);
  for (let t = 0; t < covered.length; t++) if (covered[t]) cStart[cellOf(t) + 1]++;
  for (let c = 0; c < ncell; c++) cStart[c + 1] += cStart[c];
  const cItems = new Int32Array(cStart[ncell]), cFill = cStart.slice(0, ncell);
  for (let t = 0; t < covered.length; t++) if (covered[t]) cItems[cFill[cellOf(t)]++] = t;

  function query(X, r) {
    const out = [];
    const i0 = Math.max(0, Math.floor((X[0] - r - lo[0]) / CELL)), i1 = Math.min(dim[0] - 1, Math.floor((X[0] + r - lo[0]) / CELL));
    const j0 = Math.max(0, Math.floor((X[1] - r - lo[1]) / CELL)), j1 = Math.min(dim[1] - 1, Math.floor((X[1] + r - lo[1]) / CELL));
    const k0 = Math.max(0, Math.floor((X[2] - r - lo[2]) / CELL)), k1 = Math.min(dim[2] - 1, Math.floor((X[2] + r - lo[2]) / CELL));
    for (let k = k0; k <= k1; k++) for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const c = (k * dim[1] + j) * dim[0] + i;
      for (let n = cStart[c]; n < cStart[c + 1]; n++) out.push(cItems[n]);
    }
    return out;
  }
  return { pos: P, nrm: Nm, covered, gStart, gItems, query };
}

// A fine hash of a dab's texels, for "which texel is nearest this point" during smudging.
class FineGrid {
  constructor(s, texels, size = 0.0008) {
    this.s = s; this.size = size; this.cells = new Map();
    for (const t of texels) {
      const key = this.key(Math.floor(s.pos[t * 3] / size), Math.floor(s.pos[t * 3 + 1] / size), Math.floor(s.pos[t * 3 + 2] / size));
      let list = this.cells.get(key); if (!list) this.cells.set(key, list = []);
      list.push(t);
    }
  }
  key(i, j, k) { return (i + 512) * 1048576 + (j + 512) * 1024 + (k + 512); }
  nearest(x, y, z) {
    const s = this.s, i = Math.floor(x / this.size), j = Math.floor(y / this.size), k = Math.floor(z / this.size);
    let best = -1, bd = Infinity;
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let c = -1; c <= 1; c++) {
      const list = this.cells.get(this.key(i + a, j + b, k + c)); if (!list) continue;
      for (const t of list) {
        const dx = s.pos[t * 3] - x, dy = s.pos[t * 3 + 1] - y, dz = s.pos[t * 3 + 2] - z, d = dx * dx + dy * dy + dz * dz;
        if (d < bd) { bd = d; best = t; }
      }
    }
    return best;
  }
}

async function loadBitmap(url) {
  try {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) return null;
    return await createImageBitmap(await r.blob(), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  } catch { return null; }
}
function readPixels(bitmap) {
  const c = document.createElement('canvas'); c.width = c.height = TEX;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(bitmap, 0, 0, TEX, TEX);
  return g.getImageData(0, 0, TEX, TEX).data;
}
function falloff(q, hard) {
  if (q <= hard) return 1;
  const s = (1 - q) / Math.max(1e-6, 1 - hard);
  return s * s * (3 - 2 * s);
}
function triArea(p, a, b, c) {
  const ux = p.getX(b) - p.getX(a), uy = p.getY(b) - p.getY(a), uz = p.getZ(b) - p.getZ(a);
  const vx = p.getX(c) - p.getX(a), vy = p.getY(c) - p.getY(a), vz = p.getZ(c) - p.getZ(a);
  return 0.5 * Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx);
}
function uvArea(u, a, b, c) {
  return 0.5 * Math.abs((u.getX(b) - u.getX(a)) * (u.getY(c) - u.getY(a)) - (u.getX(c) - u.getX(a)) * (u.getY(b) - u.getY(a)));
}
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const lerp3 = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
function normalise(v) { const l = Math.hypot(v[0], v[1], v[2]) || 1; v[0] /= l; v[1] /= l; v[2] /= l; return v; }
