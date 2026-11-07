# Character kit: people, faces and animations for NOBODY CAME

Everything that makes a person in the game is in this folder: the Blender scripts that build the 3D bodies, clothes, hair and animations; the painted reference sheets; and the script that turns those sheets into face textures. One command rebuilds it all into the game.

The game is the folder this one sits in (`..`). It's a Godot 4.7 project. Read `../notes_for_agent.md` before you start; it has the house rules. In particular:

- **Testing:** test only what you changed. Don't run soak tests unless the user asks.
- **Lessons:** add what you learn to `../LESSONS_LEARNED.md`.
- **MPFB:** the user doesn't want MPFB/MakeHuman.

## Rebuild everything

```bash
python character_kit/build.py
```

Run it from anywhere. It does four things, in order:

1. Runs Blender headless on `blender/blender_people.py`. This writes `../assets/models/human.glb`: every mesh, the skeleton and every animation (about 35 seconds).
2. Runs `faces/faces_from_refs.py`. This writes `../assets/textures/face_<id>.png` from the sheets in `faces/references/`.
3. Runs a headless Godot import so the game picks up the new files.
4. Optionally takes screenshots.

**Options:**

| Command | What it does |
|---|---|
| `python character_kit/build.py --faces` | Faces only. Seconds, no Blender. |
| `python character_kit/build.py --models` | `human.glb` only. |
| `python character_kit/build.py --shots C:/somewhere/shots` | After building, runs the game's `people` line-up and saves screenshots there. |

**Screenshots from `--shots`:**

- `people_front`: everyone in a row.
- `people_back`
- `people_face<N>`: close-ups.
- `people_moving`: animations, mid-move.

Always look at them: the numbers won't show you a bad face.

**Tool paths** are set at the top of `build.py`. Override them with the `BLENDER` and `GODOT` environment variables.

**Python needs:** Pillow and numpy.

## What's in here

| Path | What it is |
|---|---|
| `build.py` | The one command above |
| `blender/blender_people.py` | Builds every human mesh from signed distance fields: bodies, heads, hands, clothes, hats, hair, glasses. It meshes them, weights them to the skeleton and bakes ambient occlusion into vertex colours. No base mesh and no add-ons. The docstring at the top describes the coordinate system and lists every mesh. |
| `blender/blender_rig.py` | The skeleton (`build_skeleton`), **all animations** (`build_anims`) and the GLB export. `../tools/blender_models.py` also uses it to build the grey. |
| `faces/faces_from_refs.py` | Turns each reference sheet into a face texture. The `REFS` table at the top lists every face. |
| `faces/references/` | The user's painted sheets. Each shows a front view, and usually a profile too. |
| `faces/grid.py` | Zooms into a sheet with a labelled pixel grid, so you can read off eye and mouth positions. |

**Game files that use this output.** They live in the game, not here. Edit them in place.

| Game file | Role |
|---|---|
| `../scripts/world/character.gd` | Dresses the model per person. It shows and hides meshes, and sets materials by surface name. It also holds `FACE_SKIN`, `FACE_HAIR` and the `*_look()` functions that describe agents, Bureau men and townsfolk. |
| `../scenes/world/character.tscn`, `../scenes/world/npc.tscn` | Instance `human.glb` as the `Model` node. |
| `../scripts/autoload/lore.gd` | `ROSTER`: every townsperson's name, job and face id (`"f": "m5"`). |
| `../scripts/autotest.gd` (`_people`) | The screenshot line-up. Add new faces to its `looks` list so they show up in the shots. |
| `../assets/textures/` | Clothing and skin textures the materials use: `skin`, `cloth`, `suitcloth`, `hair`, `rubber` and `top_*`. They come from the main art pipeline (`../tools/gen_art.py` and `../tools/gimp_post.py`), not from this kit. |

## Faces: how the images become textures

**Current faces:**

| Face id | Who | Sheet |
|---|---|---|
| `m1` | Main townsman, square-jawed | `m1.png` |
| `m2` | Stubbled man | `m2.png` |
| `f1` | Younger woman | `f1.png` |
| `f2` | Older-looking woman | `f2.png` |
| `m3`, `m4`, `f3`, `f4` | Four townsfolk | `sheet2.png`, one panel each |
| `fed` | Bureau men (the FBI agent in sunglasses) | `sheet3.png` |
| `m5`, `m6`, `m7`, `f5`, `f6`, `f7`, `f8` | Outdoorsman, creative, tough, alternative, professional, athletic, academic | `sheet3.png` |
| `agent` | The player's agents (pale man in black) | `agent.png` |

`face_grey.png` (the alien) is still painted in SVG by `../tools/gen_art.py`.

**How a face is made.** Every person shares **one head shape**. The face is a texture projected straight on from the front:

- 512 px covers 24 cm of head, centred 1.665 m up.
- The pupils land at (186, 230) and (326, 230), and the lip line at (256, 381).

`faces_from_refs.py` does the following for each face:

1. Takes the front view out of a box on the sheet. The box keeps out the profile, panel frames and shirt.
2. Warps it so the three points you gave (left pupil, right pupil, lip-line centre) land exactly on those spots.
3. Clears the background:
   - **White sheets:** clears everything near-white.
   - **Grey or black studio backdrops:** flood-fills from the edges, so dark hair inside the face stays.
4. Fills the cleared area from the surrounding skin and hair.
5. Writes `face_<id>.png` and prints a skin colour and a hair colour.

On the head, the edge of the texture wraps onto the sides and the neck, so a soft fill there is right.

### Add a new face from a new image (step by step)

1. **Add the sheet.** Save it as `faces/references/<sheet>.png`. One sheet can hold several people.
2. **Find the points.** For each person, run `python character_kit/faces/grid.py <sheet> <x> <y>`, where `x, y` is roughly the middle of their face.
   - For small faces, use a smaller half-width and step, for example `... 60 5`.
   - Open the grid image and read off three points in **sheet pixels**: the left pupil, the right pupil (the left and right *in the image*) and the centre of the lip line.
   - For painted sunglasses, use the centres of the lenses.
3. **Add a line to `REFS`** in `faces/faces_from_refs.py`:
   ```python
   "m8": ("sheet4", (x0, y0, x1, y1), [(lx, ly), (rx, ry), (mx, my)]),                 # white background
   "f9": ("sheet4", (x0, y0, x1, y1), [(lx, ly), (rx, ry), (mx, my)], (84, 85, 87)),   # studio backdrop colour
   ```
   - **Box:** the front view only. Stop just under the chin or neck, above the shirt, and short of the profile.
   - **Backdrop colour:** the colour of the backdrop near the face.
   - **Tolerance:** a 6th value, `tol` (default 38), sets how far from the backdrop colour a pixel may be and still be cleared. Lower it (for example 22) if grey hair or a grey beard is being cleared.
   - **Face id:** start the id with `m` or `f`. A face id starting with `f` (except `fed`) gets the female body, `person_f`. The skirt and long hair come from the person's `"sex"` in the roster, so set that too.
4. **Build:** run `python character_kit/build.py --faces`. Check `../assets/textures/face_<id>.png`: eyes and mouth in the middle, no stripes of backdrop left.
5. **Register the face** in `../scripts/world/character.gd`. Add `"<id>": Color(...)` to `FACE_SKIN` (used for the hands) and `FACE_HAIR` (used for the hair mesh). Start from the colours the script printed. The skin sample can hit a shadow, so brighten it by eye if the hands look too dark.
6. **Give it to someone:**
   - **A townsperson:** set `"f": "<id>"` on their `ROSTER` entry in `../scripts/autoload/lore.gd`.
   - **Bureau men:** use the face id `fed` (see `fed_look()`).
   - **The agents:** use `agent` (see `agent_look()`).
7. **Look at it:** add the face to the `looks` list in `_people()` in `../scripts/autotest.gd`, then run `python character_kit/build.py --faces --shots <dir>`.

## Models: meshes, skeleton and animations

**Meshes in `human.glb`.** `character.gd` shows exactly one of each kind per person:

| Kind | Meshes |
|---|---|
| Head, neck and hands | `person_m`, `person_f` |
| Legs | `legs_m`; `legs_coat` (trousers from mid-thigh down, worn under the trench coat) |
| Outfit | `outfit_suit`, `outfit_trench`, `outfit_shirt`, `outfit_dress` |
| Extras | `hat`, `hair_short`, `hair_long`, `glasses` |

**Surface (material) names are the contract.** `character.gd` dresses each surface by its name prefix:

`face`, `skin`, `top`, `shirt`, `tie`, `pants`, `shoes`, `skirt`, `hat`, `band`, `hair`, `lens`

A new garment must use these names, or `character.gd` must learn the new one. If you add or rename a mesh, update the show/hide logic in `character.gd` (`set_look`, `outfit_for`) to match.

**Coordinates (Blender):**

- +Z is up and the front of the body faces -Y. x > 0 is the character's left.
- Units are metres; a person is 1.82 m tall.
- The game turns the model to face +Z in `character.tscn` (the `Model` node's transform).

**Skeleton** (`build_skeleton` in `blender_rig.py`): `hips`, `spine`, `chest`, `neck`, `head`, plus `upper_arm`, `lower_arm`, `hand`, `upper_leg`, `lower_leg` and `foot`, each in `.L` and `.R`. Every mesh is weighted by its distance to the bones it may follow.

**Animations** (`build_anims` in `blender_rig.py`, 24 fps). Each is a few keyed poses: bone → (x, y, z) degrees, plus an optional hip drop.

| Name | Used for |
|---|---|
| `idle` | Townsfolk standing, breathing |
| `still` | Agents standing: nothing moves at all, on purpose |
| `walk`, `run` | Townsfolk gait (`gait()` makes both) |
| `agent_walk` | The agents' walk: arms dead straight, on purpose |
| `talk` | Conversation gestures |
| `phone` | Calling it in |
| `sit` | Seated |
| `cower` | Scared |
| `reach` | Picking something up |
| `cuffed` | Held by the Bureau |
| `cast` | Using a power |
| `dead` | Lying flat |

- **Names matter:** the game asks for animations **by these names**. A missing one is silently skipped, and the character freezes in its last pose. Keep the names, or change every caller: `character.gd`, `player.gd` and `sim.gd`.
- **Adding one:** add an `action(arm, "name", [...])` in `build_anims`, rebuild with `--models`, and play it with `character.play("name")`.

**The grey** (the alien) is a separate, older low-poly model. It's built by `../tools/blender_models.py` together with the props, using the skeleton and animations from `blender/blender_rig.py`:

```bash
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b -P tools/blender_models.py -- <abs path to assets/models>
```

## Things already learned (don't repeat them)

- **Reshaping the shared head made everyone lumpy.** An attempt with shape keys for jaw, cheeks, nose, chin and brow was reverted. The user likes the current head with painted faces. If you try per-person heads, change the shape only gently and over wide areas (from the profile silhouettes), and show screenshots before committing.
- **Hair doesn't match the paintings.** The hair meshes are two smooth caps (`hair_short`, `hair_long`), tinted per face. Curls, braids, buns and caps in the paintings only exist painted on the forehead. Matching hair meshes would be the biggest visual win.
- **Painted hats and glasses** (cap, beanie, sunglasses) are part of the face texture. The game's own 3D hat and glasses go on top.
- **`ImageDraw.floodfill` silently does nothing** on an image made with `Image.fromarray`. Call `.copy()` first.
- **Point picking:** pick eye and mouth points from a `grid.py` zoom, not by eyeballing the whole sheet.
