"""Round 40: a CIF that NAMES its space group is expanded at last.

The gap: `_symmetry_space_group_name_H-M 'P 21/c'` with no operator loop meant
`symops = [IDENTITY]`, so MoloM drew the asymmetric unit -- a quarter of the
structure, with no error and a perfectly plausible picture. Christian's own
files show how it hides: of 37 test CIFs only two omit a usable loop, so the
bug is rare enough never to be noticed and total when it lands.

Two things are tested here, and the second matters as much as the first:

* the operators derived from a symbol are the RIGHT ones -- pinned against
  each file's own loop, because a symbol names a group and a group has up to
  nine settings (`P 21/c`, `P 21/n` and `P 21/a` are all number 14 and have
  different operators);
* every derivation is REPORTED, including the ones we refuse to make.
"""

import os

import pytest

from molom.core import cif, io, spacegroups

DATA = os.path.join(os.path.dirname(__file__), "data")
#: Ferrocene from the Crystallography Open Database (entry 2101932, Brock &
#: Fu, Acta Cryst B53, 928), vendored VERBATIM with its attribution header.
#: A real file rather than a synthetic one because the interesting part is
#: exactly what real files do: it gives a Hall symbol AND `P 1 21/a 1`, and
#: lists no operators at all. ASE refuses it outright.
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")

MINIMAL = """data_test
_cell_length_a 8.0
_cell_length_b 9.0
_cell_length_c 10.0
_cell_angle_alpha 90
_cell_angle_beta 100
_cell_angle_gamma 90
{header}
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
C1 C 0.10 0.20 0.30
O1 O 0.15 0.35 0.25
"""


def _parse(header):
    return cif.parse_cif(MINIMAL.format(header=header))


def _ops(sym):
    """Resolved operators as a comparable set."""
    resolved = spacegroups.operators_for(sym)
    assert resolved is not None, "did not resolve {!r}".format(sym)
    return frozenset(resolved.xyz)


def _canonical(ops):
    """Operators as (rotation, translation) with the lattice period removed,
    so two spellings of the same operation compare equal."""
    out = set()
    for op in ops:
        rot = tuple(int(round(v)) for v in op.rotation.flatten())
        trans = tuple(round(float(t) % 1.0, 4) % 1.0 for t in op.translation)
        out.add((rot, trans))
    return frozenset(out)


requires_backend = pytest.mark.skipif(
    not spacegroups.available(),
    reason="needs spglib or pymatgen to derive operators")


# --------------------------------------------------------------- the resolver
@requires_backend
def test_the_spellings_real_files_use_all_resolve():
    """`P 21/c` is what a CIF writes and the one form pymatgen rejects."""
    canonical = _ops("P2_1/c")
    for spelling in ("P 21/c", "P21/c", "P2(1)/c", "P 1 21/c 1", "p 21/c"):
        assert _ops(spelling) == canonical, spelling


@requires_backend
def test_settings_of_one_group_are_kept_apart():
    """The reason a symbol cannot just be mapped to its IT number.

    All three are number 14. Expanding a P2_1/n file with P2_1/c operators
    produces a confident, completely wrong structure -- so if this test ever
    passes with the sets equal, the feature is worse than not having it.
    """
    c, n, a = _ops("P 21/c"), _ops("P 21/n"), _ops("P 21/a")
    assert c != n and n != a and c != a
    assert all(len(s) == 4 for s in (c, n, a))


@requires_backend
def test_the_pre_1992_double_glide_names_resolve():
    """`Cmca` was renamed `Cmce`; ZIF-L.cif still says `Cmca`."""
    for old, new in (("Cmca", "Cmce"), ("Aba2", "Aea2"), ("Abm2", "Aem2"),
                     ("Cmma", "Cmme"), ("Ccca", "Ccce")):
        assert _ops(old) == _ops(new), old


@requires_backend
def test_the_pre_1990_bar_less_spelling_resolves():
    """Older files write `F d 3 m` for what is now `Fd-3m`."""
    assert _ops("F d 3 m") == _ops("Fd-3m")
    assert _ops("P m 3 m") == _ops("Pm-3m")


@requires_backend
def test_an_unknown_symbol_is_not_guessed_at():
    assert spacegroups.operators_for("Wibble 7") is None
    assert spacegroups.operators_for("") is None


@requires_backend
def test_the_hall_symbol_and_the_number_are_both_routes():
    by_hall = spacegroups.operators_for(hall="-P 2yn")
    by_number = spacegroups.operators_for(number=14)
    assert by_hall is not None and by_number is not None
    assert frozenset(by_hall.xyz) == _ops("P 21/n")     # the Hall names b2
    assert frozenset(by_number.xyz) == _ops("P 21/c")   # a number has no setting
    assert by_number.source == spacegroups.SOURCE_NUMBER


@requires_backend
def test_a_rhombohedral_cell_picks_the_rhombohedral_setting():
    """`R -3 c` is spelled the same on both axes, so the CELL is the evidence."""
    hexagonal = spacegroups.operators_for("R -3 c", rhombohedral=False)
    rhombo = spacegroups.operators_for("R -3 c", rhombohedral=True)
    assert len(hexagonal.xyz) == 36 and len(rhombo.xyz) == 12
    assert cif.Cell(6.0, 6.0, 6.0, 95.0, 95.0, 95.0).looks_rhombohedral()
    assert not cif.Cell(5.0, 5.0, 17.0, 90.0, 90.0, 120.0).looks_rhombohedral()


@requires_backend
def test_an_explicit_origin_choice_is_obeyed_and_not_called_an_assumption():
    plain = spacegroups.operators_for("F d -3 m")
    stated = spacegroups.operators_for("F d -3 m :2")
    assert frozenset(plain.xyz) == frozenset(stated.xyz)
    assert plain.ambiguous and not stated.ambiguous


# ------------------------------------------------------------------ the reader
@requires_backend
def test_a_named_group_without_a_loop_is_expanded():
    data = _parse("_symmetry_space_group_name_H-M 'P 21/c'")
    assert len(data.symops) == 4
    assert data.symmetry_source == spacegroups.SOURCE_SYMBOL
    symbols, _ = cif.expand(data, boundary=False)
    assert len(symbols) == 8                      # 2 sites x 4 operators
    assert "4 generated from the space group" in data.symmetry_note


def test_the_files_own_loop_is_never_second_guessed():
    """Some programs write P1 coordinates under the parent group's name.

    Re-applying the named group's operators would DOUBLE such a structure, so
    a loop -- even a short one -- is taken at its word.
    """
    data = _parse("_symmetry_space_group_name_H-M 'P 21/c'\n"
                  "loop_\n_symmetry_equiv_pos_as_xyz\n'x,y,z'\n"
                  "'-x,y+1/2,-z+1/2'")
    assert len(data.symops) == 2
    assert data.symmetry_source == spacegroups.SOURCE_FILE
    assert not data.symmetry_note


def test_an_identity_only_loop_is_reported_but_obeyed():
    data = _parse("_symmetry_space_group_name_H-M 'P 21/c'\n"
                  "loop_\n_symmetry_equiv_pos_as_xyz\n'x,y,z'")
    assert len(data.symops) == 1
    assert "only the identity" in data.symmetry_note


def test_a_file_that_really_is_p1_says_nothing():
    for header in ("", "_symmetry_space_group_name_H-M 'P 1'",
                   "_symmetry_Int_Tables_number 1"):
        data = _parse(header)
        assert data.symmetry_source == spacegroups.SOURCE_P1
        assert not data.symmetry_note, header


def test_an_unresolvable_group_is_reported_not_silently_dropped():
    """The whole point: this case used to be indistinguishable from success."""
    data = _parse("_symmetry_space_group_name_H-M 'Wibble 7'")
    assert len(data.symops) == 1
    assert data.symmetry_source == spacegroups.SOURCE_UNRESOLVED
    assert "Wibble 7" in data.symmetry_note
    assert "asymmetric unit only" in data.symmetry_note


def test_derivation_can_be_switched_off():
    data = cif.parse_cif(
        MINIMAL.format(header="_symmetry_space_group_name_H-M 'P 21/c'"),
        derive_symmetry=False)
    assert len(data.symops) == 1
    assert data.symmetry_source == spacegroups.SOURCE_UNRESOLVED


def test_a_missing_backend_says_so_instead_of_failing_quietly(monkeypatch):
    """Neither library is a hard dependency, so the no-backend path is real.

    Patched at the module boundary rather than by hiding the imports: what is
    under test is the READER's reporting when nothing can answer, and a note
    that just says "could not expand" would leave the user with no idea that
    installing one package fixes it.
    """
    monkeypatch.setattr(spacegroups, "operators_for", lambda *a, **k: None)
    monkeypatch.setattr(spacegroups, "available", lambda: "")
    data = _parse("_symmetry_space_group_name_H-M 'P 21/c'")
    assert data.symmetry_source == spacegroups.SOURCE_UNRESOLVED
    assert "spglib" in data.symmetry_note


# -------------------------------------------------------------- the whole file
@requires_backend
def test_ferrocene_expands_to_its_own_formula_times_z():
    """The independent check that needs no other library (round 39's lesson).

    `C10 H10 Fe` x Z=2 = 42 atoms. Before this round the same file gave 11 --
    the asymmetric unit, silently.
    """
    text = open(FERROCENE, encoding="utf-8").read()
    data = cif.parse_cif(text)
    assert data.n_sites == 11
    assert data.symmetry_source == spacegroups.SOURCE_HALL
    symbols, coords = cif.expand(data, boundary=False)
    assert len(symbols) == 42
    assert sorted(symbols).count("C") == 20
    assert sorted(symbols).count("H") == 20
    assert sorted(symbols).count("Fe") == 2
    assert len(cif.expand(cif.parse_cif(text, derive_symmetry=False),
                          boundary=False)[0]) == 11


@requires_backend
def test_the_derived_operators_match_the_hall_symbol_the_file_also_gives():
    """Two independent statements in one file, which must agree.

    `P 1 21/a 1` (a symbol with a setting) and `-P 2yab` (a Hall symbol) are
    the same operators said twice, so the file cross-checks the resolver.
    """
    data = cif.parse_cif(open(FERROCENE, encoding="utf-8").read())
    from_symbol = spacegroups.operators_for("P 1 21/a 1")
    # Compared as OPERATORS, not as text: `SymOp.as_xyz` writes "0.5" where
    # the generator writes "1/2", and the two parse to the same thing.
    assert _canonical(cif.SymOp.from_xyz(t) for t in from_symbol.xyz) == \
        _canonical(data.symops)


@requires_backend
def test_the_import_metadata_carries_the_provenance(tmp_path):
    """`_read_cif` has to pass it on, or the UI cannot report it."""
    records = io.read_structures(FERROCENE)
    (atoms, meta), = records
    assert len(atoms) > 11
    assert meta["symmetry_source"] == spacegroups.SOURCE_HALL
    assert "generated from the Hall symbol" in meta["symmetry_note"]
    assert meta["hall"] == "-P 2yab"


# ------------------------------------------------------------- the loop parser
def test_a_double_spaced_loop_header_is_read():
    """H7Mg2O10P2.cif puts a blank line between every tag, which is legal.

    The tag scan stopped at the first blank line, so the whole atom-site loop
    vanished and a good file was rejected with "no fractional atom sites".
    """
    spaced = """data_x
_cell_length_a 8.0
_cell_length_b 8.0
_cell_length_c 8.0

loop_

_atom_site_label

_atom_site_type_symbol

_atom_site_fract_x

_atom_site_fract_y

_atom_site_fract_z

C1 C 0.1 0.2 0.3
O1 O 0.4 0.5 0.6
"""
    data = cif.parse_cif(spaced)
    assert data.n_sites == 2
    assert data.symbols == ["C", "O"]


# ------------------------------------------------------------------------- UI
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


@requires_backend
def test_the_window_states_where_the_symmetry_came_from(win):
    win.open_path(FERROCENE)
    obj = win.scene.objects[-1]
    note = win.symmetry_note(obj.structure)
    assert note and "Hall symbol" in note
    # And it reaches the page someone opens to ask why the cell looks so.
    win._sync_crystal_page()
    assert "Symmetry:" in win.crystal_page.summary.text()
