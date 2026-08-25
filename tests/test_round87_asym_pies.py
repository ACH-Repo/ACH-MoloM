"""Round 87: the asymmetric unit shows a solid solution as a pie sphere, and
an edit no longer flattens it.

Open item **A4**, the last piece. The full cell has drawn a shared site as one
pie sphere since round 42, because `expand`'s minimum-image merge collapses
the co-located rows; the asymmetric unit listed them verbatim and drew four
atoms stacked inside one another. Same structure, two pictures - and the one
that looked broken was the one that had not lost anything.

Merging for display was always easy. What made it a DATA-LOSS hazard rather
than a feature is `sync_asymmetric_unit`: it writes the drawn atoms straight
back into `asym_symbols` and resets any parallel column whose length no longer
matches, so a merged view would go from five `_atom_site_` rows to two and
write `asym_occupancy = [1.0, 1.0]` - permanently reducing Nb/Ti/Ni/Co to the
pure NbO2 that round 42 exists to stop MoloM drawing. Christian's decision was
to merge AND fix the write-back.
"""
import os

import numpy as np
import pytest

from molom.core import cif, edits

SOLID = os.path.join(os.path.dirname(__file__), "data",
                     "cod_1547149_solid_solution.cif")
FERROCENE = os.path.join(os.path.dirname(__file__), "data",
                         "cod_2101932_ferrocene.cif")


def _data(path):
    with open(path, encoding="utf-8") as fh:
        return cif.parse_cif(fh.read())


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def _open_asym(win, path):
    win.open_path(path)
    obj = win.scene.objects[-1]
    win.active_id = obj.id
    win.on_crystal_view("asym")
    return obj


# ------------------------------------------------------------------- core
def test_the_asym_view_merges_a_shared_site():
    """Five rows at one position become one drawn atom with a composition."""
    data = _data(SOLID)
    assert list(data.symbols) == ["Nb", "Ti", "Ni", "Co", "O"]
    symbols, frac, composition, rows = cif.asym_view(data)
    assert symbols == ["Nb", "O"]
    assert frac.shape == (2, 3)
    assert rows == [[0, 1, 2, 3], [4]]
    assert composition["0"] == [("Nb", 0.5), ("Ti", 0.25), ("Ni", 0.15),
                                ("Co", 0.1)]


def test_the_merged_atom_is_drawn_as_the_majority_species():
    """The full cell draws the site in the colour of what it mostly is, so
    the asymmetric unit has to agree - two pictures of one site differing by
    element would be worse than the stacked atoms this replaces."""
    symbols, _f, composition, _r = cif.asym_view(_data(SOLID))
    assert symbols[0] == composition["0"][0][0] == "Nb"


def test_an_ordinary_crystal_is_untouched():
    """Only GENUINE shared sites merge - more than one species, fractional
    occupancies. Two symmetry-redundant rows for one atom are a duplicate, not
    a solid solution (round 33's urea case), so an ordinary file's asymmetric
    unit must come back exactly as the file lists it."""
    data = _data(FERROCENE)
    symbols, frac, composition, rows = cif.asym_view(data)
    assert symbols == list(data.symbols)
    assert np.allclose(frac, data.frac)
    assert composition == {}
    assert rows == [[i] for i in range(len(data.symbols))]


def test_asym_rows_is_a_per_atom_list_so_a_delete_remaps_it():
    """It is one entry per DRAWN atom, so it has to travel with them."""
    assert "asym_rows" in edits._PER_ATOM_LISTS


# -------------------------------------------------------------- write-back
def test_moving_a_shared_site_keeps_the_solid_solution(win):
    """The whole point of A4. Every row of the site takes the atom's new
    position and keeps its own element and occupancy."""
    obj = _open_asym(win, SOLID)
    meta = obj.structure.metadata
    assert obj.structure.n_atoms == 2, "the shared site should be merged"
    assert meta["asym_rows"] == [[0, 1, 2, 3], [4]]

    obj.structure.frames[0][0] += np.array([0.3, 0.0, 0.0])
    assert win.sync_asymmetric_unit(obj) is True
    assert meta["asym_symbols"] == ["Nb", "Ti", "Ni", "Co", "O"]
    assert [round(float(o), 2) for o in meta["asym_occupancy"]] == \
        [0.5, 0.25, 0.15, 0.1, 1.0]
    # ...and all four rows moved together, since they are one position.
    first_four = np.asarray(meta["asym_frac"][:4], dtype=float)
    assert np.allclose(first_four, first_four[0])


def test_the_columns_are_measured_against_the_ROWS_not_the_atoms(win):
    """The reset loop compares each parallel column with `asym_symbols`, not
    with the drawn atom count. Comparing with `s.n_atoms` found 5 != 2 and
    reset `asym_occupancy` to [1.0, 1.0] immediately after the write-back had
    rebuilt it correctly - the very flattening this round exists to stop."""
    obj = _open_asym(win, SOLID)
    meta = obj.structure.metadata
    win.sync_asymmetric_unit(obj)
    assert len(meta["asym_occupancy"]) == len(meta["asym_symbols"]) == 5
    assert obj.structure.n_atoms == 2


def test_an_ordinary_crystal_still_writes_one_row_per_atom(win):
    """Nothing merged means nothing to expand, and no map left behind."""
    obj = _open_asym(win, FERROCENE)
    meta = obj.structure.metadata
    before = list(meta["asym_symbols"])
    obj.structure.frames[0][0] += np.array([0.05, 0.0, 0.0])
    win.sync_asymmetric_unit(obj)
    assert meta["asym_symbols"] == before
    assert "asym_rows" not in meta, "a map describing nothing must not persist"


def test_deleting_the_shared_atom_takes_all_of_its_rows(win):
    """A merged atom stands for four `_atom_site_` rows; deleting it has to
    take the group, not leave three orphans behind."""
    obj = _open_asym(win, SOLID)
    meta = obj.structure.metadata
    report = {}
    edits.delete_atoms(obj.structure, [0], report=report)
    obj.remap_atoms(report.get("remap") or {})
    win.sync_asymmetric_unit(obj)
    assert meta["asym_symbols"] == ["O"]
    assert [round(float(o), 2) for o in meta["asym_occupancy"]] == [1.0]
    assert "asym_rows" not in meta


def test_the_full_cell_still_shows_its_pies_after_a_round_trip(win):
    """asym -> cell must not lose what asym was showing."""
    obj = _open_asym(win, SOLID)
    win.sync_asymmetric_unit(obj)
    win.on_crystal_view("cell")
    meta = obj.structure.metadata
    assert obj.structure.n_atoms == 21
    assert len(meta.get("site_occupancy") or {}) == 10


def test_a_stale_map_is_refused_rather_than_misapplied(win):
    """Round 51's rule: a mis-indexed occupancy is worse than none."""
    obj = _open_asym(win, SOLID)
    meta = obj.structure.metadata
    meta["asym_rows"] = [[0, 1, 2, 99], [4]]         # points off the end
    frac = np.zeros((2, 3))
    assert win._write_back_shared(meta, obj.structure, frac) is False
