"""Round 83: the occupancy pie spheres, on every view (open item A4).

Christian: "Pie occupation spheres still only work for certain sites. They are
completely omitted in the asymmetric unit for cif: 1547149.cif."

Both halves reproduced, and the first was **one bug wearing a disguise**: the
composition map is keyed by DRAWN atom index and comes from `packing.pack`,
but two places then overwrote it with the map from `expand(boundary=False)` -
which is keyed by CONTENT index. That does not merely lose the boundary
copies, it changes what the keys MEAN. The two agree on the first atoms of the
cell, because a content atom is its own first image, which is exactly why it
looked as though the feature worked on some sites and not others: 2 of
`1547149.cif`'s 10 Nb were drawn with a composition and the other 8 plain.

The same overwrite left `site_of` with 6 entries for 21 atoms, and left
`content_of` stale across a view switch - which is the dangerous one, since
`images_of` reads it to decide which atoms a delete should take with it.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SOLID_SOLUTION = os.path.join(DATA, "cod_1547149_solid_solution.cif")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def _pies(obj):
    table = obj.structure.metadata.get("site_occupancy") or {}
    return sorted(int(k) for k in table)


def test_the_packing_maps_every_image_of_a_shared_site():
    """Core has always been right; it was the callers that overwrote it."""
    from molom.core import cif as cif_mod, packing
    data = cif_mod.parse_cif(open(SOLID_SOLUTION, encoding="utf-8",
                                  errors="replace").read())
    symbols, _coords, _bonds, meta = packing.pack(data)
    nb = [i for i, s in enumerate(symbols) if s == "Nb"]
    table = meta["site_occupancy"]
    assert len(nb) == 10
    assert all(str(i) in table for i in nb)


def test_every_image_of_the_shared_site_carries_the_composition(win):
    """The import path. 2 of 10 before."""
    win.open_path(SOLID_SOLUTION)
    obj = win._active_obj()
    nb = [i for i, s in enumerate(obj.structure.symbols) if s == "Nb"]
    assert len(nb) == 10
    assert _pies(obj) == nb
    for index in nb:
        composition = dict(obj.structure.metadata["site_occupancy"][str(index)])
        assert composition == {"Nb": 0.5, "Ti": 0.25, "Ni": 0.15, "Co": 0.1}


def test_the_composition_survives_a_view_switch(win):
    """The rebuild path had the same overwrite, so the pies came back as 2."""
    win.open_path(SOLID_SOLUTION)
    obj = win._active_obj()
    before = _pies(obj)
    for mode in ("asym", "cell"):
        win.on_crystal_view(mode)
    assert _pies(win._active_obj()) == before


def test_no_per_atom_map_outlives_the_atoms_it_describes(win):
    """`site_of` held 6 entries for 21 atoms, and `content_of` survived a
    switch to the asymmetric unit still describing the full cell - which is
    what `images_of` reads to decide what a delete takes with it."""
    win.open_path(SOLID_SOLUTION)
    for mode in ("cell", "asym", "cell", "packing"):
        win.on_crystal_view(mode)
        obj = win._active_obj()
        n = obj.structure.n_atoms
        meta = obj.structure.metadata
        for key in ("site_of", "content_of"):
            column = meta.get(key)
            assert not column or len(column) == n, (mode, key, len(column), n)
        for index in _pies(obj):
            assert index < n, (mode, index, n)


def test_the_asymmetric_unit_carries_no_stale_composition(win):
    """It produces no composition of its own (see the round-83 note on why
    merging the shared rows there is not safe yet), so what it must NOT do is
    keep the full cell's - which would paint the pie onto whichever of the
    five listed sites happened to hold that index."""
    win.open_path(SOLID_SOLUTION)
    win.on_crystal_view("asym")
    obj = win._active_obj()
    assert obj.structure.symbols == ["Nb", "Ti", "Ni", "Co", "O"]
    assert _pies(obj) == []
