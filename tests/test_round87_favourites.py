"""Round 87: favourites in the crystal search.

Christian: "Add 'favourite' checkboxes to the crystal search by name. Do not
save the cifs locally, just have the links to them or whatever you use stay
persistent when a user selects some. Show them by default when opening the
search window. When a search is performed, sort them to the very bottom
separated by a horizontal line like the ones that F3 search options already
uses to separate different categories of functions."
"""
import tempfile

import pytest

from molom.core import cifsearch
from molom.core.cifsearch import Hit


@pytest.fixture
def dialog():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.dialogs import CifSearchDialog

    def build(hits=(), favourites=None):
        dlg = CifSearchDialog(None, favourites=favourites)
        if hits:
            dlg.hits = list(hits)
            dlg.table.refill()
        return dlg
    return build


def _hits(n=3):
    return [Hit("cod", str(1000 + k), formula="SiO2", name="quartz %d" % k,
                temperature=100 + k, year=2000 + k) for k in range(n)]


# ------------------------------------------------------------- the bookmark
def test_a_favourite_is_a_REFERENCE_not_a_file():
    """Christian: "do not save the cifs locally, just have the links".

    A bookmark stays correct when COD supersedes an entry, and a hundred of
    them cost a few kilobytes of settings rather than a hundred CIFs on disk.
    """
    hit = Hit("cod", "1547149", formula="NbO2", name="niobium oxide",
              temperature=293, year=2011, computed=False)
    data = hit.to_dict()
    assert set(data) >= {"source", "ref", "formula", "temperature", "year"}
    assert not any("cif" in str(v).lower() for v in data.values()
                   if isinstance(v, str))
    back = cifsearch.hit_from_dict(data)
    assert back.key() == hit.key()
    assert back.formula == "NbO2" and back.temperature == 293


def test_identity_is_the_provider_and_its_own_reference():
    """Never the formula or the name: a dozen determinations of quartz share
    both, and COD leaves most entries unnamed (round 85)."""
    a = Hit("cod", "1", formula="SiO2", name="quartz")
    b = Hit("cod", "2", formula="SiO2", name="quartz")
    assert a.key() != b.key()
    assert Hit("cod", "1", name="").key() == a.key()


def test_a_corrupt_entry_is_dropped_not_raised():
    """A stored preference outlives the code that wrote it, and a favourites
    list that raises on load is worse than one that has lost an entry."""
    assert cifsearch.hit_from_dict({}) is None
    assert cifsearch.hit_from_dict("nonsense") is None
    assert cifsearch.hit_from_dict({"ref": "1"}) is None


# ------------------------------------------------------------------- the UI
def test_starring_a_row_adds_it(dialog):
    from PySide6.QtCore import Qt
    dlg = dialog(_hits(3))
    dlg.table.item(1, dlg.STAR).setCheckState(Qt.Checked)
    assert list(dlg.favourites) == [("cod", "1001")]
    dlg.table.item(1, dlg.STAR).setCheckState(Qt.Unchecked)
    assert dlg.favourites == {}


def test_they_show_by_default_with_no_search(dialog):
    """"Show them by default when opening the search window." With nothing
    remembered they ARE the content, so there is nothing to separate them
    from and no rule is drawn."""
    from PySide6.QtCore import Qt
    favs = {h.key(): h for h in _hits(2)}
    dlg = dialog(favourites=favs)
    assert dlg.table.rowCount() == 2
    assert dlg.table._divider_rows == set()
    assert "favourite" in dlg.info.text()
    assert dlg.table.item(0, dlg.STAR).checkState() == Qt.Checked


def test_a_search_pushes_them_below_a_full_width_rule(dialog):
    """The F3 palette's device, for the F3 palette's reason: a long list has
    to say where one kind of entry stops and another starts."""
    favs = {h.key(): h for h in _hits(1)}
    dlg = dialog([Hit("cod", "999", formula="TiO2", name="rutile")],
                 favourites=favs)
    assert dlg.table.rowCount() == 3            # result, rule, favourite
    assert sorted(dlg.table._divider_rows) == [1]
    rule = dlg.table.item(1, 0)
    assert rule.text().startswith("──")
    assert "FAVOURITES" in rule.text()
    assert dlg.table.columnSpan(1, 0) == len(dlg.COLUMNS)
    assert dlg.table.item(0, 1).text() == "TiO2"      # the result is above
    assert dlg.table.item(2, 1).text() == "SiO2"      # the favourite below


def test_a_favourite_the_search_FOUND_is_not_shown_twice(dialog):
    """It stays in the results with its star ticked - showing it twice would
    make one structure look like two, and the copy in the results is the one
    carrying its rank."""
    from PySide6.QtCore import Qt
    found = _hits(3)
    dlg = dialog(found, favourites={found[1].key(): found[1]})
    assert dlg.table.rowCount() == 3
    assert dlg.table._divider_rows == set()
    stars = [dlg.table.item(r, dlg.STAR).checkState() == Qt.Checked
             for r in range(3)]
    assert stars == [False, True, False]


def test_the_rule_is_not_selectable_and_imports_nothing(dialog):
    favs = {h.key(): h for h in _hits(1)}
    dlg = dialog([Hit("cod", "999", formula="TiO2")], favourites=favs)
    row = sorted(dlg.table._divider_rows)[0]
    dlg.table.clearSelection()
    dlg.table.selectRow(row)
    assert dlg.chosen == []
    dlg.table.clearSelection()
    dlg.table.selectRow(row + 1)
    assert [h.formula for h in dlg.chosen] == ["SiO2"]


def test_the_star_column_does_not_sort(dialog):
    """It is a control, not data."""
    dlg = dialog(_hits(3))
    dlg.table._sort_by(dlg.STAR)
    assert dlg.table._sort_column is None


def test_the_numeric_columns_still_sort_numerically(dialog):
    """The star column shifted every index by one; the temperature and year
    columns have to move with it or they compare the wrong field."""
    dlg = dialog([Hit("cod", str(k), formula="SiO2", temperature=t, year=y)
                  for k, (t, y) in enumerate([(100, 2008), (98, 1998),
                                              (293, 1975)])])
    dlg.table._sort_by(4)
    assert [dlg.table.item(r, 4).text() for r in range(3)] == \
        ["98", "100", "293"]
    dlg.table._sort_by(5)
    assert [dlg.table.item(r, 5).text() for r in range(3)] == \
        ["1975", "1998", "2008"]


# ------------------------------------------------------------- persistence
def test_they_survive_a_new_window():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    favs = {h.key(): h for h in _hits(2)}
    win.set_cif_favourites(favs)
    other = MainWindow()
    back = other.cif_favourites()
    assert set(back) == set(favs)
    assert back[("cod", "1000")].temperature == 100


def test_unreadable_settings_do_not_break_the_dialog():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.settings.setValue("cif_favourites", "{not json")
    assert win.cif_favourites() == {}
