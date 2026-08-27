"""Round 91: moving a crystal is not editing it.

Christian, with a savefile of isostructural alkali fluorides: "I wanted to
change a tick box in the cif props pane for all of them simultaneously =>
Select all, untick draw atoms outside boundary. I think it basically just
selected the last in the list CsF and then some edit happened, which converted
it to P1 and made the tickbox i wanted to change unresponsive."

Reproduced from that file, and the tick box was innocent: **a plain 0.5 A
translation of a whole crystal demoted `F m -3 m` to `P 1`**. `demote_to_p1`
fired on every edit commit without asking what the edit was, and it sets
`cell_frozen` as a side effect (round 52) - which is what killed the control
afterwards.

A space group describes the STRUCTURE, not where it sits in world space. Round
43e already knew "an EDIT is not a rigid motion" and captured the cell pose
before one so the box would not creep; this is the same distinction applied to
the symmetry.
"""
import numpy as np
import pytest

from molom.core import rotations


@pytest.fixture
def crystal():
    """A cubic crystal with real symmetry, built rather than vendored."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    from molom.core.structure import Structure

    win = MainWindow()
    # Rock salt, one cell: the same shape as the fluorides in the report.
    a = 4.0
    coords, symbols = [], []
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                coords.append([i * a, j * a, k * a])
                symbols.append("Na")
    coords.append([a / 2.0, a / 2.0, a / 2.0])
    symbols.append("Cl")
    s = Structure.from_atoms(
        [(sym, c[0], c[1], c[2]) for sym, c in zip(symbols, coords)],
        name="salt")
    s.metadata.update({
        "cell": {"a": a, "b": a, "c": a,
                 "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
        "spacegroup": "F m -3 m",
        "symops": ["x,y,z"],
    })
    obj = win.scene.add(s)
    win.active_id = obj.id
    return win, obj


def _group(obj):
    return (obj.structure.metadata or {}).get("spacegroup")


def _frozen(obj):
    return bool((obj.structure.metadata or {}).get("cell_frozen"))


def _select_all(win, obj):
    win.viewport.set_selection(
        [(obj.id, i) for i in range(obj.structure.n_atoms)])


def test_a_rigid_TRANSLATION_leaves_the_space_group_alone(crystal):
    """The bug as reported: a crystal that was only moved came back as P1."""
    win, obj = crystal
    _select_all(win, obj)
    win.begin_model_edit()
    obj.structure.coords = obj.structure.coords + np.array([0.5, 0.0, 0.0])
    win._on_edit_committed()
    assert _group(obj) == "F m -3 m"
    assert not _frozen(obj), "and the cell is not frozen, so the ticks live"


def test_a_rigid_ROTATION_leaves_it_alone_too(crystal):
    win, obj = crystal
    _select_all(win, obj)
    win.begin_model_edit()
    rot = rotations.axis_angle_mat3(np.array([0.0, 0.0, 1.0]), 0.7)
    obj.structure.coords = rotations.rotate_points_about(
        obj.structure.coords, rot, obj.structure.centroid())
    win._on_edit_committed()
    assert _group(obj) == "F m -3 m"
    assert not _frozen(obj)


def test_moving_ONE_atom_still_demotes(crystal):
    """The distinction has to cut both ways: dragging an atom out of its site
    really does break the symmetry, and P1 is the honest answer."""
    win, obj = crystal
    _select_all(win, obj)
    win.begin_model_edit()
    coords = obj.structure.coords.copy()
    coords[0] += np.array([0.35, 0.0, 0.0])
    obj.structure.coords = coords
    win._on_edit_committed()
    assert _group(obj) == "P 1"
    assert _frozen(obj)


def test_a_CHEMISTRY_edit_still_demotes(crystal):
    """Changing an element changes what the structure IS, however little the
    atoms moved."""
    from molom.core import edits
    win, obj = crystal
    _select_all(win, obj)
    win.begin_model_edit()
    edits.set_element(obj.structure, [0], "K")
    win._on_edit_committed()
    assert _group(obj) == "P 1"


def test_the_rigidity_test_refuses_to_guess(crystal):
    """With nothing captured to compare against, the conservative path (treat
    it as a real edit) is what happens - a wrongly KEPT space group would be
    expanded into a structure that is not there."""
    win, obj = crystal
    win._coords_before_edit = None
    assert win._edit_was_rigid(obj) is False


def test_the_capture_is_consumed_so_it_cannot_go_stale(crystal):
    """Read once and cleared: a leftover snapshot from an earlier gesture
    would let a later real edit be mistaken for a rigid one."""
    win, obj = crystal
    win.begin_model_edit()
    assert win._coords_before_edit is not None
    assert win._edit_was_rigid(obj) is True
    assert win._coords_before_edit is None
    assert win._edit_was_rigid(obj) is False


def test_the_savefile_that_was_reported_is_readable(tmp_path):
    """The file itself, if it is on this machine - four fluorides still
    `F m -3 m` and CsF already demoted, which is the damage this fixes."""
    import os
    path = os.path.expanduser(r"~\\Desktop\\MF.molom")
    if not os.path.exists(path):
        pytest.skip("Christian's savefile is not on this machine")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.open_path(path)
    groups = [(o.name, (o.structure.metadata or {}).get("spacegroup"))
              for o in win.scene.objects
              if (o.structure.metadata or {}).get("cell")]
    assert len(groups) >= 5
    # The record of the bug: one of them is P1 and its siblings are not.
    assert sum(1 for _n, g in groups if g == "P 1") >= 1
