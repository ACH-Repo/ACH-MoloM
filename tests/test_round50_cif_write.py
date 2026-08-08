"""Round 50: a written `.cif` that is actually a crystal.

There was no CIF writer at all. `io.write_structure_file` handed OpenBabel an
xyz block for any non-xyz extension, so a `.cif` carried coordinates and
nothing else — measured on a ZIF-8 export: no `_cell_length_a`, no symmetry,
and MoloM's own parser rejected the file MoloM had just written.

The round trip is the test that matters, so most of these read the file back
through the real reader rather than looking at the text. Two independent
readers were also run by hand: ASE and pymatgen both read the written files
exactly as they read the originals, and pymatgen actually warns on the
ORIGINAL ferrocene file (no operator loop) and not on ours.
"""

import os

import numpy as np
import pytest

from molom.core import bonding, build, cif, cif_write, io, rotations
from molom.core.scene import Scene
from molom.core.structure import Structure

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")
OXIDE = os.path.join(DATA, "cod_1547149_solid_solution.cif")


def _load(path, pin=True):
    """A scene object as the app would have it, cell reference included."""
    atoms, meta = io.read_structures(path)[0]
    s = Structure([a[0] for a in atoms],
                  np.array([a[1:] for a in atoms], dtype=float),
                  metadata=meta)
    bonding.perceive_structure_bonds(s)
    if pin:
        from molom.ui.viewport import set_cell_reference
        set_cell_reference(s)
    sc = Scene()
    return sc.add(s, name=os.path.splitext(os.path.basename(path))[0])


def _write(obj, tmp_path, name="out.cif", **kw):
    path = str(tmp_path / name)
    report = {}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(cif_write.from_object(obj, report=report, **kw))
    return path, report


def _facts(path):
    atoms, meta = io.read_structures(path)[0]
    from collections import Counter
    return {
        "n": len(atoms),
        "formula": dict(sorted(Counter(a[0] for a in atoms).items())),
        "cell": tuple(round(meta["cell"][k], 6) for k in
                      ("a", "b", "c", "alpha", "beta", "gamma")),
        "ops": len(meta.get("symops") or []),
        "sg": meta.get("spacegroup"),
        "content": meta.get("cell_content"),
        "asym": len(meta.get("asym_symbols") or []),
    }


# ------------------------------------------------------------ the round trip
@pytest.mark.parametrize("source", [FERROCENE, OXIDE])
def test_a_crystal_survives_the_round_trip_intact(source, tmp_path):
    """Cell, space group, operator count, asymmetric unit and every drawn
    atom — the same file read back."""
    obj = _load(source)
    path, report = _write(obj, tmp_path)
    assert report["policy"] == cif_write.POLICY_ASYMMETRIC
    assert _facts(path) == _facts(source)


def test_the_file_we_write_is_one_our_own_reader_accepts(tmp_path):
    """The measurement that opened this item: our parser rejected our own
    output with "no unit cell in this CIF"."""
    obj = _load(OXIDE)
    path, _r = _write(obj, tmp_path)
    text = open(path, encoding="utf-8").read()
    assert "_cell_length_a" in text
    assert "_symmetry_equiv_pos_as_xyz" in text
    assert "_atom_site_occupancy" in text
    data = cif.parse_cif(text)
    assert data.cell is not None and len(data.symops) == 16


def test_the_setting_the_file_was_written_in_is_kept(tmp_path):
    """All nine settings of number 14 share the standard short symbol, so
    printing `P2_1/c` for a file that says `P 21/a` reads as an outright
    error to whoever made the compound (round 41)."""
    obj = _load(FERROCENE)
    path, report = _write(obj, tmp_path)
    assert report["spacegroup"] == "P 1 21/a 1"
    assert io.read_structures(path)[0][1]["spacegroup"] == "P 1 21/a 1"


def test_the_operator_loop_is_written_once(tmp_path):
    """Writing BOTH synonymous tags as two columns of one loop doubles the
    operator count for any reader that knows them: the first cut read its own
    16-operation file back as 32."""
    obj = _load(OXIDE)
    path, _r = _write(obj, tmp_path)
    text = open(path, encoding="utf-8").read()
    assert text.count("_symmetry_equiv_pos_as_xyz") == 1
    assert "_space_group_symop_operation_xyz" not in text
    assert io.read_structures(path)[0][1]["symops"] == \
        io.read_structures(OXIDE)[0][1]["symops"]


def test_the_site_labels_come_back(tmp_path):
    """"C12A" is what the crystallographer calls that atom."""
    obj = _load(FERROCENE)
    path, _r = _write(obj, tmp_path)
    labels = cif.parse_cif(open(path, encoding="utf-8").read()).labels
    assert labels == cif.parse_cif(open(FERROCENE,
                                        encoding="utf-8").read()).labels


def test_occupancies_and_the_disorder_columns_round_trip(tmp_path):
    """`resolve_disorder` PREFERS the group/assembly columns to geometric
    overlap, so dropping them means the file we wrote resolves to a different
    structure from the one we read — round 43c's bug from the other side."""
    src = tmp_path / "d.cif"
    src.write_text("""data_d
_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_symmetry_equiv_pos_as_xyz
'x, y, z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_disorder_assembly
_atom_site_disorder_group
C1  C  0.1000 0.1000 0.1000 1.00  .  .
C2A C  0.3000 0.1000 0.1000 0.60  A  1
C2B C  0.3200 0.1200 0.1000 0.40  A  2
O1  O  0.5000 0.1000 0.1000 1.00  .  .
""", encoding="utf-8")
    obj = _load(str(src))
    path, _r = _write(obj, tmp_path)
    before = io.read_structures(str(src))[0][1]
    after = io.read_structures(path)[0][1]
    for key in ("asym_occupancy", "asym_disorder_groups",
                "asym_disorder_assemblies", "asym_symbols"):
        assert after[key] == before[key], key


def test_an_ordered_file_gets_no_empty_disorder_columns(tmp_path):
    obj = _load(FERROCENE)
    path, _r = _write(obj, tmp_path)
    assert "_atom_site_disorder_group" not in open(path,
                                                   encoding="utf-8").read()


# ------------------------------------------------------------ what is written
def test_only_the_cell_CONTENT_is_written(tmp_path):
    """Everything past `cell_content` is a boundary copy, i.e. an exact
    lattice translate of an atom already listed. Writing those would claim a
    cell with every face atom in it twice."""
    obj = _load(FERROCENE)
    assert obj.structure.n_atoms == 210             # the packed picture
    path, report = _write(obj, tmp_path)
    assert report["n_drawn"] == 210 and report["n_content"] == 42
    assert report["n_sites"] == 11                  # the asymmetric unit
    parsed = cif.parse_cif(open(path, encoding="utf-8").read())
    assert parsed.n_sites == 11


def test_a_rotated_crystal_writes_the_same_file():
    """A cell is stored as lengths and angles, so its matrix is built in a
    canonical orientation and every fractional calculation assumes the atoms
    are still in it. Rotate the crystal and the coordinates ARE the rotation
    unless the pose is undone first (round 43c)."""
    obj = _load(FERROCENE)
    plain = cif_write.from_object(obj)
    original = np.array(obj.structure.coords, dtype=float)
    for degrees in (10.0, 37.0, 90.0):
        rot = rotations.axis_angle_mat3(np.array([0.3, 0.8, 0.5]),
                                        np.radians(degrees))
        obj.structure.frames[0][:] = original @ rot.T
        assert cif_write.from_object(obj) == plain, degrees


def test_an_edit_re_derives_the_symmetry_instead_of_keeping_it(tmp_path):
    """Operators that no longer describe the structure would expand it into a
    cell that never existed. Moving one atom of six in P4_2/mnm breaks every
    operation, and spglib says so."""
    obj = _load(OXIDE)
    obj.structure.frames[0][0] += np.array([0.31, 0.17, 0.09])
    path, report = _write(obj, tmp_path)
    assert report["policy"] == cif_write.POLICY_CELL
    assert report["symops"] == 1                    # P1: the symmetry is gone
    assert report["occupancy_lost"] is True         # ...and it says so
    assert io.read_structures(path)                 # still a readable crystal


def test_an_unedited_cell_keeps_the_files_own_operators(tmp_path):
    """The converse, and the reason the choice is made by measurement: with
    nothing moved, the stored asymmetric unit still reproduces the drawn
    content, so nothing is re-derived."""
    obj = _load(OXIDE)
    _path, report = _write(obj, tmp_path)
    assert report["policy"] == cif_write.POLICY_ASYMMETRIC
    assert report.get("rederived") is None


def test_asking_for_p1_writes_the_whole_content(tmp_path):
    obj = _load(OXIDE)
    path, report = _write(obj, tmp_path, policy=cif_write.POLICY_P1)
    assert report["policy"] == cif_write.POLICY_P1
    assert report["n_sites"] == report["n_content"] == 6
    assert len(io.read_structures(path)[0][1]["symops"]) == 1


# --------------------------------------------------------------- no cell
def test_a_molecule_gets_an_invented_box_and_is_told_so(tmp_path):
    """A CIF without a cell is not a CIF, so refusing to write one would be
    less useful than writing one honestly labelled. The geometry has to
    survive: the box is a container, not a change of shape."""
    sc = Scene()
    obj = sc.add(build.cubane(), name="cubane")
    path, report = _write(obj, tmp_path)
    assert report["invented_cell"] is True
    assert report["policy"] == cif_write.POLICY_P1
    assert "invented" in open(path, encoding="utf-8").read()
    atoms, _meta = io.read_structures(path)[0]
    assert len(atoms) == 16
    before = np.array(obj.structure.coords, dtype=float)
    after = np.array([a[1:] for a in atoms], dtype=float)
    before = before - before.mean(axis=0)
    after = after - after.mean(axis=0)
    gap = np.linalg.norm(before[:, None, :] - after[None, :, :], axis=-1)
    # 5 decimal places on a ~15 A box is 1.5e-4 A, and nothing worse than that
    assert gap.min(axis=1).max() < 5e-4


def test_the_invented_box_clears_the_molecule_on_every_side():
    """An invented cell must at least not imply a bond that is not there."""
    xyz = np.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0], [0.0, 3.0, 0.0]])
    cell = cif_write.invented_cell(xyz)
    assert cell.a >= 1.5 + 2 * cif_write.INVENTED_PADDING - 1e-9
    assert cell.b >= 3.0 + 2 * cif_write.INVENTED_PADDING - 1e-9
    assert cell.alpha == cell.beta == cell.gamma == 90.0


def test_write_structure_file_no_longer_goes_through_openbabel(tmp_path):
    """Any caller with plain atoms still gets a REAL cif — the xyz-block
    route produced a file with no cell at all."""
    path = str(tmp_path / "plain.cif")
    backend = io.write_structure_file(
        path, [("C", 0.0, 0.0, 0.0), ("O", 1.2, 0.0, 0.0)], name="co")
    assert backend == "native"
    text = open(path, encoding="utf-8").read()
    assert "_cell_length_a" in text and "_atom_site_fract_x" in text
    assert len(io.read_structures(path)[0][0]) == 2


# ------------------------------------------------------------------ helpers
def test_operators_are_compared_as_geometry_not_as_text():
    """One operation has half a dozen spellings, so a string comparison
    answers the wrong question."""
    assert cif_write.operators_match(["x,y,z", "-x+1/2,y,-z"],
                                     ["X, Y, Z", "0.5-x, y, -z"])
    assert not cif_write.operators_match(["x,y,z"], ["x,y,z", "-x,-y,-z"])


def test_labels_fall_back_when_the_file_gave_none_or_repeated_them():
    assert cif_write.site_labels(["C", "C", "O"]) == ["C1", "C2", "O1"]
    assert cif_write.site_labels(["C", "C"], ["A", "A"]) == ["C1", "C2"]
    assert cif_write.site_labels(["C", "O"], ["C12A", "O3"]) == ["C12A", "O3"]


def test_awkward_values_are_quoted():
    assert cif_write._quote("P 21/c") == "'P 21/c'"
    assert cif_write._quote("Pnma") == "Pnma"
    assert cif_write._quote("") == "?"
    assert cif_write._quote("it's").startswith("\n;")


def test_several_crystals_become_several_data_blocks():
    """One data block per structure is ordinary CIF, and it is what a scene
    with two crystals in it means."""
    sc = Scene()
    for path in (FERROCENE, OXIDE):
        atoms, meta = io.read_structures(path)[0]
        sc.add(Structure([a[0] for a in atoms],
                         np.array([a[1:] for a in atoms], dtype=float),
                         metadata=meta),
               name=os.path.basename(path))
    reports = []
    text = cif_write.scene_text(sc.objects, reports=reports)
    assert text.count("\ndata_") + text.startswith("data_") == 2
    assert len(reports) == 2
    assert all(r["policy"] == cif_write.POLICY_ASYMMETRIC for r in reports)


# ------------------------------------------------------------------- the app
def test_the_app_exports_a_cif_through_the_crystal_path(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.open_path(OXIDE)
    path = str(tmp_path / "app.cif")
    backend, n_obj, _n_atoms = win.export_visible(path)
    assert backend == "cif" and n_obj == 1
    assert _facts(path) == _facts(OXIDE)
    # ...and what it decided is in front of the user, not swallowed
    assert "P 42/m n m" in win._cif_export_note
    assert "16 operations" in win._cif_export_note


def test_the_export_note_says_when_a_cell_was_invented():
    pytest.importorskip("PySide6")
    from molom.ui.app import MainWindow
    note = MainWindow.cif_export_note([{"name": "cubane",
                                        "invented_cell": True,
                                        "policy": cif_write.POLICY_P1}])
    assert "invented" in note and "cubane" in note


def test_the_export_note_says_when_occupancies_were_dropped():
    pytest.importorskip("PySide6")
    from molom.ui.app import MainWindow
    note = MainWindow.cif_export_note([{"name": "x", "spacegroup": "P 1",
                                        "symops": 1, "n_sites": 4,
                                        "policy": cif_write.POLICY_CELL,
                                        "occupancy_lost": True}])
    assert "re-derived" in note and "occupancies NOT carried" in note


# ----------------------------------------------- editing a packed crystal
def test_editing_a_packed_crystal_is_flagged():
    """The copies are ordinary independent atoms — measured on ZIF-8, atom 0
    has a copy at index 348 and moving one does not move the other. Until
    editing operates on the CONTENT and re-packs, the honest thing is to say
    so rather than let the structure quietly disagree with itself."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    obj = _load(FERROCENE)
    assert MainWindow.packed_crystal_edit(obj)      # 210 drawn, 42 content

    sc = Scene()
    plain = sc.add(build.cubane(), name="cubane")
    assert not MainWindow.packed_crystal_edit(plain)


def test_the_packed_warning_fires_once_per_object():
    """A message on every drag drowns out everything else the status bar has
    to say."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win._active_obj()
    win.statusBar().clearMessage()
    win._warn_packed_edit(obj)
    assert "PACKED" in win.statusBar().currentMessage()
    win.statusBar().clearMessage()
    win._warn_packed_edit(obj)
    assert win.statusBar().currentMessage() == ""
