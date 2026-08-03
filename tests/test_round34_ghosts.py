"""Round 34: the symmetry ghosts stop being shredded by the cell boundary.

Christian's report: "the ghost atoms are glitched. they show bonds where
there shouldn't be any... fragments that should be in a clone to the right are
instead attributed to the molecule on the left and connected. the bonds face
the wrong way and are way too long."

That is per-ATOM wrapping. `images_of` put every atom of an image into [0,1)
on its own, so any copy straddling a face came back in two halves — and since
the bonds are perceived with the minimum image, the two halves stayed bonded
and were drawn as lines across the whole box. Exactly the round-19 bug, one
level up: real atoms were fixed then, the ghosts were not.
"""

import numpy as np
import pytest

from molom.core import cif, symmetry


def _cubic(a=8.0):
    return cif.Cell(a, a, a, 90.0, 90.0, 90.0)


def _straddling_pair():
    """Two bonded atoms either side of the x = 0 face.

    In a cubic 8 A cell these sit 1.2 A apart across the boundary, which is a
    bond by the covalent criterion, and 6.8 A apart if one of them is wrapped
    to the other side — the "way too long" line.
    """
    symbols = ["C", "C"]
    frac = np.array([[0.05, 0.5, 0.5], [-0.10, 0.5, 0.5]])
    return symbols, frac, _cubic()


def test_default_wrapping_still_wraps_per_atom():
    """Unchanged for callers that pass no normalizer (the NaCl paths)."""
    ops = [cif.SymOp.from_xyz("x,y,z"), cif.SymOp.from_xyz("-x,-y,-z")]
    images = symmetry.images_of(np.array([[0.1, 0.2, 0.3]]), ops)
    assert images
    for img in images:
        # lattice images are deliberately outside; the operator image is not
        assert np.all(img > -1.001) and np.all(img < 2.001)


def test_whole_molecule_normalizer_keeps_a_straddling_image_together():
    symbols, frac, cell = _straddling_pair()
    whole = lambda f: cif.unwrap_molecules(symbols, f, cell)
    ops = [cif.SymOp.from_xyz("x,y,z")]

    naive = symmetry.images_of(frac, ops, keep_identity=True, lattice=False)
    kept = symmetry.images_of(frac, ops, keep_identity=True, lattice=False,
                              normalize=whole)
    assert len(naive) == 1 and len(kept) == 1

    def span(image):
        cart = np.asarray(image) @ cell.matrix()
        return float(np.linalg.norm(cart[0] - cart[1]))

    # The naive wrap tears the pair apart across the cell...
    assert span(naive[0]) > 5.0
    # ...while wrapping by molecule leaves it the bond it actually is.
    assert span(kept[0]) == pytest.approx(1.2, abs=1e-6)


def test_direct_pairs_drops_a_bond_that_only_exists_across_a_face():
    symbols, frac, cell = _straddling_pair()
    adj = cif.periodic_neighbours(symbols, frac, cell)
    pairs = [(i, j) for i, row in enumerate(adj) for j in row if j > i]
    assert pairs == [(0, 1)]                 # bonded in the crystal

    wrapped = frac - np.floor(frac)          # what per-atom wrapping gives
    assert cif.direct_pairs(symbols, wrapped, cell, pairs) == []
    # ...and kept once the image is contiguous again
    whole = cif.unwrap_molecules(symbols, frac, cell)
    assert cif.direct_pairs(symbols, whole, cell, pairs) == [(0, 1)]


def test_direct_pairs_ignores_pairs_that_are_simply_far_apart():
    symbols = ["C", "C"]
    frac = np.array([[0.1, 0.1, 0.1], [0.6, 0.6, 0.6]])
    assert cif.direct_pairs(symbols, frac, _cubic(), [(0, 1)]) == []


def test_direct_pairs_tolerates_out_of_range_indices():
    symbols = ["C", "C"]
    frac = np.array([[0.0, 0, 0], [0.1, 0, 0]])
    assert cif.direct_pairs(symbols, frac, _cubic(), [(0, 9)]) == []
    assert cif.direct_pairs(symbols, frac, _cubic(), []) == []


def test_normalizer_does_not_break_de_duplication():
    """A special position still collapses to one ghost, not one per operator."""
    symbols = ["Na"]
    cell = _cubic(4.0)
    whole = lambda f: cif.unwrap_molecules(symbols, f, cell)
    ops = [cif.SymOp.from_xyz(t) for t in
           ("x,y,z", "-x,y,z", "x,-y,z", "-x,-y,-z")]
    images = symmetry.images_of(np.zeros((1, 3)), ops, lattice=False,
                                normalize=whole)
    assert images == []          # every operator maps the origin onto itself


def _all_ghost_bonds_are_short(symbols, frac, cell, ops, limit):
    """Shared end-to-end assertion: nothing DRAWN may be longer than a bond.

    This is the property the screenshot violated — a ghost skeleton with lines
    reaching across the box — so it is the property worth asserting, rather
    than any particular atom count.
    """
    whole = lambda f: cif.unwrap_molecules(symbols, f, cell)
    adj = cif.periodic_neighbours(symbols, frac, cell)
    pairs = [(i, j) for i, row in enumerate(adj) for j in row if j > i]
    assert pairs, "the asymmetric unit should have some bonds"
    matrix = cell.matrix()
    drawn = 0
    for image in symmetry.images_of(frac, ops, normalize=whole):
        cart = np.asarray(image) @ matrix
        for i, j in cif.direct_pairs(symbols, image, cell, pairs):
            assert float(np.linalg.norm(cart[i] - cart[j])) < limit
            drawn += 1
    return drawn


def test_a_molecule_on_a_cell_face_ghosts_without_stretched_bonds():
    """A three-atom molecule centred ON the x face — the shape of the bug.

    Built here rather than parsed: this is a geometry claim, not a claim about
    any file format, and it must run on every machine.
    """
    symbols = ["O", "C", "O"]
    cell = _cubic(9.0)
    # C exactly on x = 0 with an O either side: the classic straddler.
    frac = np.array([[-0.13, 0.5, 0.5], [0.0, 0.5, 0.5], [0.13, 0.5, 0.5]])
    ops = [cif.SymOp.from_xyz(t) for t in
           ("x,y,z", "-x,-y,z", "x,1/2-y,1/2+z", "-x,1/2+y,1/2+z")]
    drawn = _all_ghost_bonds_are_short(symbols, frac, cell, ops, limit=2.2)
    assert drawn > 0, "the ghosts should still be drawn WITH their bonds"


def test_the_real_urea_cif_when_it_is_on_this_machine():
    """Christian's own file, which is where the report came from."""
    import os
    from test_round32_cell_input import UREA_PATH
    if not os.path.exists(UREA_PATH):
        pytest.skip("urea.cif not on this machine")
    data = cif.parse_cif(open(UREA_PATH, encoding="utf-8",
                              errors="replace").read())
    _all_ghost_bonds_are_short(data.symbols, data.frac, data.cell,
                               data.symops, limit=2.2)
