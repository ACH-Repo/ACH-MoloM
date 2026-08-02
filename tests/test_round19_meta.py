"""Round 19: meta atoms — coordination constraints that survive optimisation."""

import numpy as np
import pytest

from molom.core import coordination, meta
from molom.core.structure import Structure


def _complex(n_donors=5):
    """A centre with `n_donors` ligand atoms hung off it, roughly placed."""
    coords = [[0.0, 0.0, 0.0]]
    for k in range(n_donors):
        angle = 2.0 * np.pi * k / n_donors
        coords.append([2.4 * np.cos(angle), 2.4 * np.sin(angle), 0.3 * k])
    s = Structure.from_atoms(
        [("Zn", *coords[0])] + [("N", *c) for c in coords[1:]])
    for j in range(1, n_donors + 1):
        s.bonds.append((0, j, 1))
    return s


def test_meta_atom_round_trips_through_its_dict():
    m = meta.MetaAtom("trigonal_bipyramidal", 2.0, "Fe")
    again = meta.MetaAtom.from_dict(m.to_dict())
    assert again.geometry == "trigonal_bipyramidal"
    assert again.distance == pytest.approx(2.0)
    assert again.element == "Fe"
    assert again.locked


def test_unknown_geometry_is_rejected():
    with pytest.raises(ValueError):
        meta.MetaAtom("banana", 2.0)


def test_export_element_is_resolved_case_insensitively():
    assert meta.MetaAtom("octahedral", 2.0, "iron").element == "Fe"
    assert meta.MetaAtom("octahedral", 2.0, "FE").element == "Fe"
    assert meta.MetaAtom("octahedral", 2.0, "").element == ""


def test_setting_a_meta_atom_retypes_it_to_the_dummy():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("trigonal_bipyramidal", 2.0, "Fe"))
    assert s.symbols[0] == meta.META_SYMBOL
    got = meta.get_meta(s, 0)
    assert got is not None and got.element == "Fe"


def test_meta_table_survives_a_metadata_round_trip():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("octahedral", 2.1, "Ru"))
    # Savepoints are JSON, so the keys must already be strings.
    import json
    clone = json.loads(json.dumps(s.metadata))
    assert clone["meta_atoms"]["0"]["geometry"] == "octahedral"
    assert clone["meta_atoms"]["0"]["element"] == "Ru"


def test_frozen_atoms_covers_the_centre_and_its_donors():
    """This is what 'holds the shape': freeze the whole first coordination
    sphere and the force field cannot collapse it."""
    s = _complex(n_donors=5)
    meta.set_meta(s, 0, meta.MetaAtom("trigonal_bipyramidal", 2.0, "Fe"))
    assert meta.frozen_atoms(s) == [0, 1, 2, 3, 4, 5]


def test_an_unlocked_meta_atom_freezes_nothing():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("trigonal_bipyramidal", 2.0, "Fe",
                                      locked=False))
    assert meta.frozen_atoms(s) == []


def test_idealize_puts_donors_at_the_requested_distance():
    s = _complex(n_donors=5)
    m = meta.MetaAtom("trigonal_bipyramidal", 2.0, "Fe")
    meta.set_meta(s, 0, m)
    moved = meta.idealize(s, 0, m)
    assert moved == 5
    centre = s.coords[0]
    for j in range(1, 6):
        assert np.linalg.norm(s.coords[j] - centre) == pytest.approx(2.0)


def test_idealize_reproduces_the_named_geometry():
    s = _complex(n_donors=5)
    m = meta.MetaAtom("trigonal_bipyramidal", 2.0)
    meta.set_meta(s, 0, m)
    meta.idealize(s, 0, m)
    dirs = s.coords[1:6] - s.coords[0]
    dirs = dirs / np.linalg.norm(dirs, axis=1)[:, None]
    # A trigonal bipyramid has exactly one pair of donors at 180 degrees.
    dots = dirs @ dirs.T
    axial = int(np.sum(dots < -0.99)) // 2
    assert axial == 1


def test_resolved_symbols_swaps_the_dummy_only_on_export():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("trigonal_bipyramidal", 2.0, "Fe"))
    assert s.symbols[0] == meta.META_SYMBOL          # still a dummy in the app
    assert meta.resolved_symbols(s)[0] == "Fe"       # ...real on the way out
    assert meta.resolved_symbols(s)[1] == "N"


def test_a_meta_atom_without_an_element_is_reported_not_guessed():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("octahedral", 2.0))
    assert meta.unresolved(s) == [0]
    assert meta.resolved_symbols(s)[0] == meta.META_SYMBOL


def test_remap_follows_atoms_and_drops_deleted_ones():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("octahedral", 2.0, "Fe"))
    meta.remap(s, {0: 3})
    assert meta.get_meta(s, 3) is not None
    assert meta.get_meta(s, 0) is None
    meta.remap(s, {3: None})
    assert meta.all_meta(s) == {}


def test_prune_drops_entries_past_the_end():
    s = _complex()
    meta.set_meta(s, 0, meta.MetaAtom("octahedral", 2.0))
    s.metadata["meta_atoms"]["99"] = {"geometry": "octahedral",
                                      "distance": 2.0}
    meta.prune(s)
    assert sorted(meta.all_meta(s)) == [0]


def test_every_template_geometry_is_usable_as_a_meta_atom():
    for name in coordination.GEOMETRY_DIRECTIONS:
        m = meta.MetaAtom(name, 2.0, "Fe")
        assert m.n_donors >= 1
