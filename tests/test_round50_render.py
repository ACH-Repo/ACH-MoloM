"""Round 50: the render path — polyhedra that reach Blender, and a .blend.

Three things, all from the round-49 "NEXT UP" list:

* the polyhedra SHADING was a Python loop per triangle per frame, which is
  most of the slowdown Christian noticed after round 48;
* the Blender export dropped coordination polyhedra entirely, so a MOF figure
  lost exactly the thing that makes it readable;
* the export wrote a script you had to run every time, where Blender is
  installed and can simply be invoked to save a finished `.blend`.

The .blend half cannot be asserted offline — it needs Blender — so what is
pinned here is the command and the discovery, and the actual run was verified
by doing it: Blender 5.1 headless on `cod_1547149_solid_solution.cif`, then
rendering the saved file with no script involved.
"""

import ast
import os

import numpy as np
import pytest

from molom.core import blender_export as bx
from molom.core import bonding, build, cif, polyhedra
from molom.core import style as style_mod
from molom.core.camera import Camera
from molom.core.scene import Scene
from molom.core.structure import Structure

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ------------------------------------------------------------------ shading
def _octahedra(n=12):
    """A pile of octahedra — the shape of a packed framework's polyhedra."""
    rng = np.random.default_rng(0)
    base = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                     [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float) * 2.0
    out = []
    for k in range(n):
        verts = base + rng.normal(scale=0.1, size=(6, 3)) + rng.uniform(
            -20, 20, size=3)
        out.append({"centre": k, "symbol": "Mg", "color": (0.54, 1.0, 0.0),
                    "vertices": verts, "faces": polyhedra.hull_faces(verts),
                    "donors": []})
    return out


def test_the_split_shading_is_the_same_shading():
    """`face_arrays` + `shade_from_faces` must be `shade_colors` exactly —
    the split is a performance change, not a look change."""
    built = _octahedra()
    eye = np.array([3.0, -8.0, 40.0])
    faces = polyhedra.face_arrays(built)
    assert np.allclose(polyhedra.shade_from_faces(faces, eye),
                       polyhedra.shade_colors(built, eye))


def test_the_cached_half_carries_the_triangle_soup():
    """The vertices were being rebuilt per frame too, one `triangle_soup` call
    per polyhedron; they are camera-independent, so they belong in the cache
    with the normals."""
    built = _octahedra()
    faces = polyhedra.face_arrays(built)
    soup = np.vstack([polyhedra.triangle_soup([p])[0] for p in built])
    assert np.allclose(faces["vertices"], soup)
    n_faces = sum(len(p["faces"]) for p in built)
    assert len(faces["normals"]) == n_faces
    assert len(faces["centroids"]) == n_faces
    assert len(faces["vertices"]) == 3 * n_faces


def test_shading_an_empty_scene_is_an_empty_array():
    empty = polyhedra.face_arrays([])
    assert empty["vertices"].shape == (0, 3)
    assert polyhedra.shade_from_faces(empty, np.zeros(3)).shape == (0, 3)


def test_a_degenerate_face_still_shades_finite():
    poly = [{"vertices": np.zeros((3, 3)), "faces": [(0, 1, 2)],
             "color": (0.5, 0.5, 0.5), "centre": 0, "symbol": "Mg",
             "donors": []}]
    faces = polyhedra.face_arrays(poly)
    assert np.all(np.isfinite(polyhedra.shade_from_faces(faces,
                                                         np.zeros(3))))


# -------------------------------------------------------------------- hulls
def test_a_square_face_is_covered_once():
    """A hull face is a PLANE, not a triple. One triangle per accepted triple
    stacked FOUR of them on each square face of a cubic centre — 24 triangles
    over its 12, which blends twice in the viewport and z-fights in a render.
    """
    cube = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1)
                     for z in (-1, 1)], dtype=float)
    assert len(polyhedra.hull_faces(cube)) == 12


@pytest.mark.parametrize("name,points,n_faces", [
    ("tetrahedron", [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], 4),
    ("octahedron", [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0],
                    [0, 0, 1], [0, 0, -1]], 8),
    ("trigonal bipyramid", [[1, 0, 0], [-0.5, 0.87, 0], [-0.5, -0.87, 0],
                            [0, 0, 1.2], [0, 0, -1.2]], 6),
    ("square pyramid", [[1, 1, 0], [1, -1, 0], [-1, 1, 0], [-1, -1, 0],
                        [0, 0, 1.5]], 6),
])
def test_the_standard_coordination_solids_have_their_own_face_count(
        name, points, n_faces):
    assert len(polyhedra.hull_faces(np.asarray(points, dtype=float))) \
        == n_faces


def test_every_face_still_winds_outward():
    """Backface culling and the flat shading both depend on it, and grouping
    the triples into planes is exactly where the winding could have been
    lost — a fan built in index order faces whichever way it happens to."""
    rng = np.random.default_rng(3)
    for _ in range(50):
        pts = rng.normal(size=(int(rng.integers(4, 10)), 3))
        centre = pts.mean(axis=0)
        for a, b, c in polyhedra.hull_faces(pts):
            normal = np.cross(pts[b] - pts[a], pts[c] - pts[a])
            outward = pts[[a, b, c]].mean(axis=0) - centre
            assert float(normal @ outward) > -1e-9


# ----------------------------------------------------------- for_object
def _crystal():
    from molom.core import io
    atoms, meta = io.read_structures(
        os.path.join(DATA, "cod_1547149_solid_solution.cif"))[0]
    s = Structure([a[0] for a in atoms],
                  np.array([a[1:] for a in atoms], dtype=float),
                  metadata=meta)
    bonding.perceive_structure_bonds(s)
    return s


def test_polyhedra_are_off_unless_the_object_says_so():
    sc = Scene()
    obj = sc.add(_crystal(), name="oxide")
    assert polyhedra.for_object(obj, None) == []
    obj.structure.metadata["polyhedra"] = True
    assert polyhedra.for_object(obj, None)          # falls back to the bonds


def test_a_crystal_builds_from_the_periodic_graph():
    """With a cell it goes through `build_periodic`, so every solid closes
    whatever the display options are doing."""
    sc = Scene()
    obj = sc.add(_crystal(), name="oxide")
    obj.structure.metadata["polyhedra"] = True
    cell = cif.Cell.from_dict(obj.structure.metadata["cell"])
    built = polyhedra.for_object(obj, cell)
    assert len(built) == 10
    assert all(len(p["vertices"]) == 6 for p in built)   # whole octahedra
    assert all(len(p["faces"]) == 8 for p in built)


# ------------------------------------------------------- the Blender export
@pytest.fixture
def crystal_scene():
    sc = Scene()
    obj = sc.add(_crystal(), name="oxide")
    obj.structure.metadata["polyhedra"] = True
    return sc


def _cell_of(obj):
    d = (obj.structure.metadata or {}).get("cell")
    return cif.Cell.from_dict(d) if d else None


def test_the_export_carries_the_polyhedra(crystal_scene):
    """Measured before this round: `collect` returned atoms, bonds, camera,
    centre, lights, materials and radius, and the only mention of the module
    was `is_metal` for picking metallic materials. A MOF figure lost the
    solids."""
    data = bx.collect(crystal_scene, style_mod.BALL_AND_STICK,
                      bx.ExportOptions(), cell_of=_cell_of)
    assert len(data["polyhedra"]) == 10
    first = data["polyhedra"][0]
    assert len(first["vertices"]) == 6 and len(first["faces"]) == 8
    assert first["material"] == "MoloM Nb polyhedron"
    assert "10 polyhedra" in bx.summarise(data)


def test_the_polyhedron_material_is_translucent_and_not_metallic(
        crystal_scene):
    """Niobium is a metal, so the ordinary material is metallic — but a
    translucent metal renders as a chrome shell with nothing readable inside
    it, which is the opposite of the point."""
    data = bx.collect(crystal_scene, style_mod.BALL_AND_STICK,
                      bx.ExportOptions(polyhedra_alpha=0.4),
                      cell_of=_cell_of)
    by_name = {m["name"]: m for m in data["materials"]}
    assert by_name["MoloM Nb"]["metallic"] == 1.0
    solid = by_name["MoloM Nb polyhedron"]
    assert solid["alpha"] == pytest.approx(0.4)
    assert solid["metallic"] == 0.0


def test_turning_the_polyhedra_off_exports_none(crystal_scene):
    data = bx.collect(crystal_scene, style_mod.BALL_AND_STICK,
                      bx.ExportOptions(polyhedra=False), cell_of=_cell_of)
    assert data["polyhedra"] == []
    assert not any("polyhedron" in m["name"] for m in data["materials"])


def test_a_plain_molecule_exports_no_polyhedra():
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    data = bx.collect(sc, style_mod.BALL_AND_STICK, bx.ExportOptions())
    assert data["polyhedra"] == []
    assert "polyhedra" not in bx.summarise(data)


def test_the_script_carries_them_as_a_readable_literal(crystal_scene):
    cam = Camera()
    cam.fit(np.zeros(3), 8.0)
    opts = bx.ExportOptions()
    data = bx.collect(crystal_scene, style_mod.BALL_AND_STICK, opts,
                      camera=cam, cell_of=_cell_of)
    src = bx.build_script(data, opts, title="oxide")
    compile(src, "<script>", "exec")              # it is valid Python
    node = [n for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and n.targets[0].id == "POLYHEDRA"]
    solids = ast.literal_eval(node[0].value)
    assert len(solids) == 10
    name, material, verts, faces = solids[0]
    assert name.startswith("poly.Nb.")
    assert material == "MoloM Nb polyhedron"
    assert len(verts) == 6 and all(len(v) == 3 for v in verts)
    assert len(faces) == 8 and all(len(f) == 3 for f in faces)
    # `from_pydata` indexes into the vertex list, so every index must be one
    assert all(0 <= i < len(verts) for f in faces for i in f)
    assert "build_polyhedra" in src


# ------------------------------------------------------------ running Blender
def test_a_launcher_resolves_to_the_real_executable(tmp_path):
    """Windows installs ship `blender-launcher.exe` beside `blender.exe`, and
    the launcher is a GUI shim — `-b --python` wants the binary. Christian's
    own path points at the launcher, so this is the normal case."""
    (tmp_path / "blender-launcher.exe").write_text("x")
    (tmp_path / "blender.exe").write_text("x")
    got = bx.find_blender(str(tmp_path / "blender-launcher.exe"))
    assert os.path.basename(got) == "blender.exe"


def test_a_lone_binary_is_taken_as_it_is(tmp_path):
    exe = tmp_path / "blender"
    exe.write_text("x")
    assert bx.find_blender(str(exe)) == str(exe)


def test_a_missing_hint_does_not_stop_the_search(tmp_path):
    """The stored setting can point at an install that has been moved or
    upgraded; a dead path must fall through to discovery, not win."""
    missing = str(tmp_path / "nowhere" / "blender.exe")
    assert bx.find_blender(missing) != missing


def test_the_command_separates_blenders_arguments_from_the_scripts():
    """Without the bare `--`, Blender parses `--save` itself and refuses to
    start."""
    cmd = bx.blend_command("blender", "build.py", "out.blend")
    assert cmd[0] == "blender" and "-b" in cmd
    assert cmd.index("--python") < cmd.index("--")
    assert cmd[cmd.index("--") + 1:] == ["--save", "out.blend"]


def test_the_script_saves_when_told_to():
    """The `--save` handling has to be in the generated source, since that is
    what runs inside Blender."""
    data = bx.collect(Scene(), style_mod.BALL_AND_STICK, bx.ExportOptions())
    src = bx.build_script(data, bx.ExportOptions())
    assert "def save_blend(path):" in src
    assert "wm.save_as_mainfile" in src
    assert '"--save" in _argv' in src
    # ...and it must not fire on an ordinary "Run Script" in the GUI, where
    # there is no `--` in sys.argv at all.
    assert 'if "--" in sys.argv' in src


def test_write_blend_reports_a_missing_blender_rather_than_raising(tmp_path):
    """Blender is optional. A failed build must leave the script behind and
    say so, not take the export down with it."""
    ok, message = bx.write_blend("", str(tmp_path / "b.py"),
                                 str(tmp_path / "o.blend"))
    assert ok is False and "Blender" in message


def test_the_default_filename_follows_the_format():
    assert bx.default_path("/tmp", "zif").endswith("zif_blender.py")
    assert bx.default_path("/tmp", "zif", ".blend").endswith(
        "zif_blender.blend")


# ------------------------------------------------------------------ the UI
def test_the_dialog_round_trips_the_new_options():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.dialogs import BlenderExportDialog
    QApplication.instance() or QApplication([])
    opts = bx.ExportOptions(output="script", polyhedra=False,
                            polyhedra_alpha=0.8)
    dlg = BlenderExportDialog(None, opts)
    out = dlg.options()
    assert out.output == "script"
    assert out.polyhedra is False
    assert out.polyhedra_alpha == pytest.approx(0.8)
    # the opacity is meaningless with the solids off, so it greys out
    assert not dlg.polyhedra_alpha.isEnabled()
    dlg.polyhedra.setChecked(True)
    assert dlg.polyhedra_alpha.isEnabled()


def test_the_blender_path_greys_out_for_a_script():
    """It is only needed to BUILD a .blend; leaving it live over a format
    that never uses it is a control that does nothing."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.dialogs import BlenderExportDialog
    QApplication.instance() or QApplication([])
    dlg = BlenderExportDialog(None, bx.ExportOptions(output="blend"))
    assert dlg.blender_exe.isEnabled()
    dlg.output_combo.setCurrentIndex(
        dlg.output_combo.findData("script"))
    assert not dlg.blender_exe.isEnabled()


def test_the_export_option_keys_all_exist():
    """`_BLENDER_KEYS` drives the QSettings round trip by name, so a typo
    there is a silently unsaved preference."""
    pytest.importorskip("PySide6")
    from molom.ui.app import MainWindow
    opts = bx.ExportOptions()
    for key in MainWindow._BLENDER_KEYS:
        assert hasattr(opts, key), key
