# CHARACTER FORGE · character_kit studio

**Version 1.1 — viewport visibility fix.** A **local web-based character assembly tool** built around the supplied `character_kit.zip` from **NOBODY CAME**. The original procedural geometry generator, Blender rig and animation scripts, 17 painted reference sheets, and the face-warping algorithm are included. This is **not** a generic character generator or a remake of the complete Godot game: it is a new visual workstation for the character kit in the ZIP.

## Start on Windows

1. Have **Python 3.10+** and **Blender 5.x** installed (Blender 4.5 also usually works).
2. Unzip the entire folder somewhere writable (for example, `Documents\CharacterForge`).
3. Double-click **`run.bat`**. Its first run installs the small Python web-server dependencies.
4. Open **http://127.0.0.1:8765** if it did not open automatically. The terminal must remain open while you use the tool.

If Blender export says "Blender not found," edit `run.bat` and uncomment/update the BLENDER line to its real path, for example:

```bat
set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

### Start on Linux / macOS

Use a Python 3.10+ virtual environment, install `requirements.txt`, then `python server.py`. For example:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
BLENDER=/path/to/blender python server.py
```

Open **http://127.0.0.1:8765**. `run.sh` offers the short version if your system Python allows pip installs. The viewer needs an internet connection to load Three.js from a version-pinned CDN. The Python server, face generation, stored assets and Blender exports work locally; if Three.js cannot load, the preview falls back to an actual Blender still image. The tool does **not** upload your references to a remote service.

## UI workflow

1. **Choose a face** from the left-hand gallery. The kit includes 17 existing face textures, including the pale agent and federal operative.
2. **Customize appearance**: male/female body mesh, suit/trench/shirt/dress, no/short/long hair, fedora, glasses and model height multiplier.
3. **Choose surface colors** under `MATERIALS`; these are stored in the exported glTF materials (not just a browser-only preview).
4. **Preview animations** under `MOTION`. All 13 original named animations are preserved in GLB exports.
5. **Save character** to the local project library, then use **Export model** to download a rigged GLB or Godot-ready ZIP.

### Import a new painted face

Use **Import a new face**, choose an image, then:

- Drag the crop corners to isolate the **front of the face**. Drag inside the rectangle to move it around a contact sheet.
- Click the **Left eye**, **Right eye**, or **Lip center** tool, then click the corresponding point on the reference.
- Choose the studio backdrop color (white by default, or dark grey for studio photos). Background tolerance controls which colors are removed.
- Give the result a **new face ID** and click **Generate face texture**. The original `faces_from_refs.py` warp/fill process writes a 1024×1024 PNG that wraps round the whole head (front view only; built-in faces also use a profile view). It appears in the face gallery immediately.
- In head mode, **Map sources** chooses which view of the reference (front, side, both or a smooth fill) paints each part of the head, previews the regions on the 3D head, and rebakes the texture.
- In head mode, **Touch up** paints straight onto the 3D head: Paint, Smudge, Blur and Pick (colour), with size in millimetres, strength, softness, undo/redo and Save. Left-drag brushes, right-drag orbits; the pose holds still while you work. Brushes follow the head's surface, so strokes carry on across the texture's seams. Saving keeps the previous texture as `face_<id>.prev.png` and your strokes as `face_<id>.touch.png`, which every rebake lays back on top; **Remove all saved touch-ups** rebakes without them.
- **Edit shape** (in the viewport's bottom bar) moves the model's vertices. Click to select a vertex, edge or face (1 / 2 / 3; Shift-click adds or removes), then **Move** (G) follows the mouse until you click; X, Y or Z locks it to an axis, right-click or Esc cancels. **Nudge** moves by a set number of millimetres. **Mirror left / right** repeats a move on the other side; **Soft falloff** drags nearby vertices along for smooth changes. Drag still orbits, and the rig holds its rest pose while you edit. Edits belong to the character: **Save character** keeps them and the export applies them in Blender.

The original painted eyes and expressions are 2D face textures projected onto an existing 3D head. This does not automatically reconstruct a unique head mesh or a fully sculpted likeness from the reference. The original source kit notes that the common head shape works better than its earlier per-person head deformations.

### Exported model contents

`Rigged GLB` creates one character containing **one** appropriate body, one leg mesh, one outfit, and the chosen accessories. It retains the **shared skeleton, skin weights, UVs, vertex colors, embedded 1024×1024 face texture, and 13 animation actions**. The resulting file imports through Godot's glTF importer or Blender's glTF importer. The `Godot-ready package` additionally includes `character.json`, a separate editable face PNG, and instructions.

The source `human.glb` is included in this archive and was generated from the included Blender script. Use the **? → Rebuild base geometry** action in the web UI if you edit the procedural geometry generator and want a fresh source GLB. You can also run `python character_kit/build.py --models` using the BLENDER environment variable; the standalone build skips Godot import if there's no `project.godot` file.

## Project layout

| Directory | Description |
|---|---|
| `character_kit/` | Original Blender geometry/rig code and painted reference sheets, with small standalone compatibility patches and `blender/export_character.py` added |
| `assets/models/human.glb` | Prebuilt original character kit containing all mesh variants and animations |
| `assets/textures/` | Generated 1024×1024 face textures (wrapped round the head) used by the preview and Blender exports |
| `static/` | Web UI, preview image and Three.js-based 3D viewer |
| `server.py` | Local FastAPI server, face processing, saved characters, exports and geometry rebuild |
| `data/characters.json` | Saved characters (populated with four example presets on first launch) |
| `data/custom_faces.json` | Custom face definitions |
| `exports/` | Local copies of compiled character GLBs / ZIPs |
| `qa.py` | Noninteractive check of source assets and animations |

## Version 1.1 viewport fix

If you had an earlier version showing a grid and floor but no character even though the status said `MODEL LOADED`, **update the `static/` files from the viewport-fix patch** and hard-refresh the browser with **Ctrl+F5**. The bug was in the Three.js scene hierarchy: multi-material characters are loaded as named groups containing primitive meshes. The original viewer hid every child mesh by comparing its name against the parent group's name. Version 1.1 applies appearance visibility at the group level, so the body, wardrobe and accessories appear together as intended.

The patch overwrites only four frontend files and does not touch `data/`, `assets/`, `exports/`, or `character_kit/`.

## Technical notes / limits

- The original kit uses a small fixed wardrobe and **two stylized hair caps**, not a large modular clothing library. All character variations are assembled from these real source meshes; the UI does not pretend to have geometry it cannot export.
- All animation clips are preserved **by original names**: `idle`, `still`, `walk`, `run`, `agent_walk`, `talk`, `phone`, `sit`, `cower`, `reach`, `cuffed`, `cast`, `dead`.
- The original material surface names (`face`, `skin`, `top`, `shirt`, `tie`, `pants`, `shoes`, `skirt`, `hat`, `band`, `hair`, `lens`) are kept compatible with the source kit.
- `run.bat` hosts **only** on `127.0.0.1`, for local access. There's no external account, upload, database or network API to connect.
- The supplied ZIP did **not** include the rest of the NOBODY CAME game (`project.godot`, world scene, `character.gd` etc.), so this package exports standalone assets, not an edited runnable game. You can import the exported GLBs into your own Godot project.
- The Three.js viewer is loaded from `cdn.jsdelivr.net` (version 0.170.0); license is MIT, copyright Three.js authors. The rest of the interface uses no external JavaScript dependencies. If the browser is offline, an actual rendered sample remains visible but won't respond to model changes.

## Smoke-tested

Using Blender **5.2.1 LTS**, the included procedural source was built to a working `human.glb`. The web API generated all 17 supplied face maps and processed a fresh uploaded face. Male agent and female dress exports were tested. Both exported models contained exactly **one skin, all 13 animation clips, and one embedded face image**. The packaging API produced the documented Godot-ready ZIP members.
