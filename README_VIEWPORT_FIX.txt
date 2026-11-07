Character Forge v1.1 - empty viewport fix
======================================

Your screenshot shows the interface, lighted floor, 3D controls, mesh/animation metadata,
but NO CHARACTER. This was a bug in the web viewer, not a broken Blender export.

The glTF contains objects such as person_m and outfit_trench, each with multiple
materials. Three.js loads those objects as named groups with generated child mesh
names. The old preview hid the children because it compared only child mesh names
to group names. The improved viewer shows/hides the whole named group.

INSTALLATION (PATCH ZIP)
------------------------
1. Close the local Character Forge web page.
2. Stop the Character Forge Python window (Ctrl+C).
3. Open the folder CONTAINING your existing CharacterForge directory.
4. Extract this zip THERE, allowing overwrite of the four older static files.
   Example: Documents/CharacterForge/static/viewer.js will be replaced.
5. Run CharacterForge/run.bat again and reopen http://127.0.0.1:8765.
6. Press Ctrl+F5 if the browser still displays the old viewer.

The patch does NOT overwrite custom faces, presets, assets, or exports.
The full v1.1 download is also available if you prefer a fresh installation.

TESTED
------
The included GLB has all twelve expected model parts. Six Node tests pass for
agent outfit, multi-primitive groups, body variants, wardrobe combinations,
and missing geometry errors. The automated visual Chromium test was blocked by
the test environment's browser policy, so confirm visually in Firefox.
