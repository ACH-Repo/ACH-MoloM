"""Round 42: a site shared by several species, drawn as VESTA draws it.

`1547149.cif` puts Nb 0.50, Ti 0.25, Ni 0.15 and Co 0.10 on ONE position — a
substitutional solid solution. MoloM drew it as pure Nb, and not because of a
policy decision: all four sit at (0,0,0), so `expand`'s minimum-image
de-duplication discarded three of them before occupancy was ever consulted.
The rendered composition was one the file never claimed, with nothing on
screen or on the crystal page to say so.

So this is a correctness fix with a rendering feature on top: keep the shared
site's composition, report it, and draw the sphere as occupancy WEDGES.
"""

import os

import pytest

from molom.core import cif, style

DATA = os.path.join(os.path.dirname(__file__), "data")
#: COD entry 1547149, vendored verbatim (COD data is public domain).
SOLID_SOLUTION = os.path.join(DATA, "cod_1547149_solid_solution.cif")


def _colour(sym):
    from molom.core import elements
    return elements.color_f(elements.atomic_number(sym))


# ------------------------------------------------------------------- the file
def test_the_shared_site_is_read_and_not_thrown_away():
    data = cif.parse_cif(open(SOLID_SOLUTION, encoding="utf-8").read())
    composition = cif.site_composition(data)
    assert composition, "the four species on one site were lost"
    parts = dict(composition[0])
    assert parts == pytest.approx({"Nb": 0.5, "Ti": 0.25,
                                   "Ni": 0.15, "Co": 0.1})
    # Ordered by occupancy, so the biggest wedge is drawn first.
    assert [s for s, _o in composition[0]] == ["Nb", "Ti", "Ni", "Co"]


def test_expansion_reports_which_drawn_atoms_are_shared():
    data = cif.parse_cif(open(SOLID_SOLUTION, encoding="utf-8").read())
    report = {}
    symbols, _coords = cif.expand(data, boundary=False, report=report)
    table = report["site_occupancy"]
    metals = [i for i, s in enumerate(symbols) if s == "Nb"]
    assert sorted(int(k) for k in table) == metals


def test_boundary_copies_inherit_the_composition():
    """Otherwise the cell shows one pie sphere and eight plain ones."""
    data = cif.parse_cif(open(SOLID_SOLUTION, encoding="utf-8").read())
    report = {}
    symbols, _coords = cif.expand(data, boundary=True, report=report)
    table = report["site_occupancy"]
    metals = [i for i, s in enumerate(symbols) if s == "Nb"]
    assert len(metals) > 2, "boundary completion should repeat the corners"
    assert sorted(int(k) for k in table) == metals


def test_an_ordinary_crystal_has_no_shared_sites():
    """A disordered methyl is NOT a shared site: its alternatives are 0.7 A
    apart, which is two positions for one atom, not two species on one."""
    from tests.test_round40_spacegroup import FERROCENE
    data = cif.parse_cif(open(FERROCENE, encoding="utf-8").read())
    assert cif.site_composition(data) == {}
    report = {}
    cif.expand(data, boundary=False, report=report)
    assert "site_occupancy" not in report


# ----------------------------------------------------------------- the wedges
def test_wedges_are_cumulative_boundaries_ending_at_one():
    wedges = style.occupancy_wedges(
        [("Nb", 0.5), ("Ti", 0.25), ("Ni", 0.15), ("Co", 0.1)], _colour)
    assert [w[3] for w in wedges] == pytest.approx([0.5, 0.75, 0.9, 1.0])
    assert wedges[0][:3] == pytest.approx(_colour("Nb"))
    assert wedges[3][:3] == pytest.approx(_colour("Co"))


def test_occupancies_are_normalised_against_their_own_total():
    """A site refined to 0.97 in total is rounding, not 3% vacancy — and an
    un-normalised last boundary would leave a sliver of the wrong colour."""
    wedges = style.occupancy_wedges([("Fe", 0.6), ("Ni", 0.37)], _colour)
    assert wedges[1][3] == pytest.approx(1.0)
    assert wedges[0][3] == pytest.approx(0.6 / 0.97)


def test_more_species_than_wedges_are_merged_not_dropped():
    wedges = style.occupancy_wedges(
        [("Fe", 0.4), ("Ni", 0.3), ("Co", 0.2), ("Ti", 0.05), ("Nb", 0.05)],
        _colour)
    assert len(wedges) == style.MAX_OCCUPANCY_WEDGES
    assert wedges[-1][3] == pytest.approx(1.0)


def test_the_padding_can_never_be_reached():
    """Fewer species than wedges still has to fill the fixed instance stride,
    and the filler must not be able to win a fragment."""
    wedges = style.occupancy_wedges([("Fe", 0.7), ("Ni", 0.3)], _colour)
    assert len(wedges) == style.MAX_OCCUPANCY_WEDGES
    assert wedges[1][3] == pytest.approx(1.0)      # real last boundary
    assert all(w[3] == pytest.approx(1.0) for w in wedges[1:])


# --------------------------------------------------------------------- the UI
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def test_an_outliner_colour_beats_the_wedges(win):
    """Christian's precedence rule: painting an atom yourself is a deliberate
    statement about that atom, so it stays solid in the colour you chose."""
    win.open_path(SOLID_SOLUTION)
    obj = win.scene.objects[-1]
    n = obj.structure.n_atoms
    before = win.viewport._occupancy_wedges(obj, n, n)
    assert before, "the shared sites should be drawn as wedges"
    painted = sorted(before)[0]
    obj.atom_colors[painted] = (1.0, 0.5, 0.0)
    after = win.viewport._occupancy_wedges(obj, n, n)
    assert painted not in (after or {})
    assert len(after or {}) == len(before) - 1


def test_the_display_can_be_switched_off(win):
    win.open_path(SOLID_SOLUTION)
    obj = win.scene.objects[-1]
    n = obj.structure.n_atoms
    win.viewport.show_occupancy = False
    assert win.viewport._occupancy_wedges(obj, n, n) is None
    win.viewport.show_occupancy = True
    assert win.viewport._occupancy_wedges(obj, n, n)


def test_the_crystal_page_states_the_composition(win):
    """The page has to SAY it: a solid solution drawn as its majority element
    is exactly the kind of wrongness that looks like a clean import."""
    win.open_path(SOLID_SOLUTION)
    win._sync_crystal_page()
    text = win.crystal_page.detail.text()
    assert "Shared site" in text
    for symbol in ("Nb", "Ti", "Ni", "Co"):
        assert symbol in text
    # One line per DISTINCT composition, not one per symmetry image.
    assert text.count("Shared site") == 1
