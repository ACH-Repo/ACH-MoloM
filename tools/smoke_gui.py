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

    def run():
        try:
            grab("00_startup")
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
    raise SystemExit(main(given))
