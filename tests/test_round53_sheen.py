"""Round 53: VESTA's sheen on a polyhedron, and three smaller things.

Christian: "VESTA also adds some small reflectiveness to polyhedra that shows
up when you rotate the view so that the normal of a polyhedron face is
directed straight at the observer." Plus: the lasso felt lost, and the view
radios could not be driven with several CIFs open.
"""

import os

import numpy as np
import pytest

from molom.core import polyhedra

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OXIDE = os.path.join(DATA, "cod_1547149_solid_solution.cif")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


def _octahedron(scale=2.0):
    pts = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                    [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float) * scale
    return [{"vertices": pts, "faces": polyhedra.hull_faces(pts),
             "color": (0.2, 0.5, 0.9), "centre": 0, "symbol": "Nb",
             "donors": []}]


def _rotate(axis, angle):
    k = np.asarray(axis, dtype=float)
    k = k / np.linalg.norm(k)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(angle) * kx + (1 - np.cos(angle)) * kx @ kx


# ------------------------------------------------------------------ the sheen
def test_the_sheen_peaks_on_the_face_that_faces_you():
    """The whole effect: a highlight that appears as a face normal comes into
    line with the view, and slides off as it turns away."""
    faces = polyhedra.face_arrays(_octahedron())
    n0 = faces["normals"][0] / np.linalg.norm(faces["normals"][0])
    axis = np.cross(n0, [0.0, 0.0, 1.0])
    seen = []
    for degrees in (0, 10, 20, 30, 45):
        eye = (_rotate(axis, np.radians(degrees)) @ n0) * 40.0
        seen.append(float(polyhedra.specular_from_faces(faces, eye)[0][0]))
    assert seen[0] == pytest.approx(polyhedra.SPECULAR, rel=1e-6)
    assert seen == sorted(seen, reverse=True)      # monotone falling
    # ...and it is a HIGHLIGHT, not a wash: mostly gone within 30 degrees
    assert seen[3] < 0.1 * seen[0]
    assert seen[4] < 0.01 * seen[0]


def test_the_sheen_is_white_so_it_reads_as_a_reflection():
    faces = polyhedra.face_arrays(_octahedron())
    n0 = faces["normals"][0] / np.linalg.norm(faces["normals"][0])
    glint = polyhedra.specular_from_faces(faces, n0 * 40.0)
    assert np.allclose(glint[0], glint[0][0])      # equal in r, g and b


def test_turning_it_off_costs_nothing():
    faces = polyhedra.face_arrays(_octahedron())
    glint = polyhedra.specular_from_faces(faces, np.array([0.0, 0.0, 40.0]),
                                          specular=0.0)
    assert glint.shape[1] == 3
    assert not glint.any()


def test_a_tighter_exponent_narrows_the_highlight():
    """`shininess` is what keeps it a highlight rather than a bloom."""
    faces = polyhedra.face_arrays(_octahedron())
    n0 = faces["normals"][0] / np.linalg.norm(faces["normals"][0])
    axis = np.cross(n0, [0.0, 0.0, 1.0])
    eye = (_rotate(axis, np.radians(20.0)) @ n0) * 40.0
    broad = polyhedra.specular_from_faces(faces, eye, 0.3, 8.0)[0][0]
    tight = polyhedra.specular_from_faces(faces, eye, 0.3, 48.0)[0][0]
    assert tight < broad


def test_the_diffuse_half_still_never_brightens_past_the_element_colour():
    """Round 48's invariant, and the reason the sheen is a SEPARATE array: a
    grazing face brightening toward white is the Fresnel mistake, and it
    washes the colour out exactly where two faces meet."""
    polys = _octahedron()
    base = np.asarray(polys[0]["color"], dtype=float)
    colours = polyhedra.shade_colors(polys, np.array([0.0, 0.0, 40.0]))
    assert np.all(colours <= base + 1e-9)


def test_one_facing_term_feeds_both_halves():
    """`|N.V|` is the only camera-dependent quantity, so it is computed once
    and shared — the per-frame cost of the sheen is one power."""
    faces = polyhedra.face_arrays(_octahedron())
    eye = np.array([5.0, -3.0, 40.0])
    facing = polyhedra.facing_from_faces(faces, eye)
    assert len(facing) == len(faces["normals"])
    assert np.all((facing >= 0.0) & (facing <= 1.0 + 1e-12))
    expected = polyhedra.SPECULAR * facing ** polyhedra.SHININESS
    assert np.allclose(polyhedra.specular_from_faces(faces, eye)[::3, 0],
                       expected)


def test_a_degenerate_face_is_still_finite():
    poly = [{"vertices": np.zeros((3, 3)), "faces": [(0, 1, 2)],
             "color": (0.5, 0.5, 0.5), "centre": 0, "symbol": "Mg",
             "donors": []}]
    faces = polyhedra.face_arrays(poly)
    assert np.all(np.isfinite(polyhedra.specular_from_faces(faces,
                                                            np.zeros(3))))


def test_an_empty_scene_gives_an_empty_array():
    empty = polyhedra.face_arrays([])
    assert polyhedra.specular_from_faces(empty, np.zeros(3)).shape == (0, 3)


def test_the_defaults_are_the_measured_ones():
    """Chosen by rendering the same frame six ways and differencing them:
    0.30/24 lit 15.6% of the frame at a peak gain of 0.89, which washes the
    element colour out on the faces you most need to read."""
    assert polyhedra.SPECULAR == pytest.approx(0.15)
    assert polyhedra.SHININESS == pytest.approx(32.0)


# ------------------------------------------------------------------- the UI
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def test_the_viewport_owns_the_sheen_settings(win):
    """Module-level constants cannot be tuned at run time — a default
    ARGUMENT binds its value once at import and never looks at the name
    again, which is exactly why the first attempt to A/B this produced two
    identical frames."""
    vp = win.viewport
    assert vp.polyhedra_specular == pytest.approx(polyhedra.SPECULAR)
    assert vp.polyhedra_shininess == pytest.approx(polyhedra.SHININESS)
    vp.polyhedra_specular = 0.0          # and it is per viewport, so tunable
    assert vp.polyhedra_specular == 0.0


def test_the_lasso_has_a_button_of_its_own(win):
    """It was reachable only by `Shift+Space, L` or F3, so nothing on screen
    said it still existed — which is what "did we lose lasso select?" was."""
    assert "lasso" in win.toolbar.buttons
    win._on_tool_clicked("lasso")
    assert win.viewport._select_tool == "lasso"
    win._on_tool_clicked("lasso")        # ...and it toggles back off
    assert win.viewport._select_tool is None


def test_arming_the_lasso_disarms_the_other_tools(win):
    from molom.core import build
    obj = win.scene.add(build.cubane(), name="cubane")
    win.active_id = obj.id
    win.viewport.set_mode("edit", obj.id)
    win.viewport.set_draw_tool(True)
    win._on_tool_clicked("lasso")
    assert not win.viewport.draw_tool_active
    assert win.viewport._select_tool == "lasso"


def test_the_graphics_report_is_registered(win):
    op = win.ops.get("graphics_info")
    assert op is not None
    assert "gpu" in op.aliases
    assert not win.ops.duplicate_keys()
    # offscreen has no live context, and it must say so rather than raise
    assert isinstance(win.viewport.graphics_info(), dict)


def test_the_viewport_asks_for_its_own_surface_format(win):
    """`QSurfaceFormat.setDefaultFormat` only runs under `python -m molom`, so
    anything else building a window got the driver's default — measured as a
    compatibility profile with no multisampling."""
    from molom.ui.viewport import default_surface_format
    want = default_surface_format()
    got = win.viewport.format()
    assert got.majorVersion() == want.majorVersion()
    assert got.profile() == want.profile()
    assert got.samples() == want.samples()


def test_the_view_radios_follow_the_active_crystal(win):
    """Christian: "I cannot toggle the different view states of cifs when
    multiple cifs are imported." The radio was set once at construction, so
    with two crystals open it kept whichever mode the LAST one was put into —
    and a radio that is already checked emits nothing, so clicking the mode
    you wanted did nothing at all."""
    win.open_path(FERROCENE)
    a = win._active_obj()
    win.open_path(OXIDE)
    b = win._active_obj()
    page = win.crystal_page
    page.asym_radio.setChecked(True)
    assert b.structure.metadata["cell_view"] == "asym"

    win.active_id = a.id
    win._sync_crystal_page()
    assert page.cell_radio.isChecked()          # A is still a full cell
    page.asym_radio.setChecked(True)            # ...and this now fires
    assert win.scene.get(a.id).structure.metadata["cell_view"] == "asym"

    win.active_id = b.id
    win._sync_crystal_page()
    assert page.asym_radio.isChecked()
