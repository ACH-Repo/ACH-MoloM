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
            win.timeline.advance_images(3)
            win._apply_timeline()
            app.processEvents()
            grab("97_vibration_{}".format(k))
        print("  bonds through the cycle:",
              len(win.scene.get(obj.id).structure.bonds))

    def run():
        try:
            grab("00_startup")
            camera_steps()
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
