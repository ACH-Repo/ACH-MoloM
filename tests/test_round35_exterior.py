"""Round 35: VESTA's boundary SEARCH — bonded atoms outside the cell.

Christian's side-by-side against VESTA showed MoloM's chains ending flat at
the cell wall while VESTA's ran on. That is a different operation from round
32's `boundary_images`, which only repeats sites lying exactly ON a face; a
chain crossing a face has nothing on the face to repeat.
"""

import numpy as np
import pytest

from molom.core import cif

#: A one-dimensional chain running along a: two atoms per cell, bonded to
#: each other and — crucially — to the images in the cells either side. The
#: cell is deliberately roomy in b and c so nothing bonds sideways.
CHAIN_CIF = """
data_chain
_cell_length_a  3.0000
_cell_length_b  9.0000
_cell_length_c  9.0000
_cell_angle_alpha 90.0
_cell_angle_beta  90.0
_cell_angle_gamma 90.0
loop_
_symmetry_equiv_pos_as_xyz
  'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
  C1 C 0.20 0.5 0.5
  C2 C 0.70 0.5 0.5
"""


@pytest.fixture
def chain():
    return cif.parse_cif(CHAIN_CIF)


def test_the_chain_really_does_cross_the_cell_faces(chain):
    """Guard on the fixture itself: if the chain did not bond to its own
    images there would be nothing for the search to find, and every
    assertion below would pass for the wrong reason."""
    symbols, coords = cif.expand(chain)
    frac = chain.cell.to_fractional(coords)
    info = cif.fragment_info(symbols, frac, chain.cell)
    assert any(periodic for _group, periodic in info)


def test_off_by_default_nothing_is_added(chain):
    """Christian's call: an existing structure must not change on import."""
    plain = cif.expand(chain)[1]
    same = cif.expand(chain, exterior=0)[1]
    assert len(plain) == len(same)


def test_the_search_adds_atoms_beyond_the_faces(chain):
    base_symbols, base_coords = cif.expand(chain)
    ext_symbols, ext_coords = cif.expand(chain, exterior=1)
    assert len(ext_symbols) > len(base_symbols)
    added = cif.Cell.to_fractional(chain.cell, ext_coords[len(base_coords):])
    # Every ADDED atom is outside the closed box — that is what makes it
    # exterior rather than a duplicate of something already drawn.
    assert np.any(added < -1e-6) or np.any(added > 1.0 + 1e-6)
    assert all(np.any(f < -1e-6) or np.any(f > 1.0 + 1e-6) for f in added)


def test_the_added_atoms_are_within_bonding_range_of_the_cell(chain):
    """They must be BONDED neighbours, not simply the next cell along."""
    from molom.core import elements
    base_symbols, base_coords = cif.expand(chain)
    ext_symbols, ext_coords = cif.expand(chain, exterior=1)
    added = ext_coords[len(base_coords):]
    added_syms = ext_symbols[len(base_symbols):]
    for sym, point in zip(added_syms, added):
        d = np.linalg.norm(base_coords - point, axis=1)
        limit = (elements.radius_covalent(elements.atomic_number(sym))
                 + max(elements.radius_covalent(
                     elements.atomic_number(s)) for s in base_symbols) + 0.45)
        assert float(d.min()) < limit


def test_deeper_shells_reach_further(chain):
    one = len(cif.expand(chain, exterior=1)[0])
    two = len(cif.expand(chain, exterior=2)[0])
    assert two > one


def test_the_cell_CONTENT_is_untouched(chain):
    """Z must not move. Anything counting formula units uses boundary=False,
    and the search must never leak into it."""
    content = cif.expand(chain, boundary=False, exterior=0)[0]
    still = cif.expand(chain, boundary=False, exterior=1)[0]
    assert len(content) == 2
    # The exterior atoms are appended, so the content is the same prefix.
    assert list(still[:len(content)]) == list(content)


def test_a_molecular_crystal_gains_nothing_from_the_search():
    """An isolated molecule has no bonds crossing a face, so there is
    nothing beyond the wall to draw and the picture must not change."""
    lone = cif.parse_cif("""
data_lone
_cell_length_a 12.0
_cell_length_b 12.0
_cell_length_c 12.0
_cell_angle_alpha 90.0
_cell_angle_beta  90.0
_cell_angle_gamma 90.0
loop_
_symmetry_equiv_pos_as_xyz
  'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
  C1 C 0.50 0.50 0.50
  O1 O 0.60 0.50 0.50
""")
    assert len(cif.expand(lone, exterior=1)[0]) == \
        len(cif.expand(lone, exterior=0)[0])


def test_bonded_exterior_de_duplicates_images_reached_twice():
    """A copy found from two directions must be added once. Keying on
    (site, integer image) is what guarantees it."""
    data = cif.parse_cif(CHAIN_CIF)
    symbols, coords = cif.expand(data)
    frac = data.cell.to_fractional(coords)
    ext_syms, ext_frac = cif.bonded_exterior(symbols, frac, data.cell,
                                             depth=3)
    keys = {(s, tuple(np.round(f, 6))) for s, f in zip(ext_syms, ext_frac)}
    assert len(keys) == len(ext_syms)


def test_the_symmetry_modifier_carries_the_setting_through_a_savepoint():
    from molom.core import modifiers
    mod = modifiers.SymmetryModifier(cell={"a": 3.0, "b": 9.0, "c": 9.0,
                                           "alpha": 90.0, "beta": 90.0,
                                           "gamma": 90.0},
                                     symops=["x,y,z"], exterior=1)
    back = modifiers.from_dict(mod.to_dict())
    assert back.exterior == 1
