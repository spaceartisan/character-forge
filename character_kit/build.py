"""Rebuild every person in the game: models, animations and faces. One command.

    python character_kit/build.py              everything: human.glb, face textures, Godot import
    python character_kit/build.py --faces      face textures only (fast, no Blender)
    python character_kit/build.py --models     human.glb only (Blender, about 35 s)
    python character_kit/build.py --shots DIR  also run the game's `people` line-up and save screenshots to DIR

Run from anywhere. Writes into the game this folder sits in:
    assets/models/human.glb        meshes, skeleton and every animation
    assets/textures/face_<id>.png  one per entry in faces/faces_from_refs.py REFS
"""
import os, pathlib, shutil, subprocess, sys

KIT = pathlib.Path(__file__).resolve().parent
GAME = KIT.parent
def _find_blender():
    found = sorted(pathlib.Path(r"C:\Program Files\Blender Foundation").glob("Blender */blender.exe"), reverse=True)
    return str(found[0]) if found else r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"


BLENDER = os.environ.get("BLENDER") or shutil.which("blender") or _find_blender()
GODOT = os.environ.get("GODOT", r"C:\Program Files\Godot\Godot_v4.7-stable_win64.exe\Godot_v4.7-stable_win64_console.exe")


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        sys.exit(f"failed ({r.returncode}): {cmd[0]}")
    return r


def models():
    out = GAME / "assets" / "models"
    r = run([BLENDER, "-b", "-P", KIT / "blender" / "blender_people.py", "--", out], capture_output=True, text=True)
    if "BLENDER_DONE" not in r.stdout:
        print(r.stdout[-3000:], r.stderr[-3000:])
        sys.exit("Blender did not finish human.glb")
    print("wrote", out / "human.glb")


def faces():
    run([sys.executable, "-I", KIT / "faces" / "faces_from_refs.py"])


def godot_import():
    # Headless import so the new glb/png are picked up; Godot prints harmless noise here.
    if not (GAME / "project.godot").is_file():
        print("standalone workspace: Godot game import not needed")
        return
    if not pathlib.Path(GODOT).is_file():
        print("Godot executable not found; skipping game import")
        return
    run([GODOT, "--headless", "--path", GAME, "--import"], capture_output=True)
    print("imported into Godot")


def shots(dest):
    dest = pathlib.Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([GODOT, "--path", str(GAME), "--", "--autotest=people", f"--shotdir={dest}"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(("PASS", "FAIL", "AUTOTEST_DONE", "SCRIPT ERROR")):
            print(line)
    print("screenshots in", dest, "(people_front, people_back, people_face<N>, people_moving)")


if __name__ == "__main__":
    args = sys.argv[1:]
    only_faces, only_models = "--faces" in args, "--models" in args
    if not only_faces:
        models()
    if not only_models:
        faces()
    godot_import()
    if "--shots" in args:
        shots(args[args.index("--shots") + 1])
