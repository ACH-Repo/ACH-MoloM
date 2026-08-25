"""Round 25: edit-mode duplicate, fragment-scoped transforms, and Join."""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.load_default_scene()
    w.show()
    return w


# ------------------------------------------------------- connected fragments
def test_connected_component_stops_at_the_fragment_edge():
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.5, 0, 0),
                              ("O", 9, 9, 9), ("H", 10, 9, 9)])
    s.bonds = [(0, 1, 1), (2, 3, 1)]
    assert s.connected_component([0]) == {0, 1}
    assert s.connected_component([3]) == {2, 3}
    assert [len(f) for f in s.fragments()] == [2, 2]


def test_a_lone_atom_is_its_own_fragment():
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.5, 0, 0), ("Zn", 9, 9, 9)])
    s.bonds = [(0, 1, 1)]
    assert s.connected_component([2]) == {2}


def test_edit_mode_transform_moves_only_the_connected_fragment(win):
    """Christian's case: a metal centre and an unbonded ligand share one
    object; shifting the centre must not drag the ligand."""
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Zn", 0.0, 0.0, 0.0),
                              ("C", 9.0, 0.0, 0.0), ("C", 10.5, 0.0, 0.0)])
    s.bonds = [(1, 2, 1)]
    win._install_structure(s)
    obj = win._active_obj()
    win.viewport.toggle_mode(obj.id)
    win.viewport.set_selection([(obj.id, 0)])
    ligand_before = obj.structure.coords[1].copy()
    win._translate_object(obj, np.array([0.0, 0.0, -5.0]))
    assert obj.structure.coords[0][2] == pytest.approx(-5.0)
    assert obj.structure.coords[1] == pytest.approx(ligand_before)


def test_object_mode_transform_still_moves_everything(win):
    obj = win._active_obj()
    before = obj.structure.coords.copy()
    win.viewport.set_selection([(obj.id, 0)])
    win._translate_object(obj, np.array([1.0, 0.0, 0.0]))
    assert obj.structure.coords == pytest.approx(before + [1.0, 0, 0])


# ------------------------------------------------------------ duplicate in edit
def test_duplicate_in_edit_mode_adds_to_the_same_molecule(win):
    obj = win._active_obj()
    win.viewport.toggle_mode(obj.id)
    n_objects = win.scene.n_objects
    n_atoms = obj.structure.n_atoms
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    win.on_duplicate()
    assert win.scene.n_objects == n_objects, "must NOT spawn a new molecule"
    assert obj.structure.n_atoms == n_atoms + 2


def test_duplicate_in_edit_mode_copies_internal_bonds(win):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0, 0, 0), ("O", 1.2, 0, 0)])
    s.bonds = [(0, 1, 2)]
    win._install_structure(s)
    obj = win._active_obj()
    win.viewport.toggle_mode(obj.id)
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    win.on_duplicate()
    assert obj.structure.n_atoms == 4
    pairs = {frozenset((int(b[0]), int(b[1]))) for b in obj.structure.bonds}
    assert frozenset((2, 3)) in pairs


def test_duplicate_in_object_mode_still_makes_a_new_molecule(win):
    obj = win._active_obj()
    n_objects = win.scene.n_objects
    win.viewport.select_whole_molecules([obj.id])
    win.on_duplicate()
    assert win.scene.n_objects == n_objects + 1


# --------------------------------------------------------------------- join
def test_join_bonds_two_atoms_in_edit_mode(win):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.5, 0, 0)])
    win._install_structure(s)
    obj = win._active_obj()
    win.viewport.toggle_mode(obj.id)
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    win.on_join()
    pairs = {frozenset((int(b[0]), int(b[1]))) for b in obj.structure.bonds}
    assert frozenset((0, 1)) in pairs


def test_join_needs_exactly_two_atoms_in_edit_mode(win):
    obj = win._active_obj()
    win.viewport.toggle_mode(obj.id)
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1), (obj.id, 2)])
    before = len(obj.structure.bonds)
    win.on_join()
    assert len(obj.structure.bonds) == before


def test_join_across_molecules_merges_them(win):
    from molom.core.structure import Structure
    win._install_structure(Structure.from_atoms([("C", 0, 0, 0)], name="a"))
    win._install_structure(Structure.from_atoms([("O", 5, 0, 0)], name="b"))
    a, b = win.scene.objects[-2], win.scene.objects[-1]
    before = win.scene.n_objects
    win.on_merge_ids([a.id, b.id], mode="replace")
    assert win.scene.n_objects == before - 1     # two consumed, one made


def test_join_into_a_new_molecule_keeps_the_originals(win):
    from molom.core.structure import Structure
    win._install_structure(Structure.from_atoms([("C", 0, 0, 0)], name="a"))
    win._install_structure(Structure.from_atoms([("O", 5, 0, 0)], name="b"))
    a, b = win.scene.objects[-2], win.scene.objects[-1]
    before = win.scene.n_objects
    win.on_merge_ids([a.id, b.id], mode="new")
    assert win.scene.n_objects == before + 1
    assert not win.scene.get(a.id).visible      # hidden, not destroyed


def test_join_is_bound_to_j(win):
    assert win.ops.get("join").key == "J"


def test_the_choice_popup_offers_both_join_modes(win):
    from molom.ui.choice_popup import ChoicePopup
    popup = ChoicePopup("Join", [("new", "Into a new molecule", ""),
                                 ("replace", "Replace the originals", "")],
                        win)
    assert popup.list.count() == 2
    from PySide6.QtCore import Qt
    assert popup.list.item(0).data(Qt.UserRole) == "new"
    assert popup.list.item(1).data(Qt.UserRole) == "replace"


# ------------------------------------------- per-element display (MOF work)
def test_hiding_atoms_removes_them_from_drawing_and_picking(win):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0, 0, 0), ("H", 1, 0, 0), ("H", 0, 1, 0)])
    s.bonds = [(0, 1, 1), (0, 2, 1)]
    win._install_structure(s)
    obj = win._active_obj()
    win.viewport.refresh_geometry()
    win.viewport._ensure_pick_data()
    before = len(win.viewport._atom_map)
    obj.atom_hidden.update(obj.element_indices("H"))
    win.viewport.refresh_geometry()
    win.viewport._ensure_pick_data()
    assert len(win.viewport._atom_map) == before - 2
    assert obj.structure.n_atoms == 3, "hidden, not deleted"


def test_per_element_sphere_scale_is_stored_and_read_back(win):
    obj = win._active_obj()
    rows = obj.element_indices("C")
    assert rows
    for i in rows:
        obj.atom_scales[i] = 0.35
    assert obj.atom_scale_for(rows[0]) == pytest.approx(0.35)
    assert obj.atom_scale_for(-1) == pytest.approx(1.0)    # default


def test_element_indices_groups_by_symbol(win):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Zn", 0, 0, 0), ("O", 1, 0, 0), ("Zn", 2, 0, 0)])
    win._install_structure(s)
    obj = win._active_obj()
    assert obj.element_indices("Zn") == [0, 2]
    assert obj.element_indices("O") == [1]


def test_the_row_controls_expose_show_and_size(win):
    """Round 26's claim: an outliner row carries per-element show/hide and
    sphere size, without which a MOF cannot be drawn properly.

    This used to assert `hasattr(control, "show_btn")`, which pinned the
    IMPLEMENTATION - five QToolButtons - rather than the claim, and duly
    broke when the five buttons became five painted squares in one widget
    (the buttons cost 0.9 ms a row to build, which is most of what made
    opening a 300-atom element group take half a second). What matters is
    that both controls are REACHABLE and that they act, so that is what is
    pinned now.
    """
    from molom.ui.outliner import RowControls
    win.outliner.tree.expandAll()
    controls = win.outliner.tree.findChildren(RowControls)
    assert controls
    control = controls[0]
    assert "show" in control.KEYS and "size" in control.KEYS
    # Reachable: each square has its own hit area, and a tooltip saying what
    # its letter means (an unlabelled square is a guess - round 26).
    rects = [control.square_rect(k) for k in control.KEYS]
    assert len({(r.x(), r.y()) for r in rects}) == len(control.KEYS)
    assert all(control._key_at(r.center()) == k
               for k, r in zip(control.KEYS, rects))
    assert control._faces["show"][3] and control._faces["size"][3]


def test_toggling_visibility_from_the_row_control(win):
    from molom.ui.outliner import RowControls
    win.outliner.tree.expandAll()
    control = win.outliner.tree.findChildren(RowControls)[0]
    obj = control._obj
    rows = control._rows
    control._toggle_shown()
    assert all(i in obj.atom_hidden for i in rows)
    control._toggle_shown()
    assert not any(i in obj.atom_hidden for i in rows)
