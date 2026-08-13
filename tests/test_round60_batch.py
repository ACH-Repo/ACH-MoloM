"""Round 60: Christian's batch — camera gestures, exports, supercell bonds,
persistent measurements.

* "Ctrl+drag should still dolly the camera... Shift+drag should pan the view of
  the camera. Right now it is doing the same thing as Ctrl+drag."
* "Crop to content option when saving images the regular way."
* "supercells do not show bonds in cif properties tab."
* "Screenshots of cifs are missing the unit cell boundaries. Not legible
  without them."
* "Measurements should be persistent in the viewport, but deletable by
  selecting + Delete or hovering over them + Delete."
"""

import os

import numpy as np
import pytest

from molom.core import cif, crop

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def _wheel(vp, dy, mods):
    """A trackpad-style scroll (pixelDelta non-null), as Qt delivers it."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    return QWheelEvent(QPointF(400, 300), vp.mapToGlobal(QPoint(400, 300)),
                       QPoint(0, int(dy)), QPoint(0, int(dy * 8)),
                       Qt.NoButton, mods, Qt.NoScrollPhase, False)


# ------------------------------------------- the three camera-view gestures
def test_plain_scroll_resizes_the_frame_and_never_moves_the_camera(win):
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp, cam = win.viewport, win.scene.active_camera()
    where, far, zoom = np.array(cam.center), cam.distance, cam.frame_zoom
    vp.wheelEvent(_wheel(vp, 40, Qt.NoModifier))
    assert cam.frame_zoom != zoom
    assert cam.distance == pytest.approx(far)
    assert np.allclose(cam.center, where)


def test_ctrl_scroll_DOLLIES_the_camera(win):
    """Christian: "actually move it closer/further from the object". The frame
    must not resize with it — that is the other gesture."""
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp, cam = win.viewport, win.scene.active_camera()
    where, far, zoom = np.array(cam.center), cam.distance, cam.frame_zoom
    vp.wheelEvent(_wheel(vp, 40, Qt.ControlModifier))
    assert cam.distance != pytest.approx(far), "Ctrl+scroll must dolly"
    assert cam.frame_zoom == pytest.approx(zoom), "and must not resize the frame"
    assert np.allclose(cam.center, where), "a dolly is not a truck"


def test_shift_scroll_PANS_and_is_not_the_same_as_ctrl(win):
    """The reported bug: both modifiers fell through to the frame zoom, so
    Shift did "the same thing as Ctrl"."""
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp, cam = win.viewport, win.scene.active_camera()
    where, far, zoom = np.array(cam.center), cam.distance, cam.frame_zoom
    vp.wheelEvent(_wheel(vp, 40, Qt.ShiftModifier))
    assert not np.allclose(cam.center, where), "Shift+scroll must truck"
    assert cam.distance == pytest.approx(far), "a truck is not a dolly"
    assert cam.frame_zoom == pytest.approx(zoom)


def test_the_three_gestures_are_all_different(win):
    """One gesture, one meaning — the whole point of the report."""
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp, cam = win.viewport, win.scene.active_camera()
    home = (np.array(cam.center), cam.distance, cam.frame_zoom)

    def after(mods):
        cam.center, cam.distance, cam.frame_zoom = (home[0].copy(), home[1],
                                                    home[2])
        cam.apply_to(vp.camera)
        vp.sync_camera_lens()
        vp._last_cam_wheel_t = -1e9
        vp.wheelEvent(_wheel(vp, 40, mods))
        return (tuple(np.round(cam.center, 6)), round(cam.distance, 6),
                round(cam.frame_zoom, 6))

    plain = after(Qt.NoModifier)
    ctrl = after(Qt.ControlModifier)
    shift = after(Qt.ShiftModifier)
    assert len({plain, ctrl, shift}) == 3


def test_a_scroll_gesture_is_one_undo_step_but_a_pause_starts_another(win):
    """A drag ends at a release; a scroll has no release, so the gesture is
    closed by a pause. Without it every Ctrl+scroll for the rest of the session
    would coalesce into the first one's undo step."""
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp, cam = win.viewport, win.scene.active_camera()
    depth = len(win.undo._stack) if hasattr(win.undo, "_stack") else None
    for _ in range(6):
        vp.wheelEvent(_wheel(vp, 10, Qt.ControlModifier))
    assert vp._truck_gesture == cam.id
    if depth is not None:
        assert len(win.undo._stack) == depth + 1
    vp._last_cam_wheel_t = -1e9              # simulate the pause
    vp.wheelEvent(_wheel(vp, 10, Qt.ControlModifier))
    if depth is not None:
        assert len(win.undo._stack) == depth + 2


# ----------------------------------------------------------- crop to content
def test_content_box_is_tight_and_padded():
    mask = np.zeros((100, 200), dtype=bool)
    mask[40:60, 80:120] = True
    assert crop.content_box(mask, margin=0) == (80, 40, 40, 20)
    assert crop.content_box(mask, margin=5) == (75, 35, 50, 30)


def test_content_box_of_an_empty_image_keeps_the_whole_frame():
    """Cropping nothing to nothing would make the caller write a broken file."""
    assert crop.content_box(np.zeros((50, 70), dtype=bool)) == (0, 0, 70, 50)


def test_content_box_never_leaves_the_image():
    mask = np.zeros((40, 60), dtype=bool)
    mask[10:20, 10:20] = True
    x, y, w, h = crop.content_box(mask, margin=500)
    assert (x, y) == (0, 0) and (w, h) == (60, 40)


def test_an_aspect_only_ever_GROWS_the_box():
    """Shrinking to a ratio would crop away the content just asked for."""
    mask = np.zeros((200, 200), dtype=bool)
    mask[90:110, 20:180] = True                  # a wide, short band
    tight = crop.content_box(mask, margin=0)
    wide = crop.content_box(mask, margin=0, aspect=1.0)
    assert wide[2] >= tight[2] and wide[3] >= tight[3]


def test_alpha_and_colour_masks_agree_on_the_same_picture():
    alpha = np.zeros((20, 30), dtype=np.uint8)
    alpha[5:15, 6:24] = 255
    rgb = np.zeros((20, 30, 3), dtype=np.uint8)
    rgb[:, :] = (60, 60, 60)                     # the background
    rgb[5:15, 6:24] = (200, 30, 30)              # the molecule
    assert crop.content_box(crop.alpha_mask(alpha)) == \
        crop.content_box(crop.colour_mask(rgb, (60, 60, 60)))


def test_the_content_box_survives_the_QImage_conversion(win):
    """The risky half of the crop is the QImage -> numpy bridge, NOT the
    geometry: `bytesPerLine` can exceed 4*width, and assuming a tight buffer
    shears the image. A QImage needs no GL context, so this is testable here
    even though `render_image` itself is not — see `tools/smoke_gui.py`, which
    drives the real thing in a real window.
    """
    from PySide6.QtGui import QImage
    image = QImage(120, 90, QImage.Format_RGBA8888)
    image.fill(0x00000000)                      # fully transparent
    for y in range(30, 60):
        for x in range(20, 80):
            image.setPixel(x, y, 0xFFFF0000)    # an opaque block
    box = win.viewport._content_box(image, transparent=True, margin=0)
    assert box == (20, 30, 60, 30)


def test_the_content_box_uses_the_BACKGROUND_when_opaque(win):
    """An opaque export has no alpha to read, so content is whatever differs
    from the viewport's own background colour."""
    from PySide6.QtGui import QImage
    vp = win.viewport
    back = tuple(int(round(c * 255.0)) for c in vp.background)
    image = QImage(100, 80, QImage.Format_RGBA8888)
    image.fill(0xFF000000 | (back[0] << 16) | (back[1] << 8) | back[2])
    for y in range(10, 40):
        for x in range(50, 90):
            image.setPixel(x, y, 0xFF00FF00)
    box = vp._content_box(image, transparent=False, margin=0)
    assert box == (50, 10, 40, 30)


def test_render_image_takes_the_crop_option(win):
    """The plumbing, without touching GL: `render_image` itself needs a live
    context (it builds an FBO), so the picture is checked by the smoke tool."""
    import inspect
    params = inspect.signature(win.viewport.render_image).parameters
    assert "crop_to_content" in params and "crop_margin" in params
    assert params["crop_to_content"].default is False
    assert hasattr(win.viewport, "render_crop")


# -------------------------------------------- the unit cell IS in an export
def test_the_export_overlays_no_longer_hide_the_cell_behind_furniture(win):
    """"Screenshots of cifs are missing the unit cell boundaries. Not legible
    without them." The box was behind `furniture=`, which the still-image
    export does not pass — and so were the polyhedra, the occupancy spheres and
    the wireframe buffer. Only the atom LABELS are optional now.
    """
    import inspect
    src = inspect.getsource(win.viewport.render_image)
    # The structural passes must not sit inside a `if furniture:` block.
    for call in ("_draw_occupancy", "_draw_polyhedra", "_wire_lines"):
        assert call in src
    assert "if furniture:" not in src, \
        "structural passes must not be gated on `furniture` any more"
    assert "labels=furniture" in src
    overlays = inspect.signature(win.viewport._paint_export_overlays).parameters
    assert "labels" in overlays


# --------------------------------------------------- supercell bonds (a bug)
def test_a_supercell_replicates_its_BONDS(win=None):
    """"supercells do not show bonds in cif properties tab" — the packing path
    repeated the atoms and never the bonds, so every cell past the first drew
    as loose spheres."""
    data = cif.parse_cif(open(FERROCENE, encoding="utf-8").read())
    counts = {}
    for block in ((1, 1, 1), (2, 1, 1), (2, 2, 1), (2, 2, 2)):
        report = {}
        symbols, _xyz = cif.build_view(
            data.cell, data.symbols, data.frac, data.symops, mode="packing",
            na=block[0], nb=block[1], nc=block[2],
            occupancy=data.occupancy, report=report)
        counts[block] = (len(symbols), len(report.get("packed_bonds") or []))

    single_atoms, single_bonds = counts[(1, 1, 1)]
    assert single_bonds > 0
    for block, (atoms, bonds) in counts.items():
        assert bonds > 0, "{} drew no bonds at all".format(block)
        if block != (1, 1, 1):
            assert atoms > single_atoms and bonds > single_bonds, \
                "{} must grow both atoms AND bonds".format(block)
        # The connectivity per atom is a property of the structure, not of how
        # many cells are drawn, so the ratio has to hold across the block.
        assert bonds / float(atoms) == pytest.approx(
            single_bonds / float(single_atoms), rel=1e-6)


def test_supercell_bond_indices_stay_in_range():
    """The de-duplication renumbers, so an unremapped bond would point past the
    end of the atom list — or worse, at the wrong atom."""
    data = cif.parse_cif(open(FERROCENE, encoding="utf-8").read())
    report = {}
    symbols, _xyz = cif.build_view(
        data.cell, data.symbols, data.frac, data.symops, mode="packing",
        na=2, nb=2, nc=2, occupancy=data.occupancy, report=report)
    bonds = report.get("packed_bonds") or []
    assert bonds
    for i, j, _order in bonds:
        assert 0 <= i < len(symbols) and 0 <= j < len(symbols)
        assert i != j


def test_the_dedup_reports_what_each_duplicate_collapsed_onto():
    """`canonical` is what lets a bond survive the merge instead of being
    dropped: a coincident atom is the same physical atom, not a lost one."""
    xyz = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    keep, canonical = cif._coincident_map(xyz, tol=0.1)
    assert list(keep) == [True, True, False]
    assert int(canonical[2]) == 0
    assert int(canonical[0]) == 0 and int(canonical[1]) == 1


# --------------------------------------------------- persistent measurements
def test_measurements_persist_and_stack_up(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp.set_measure_tool(True)
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    first = vp.commit_measurement()
    vp._measure_picks = [(obj.id, 0), (obj.id, 1), (obj.id, 2)]
    second = vp.commit_measurement()
    assert first != second
    assert len(vp.measurements) == 2
    texts = [vp._measure_entry_text(m) for m in vp.measurements]
    assert any("d(" in t for t in texts) and any("angle(" in t for t in texts)


def test_one_pick_is_not_a_measurement(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp._measure_picks = [(obj.id, 0)]
    assert vp.commit_measurement() is None
    assert vp.measurements == []


def test_putting_the_tool_away_KEEPS_them(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp.set_measure_tool(True)
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    vp.set_measure_tool(False)
    assert len(vp.measurements) == 1, "Esc/off must not bin a finished one"


def test_delete_takes_the_HOVERED_measurement(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    ident = vp.commit_measurement()
    vp._hover_measurement = ident
    assert vp.has_measurement_target()
    assert win.viewport.delete_measurement() is True
    assert vp.measurements == []


def test_delete_takes_the_SELECTED_measurement(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    ident = vp.commit_measurement()
    vp.selected_measurement = ident
    assert vp.delete_measurement() is True
    assert vp.measurements == []


def test_delete_falls_through_to_ATOMS_when_no_measurement_is_targeted(win):
    """Delete must not become a measurement-only key."""
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    before = obj.structure.n_atoms
    vp.set_selection([(obj.id, 0)])
    assert vp.delete_measurement() is False
    win.on_delete_selected()
    assert win.scene.get(obj.id).structure.n_atoms < before


def test_the_delete_operator_is_enabled_by_a_hovered_measurement(win):
    """`run_op` refuses a disabled operator, so a predicate that only looked at
    the atom selection would stop Delete ever reaching a measurement."""
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp.set_selection([])
    op = win.ops.get("delete_selected")
    assert op.enabled(win) is False
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    vp._hover_measurement = vp.commit_measurement()
    assert op.enabled(win) is True


def test_hiding_measurements_does_not_delete_them(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    vp.commit_measurement()
    vp.set_show_measurements(False)
    assert vp.show_measurements is False
    assert len(vp.measurements) == 1
    vp.set_show_measurements(True)
    assert vp.show_measurements is True


def test_clear_removes_everything_including_the_one_in_progress(win):
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    vp.commit_measurement()
    vp._measure_picks = [(obj.id, 2), (obj.id, 3)]
    assert vp.clear_measurements() == 1
    assert vp.measurements == [] and vp._measure_picks == []


def test_a_measurement_whose_atom_is_gone_is_dropped_not_drawn(win):
    """It is held on the viewport rather than in the scene, so an atom can
    vanish underneath it. Better to drop it than to draw half of it against
    whatever now holds that index."""
    win.load_default_scene()
    vp, obj = win.viewport, win._active_obj()
    vp._measure_picks = [(obj.id, 0), (obj.id, obj.structure.n_atoms - 1)]
    vp.commit_measurement()
    assert len(vp.measurements) == 1
    win.scene.remove(obj.id)
    # Pruning is its OWN method, not a side effect of painting: offscreen never
    # runs paintGL, and a hidden mutation in a paint path is the round-33 trap.
    assert vp.prune_measurements() == 1
    assert vp.measurements == []


def test_the_measurement_operators_exist_and_clash_with_nothing(win):
    for op_id in ("measure_show", "measure_clear"):
        assert win.ops.get(op_id) is not None
    assert not win.ops.duplicate_keys()
