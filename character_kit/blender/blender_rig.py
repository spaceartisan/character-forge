"""Shared by character_kit/blender/blender_people.py and tools/blender_models.py (the grey): the human skeleton, its animations and GLB export."""
import bpy, math, os
from mathutils import Matrix, Vector


def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build_skeleton(s):
    """s: proportions dict."""
    data = bpy.data.armatures.new("rig")
    arm = bpy.data.objects.new("rig", data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = data.edit_bones
    def B(name, head, tail, parent=None, connect=False):
        b = eb.new(name); b.head = head; b.tail = tail; b.roll = 0
        if parent: b.parent = eb[parent]; b.use_connect = connect
    h = s["h"]
    B("hips", (0, 0, h * .53), (0, 0, h * .6))
    B("spine", (0, 0, h * .6), (0, 0, h * .7), "hips")
    B("chest", (0, 0, h * .7), (0, 0, h * .81), "spine")
    B("neck", (0, 0, h * .81), (0, 0, h * .85), "chest")
    B("head", (0, 0, h * .85), (0, 0, h * .97), "neck")
    sw, hw = s["sw"], s["hw"]
    for side, sg in (("L", 1), ("R", -1)):
        B(f"upper_arm.{side}", (sg * sw, 0, h * .8), (sg * (sw + .03), .01, h * .63), "chest")
        B(f"lower_arm.{side}", (sg * (sw + .03), .01, h * .63), (sg * (sw + .045), -.02, h * .49), f"upper_arm.{side}")
        B(f"hand.{side}", (sg * (sw + .045), -.02, h * .49), (sg * (sw + .05), -.03, h * .43), f"lower_arm.{side}")
        B(f"upper_leg.{side}", (sg * hw, 0, h * .52), (sg * hw, -.01, h * .28), "hips")
        B(f"lower_leg.{side}", (sg * hw, -.01, h * .28), (sg * hw, .01, h * .05), f"upper_leg.{side}")
        B(f"foot.{side}", (sg * hw, .01, h * .05), (sg * hw, -.13, h * .02), f"lower_leg.{side}")
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm



BONES = ["hips", "spine", "chest", "neck", "head"] + [f"{p}.{s}" for p in ("upper_arm", "lower_arm", "hand", "upper_leg", "lower_leg", "foot") for s in "LR"]
FPS = 24


def eul(x=0, y=0, z=0):
    """World-axis rotation in degrees. +x pitches a hanging limb backward, -x forward."""
    return (x, y, z)


def key_pose(arm, frame, pose, hips_z=0.0, hips_y=0.0):
    for n in BONES:
        pb = arm.pose.bones[n]
        pb.rotation_mode = "QUATERNION"
        x, y, z = pose.get(n, (0, 0, 0))
        rw = Matrix.Rotation(math.radians(z), 4, "Z") @ Matrix.Rotation(math.radians(y), 4, "Y") @ Matrix.Rotation(math.radians(x), 4, "X")
        rest = arm.data.bones[n].matrix_local
        rl = (rest.inverted() @ rw @ rest).to_quaternion()
        pb.rotation_quaternion = rl
        pb.keyframe_insert("rotation_quaternion", frame=frame, group=n)
    hb = arm.pose.bones["hips"]
    rest = arm.data.bones["hips"].matrix_local.to_3x3()
    hb.location = rest.inverted() @ Vector((0, hips_y, hips_z))
    hb.keyframe_insert("location", frame=frame, group="hips")


def action(arm, name, frames):
    """frames: list of (t_seconds, pose, hips_z[, hips_y])."""
    a = bpy.data.actions.new(name)
    a.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = a
    for f in frames:
        key_pose(arm, int(round(f[0] * FPS)) + 1, f[1], f[2] if len(f) > 2 else 0.0, f[3] if len(f) > 3 else 0.0)
    return a


def mirror(p):
    out = {}
    for k, (x, y, z) in p.items():
        if k.endswith(".L"): out[k[:-2] + ".R"] = (x, -y, -z)
        elif k.endswith(".R"): out[k[:-2] + ".L"] = (x, -y, -z)
        else: out[k] = (x, -y, -z)
    return out


def merge(*ps):
    o = {}
    for p in ps: o.update(p)
    return o


def build_anims(arm):
    # Arms hang with slight out-rotation built into rest; idle keeps them perfectly still except breath.
    breathe0 = {"chest": (-1, 0, 0), "head": (1, 0, 0)}
    breathe1 = {"chest": (1.5, 0, 0), "head": (-.5, 0, 0), "upper_arm.L": (0, 0, 1), "upper_arm.R": (0, 0, -1)}
    action(arm, "idle", [(0, breathe0), (1.6, breathe1, .003), (3.2, breathe0)])
    # An Office agent's idle: absolutely nothing moves. The eye reads this as wrong.
    action(arm, "still", [(0, {"head": (0, 0, 0)}), (4.0, {"head": (0, 0, 0)})])

    def gait(a, b, spread, armsw, lean, bob, t):
        # a: forward thigh, b: rear thigh (deg); contact, pass, contact, pass
        contact = {"upper_leg.L": (-a, 0, 0), "lower_leg.L": (b * .15, 0, 0), "foot.L": (-a * .35 + 8, 0, 0),
                   "upper_leg.R": (b, 0, 0), "lower_leg.R": (b * 1.05, 0, 0), "foot.R": (10, 0, 0),
                   "upper_arm.L": (armsw, 0, 0), "lower_arm.L": (armsw * .5 - spread, 0, 0), "upper_arm.R": (-armsw, 0, 0), "lower_arm.R": (-armsw * .8 - spread, 0, 0),
                   "hips": (lean * .4, 5, 7), "spine": (lean * .4, 0, -3), "chest": (lean * .5, -3, -8), "head": (-lean * .5, 0, 3)}
        passing = {"upper_leg.L": (a * .15, 0, 0), "lower_leg.L": (a * .25, 0, 0), "foot.L": (-4, 0, 0),
                   "upper_leg.R": (-a * .5, 0, 0), "lower_leg.R": (a * 1.5, 0, 0), "foot.R": (6, 0, 0),
                   "upper_arm.L": (armsw * .1, 0, 0), "lower_arm.L": (-spread, 0, 0), "upper_arm.R": (-armsw * .1, 0, 0), "lower_arm.R": (-spread, 0, 0),
                   "hips": (lean * .4, 0, 0), "spine": (lean * .4, 0, 0), "chest": (lean * .5, 0, 0), "head": (-lean * .5, 0, 0)}
        return [(0, contact, -bob), (t * .25, passing, bob), (t * .5, mirror(contact), -bob), (t * .75, mirror(passing), bob), (t, contact, -bob)]
    action(arm, "walk", gait(24, 22, 8, 18, 2, .015, 1.05))
    # The agent walk: same stride, arms held dead straight. Reads as wrong without saying why.
    action(arm, "agent_walk", gait(23, 21, 0, 3, 0, .006, 1.2))
    action(arm, "run", gait(44, 40, 60, 42, 12, .03, .66))

    bent = {"upper_arm.L": (-40, 0, 12), "lower_arm.L": (-80, 0, 0), "upper_arm.R": (-40, 0, -12), "lower_arm.R": (-80, 0, 0)}
    action(arm, "talk", [
        (0, merge(bent, {"head": (0, 0, 8), "lower_arm.L": (-90, 0, 0)})),
        (.8, merge(bent, {"head": (-4, 0, -6), "lower_arm.R": (-105, 0, 0), "upper_arm.R": (-30, 0, -25)})),
        (1.6, merge(bent, {"head": (3, 0, 0), "lower_arm.L": (-70, 0, 0), "upper_arm.L": (-46, 0, 20)})),
        (2.4, merge(bent, {"head": (0, 0, 8), "lower_arm.L": (-90, 0, 0)}))])
    ph = {"upper_arm.R": (-30, 0, -38), "lower_arm.R": (-145, 0, 0), "hand.R": (-10, 0, 0), "head": (0, 10, 0)}
    action(arm, "phone", [(0, ph), (1.2, merge(ph, {"head": (4, 12, 6)})), (2.4, ph)])
    sit = {"upper_leg.L": (-85, 0, 0), "upper_leg.R": (-85, 0, 0), "lower_leg.L": (85, 0, 0), "lower_leg.R": (85, 0, 0), "upper_arm.L": (-25, 0, 0), "upper_arm.R": (-25, 0, 0), "lower_arm.L": (-60, 0, 0), "lower_arm.R": (-60, 0, 0)}
    action(arm, "sit", [(0, sit, -.42), (2.5, merge(sit, {"head": (6, 0, 6)}), -.42), (5.0, sit, -.42)])
    cower = {"hips": (25, 0, 0), "upper_leg.L": (-95, 0, 0), "upper_leg.R": (-95, 0, 0), "lower_leg.L": (100, 0, 0), "lower_leg.R": (100, 0, 0), "chest": (20, 0, 0), "head": (15, 0, 0), "upper_arm.L": (-70, 0, 25), "upper_arm.R": (-70, 0, -25), "lower_arm.L": (-120, 0, 0), "lower_arm.R": (-120, 0, 0)}
    action(arm, "cower", [(0, cower, -.32), (.2, merge(cower, {"head": (20, 3, 0)}), -.33), (.4, cower, -.32)])
    action(arm, "reach", [(0, {}), (.2, {"upper_arm.R": (-60, 0, 0), "lower_arm.R": (-30, 0, 0), "chest": (6, 0, 0)}), (.5, {"upper_arm.R": (-65, 0, 0), "lower_arm.R": (-25, 0, 0), "chest": (8, 0, 0)}), (.8, {})])
    cuf = {"upper_arm.L": (24, 0, -6), "upper_arm.R": (24, 0, 6), "lower_arm.L": (30, 0, -20), "lower_arm.R": (30, 0, 20), "head": (10, 0, 0)}
    action(arm, "cuffed", [(0, cuf), (2.0, merge(cuf, {"head": (14, 0, 4)})), (4.0, cuf)])
    action(arm, "cast", [(0, {}), (.18, {"upper_arm.R": (-82, 0, -8), "lower_arm.R": (-8, 0, 0), "head": (-4, 0, 0)}), (.7, {"upper_arm.R": (-84, 0, -6), "lower_arm.R": (-6, 0, 0)}), (1.0, {})])
    action(arm, "dead", [(0, {"hips": (-90, 0, 0), "head": (0, 0, 40), "upper_arm.L": (-6, 0, 40), "upper_arm.R": (-20, 0, -32), "upper_leg.L": (0, 0, 6), "lower_leg.R": (30, 0, 0)}, -.93, 0), (1.0, {"hips": (-90, 0, 0), "head": (0, 0, 40), "upper_arm.L": (-6, 0, 40), "upper_arm.R": (-20, 0, -32), "upper_leg.L": (0, 0, 6), "lower_leg.R": (30, 0, 0)}, -.93, 0)])
    arm.animation_data.action = None



def export(path, colors=False):
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_animations=True, export_animation_mode="ACTIONS", export_skins=True, export_materials="EXPORT",
                              export_force_sampling=True, export_frame_step=1, export_optimize_animation_size=True, export_yup=True,
                              export_vertex_color="ACTIVE" if colors else "MATERIAL")
    print("WROTE", path, os.path.getsize(path))
