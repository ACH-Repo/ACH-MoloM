"""Round 68: defining and correcting a unit cell.

Christian, 2026-08-12: "what we definitely need is a way to define the unit cell
parameters, right?" - and he was right. Everything in `core/cif.py` CONSUMES a
cell that arrived in a file; the crystal page rendered a, b, c and the angles as
read-only text. A molecule with no cell could never be given one and an
imported cell could never be corrected.
"""

import numpy as np
import pytest

from molom.core import celledit
from molom.core.cif import Cell
from molom.core.structure import Structure


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


def _two_atoms():
    s = Structure(["C", "C"], np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0]]))
    s.bonds = [(0, 1, 1)]
    return s


# ------------------------------------------------------------- validation
def test_a_plain_cubic_cell_is_accepted():
    celledit.validate(5.0, 5.0, 5.0, 90.0, 90.0, 90.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_lengths_must_be_positive(bad):
    with pytest.raises(celledit.CellError):
        celledit.validate(bad, 5.0, 5.0, 90.0, 90.0, 90.0)


@pytest.mark.parametrize("angle", [0.0, 180.0, 200.0, -30.0])
def test_angles_must_be_in_range(angle):
    with pytest.raises(celledit.CellError):
        celledit.validate(5.0, 5.0, 5.0, angle, 90.0, 90.0)


def test_angles_that_cannot_close_are_refused():
    """The part that catches people out: the three angles are NOT independent.
    30/30/120 passes every per-angle range check and describes no solid at all
    - the faces cannot meet."""
    with pytest.raises(celledit.CellError) as excinfo:
        celledit.validate(5.0, 5.0, 5.0, 30.0, 30.0, 120.0)
    assert "close" in str(excinfo.value)


def test_a_real_monoclinic_cell_is_fine():
    celledit.make_cell(10.443, 7.572, 5.824, 90.0, 120.95, 90.0)


def test_a_legal_triclinic_cell_is_fine():
    celledit.make_cell(6.0, 7.0, 8.0, 80.0, 95.0, 105.0)


# --------------------------------------------------------------- suggest
def test_a_suggested_cell_contains_the_molecule():
    s = _two_atoms()
    cell = celledit.suggest_cell(s, padding=2.0)
    assert cell.a >= 3.0                      # the span, plus the margin
    assert cell.alpha == 90.0 and cell.gamma == 90.0


def test_suggesting_for_an_empty_structure_still_gives_a_cell():
    assert celledit.suggest_cell(Structure([], np.zeros((0, 3)))) is not None


# ------------------------------------------------------- applying a cell
def test_giving_a_cell_less_molecule_a_box_does_not_move_it():
    """There are no fractional coordinates to preserve - only a box being
    drawn around what is already there."""
    s = _two_atoms()
    before = s.coords.copy()
    report = celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    assert report["had_cell"] is False
    assert report["kept"] == "cartesian"
    assert np.allclose(s.coords, before)


def test_correcting_a_cell_keeps_the_FRACTIONAL_positions():
    """Fractional coordinates ARE the structure; a, b, c are the frame."""
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    report = celledit.apply_cell(s, celledit.make_cell(20.0, 10.0, 10.0))
    assert report["kept"] == "fractional"
    assert s.coords[1][0] == pytest.approx(6.0)     # x doubled with a


def test_keeping_cartesian_leaves_the_atoms_alone():
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    before = s.coords.copy()
    celledit.apply_cell(s, celledit.make_cell(20.0, 10.0, 10.0),
                        keep_fractional=False)
    assert np.allclose(s.coords, before)


def test_every_frame_is_transformed_not_just_the_current_one():
    s = _two_atoms()
    s.frames.append(s.frames[0] * 2.0)
    celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    celledit.apply_cell(s, celledit.make_cell(20.0, 10.0, 10.0))
    assert s.frames[1][1][0] == pytest.approx(12.0)


def test_a_new_cell_with_no_symmetry_is_P1():
    """P1 is true of every arrangement of atoms, so it is the only honest
    default for a box you have just drawn (round 52's reasoning)."""
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(9.0, 9.0, 9.0))
    assert s.metadata["symops"] == ["x,y,z"]
    assert s.metadata["spacegroup"] == "P 1"


def test_supplied_operators_are_stored():
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(9.0, 9.0, 9.0),
                        symops=["x,y,z", "-x,-y,-z"], spacegroup="P -1")
    assert len(s.metadata["symops"]) == 2
    assert s.metadata["spacegroup"] == "P -1"


def test_an_impossible_cell_is_refused_before_anything_is_written():
    s = _two_atoms()
    with pytest.raises(celledit.CellError):
        celledit.apply_cell(s, Cell(5.0, 5.0, 5.0, 30.0, 30.0, 120.0))
    assert "cell" not in (s.metadata or {})


# --------------------------------------------------------------- removing
def test_removing_a_cell_leaves_the_atoms_where_they_are():
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(9.0, 9.0, 9.0))
    before = s.coords.copy()
    assert celledit.clear_cell(s) is True
    assert celledit.cell_of(s) is None
    assert np.allclose(s.coords, before)


def test_removing_takes_the_crystallography_with_it():
    """Keeping a space group for a cell that no longer exists is how a later
    rebuild invents a structure from nothing."""
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(9.0, 9.0, 9.0),
                        symops=["x,y,z", "-x,-y,-z"], spacegroup="P -1")
    celledit.clear_cell(s)
    for key in ("cell", "symops", "spacegroup"):
        assert key not in s.metadata


def test_removing_a_cell_that_is_not_there_says_so():
    assert celledit.clear_cell(_two_atoms()) is False


# ------------------------------------------------------------- the UI
def test_the_editor_is_live_on_a_molecule_with_no_cell(win):
    """That is the case it exists for - everything else on the page greys out,
    but "give this molecule a box" has to stay reachable."""
    win._sync_crystal_page()
    assert win.crystal_page.cell_editor.isEnabled()


def test_fit_to_molecule_fills_the_fields(win):
    win.on_suggest_cell()
    values, _group, _keep = win.crystal_page.cell_fields()
    assert values["a"] > 1.0 and values["alpha"] == 90.0


def test_apply_puts_a_cell_on_the_molecule(win):
    obj = win._active_obj()
    assert celledit.cell_of(obj.structure) is None
    win.on_suggest_cell()
    win.on_apply_cell()
    assert celledit.cell_of(obj.structure) is not None
    assert win.viewport.show_cell is True


def test_a_refused_cell_is_explained_on_the_page(win):
    """Not in a status-bar message that is gone four seconds later."""
    obj = win._active_obj()
    page = win.crystal_page
    win.on_suggest_cell()
    page.cell_edits["alpha"].setValue(30.0)
    page.cell_edits["beta"].setValue(30.0)
    page.cell_edits["gamma"].setValue(120.0)
    win.on_apply_cell()
    assert "close" in page.cell_note.text()
    assert celledit.cell_of(obj.structure) is None, "nothing should be written"


def test_a_space_group_symbol_is_resolved_through_the_same_database(win):
    """A cell defined here must expand exactly as an imported one would."""
    obj = win._active_obj()
    win.on_suggest_cell()
    win.crystal_page.cell_group.setText("P 21/c")
    win.on_apply_cell()
    assert len(obj.structure.metadata.get("symops") or []) == 4


def test_an_unknown_space_group_changes_nothing(win):
    obj = win._active_obj()
    win.on_suggest_cell()
    win.crystal_page.cell_group.setText("not a group")
    win.on_apply_cell()
    assert "not recognised" in win.crystal_page.cell_note.text()
    assert celledit.cell_of(obj.structure) is None


def test_remove_from_the_page_clears_it(win):
    obj = win._active_obj()
    win.on_suggest_cell()
    win.on_apply_cell()
    win.on_remove_cell()
    assert celledit.cell_of(obj.structure) is None
    assert obj.structure.n_atoms > 0


def test_the_editor_expands_by_its_own_hidden_flag(win):
    """`isVisible` is False for everything on a non-current stacked page, so
    the arrow would only ever expand (round 34)."""
    page = win.crystal_page
    assert page.cell_editor.isHidden()
    page._toggle_editor()
    assert not page.cell_editor.isHidden()
    page._toggle_editor()
    assert page.cell_editor.isHidden()


# ------------------------------------------- fractional coordinate entry
def test_fractional_round_trips():
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(12.0, 12.0, 12.0))
    assert celledit.set_fractional(s, 1, [0.5, 0.25, 0.125]) is True
    assert np.allclose(celledit.fractional_of(s, 1), [0.5, 0.25, 0.125])


def test_fractional_needs_a_cell_to_be_a_fraction_OF():
    s = _two_atoms()
    assert celledit.fractional_of(s, 0) is None
    assert celledit.set_fractional(s, 0, [0.0, 0.0, 0.0]) is False


def test_fractional_respects_a_skewed_cell():
    """3.47 A is a statement about one cell; 0.25 is a statement about the
    structure. A monoclinic frame must not break the mapping."""
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(10.0, 8.0, 6.0, 90.0, 115.0, 90.0))
    celledit.set_fractional(s, 1, [0.3, 0.4, 0.5])
    assert np.allclose(celledit.fractional_of(s, 1), [0.3, 0.4, 0.5], atol=1e-9)


def test_wrapping_is_opt_in():
    """Off by default: an atom outside the cell may be exactly where it
    belongs - a boundary copy, or an unwrapped molecule."""
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    celledit.set_fractional(s, 1, [1.25, 0.0, 0.0])
    assert celledit.fractional_of(s, 1)[0] == pytest.approx(1.25)
    celledit.set_fractional(s, 1, [1.25, 0.0, 0.0], wrap=True)
    assert celledit.fractional_of(s, 1)[0] == pytest.approx(0.25)


def test_every_frame_moves_with_the_atom():
    s = _two_atoms()
    s.frames.append(s.frames[0].copy())
    celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    celledit.set_fractional(s, 1, [0.5, 0.5, 0.5])
    assert np.allclose(s.frames[1][1], s.frames[0][1])


def test_a_non_numeric_fraction_is_refused():
    s = _two_atoms()
    celledit.apply_cell(s, celledit.make_cell(10.0, 10.0, 10.0))
    with pytest.raises(celledit.CellError):
        celledit.set_fractional(s, 0, [float("nan"), 0.0, 0.0])


def test_the_block_is_live_only_for_exactly_one_picked_atom(win):
    obj = win._active_obj()
    win.on_suggest_cell()
    win.on_apply_cell()
    win.viewport.set_selection([(obj.id, 1)])
    assert win.crystal_page.frac_editor.isEnabled()
    win.viewport.set_selection([(obj.id, 1), (obj.id, 2)])
    assert not win.crystal_page.frac_editor.isEnabled()
    win.viewport.set_selection([])
    assert not win.crystal_page.frac_editor.isEnabled()


def test_the_block_is_dead_without_a_cell(win):
    obj = win._active_obj()
    win.viewport.set_selection([(obj.id, 0)])
    assert not win.crystal_page.frac_editor.isEnabled()


def test_typing_a_fraction_moves_the_atom(win):
    obj = win._active_obj()
    win.on_suggest_cell()
    win.on_apply_cell()
    win.viewport.set_selection([(obj.id, 2)])
    for key, value in (("x", 0.75), ("y", 0.5), ("z", 0.25)):
        win.crystal_page.frac_edits[key].setValue(value)
    win.on_apply_fractional()
    assert np.allclose(celledit.fractional_of(obj.structure, 2),
                       [0.75, 0.5, 0.25], atol=1e-9)
