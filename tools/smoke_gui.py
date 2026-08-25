"""REAL-WINDOW smoke test. Run this whenever you touch a paint path.

    python tools/smoke_gui.py [file.cif ...]

Why it exists: Qt catches whatever `paintGL` raises, prints it to stderr and
carries on. The window then keeps working while everything drawn AFTER the
raise silently stops — which is how a one-character mistake in
`_draw_polyhedra` (`_camera_frame()[0]` on a dict) made the grid and the
compass disappear the moment coordination polyhedra were switched on. No
offscreen test could see it: the offscreen platform returns a null
framebuffer, so a headless run reports success either way.

This wraps every draw method, records anything that raises, grabs a frame per
step, and exits NON-ZERO if a paint path threw. The PNGs land next to the
script's output directory so the picture can be looked at, not just asserted.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

OUT = os.environ.get("MOLOM_SMOKE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_smoke")

FAILURES = []


def _instrument(cls):
    """Record — rather than swallow — anything a draw method raises."""
    for name in [n for n in dir(cls)
                 if n.startswith(("_draw", "_paint")) and callable(
                     getattr(cls, n, None))]:
        original = getattr(cls, name)

        def make(fn, label):
            def wrapper(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception:
                    FAILURES.append("{}:\n{}".format(label,
                                                     traceback.format_exc()))
                    raise
            return wrapper
        setattr(cls, name, make(original, name))


def main(paths):
    app = QApplication.instance() or QApplication([])
    from molom.ui import viewport as viewport_mod
    _instrument(viewport_mod.MolViewport)
    from molom.ui.app import MainWindow

    os.makedirs(OUT, exist_ok=True)
    win = MainWindow()
    win.load_default_scene()
    win.resize(1000, 750)
    win.show()

    def grab(tag):
        app.processEvents()
        win.viewport.update()
        app.processEvents()
        path = os.path.join(OUT, "{}.png".format(tag))
        win.viewport.grabFramebuffer().save(path)
        print("  frame:", path)

    def camera_steps():
        """The camera view has its own paint path (`_paint_camera_frame`) and
        its own projection (`sync_camera_lens`), and both were rewritten in
        round 57 — so both belong here. Nothing else opens a camera view."""
        print("camera view")
        win.on_place_camera()
        app.processEvents()
        grab("90_camera_looking_through")
        cam = win.scene.active_camera()
        if cam is None:
            return
        for focal, tag in ((18.0, "wide"), (200.0, "long")):
            cam.focal_mm = focal
            win.camera_changed()
            grab("91_camera_{}".format(tag))
        cam.focal_mm = 50.0
        win.camera_changed()
        # The WHEEL zooms the frame; the camera must not move.
        for tag, steps in (("out", -8), ("back", 8), ("in", 6)):
            win.viewport.zoom_camera_frame(steps)
            grab("92_camera_wheel_{}".format(tag))
        # A handle drag moves a BORDER: the scene must not rescale. Scroll out
        # first so there is room to drag INTO — the frame is clamped at the
        # window, or its own handles would go off screen.
        win.viewport.zoom_camera_frame(-10)
        from PySide6.QtCore import QPointF

        def molecule_extent():
            """Screen width of the drawn molecule — the thing that must not
            change when a border moves."""
            obj = win.scene.visible_objects()[0]
            xy, _f = win.viewport._project(obj.display_coords())
            return float(xy[:, 0].max() - xy[:, 0].min())

        before = molecule_extent()
        rect = win.viewport.camera_rect()
        win.viewport._camera_handle_press(
            QPointF(rect[0] + rect[2], rect[1] + rect[3] / 2.0))
        for step in (40, 90):
            win.viewport._camera_handle_move(
                QPointF(rect[0] + rect[2] + step, rect[1] + rect[3] / 2.0))
            grab("93_camera_border_{}".format(step))
        win.viewport._frame_drag = None
        after = molecule_extent()
        print("  after dragging: {} x {}, multiplier {:g}; molecule {:.1f} -> "
              "{:.1f} px {}".format(cam.width, cam.height, cam.multiplier,
                                    before, after,
                                    "OK" if abs(after - before) < 0.5
                                    else "RESCALED"))
        cam.fit_frame(win.viewport.width(), win.viewport.height())
        win.camera_changed()
        # Shift+drag re-frames the shot by moving the CAMERA, so the nudge
        # survives leaving it — and it is 1:1 on screen at any frame zoom.
        obj = win.scene.visible_objects()[0]

        def centre_px():
            xy, _f = win.viewport._project(obj.display_coords())
            return float(xy[:, 0].mean())

        was = centre_px()
        win.viewport.truck_camera(60.0, 0.0)
        app.processEvents()
        grab("93b_camera_shift_drag")
        print("  shift+drag 60 px: molecule {:.1f} -> {:.1f} px on screen"
              .format(was, centre_px()))
        win.viewport.truck_camera(-60.0, 0.0)
        win.viewport._truck_gesture = None
        cam.roll = 0.4                     # the frame drawn over a tilted view
        win.camera_changed()
        grab("94_camera_rolled")
        cam.roll = 0.0
        win.camera_changed()
        win.viewport._orbit_input(45.0, 10.0)   # and out again, by orbiting
        app.processEvents()
        grab("95_camera_orbited_out")           # the gizmo should be visible
        win.viewport.camera.distance *= 2.5
        win.viewport.select_camera(cam.id)
        app.processEvents()
        grab("96_camera_gizmo_selected")

    def export_steps():
        """`render_image` needs a LIVE GL context — it builds an FBO — so a
        headless pytest run cannot touch it (it segfaults on
        `QOpenGLFramebufferObject`). These two are round 60's fixes and this is
        the only place they can be checked against real pixels.
        """
        print("image export")
        data = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tests", "data")
        cif = os.path.join(data, "cod_2101932_ferrocene.cif")
        if not os.path.exists(cif):
            return
        win.open_path(cif)
        win.viewport.show_cell = True
        win.viewport.fit_view()
        app.processEvents()

        def ink(image):
            """Non-transparent samples — a cheap "how much was drawn"."""
            return sum(1 for y in range(0, image.height(), 4)
                       for x in range(0, image.width(), 4)
                       if (image.pixel(x, y) >> 24) & 0xFF)

        full = win.viewport.render_image(crop_to_content=False)
        tight = win.viewport.render_image(crop_to_content=True)
        full.save(os.path.join(OUT, "98_export_full.png"))
        tight.save(os.path.join(OUT, "98_export_cropped.png"))
        shrank = (tight.width() < full.width()
                  or tight.height() < full.height())
        print("  crop to content: {}x{} -> {}x{} {}".format(
            full.width(), full.height(), tight.width(), tight.height(),
            "OK" if shrank else "DID NOT SHRINK"))
        if not shrank:
            FAILURES.append("crop_to_content did not shrink the image")

        # The unit cell must reach the exported image (it used to be gated on
        # `furniture=`, which the still export never passes).
        with_box = ink(full)
        win.viewport.show_cell = False
        without = win.viewport.render_image(crop_to_content=False)
        win.viewport.show_cell = True
        print("  cell box in export: ink {} with, {} without {}".format(
            with_box, ink(without),
            "OK" if with_box > ink(without) else "MISSING"))
        if with_box <= ink(without):
            FAILURES.append("the unit cell box is missing from render_image")

        # Round 86: the box can be drawn as real geometry instead of being
        # painted over everything, and the EXPORT defaults to that. The claim
        # is occlusion, so the measurement is a three-way frame comparison -
        # counting coloured pixels measures the rod's THICKNESS instead, and
        # counting "axis-coloured" ones counts the red oxygens (both were
        # tried, and both said the feature worked when it did not).
        from molom.core import cellbox as cellbox_mod
        vp = win.viewport
        keep = vp.cell_zorder
        vp.show_cell = False
        plain = vp.render_image(crop_to_content=False)
        vp.show_cell = True
        vp.cell_zorder = cellbox_mod.OVERLAY
        over = vp.render_image(crop_to_content=False)
        vp.cell_zorder = cellbox_mod.DEPTH
        deep = vp.render_image(crop_to_content=False)
        vp.cell_zorder = keep
        over.save(os.path.join(OUT, "99_cell_on_top.png"))
        deep.save(os.path.join(OUT, "99_cell_depth.png"))
        painted = hidden = 0
        for y in range(0, plain.height(), 2):
            for x in range(0, plain.width(), 2):
                base = plain.pixel(x, y)
                if over.pixel(x, y) == base:
                    continue
                painted += 1
                if deep.pixel(x, y) == base:
                    hidden += 1
        share = (100.0 * hidden / painted) if painted else 0.0
        print("  cell box z-order: {} painted px, {} of them behind the "
              "structure ({:.0f}%) {}".format(
                  painted, hidden, share,
                  "OK" if hidden else "NOTHING OCCLUDED"))
        if not hidden:
            FAILURES.append("the depth-ordered cell box occluded nothing")

    def measure_steps():
        """Persistent measurements: several at once, one of them highlighted as
        the Delete target. `_paint_measure` is a paint path, so a raise here is
        exactly what this tool exists to catch."""
        print("measurements")
        obj = win._active_obj()
        if obj is None or obj.structure.n_atoms < 5:
            return
        vp = win.viewport
        vp.set_measure_tool(True)
        vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
        first = vp.commit_measurement()
        vp._measure_picks = [(obj.id, 1), (obj.id, 2), (obj.id, 3)]
        vp.commit_measurement()
        vp._measure_picks = [(obj.id, 3), (obj.id, 4)]      # live, dashed
        vp._hover_measurement = first                        # highlighted
        grab("99_measurements")
        print("  kept {}, clickable rects {}".format(
            len(vp.measurements), len(vp._measure_hits)))
        if len(vp._measure_hits) != len(vp.measurements):
            FAILURES.append("a kept measurement has no clickable label rect")
        vp.clear_measurements()
        vp.set_measure_tool(False)

    def vibration_steps():
        """A baked normal mode with a selection on it: the bonds must survive
        the squeeze and the orange hull must track the interpolated atoms."""
        freq = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tests", "data",
            "orca_freq_h3po4.out")
        if not os.path.exists(freq):
            return
        print("vibration")
        win.open_path(freq)
        obj = win._active_obj()
        modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
        if not modes:
            return
        win.on_animate_mode(modes[-1].index, amplitude=0.8)
        win.viewport.set_selection([(obj.id, i) for i in range(3)])
        for k in range(4):
            win.timeline.advance_frames(3)
            win._apply_timeline()
            app.processEvents()
            grab("97_vibration_{}".format(k))
        print("  bonds through the cycle:",
              len(win.scene.get(obj.id).structure.bonds))

    def run():
        try:
            grab("00_startup")
            camera_steps()
            export_steps()
            measure_steps()
            vibration_steps()
            for index, path in enumerate(paths):
                if not os.path.exists(path):
                    print("  skipped (missing):", path)
                    continue
                name = os.path.splitext(os.path.basename(path))[0]
                print("opening", name)
                win.open_path(path)
                app.processEvents()
                grab("{:02d}_{}_imported".format(index + 1, name))
                obj = win._active_obj()
                if obj is None:
                    continue
                meta = obj.structure.metadata or {}
                # Every overlay that has its own paint path.
                for flag, tag in (("polyhedra", "polyhedra"),
                                  ("show_symmetry", "symmetry"),
                                  ("show_ghosts", "ghosts"),
                                  ("show_refused_bonds", "refused")):
                    meta[flag] = True
                    grab("{:02d}_{}_{}".format(index + 1, name, tag))
                    meta[flag] = False
                for label in ("outside_check", "copies_check"):
                    box = getattr(win.crystal_page, label, None)
                    if box is None or not box.isEnabled():
                        continue
                    box.setChecked(not box.isChecked())
                    app.processEvents()
                    grab("{:02d}_{}_{}".format(index + 1, name, label))
                    box.setChecked(not box.isChecked())
                    app.processEvents()
        finally:
            app.quit()

    QTimer.singleShot(500, run)
    app.exec()

    print("\n--- paint-path exceptions ---")
    if FAILURES:
        for failure in FAILURES:
            print(failure)
        print("{} paint path(s) raised".format(len(FAILURES)))
        return 1
    print("(none)")
    return 0


if __name__ == "__main__":
    given = sys.argv[1:]
    if not given:
        guess = r"C:\Users\chris\Desktop\test cifs"
        given = [os.path.join(guess, f) for f in
                 ("ZIF-8.cif", "1547149.cif", "242083.cif")]
        # Christian's set is CCDC data and is not in the repo, so on a machine
        # without it every crystal overlay would be skipped and the run would
        # pass having exercised nothing. The vendored fixtures cover the same
        # paint paths — a framework metal with polyhedra, and symmetry.
        data = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tests", "data")
        given += [os.path.join(data, f) for f in sorted(os.listdir(data))
                  if f.endswith(".cif")]
    raise SystemExit(main(given))
