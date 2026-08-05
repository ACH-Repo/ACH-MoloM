"""Round 37: the Blender export, and the resolver cascade that stopped
cascading.

The export is tested at three levels, because a generated program can be wrong
in three different ways: the DATA can be wrong (`collect`), the SOURCE can be
unparseable (`compile`, plus `ast` on the emitted literals), and the SEMANTICS
can be wrong in Blender — which no offline test can reach, so that part was
verified by actually running the script in Blender 5.1 and looking at the
render.
"""

import ast

import numpy as np
import pytest

from molom.core import blender_export as bx
from molom.core import build, cif
from molom.core import style as style_mod
from molom.core.camera import Camera
from molom.core.scene import Scene
from molom.core.structure import Structure


@pytest.fixture
def scene():
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    return sc


@pytest.fixture
def cam():
    c = Camera()
    c.fit(np.zeros(3), 3.0)
    return c


# ------------------------------------------------------------------ colour
def test_colours_are_converted_to_linear():
    """Blender's sockets are linear. Dropping sRGB in raw renders washed out
    — mid grey is the case that shows it."""
    assert bx.srgb_to_linear(0.0) == 0.0
    assert bx.srgb_to_linear(1.0) == pytest.approx(1.0)
    assert bx.srgb_to_linear(0.5) == pytest.approx(0.2140, abs=1e-3)
    assert bx.srgb_to_linear(0.02) == pytest.approx(0.02 / 12.92)


def test_a_custom_colour_gets_its_own_material(scene, cam):
    obj = scene.objects[0]
    obj.atom_colors[0] = (1.0, 0.0, 0.2)
    data = bx.collect(scene, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=cam)
    names = [m["name"] for m in data["materials"]]
    assert "MoloM C" in names and "MoloM H" in names
    assert "MoloM C (ff0033)" in names        # keyed by the colour itself
    custom = [m for m in data["materials"] if "ff0033" in m["name"]][0]
    assert custom["color"][0] == pytest.approx(1.0)


def test_two_atoms_painted_alike_share_one_material(scene, cam):
    obj = scene.objects[0]
    obj.atom_colors[0] = (0.2, 0.4, 1.0)
    obj.atom_colors[1] = (0.2, 0.4, 1.0)
    data = bx.collect(scene, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=cam)
    assert sum("(" in m["name"] for m in data["materials"]) == 1


def test_metals_are_metallic_only_when_asked():
    s = Structure.from_atoms([("Zn", 0.0, 0.0, 0.0), ("O", 2.0, 0.0, 0.0)])
    s.bonds = [(0, 1, 1)]
    sc = Scene()
    sc.add(s, name="zno")
    data = bx.collect(sc, style_mod.BALL_AND_STICK, bx.ExportOptions())
    by_name = {m["name"]: m for m in data["materials"]}
    assert by_name["MoloM Zn"]["metallic"] == 1.0
    assert by_name["MoloM O"]["metallic"] == 0.0
    plain = bx.collect(sc, style_mod.BALL_AND_STICK,
                       bx.ExportOptions(metallic_metals=False))
    assert {m["name"]: m for m in plain["materials"]}["MoloM Zn"][
        "metallic"] == 0.0


# ---------------------------------------------------------------- geometry
def test_what_the_viewport_hides_is_not_exported(scene, cam):
    obj = scene.objects[0]
    full = bx.collect(scene, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=cam)
    obj.hide_atoms([8, 9, 10, 11, 12, 13, 14, 15])     # the hydrogens
    part = bx.collect(scene, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=cam)
    assert len(part["atoms"]) == len(full["atoms"]) - 8
    # ...and their bonds go with them, or the sticks hang in mid-air.
    assert len(part["bonds"]) < len(full["bonds"])


def test_per_atom_sphere_size_is_carried_over(scene, cam):
    obj = scene.objects[0]
    obj.atom_scales[0] = 0.5
    data = bx.collect(scene, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=cam)
    radii = sorted(a[2] for a in data["atoms"] if a[0] == "MoloM C")
    assert radii[0] == pytest.approx(radii[-1] * 0.5, rel=1e-6)


def test_vdw_style_exports_spheres_and_no_bonds(scene, cam):
    data = bx.collect(scene, style_mod.VDW, bx.ExportOptions(), camera=cam)
    assert data["atoms"] and not data["bonds"]


def test_each_bond_is_two_half_cylinders_coloured_by_its_atoms(scene, cam):
    data = bx.collect(scene, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=cam)
    # cubane: 12 ring bonds + 8 C-H, all single -> 20 bonds, 40 halves
    assert len(data["bonds"]) == 40
    ch = [b for b in data["bonds"] if b[0] == "MoloM H"]
    assert len(ch) == 8


def test_the_unit_cell_becomes_twelve_edges_in_three_colours():
    cell = cif.Cell(5.0, 6.0, 7.0, 90.0, 90.0, 90.0)
    edges, mats = bx.cell_edges(cell, 0.05)
    assert len(edges) == 12
    assert set(mats) == {"MoloM cell a", "MoloM cell b", "MoloM cell c"}
    assert sum(1 for e in edges if e[0] == "MoloM cell a") == 4


# ------------------------------------------------------------------ camera
def test_the_camera_looks_where_the_viewport_looks(cam):
    setup = bx.camera_setup(cam, 800, 600)
    m = np.asarray(setup["matrix"], dtype=float)
    eye = m[:3, 3]
    # Blender's camera looks down its local -Z. That axis must point from the
    # eye at what the viewport is orbiting.
    forward = -m[:3, 2]
    to_target = np.asarray(setup["target"], dtype=float) - eye
    assert np.allclose(forward / np.linalg.norm(forward),
                       to_target / np.linalg.norm(to_target), atol=1e-6)
    assert np.linalg.norm(to_target) == pytest.approx(cam.distance, rel=1e-6)
    # ...and it is a proper right-handed frame, or the render comes out
    # mirrored, which is the one error nobody notices until it is published.
    r = m[:3, :3]
    assert np.linalg.det(r) == pytest.approx(1.0, abs=1e-6)
    assert np.allclose(r.T @ r, np.eye(3), atol=1e-6)


def test_the_camera_keeps_the_viewport_up_direction(cam):
    """MoloM's turntable has no roll, so the camera's +Y must have no roll
    either: it stays in the plane containing world Z and the view axis."""
    m = np.asarray(bx.camera_setup(cam, 800, 600)["matrix"], dtype=float)
    right = m[:3, 0]
    assert float(right[2]) == pytest.approx(0.0, abs=1e-9)


def test_an_orthographic_viewport_exports_an_orthographic_camera(cam):
    cam.orthographic = True
    setup = bx.camera_setup(cam, 800, 600)
    assert setup["type"] == "ORTHO"
    half = np.tan(np.radians(cam.FOV_Y) / 2.0) * cam.distance
    assert setup["ortho_scale"] == pytest.approx(2 * half, rel=1e-6)


# ------------------------------------------------------------------ lights
def test_the_lamp_rig_scales_with_the_scene(cam):
    setup = bx.camera_setup(cam, 800, 600)
    small = bx.light_rig("three_point", setup, 3.0)
    big = bx.light_rig("three_point", setup, 30.0)
    assert len(small) == len(big) == 3
    # Inverse-square: ten times further out wants a hundred times the power,
    # or a framework renders black on settings that flattered a molecule.
    assert big[0]["energy"] == pytest.approx(small[0]["energy"] * 100.0,
                                             rel=1e-6)


def test_no_rig_means_no_lamps(cam):
    setup = bx.camera_setup(cam, 800, 600)
    assert bx.light_rig("none", setup, 5.0) == []
    assert len(bx.light_rig("key", setup, 5.0)) == 1


def test_a_sun_does_not_scale_with_distance(cam):
    """A sun's strength is irradiance, not power — scaling it by distance
    would be wrong twice over."""
    setup = bx.camera_setup(cam, 800, 600)
    near = bx.light_rig("sun", setup, 3.0)[0]
    far = bx.light_rig("sun", setup, 30.0)[0]
    assert near["energy"] == far["energy"]


def test_an_hdri_halves_the_lamps(scene, cam):
    """Both at full power is what blew the hydrogens out in the first
    render."""
    lit = bx.collect(scene, style_mod.BALL_AND_STICK,
                     bx.ExportOptions(hdri="", lights="key"), camera=cam)
    hdri = bx.collect(scene, style_mod.BALL_AND_STICK,
                      bx.ExportOptions(hdri="forest", lights="key"),
                      camera=cam)
    assert hdri["lights"][0]["energy"] == pytest.approx(
        lit["lights"][0]["energy"] * 0.5, rel=1e-6)


# ------------------------------------------------------------------ script
def _script(scene, cam, **kw):
    opts = bx.ExportOptions(**kw)
    data = bx.collect(scene, style_mod.BALL_AND_STICK, opts, camera=cam)
    return bx.build_script(data, opts, title="test", version="0",
                           basename="t.py", summary=bx.summarise(data)), data


def test_the_generated_script_is_valid_python(scene, cam):
    src, _ = _script(scene, cam)
    compile(src, "generated", "exec")         # would raise on a bad literal


def test_the_generated_script_is_pure_ascii(scene, cam):
    """It leaves here as text and may be written or copied by anything. One
    step assuming cp1252 turns an em dash into a byte Blender refuses to
    parse, in a file nobody has edited — which is exactly what happened."""
    src, _ = _script(scene, cam, hdri="studio")
    src.encode("ascii")
    assert "\u2014" not in src


def test_a_unicode_molecule_name_cannot_break_the_script(cam):
    sc = Scene()
    sc.add(build.cubane(), name="cub\u00e5ne \u2014 \u00c5")
    opts = bx.ExportOptions()
    data = bx.collect(sc, style_mod.BALL_AND_STICK, opts, camera=cam)
    src = bx.build_script(data, opts, title=sc.objects[0].name)
    src.encode("ascii")
    compile(src, "generated", "exec")


def test_the_emitted_data_matches_what_collect_produced(scene, cam):
    """Read the literals back out of the SOURCE, so a formatting bug in the
    emitter cannot hide behind a correct `collect`."""
    scene.objects[0].atom_colors[0] = (1.0, 0.0, 0.2)
    src, data = _script(scene, cam)
    tree = ast.parse(src)
    got = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0],
                                                       ast.Name):
            name = node.targets[0].id
            if name in ("ATOMS", "BONDS", "MATERIALS", "CAMERA", "LIGHTS",
                        "OPTIONS"):
                got[name] = ast.literal_eval(node.value)
    assert len(got["ATOMS"]) == len(data["atoms"])
    assert len(got["BONDS"]) == len(data["bonds"])
    assert [m["name"] for m in got["MATERIALS"]] == \
        [m["name"] for m in data["materials"]]
    assert got["CAMERA"]["matrix"] == data["camera"]["matrix"]
    assert got["ATOMS"][0][0] == data["atoms"][0][0]
    assert got["OPTIONS"]["clear_scene"] is True     # a real bool, not "True"


def test_the_script_carries_no_absolute_hdri_path(scene, cam):
    """The HDRI is resolved on the machine that RUNS it, so the script works
    for anyone with any Blender."""
    src, _ = _script(scene, cam, hdri="forest")
    assert "studiolights" in src and "system_resource" in src
    assert "C:\\\\" not in src


def test_showing_the_hdri_turns_off_the_transparent_film(scene, cam):
    src, _ = _script(scene, cam, hdri="forest", hdri_visible=True,
                     transparent=True)
    tree = ast.parse(src)
    opts = [ast.literal_eval(n.value) for n in tree.body
            if isinstance(n, ast.Assign) and n.targets[0].id == "OPTIONS"][0]
    assert opts["transparent"] is False


def test_unknown_options_are_rejected():
    """A typo in an option name must not be silently ignored — it would look
    like the setting simply had no effect."""
    with pytest.raises(TypeError):
        bx.ExportOptions(hrdi="forest")


# =================================================================== resolver
import urllib.error


def _fake(opsin=None, pubchem=None, cactus=None, autocomplete=None):
    """A getter with one switch per service. `None` means 'unreachable'."""
    def get(url):
        if "opsin" in url:
            if opsin is None:
                raise urllib.error.URLError("timed out")
            return opsin
        if "cactus" in url:
            if cactus is None:
                raise urllib.error.URLError("timed out")
            return cactus
        if "autocomplete" in url:
            return autocomplete or (200, '{"dictionary_terms": {}}')
        if pubchem is None:
            raise urllib.error.URLError("timed out")
        if "cids/JSON" in url:
            return pubchem
        return (200, '{"PropertyTable": {"Properties": '
                     '[{"IsomericSMILES": "CCO"}]}}')
    return get


def test_a_dead_opsin_falls_through_to_pubchem():
    """The reported bug: OPSIN timing out returned an error instead of
    trying the next tier, so import-by-name failed for names PubChem knows
    perfectly well."""
    from molom.core import resolve
    res = resolve.resolve("ethanol", get=_fake(
        pubchem=(200, '{"IdentifierList": {"CID": [702]}}')))
    assert res.ok and res.smiles == "CCO"
    assert "PubChem" in res.source
    assert "OPSIN unreachable" in (res.note or "")   # said, not swallowed


def test_cactus_is_the_third_tier():
    from molom.core import resolve
    res = resolve.resolve("ethanol", get=_fake(
        pubchem=(200, '{"IdentifierList": {"CID": []}}'),
        cactus=(200, "CCO\n")))
    assert res.ok and res.source == "NIH CACTUS resolver"


def test_cactus_html_is_not_mistaken_for_a_smiles():
    """It answers a miss with a web page and HTTP 200, not a 404."""
    from molom.core import resolve
    res = resolve.resolve("notathing", get=_fake(
        pubchem=(200, '{"IdentifierList": {"CID": []}}'),
        cactus=(200, "<html><body>Page not found</body></html>")))
    assert not res.ok
    assert "no match" in res.error


def test_every_service_down_reports_all_of_them_and_does_not_raise():
    from molom.core import resolve
    res = resolve.resolve("ethanol", get=_fake())
    assert not res.ok
    for name in ("OPSIN", "PubChem", "CACTUS"):
        assert name in res.error


def test_an_injected_getter_never_trips_the_circuit_breaker():
    """The breaker is for real outages. A test that fakes one must not leave
    the next test skipping a tier."""
    from molom.core import resolve
    resolve.reset_service_state()
    resolve.resolve("ethanol", get=_fake())
    assert resolve._DOWN == {}


def test_the_breaker_skips_a_service_that_just_failed():
    from molom.core import resolve
    resolve.reset_service_state()
    resolve._mark_down("opsin", True)
    assert resolve._is_down("opsin")
    tried = []

    def get(url):
        tried.append(url)
        if "cids/JSON" in url:
            return 200, '{"IdentifierList": {"CID": [702]}}'
        return (200, '{"PropertyTable": {"Properties": '
                     '[{"IsomericSMILES": "CCO"}]}}')

    res = resolve.resolve("ethanol", get=get)
    assert res.ok
    assert not any("opsin" in u for u in tried)      # not even attempted
    resolve.reset_service_state()


def test_the_probe_covers_every_tier():
    from molom.core import resolve
    rows = resolve.check_services(get=lambda url: (200, "ok"))
    labels = [r[0] for r in rows]
    assert any("OPSIN" in x for x in labels)
    assert any("PubChem" in x for x in labels)
    assert any("CACTUS" in x for x in labels)


def test_a_bare_timeout_is_normalised_to_urlerror(monkeypatch):
    """A READ timeout raises socket.timeout, not URLError, and would sail
    straight through every `except urllib.error.URLError` in this module."""
    from molom.core import resolve

    def boom(*_a, **_k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(resolve.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.URLError):
        resolve._http_get("https://example.invalid/x")


# ======================================================================= UI
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.load_default_scene()
    return w


def test_the_operator_is_registered_and_clash_free(win):
    op = win.ops.get("export_blender")
    assert op is not None and op.key == "Ctrl+Shift+B"
    assert win.ops.duplicate_keys() == {}


def test_the_app_builds_a_script_for_the_live_scene(win):
    from molom.core import blender_export as bxx
    rgb = (0.1, 0.9, 0.3)
    win.scene.objects[0].atom_colors[3] = rgb
    src = win.blender_script(bxx.ExportOptions(), "x.py")
    compile(src, "app", "exec")
    assert bxx.material_name("C", rgb, True) in src   # the painted atom's
    assert "MoloM camera" in src


def test_the_script_camera_follows_the_viewport(win):
    """Orbit, then export: the camera has to have moved with it, or 'match
    the viewport' is a lie."""
    import ast
    from molom.core import blender_export as bxx

    def matrix():
        src = win.blender_script(bxx.ExportOptions(), "x.py")
        node = [n for n in ast.parse(src).body
                if isinstance(n, ast.Assign) and n.targets[0].id == "CAMERA"]
        return ast.literal_eval(node[0].value)["matrix"]

    before = matrix()
    win.viewport.camera.rotate(120.0, 40.0)
    assert matrix() != before


def test_turning_the_camera_match_off_writes_no_camera(win):
    import ast
    from molom.core import blender_export as bxx
    src = win.blender_script(bxx.ExportOptions(match_viewport=False), "x.py")
    node = [n for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and n.targets[0].id == "CAMERA"]
    assert ast.literal_eval(node[0].value) == {}
    compile(src, "app", "exec")


def test_the_dialog_round_trips_its_options(win):
    from molom.core import blender_export as bxx
    from molom.ui.dialogs import BlenderExportDialog
    opts = bxx.ExportOptions(hdri="studio", lights="key", samples=64,
                             engine="BLENDER_EEVEE_NEXT", roughness=0.5,
                             view_transform="AgX", collection="Figure")
    dlg = BlenderExportDialog(win, opts, "cubane: 16 atoms", (640, 480))
    got = dlg.options()
    assert got.hdri == "studio"
    assert got.lights == "key"
    assert got.samples == 64
    assert got.engine == "BLENDER_EEVEE_NEXT"
    assert got.roughness == pytest.approx(0.5)
    assert got.view_transform == "AgX"
    assert got.collection == "Figure"
    assert got.resolution == (640, 480)      # the viewport's own size
    dlg.close()


def test_the_dialog_offers_no_hdri_and_that_reaches_the_options(win):
    from molom.ui.dialogs import BlenderExportDialog
    dlg = BlenderExportDialog(win, None, "", (640, 480))
    dlg.hdri_combo.setCurrentText(BlenderExportDialog._HDRI_NONE)
    assert dlg.options().hdri == ""
    assert not dlg.hdri_strength.isEnabled()   # nothing left for it to scale
    dlg.close()


def test_export_options_survive_a_restart(win):
    """They are written to QSettings on export (sandboxed by conftest), so a
    figure style set up once does not have to be set up again."""
    from molom.core import blender_export as bxx
    opts = bxx.ExportOptions(hdri="night", samples=333, metallic_metals=False,
                             collection="Paper")
    for key in win._BLENDER_KEYS:
        win.settings.setValue("blender_" + key, getattr(opts, key))
    back = win._blender_options()
    assert back.hdri == "night"
    assert back.samples == 333
    assert back.metallic_metals is False
    assert back.collection == "Paper"
