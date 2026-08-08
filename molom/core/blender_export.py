"""Export the scene as a **Blender build script** — geometry, materials,
camera, lights and world, ready to render.

Why a `.py` and not a `.blend`: writing a .blend needs Blender itself, and
shelling out to find an installation is exactly the sort of fragile thing this
project avoids. A script has better properties anyway — it is diffable, it is
editable before you run it, it can be re-run after the scene changes, and it
teaches you how the scene was built. Run it from Blender's Scripting workspace
(Open, then Run) or headless with `blender --python molecule_blender.py`.

What it builds, and why each piece is here rather than left to the user:

* **materials that already carry the right colour**, one per element plus one
  per DISTINCT custom colour — so an atom the outliner painted violet arrives
  violet, and two atoms painted the same violet share a material rather than
  littering the file. Colours are converted sRGB -> linear, because Blender's
  shader sockets are linear and dropping the viewport's numbers in raw comes
  out visibly washed out.
* **a camera in exactly the pose the viewport had**. MoloM's orbit camera and
  Blender's camera share a convention (look down local -Z, +Y up), so the
  world matrix is just the view rotation transposed with the eye in the last
  column — no Euler juggling, no gimbal surprises. Orthographic viewports
  export an orthographic camera with the matching scale.
* **an HDRI from Blender's own material-preview set** (`forest.exr`,
  `studio.exr`, ...), resolved at RUN time from `bpy.utils.system_resource`,
  so the script carries no absolute path and works on any machine with any
  Blender. That is what Christian actually uses, and an HDRI is worth more to
  a molecule render than any lamp rig: smooth spheres are almost entirely
  reflection.
* **an optional lamp rig** anyway, positioned in the CAMERA's frame (key from
  the upper left, fill opposite, rim behind), because a pure-HDRI render has
  no directional key and reads flat on a pale molecule. Energies scale with
  the square of the distance so a 5 A molecule and a 100 A framework are lit
  the same.

Geometry is one mesh datablock for atoms and one for bonds, instanced by
linked duplicates with per-OBJECT material slots. That keeps the .blend small
and every atom individually selectable — the thing you lose by merging.

UI-free: numpy + stdlib only, no Qt, no GL, no bpy. The whole script is a
string, so the tests read it and even `compile()` it.
"""

import datetime
import json
import os
from typing import List, Optional, Tuple

import numpy as np

from . import elements, polyhedra
from . import style as style_mod
from .camera import quat_to_mat3

#: Blender ships these world HDRIs with every install (the ones the Material
#: Preview shading mode offers). They live under
#: `<datafiles>/studiolights/world/` and are resolved inside the script, so
#: nothing here depends on where Blender is installed — or on the set being
#: exactly this list, since the script falls back to whatever it finds.
STUDIO_HDRIS = ("forest", "city", "courtyard", "interior", "night",
                "studio", "sunrise", "sunset")

#: Lamp rigs. "none" leans entirely on the world.
LIGHT_RIGS = ("none", "key", "three_point", "sun")

ENGINES = ("CYCLES", "BLENDER_EEVEE_NEXT")
VIEW_TRANSFORMS = ("Standard", "Filmic", "AgX")


class ExportOptions(object):
    """Everything the pre-export dialog asks for. Plain attributes so the
    dialog can write them straight in, and so a test can build one in a line.
    """

    def __init__(self, **kw):
        # world
        self.hdri = "forest"            # a STUDIO_HDRIS name, a path, or ""
        self.hdri_strength = 1.0
        self.hdri_rotation = 0.0        # degrees about Z
        self.hdri_visible = False       # show it behind the molecule
        self.background = (0.05, 0.05, 0.05)
        self.transparent = True         # film transparent when no backdrop
        # camera
        self.match_viewport = True
        self.resolution = (1920, 1080)
        # lights
        self.lights = "three_point"
        self.light_strength = 1.0
        # materials
        self.roughness = 0.35
        self.metallic_metals = True
        # geometry
        self.style_key = None           # None = whatever the viewport shows
        self.atom_scale = 1.0
        self.sphere_subdivisions = 3
        self.bond_sides = 24
        self.shade_smooth = True
        self.unit_cell = True
        self.cell_radius = 0.04
        self.polyhedra = True           # follow the ❖ toggle into the render
        self.polyhedra_alpha = 0.55     # matches the viewport default
        # output — a .blend needs Blender to build it, so it carries the path
        self.output = "blend"           # "blend" or "script"
        self.blender_exe = ""
        # render
        self.engine = "CYCLES"
        self.samples = 128
        self.view_transform = "Standard"
        self.clear_scene = True
        self.collection = "MoloM"
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError("unknown export option: {!r}".format(k))
            setattr(self, k, v)

    def to_dict(self):
        return {k: v for k, v in vars(self).items()}


# ------------------------------------------------------------------ colour
def srgb_to_linear(c):
    # type: (float) -> float
    """Blender's shader sockets are LINEAR; MoloM's palette (like every
    colour picker) is sRGB. Dropping 0.5 grey in raw gives 0.5 linear, which
    renders a good deal lighter than the viewport shows."""
    c = float(c)
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _hex(rgb):
    return "".join("{:02x}".format(int(round(max(0.0, min(1.0, c)) * 255)))
                   for c in rgb)


def material_name(symbol, rgb, custom):
    # type: (str, tuple, bool) -> str
    """One material per element, plus one per DISTINCT custom colour.

    Keying a custom colour by its hex means two atoms painted the same red
    share a material — which is what you want when you then tweak it in
    Blender — while an atom nobody touched stays on the plain element
    material.
    """
    if custom:
        return "MoloM {} ({})".format(symbol, _hex(rgb))
    return "MoloM {}".format(symbol)


# ------------------------------------------------------------------ geometry
def object_geometry(obj, style, atom_scale=1.0):
    # type: (object, object, float) -> Tuple[list, list, dict]
    """(atoms, bonds, materials) for one MolObject, following exactly what the
    viewport draws — the modifier stack's output, per-atom colours, per-atom
    sizes, hidden atoms and the multi-bond layout.

    Kept next to the viewport's `_rebuild` in behaviour on purpose: an export
    that quietly disagrees with the picture on screen is worse than no export.
    """
    atoms, bonds, materials = [], [], {}
    s = obj.structure
    if s.n_atoms == 0:
        return atoms, bonds, materials
    symbols, coords, bond_list = obj.evaluated()
    coords = np.asarray(coords, dtype=float)
    base_n = max(s.n_atoms, 1)
    zs = [elements.atomic_number(x) for x in symbols]
    colors, names, radii = [], [], []
    for i, z in enumerate(zs):
        base_i = i % base_n          # modifier copies follow their base atom
        custom = obj.atom_colors.get(base_i)
        rgb = tuple(custom) if custom is not None else elements.color_f(z)
        sym = elements.symbol(z)
        name = material_name(sym, rgb, custom is not None)
        materials[name] = (rgb, sym, 1.0)
        colors.append(rgb)
        names.append(name)
        r = style.atom_radius(elements.radius_vdw(z))
        if style.fixed_atom_radius is None:
            r *= float(atom_scale)
        if style.wireframe:
            r = 0.0
        radii.append(r * obj.atom_scale_for(base_i))
    hidden = obj.atom_hidden
    for i in range(len(symbols)):
        if i % base_n in hidden:
            continue
        if radii[i] > 0.0:
            atoms.append((names[i], _xyz(coords[i]), round(float(radii[i]), 6)))
    if style.show_bonds or style.wireframe:
        # Wireframe has no Blender equivalent worth having (a render is not a
        # viewport), so it exports as thin sticks — the closest honest thing.
        bond_radius = 0.06 if style.wireframe else style.bond_radius
        for i, j, order in bond_list:
            if i % base_n in hidden or j % base_n in hidden:
                continue
            p1, p2 = coords[i], coords[j]
            for a, b, r in style_mod.bond_cylinders(
                    p1, p2, order, bond_radius=bond_radius,
                    show_multiple=style.show_multiple_bonds
                    and not style.wireframe):
                mid = (np.asarray(a) + np.asarray(b)) / 2.0
                # Split at the midpoint and colour each half by its atom, the
                # same as the viewport — a bond that changes colour halfway is
                # most of what makes a ball-and-stick picture readable.
                bonds.append((names[i], _xyz(a), _xyz(mid),
                              round(float(r), 6)))
                bonds.append((names[j], _xyz(mid), _xyz(b),
                              round(float(r), 6)))
        # The ❖ page's refused-bond override (round 43) follows into the
        # render, or the export would silently disagree with the viewport it
        # was set up in. Their own materials, from the muted colour, so they
        # stay adjustable as a group once the scene is in Blender.
        if (s.metadata or {}).get("show_refused_bonds"):
            r_ref = bond_radius * style_mod.REFUSED_BOND_SCALE
            for i, j in (s.metadata.get("refused_bonds") or ()):
                if not (0 <= i < len(symbols) and 0 <= j < len(symbols)):
                    continue
                if i % base_n in hidden or j % base_n in hidden:
                    continue
                p1, p2 = coords[i], coords[j]
                mid = (np.asarray(p1) + np.asarray(p2)) / 2.0
                for atom, a, b in ((i, p1, mid), (j, mid, p2)):
                    rgb = style_mod.muted(colors[atom])
                    name = "MoloM {} refused".format(
                        elements.symbol(zs[atom]))
                    materials[name] = (rgb, elements.symbol(zs[atom]),
                                      1.0)
                    bonds.append((name, _xyz(a), _xyz(b),
                                  round(float(r_ref), 6)))
    return atoms, bonds, materials


def _xyz(v):
    return [round(float(x), 6) for x in np.asarray(v, dtype=float)[:3]]


def object_polyhedra(obj, cell, alpha=0.55):
    # type: (object, object, float) -> Tuple[list, dict]
    """Coordination solids as real MESHES, one per centre.

    Without these a MOF figure loses exactly the thing that makes it
    readable — the whole reason the framework community draws polyhedra at
    all. They come from `polyhedra.for_object`, the same call the viewport
    makes, so the render cannot show a different set from the screen.

    One mesh per polyhedron rather than one merged blob per object: they are
    then individually selectable, and a translucent surface renders far better
    when its faces belong to a closed convex solid than when a hundred of them
    share a datablock.
    """
    out, materials = [], {}
    built = polyhedra.for_object(obj, cell)
    for poly in built:
        sym = poly["symbol"]
        rgb = tuple(poly["color"])[:3]
        name = "MoloM {} polyhedron".format(sym)
        materials[name] = (rgb, sym, float(alpha))
        out.append({
            "name": "poly.{}.{}".format(sym, int(poly["centre"])),
            "material": name,
            "vertices": [_xyz(v) for v in poly["vertices"]],
            "faces": [[int(i) for i in tri] for tri in poly["faces"]],
        })
    return out, materials


def cell_edges(cell, radius=0.04):
    # type: (object, float) -> Tuple[list, dict]
    """The unit-cell box as cylinders, a/b/c in the axis colours.

    Cylinders rather than an edge mesh with a Wireframe modifier: an edge mesh
    does not render at all, and this way the box goes through the same code
    path as the bonds and picks up the same smooth shading.
    """
    if cell is None:
        return [], {}
    corners = np.asarray(cell.corners(), dtype=float)
    frac = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
                     [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]], dtype=float)
    axis_rgb = {0: (0.90, 0.25, 0.25), 1: (0.35, 0.80, 0.30),
                2: (0.30, 0.50, 0.95)}
    out, materials = [], {}
    for i, j in cell.edges():
        d = np.abs(frac[j] - frac[i])
        axis = int(np.argmax(d))
        name = "MoloM cell {}".format("abc"[axis])
        materials[name] = (axis_rgb[axis], "abc"[axis], 1.0)
        out.append((name, _xyz(corners[i]), _xyz(corners[j]),
                    round(float(radius), 6)))
    return out, materials


# ------------------------------------------------------------------ camera
def camera_setup(camera, width, height):
    # type: (object, int, int) -> dict
    """The viewport camera as a Blender camera.

    Both look down their local **-Z** with **+Y** up, so the world matrix is
    the view rotation TRANSPOSED (camera axes expressed in world) with the eye
    in the translation column. Nothing else is needed — in particular no Euler
    conversion, which is where this normally goes wrong.
    """
    r = quat_to_mat3(camera.rotation)
    eye = np.asarray(camera.center, dtype=float) \
        + r.T @ np.array([0.0, 0.0, float(camera.distance)])
    m = np.eye(4)
    m[:3, :3] = r.T
    m[:3, 3] = eye
    fov_y = float(getattr(camera, "FOV_Y", 40.0))
    half_h = np.tan(np.radians(fov_y) / 2.0) * float(camera.distance)
    out = {
        "matrix": [[round(float(v), 8) for v in row] for row in m],
        "type": "ORTHO" if camera.orthographic else "PERSP",
        "angle_y": round(float(np.radians(fov_y)), 8),
        "ortho_scale": round(float(2.0 * half_h), 6),
        "clip_start": round(max(float(camera.distance) * 0.005, 0.01), 6),
        "clip_end": round(float(camera.distance) * 20.0 + 100.0, 3),
        "resolution": [int(width), int(height)],
        "eye": _xyz(eye),
        "target": _xyz(camera.center),
    }
    return out


def light_rig(kind, cam, radius, strength=1.0):
    # type: (str, dict, float, float) -> list
    """Lamps placed in the CAMERA's frame, so the rig follows the shot.

    Energies go as distance SQUARED. A lamp is an inverse-square source, so a
    fixed wattage that flatters a 5 A molecule leaves a 100 A framework black
    — and the whole point of a preset is that it works without being re-tuned
    for every structure.
    """
    kind = (kind or "none").lower()
    if kind == "none" or kind not in LIGHT_RIGS:
        return []
    m = np.asarray(cam["matrix"], dtype=float)
    right, up, back = m[:3, 0], m[:3, 1], m[:3, 2]
    target = np.asarray(cam["target"], dtype=float)
    r = max(float(radius), 0.5)
    out = []

    def lamp(name, direction, dist, kind_, power, size):
        loc = target + np.asarray(direction, dtype=float) * dist
        out.append({"name": name, "type": kind_, "location": _xyz(loc),
                    "target": _xyz(target),
                    "energy": round(float(power * strength), 3),
                    "size": round(float(size), 4)})

    if kind == "sun":
        d = _unit(back * 1.0 - right * 0.6 + up * 0.8)
        # A sun's "energy" is irradiance, so it must NOT scale with distance.
        lamp("MoloM sun", d, r * 6.0, "SUN", 3.0, 0.03)
        return out
    key_d = _unit(back + (-right) * 0.75 + up * 0.55)
    dist = r * 3.2
    lamp("MoloM key", key_d, dist, "AREA", 14.0 * dist * dist, r * 1.6)
    if kind == "three_point":
        fill_d = _unit(back + right * 0.9 - up * 0.15)
        fdist = r * 3.6
        lamp("MoloM fill", fill_d, fdist, "AREA", 4.0 * fdist * fdist,
             r * 2.6)
        rim_d = _unit(-back * 0.9 + up * 0.5 + right * 0.25)
        rdist = r * 3.0
        lamp("MoloM rim", rim_d, rdist, "AREA", 7.0 * rdist * rdist, r * 1.2)
    return out


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


# ------------------------------------------------------------------ collect
def collect(scene, style, options, camera=None, width=1920, height=1080,
            cell_of=None):
    # type: (object, object, ExportOptions, object, int, int, object) -> dict
    """Everything the script needs, as plain Python data.

    Separated from `build_script` so the tests can check WHAT is exported
    without reading generated source, and so a future .blend writer or a
    different renderer could reuse it unchanged.
    """
    atoms, bonds, solids, materials = [], [], [], {}
    pts = []
    for obj in scene.visible_objects():
        st = style
        if obj.style_key and obj.style_key in style_mod.STYLE_BY_KEY:
            st = style_mod.STYLE_BY_KEY[obj.style_key]
        a, b, m = object_geometry(obj, st, options.atom_scale)
        atoms += a
        bonds += b
        materials.update(m)
        pts += [x[1] for x in a]
        if options.unit_cell and cell_of is not None:
            ce, cm = cell_edges(cell_of(obj), options.cell_radius)
            bonds += ce
            materials.update(cm)
            pts += [e[1] for e in ce] + [e[2] for e in ce]
        if options.polyhedra:
            cell = cell_of(obj) if cell_of is not None else None
            pe, pm = object_polyhedra(obj, cell, options.polyhedra_alpha)
            solids += pe
            materials.update(pm)
            for solid in pe:
                pts += solid["vertices"]
    if pts:
        arr = np.asarray(pts, dtype=float)
        centre = (arr.max(axis=0) + arr.min(axis=0)) / 2.0
        radius = float(np.linalg.norm(arr.max(axis=0) - centre)) or 1.0
    else:
        centre, radius = np.zeros(3), 1.0
    cam = camera_setup(camera, width, height) if camera is not None else None
    mats = []
    for name in sorted(materials):
        rgb, sym, alpha = materials[name]
        # A translucent solid must not also be a mirror: a metallic polyhedron
        # renders as a chrome shell with nothing readable inside it.
        solid = alpha >= 0.999
        metallic = (options.metallic_metals and polyhedra.is_metal(sym)
                    and solid)
        mats.append({
            "name": name,
            "color": [round(srgb_to_linear(c), 6) for c in rgb],
            "roughness": round(float(options.roughness)
                               * (0.7 if metallic else 1.0), 4),
            "metallic": 1.0 if metallic else 0.0,
            "alpha": round(float(alpha), 4),
            "display": [round(float(c), 4) for c in rgb] + [round(float(alpha),
                                                                 4)],
        })
    return {
        "atoms": atoms,
        "bonds": bonds,
        "polyhedra": solids,
        "materials": mats,
        "camera": cam,
        # HALF POWER when a world HDRI is doing half the work. An environment
        # lights a molecule from every direction at once; adding a full lamp
        # rig on top of it blows the white hydrogens out, which is exactly
        # what the first render did.
        "lights": light_rig(options.lights, cam, radius,
                            options.light_strength
                            * (0.5 if options.hdri else 1.0)) if cam else [],
        "centre": _xyz(centre),
        "radius": round(radius, 4),
    }


# ------------------------------------------------------------------ script
_HEADER = '''"""MoloM -> Blender scene: {title}

Generated by MoloM {version} on {date}.
{summary}

HOW TO USE
  Blender GUI : Scripting workspace -> Open -> this file -> Run Script (Alt+P)
  Headless    : blender --python "{basename}"
                blender -b --python "{basename}" -o //render_ -f 1

Everything is plain data at the top and plain bpy calls below it, so it is
meant to be edited. One Angstrom = one Blender unit.
"""

import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

# ----------------------------------------------------------------- data
OPTIONS = {options}
MATERIALS = {materials}
CAMERA = {camera}
LIGHTS = {lights}
SCENE_CENTRE = {centre}
SCENE_RADIUS = {radius}

ATOMS = [
{atoms}
]

BONDS = [
{bonds}
]

# Coordination polyhedra: one closed convex solid per metal centre, as
# (name, material, vertices, triangles).
POLYHEDRA = [
{polyhedra}
]
'''

_BODY = '''

# ----------------------------------------------------------------- helpers
def clear_scene():
    """Remove the default cube/camera/light and anything else lying about."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def get_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def sub_collection(parent, name):
    full = "{0}/{1}".format(parent.name, name)
    coll = bpy.data.collections.get(full)
    if coll is None:
        coll = bpy.data.collections.new(full)
        parent.children.link(coll)
    return coll


def make_material(spec):
    mat = bpy.data.materials.get(spec["name"])
    if mat is None:
        mat = bpy.data.materials.new(spec["name"])
    # Only if it is not already on: 5.x has nodes always, and assigning True
    # there prints a deprecation warning per material.
    if not getattr(mat, "use_nodes", True):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                bsdf = node
                break
    alpha = spec.get("alpha", 1.0)
    if bsdf is not None:
        r, g, b = spec["color"]
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value = spec["roughness"]
        bsdf.inputs["Metallic"].default_value = spec["metallic"]
        if alpha < 1.0:
            bsdf.inputs["Alpha"].default_value = alpha
            # EEVEE needs telling; Cycles honours Alpha on its own. The
            # property moved to a per-material enum in 4.2 and the older
            # spelling is a plain string, so both are tried.
            for attr, value in (("surface_render_method", "BLENDED"),
                                ("blend_method", "BLEND")):
                try:
                    setattr(mat, attr, value)
                except (AttributeError, TypeError):
                    pass
            mat.use_backface_culling = False
    mat.diffuse_color = spec["display"]      # solid-shading colour too
    return mat


def unit_sphere(subdivisions):
    """One icosphere of radius 1, shared by every atom (linked duplicates)."""
    mesh = bpy.data.meshes.new("MoloM atom")
    bm = bmesh.new()
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0)
    except TypeError:                        # Blender <= 2.9x spelling
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, diameter=1.0)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def unit_cylinder(sides):
    """Radius 1, length 1, along +Z and centred on the origin."""
    mesh = bpy.data.meshes.new("MoloM bond")
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                              segments=sides, radius1=1.0, radius2=1.0,
                              depth=1.0)
    except TypeError:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                              segments=sides, diameter1=1.0, diameter2=1.0,
                              depth=1.0)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def shade_smooth(mesh):
    for poly in mesh.polygons:
        poly.use_smooth = True


def new_object(name, mesh, material, matrix, collection):
    ob = bpy.data.objects.new(name, mesh)
    ob.matrix_world = matrix
    collection.objects.link(ob)
    if material is not None:
        # The MESH is shared, so the material has to hang off the OBJECT or
        # every atom would take the colour of the last one assigned.
        if not mesh.materials:
            mesh.materials.append(None)
        ob.material_slots[0].link = "OBJECT"
        ob.material_slots[0].material = material
    return ob


def build_polyhedra(coll, mats):
    """Coordination solids as their own meshes.

    FLAT shaded on purpose — a coordination polyhedron has real creases, and
    smoothing them rounds an octahedron into a blob. Each solid gets its own
    mesh (they are all different shapes), so nothing is shared here.
    """
    for name, mat_name, verts, faces in POLYHEDRA:
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([Vector(v) for v in verts], [], faces)
        mesh.update()
        for poly in mesh.polygons:
            poly.use_smooth = False
        ob = bpy.data.objects.new(name, mesh)
        coll.objects.link(ob)
        mat = mats.get(mat_name)
        if mat is not None:
            mesh.materials.append(mat)
    return len(POLYHEDRA)


def studio_hdri(name):
    """Blender's own material-preview HDRIs, found at RUN time so the script
    carries no absolute path from the machine that wrote it."""
    if not name:
        return None
    if os.path.sep in name or name.lower().endswith((".exr", ".hdr")):
        return name if os.path.exists(name) else None
    base = os.path.join(bpy.utils.system_resource("DATAFILES"),
                        "studiolights", "world")
    path = os.path.join(base, name + ".exr")
    if os.path.exists(path):
        return path
    if os.path.isdir(base):                  # any of them beats none
        for f in sorted(os.listdir(base)):
            if f.lower().endswith((".exr", ".hdr")):
                return os.path.join(base, f)
    return None


def build_world():
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("MoloM world")
        scene.world = world
    if not getattr(world, "use_nodes", True):
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (400, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.location = (150, 0)
    bg.inputs["Strength"].default_value = OPTIONS["hdri_strength"]
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    path = studio_hdri(OPTIONS["hdri"])
    if path:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.location = (-150, 0)
        env.image = bpy.data.images.load(path, check_existing=True)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.location = (-380, 0)
        mapping.inputs["Rotation"].default_value[2] = math.radians(
            OPTIONS["hdri_rotation"])
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = (-580, 0)
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    else:
        r, g, b = OPTIONS["background"]
        bg.inputs["Color"].default_value = (r, g, b, 1.0)
    return world


def build_camera(coll):
    if not CAMERA:
        return None
    data = bpy.data.cameras.new("MoloM camera")
    cam = bpy.data.objects.new("MoloM camera", data)
    coll.objects.link(cam)
    cam.matrix_world = Matrix(CAMERA["matrix"])
    data.clip_start = CAMERA["clip_start"]
    data.clip_end = CAMERA["clip_end"]
    data.sensor_fit = "VERTICAL"             # MoloM's field of view is the
    if CAMERA["type"] == "ORTHO":            # VERTICAL one
        data.type = "ORTHO"
        data.ortho_scale = CAMERA["ortho_scale"]
    else:
        data.angle_y = CAMERA["angle_y"]
    bpy.context.scene.camera = cam
    return cam


def build_lights(coll):
    for spec in LIGHTS:
        data = bpy.data.lights.new(spec["name"], type=spec["type"])
        data.energy = spec["energy"]
        if spec["type"] == "AREA":
            data.size = spec["size"]
            data.shape = "DISK"
        elif spec["type"] == "SUN":
            data.angle = spec["size"]
        ob = bpy.data.objects.new(spec["name"], data)
        coll.objects.link(ob)
        loc = Vector(spec["location"])
        ob.location = loc
        direction = Vector(spec["target"]) - loc
        ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return len(LIGHTS)


def set_engine(preferred):
    """Engine identifiers move between releases (EEVEE became
    BLENDER_EEVEE_NEXT in 4.2 and BLENDER_EEVEE again in 5.0), and CYCLES is
    an add-on that may be disabled. Assigning an unknown identifier raises
    TypeError, which is a more reliable test than reading the enum — that
    property is dynamic and does not list external engines."""
    scene = bpy.context.scene
    for name in (preferred, "CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = name
            return name
        except TypeError:
            continue
    return scene.render.engine


def build_render():
    scene = bpy.context.scene
    engine = set_engine(OPTIONS["engine"])
    w, h = CAMERA["resolution"] if CAMERA else (1920, 1080)
    scene.render.resolution_x = int(w)
    scene.render.resolution_y = int(h)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = bool(OPTIONS["transparent"])
    if engine == "CYCLES" and hasattr(scene, "cycles"):
        scene.cycles.samples = OPTIONS["samples"]
        scene.cycles.use_denoising = True
    elif hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = OPTIONS["samples"]
    try:
        scene.view_settings.view_transform = OPTIONS["view_transform"]
    except TypeError:                        # not in this build's list
        pass
    return engine


# ----------------------------------------------------------------- build
def main():
    if OPTIONS["clear_scene"]:
        clear_scene()
    root = get_collection(OPTIONS["collection"])
    mats = {}
    for spec in MATERIALS:
        mats[spec["name"]] = make_material(spec)

    sphere = unit_sphere(OPTIONS["sphere_subdivisions"])
    cylinder = unit_cylinder(OPTIONS["bond_sides"])
    if OPTIONS["shade_smooth"]:
        shade_smooth(sphere)
        shade_smooth(cylinder)

    atom_coll = sub_collection(root, "atoms")
    for n, (mat_name, position, radius) in enumerate(ATOMS):
        label = mat_name.replace("MoloM ", "")
        m = Matrix.Translation(Vector(position)) @ Matrix.Diagonal(
            (radius, radius, radius, 1.0))
        new_object("{0}.{1}".format(label, n), sphere,
                   mats.get(mat_name), m, atom_coll)

    bond_coll = sub_collection(root, "bonds")
    for n, (mat_name, start, end, radius) in enumerate(BONDS):
        a, b = Vector(start), Vector(end)
        d = b - a
        length = d.length
        if length < 1e-9:
            continue
        rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        m = (Matrix.Translation((a + b) / 2.0) @ rot
             @ Matrix.Diagonal((radius, radius, length, 1.0)))
        new_object("bond.{0}".format(n), cylinder, mats.get(mat_name), m,
                   bond_coll)

    if POLYHEDRA:
        build_polyhedra(sub_collection(root, "polyhedra"), mats)

    rig = sub_collection(root, "rig")
    build_camera(rig)
    n_lights = build_lights(rig)
    build_world()
    engine = build_render()
    print("MoloM: {0} atoms, {1} bond segments, {2} polyhedra, {3} materials, "
          "{4} lights, engine {5}".format(len(ATOMS), len(BONDS),
                                          len(POLYHEDRA), len(MATERIALS),
                                          n_lights, engine))


def save_blend(path):
    """Write the built scene to a .blend.

    This is what makes the export a FILE you open and press F12 in, rather
    than a script you have to run every time — and because the scene is
    already built when it is saved, the .blend needs no auto-run, no "Allow
    Execution" prompt and no trust dialog.
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    # The script itself rides along as a text datablock, so the scene can be
    # rebuilt after a tweak without going back to MoloM.
    try:
        source = os.path.abspath(__file__)
        if os.path.exists(source):
            name = os.path.basename(source)
            text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
            with open(source, "r", encoding="utf-8", errors="replace") as fh:
                text.from_string(fh.read())
    except (OSError, NameError):
        pass
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print("MoloM: saved " + path)


if __name__ == "__main__":
    main()
    # `blender -b --python this.py -- --save out.blend`
    _argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--save" in _argv:
        save_blend(_argv[_argv.index("--save") + 1])
'''


#: Typographic characters this project's prose is full of, and their ASCII
#: stand-ins. The generated script is deliberately **ASCII only**: it leaves
#: here as text and may be written, copied, opened in Blender's text editor or
#: piped through any number of tools, and exactly one of those steps assuming
#: cp1252 turns an em dash into a byte Python refuses to parse — which
#: presents as `SyntaxError: 'utf-8' codec can't decode byte 0x97`, in a file
#: nobody has edited. Molecule names go through the same fold, since they can
#: contain anything at all.
_ASCII_FOLD = {
    0x2014: "--", 0x2013: "-", 0x2018: "'", 0x2019: "'", 0x201c: '"',
    0x201d: '"', 0x2026: "...", 0x00c5: "A", 0x00b0: " deg", 0x00d7: "x",
    0x00a0: " ",
}


def ascii_only(text):
    # type: (str) -> str
    return str(text).translate(_ASCII_FOLD).encode(
        "ascii", "replace").decode("ascii")


def build_script(data, options, title="scene", version="", basename="",
                 summary=""):
    # type: (dict, ExportOptions, str, str, str, str) -> str
    """Render `collect()`'s data into the finished Blender script."""
    opts = {
        "hdri": options.hdri or "",
        "hdri_strength": float(options.hdri_strength),
        "hdri_rotation": float(options.hdri_rotation),
        "background": [float(c) for c in options.background],
        "transparent": bool(options.transparent and not options.hdri_visible),
        "sphere_subdivisions": int(options.sphere_subdivisions),
        "bond_sides": int(options.bond_sides),
        "shade_smooth": bool(options.shade_smooth),
        "polyhedra_alpha": float(options.polyhedra_alpha),
        "engine": str(options.engine),
        "samples": int(options.samples),
        "view_transform": str(options.view_transform),
        "clear_scene": bool(options.clear_scene),
        "collection": str(options.collection),
    }
    return ascii_only(_HEADER.format(
        title=title,
        version=version,
        date=datetime.date.today().isoformat(),
        summary=summary,
        basename=basename or "molecule_blender.py",
        options=_pretty(opts),
        materials=_pretty(data["materials"]),
        camera=_pretty(data["camera"] or {}),
        lights=_pretty(data["lights"]),
        centre=_pretty(data["centre"]),
        radius=repr(float(data["radius"])),
        atoms="\n".join("    {},".format(_row(a)) for a in data["atoms"]),
        bonds="\n".join("    {},".format(_row(b)) for b in data["bonds"]),
        polyhedra="\n".join(
            "    {},".format(_row((p["name"], p["material"], p["vertices"],
                                   p["faces"])))
            for p in data.get("polyhedra") or ()),
    ) + _BODY)


def _row(item):
    return "(" + ", ".join(_pretty(x) for x in item) + ")"


def _pretty(value):
    """JSON is a valid Python literal for everything we emit EXCEPT the three
    words true/false/null, so booleans are written out by hand."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, dict):
        return "{" + ", ".join("{}: {}".format(json.dumps(str(k)),
                                               _pretty(v))
                               for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_pretty(v) for v in value) + "]"
    if isinstance(value, float):
        return repr(round(value, 8))
    if isinstance(value, (int, np.integer)):
        return repr(int(value))
    return json.dumps(str(value))


def summarise(data):
    # type: (dict) -> str
    """One line for the file header — and for the status bar."""
    out = "{} atoms, {} bond segments".format(len(data["atoms"]),
                                              len(data["bonds"]))
    if data.get("polyhedra"):
        out += ", {} polyhedra".format(len(data["polyhedra"]))
    return out + ", {} materials, {} lights".format(len(data["materials"]),
                                                    len(data["lights"]))


def default_path(directory, base, suffix=".py"):
    # type: (str, str, str) -> str
    return os.path.join(directory or "",
                        "{}_blender{}".format(base or "molom", suffix))


# ------------------------------------------------------- running Blender
#: Where an install usually is, per platform. Only ever a starting point for
#: `find_blender` — the answer is a SETTING, because this is exactly the sort
#: of path that differs between two machines belonging to the same person.
_SEARCH_GLOBS = {
    "win32": (r"C:\Program Files\Blender Foundation\Blender */blender.exe",
              r"C:\Program Files\Blender Foundation\blender.exe",
              r"C:\Program Files (x86)\Steam\steamapps\common\Blender"
              r"\blender.exe"),
    "darwin": ("/Applications/Blender.app/Contents/MacOS/Blender",
               "/Applications/Blender*/Blender.app/Contents/MacOS/Blender"),
}
_SEARCH_GLOBS_POSIX = ("/usr/bin/blender", "/usr/local/bin/blender",
                       "/snap/bin/blender", "/opt/blender*/blender")


def _version_key(path):
    """Sort candidates newest-first by whatever digits are in the path."""
    import re
    nums = [int(n) for n in re.findall(r"\d+", os.path.basename(
        os.path.dirname(path)) or "")]
    return nums or [0]


def find_blender(hint=""):
    # type: (str) -> str
    """A usable Blender executable, or "".

    `hint` (the stored setting) wins if it exists. Otherwise: whatever is on
    PATH, then the usual install locations, newest version first.

    **A launcher is not the executable to script.** Windows installs ship
    `blender-launcher.exe` next to `blender.exe`, and the launcher is a
    GUI shim — for `-b --python` you want the real binary, which is right
    beside it. Christian's own path points at the launcher, so this is the
    normal case rather than an edge one.
    """
    import glob
    import shutil
    import sys
    candidates = []
    if hint:
        candidates.append(hint)
    on_path = shutil.which("blender")
    if on_path:
        candidates.append(on_path)
    globs = _SEARCH_GLOBS.get(sys.platform, _SEARCH_GLOBS_POSIX)
    found = []
    for pattern in globs:
        found.extend(glob.glob(pattern))
    candidates.extend(sorted(found, key=_version_key, reverse=True))
    for path in candidates:
        real = _real_executable(path)
        if real:
            return real
    return ""


def _real_executable(path):
    # type: (str) -> str
    if not path or not os.path.isfile(path):
        return ""
    directory, name = os.path.split(path)
    if "launcher" in name.lower():
        for sibling in ("blender.exe", "blender"):
            candidate = os.path.join(directory, sibling)
            if os.path.isfile(candidate):
                return candidate
    return path


def blend_command(exe, script_path, blend_path):
    # type: (str, str, str) -> list
    """The headless invocation, as a list for `subprocess`.

    `--` is what separates Blender's own arguments from the script's; without
    it Blender tries to parse `--save` itself and refuses to start.
    """
    return [exe, "-b", "--factory-startup", "--python", script_path,
            "--", "--save", blend_path]


def write_blend(exe, script_path, blend_path, timeout=600):
    # type: (str, str, str, float) -> Tuple[bool, str]
    """Run the generated script in Blender and save the result as a .blend.

    This is the answer to "I don't like having to load it in every time": the
    scene is BUILT before the file is written, so the .blend opens with
    everything already in it — no auto-run, no "Allow Execution" prompt, no
    trust dialog, and F12 just renders.

    Returns (ok, combined output). Failure is reported, never raised: Blender
    is optional, and an export that cannot find it should still leave the
    script behind.
    """
    import subprocess
    exe = _real_executable(exe)
    if not exe:
        return False, "No Blender executable"
    try:
        proc = subprocess.run(blend_command(exe, script_path, blend_path),
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        return False, "Blender exited {}\n{}".format(proc.returncode, out)
    if not os.path.exists(blend_path):
        return False, "Blender ran but wrote no file\n" + out
    return True, out
