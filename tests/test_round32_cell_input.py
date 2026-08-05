"""Round 32: the five issues from Christian's 2026-08-03 screenshots.

  1. the hidden-atoms row mark disappeared when the row was selected
  2. the drawn unit cell left the asymmetric unit out and never completed
     its boundary (NaCl showed one corner sodium instead of eight)
  3. G ran away and reversed as the cursor crossed the drag plane's horizon,
     and the cursor only wrapped horizontally
  4. zoom died while nothing was close, curable only by F
  5. ghosts were blank for NaCl and the symmetry lines read as flat
  plus: "I cannot add a Symmetry (CIF) modifier to anything."
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import cif, manipulate, symmetry
from molom.core.camera import Camera

# The two structures the report was written against. They are read from
# Christian's own directory when present, but the assertions below are pinned
# on the CRYSTALLOGRAPHY, not the file, so the suite still runs without them.
NACL_PATH = (r"C:\Users\chris\Documents\Claude\ASE\FIT_UNIT_CELL\ASE"
             r"\NaCl.cif")
UREA_PATH = (r"C:\Users\chris\Documents\Claude\ASE\FIT_UNIT_CELL\ASE"
             r"\urea.cif")

#: Primitive rock salt, Pm-3m, exactly as COD 2104025 states it.
PRIMITIVE_NACL = """
data_nacl
_symmetry_space_group_name_H-M   'P m -3 m'
_cell_length_a  2.8600
_cell_length_b  2.8600
_cell_length_c  2.8600
_cell_angle_alpha 90.0
_cell_angle_beta  90.0
_cell_angle_gamma 90.0
loop_
_symmetry_equiv_pos_as_xyz
  'x,y,z'
  '-x,-y,z'
  '-x,y,-z'
  'x,-y,-z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
  Na1 Na 0.0 0.0 0.0
  Cl1 Cl 0.5 0.5 0.5
"""


# ------------------------------------------------ 2: the drawn unit cell
def test_an_atom_on_the_origin_appears_on_all_eight_corners():
    """Rock salt is purple on the corners and one green in the middle
    (Christian's words). Drawing a single corner sodium is not a unit cell,
    it is one eighth of one."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    symbols, coords = cif.expand(data)
    assert symbols.count("Na") == 8
    assert symbols.count("Cl") == 1
    frac = coords @ np.linalg.inv(data.cell.matrix())
    corners = {tuple(np.round(f, 3) % 1.0) for f, s in zip(frac, symbols)
               if s == "Na"}
    assert corners == {(0.0, 0.0, 0.0)}          # all eight ARE the origin
    assert len(frac[np.array(symbols) == "Na"]) == 8


def test_the_cell_content_itself_is_unchanged():
    """Z is still Z — the boundary copies are the same atoms seen from the
    neighbouring cells, so anything that needs the CONTENT can switch them
    off and get the formula units back."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    symbols, _ = cif.expand(data, boundary=False)
    assert symbols == ["Na", "Cl"]


def test_boundary_completion_leaves_interior_atoms_alone():
    added_symbols, added = cif.boundary_images(
        ["C", "O"], np.array([[0.5, 0.5, 0.5], [0.25, 0.75, 0.5]]))
    assert added_symbols == []
    assert added.shape == (0, 3)


def test_an_edge_atom_is_doubled_and_a_face_atom_quadrupled():
    on_face = cif.boundary_images(["C"], np.array([[0.0, 0.4, 0.4]]))[1]
    on_edge = cif.boundary_images(["C"], np.array([[0.0, 0.0, 0.4]]))[1]
    on_corner = cif.boundary_images(["C"], np.array([[0.0, 0.0, 0.0]]))[1]
    assert len(on_face) == 1                     # 2 positions total
    assert len(on_edge) == 3                     # 4
    assert len(on_corner) == 7                   # 8


def test_a_boundary_copy_brings_its_whole_molecule():
    """Urea's C and O sit exactly ON the x face. Copying them alone put a
    bare C=O in the middle of the cell with its two NH2 groups left behind
    — the fragment in Christian's screenshot. VESTA draws atoms outside the
    boundary that are bonded to atoms inside it; Mercury includes the whole
    molecule when any atom fits. So does this."""
    if not os.path.exists(UREA_PATH):
        pytest.skip("urea.cif not on this machine")
    from molom.core import bonding
    from molom.core.structure import Structure
    data = cif.parse_cif(open(UREA_PATH, encoding="utf-8",
                              errors="replace").read())
    symbols, coords = cif.expand(data)
    s = Structure(symbols, coords)
    bonding.perceive_structure_bonds(s)
    degree = [0] * len(symbols)
    for i, j, _o in s.bonds:
        degree[i] += 1
        degree[j] += 1
    # In urea every carbon is bonded to O + 2 N, every nitrogen to C + 2 H.
    for k, sym in enumerate(symbols):
        if sym == "C":
            assert degree[k] == 3, "carbon {} is a fragment".format(k)
        if sym == "N":
            assert degree[k] == 3, "nitrogen {} is a fragment".format(k)
        if sym == "O":
            assert degree[k] == 1, "oxygen {} is stranded".format(k)


def test_an_ionic_lattice_is_not_completed_into_molecules():
    """The counterpart: NaCl's Na and Cl fall inside the covalent criterion,
    so treating that pair as a "molecule" and carrying it to every corner
    gives eight chlorines that should not be there. It is a periodic network
    and only the atom itself travels."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    symbols, _coords = cif.expand(data)
    assert symbols.count("Na") == 8
    assert symbols.count("Cl") == 1


def test_periodicity_is_detected_even_in_a_two_atom_cell():
    """A walk cannot find a second route through a cell holding two atoms,
    so rock salt looked finite. It bonds to its own lattice image, which is
    what actually makes it a lattice."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    info = cif.fragment_info(list(data.symbols), data.frac, data.cell,
                             split_coordination=False)
    assert info and all(periodic for _g, periodic in info)


def test_an_ionic_lattice_is_cut_into_ions_not_left_infinite():
    """Round 38: Na-Cl is a COORDINATION bond, so the lattice is cut there
    and each ion becomes its own finite fragment. The boundary output is
    unchanged — a one-atom fragment completes exactly like the per-atom rule
    it replaces — but now for the right reason, and the same cut is what makes
    a MOF's linkers finite."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    info = cif.fragment_info(list(data.symbols), data.frac, data.cell)
    assert [sorted(g) for g, _p in info] == [[0], [1]]


def test_a_real_molecule_is_not_called_periodic():
    if not os.path.exists(UREA_PATH):
        pytest.skip("urea.cif not on this machine")
    data = cif.parse_cif(open(UREA_PATH, encoding="utf-8",
                              errors="replace").read())
    symbols, coords = cif.expand(data, boundary=False)
    frac = coords @ np.linalg.inv(data.cell.matrix())
    info = cif.fragment_info(list(symbols), frac, data.cell)
    assert info and not any(periodic for _g, periodic in info)


def test_a_molecule_centred_on_a_face_stays_inside_its_own_cell():
    """Urea's molecule sits exactly ON the x face, so whether floor() saw
    1.0 or 0.99999 decided between drawing it in the box and dumping it
    outside — which is what "the asymmetric unit is left out of the unit
    cell" actually was."""
    if not os.path.exists(UREA_PATH):
        pytest.skip("urea.cif not on this machine")
    data = cif.parse_cif(open(UREA_PATH, encoding="utf-8",
                              errors="replace").read())
    symbols, coords = cif.expand(data)
    frac = coords @ np.linalg.inv(data.cell.matrix())
    carbons = frac[np.array(symbols) == "C"]
    # A carbon must sit at the x = 0 face, not only at x = 1.
    assert np.any(np.abs(carbons[:, 0]) < 1e-6)


@pytest.mark.skipif(not os.path.exists(NACL_PATH), reason="not on this machine")
def test_christians_nacl_file_gives_eight_corners_and_one_centre():
    data = cif.parse_cif(open(NACL_PATH, encoding="utf-8",
                              errors="replace").read())
    symbols, _coords = cif.expand(data)
    assert symbols.count("Na") == 8
    assert symbols.count("Cl") == 1


# -------------------------------------------------- 3: the grab runaway
def _ray(pitch_deg):
    """A ray from 10 A up the +z axis, tilted by `pitch` off straight down."""
    a = np.radians(pitch_deg)
    return np.array([0.0, 0.0, 10.0]), np.array([0.0, np.sin(a), -np.cos(a)])


def test_a_grazing_ray_gives_no_plane_hit():
    """As the cursor rises past the drag plane's horizon the intersection
    shoots to infinity and then FLIPS SIGN — the selection bolting the other
    way. None makes the caller hold instead."""
    plane_point, normal = np.zeros(3), np.array([0.0, 0.0, 1.0])
    origin, direction = _ray(0.0)
    assert manipulate.ray_plane(origin, direction, plane_point,
                                normal) is not None
    # Past ~81 degrees off vertical the ray is grazing the plane.
    for pitch in (82.0, 89.0, 90.0, 91.0, 120.0):
        assert manipulate.ray_plane(_ray(pitch)[0], _ray(pitch)[1],
                                    plane_point, normal) is None


def test_the_plane_hit_never_jumps_across_the_horizon():
    plane_point, normal = np.zeros(3), np.array([0.0, 0.0, 1.0])
    last = None
    for pitch in np.arange(0.0, 80.0, 2.0):
        hit = manipulate.ray_plane(_ray(pitch)[0], _ray(pitch)[1],
                                   plane_point, normal)
        assert hit is not None
        if last is not None:
            assert hit[1] > last[1]          # monotonic, never reversing
        last = hit


def test_a_grab_holds_still_when_the_ray_stops_meaning_anything():
    state = manipulate.GrabState(np.zeros(3), np.array([0.0, 0.0, 1.0]))
    origin, direction = _ray(40.0)
    state.update_mouse(origin, direction)
    origin, direction = _ray(60.0)
    state.update_mouse(origin, direction)
    moved = state.delta().copy()
    for pitch in (91.0, 120.0, 179.0):
        state.update_mouse(*_ray(pitch))
        assert state.delta() == pytest.approx(moved), "grab bolted at the horizon"


def test_an_axis_locked_grab_holds_when_sighted_along_its_axis():
    state = manipulate.GrabState(np.zeros(3), np.array([0.0, 0.0, 1.0]))
    state.set_axis(0)                       # lock to X
    state.update_mouse(np.array([0.0, 0.0, 10.0]),
                       np.array([0.3, 0.0, -1.0]))
    before = state.delta().copy()
    # now look straight down the X axis: the cursor carries no information
    state.update_mouse(np.array([-10.0, 0.0, 0.0]),
                       np.array([1.0, 0.0, 0.0]))
    assert state.delta() == pytest.approx(before)


def test_ray_line_still_solves_an_ordinary_view():
    t = manipulate.ray_line_t(np.array([0.0, 5.0, 0.0]),
                              np.array([0.0, -1.0, 0.0]),
                              np.zeros(3), np.array([1.0, 0.0, 0.0]))
    assert t == pytest.approx(0.0)


# ---------------------------------------------------------- 4: the zoom
def test_zooming_in_keeps_making_progress_after_the_centre_drifts():
    """Twelve ordinary pans put the orbit centre 20+ A from the molecule;
    zoom then bottomed out at the 0.5 A floor with nothing near the camera.
    F cured it because F re-fits the centre."""
    cam = Camera()
    cam.fit(np.zeros(3), 5.0)
    for _ in range(12):
        cam.pan(120, 40, 1200, 800)
    drift = float(np.linalg.norm(cam.center))
    assert drift > 5.0, "the pans must actually move the centre"
    before = float(np.linalg.norm(cam.center - np.zeros(3)))
    for _ in range(80):
        cam.zoom(1)
    after = float(np.linalg.norm(cam.center - np.zeros(3)))
    assert cam.distance == pytest.approx(cam.MIN_DISTANCE)
    assert after != pytest.approx(before), "zoom stopped making progress"


def test_zooming_in_travels_along_the_view_direction():
    from molom.core.camera import quat_to_mat3
    cam = Camera()
    cam.fit(np.zeros(3), 5.0)
    cam.distance = cam.MIN_DISTANCE
    before = cam.center.copy()
    cam.zoom(1)
    moved = cam.center - before
    forward = quat_to_mat3(cam.rotation).T @ np.array([0.0, 0.0, -1.0])
    assert float(np.linalg.norm(moved)) > 0.0
    assert moved / np.linalg.norm(moved) == pytest.approx(forward)


def test_ordinary_zoom_is_untouched():
    cam = Camera()
    cam.fit(np.zeros(3), 5.0)
    centre = cam.center.copy()
    start = cam.distance
    cam.zoom(1)
    assert cam.distance == pytest.approx(start * 0.88)
    assert cam.center == pytest.approx(centre)   # the centre must NOT move
    cam.zoom(-1)
    assert cam.distance == pytest.approx(start)


# -------------------------------------------------------- 5: the ghosts
def test_ghosts_exist_for_a_structure_whose_ops_all_map_onto_themselves():
    """In Pm-3m every operator maps Na(0,0,0)+Cl(1/2,1/2,1/2) onto itself, so
    after de-duplication there was nothing left to draw at all."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    ghosts = symmetry.images_of(data.frac, data.symops)
    assert ghosts, "no ghost images for rock salt"
    origins = {tuple(np.round(g[0], 3)) for g in ghosts}
    assert (1.0, 0.0, 0.0) in origins            # the neighbouring corner


def test_ghost_images_are_distinct():
    """One ghost per OPERATOR stacks 47 identical skeletons on the original
    in a 48-operator group."""
    data = cif.parse_cif(PRIMITIVE_NACL)
    ghosts = symmetry.images_of(data.frac, data.symops)
    for i in range(len(ghosts)):
        for j in range(i + 1, len(ghosts)):
            assert not np.allclose(ghosts[i], ghosts[j], atol=1e-4)


def test_a_ghost_is_never_the_asymmetric_unit_itself():
    data = cif.parse_cif(PRIMITIVE_NACL)
    base = data.frac - np.floor(data.frac)
    for g in symmetry.images_of(data.frac, data.symops):
        assert not np.allclose(g, base, atol=1e-4)


# --------------------------------------------------------------- the app
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.load_default_scene()
    return w


def _open_nacl(win, tmp_path):
    path = tmp_path / "nacl.cif"
    path.write_text(PRIMITIVE_NACL, encoding="utf-8")
    win.open_path(str(path))
    return win._active_obj()


def test_adding_a_symmetry_modifier_changes_something(win, tmp_path):
    """It appended a modifier to a molecule that was ALREADY the full cell,
    so the operations de-duplicated straight back and nothing moved."""
    obj = _open_nacl(win, tmp_path)
    assert obj.structure.n_atoms == 9            # the drawn cell
    win.on_add_modifier("symmetry")
    # by KIND, not by index: a crystal whose bonds cross the cell faces also
    # carries a boundary modifier (round 39), and it is kept LAST.
    syms = [m for m in obj.modifiers if getattr(m, "kind", "") == "symmetry"]
    assert len(syms) == 1
    assert getattr(obj.modifiers[-1], "kind", "") in ("symmetry", "boundary")
    assert obj.structure.n_atoms == 2            # base = the asymmetric unit
    assert len(obj.evaluated()[0]) == 9          # what gets drawn/exported


def test_a_plain_molecule_can_take_a_symmetry_modifier(win):
    """Christian's actual use case: take a fragment, stack single operations
    one at a time, and watch an asymmetric unit become a cell. Refusing
    because the molecule "has no cell" made the whole modifier unreachable
    for exactly the job it is most instructive for."""
    obj = win.scene.objects[0]
    win.on_add_modifier("symmetry")
    # by KIND, not by index: a crystal whose bonds cross the cell faces also
    # carries a boundary modifier (round 39), and it is kept LAST.
    syms = [m for m in obj.modifiers if getattr(m, "kind", "") == "symmetry"]
    assert len(syms) == 1
    assert getattr(obj.modifiers[-1], "kind", "") in ("symmetry", "boundary")
    mod = obj.modifiers[0]
    assert mod.symops == ["x,y,z"]               # identity to start from
    assert mod.cell["a"] > 0.0                   # a box was invented for it
    base = obj.structure.n_atoms
    assert len(obj.evaluated()[0]) == base       # identity changes nothing


def test_each_added_operation_multiplies_the_content(win):
    obj = win.scene.objects[0]
    win.on_add_modifier("symmetry")
    mod = obj.modifiers[0]
    base = obj.structure.n_atoms
    for k, op in enumerate(("-x,-y,z", "-x,-y,-z", "1/2+x,1/2+y,z"), start=2):
        mod.symops.append(op)
        assert len(obj.evaluated()[0]) == base * k, \
            "{} produced no new copy".format(op)


def test_a_molecule_on_the_cell_origin_would_map_onto_itself(win):
    """Which is why the invented cell is OFFSET so the molecule sits at a
    general position — otherwise every operation through the origin is a
    no-op and the modifier looks broken while working perfectly."""
    obj = win.scene.objects[0]
    win.on_add_modifier("symmetry")
    mod = obj.modifiers[0]
    assert not np.allclose(mod.origin, np.zeros(3))
    mod.symops.append("-x,-y,-z")
    assert len(obj.evaluated()[0]) == 2 * obj.structure.n_atoms
    mod.origin = np.zeros(3)                     # put it back on the origin
    obj.structure.frames[0] -= obj.structure.coords.mean(axis=0)
    assert len(obj.evaluated()[0]) == obj.structure.n_atoms


def test_a_crystal_still_uses_its_own_cell(win, tmp_path):
    obj = _open_nacl(win, tmp_path)
    win.on_add_modifier("symmetry")
    mod = [m for m in obj.modifiers if getattr(m, "kind", "") == "symmetry"][0]
    assert len(mod.symops) == 4                  # the file's operations
    assert mod.cell["a"] == pytest.approx(2.86)
    assert np.allclose(mod.origin, np.zeros(3))  # the CIF's own frame


def test_the_symmetry_card_is_not_blank(win, tmp_path):
    _open_nacl(win, tmp_path)
    win.properties.setVisible(True)
    win.on_add_modifier("symmetry")
    win._sync_modifier_page()
    mod = [m for m in win._active_obj().modifiers
           if getattr(m, "kind", "") == "symmetry"][0]
    assert "ops" in win.modifier_page._summary(mod)


def test_the_depth_cue_spans_what_is_drawn(win):
    """Scaling the cue by camera distance made a small cell come out flat —
    every line at nearly the same alpha, which is "no depth cues"."""
    vp = win.viewport
    corners = np.array([[x, y, z] for x in (0.0, 3.0)
                        for y in (0.0, 3.0) for z in (0.0, 3.0)])
    vp.set_depth_cue_extent(corners)
    fades = sorted(vp._depth_fade(c) for c in corners)
    assert fades[0] < 0.15 and fades[-1] > 0.95, "the cue barely varies"
    vp._cue_range = None


def test_the_symmetry_overlay_is_not_recomputed_every_frame(win, tmp_path):
    """Parsing 48 operators, classifying them (an eigen-decomposition each)
    and re-imaging the ghosts cost ~12 ms per repaint, so simply switching
    symmetry on made trackpad zooming crawl."""
    obj = _open_nacl(win, tmp_path)
    meta = obj.structure.metadata
    meta["show_symmetry"] = True
    meta["show_ghosts"] = True
    vp = win.viewport
    vp._sym_cache = None
    first = vp._symmetry_plan(obj, meta)
    again = vp._symmetry_plan(obj, meta)
    assert again is first, "the plan was rebuilt for an unchanged scene"
    # ...but a changed filter must rebuild it
    meta["symmetry_kinds"] = ["rotation"]
    assert vp._symmetry_plan(obj, meta) is not first


def test_the_cursor_wraps_on_both_axes(win):
    """It was horizontal only, so a vertical grab ran out of screen and the
    pointer left the window."""
    from PySide6.QtCore import QPointF
    vp = win.viewport
    vp.resize(800, 600)
    obj = win.scene.objects[0]
    vp.set_selection([(obj.id, 0)])
    vp.start_grab()
    assert vp._active_modal_state() is not None
    for pos, moved in ((QPointF(2.0, 300.0), True),
                       (QPointF(798.0, 300.0), True),
                       (QPointF(400.0, 2.0), True),
                       (QPointF(400.0, 598.0), True),
                       (QPointF(400.0, 300.0), False)):
        before = QPointF(vp._drag_last) if vp._drag_last else None
        vp._wrap_cursor(pos)
        after = vp._drag_last
        if moved:
            assert after != pos, "no wrap at {}".format(pos)
        else:
            assert before is None or after == before
