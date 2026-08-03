"""Round 31: hiding that survives, mode filtering, and align preview.

Three separate reports from 2026-08-03:

  * "The hiding function is broken. I click the global hide/show tick and it
    disappears for a split second then pops back in again."
  * amplitude defaults, a type-in box, and the stutter while dragging;
    sorting modes by intensity and filtering by wavenumber.
  * roadmap 1f, reported twice: align must PREVIEW, then confirm.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import vibrations
from molom.core.scene import Scene
from molom.core.structure import Structure

FREQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "orca_freq_h3po4.out")


def _mol(name="m", n=4):
    return Structure.from_atoms(
        [("C", float(i), 0.0, 0.0) for i in range(n)], name=name)


# ------------------------------------------------------- hiding, in core
def test_hidden_atoms_survive_a_snapshot():
    """The bug: `atom_hidden` and `atom_scales` arrived in round 26 and were
    never added to `snapshot()`, so every undo quietly un-hid everything."""
    scene = Scene()
    obj = scene.add(_mol())
    obj.hide_atoms([1, 2])
    obj.atom_scales[0] = 0.4
    snap = scene.snapshot()
    obj.unhide_all()
    obj.atom_scales.clear()
    scene.restore(snap)
    back = scene.objects[0]
    assert back.atom_hidden == {1, 2}
    assert back.atom_scales == {0: pytest.approx(0.4)}


def test_hidden_atoms_survive_a_savepoint():
    import json
    scene = Scene()
    obj = scene.add(_mol())
    obj.hide_atoms([3])
    obj.atom_scales[2] = 1.5
    # through JSON, as a real .molom file goes: dict keys become strings
    data = json.loads(json.dumps(scene.to_dict()))
    again = Scene()
    again.from_dict(data)
    assert again.objects[0].atom_hidden == {3}
    assert again.objects[0].atom_scales == {2: pytest.approx(1.5)}


def test_hide_and_unhide_report_what_changed():
    obj = Scene().add(_mol())
    assert obj.hide_atoms([0, 1]) == 2
    assert obj.hide_atoms([1, 2]) == 1        # 1 was already hidden
    assert obj.has_hidden
    assert obj.unhide_all() == 3
    assert not obj.has_hidden
    assert obj.unhide_all() == 0


def test_hiding_ignores_indices_that_are_not_atoms():
    obj = Scene().add(_mol(n=3))
    assert obj.hide_atoms([0, 99, -1]) == 1
    assert obj.atom_hidden == {0}


# --------------------------------------------------------- modes: order
@pytest.fixture(scope="module")
def modes():
    text = open(FREQ_FILE, encoding="utf-8", errors="replace").read()
    return vibrations.parse_orca_frequencies(text)


def test_ir_intensities_are_read(modes):
    """Sorting by intensity needs the IR SPECTRUM block, which the parser
    ignored — every mode came back with intensity None."""
    real = [m for m in modes if not m.is_trivial]
    assert all(m.intensity is not None for m in real)
    assert modes[15].intensity == pytest.approx(390.87)
    # the table lists only the vibrations, so the rigid motions stay None
    assert all(m.intensity is None for m in modes if m.is_trivial)


def test_sorting_by_intensity_puts_the_strongest_first(modes):
    ordered = vibrations.sort_modes(modes, vibrations.SORT_INTENSITY)
    assert ordered[0].index == 15            # 390.87 km/mol
    assert ordered[1].index == 20            # 285.30
    # modes with no intensity go last rather than being dropped
    assert len(ordered) == len(modes)
    assert all(m.is_trivial for m in ordered[-6:])


def test_sorting_by_frequency_is_the_spectrum(modes):
    ordered = vibrations.sort_modes(modes, vibrations.SORT_FREQUENCY)
    freqs = [m.wavenumber for m in ordered]
    assert freqs == sorted(freqs)


def test_a_job_with_no_ir_block_still_sorts(modes):
    bare = [vibrations.Mode(m.index, m.wavenumber, m.displacements)
            for m in modes]
    ordered = vibrations.sort_modes(bare, vibrations.SORT_INTENSITY)
    assert len(ordered) == len(bare)


# -------------------------------------------------------- modes: filter
def test_filtering_by_wavenumber(modes):
    window = vibrations.filter_modes(modes, 900.0, 1050.0)
    assert [m.index for m in window] == [15, 16, 17, 18, 19]
    assert all(900.0 <= m.wavenumber <= 1050.0 for m in window)


def test_an_open_bound_means_no_bound(modes):
    assert len(vibrations.filter_modes(modes, None, None)) == 18
    assert len(vibrations.filter_modes(modes, 3000.0, None)) == 3   # the O-H's
    assert len(vibrations.filter_modes(modes, None, 3000.0)) == 15


def test_a_backwards_range_is_read_the_right_way_round(modes):
    assert (vibrations.filter_modes(modes, 1050.0, 900.0) ==
            vibrations.filter_modes(modes, 900.0, 1050.0))


def test_trivial_modes_stay_out_unless_asked_for(modes):
    assert len(vibrations.filter_modes(modes, include_trivial=True)) == 24
    assert len(vibrations.filter_modes(modes)) == 18


# ------------------------------------------------------------------ app
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


def test_h_hides_the_selection(win):
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    win.on_hide_selected()
    assert obj.atom_hidden == {0, 1}
    # and nothing is left selected — a G on invisible atoms is a trap
    assert win.viewport.selection == []


def test_h_hides_across_several_molecules(win):
    win._install_structure(_mol("other"))
    a, b = win.scene.objects[0], win.scene.objects[1]
    win.viewport.set_selection([(a.id, 0), (b.id, 2)])
    win.on_hide_selected()
    assert a.atom_hidden == {0} and b.atom_hidden == {2}


def test_hiding_survives_an_undo_of_something_else(win):
    """The actual symptom: hide, then any operation that restores a
    snapshot, and the atoms come back."""
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0)])
    win.on_hide_selected()
    win.push_undo()
    win._on_model_edit_cancel()               # a cancelled gesture
    assert win.scene.objects[0].atom_hidden == {0}


def test_undoing_the_hide_itself_still_works(win):
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (obj.id, 3)])
    win.on_hide_selected()
    assert win.scene.objects[0].atom_hidden == {0, 3}
    win.on_undo()
    assert win.scene.objects[0].atom_hidden == set()


def test_ticking_the_eye_back_on_shows_every_atom(win):
    """Christian's rule: cycling the tick restores the whole molecule. H
    only hides, so there has to be one obvious way back."""
    obj = win.scene.objects[0]
    obj.hide_atoms([0, 1, 2])
    win._on_obj_visibility(obj.id, False)
    assert obj.atom_hidden == {0, 1, 2}       # hiding the object changes none
    win._on_obj_visibility(obj.id, True)
    assert obj.atom_hidden == set()
    assert obj.visible


def test_alt_h_shows_everything_in_the_scene(win):
    win._install_structure(_mol("other"))
    for o in win.scene.objects:
        o.hide_atoms([0])
    win.on_unhide_all()
    assert all(not o.has_hidden for o in win.scene.objects)


def test_a_molecule_with_hidden_atoms_is_marked_in_the_outliner(win):
    """Hidden atoms are invisible by definition, so the row is the only
    thing left that can say they exist."""
    from molom.ui.outliner import ROLE_HIDDEN
    obj = win.scene.objects[0]
    assert win.outliner.tree.topLevelItem(0).data(0, ROLE_HIDDEN) is None
    obj.hide_atoms([0])
    win.outliner.sync(win.scene, win.active_id)
    item = win.outliner.tree.topLevelItem(0)
    assert item.data(0, ROLE_HIDDEN) is True
    assert "hidden" in item.toolTip(0)
    obj.unhide_all()
    win.outliner.sync(win.scene, win.active_id)
    assert win.outliner.tree.topLevelItem(0).data(0, ROLE_HIDDEN) is None


def test_the_hidden_mark_survives_being_selected(win):
    """A plain foreground brush loses to the selection highlight, so the one
    row you clicked was the one that stopped warning you (Issue 1)."""
    from PySide6.QtWidgets import QStyleOptionViewItem
    from molom.ui.outliner import ROLE_HIDDEN
    from PySide6.QtGui import QPalette
    obj = win.scene.objects[0]
    obj.hide_atoms([0])
    win.outliner.sync(win.scene, win.active_id)
    tree = win.outliner.tree
    item = tree.topLevelItem(0)
    item.setSelected(True)
    index = tree.indexFromItem(item, 0)
    assert index.data(ROLE_HIDDEN) is True
    option = QStyleOptionViewItem()
    win.outliner._hidden_delegate.initStyleOption(option, index)
    mark = win.outliner.HIDDEN_MARK
    assert option.palette.color(QPalette.HighlightedText) == mark
    assert option.palette.color(QPalette.Text) == mark


def test_a_hidden_trajectory_does_not_re_perceive_bonds(win):
    """Christian asked whether hiding an animated molecule actually saves
    anything. It did not: bond perception — the expensive part of a tick —
    ran regardless of visibility, so a hidden track cost 105% of a visible
    one (600 atoms, 40 frames). It is deferred now."""
    from molom.core import bonding
    s = _mol("moving", 6)
    for k in range(1, 6):
        s.frames.append(s.frames[0] + np.array([0.0, 0.0, 0.05 * k]))
    win._install_structure(s)
    obj = win.scene.objects[-1]
    win._sync_traj_bar()

    calls = []
    real = bonding.perceive_structure_bonds
    bonding.perceive_structure_bonds = lambda st, **kw: (calls.append(st),
                                                         real(st, **kw))[1]
    try:
        obj.visible = False
        for _ in range(30):
            win.timeline.advance_images(1)
            win._apply_timeline()
        assert calls == [], "hidden molecule still re-perceived bonds"

        # ...and it catches up the moment it is visible again
        win._on_obj_visibility(obj.id, True)
        assert len(calls) == 1
    finally:
        bonding.perceive_structure_bonds = real


def test_hidden_atoms_are_not_drawn_or_picked(win):
    obj = win.scene.objects[0]
    win.viewport._ensure_pick_data()
    before = len(win.viewport._atom_map)
    obj.hide_atoms([0, 1])
    win.viewport.refresh_geometry()
    win.viewport._ensure_pick_data()
    assert len(win.viewport._atom_map) == before - 2


# ------------------------------------------------- vibration page controls
def _freq(win):
    win.open_path(FREQ_FILE)
    return win._active_obj()


def test_the_amplitude_default_and_slider_range(win):
    from molom.ui import properties
    page = win.vibration_page
    assert properties.DEFAULT_AMPLITUDE == 0.2
    assert page.amp_slider.minimum() == 5        # 0.05 A
    assert page.amp_slider.maximum() == 100      # 1.00 A
    assert page.amp_spin.value() == pytest.approx(0.2)


def test_the_amplitude_box_may_exceed_the_slider(win):
    """The slider is calibrated for reading a mode; the box is the escape
    hatch for the occasional deliberately absurd amplitude."""
    page = win.vibration_page
    page.amp_spin.setValue(3.5)
    assert page.amplitude() == pytest.approx(3.5)
    assert page.amp_slider.value() == 100        # pegged, not wrong
    page.amp_slider.setValue(30)
    assert page.amp_spin.value() == pytest.approx(0.30)


def test_dragging_the_amplitude_does_not_snapshot_per_tick(win):
    """The stutter: every slider tick took a full deep scene snapshot AND
    rebuilt all 3N mode cards."""
    obj = _freq(win)
    win.on_animate_mode(6)
    depth = len(win.undo._undo)
    for value in range(20, 41):
        win.vibration_page.amp_slider.setValue(value)
    assert len(win.undo._undo) == depth + 1      # ONE step for the gesture
    win._mode_rebake.stop()
    win._rebake_mode()
    assert win._mode_amplitude[obj.id] == pytest.approx(0.40)


def test_the_page_sorts_and_filters_live(win):
    _freq(win)
    page = win.vibration_page
    assert len(page.visible_modes()) == 18
    page.low_edit.setText("900")
    page.high_edit.setText("1050")
    assert [m.index for m in page.visible_modes()] == [15, 16, 17, 18, 19]
    page.sort_combo.setCurrentIndex(1)           # IR intensity
    assert page.visible_modes()[0].index == 15
    assert "5 of 24" in page.count_label.text()


def test_a_half_typed_bound_does_not_empty_the_list(win):
    _freq(win)
    page = win.vibration_page
    for text in ("", "-", ".", "1"):
        page.low_edit.setText(text)
        assert page.visible_modes(), "{!r} emptied the list".format(text)


# ------------------------------------------------------ 1f: align preview
def test_align_previews_and_only_commits_on_confirm(win):
    """Roadmap 1f, reported twice: X used to apply AND end, so you could not
    look at the result and choose Y instead."""
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    depth = len(win.undo._undo)

    win.on_align_smart()
    assert win.viewport._align_wait == "axis"
    win._on_align_key("axis", 1)                 # align the pair to Y
    assert win.viewport is not None
    moved = obj.structure.coords.copy()
    assert not np.allclose(moved, before)        # applied as a preview
    assert len(win.undo._undo) == depth          # ...but not committed

    win.viewport._align_previewed = 1
    win.viewport._confirm_align()
    assert win.viewport._align_wait is None
    assert len(win.undo._undo) == depth + 1
    assert np.allclose(obj.structure.coords, moved)


def test_a_second_axis_key_replaces_the_first_preview(win):
    """Previews must not compound: X then Y is the Y alignment, not Y on
    top of X."""
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (obj.id, 2)])
    win.on_align_smart()
    win._on_align_key("axis", 1)
    win.viewport._align_previewed = 1
    via_x = obj.structure.coords.copy()

    win._on_align_key("axis", 0)
    direct = obj.structure.coords.copy()
    win.viewport._confirm_align()

    # doing X alone from the same start must give the same answer
    win.on_undo()
    win.viewport.set_selection([(obj.id, 0), (obj.id, 2)])
    win.on_align_smart()
    win._on_align_key("axis", 0)
    assert np.allclose(win.scene.objects[0].structure.coords, direct)
    assert not np.allclose(direct, via_x)


def test_cancelling_an_align_puts_it_back_exactly(win):
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    origin = obj.origin.copy()
    depth = len(win.undo._undo)

    win.on_align_smart()
    win._on_align_key("axis", 2)
    win.viewport._align_previewed = 2
    win.viewport._end_align_wait("Align cancelled", cancel=True)

    assert np.allclose(obj.structure.coords, before)
    assert np.allclose(obj.origin, origin)
    assert len(win.undo._undo) == depth          # no undo entry at all


def test_undo_after_confirming_returns_to_the_original_pose(win):
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    win.on_align_smart()
    win._on_align_key("axis", 1)
    win.viewport._align_previewed = 1
    win.viewport._confirm_align()
    win.on_undo()
    assert np.allclose(win.scene.objects[0].structure.coords, before)


def test_the_single_atom_case_still_applies_at_once(win):
    """Explicitly out of scope for 1f: it takes no axis key, so there is
    nothing to preview."""
    obj = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 2)])
    win.on_align_smart()
    assert win.viewport._align_wait is None
    assert np.allclose(obj.structure.coords[2], np.zeros(3))
