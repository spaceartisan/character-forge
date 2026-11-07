# Character Forge — Functional verification

- [x] Unpacked and inspected the supplied `character_kit.zip` source.
- [x] Located Blender 5.2.1 in the user's DEV_TOOLS library and successfully ran its procedural generator.
- [x] Built `assets/models/human.glb`: 12 mesh variants, 1 skin, 13 animation clips.
- [x] Ran the source face conversion script: 17 textures, all 512×512.
- [x] Started the FastAPI server and queried `/api/catalog` successfully.
- [x] Tested image upload endpoint with one of the reference sheets.
- [x] Tested Face Lab's backend using a crop/three landmarks: produced a new 512×512 face texture, then removed test artifacts.
- [x] Tested male pale-agent glTF export: 5 selected mesh variants, 1 skin, 13 animation clips, 1 embedded image.
- [x] Tested female dress with long hair as a ZIP export: 4 selected mesh variants, 1 skin, 13 animation clips, 1 embedded image.
- [x] Inspected Godot-ready ZIP members: GLB, face PNG, configuration JSON, instructions.
- [x] Node.js syntax checks of frontend JS modules; Python compilation checks.
- [x] Rendered an actual character from the exported agent GLB in Blender.
- [x] Static project QA checks (`python qa.py`).
- [ ] Interactive Chrome screenshot/Three.js runtime validation could not be completed: sandbox Chromium navigation returned `ERR_BLOCKED_BY_ADMINISTRATOR` even on `data:` URLs. The viewer uses version-pinned Three.js imports from a public CDN.

The tool uses the kit's existing shared head and body silhouettes; it doesn't procedurally construct entirely new head shapes, hair geometry or outfits.


## v1.1 — Empty viewport fix

**Issue shown by user:** the original GLB loaded with 17 joints and 13 animations, floor and controls drew correctly, but the character was invisible.

**Cause:** the GLB has 12 named mesh nodes, but many have multiple primitives/materials. `GLTFLoader` represents those nodes as groups whose child meshes have different generated names. The UI gathered only `isMesh` descendants, then hid all selected components by comparing leaf names to the 12 parent names. Clothing and body vanished, while the GLB remained loaded.

**Fix:** `static/character-parts.mjs` resolves named group/mesh nodes with `root.getObjectByName`, and toggles the full part's visibility. `viewer.js` retains a separate list of leaf meshes for coloring and face maps. An absent mandatory part now throws instead of claiming it loaded. The frontend includes a cache-busted viewer script.

**Verification:** 6/6 Node tests passed against the included actual GLB node tree. Tests check all 12 named parts, multipart group recognition, full agent outfit, female dress/hair, body/outfit combinations, and missing-part diagnostic. JavaScript syntax checks and `python qa.py` passed. **Visual browser test remains unverified** because the sandbox's Chromium cannot navigate even to localhost (`ERR_BLOCKED_BY_ADMINISTRATOR`); end-user visual confirmation is still necessary.
