"""CLI entry point: `molom [FILE]` / `python -m molom [FILE]`.

`--selftest` exercises the core (elements, IO, bonding, meshes, camera,
picking) with no display and no GL — usable over SSH/CI to verify an install.
"""

import argparse
import sys


def _selftest():
    # type: () -> int
    import numpy as np
    from molom.core import bonding, edits, elements, io, measure, meshes, picking
    from molom.core.camera import Camera
    from molom.core.structure import Structure

    water = [("O", 0.0, 0.0, 0.117), ("H", 0.0, 0.757, -0.469),
             ("H", 0.0, -0.757, -0.469)]
    s = Structure.from_atoms(water, name="water")
    bonding.perceive_structure_bonds(s)
    assert len(s.bonds) == 2, s.bonds
    assert abs(measure.angle(s.coords[1], s.coords[0], s.coords[2]) - 104.5) < 3.0
    edits.add_atom(s, "H", edits.suggested_position(s, bond_to=0, symbol="H"),
                   bond_to=0)
    assert s.n_atoms == 4 and len(s.bonds) == 3
    v, n, f = meshes.icosphere(2)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-6)
    cam = Camera()
    cam.fit(s.centroid(), s.bounding_radius())
    view = cam.view_matrix()
    proj = cam.projection_matrix(640, 480)
    origin, direction = picking.ray_from_screen(320, 240, 640, 480, view, proj)
    hit = picking.pick_sphere(origin, direction, s.coords,
                              np.full(s.n_atoms, 0.5))
    assert hit is not None
    print("elements:", elements.ELEMENT_COUNT, "entries;",
          "C covalent", elements.radius_covalent(6), "A")
    print("import formats:", len(io.SUPPORTED_IMPORT_FORMATS))
    print("selftest OK")
    return 0


def main(argv=None):
    # type: (list) -> int
    parser = argparse.ArgumentParser(
        prog="molom", description="MoloM - molecule viewer/builder")
    parser.add_argument("file", nargs="?", help="structure file to open")
    parser.add_argument("--selftest", action="store_true",
                        help="run the headless core selftest and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication
    from molom.ui.viewport import default_surface_format
    from molom.ui.app import MainWindow, apply_dark_theme

    QSurfaceFormat.setDefaultFormat(default_surface_format())
    app = QApplication(sys.argv[:1])
    app.setApplicationName("MoloM")
    apply_dark_theme(app)   # Blender-grey UI everywhere, not just the GL view
    win = MainWindow()
    win.show_startup()   # maximized by default; Settings offers windowed
    if args.file:
        win.open_path(args.file)
    else:
        win.load_default_scene()    # cubane, the way Blender opens on a cube
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
