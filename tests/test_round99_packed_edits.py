"""Round 99: A3 - a geometry edit to a PACKED crystal reaches its copies.

A crystal is drawn with boundary copies: an atom on a cell face appears
twice, one on a corner eight times, as independent entries in the atom list.
Round 54 taught an ELEMENT change and a DELETE to reach every image
(`packing.images_of`); a geometry edit never learned, so moving one atom left
its seven copies where they were and the cell disagreed with itself across
its own faces. Round 50 flagged it with a message and it stood on the docket
as A3 ever since.

The measurement it was fixed against: on ferrocene, content atom 0 is drawn
EIGHT times, and a 0.5 A drag moved exactly one of them.
"""
import os

import numpy as np
import pytest

from molom.core import cif as cif_mod
from molom.core import packing as packing_mod

HERE = os.path.dirname(__file__)
FERROCENE = os.path.join(HERE, "data", "cod_2101932_ferrocene.cif")


@pytest.fixture
def bench():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win.scene.objects[-1]
    win.active_id = obj.id
    return win, obj


def _move(win, obj, rows, delta):
    """What every geometry gesture ultimately does: `begin_model_edit`, move
    some atoms, commit."""
    win.begin_model_edit()
    coords = np.array(obj.structure.coords, copy=True)
    for row in rows:
        coords[row] = coords[row] + np.asarray(delta, dtype=float)
    obj.structure.coords = coords
    win._on_edit_committed()


def _groups(obj):
    return packing_mod.image_groups(obj.structure.metadata,
                                    obj.structure.n_atoms)


def _multi(obj):
    """A content atom that really is drawn more than once."""
    for content, rows in sorted(_groups(obj).items()):
        if len(rows) > 1:
            return content, rows
    raise AssertionError("this fixture has no boundary copies")


def _worst_disagreement(obj):
    """How far two images of one atom are from being exactly one lattice
    vector apart. Zero is a cell that agrees with itself; that IS the
    property A3 is about, and it is measurable without knowing which gesture
    was made."""
    meta = obj.structure.metadata
    cell = cif_mod.Cell.from_dict(meta["cell"])
    matrix = np.asarray(cell.matrix(), dtype=float)
    inverse = np.linalg.inv(matrix)
    coords = np.asarray(obj.structure.coords, dtype=float)
    worst = 0.0
    for rows in _groups(obj).values():
        frac = coords[rows] @ inverse
        for other in frac[1:]:
            delta = other - frac[0]
            delta = delta - np.round(delta)          # modulo the lattice
            worst = max(worst, float(np.linalg.norm(delta @ matrix)))
    return worst


# --------------------------------------------------------------- the fixture
def test_ferrocene_really_is_drawn_with_copies(bench):
    """The premise. Without it the rest of this file proves nothing."""
    _win, obj = bench
    assert obj.structure.metadata.get("packed")
    assert obj.structure.n_atoms == 210
    assert int(obj.structure.metadata["cell_content"]) == 42
    content, rows = _multi(obj)
    assert len(rows) == 8, "content atom {} is drawn 8 times".format(content)


def test_an_untouched_cell_agrees_with_itself(bench):
    _win, obj = bench
    assert _worst_disagreement(obj) < 1e-9


# ------------------------------------------------------------------- A3
def test_moving_one_atom_moves_every_image_of_it(bench):
    """The bug, as an assertion. Before this it moved exactly one."""
    win, obj = bench
    content, rows = _multi(obj)
    before = np.array(obj.structure.coords, copy=True)
    _move(win, obj, [rows[0]], [0.5, 0.0, 0.0])
    after = np.asarray(obj.structure.coords)
    moved = set(np.flatnonzero(
        np.linalg.norm(after - before, axis=1) > 1e-9).tolist())
    assert moved == set(rows)
    for row in rows:
        assert np.allclose(after[row] - before[row], [0.5, 0.0, 0.0])


def test_the_cell_still_agrees_with_itself_afterwards(bench):
    """The property that matters, stated without reference to which atoms
    moved: two images of one atom are exactly one lattice vector apart."""
    win, obj = bench
    _content, rows = _multi(obj)
    _move(win, obj, [rows[0]], [0.37, -0.21, 0.08])
    assert _worst_disagreement(obj) < 1e-9


def test_moving_a_whole_molecule_keeps_it_agreeing(bench):
    """The ordinary gesture - select a molecule, grab it."""
    win, obj = bench
    fragment = sorted(obj.structure.connected_component([0]))
    assert len(fragment) > 5
    _move(win, obj, fragment, [0.3, 0.3, 0.0])
    assert _worst_disagreement(obj) < 1e-9


def test_the_delta_is_exact_because_images_differ_by_a_LATTICE_VECTOR(bench):
    """Why the same delta is right rather than an approximation: a lattice
    translation commutes with a Cartesian displacement, so applying one
    delta to every image keeps them exactly one lattice vector apart however
    large the move."""
    win, obj = bench
    _content, rows = _multi(obj)
    _move(win, obj, [rows[0]], [12.5, -7.25, 3.125])
    assert _worst_disagreement(obj) < 1e-9


# ------------------------------------------------- what must NOT change
def test_a_rigid_move_of_the_whole_crystal_is_still_rigid(bench):
    """Every image already moved by the same delta, so the sync is a no-op -
    and round 91's rule stands: a space group describes the STRUCTURE, not
    where it sits in world space."""
    win, obj = bench
    was = obj.structure.metadata.get("spacegroup")
    _move(win, obj, range(obj.structure.n_atoms), [1.0, -2.0, 0.5])
    assert obj.structure.metadata.get("spacegroup") == was
    assert not obj.structure.metadata.get("cell_frozen")
    assert _worst_disagreement(obj) < 1e-9


def test_editing_one_atom_still_demotes_to_P1(bench):
    """Moving an atom out of its site IS an edit to the structure, and the
    demotion is round 52's. Reaching the copies must not hide that."""
    win, obj = bench
    _content, rows = _multi(obj)
    _move(win, obj, [rows[0]], [0.5, 0.0, 0.0])
    assert obj.structure.metadata.get("spacegroup") == "P 1"


def test_an_unpacked_structure_is_left_alone(bench):
    """No `content_of` means nothing is known about copies, and guessing
    would move atoms nobody touched. The asymmetric-unit view drops the map
    (round 83), which is exactly that case."""
    win, obj = bench
    win.on_crystal_view("asym")
    assert _groups(obj) == {}
    before = np.array(obj.structure.coords, copy=True)
    _move(win, obj, [0], [0.4, 0.0, 0.0])
    after = np.asarray(obj.structure.coords)
    moved = np.flatnonzero(np.linalg.norm(after - before, axis=1) > 1e-9)
    assert list(moved) == [0]


def test_adding_or_removing_atoms_is_left_to_the_delete_path(bench):
    """A changed atom COUNT is a different question, and `images_of` already
    answers it where a delete is made. Comparing coordinates across it would
    compare different atoms."""
    win, obj = bench
    win.begin_model_edit()
    before = obj.structure.n_atoms
    obj.delete_atoms([0])
    touched, disagreed = win._sync_packed_images(obj)
    assert (touched, disagreed) == (0, 0)
    assert obj.structure.n_atoms == before - 1


def test_two_copies_pulled_apart_are_reported_not_averaged(bench):
    """The one case with no right answer: the user has moved two images of
    ONE atom differently. The first move wins - averaging would be a third
    answer nobody asked for - and it is said out loud, because it is the only
    outcome here where atoms end up somewhere nobody put them."""
    win, obj = bench
    _content, rows = _multi(obj)
    win.begin_model_edit()
    coords = np.array(obj.structure.coords, copy=True)
    coords[rows[0]] += np.array([0.5, 0.0, 0.0])
    coords[rows[1]] += np.array([0.0, 0.5, 0.0])
    obj.structure.coords = coords
    win._on_edit_committed()
    message = win.statusBar().currentMessage()
    assert "boundary copies" in message and "apart" in message


def test_the_plain_case_says_how_many_copies_came_along(bench):
    """A control that quietly moves seven atoms you did not select has to say
    so - round 91b's rule for the crystal page, applied to an edit."""
    win, obj = bench
    _content, rows = _multi(obj)
    win.statusBar().clearMessage()
    touched, disagreed = 0, 0
    win.begin_model_edit()
    coords = np.array(obj.structure.coords, copy=True)
    coords[rows[0]] += np.array([0.5, 0.0, 0.0])
    obj.structure.coords = coords
    touched, disagreed = win._sync_packed_images(obj)
    win._report_packed_images(obj, touched, disagreed)
    assert touched == len(rows) - 1
    assert "boundary copy" in win.statusBar().currentMessage()


# --------------------------------------------------------- the core helper
def test_image_groups_is_every_image_of_every_atom(bench):
    _win, obj = bench
    groups = _groups(obj)
    mapping = obj.structure.metadata["content_of"]
    assert sum(len(rows) for rows in groups.values()) == obj.structure.n_atoms
    for content, rows in groups.items():
        assert all(int(mapping[row]) == content for row in rows)
    # ...and it agrees with `images_of`, which answers the same question for
    # one selection.
    content, rows = _multi(obj)
    assert packing_mod.images_of(obj.structure.metadata, [rows[0]],
                                 obj.structure.n_atoms) == sorted(rows)


def test_image_groups_is_empty_without_a_mapping():
    """Empty means "nothing known about copies", which is not the same as
    "no copies" - and the caller has to be able to tell them apart."""
    assert packing_mod.image_groups({}, 10) == {}
    assert packing_mod.image_groups({"content_of": [0, 0, 1]}, 10) == {}
    assert packing_mod.image_groups({"content_of": [0, 0, 1]}, 3) == {
        0: [0, 1], 1: [2]}
