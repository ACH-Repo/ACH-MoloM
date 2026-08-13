"""Round 62: meta-atom optimisation, monodentate templating, bonds, the logo.

Christian, 2026-08-12, after retesting the ligand templates:
* "What breaks is the optimization with a meta atom. The bonds do not keep the
  length they are set with. They become incredibly short."
* "meta atoms should just have the element color of the regular element they
  are using as a placeholder."
* "monodentate ligands are a nice exception ... allows for coordination for
  multiple hydrogens at once"
* "bonds cannot be used to select mols via double click when hovering over them
  in object mode"
* the logo, and Export animation in the File menu
"""

import inspect
import os

import numpy as np
import pytest

from molom.core import forcefield as ff_mod
from molom.core import meta as meta_mod
from molom.core import templates as tpl_mod
from molom.core.structure import Structure


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def _bent_meta_complex(distance=2.0, collapsed=False):
    """A bent meta centre with two donors, optionally collapsed onto it."""
    r = 0.3 if collapsed else distance
    coords = np.array([[0.0, 0.0, 0.0],
                       [r, 0.0, 0.0],
                       [-r * 0.5, r * 0.866, 0.0]])
    s = Structure(["Xx", "O", "O"], coords)
    s.bonds = [(0, 1, 1), (0, 2, 1)]
    meta_mod.set_meta(s, 0, meta_mod.MetaAtom(
        geometry="bent", distance=distance, element="Fe", locked=True))
    return s


# ------------------------------------------------- the optimisation itself
def test_the_force_field_never_sees_the_dummy_element():
    """Both RDKit tiers refuse an unknown element outright, which is what sent
    every meta complex to the one backend that ignored `fixed`."""
    s = _bent_meta_complex()
    resolved = meta_mod.resolved_symbols(s)
    assert "Xx" not in resolved
    assert resolved[0] == "Fe"


def test_openbabel_optimize_ACCEPTS_a_fixed_list():
    """It silently had no such parameter — on the tier metal complexes always
    land on."""
    params = inspect.signature(ff_mod._openbabel_optimize).parameters
    assert "fixed" in params


def test_the_openbabel_tier_is_passed_the_fixed_list():
    src = inspect.getsource(ff_mod.optimize)
    assert "_openbabel_optimize(symbols, coords, bonds, steps, fixed)" in src


def test_frozen_atoms_covers_the_centre_AND_its_donors():
    s = _bent_meta_complex()
    assert meta_mod.frozen_atoms(s) == [0, 1, 2]


def test_idealize_restores_a_collapsed_sphere():
    """Freezing a collapsed sphere preserves the damage; the promise of a
    locked meta atom is that the distance you set is the distance you get."""
    s = _bent_meta_complex(distance=2.0, collapsed=True)
    before = [float(np.linalg.norm(s.coords[0] - s.coords[j])) for j in (1, 2)]
    assert max(before) < 1.0
    meta_mod.idealize(s, 0, meta_mod.get_meta(s, 0))
    after = [float(np.linalg.norm(s.coords[0] - s.coords[j])) for j in (1, 2)]
    assert all(v == pytest.approx(2.0, abs=1e-6) for v in after)


def test_the_optimize_path_idealizes_and_resolves_before_running(win):
    """Both halves of the fix are in `on_optimize`, ahead of the worker."""
    src = inspect.getsource(win.on_optimize)
    assert "meta_mod.idealize" in src
    assert "meta_mod.resolved_symbols" in src
    # and the resolved symbols are what the worker is handed
    assert "OptimizeWorker(symbols," in src


def test_a_locked_meta_sphere_survives_a_real_optimisation():
    """End to end, on whatever tier this machine has."""
    pytest.importorskip("rdkit")
    s = _bent_meta_complex(distance=2.0)
    frozen = meta_mod.frozen_atoms(s)
    symbols = meta_mod.resolved_symbols(s)
    out, _info = ff_mod.optimize(symbols, s.coords.copy(), s.bonds,
                                 fixed=frozen)
    for j in (1, 2):
        assert float(np.linalg.norm(out[0] - out[j])) == pytest.approx(
            2.0, abs=1e-3)


# ------------------------------------------------------- the meta colour
def test_a_meta_atom_wears_its_resolved_element_colour(win):
    """`Xx` grey said nothing about what the centre becomes; the halo is what
    marks it as a meta atom.

    Checked on the COLOUR THAT GETS UPLOADED rather than by grepping the
    source: the first version asserted `meta_mod.all_meta` appeared inside
    `_rebuild`, which broke the moment that code moved into
    `_build_object_block` even though nothing about the behaviour changed.
    """
    from molom.core import elements
    fe = elements.color_f(elements.atomic_number("Fe"))
    xx = elements.color_f(elements.atomic_number("Xx"))
    assert fe != xx, "the fixture would be meaningless if these matched"

    obj = win.scene.add(_bent_meta_complex(), name="meta")
    block = win.viewport._build_object_block(obj)
    drawn = [tuple(round(float(c), 6) for c in row[:3])
             for row in block["sphere_cols"]]
    assert tuple(round(float(c), 6) for c in fe) in drawn, \
        "the meta centre was not drawn in its resolved element's colour"
    assert tuple(round(float(c), 6) for c in xx) not in drawn


# --------------------------------------------- monodentate, several at once
def test_one_ligating_atom_means_one_copy_per_placeholder(win):
    win.load_default_scene()                    # cubane
    host = win._active_obj()
    ligand = win.scene.add(
        Structure(["N", "H"], np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])),
        name="mono")
    ligand.structure.bonds = [(0, 1, 1)]
    tpl_mod.set_ligating(ligand.structure, [0])
    for other in win.scene.objects:
        if other is not ligand:
            tpl_mod.clear_ligating(other.structure)

    hydrogens = [i for i, sym in enumerate(host.structure.symbols)
                 if sym == "H"][:3]
    before = host.structure.n_atoms
    win.viewport.set_selection([(host.id, i) for i in hydrogens])
    win.on_template_coordinate()
    after = win.scene.get(host.id).structure.n_atoms
    # three copies of a 2-atom ligand, three placeholders consumed
    assert after == before + 3 * 2 - 3


def test_a_polydentate_ligand_still_demands_geminal_slots(win):
    """Slots on two different centres would be a BRIDGING ligand, which is a
    genuinely different operation — so the rule is not relaxed there."""
    win.load_default_scene()
    host = win._active_obj()
    hydrogens = [i for i, sym in enumerate(host.structure.symbols)
                 if sym == "H"][:2]
    centres = {host.structure.bonded_neighbors(i)[0] for i in hydrogens}
    if len(centres) < 2:
        pytest.skip("need two hydrogens on different carbons")
    with pytest.raises(tpl_mod.TemplateError):
        tpl_mod.check_placeholders(host.structure, hydrogens)


# ------------------------------------------------ bonds pick a molecule
def test_there_is_an_all_objects_bond_hit_test(win):
    """`_bond_at` is scoped to the EDITED molecule, so object mode found
    nothing at all."""
    assert hasattr(win.viewport, "_bond_object_at")
    src = inspect.getsource(win.viewport._select_molecule_at)
    assert "_bond_object_at" in src


def test_the_bond_hit_test_searches_visible_objects(win):
    src = inspect.getsource(win.viewport._bond_object_at)
    assert "visible_objects" in src
    # nearest hit, not the first object that happens to match
    assert "best_d" in src


# --------------------------------------------------------------- the logo
def test_the_logo_resources_exist_and_load():
    from molom import resources
    assert os.path.exists(resources.SVG)
    for size in resources.SIZES:
        assert os.path.exists(resources.png(size)), size


def test_the_window_and_app_carry_the_icon(win):
    assert not win.windowIcon().isNull()


def test_the_icon_is_declared_as_package_data():
    """Without this the wheel carries the module and none of the images, and an
    installed MoloM silently falls back to the Python logo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read()
    assert "molom.resources" in text
    assert "package-data" in text
    assert "*.png" in text


# ------------------------------------------------- export animation is findable
def test_export_animation_is_in_the_File_menu(win):
    entries = []
    for action in win.menuBar().actions():
        if action.text().replace("&", "") == "File" and action.menu():
            entries = [a.text().replace("&", "")
                       for a in action.menu().actions() if a.text()]
    assert any("Export animation" in e for e in entries), entries
