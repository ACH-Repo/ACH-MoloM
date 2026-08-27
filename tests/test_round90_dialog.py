"""Round 90: the molecule search DIALOG, driven rather than described.

Round 59's lesson is the reason this file exists: a mechanism with tests and
no gesture test is a feature nobody can reach. `core/molsearch.py` is covered
in `test_round90_molsearch.py`; these drive the widget.
"""
import pytest

from molom.core import molsearch


@pytest.fixture
def dialog():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.dialogs import MoleculeSearchDialog

    def build(candidates=(), favourites=None):
        dlg = MoleculeSearchDialog(None, favourites=favourites)
        if candidates:
            dlg.table.set_results(list(candidates))
        return dlg
    return build


def _cand(name, key, weight=None, smiles="Cc1ccccc1C", **kw):
    return molsearch.Candidate("pubchem", ref=key, name=name, inchikey=key,
                               smiles=smiles, formula="C8H10", weight=weight,
                               **kw)


def _isomers():
    return [_cand("O-Xylene", "K1", 106.17), _cand("M-Xylene", "K2", 106.16),
            _cand("P-Xylene", "K3", 106.16)]


# ------------------------------------------------------ incremental filling
def test_results_land_incrementally_without_reordering(dialog):
    """The dialog fills as providers answer, and a row already on screen is
    never moved - round 78's rule, which is why this goes through
    `merge_batch` rather than replacing the list."""
    dlg = dialog()
    dlg._landed("opsin", [_cand("O-Xylene", "K1", 106.17)])
    assert dlg.table.rowCount() == 1
    dlg._landed("pubchem", [_cand("M-Xylene", "K2", 106.16),
                            _cand("P-Xylene", "K3", 106.16)])
    assert [c.name for c in dlg.candidates] == ["O-Xylene", "M-Xylene",
                                                "P-Xylene"]


def test_a_second_provider_fills_the_row_rather_than_adding_one(dialog):
    """OPSIN's structure and PubChem's name are the same compound."""
    dlg = dialog()
    bare = molsearch.Candidate("opsin", ref="xylene", inchikey="K1",
                               smiles="Cc1ccccc1C")
    dlg._landed("opsin", [bare])
    dlg._landed("pubchem", [_cand("O-Xylene", "K1", 106.17)])
    assert len(dlg.candidates) == 1
    assert dlg.candidates[0].name == "O-Xylene"
    assert dlg.table.rowCount() == 1


# --------------------------------------------------------------- the panel
def test_selecting_a_row_draws_its_skeletal_structure(dialog):
    """The whole reason the panel is there: o-, m- and p-xylene share a
    formula AND a weight, so the picture is the only thing in the window that
    can tell them apart."""
    from molom.core import depict
    if not depict.available():
        pytest.skip("RDKit was built without the Cairo backend")
    dlg = dialog(_isomers())
    dlg.table.selectRow(0)
    pixmap = dlg.picture.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert "O-Xylene" in dlg.detail.text()


def test_an_interpreted_name_is_shown_in_the_panel(dialog):
    """OPSIN reading "xylene" as o-xylene is exactly the thing a user would
    otherwise never be told."""
    cand = _cand("O-Xylene", "K1", 106.17)
    cand.note = "read 'xylene' as O-Xylene"
    dlg = dialog([cand])
    dlg.table.selectRow(0)
    assert "read 'xylene' as O-Xylene" in dlg.detail.text()


def test_the_table_is_single_select_so_the_panel_is_never_ambiguous(dialog):
    from PySide6.QtWidgets import QAbstractItemView
    dlg = dialog(_isomers())
    assert dlg.table.selectionMode() == QAbstractItemView.SingleSelection


# ------------------------------------------------------------- the columns
def test_weight_sorts_numerically_and_blanks_sink(dialog):
    """`QTableWidgetItem` compares LEXICALLY, so 106.17 would sort against
    99.5 as text - hence the hand-driven sort - and an unknown weight is not
    zero, so it sinks whichever way the column points."""
    cands = [_cand("A", "K1", 106.17), _cand("B", "K2", 99.5),
             _cand("C", "K3", None)]
    dlg = dialog(cands)
    weight_column = 3
    dlg.table._sort_by(weight_column)
    assert [c.name for c in dlg.table.ordered_results()] == ["B", "A", "C"]
    dlg.table._sort_by(weight_column)               # descending
    assert [c.name for c in dlg.table.ordered_results()] == ["A", "B", "C"]
    dlg.table._sort_by(weight_column)               # back to the ranking
    assert dlg.table._sort_column is None
    assert [c.name for c in dlg.table.ordered_results()] == ["A", "B", "C"]


# ------------------------------------------------------------- favourites
def test_starring_a_row_adds_it(dialog):
    from PySide6.QtCore import Qt
    dlg = dialog(_isomers())
    dlg.table.item(0, dlg.table.STAR).setCheckState(Qt.Checked)
    assert list(dlg.favourites) == ["K1"]
    dlg.table.item(0, dlg.table.STAR).setCheckState(Qt.Unchecked)
    assert dlg.favourites == {}


def test_favourites_show_with_no_search_and_sink_below_a_rule_after_one(dialog):
    favourite = _cand("Ferrocene", "KF", 186.03)
    dlg = dialog(favourites={"KF": favourite})
    assert dlg.table.rowCount() == 1          # they ARE the window's content
    assert not dlg.table._divider_rows
    dlg.table.set_results(_isomers())
    assert dlg.table._divider_rows            # now they need separating
    assert dlg.table.rowCount() == 5          # 3 results + rule + 1 favourite


def test_a_favourite_the_search_FOUND_is_not_shown_twice(dialog):
    found = _cand("O-Xylene", "K1", 106.17)
    dlg = dialog(favourites={"K1": found})
    dlg.table.set_results(_isomers())
    assert dlg.table.rowCount() == 3
    assert not dlg.table._divider_rows


# --------------------------------------------------------------- remembering
def test_the_last_search_comes_back_without_re_running_it(dialog):
    import time
    dlg = dialog(_isomers())
    dlg.edit.setText("xylene")
    query, cands, when = dlg.remembered()
    assert query == "xylene" and len(cands) == 3
    again = dialog()
    again.restore((query, cands, when - 600))
    assert len(again.candidates) == 3
    assert again._worker is None              # NOT re-run
    assert "minutes ago" in again.info.text()
