"""Generate the screenshots the README and the PyPI page use.

    python tools/screenshots.py            # -> docs/screenshots/*.png

A REAL window, never offscreen — the offscreen platform hands back a null
framebuffer, so a headless run would write black rectangles and report success
(the round-48 lesson, and the reason `tools/smoke_gui.py` exists at all).

Three rules this file exists to hold:

* **A FRESH WINDOW PER SHOT.** Imports ADD to the scene in MoloM and never
  replace, which is correct for the program and wrong for a screenshot: the
  first draft had the camera shot showing cubane, a ferrocene packing and a
  solid solution all at once, 247 atoms of unrelated structures. Rebuilding the
  window makes each shot a pure function of its own setup.
* **Drive the CONTROLS, not the metadata.** Setting `metadata["polyhedra"]`
  directly draws the solids and leaves the tick box unticked, so the screenshot
  shows a feature apparently switched off while it is plainly on — round 51's
  bug, staged for the camera. Going through the page's own checkbox is also the
  only way the picture proves the wiring works.
* **Verify the grab.** `win.grab()` takes the whole window, docks included,
  which is what a reader wants; a QOpenGLWidget composites into the backing
  store, so the viewport really is in it. `_check` confirms that per shot
  rather than trusting it, because the failure mode is a uniform rectangle and
  it is completely silent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QTimer, Qt          # noqa: E402
from PySide6.QtGui import QPainter                     # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("MOLOM_SHOTS_OUT") or os.path.join(
    ROOT, "docs", "screenshots")
DATA = os.path.join(ROOT, "tests", "data")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")
SOLID_SOLUTION = os.path.join(DATA, "cod_1547149_solid_solution.cif")
FREQ = os.path.join(DATA, "orca_freq_h3po4.out")

# 16:10 at a size that stays legible when GitHub scales it into a README
# column and still looks like a real application window rather than a crop.
SIZE = (1400, 875)

WROTE = []
PROBLEMS = []


def compose(win):
    """A whole-window screenshot with the GL surface pasted in over itself.

    `win.grab()` walks the widget hierarchy and, for a QOpenGLWidget, hands
    back the GL geometry WITHOUT the QPainter overlays that `paintGL` draws on
    top of it — measured, not assumed: the same frame grabbed both ways gives a
    film back, eight handles, the veil and the hint line through
    `grabFramebuffer()` and none of them through `win.grab()`. Since the
    overlays are most of what MoloM draws (the camera frame, the cell box, the
    compass, labels, symmetry elements, the measurement readout), a window grab
    on its own quietly photographs the program with its features switched off.

    So take both and composite: the window for the chrome, the framebuffer for
    the viewport. The framebuffer is already in DEVICE pixels, which is why the
    paste offset is scaled by the ratio rather than used as-is.

    The paste then has to be undone for the viewport's own CHILD widgets — the
    floating tool column, the crystal ribbon, the periodic table. Those are
    real widgets sitting over the GL surface, so they are in the window grab
    and NOT in the framebuffer, and pasting the framebuffer flat over the
    viewport erased them (the tool column vanished from the first composite).

    They are restored by copying their rectangles back out of the ORIGINAL
    window grab rather than by re-grabbing each one. `child.grab()` renders a
    widget onto a fresh surface with nothing behind it, which throws away the
    translucency these panels are styled with — the second composite came back
    with a white toolbar and a white ribbon over a dark viewport. The window
    grab already has them composited correctly; the only thing wrong with it is
    the GL surface, so that is the only thing worth replacing.
    """
    base = win.grab().toImage()
    frame = win.viewport.grabFramebuffer()
    if frame.isNull():
        return base
    ratio = base.width() / max(win.width(), 1)
    # BOTH grabs carry a devicePixelRatio (1.5 on this machine), and a QPainter
    # on such an image works in LOGICAL coordinates — so device-pixel offsets
    # get multiplied by the ratio a second time and everything lands 1.5x too
    # far down. Dropping the ratio to 1 makes one pixel of arithmetic mean one
    # pixel of image, which is the only way this stays debuggable.
    for grabbed in (base, frame):
        grabbed.setDevicePixelRatio(1.0)
    image = base.copy()
    image.setDevicePixelRatio(1.0)

    def rect_of(widget):
        point = widget.mapTo(win, QPoint(0, 0))
        return (int(round(point.x() * ratio)), int(round(point.y() * ratio)),
                int(round(widget.width() * ratio)),
                int(round(widget.height() * ratio)))

    painter = QPainter(image)
    x, y, _w, _h = rect_of(win.viewport)
    painter.drawImage(QPoint(x, y), frame)
    for child in win.viewport.children():
        if isinstance(child, QWidget) and child.isVisible():
            cx, cy, cw, ch = rect_of(child)
            painter.drawImage(QPoint(cx, cy), base.copy(cx, cy, cw, ch))
    painter.end()
    return image


def _check(tag, image):
    """A screenshot that is uniformly one colour is a failed grab, not a
    picture — and it is the failure mode that looks like success."""
    if image.isNull():
        PROBLEMS.append("{}: null image".format(tag))
        return False
    small = image.scaled(48, 48, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    seen = {small.pixel(x, y) for x in range(48) for y in range(0, 48, 2)}
    if len(seen) < 12:
        PROBLEMS.append("{}: only {} distinct colours - grab looks empty"
                        .format(tag, len(seen)))
        return False
    return True


def main():
    app = QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow

    os.makedirs(OUT, exist_ok=True)
    live = {}

    def settle(rounds=8):
        for _ in range(rounds):
            app.processEvents()
        win = live.get("win")
        if win is not None:
            win.viewport.update()
        for _ in range(rounds):
            app.processEvents()

    def new_window(page="outliner"):
        """One window per shot: see the module docstring."""
        old = live.pop("win", None)
        win = MainWindow()
        win.resize(*SIZE)
        win.properties.setVisible(True)
        win.properties.show_page(page)
        win.show()
        live["win"] = win
        settle()
        if old is not None:
            old.close()
            old.deleteLater()
        return win

    def shot(tag, caption, viewport_only=False):
        win = live["win"]
        settle()
        # Printed for every shot because "the overlay is missing" is the whole
        # class of failure a screenshot tool cannot see: the picture looks
        # perfectly fine, just without the feature it was taken for.
        print("    [state] looking_through={} rect={}".format(
            win.viewport.looking_through, win.viewport.camera_rect()))
        image = (win.viewport.grabFramebuffer() if viewport_only
                 else compose(win))
        path = os.path.join(OUT, "{}.png".format(tag))
        if _check(tag, image) and image.save(path):
            WROTE.append((tag, caption))
            print("  {}  {}x{}".format(os.path.basename(path),
                                       image.width(), image.height()))
        else:
            print("  FAILED", tag)

    # ---------------------------------------------------------------- shots
    def viewport_and_outliner():
        """The default scene: cubane, built analytically so it is exactly
        centred and axis-aligned (Blender's default cube, in molecules)."""
        win = new_window("outliner")
        win.load_default_scene()
        # Expand the molecule so the VESTA-style per-element rows show — the
        # tree is the point of the shot, and every row is collapsed by default.
        win.outliner.tree.expandToDepth(0)
        win.viewport.fit_view()
        shot("01-viewport",
             "Ball-and-stick viewport with the scene outliner. Avogadro 2's "
             "element data and exact sizing rules; Blender's ergonomics "
             "around them.")

    def crystal_polyhedra():
        """A framework metal with its coordination polyhedra — the picture a
        crystallographer wants, and what VESTA gets used for."""
        win = new_window("crystal")
        win.open_path(SOLID_SOLUTION)
        page = win.crystal_page
        page.box_check.setChecked(True)
        page.poly_check.setChecked(True)       # the CONTROL, not the metadata
        # Pie spheres OFF for this shot only. They are on by default and they
        # are correct, but a shared site's wedges seen THROUGH a translucent
        # octahedron, on a 4.7 x 4.7 x 3.0 A cell, reads as a rendering fault
        # rather than as two features at once. The polyhedra are what this
        # picture is for.
        page.occupancy_check.setChecked(False)
        settle()
        win.viewport.fit_view()
        win.viewport.camera.distance *= 1.25   # room for the cell box corners
        shot("02-crystal-polyhedra",
             "CIF import that keeps the crystallography: space group and "
             "setting, symmetry operators, shared-site occupancies drawn as "
             "pie spheres, and closed coordination polyhedra with a "
             "VESTA-style specular sheen.")

    def packed_crystal():
        """Ferrocene: a molecular crystal, packed whole."""
        win = new_window("crystal")
        win.open_path(FERROCENE)
        win.crystal_page.box_check.setChecked(True)
        settle()
        win.viewport.fit_view()
        shot("03-packing",
             "A molecular crystal drawn as a crystal: molecules are wrapped "
             "by fragment and completed across the cell faces, never cut in "
             "half at a boundary.",
             viewport_only=True)

    def camera_view():
        """Round 56-58: a saved camera you compose in. The film back is a real
        framing — the projection follows it — with eight drag handles."""
        win = new_window("camera")
        win.open_path(FERROCENE)
        win.viewport.fit_view()
        win.on_place_camera()                  # sets `looking_through`
        settle()
        cam = win.scene.active_camera()
        if cam is None or win.viewport.looking_through is None:
            PROBLEMS.append("camera_view: not looking through a camera")
            return
        # Pull the frame in so the film back sits clearly inside the window
        # with its handles on screen. The wheel is the frame zoom, and it is
        # the ONLY control that resizes the picture (round 58).
        win.viewport.zoom_camera_frame(-7)
        # The zoom is a viewport action and does not refresh the properties
        # page, so without this the panel reads the value from when the camera
        # was placed while the viewport reads the real one — a screenshot that
        # contradicts itself.
        win._sync_all()
        shot("04-camera-view",
             "Camera objects ride the savefile. Looking through one really "
             "frames the shot: drag a border to reshape the film, Shift+drag "
             "to re-frame, the wheel to zoom the frame. F12 renders exactly "
             "this, and the Blender export carries the camera over.")

    def vibrations():
        """A baked ORCA normal mode, mid-cycle, with the mode list beside it —
        a still of a vibration says little on its own."""
        win = new_window("vibrations")
        if not os.path.exists(FREQ):
            return
        win.open_path(FREQ)
        obj = win._active_obj()
        modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
        if not modes:
            PROBLEMS.append("vibrations: no modes parsed")
            return
        win.on_animate_mode(modes[-1].index, amplitude=0.5)
        win.timeline.advance_frames(5)
        win._apply_timeline()
        win.viewport.fit_view()
        shot("05-vibrations",
             "ORCA normal modes baked onto the scene clock, so a vibration "
             "plays, interpolates, sits on the multi-track timeline and "
             "exports through the same path as a trajectory.")

    def run():
        try:
            print("writing to", OUT)
            for step in (viewport_and_outliner, crystal_polyhedra,
                         packed_crystal, camera_view, vibrations):
                try:
                    step()
                except Exception as exc:            # keep going: one bad shot
                    PROBLEMS.append("{}: {!r}".format(step.__name__, exc))
                    print("  ERROR in", step.__name__, repr(exc))
        finally:
            app.quit()

    QTimer.singleShot(700, run)
    app.exec()

    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# Screenshots\n\nGenerated by `tools/screenshots.py` — do "
                 "not edit by hand.\n\n")
        for tag, caption in WROTE:
            fh.write("### {}\n\n![{}]({}.png)\n\n{}\n\n".format(
                tag, tag, tag, caption))

    print("\n{} screenshot(s) written".format(len(WROTE)))
    if PROBLEMS:
        print("--- problems ---")
        for problem in PROBLEMS:
            print(" ", problem)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
