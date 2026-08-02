"""Round 17: element resolution by name, and the periodic-table layout."""

import pytest

from molom.core import elements, ptable


# ------------------------------------------------------- name / symbol input
@pytest.mark.parametrize("text,want", [
    ("C", "C"), ("c", "C"), ("FE", "Fe"), ("fe", "Fe"), ("Fe", "Fe"),
    ("carbon", "C"), ("Carbon", "C"), ("CARBON", "C"), ("  carbon ", "C"),
    ("iron", "Fe"), ("IRON", "Fe"),
    ("oxygen", "O"), ("nitrogen", "N"), ("tungsten", "W"),
    ("aluminum", "Al"), ("aluminium", "Al"),     # both spellings
    ("cesium", "Cs"), ("caesium", "Cs"),
    ("sulphur", "S"), ("sulfur", "S"),
])
def test_symbol_from_text_accepts_symbols_and_names(text, want):
    assert elements.symbol_from_text(text) == want


def test_names_win_over_the_tolerant_symbol_reading():
    """`atomic_number` truncates, so "iron" would read as iodine (I) and
    "boron" as B-then-junk. Whole names must be tried first."""
    assert elements.symbol_from_text("iron") == "Fe"
    assert elements.symbol_from_text("silicon") == "Si"
    assert elements.symbol_from_text("copper") == "Cu"
    # ...while a bare symbol still resolves the tolerant way.
    assert elements.symbol_from_text("Cl2") == "Cl"


def test_unknown_text_is_empty_not_a_dummy_atom():
    for junk in ("", "   ", "zzz", "unobtainium", "42", "carbonn", "iiron"):
        assert elements.symbol_from_text(junk) == "", junk
        assert elements.from_text(junk) == 0, junk


def test_a_mistyped_name_is_not_truncated_into_an_element():
    """The tolerant symbol reading keeps only the first 1-2 letters, so
    "unobtainium" used to come back as uranium. A word too long to be a
    symbol must match a NAME or fail."""
    assert elements.symbol_from_text("unobtainium") == ""
    assert elements.symbol_from_text("nitrogenn") == ""
    # ...but the genuine symbol-with-junk cases still work.
    assert elements.symbol_from_text("C1") == "C"
    assert elements.symbol_from_text("Fe3") == "Fe"


def test_every_element_resolves_from_its_own_name():
    for z in range(1, elements.ELEMENT_COUNT):
        assert elements.from_text(elements.NAMES[z]) == z
        assert elements.from_text(elements.SYMBOLS[z]) == z


# -------------------------------------------------------- periodic table map
def test_layout_places_every_element_exactly_once():
    cells = ptable.layout()
    zs = sorted(z for z, _r, _c in cells)
    assert zs == list(range(1, 119))


def test_layout_has_no_two_elements_in_one_cell():
    seen = {}
    for z, row, col in ptable.layout():
        assert (row, col) not in seen, \
            "{} collides with {}".format(z, seen.get((row, col)))
        seen[(row, col)] = z


def test_layout_stays_inside_the_chart():
    for z, row, col in ptable.layout():
        assert 1 <= col <= ptable.COLUMNS
        assert 1 <= row <= ptable.ROWS
        assert row != ptable.MAIN_ROWS + 1, "row 8 is the f-block gap"


def test_the_famous_corners_are_where_a_chemist_expects():
    pos = {z: (r, c) for z, r, c in ptable.layout()}
    assert pos[1] == (1, 1)                      # H top left
    assert pos[2] == (1, 18)                     # He top right
    assert pos[6] == (2, 14)                     # C, group 14
    assert pos[8] == (2, 16)                     # O, group 16
    assert pos[26] == (4, 8)                     # Fe, group 8
    assert pos[57] == (ptable.LANTHANIDE_ROW, 3)   # La starts the f-block
    assert pos[71] == (ptable.LANTHANIDE_ROW, 17)  # Lu ends it
    assert pos[89] == (ptable.ACTINIDE_ROW, 3)     # Ac
    assert pos[103] == (ptable.ACTINIDE_ROW, 17)   # Lr
    assert pos[72] == (6, 4)                     # Hf resumes the main body
    assert pos[118] == (7, 18)                   # Og bottom right


def test_cell_text_contrast_flips_with_the_element_colour():
    # The Jmol palette spans near-white (H 240,240,240; F is pale cyan) to
    # near-black (Cs is deep purple), so a fixed foreground is unreadable at
    # one end or the other.
    assert ptable.text_is_dark(1)          # off-white H  -> black text
    assert ptable.text_is_dark(9)          # pale cyan F  -> black text
    assert not ptable.text_is_dark(55)     # dark purple Cs -> white text
    assert not ptable.text_is_dark(7)      # blue N       -> white text
