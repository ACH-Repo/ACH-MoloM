"""Shared plumbing for the two bundled pipeline add-ons.

Both the 🐞 debug page and the 🧪 sandbox page do the same thing with a
different algorithm: run a pipeline up to one stage and put THAT on screen,
rebuilt from the CIF text every time. This module is the part they share.

It lives in `molom/addons/` rather than in `molom/ui/` on purpose — nothing
in the application proper should have to know these pages exist. That is the
whole point of moving them out: `MainWindow` no longer mentions them, so
neither does anything you have to reason about while working on MoloM itself.
"""
import numpy as np

from molom.core.structure import Structure
from molom.ui.viewport import set_cell_reference

#: Both pages own ONE scene object between them and replace it on every stage
#: click, found by NAME rather than by a stored id — an undo between two
#: clicks rebuilds the scene and every id with it. One object for both because
#: they are alternative algorithms for the same thing, and seeing them at once
#: would be a picture of neither.
DEBUG_NAME = "Debug pipeline"
SANDBOX_NAME = "Sandbox pipeline"
PIPELINE_NAMES = (DEBUG_NAME, SANDBOX_NAME)


def pipeline_object(window):
    """The one object either pipeline page owns, whichever made it."""
    for obj in window.scene.objects:
        for name in PIPELINE_NAMES:
            if obj.name == name or obj.name.startswith(name + "."):
                return obj
    return None


def show_result(window, result, index, stages, page, name):
    """Put a pipeline stage's output on screen, replacing the last one."""
    window.push_undo()
    previous = pipeline_object(window)
    keep_camera = previous is not None and not getattr(
        window, "_pipeline_needs_fit", False)
    if previous is not None:
        window.scene.remove(previous.id)
    s = Structure(list(result.symbols), result.coords, name=name)
    s.bonds = [(int(i), int(j), int(o)) for i, j, o in result.bonds]
    # A stage can hand the viewport something no coordinate implies — the
    # composition of a shared site, which is what draws a pie sphere.
    s.metadata.update(getattr(result, "meta", None) or {})
    if result.cell is not None:
        s.metadata["cell"] = result.cell.to_dict()
        # Needs three atoms to fit a pose; below that the box is simply drawn
        # in the cell's own frame, which is right for the cell-only stage.
        set_cell_reference(s)
    obj = window.scene.add(s, name=name)
    window.active_id = obj.id
    window.viewport.show_cell = True
    window.viewport.set_selection([])
    window._sync_all()
    if not keep_camera:
        # Frame it ONCE per file. Re-fitting on every stage would move the
        # camera between the two pictures you are trying to compare.
        fit_view(window, result)
        window._pipeline_needs_fit = False
    page.show_result(result)
    stage = stages[max(0, min(int(index), len(stages) - 1))]
    window.statusBar().showMessage(
        "{} stage {} — {}: {} atoms, {} bonds".format(
            name.split()[0], int(index) + 1, stage.label,
            len(result.symbols), len(result.bonds)), 8000)


def fit_view(window, result):
    """Frame the CELL as well as the atoms.

    `fit_view` frames atoms, and the first stage deliberately has none — it
    would fall back to a 1 A radius at the origin and leave a 17 A box
    entirely off screen. The box is the subject here, so it is framed too.
    """
    points = []
    if result.cell is not None:
        points.append(np.asarray(result.cell.corners(), dtype=float))
    if len(result.symbols):
        points.append(np.asarray(result.coords, dtype=float))
    if not points:
        window.viewport.fit_view()
        return
    arr = np.vstack(points)
    center = arr.mean(axis=0)
    radius = float(np.linalg.norm(arr - center, axis=1).max()) + 1.5
    window.viewport.camera.fit(center, radius)
    window.viewport.update()


def install(window, key, glyph, tip, page, attr):
    """Add a page to the properties dock and remember it on the window."""
    setattr(window, attr, page)
    page.file_loaded.connect(
        lambda _p, w=window: setattr(w, "_pipeline_needs_fit", True))
    window.properties.add_page(key, glyph, tip, page)


def uninstall(window, key, attr):
    """Take the page away again and drop anything it left in the scene."""
    window.properties.remove_page(key)
    obj = pipeline_object(window)
    if obj is not None:
        window.scene.remove(obj.id)
        window._sync_all()
    if hasattr(window, attr):
        delattr(window, attr)
