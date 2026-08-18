"""Round 75: computed layers on a molecule, and what an edit does to them.

Christian's design, 2026-08-17. The heart of it is that an isosurface and a set
of normal modes fail DIFFERENTLY, so one "invalidate" flag would be wrong for
one of them:

* an isosurface "cannot be retained the moment anything changes about a mol
  even slightly. And it should be pretty easy to recalculate if it is lost" ->
  dropped;
* modes: "an edit should not get rid of modes, only declare itself as no longer
  physical in the GUI and in any potential export" -> kept and flagged, because
  the use case is a deliberately inaccurate comparison figure.

Plus overwrite protection modelled on ORCA Workbench (a tick box that must be
cleared first), on the objects that need it and no others; and the outliner
colour swap - hidden atoms go to diagonal stripes so that red is free for the
state that is actually a correctness problem.
"""

import numpy as np
import pytest

from molom.core import attachments as A
from molom.core.scene import Scene
from molom.core.structure import Structure


def _obj(scene=None, n=3):
    scene = scene or Scene()
    return scene, scene.add(Structure(["C"] * n, [np.zeros((n, 3))]), name="m")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


# ------------------------------------------------------- the two policies
def test_a_volatile_layer_is_dropped_by_any_edit():
    """An isosurface computed for one conformer describes no other, and is
    cheap to rebuild - so it goes, rather than drawing a confident lie."""
    _s, obj = _obj()
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    dropped, flagged = A.note_edit(obj, A.KIND_CHEMISTRY)
    assert dropped == ["iso"] and flagged == []
    assert "iso" not in A.attachments_of(obj)


def test_a_volatile_layer_goes_on_a_GEOMETRY_edit_too():
    """"the moment anything changes about a mol even slightly"."""
    _s, obj = _obj()
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    assert A.note_edit(obj, A.KIND_GEOMETRY)[0] == ["iso"]


def test_a_fragile_layer_is_KEPT_and_flagged():
    """Throwing away a twenty-minute calculation because somebody swapped an
    oxygen is the worse failure - the comparison figure is a real use."""
    _s, obj = _obj()
    A.attach(obj, A.Attachment("modes", "Modes"))
    dropped, flagged = A.note_edit(obj, A.KIND_CHEMISTRY)
    assert dropped == [] and flagged == ["modes"]
    assert "modes" in A.attachments_of(obj)
    assert A.unphysical(obj)


def test_a_fragile_layer_survives_a_GEOMETRY_edit_unflagged():
    """Moving a whole molecule is a rigid placement - the modes travel with it
    and stay exactly as valid. Flagging here would put a warning on the
    commonest gesture in the program, which is a warning nobody reads."""
    _s, obj = _obj()
    A.attach(obj, A.Attachment("modes", "Modes"))
    assert A.note_edit(obj, A.KIND_GEOMETRY) == ([], [])
    assert not A.unphysical(obj)


def test_flagging_is_not_repeated():
    _s, obj = _obj()
    A.attach(obj, A.Attachment("modes", "Modes"))
    A.note_edit(obj, A.KIND_CHEMISTRY)
    assert A.note_edit(obj, A.KIND_CHEMISTRY)[1] == []


def test_the_stale_note_names_what_stopped_being_physical():
    """It feeds the tooltip, the status bar and any export - Christian asked
    for the state to declare itself "in the GUI and in any potential export"."""
    _s, obj = _obj()
    assert A.describe_stale(obj) is None
    A.attach(obj, A.Attachment("modes", "Modes"))
    A.note_edit(obj, A.KIND_CHEMISTRY)
    note = A.describe_stale(obj)
    assert "Modes" in note and "edited" in note


# ------------------------------------------------------------ the lock
def test_only_objects_that_carry_something_are_protected():
    """"Only add overwrite protections to outliner objects that actually
    require them." A lock on an object with nothing to lose is noise, and
    noise is what teaches people to click through warnings."""
    _s, obj = _obj()
    assert not A.needs_protection(obj) and not A.is_locked(obj)
    A.attach(obj, A.Attachment("modes", "Modes"))
    assert A.needs_protection(obj) and A.is_locked(obj)


def test_the_lock_goes_with_the_last_attachment():
    _s, obj = _obj()
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    assert A.is_locked(obj)
    A.detach(obj, "iso")
    assert not A.is_locked(obj) and not A.needs_protection(obj)


def test_an_edit_that_empties_the_layers_unlocks_it():
    _s, obj = _obj()
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    A.note_edit(obj, A.KIND_CHEMISTRY)
    assert not A.is_locked(obj)


# ---------------------------------------------------- riding the checklist
def test_attachments_survive_snapshot_and_restore():
    """Round 31's four-place checklist, honoured on arrival this time: a field
    missing from `restore` is thrown away by every undo AND by every cancelled
    viewport gesture, which reads as the feature being broken."""
    scene, obj = _obj()
    A.attach(obj, A.Attachment("modes", "Modes", detail="24 modes",
                               toggleable=False))
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE,
                               visible=False, source="mopac"))
    scene.restore(scene.snapshot())
    back = A.attachments_of(scene.objects[0])
    assert sorted(back) == ["iso", "modes"]
    assert back["modes"].toggleable is False
    assert back["modes"].detail == "24 modes"
    assert back["iso"].visible is False
    assert back["iso"].source == "mopac"
    assert back["iso"].policy == A.POLICY_VOLATILE
    assert scene.objects[0].edit_locked is True


def test_the_stale_flag_itself_round_trips():
    scene, obj = _obj()
    A.attach(obj, A.Attachment("modes", "Modes"))
    A.note_edit(obj, A.KIND_CHEMISTRY)
    scene.restore(scene.snapshot())
    assert A.unphysical(scene.objects[0])


# ------------------------------------------------- through the application
def test_modes_arriving_protect_the_molecule(win):
    from molom.core import vibrations as V
    import os
    obj = win._active_obj()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "mopac_pm7_water_force.out")
    modes = V.parse_mopac_frequencies(open(path, encoding="utf-8",
                                           errors="replace").read())
    win.set_modes(obj, modes)
    assert A.is_locked(obj)
    att = A.attachments_of(obj)["modes"]
    assert att.policy == A.POLICY_FRAGILE
    # A tick box would have nothing to do: modes are a data source for the
    # animation, not a layer painted over the molecule.
    assert att.toggleable is False


def test_a_locked_molecule_REFUSES_a_real_element_change(win):
    """The gesture, not the hook - round 73's lesson. `apply_element` is the
    one path shared by typing, the periodic table and the dialog."""
    from molom.core import vibrations as V
    import os
    obj = win._active_obj()
    vp = win.viewport
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "mopac_pm7_water_force.out")
    win.set_modes(obj, V.parse_mopac_frequencies(
        open(path, encoding="utf-8", errors="replace").read()))
    vp.set_mode("edit", obj.id)
    before = list(obj.structure.symbols)
    win._confirm_unlock = lambda o: False          # the user cancels
    vp.set_selection([(obj.id, 0)])
    vp.apply_element("S")
    assert list(obj.structure.symbols) == before
    assert A.is_locked(obj) and not A.unphysical(obj)


def test_agreeing_lets_the_edit_through_and_flags_it(win):
    from molom.core import vibrations as V
    import os
    obj = win._active_obj()
    vp = win.viewport
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "mopac_pm7_water_force.out")
    win.set_modes(obj, V.parse_mopac_frequencies(
        open(path, encoding="utf-8", errors="replace").read()))
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    vp.set_mode("edit", obj.id)
    win._confirm_unlock = lambda o: True
    vp.set_selection([(obj.id, 0)])
    vp.apply_element("S")
    assert obj.structure.symbols[0] == "S"
    assert "iso" not in A.attachments_of(obj)      # volatile: gone
    assert "modes" in A.attachments_of(obj)        # fragile: kept
    assert A.unphysical(obj)
    assert len(win._modes.get(obj.id) or []) == 3  # the data itself survives


def test_it_asks_once_not_once_per_edit(win):
    """Agreeing clears the lock, so the rest of an editing session is
    uninterrupted. A dialog per keystroke is a dialog people learn to dismiss
    without reading."""
    from molom.core import vibrations as V
    import os
    obj = win._active_obj()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "mopac_pm7_water_force.out")
    win.set_modes(obj, V.parse_mopac_frequencies(
        open(path, encoding="utf-8", errors="replace").read()))
    asked = []
    win._confirm_unlock = lambda o: (asked.append(1), True)[1]
    assert win.begin_chemistry_edit() is True
    assert win.begin_chemistry_edit() is True
    assert len(asked) == 1


def test_UNDO_restores_a_molecule_whose_layers_are_intact(win):
    """The flag is set AFTER the undo snapshot, so Ctrl+Z gives back a
    molecule that is not still marked unphysical."""
    from molom.core import vibrations as V
    import os
    obj = win._active_obj()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "mopac_pm7_water_force.out")
    win.set_modes(obj, V.parse_mopac_frequencies(
        open(path, encoding="utf-8", errors="replace").read()))
    win._confirm_unlock = lambda o: True
    win.begin_chemistry_edit()
    assert A.unphysical(win._active_obj())
    win.on_undo()
    assert not A.unphysical(win._active_obj())


def test_a_geometry_modal_is_not_gated(win):
    """`on_model_edit_begin` still goes straight to `begin_model_edit`: a
    dialog on every grab would be intolerable, and a rigid move does not
    invalidate anything."""
    assert win.viewport.on_model_edit_begin == win.begin_model_edit
    assert win.viewport.on_edit_begin == win.begin_chemistry_edit


# ---------------------------------------------------------- the outliner
def test_the_row_appears_only_where_there_is_something_to_show(win):
    from molom.ui.outliner import AttachmentControls
    obj = win._active_obj()
    win.outliner.sync(win.scene, win.active_id)
    tree = win.outliner.tree
    top = tree.topLevelItem(0)
    assert not any(isinstance(tree.itemWidget(top.child(i), 0),
                              AttachmentControls)
                   for i in range(top.childCount()))
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    win.outliner.sync(win.scene, win.active_id)
    top = win.outliner.tree.topLevelItem(0)
    rows = [tree.itemWidget(top.child(i), 0) for i in range(top.childCount())]
    assert any(isinstance(r, AttachmentControls) for r in rows)


def test_the_row_sits_ABOVE_the_element_groups(win):
    """Christian's sketch puts it there, and it is a per-molecule state - it
    would read as belonging to an element if it came after them."""
    from molom.ui.outliner import AttachmentControls
    obj = win._active_obj()
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    win.outliner.sync(win.scene, win.active_id)
    tree = win.outliner.tree
    top = tree.topLevelItem(0)
    kinds = [type(tree.itemWidget(top.child(i), 0)).__name__
             for i in range(top.childCount())]
    assert kinds[0] == "AttachmentControls"


def test_a_non_toggleable_layer_gets_a_label_not_a_dead_tick(win):
    from PySide6.QtWidgets import QCheckBox, QLabel
    from molom.ui.outliner import AttachmentControls
    obj = win._active_obj()
    A.attach(obj, A.Attachment("modes", "Modes", toggleable=False))
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    win.outliner.sync(win.scene, win.active_id)
    tree = win.outliner.tree
    top = tree.topLevelItem(0)
    row = [tree.itemWidget(top.child(i), 0) for i in range(top.childCount())
           if isinstance(tree.itemWidget(top.child(i), 0),
                         AttachmentControls)][0]
    widgets = {}
    for i in range(row.layout().count()):
        w = row.layout().itemAt(i).widget()
        widgets[w.text()] = type(w)
    assert widgets["Lock"] is QCheckBox
    assert widgets["Density"] is QCheckBox
    assert widgets["Modes"] is QLabel


def test_hidden_is_STRIPES_and_unphysical_is_RED(win):
    """The swap Christian asked for: red is the loudest mark the outliner has,
    and hiding a few hydrogens is a routine display choice rather than a
    problem. Red now belongs to the state that IS one."""
    from PySide6.QtWidgets import QStyleOptionViewItem
    from PySide6.QtGui import QPalette
    from molom.ui.outliner import ROLE_HIDDEN, ROLE_UNPHYSICAL
    obj = win._active_obj()
    obj.hide_atoms([0])
    win.outliner.sync(win.scene, win.active_id)
    tree = win.outliner.tree
    index = tree.indexFromItem(tree.topLevelItem(0), 0)
    assert index.data(ROLE_HIDDEN) is True
    assert index.data(ROLE_UNPHYSICAL) is None
    option = QStyleOptionViewItem()
    win.outliner._hidden_delegate.initStyleOption(option, index)
    assert option.palette.color(QPalette.Text) != win.outliner.HIDDEN_MARK

    A.attach(obj, A.Attachment("modes", "Modes"))
    A.note_edit(obj, A.KIND_CHEMISTRY)
    win.outliner.sync(win.scene, win.active_id)
    index = tree.indexFromItem(tree.topLevelItem(0), 0)
    assert index.data(ROLE_UNPHYSICAL) is True
    option = QStyleOptionViewItem()
    win.outliner._hidden_delegate.initStyleOption(option, index)
    assert option.palette.color(QPalette.Text) == win.outliner.HIDDEN_MARK


def test_the_tick_box_drives_visibility(win):
    obj = win._active_obj()
    A.attach(obj, A.Attachment("iso", "Density", policy=A.POLICY_VOLATILE))
    win.on_attachment_toggled(obj.id, "iso", False)
    assert A.attachments_of(obj)["iso"].visible is False
    assert A.visible_attachments(obj) == []
    win.on_attachment_toggled(obj.id, "iso", True)
    assert [a.key for a in A.visible_attachments(obj)] == ["iso"]


def test_the_lock_box_drives_the_lock(win):
    obj = win._active_obj()
    A.attach(obj, A.Attachment("modes", "Modes"))
    win.on_attachment_lock_toggled(obj.id, False)
    assert not A.is_locked(obj)
    win.on_attachment_lock_toggled(obj.id, True)
    assert A.is_locked(obj)


def test_only_the_permission_gate_reads_on_edit_begin():
    """`on_edit_begin` changed meaning this round - from "take an undo
    snapshot" to "may I make a chemistry edit?" - and the callers that wanted
    only the snapshot had to move to `on_model_edit_begin`.

    Two had not: grabbing a CAMERA and trucking one both went through it, so a
    molecule's overwrite lock refused to let you move the camera, and popped a
    dialog to say so (which hung the suite, since a modal has nobody to click
    it). Pinned structurally, because the next person to add a gesture will
    reach for the same hook.
    """
    import re
    src = open("molom/ui/viewport.py", encoding="utf-8").read()
    uses = [m for m in re.findall(r"^.*self\.on_edit_begin.*$", src,
                                  re.MULTILINE)
            if "self.on_edit_begin = None" not in m]
    # Only `_begin_edit`'s two lines may touch it.
    assert len(uses) == 2, uses
    assert all("return self.on_edit_begin() is not False" in u
               or "if self.on_edit_begin is None" in u for u in uses), uses


def test_a_camera_grab_is_not_gated_by_a_molecules_lock(win):
    """The gesture that found it: a locked molecule must not stop you moving a
    camera, which is not a chemistry edit and not even the same object."""
    from molom.core import attachments as A
    obj = win._active_obj()
    A.attach(obj, A.Attachment("modes", "Modes"))
    assert A.is_locked(obj)
    win.on_place_camera()
    win.leave_camera()
    vp = win.viewport
    vp.select_camera(win.scene.cameras[0].id)

    def refuse(_o):
        raise AssertionError("a camera grab asked to unlock a molecule")

    win._confirm_unlock = refuse
    assert vp.start_camera_grab() is True
    vp.finish_camera_drag(commit=False)
