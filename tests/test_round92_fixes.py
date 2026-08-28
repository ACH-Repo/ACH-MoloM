"""Round 92: two things Christian hit while testing the OWB round trip.

1. Pasting a CAS number showed both chemistry backends complaining about a
   SMILES they had been handed wrongly.
2. Switching an `F m -3 m` fluoride to "asymmetric unit only" moved the
   crystal, and its cell box, to the origin.
"""
import os

import numpy as np
import pytest


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


# ------------------------------------------------------------- pasted text
def test_a_pasted_CAS_number_is_looked_up_not_parsed_as_a_smiles(win,
                                                                 monkeypatch):
    """Christian pasted `2591-17-5` and got "RDKit could not parse SMILES"
    plus "OpenBabel raised OSError" in a dialog - two complaints about a
    question nobody should have asked. A CAS number is a NAME.
    """
    from PySide6.QtWidgets import QApplication
    asked = []
    monkeypatch.setattr(type(win), "on_import_by_name",
                        lambda self, query="": asked.append(query))
    QApplication.clipboard().setText("2591-17-5")
    win.on_paste()
    assert asked == ["2591-17-5"]


def test_a_pasted_NAME_is_looked_up_too(win, monkeypatch):
    from PySide6.QtWidgets import QApplication
    asked = []
    monkeypatch.setattr(type(win), "on_import_by_name",
                        lambda self, query="": asked.append(query))
    QApplication.clipboard().setText("benzoic acid")
    win.on_paste()
    assert asked == ["benzoic acid"]


def test_a_pasted_SMILES_is_still_built_directly(win, monkeypatch):
    """It needs no network and must not be sent to a search."""
    from PySide6.QtWidgets import QApplication
    built, searched = [], []
    monkeypatch.setattr(type(win), "_install_smiles_batch",
                        lambda self, pairs, src, extras=None: built.append(src))
    monkeypatch.setattr(type(win), "on_import_by_name",
                        lambda self, query="": searched.append(query))
    QApplication.clipboard().setText("CC(=O)Oc1ccccc1C(=O)O")
    win.on_paste()
    assert built and not searched


# --------------------------------------------------- the cell pose survives
def _fluoride(win, name="RbF", a=5.64, shift=36.0):
    """A rock-salt fluoride whose ASYMMETRIC UNIT is two atoms - which is the
    whole point: two points cannot fit a rotation."""
    from molom.core.structure import Structure
    from molom.ui.viewport import set_cell_reference
    coords, symbols = [], []
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                coords.append([i * a, j * a, k * a])
                symbols.append("Rb")
    coords.append([a / 2.0, a / 2.0, a / 2.0])
    symbols.append("F")
    s = Structure.from_atoms(
        [(sym, c[0], c[1], c[2]) for sym, c in zip(symbols, coords)],
        name=name)
    s.metadata.update({
        "cell": {"a": a, "b": a, "c": a,
                 "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
        "spacegroup": "F m -3 m", "symops": ["x,y,z"],
        "asym_symbols": ["Rb", "F"],
        "asym_frac": [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    })
    obj = win.scene.add(s)
    # Pin the reference to the CELL FRAME first, then MOVE the crystal - which
    # is what a grab does, and what makes the pose a real translation rather
    # than the identity. Pinning after the move would make the fit trivial and
    # the test would prove nothing.
    set_cell_reference(s)
    s.coords = s.coords + np.array([shift, 0.0, 0.0])
    return obj


def test_a_two_atom_asymmetric_unit_clears_its_stale_reference(win):
    """A reference sample that outlives the atoms it names is worse than
    none: it stays perfectly VALID-looking while describing a structure that
    is no longer there."""
    from molom.ui.viewport import set_cell_reference
    obj = _fluoride(win)
    assert obj.structure.metadata.get("cell_ref_idx")
    obj.structure.symbols = ["Rb", "F"]
    obj.structure.frames = [np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])]
    obj.structure.set_frame(0)
    set_cell_reference(obj.structure)
    assert not obj.structure.metadata.get("cell_ref_idx")


def test_the_asym_round_trip_keeps_the_crystal_where_it_was(win):
    """The report: "Unit cell of RbF jumped from position of RbF to (0,0,0)
    as an anchor. Clicking full unit cell again shifted the full crystal back
    to (0,0,0)." """
    obj = _fluoride(win)
    win.active_id = obj.id
    win.viewport.set_selection([])
    home = obj.structure.centroid().copy()
    assert home[0] > 30.0
    win.on_crystal_view("asym")
    assert obj.structure.n_atoms == 2
    assert obj.structure.centroid()[0] > 30.0, "the asym unit stayed put"
    win.on_crystal_view("cell")
    assert np.allclose(obj.structure.centroid(), home, atol=1e-6)


def test_the_cell_BOX_stays_with_it(win):
    """Same fault, and the half Christian saw first."""
    from molom.ui.viewport import cell_corners_world
    obj = _fluoride(win)
    win.active_id = obj.id
    win.viewport.set_selection([])
    before = cell_corners_world(obj)[0].copy()
    win.on_crystal_view("asym")
    after = cell_corners_world(obj)[0]
    assert np.allclose(before, after, atol=1e-6)


def test_it_survives_repeated_switching(win):
    obj = _fluoride(win)
    win.active_id = obj.id
    win.viewport.set_selection([])
    home = obj.structure.centroid().copy()
    for _ in range(3):
        win.on_crystal_view("asym")
        win.on_crystal_view("cell")
    assert np.allclose(obj.structure.centroid(), home, atol=1e-6)


def test_the_stored_pose_rides_the_savefile(win, tmp_path):
    """It lives in metadata, so it round-trips with everything else there."""
    from molom.core import project
    from molom.core.scene import Scene
    from molom.ui.viewport import stored_cell_pose
    obj = _fluoride(win)
    win.active_id = obj.id
    win.viewport.set_selection([])
    win.on_crystal_view("asym")
    assert stored_cell_pose(obj.structure) is not None
    path = str(tmp_path / "t.molom")
    project.save_project(path, win.scene)
    back = Scene()
    back.from_dict(project.load_project(path)["scene"])
    reloaded = [o for o in back.objects if o.name == "RbF"][0]
    pose = stored_cell_pose(reloaded.structure)
    assert pose is not None
    assert pose[1][0] > 30.0


# ------------------------------------------------ the OWB round-trip is SAID
def _roundtrip(win, tmp_path):
    """A session opened from a structure file, as ORCA Workbench launches it."""
    from molom.core import build as build_mod
    path = str(tmp_path / "mol.xyz")
    seed = win.scene.add(build_mod.cubane())
    win.active_id = seed.id
    win.export_visible(path)
    win.scene.remove(seed.id)
    win.open_path(path)
    obj = win.scene.objects[-1]
    win.active_id = obj.id
    return path, obj


def test_a_round_trip_session_says_so_in_the_viewport(win, tmp_path):
    """Christian: "there is no indication that an edit will be forwarded to
    OWB or that we are currently in a round-trip situation"."""
    assert win.viewport.roundtrip_note == ""
    path, _obj = _roundtrip(win, tmp_path)
    note = win.viewport.roundtrip_note
    assert "Ctrl+S" in note and "mol.xyz" in note


def test_a_project_is_not_a_round_trip(win, tmp_path):
    """Saving MoloM's own document needs no warning that it saves it."""
    from molom.core import project
    _path, _obj = _roundtrip(win, tmp_path)
    assert win.viewport.roundtrip_note
    win.project_path = str(tmp_path / "scene.molom")
    project.save_project(win.project_path, win.scene)
    win.source_path = None
    win._sync_roundtrip_note()
    assert win.viewport.roundtrip_note == ""


def test_saving_flashes_a_confirmation(win, tmp_path):
    """"Ctrl+S should flash a fading out text that informs the user changes
    have been applied" - the status bar is at the far corner of the window and
    a save is exactly when nobody is looking there."""
    _path, _obj = _roundtrip(win, tmp_path)
    assert win.viewport._flash is None
    win.on_save_geometry_back()
    assert win.viewport._flash is not None
    assert "mol.xyz" in win.viewport._flash[0]


def test_the_flash_expires(win, tmp_path):
    _path, _obj = _roundtrip(win, tmp_path)
    win.viewport.flash("x", seconds=0.0)
    win.viewport._flash_tick()
    assert win.viewport._flash is None


# ----------------------------------------------- and the SMILES goes with it
def test_the_derived_SMILES_is_forwarded_and_follows_an_edit(win, tmp_path):
    """The graph is what `structure_to_smiles` reads, so after an edit this is
    the EDITED constitution rather than the one the molecule arrived with."""
    from molom.core import edits
    path, obj = _roundtrip(win, tmp_path)
    before = win._smiles_note()
    assert before.startswith("SMILES: ")
    edits.set_element_adjusted(obj.structure, [0], "N")
    after = win._smiles_note()
    assert after != before and "N" in after
    win.on_save_geometry_back()
    comment = open(path, encoding="utf-8").read().splitlines()[1]
    assert "SMILES:" in comment and "N" in comment


def test_a_CRYSTAL_forwards_no_SMILES(win):
    """A SMILES of a packed cell means nothing, and a wrong one forwarded into
    another program is much worse than none."""
    obj = _fluoride(win)
    win.active_id = obj.id
    assert win._smiles_note() == ""


def test_a_molecule_with_no_bonds_forwards_nothing(win):
    from molom.core.structure import Structure
    obj = win.scene.add(Structure.from_atoms([("C", 0.0, 0.0, 0.0)], name="x"))
    win.active_id = obj.id
    assert win._smiles_note() == ""


# ------------------------------------- a .cif that is not a crystal says so
def test_a_cif_with_no_cell_is_announced(win, tmp_path):
    """Christian opened a `ZIF-8.cif` and got a molecule with a dead crystal
    page and no explanation.

    The file was the problem - OpenBabel had written it with no
    `_cell_length_a` at all, and ASE refuses the same file ("0 lattice
    vectors") - so MoloM was right and merely silent about it. A `.cif` that
    opens with no cell now says why.
    """
    from molom.core import build as build_mod
    obj = win.scene.add(build_mod.cubane())        # no cell of any kind
    assert win.cif_fallback_note(obj, str(tmp_path / "x.cif"))
    # ...and only for a .cif: an .xyz has no crystallography to lose.
    assert win.cif_fallback_note(obj, str(tmp_path / "x.xyz")) is None
    assert win.cif_fallback_note(obj, None) is None


def test_a_real_crystal_says_nothing(win):
    obj = _fluoride(win)
    assert win.cif_fallback_note(obj, "whatever.cif") is None


# --------------------------------- the round trip survives a project SaveAs
def test_saving_a_project_does_not_end_the_round_trip(win, tmp_path):
    """ORCA Workbench is still waiting for that .xyz. Clearing `source_path`
    disabled Ctrl+Alt+S in the one situation it exists for - which is why the
    two shortcuts looked identical."""
    from molom.core import project
    path, _obj = _roundtrip(win, tmp_path)
    win.project_path = str(tmp_path / "scene.molom")
    project.save_project(win.project_path, win.scene)
    win._sync_roundtrip_note()
    assert win.source_path == os.path.abspath(path)
    # ...and the banner names the key that now writes back.
    assert "Ctrl+Alt+S" in win.viewport.roundtrip_note


def test_without_a_project_the_banner_names_Ctrl_S(win, tmp_path):
    _path, _obj = _roundtrip(win, tmp_path)
    note = win.viewport.roundtrip_note
    assert "Ctrl+S" in note and "Ctrl+Alt+S" not in note
