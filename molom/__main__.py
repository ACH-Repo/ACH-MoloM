"""CLI entry point: `molom [FILE]` / `python -m molom [FILE]`.

`--selftest` exercises the core (elements, IO, bonding, meshes, camera,
picking) with no display and no GL — usable over SSH/CI to verify an install.

**The other two flags exist for ORCA Workbench**, which is the reason this
project started. OWB launches an external 3D program as `[program, file.xyz]`
and nothing more, so `molom mol.xyz` was already the whole of what its
`viewer_3d_path` needs. What it could not do was the two things that make the
integration worth having:

* `--select 3,7,11` picks atoms BY 0-BASED INDEX, which is ORCA's convention
  and therefore OWB's (`orca_workbench/core/geomspec.py`: "ORCA atom indices
  are 0-based"). Paste the indices out of a `%geom` constraint and MoloM shows
  you which atoms they are - and, for two, three or four of them, the bond,
  angle or dihedral they define, which is exactly what the constraint means.
* `--where` prints the launcher path to paste into OWB's program slots, since
  "point it at molom" is only easy once you know where the console script
  landed.
"""

import argparse
import os
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


def parse_indices(text):
    # type: (str) -> list
    """`"3,7,11"` or `"3 7 11"` -> `[3, 7, 11]`.

    Accepts commas or whitespace because a `%geom` block is written with
    spaces and a shell argument is easier with commas, and there is no reason
    to make the user care which. Raises ValueError on anything else rather
    than silently dropping a token - a constraint quietly missing an atom is
    worse than a refusal.
    """
    out = []
    for token in str(text or "").replace(",", " ").split():
        try:
            out.append(int(token))
        except ValueError:
            raise ValueError("not an atom index: {!r}".format(token))
    return out


def launcher_path():
    # type: () -> str
    """Where the `molom` console script is, or "" if there is not one.

    `shutil.which` FIRST, because that is what ORCA Workbench itself uses to
    decide whether a program is usable (`_on_path` in its molecules tab), and
    because a per-user pip install puts the script nowhere near
    `sys.executable` - on this machine the interpreter is in
    `C:\Program Files\Python310` and the launcher in
    `%APPDATA%\Python\Python310\Scripts`. Looking only beside the
    interpreter reported "not installed" for a perfectly working install.
    """
    import shutil
    import sysconfig
    found = shutil.which("molom")
    if found:
        return found
    for key in ("scripts", "purelib"):
        try:
            base = sysconfig.get_path(key)
        except Exception:                               # noqa: BLE001
            continue
        if not base:
            continue
        for name in ("molom.exe", "molom"):
            candidate = os.path.join(base, name)
            if os.path.isfile(candidate):
                return candidate
    return ""


def _where():
    # type: () -> int
    """Print the path to paste into ORCA Workbench's program slots."""
    found = launcher_path()
    if found:
        print(found)
        return 0
    print("{} -m molom".format(sys.executable))
    print("(no `molom` console script on PATH - the line above works as a "
          "command but ORCA Workbench wants a single program path, so "
          "`pip install -e .` to get one)", file=sys.stderr)
    return 0


def main(argv=None):
    # type: (list) -> int
    parser = argparse.ArgumentParser(
        prog="molom", description="MoloM - molecule viewer/builder")
    parser.add_argument("file", nargs="?", help="structure file to open")
    parser.add_argument("--selftest", action="store_true",
                        help="run the headless core selftest and exit")
    parser.add_argument("--select", metavar="i,j,k",
                        help="select these atoms of the opened file. "
                             "0-BASED, matching ORCA and so ORCA Workbench's "
                             "%%geom constraints; two to four of them also "
                             "report the bond, angle or dihedral")
    parser.add_argument("--where", action="store_true",
                        help="print the launcher path for ORCA Workbench's "
                             "3D viewer/editor slots and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.where:
        return _where()

    selection = []
    if args.select:
        try:
            selection = parse_indices(args.select)
        except ValueError as exc:
            parser.error(str(exc))
        if not args.file:
            parser.error("--select needs a file to select atoms in")

    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication
    from molom import resources
    from molom.ui.viewport import default_surface_format
    from molom.ui.app import MainWindow, apply_dark_theme

    QSurfaceFormat.setDefaultFormat(default_surface_format())
    # WINDOWS TASKBAR: a Python process inherits python.exe's taskbar identity,
    # so the window icon can be set correctly and the taskbar STILL shows the
    # Python logo and groups MoloM under "Python". The taskbar keys off the
    # AppUserModelID, not off the window icon, and it has to be set before any
    # window exists. Harmless and skipped everywhere else.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ACH.MoloM.viewer.1")
        except Exception:
            pass                      # cosmetic only; never worth failing on

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MoloM")
    # Set on the APPLICATION, so every window and dialog inherits it and the
    # taskbar entry gets it too. Without this the whole program shows the
    # generic Python logo, which is what a user sees before anything else.
    icon = resources.app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    apply_dark_theme(app)   # Blender-grey UI everywhere, not just the GL view
    from .ui import dialogs
    win = MainWindow()
    win.show_startup()   # maximized by default; Settings offers windowed
    if args.file:
        win.open_path(args.file)
        if selection:
            picked, missing = win.select_atom_indices(selection)
            note = "Selected atom{} {} (0-based)".format(
                "" if len(picked) == 1 else "s",
                ", ".join(str(i) for i in picked)) if picked else \
                "Nothing selected"
            if missing:
                note += " - no atom {} in this file".format(
                    ", ".join(str(i) for i in missing))
            win.statusBar().showMessage(note, 15000)
    else:
        win.load_default_scene()    # cubane, the way Blender opens on a cube
    # A name lookup or a crystal search runs in a worker thread that
    # deliberately outlives the dialog that started it (so cancelling one
    # cannot destroy a running QThread). It must not outlive the PROCESS:
    # tearing the interpreter down under a live thread is the same crash from
    # the other end, and it would land on quit, after everything worked.
    code = app.exec()
    dialogs.wait_for_workers()
    return code


if __name__ == "__main__":
    sys.exit(main())
