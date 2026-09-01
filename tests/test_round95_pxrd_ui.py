"""Round 95: the powder pattern becomes something you can open.

Round 94 computed the physics and left the window unbuilt. This is the bridge
from a crystal MoloM has open to `pxrd.compute`, and the window that draws it.

The bridge is where the mistakes live, not the arithmetic: the DRAWN atoms are
not the cell contents (boundary copies are duplicates, a packing is many
cells, and both are in the viewport's frame rather than the cell's), so the
sum is regenerated from the asymmetric unit and the operators every time.
"""
import os

import numpy as np
import pytest

from molom.core import cif as cif_mod
from molom.core import io as io_mod
from molom.core import pxrd
from molom.core.structure import Structure

HERE = os.path.dirname(__file__)
FERROCENE = os.path.join(HERE, "data", "cod_2101932_ferrocene.cif")
SOLID_SOLUTION = os.path.join(HERE, "data", "cod_1547149_solid_solution.cif")


def _open(path, name="crystal"):
    atoms, meta = io_mod.read_structures(path)[0]
    s = Structure.from_atoms(atoms, name=name)
    s.metadata.update(meta or {})
    return s


# ---------------------------------------------------------------- the bridge
def test_a_molecule_has_no_powder_pattern():
    """Refused rather than answered. A diffractogram of a lone molecule is
    not a thing, and inventing a box to give one would be worse than None."""
    from molom.core import build as build_mod
    assert pxrd.cell_contents(build_mod.cubane()) is None
    assert pxrd.pattern_for(build_mod.cubane()) is None


def test_the_contents_are_the_CELL_and_not_the_drawn_atoms():
    """Ferrocene draws 210 atoms and its cell holds 42. Summing over the
    picture would count every boundary copy twice."""
    s = _open(FERROCENE)
    assert s.n_atoms == 210
    _cell, symbols, frac, _occ = pxrd.cell_contents(s)
    assert len(symbols) == 42
    assert frac.shape == (42, 3)


def test_a_shared_site_scatters_as_all_of_its_species():
    """`expand`'s minimum-image merge keeps the first species of a shared
    site and discards the rest (round 42's ordering flaw). For a picture that
    costs a pie sphere; for a structure factor it is the wrong scatterer, so
    the site is put back together - one term per species at one position."""
    s = _open(SOLID_SOLUTION)
    _cell, symbols, frac, occ = pxrd.cell_contents(s)
    assert set(symbols) == {"Nb", "Ti", "Ni", "Co", "O"}
    # The four metals sit on ONE position, so their fractional coordinates
    # are identical and their occupancies are the file's own.
    metals = [(sym, o, tuple(np.round(f, 6)))
              for sym, o, f in zip(symbols, occ, frac) if sym != "O"]
    first = metals[0][2]
    same = [m for m in metals if m[2] == first]
    assert sorted(round(o, 2) for _s, o, _f in same) == [0.10, 0.15, 0.25, 0.50]


def test_the_solid_solution_gives_the_rutile_pattern():
    """A textbook check rather than one of our own numbers: this is a
    rutile-type oxide, whose three strongest reflections are 110, 101, 211."""
    s = _open(SOLID_SOLUTION)
    # Explicitly past 50 degrees: the default range stops below 211, which is
    # the right default for a lab pattern and the wrong one for this check.
    pxrd.set_settings(s, two_theta_max=90.0)
    pattern = pxrd.pattern_for(s)
    strongest = sorted(pattern.reflections, key=lambda r: -r.intensity)[:3]
    assert [r.label() for r in strongest] == ["(1 1 0)", "(1 0 1)", "(2 1 1)"]
    # ...and 110 is the strongest of the three, which is what makes it rutile
    # rather than merely tetragonal.
    assert strongest[0].two_theta == pytest.approx(26.81, abs=0.05)


def test_the_pattern_does_not_depend_on_the_display_mode():
    """The invariant that says the bridge is right. A structure factor is a
    property of the CELL, so the asymmetric unit, the full cell and a 2x2x2
    packing are three pictures of one crystal and must give one pattern.
    Reading the drawn atoms instead would give three different answers.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow

    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win.scene.objects[-1]
    win.active_id = obj.id
    seen = {}
    for mode, kwargs in (("cell", {}), ("asym", {}),
                         ("packing", dict(na=2, nb=2, nc=2))):
        win.on_crystal_view(mode, **kwargs)
        pattern = pxrd.pattern_for(obj.structure)
        seen[mode] = [(r.hkl, round(r.two_theta, 6),
                       round(r.intensity / pattern.strongest(), 6))
                      for r in pattern.reflections]
    assert seen["cell"] == seen["asym"] == seen["packing"]
    assert len(seen["cell"]) > 50


def test_a_moved_crystal_gives_the_same_pattern():
    """The fallback path un-poses before converting to fractional, and the
    regenerated path never touches the drawn atoms at all - so a crystal that
    has been dragged across the viewport diffracts exactly as it did."""
    s = _open(FERROCENE)
    before = pxrd.pattern_for(s)
    s.frames = [s.coords + np.array([4.0, -2.0, 7.5])]
    s.set_frame(0)
    after = pxrd.pattern_for(s)
    assert [r.hkl for r in before.reflections] == [r.hkl for r in
                                                   after.reflections]


def test_the_settings_ride_the_structure():
    s = _open(FERROCENE)
    pxrd.set_settings(s, wavelength=pxrd.WAVELENGTHS["Mo Ka1"])
    assert pxrd.settings_of(s)["wavelength"] == pxrd.WAVELENGTHS["Mo Ka1"]
    assert pxrd.pattern_for(s).wavelength == pxrd.WAVELENGTHS["Mo Ka1"]
    # Only what DIFFERS from the defaults is stored.
    # A single line is fully described by its number, so nothing else is
    # written: `source` is empty by default and setting a bare wavelength
    # clears it.
    assert set(s.metadata[pxrd.METADATA_KEY]) == {"wavelength"}


# ---------------------------------------------------------------- the window
@pytest.fixture
def bench():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.open_path(FERROCENE)
    win.open_path(SOLID_SOLUTION)
    return win


def test_the_operator_opens_a_window_with_a_trace_per_crystal(bench):
    win = bench
    win.on_pxrd()
    window = win._pxrd_window
    assert window is not None
    assert len(window.rows) == 2
    assert len(window.plot.traces) == 2
    assert all(len(t.x) > 100 for t in window.plot.traces)


def test_the_default_scene_molecule_is_not_offered(bench):
    """Cubane is in the scene and has no cell, so it is simply absent - a
    greyed row saying "not a crystal" would be one more dead control."""
    win = bench
    win.on_pxrd()
    names = [obj.name for obj, _box, _c in win._pxrd_window.rows]
    assert "cubane" not in names


def test_two_wavelengths_force_the_Q_axis(bench):
    """2-theta depends on the wavelength and Q does not, so two patterns
    computed at two wavelengths cannot honestly share an angle axis."""
    win = bench
    win.on_pxrd()
    window = win._pxrd_window
    assert window.plot.axis == pxrd.AXIS_TWO_THETA
    pxrd.set_settings(win.scene.objects[-1].structure,
                      wavelength=pxrd.WAVELENGTHS["Mo Ka1"])
    window.recompute()
    assert window.plot.axis == pxrd.AXIS_Q
    assert not window.q_axis.isEnabled(), "forced, so it must not be clickable"
    assert "wavelength" in window.note.text()


def test_unticking_a_crystal_drops_its_trace_and_is_remembered(bench):
    win = bench
    win.on_pxrd()
    window = win._pxrd_window
    obj, box, _c = window.rows[0]
    box.setChecked(False)
    assert len(window.plot.traces) == 1
    assert pxrd.settings_of(obj.structure)["enabled"] is False


def test_the_hover_readout_names_the_reflection(bench):
    win = bench
    win.on_pxrd()
    window = win._pxrd_window
    text = window.plot.readout(window.plot.plot_rect().center().x())
    assert "2th =" in text and "d =" in text


def test_the_export_writes_the_curve_and_the_reflections(bench, tmp_path):
    """Both, because they answer different questions: the curve is what you
    overlay on a measurement, the list is what you look an index up in."""
    win = bench
    win.on_pxrd()
    out = str(tmp_path / "pxrd.csv")
    assert win._pxrd_window.export(out) == out
    text = open(out, encoding="utf-8").read()
    assert "two_theta_deg" in text.splitlines()[3]
    assert "# reflections" in text
    assert "multiplicity" in text


# ------------------------------ the content slice, found by building the above
def test_demoting_to_P1_does_not_change_the_structure():
    """Found by simulating a pattern before and after a demotion: they must
    be the same crystal, and they were not.

    `resync_derived_asymmetric_unit` took the first `cell_content` DRAWN
    atoms as the content, and `packing.pack`'s own comment says why that is
    wrong - `complete_molecules` reorders and duplicates, so the prefix is a
    different set. Measured on ferrocene: the first 42 drawn atoms are ONE
    molecule plus a lattice copy of it, so demoting wrote 21 atoms listed
    twice, `expand` merged the duplicates, and the P1 cell was half the
    crystal. The file's own `Z = 2` and `C10 H10 Fe` settle which is right.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow

    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win.scene.objects[-1]
    win.active_id = obj.id
    before = pxrd.pattern_for(obj.structure)
    win.demote_to_p1(obj)
    assert obj.structure.metadata["spacegroup"] == "P 1"
    after = pxrd.pattern_for(obj.structure)
    assert len(after) == len(before)
    top_b, top_a = before.strongest(), after.strongest()
    for b, a in zip(before.reflections, after.reflections):
        assert a.hkl == b.hkl
        assert a.intensity / top_a == pytest.approx(b.intensity / top_b,
                                                    abs=1e-9)


def test_the_P1_unit_lists_every_atom_once():
    """The same thing said structurally: Z = 2 formula units of C10H10Fe is
    42 DISTINCT atoms, so no two of them may coincide modulo the lattice."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow

    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win.scene.objects[-1]
    win.active_id = obj.id
    win.demote_to_p1(obj)
    meta = obj.structure.metadata
    cell = cif_mod.Cell.from_dict(meta["cell"])
    frac = np.asarray(meta["asym_frac"], dtype=float)
    assert len(frac) == 42
    matrix = cell.matrix()
    for i in range(len(frac)):
        for j in range(i + 1, len(frac)):
            delta = frac[j] - frac[i]
            delta = delta - np.round(delta)
            assert np.linalg.norm(delta @ matrix) > 0.05, (i, j)


def test_content_indices_is_a_lookup_not_a_prefix():
    """The rule on its own, offline: with a `content_of` map the answer is the
    FIRST drawn image of each content atom, and the prefix is only the
    fallback for a structure that was never packed."""
    from molom.core import packing as packing_mod
    # Ferrocene's shape: two molecules of 3 atoms, drawn molecule by molecule
    # while `expand` emitted them site by site.
    meta = {"cell_content": 6,
            "content_of": [0, 2, 4, 0, 2, 4, 1, 3, 5, 1, 3, 5]}
    assert packing_mod.content_indices(meta, 12) == [0, 6, 1, 7, 2, 8]
    # No map: the prefix, which is what an unpacked crystal really is.
    assert packing_mod.content_indices({"cell_content": 3}, 9) == [0, 1, 2]
    # A map of the wrong length describes a different atom list and is
    # refused rather than trusted - round 80's rule.
    assert packing_mod.content_indices(
        {"cell_content": 3, "content_of": [0, 1]}, 9) == [0, 1, 2]
