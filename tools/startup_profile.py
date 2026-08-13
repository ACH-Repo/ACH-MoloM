"""Where MoloM's startup time actually goes.

    python tools/startup_profile.py            # the breakdown
    python tools/startup_profile.py --imports  # slowest imports only

Christian, 2026-08-11: "Add periodic launch time tests. The startup is getting
slow." Nothing in the suite would ever notice: 1378 tests build `MainWindow()`
over and over and none of them times it, so startup can regress by half a
second a round and only ever be felt.

The point of this script is that "startup" is THREE different problems and one
number cannot tell them apart:

  1. IMPORT TIME     - paid before a single line of MoloM runs. Usually a heavy
                       third-party module pulled in at module scope.
  2. CONSTRUCTION    - `MainWindow()`: every widget, the operator registry, the
                       add-on scan, the periodic table's 118 painted cells.
  3. FIRST PAINT     - creating the GL context, compiling shaders, uploading
                       the first buffers.

A wall-clock number here is machine-specific and this project runs on two very
different machines, so this prints a breakdown for a human to read. The
REGRESSION guards that can be asserted portably live in
`tests/test_round65_startup.py` instead - they check structure ("core must not
import rdkit"), not milliseconds.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _t():
    return time.perf_counter()


def slowest_imports(limit=14):
    """`python -X importtime`, summarised. The cumulative column is the one
    that matters: it includes everything a module drags in with it."""
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import molom.ui.app"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rows = []
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        if not line.startswith("import time:"):
            continue
        body = line[len("import time:"):]
        parts = body.split("|")
        if len(parts) < 3:
            continue
        try:
            cumulative = int(parts[1].strip())
        except ValueError:
            continue
        rows.append((cumulative, parts[2].strip()))
    rows.sort(reverse=True)
    # Only top-level names: the nested ones are already inside their parent's
    # cumulative figure, so listing them is double counting.
    seen, out = set(), []
    for micros, name in rows:
        root = name.split(".")[0]
        if root in seen:
            continue
        seen.add(root)
        out.append((micros / 1000.0, name))
        if len(out) >= limit:
            break
    return out


def main(argv):
    if "--imports" in argv:
        print("slowest imports of `molom.ui.app` (cumulative ms)")
        for ms, name in slowest_imports():
            print("  {:8.1f}  {}".format(ms, name))
        return 0

    print("MoloM startup breakdown  (python {}.{})".format(*sys.version_info[:2]))
    print("-" * 58)

    t0 = _t()
    import molom                                            # noqa: F401
    t_pkg = _t() - t0

    t0 = _t()
    from molom import core                                  # noqa: F401
    from molom.core import io, cif, spacegroups             # noqa: F401
    t_core = _t() - t0

    t0 = _t()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QSurfaceFormat                # noqa: F401
    t_qt = _t() - t0

    t0 = _t()
    from molom.ui import app as app_mod
    t_ui = _t() - t0

    t0 = _t()
    from molom.core import addons as addons_mod
    found = addons_mod.discover() if hasattr(addons_mod, "discover") else []
    t_addons = _t() - t0

    application = QApplication.instance() or QApplication(sys.argv[:1])

    t0 = _t()
    win = app_mod.MainWindow()
    t_win = _t() - t0

    t0 = _t()
    win.load_default_scene()
    t_scene = _t() - t0

    t0 = _t()
    win.resize(1000, 750)
    win.show()
    for _ in range(6):
        application.processEvents()
    t_show = _t() - t0

    rows = [("import molom (package)", t_pkg),
            ("import molom.core (+ spglib)", t_core),
            ("import PySide6", t_qt),
            ("import molom.ui.app", t_ui),
            ("add-on scan ({} found)".format(len(found)), t_addons),
            ("MainWindow()", t_win),
            ("load_default_scene()", t_scene),
            ("show() + first paint", t_show)]
    total = sum(v for _n, v in rows)
    for name, value in rows:
        bar = "#" * int(round(40.0 * value / max(total, 1e-9)))
        print("  {:<30} {:7.1f} ms  {}".format(name, value * 1000.0, bar))
    print("-" * 58)
    print("  {:<30} {:7.1f} ms".format("TOTAL", total * 1000.0))
    print("\nRun with --imports to see which module costs the most.")
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
