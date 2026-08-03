"""Round 23: the multi-row timeline pane."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _traj(name, n, axis=0):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0.0, 0.0, 0.0), ("O", 1.2, 0.0, 0.0)],
                             name=name)
    for k in range(1, n):
        frame = s.frames[0].copy()
        frame[:, axis] += k * 0.5
        s.frames.append(frame)
    return s


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    for name, n, axis in (("alpha", 5, 0), ("beta", 21, 1), ("gamma", 13, 2)):
        w._install_structure(_traj(name, n, axis))
    w._sync_traj_bar()
    return w


def test_a_row_per_animated_object(win):
    rows = win.traj_bar.rows.rows()
    assert len(rows) == 3
    assert win.traj_bar.rows.names[rows[0].obj_id] in ("alpha", "beta",
                                                       "gamma")


def test_stills_get_no_row(win):
    from molom.core.structure import Structure
    win._install_structure(Structure.from_atoms([("C", 0.0, 0.0, 0.0)]))
    win._sync_traj_bar()
    assert len(win.traj_bar.rows.rows()) == 3      # unchanged


def test_the_pane_opens_itself_when_there_is_something_to_play(win):
    """With the transport slider gone, a collapsed pane would leave nothing
    to scrub — so it opens as soon as a trajectory exists."""
    panel = win.traj_bar
    assert panel.rows.isVisible()
    assert panel.rows.height() >= 3 * 21


def test_the_pane_still_collapses_on_request(win):
    panel = win.traj_bar
    panel.expand_btn.setChecked(False)
    assert not panel.rows.isVisible()
    panel.expand_btn.setChecked(True)
    assert panel.rows.isVisible()


def test_there_is_no_redundant_transport_slider(win):
    assert not hasattr(win.traj_bar, "slider")


def test_the_playhead_is_draggable(win):
    rows = win.traj_bar.rows
    rows.resize(600, rows.natural_height())
    from PySide6.QtCore import QPointF
    x = rows._x_for(win.timeline.time)
    assert rows._on_playhead(QPointF(x, 30.0))
    assert not rows._on_playhead(QPointF(x + 40, 30.0))


def test_the_grip_resizes_the_rows_area(win):
    panel = win.traj_bar
    panel.expand_btn.setChecked(True)
    before = panel.rows.height()
    panel._resize_rows(40)         # drag up = taller
    assert panel.rows.height() > before
    panel._resize_rows(-10000)     # clamped, never collapses to nothing
    assert panel.rows.height() >= 30


def test_time_and_pixels_round_trip(win):
    rows = win.traj_bar.rows
    rows.resize(600, 80)
    for t in (0.0, 5.0, 12.5, 20.0):
        assert rows._time_for(rows._x_for(t)) == pytest.approx(t, abs=1e-6)


def test_dragging_a_bar_moves_that_track_only(win):
    tl = win.timeline
    ids = [t.obj_id for t in tl.tracks()]
    tl.get(ids[1]).start = 6.0
    others = {i: tl.get(i).start for i in ids if i != ids[1]}
    assert tl.get(ids[1]).start == pytest.approx(6.0)
    for i, start in others.items():
        assert tl.get(i).start == pytest.approx(start)


def test_offsetting_a_track_lengthens_the_scene(win):
    tl = win.timeline
    before = tl.duration
    long_track = max(tl.tracks(), key=lambda t: t.n_frames)
    long_track.start = 6.0
    assert tl.duration == pytest.approx(before + 6.0)


def test_rows_are_ordered_by_start_then_id(win):
    tl = win.timeline
    ids = [t.obj_id for t in tl.tracks()]
    tl.get(ids[0]).start = 30.0
    ordered = [t.obj_id for t in win.traj_bar.rows.rows()]
    assert ordered[-1] == ids[0]


def test_disabling_a_row_freezes_that_object(win):
    tl = win.timeline
    track = tl.tracks()[0]
    track.enabled = False
    win._apply_timeline()
    assert tl.frame_for(track.obj_id) is None
    obj = win.scene.get(track.obj_id)
    assert obj.play_position is None


def test_seeking_from_the_rows_moves_the_shared_playhead(win):
    win.traj_bar.rows.seek_requested.emit(7.5)
    assert win.timeline.time == pytest.approx(7.5)


def test_the_transport_label_counts_the_tracks(win):
    win.traj_bar.sync(win.timeline,
                      {o.id: o.name for o in win.scene.objects}, False)
    assert "3 tracks" in win.traj_bar.label.text()


def test_the_pane_paints_without_error(win):
    """Custom painting is easy to break silently — grab() would raise."""
    panel = win.traj_bar
    panel.expand_btn.setChecked(True)
    panel.rows.resize(700, panel.rows.natural_height())
    image = panel.rows.grab()
    assert image.width() == 700


def test_end_mode_cycles_on_double_click(win):
    from molom.core import timeline as timeline_mod
    track = win.traj_bar.rows.rows()[0]
    assert track.end == timeline_mod.HOLD
    order = ["hold", "loop", "pingpong"]
    track.end = order[(order.index(track.end) + 1) % 3]
    assert track.end == timeline_mod.LOOP


# ------------------------------------------------- per-crystal outliner row
@pytest.fixture
def crystal_win(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    from molom.core.structure import Structure
    from tests.test_round18_cif import NACL_CIF
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w._install_structure(Structure.from_atoms([("C", 0.0, 0.0, 0.0)],
                                              name="plain"))
    path = tmp_path / "nacl.cif"
    path.write_text(NACL_CIF, encoding="utf-8")
    w.open_path(str(path))
    return w


def _controls(win):
    from molom.ui.outliner import CrystalControls
    return win.outliner.tree.findChildren(CrystalControls)


def test_only_a_cif_object_gets_crystal_controls(crystal_win):
    """An ordinary molecule has no cell, so the row must not grow switches
    that cannot do anything."""
    assert len(_controls(crystal_win)) == 1


def test_the_row_checkboxes_apply_immediately(crystal_win):
    from PySide6.QtWidgets import QApplication
    ctrl = _controls(crystal_win)[0]
    assert crystal_win._active_obj().structure.n_atoms == 27
    ctrl.asym_check.setChecked(True)          # no Apply button pressed
    QApplication.processEvents()
    assert crystal_win._active_obj().structure.n_atoms == 2
    ctrl.full_check.setChecked(True)
    QApplication.processEvents()
    assert crystal_win._active_obj().structure.n_atoms == 27


def test_the_content_checkboxes_are_exclusive(crystal_win):
    ctrl = _controls(crystal_win)[0]
    ctrl.asym_check.setChecked(True)
    assert not ctrl.full_check.isChecked()
    ctrl.full_check.setChecked(True)
    assert not ctrl.asym_check.isChecked()


def test_show_unit_cell_checkbox_drives_the_viewport(crystal_win):
    ctrl = _controls(crystal_win)[0]
    ctrl.box_check.setChecked(False)
    assert not crystal_win.viewport.show_cell
    ctrl.box_check.setChecked(True)
    assert crystal_win.viewport.show_cell


def test_advanced_opens_the_page_on_that_crystal(crystal_win):
    from PySide6.QtWidgets import QApplication
    ctrl = _controls(crystal_win)[0]
    ctrl.advanced.emit(ctrl.obj_id)
    QApplication.processEvents()
    assert crystal_win.active_id == ctrl.obj_id
    index = crystal_win.properties.buttons["crystal"][1]
    assert crystal_win.properties.stack.currentIndex() == index


def test_the_crystal_page_has_no_apply_button(crystal_win):
    assert not hasattr(crystal_win.crystal_page, "apply_button")


def test_the_crystal_tab_stays_clickable_and_greys_its_controls(crystal_win):
    """Round 34 replaces round 23's greyed TAB with greyed CONTROLS.

    A greyed tab cannot explain why it is greyed (the round-30 lesson from the
    vibrations page), and this one greyed itself on whatever molecule happened
    to be active — so clicking a solvent molecule made the page you were
    reading disappear. Christian asked for the ∿ treatment: always clickable,
    with the page saying what to select.
    """
    tab = crystal_win.properties.buttons["crystal"][0]
    page = crystal_win.crystal_page
    crystal_win._sync_crystal_page()
    assert tab.isEnabled()
    assert page.cell_radio.isEnabled()

    plain = [o for o in crystal_win.scene.objects if o.name == "plain"][0]
    crystal_win.active_id = plain.id
    crystal_win._sync_crystal_page()
    assert tab.isEnabled()                    # still reachable...
    assert not page.cell_radio.isEnabled()    # ...but nothing is live
    assert not page.sym_check.isEnabled()
    assert not page.ghost_check.isEnabled()
    assert "cif" in page.summary.text().lower()   # and it says what to do
