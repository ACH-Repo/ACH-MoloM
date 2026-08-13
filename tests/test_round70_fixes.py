"""Round 70: the chase regression, and the symmetry modifier made legible.

Christian, 2026-08-12:
* "turning only without acceleration now moves the entire mol. and it is moving
  fast" - a regression from round 69.
* "no bonds are shown once a symmetry modifier is added"
* "the boundary bonds modifier doesn't add at all"
* "I have no idea what the cell/box limits are"
"""

import numpy as np
import pytest

from molom.core import celledit


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


# ------------------------------------------------- the chase regression
def test_pure_steering_does_not_translate_the_cockpit(win):
    """An aircraft turns about its COCKPIT. Rotating about the centroid swings
    the cockpit atom along an arc, and since the camera tracks that atom the
    whole molecule then sweeps across the frame under nothing but a turn."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    start = vp._cockpit_pos(obj).copy()
    vp._fly["aim"].offset = np.array([60.0, 0.0])
    for _ in range(180):
        vp._fly_tick(dt=1.0 / 60.0)
    moved = float(np.linalg.norm(vp._cockpit_pos(obj) - start))
    assert moved < 1e-6, "steering translated the ship by {:.4f} A".format(moved)


def test_the_ship_still_turns(win):
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    vp._fly["aim"].offset = np.array([60.0, 0.0])
    for _ in range(60):
        vp._fly_tick(dt=1.0 / 60.0)
    assert not np.allclose(obj.orientation, [1, 0, 0, 0], atol=1e-6)


def test_the_origin_travels_with_the_atoms(win):
    """The centroid is a point ON the molecule. Rotating the atoms about the
    cockpit and leaving it behind desynchronises the cell box and every later
    transform from the atoms they describe."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    vp._fly["aim"].offset = np.array([60.0, 0.0])
    for _ in range(90):
        vp._fly_tick(dt=1.0 / 60.0)
    centroid = np.asarray(obj.structure.coords, dtype=float).mean(axis=0)
    assert np.allclose(obj.origin, centroid, atol=1e-6)


def test_first_person_pivots_about_the_cockpit_TOO(win):
    """This round asserted the opposite, on the reasoning that inside the
    cockpit the centroid IS the eye. It is not: `obj.origin` is only the
    centroid until something moves it, and round 71 measured 8.10 A of drift on
    a real file. So first person turned about a point out in empty space and
    threw itself off the ship. Both modes pivot on the cockpit now.

    Note the shape of the test that shipped the bug: it asserted a LINE OF
    SOURCE, so it passed for as long as the code said what it said, which is
    not the same as the code being right.
    """
    obj = win._active_obj()
    vp = win.viewport
    obj.origin = np.asarray(obj.origin, dtype=float) + np.array([8.0, 0.0, 0.0])
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    before = np.asarray(obj.structure.coords[0], dtype=float).copy()
    vp._fly["aim"].offset = np.array([60.0, 20.0])
    for _ in range(90):
        vp._fly_tick(dt=1.0 / 60.0)
    moved = float(np.linalg.norm(
        np.asarray(obj.structure.coords[0], dtype=float) - before))
    assert moved < 1e-9, "a pure turn dragged the cockpit atom along an arc"


# ------------------------------------------------- the symmetry modifier
def test_a_symmetry_modifier_keeps_the_bonds(win):
    """It used to return an EMPTY bond list, so adding it dropped every bond in
    the picture - including the ones on the asymmetric unit you started from -
    and the molecule fell apart into loose spheres."""
    obj = win._active_obj()
    before = len(obj.evaluated()[2])
    assert before > 0
    win.on_add_modifier("symmetry")
    assert len(obj.evaluated()[2]) > 0, "the symmetry modifier removed the bonds"


def test_the_bonds_scale_with_the_copies(win):
    obj = win._active_obj()
    win.on_add_modifier("symmetry")
    one = obj.evaluated()
    mod = [m for m in obj.modifiers if m.kind == "symmetry"][0]
    mod.symops = ["x,y,z", "-x,-y,-z"]           # add an inversion centre
    two = obj.evaluated()
    assert len(two[0]) > len(one[0]), "the inversion made no copy"
    assert len(two[2]) > len(one[2]), "the copy came out with no bonds"


def test_the_invented_cell_is_a_REAL_cell(win):
    """A cell known only to the modifier is one the viewport cannot draw a box
    for and the crystal page cannot report - which is why "I have no idea what
    the cell/box limits are"."""
    obj = win._active_obj()
    assert celledit.cell_of(obj.structure) is None
    win.on_add_modifier("symmetry")
    assert celledit.cell_of(obj.structure) is not None
    assert win.viewport.show_cell is True


def test_the_boundary_modifier_can_be_added_after_symmetry(win):
    """It refused because it reads the cell from METADATA, where the invented
    one never was: "the boundary bonds modifier doesn't add at all"."""
    obj = win._active_obj()
    win.on_add_modifier("symmetry")
    win.on_add_modifier("boundary")
    assert "boundary" in [m.kind for m in obj.modifiers]


def test_an_imported_cell_is_not_overwritten(win):
    """Only an INVENTED cell is written; a real one must be left exactly as the
    file wrote it."""
    obj = win._active_obj()
    win.on_suggest_cell()
    win.on_apply_cell()
    original = celledit.cell_of(obj.structure).to_dict()
    win.on_add_modifier("symmetry")
    assert celledit.cell_of(obj.structure).to_dict() == original
