"""The results table both searches use: sorting, stars and a divider.

Rounds 86 and 87 built this behaviour for the crystal search - numeric columns
that sort as numbers, unknowns that sink whichever way the column points, a
third click that restores the search ranking, a star column backed by
persistent favourites, and a full-width rule separating the two kinds of row.
Round 90 needed all of it again for the molecule search.

Two copies of that is exactly the drift this project keeps finding, so it is
one widget with four hooks. What stays in each dialog is what genuinely
differs: the columns, what a row is chosen BY, and what happens to the one
that is selected.

The table owns the FAVOURITES dictionary because the star column is what edits
it; persisting them is the window's job, which is why `favourites_changed` is
a signal rather than a call into settings from here.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                               QTableWidgetItem)


class ResultTable(QTableWidget):
    """A ranked list of search results with bookmarks.

    Subclass and implement `cells_for` and `key_for`; override `sort_value`
    and `decorate` where a column needs more than its text.
    """

    #: Header labels. The first is the star, which is a CONTROL rather than a
    #: column of data: it carries no text and never sorts.
    COLUMNS = ("★",)
    STAR = 0

    #: `{column index: attribute name}` for columns holding a NUMBER.
    #: `QTableWidgetItem` sorts LEXICALLY, so "100" would sort before "98" and
    #: a run of empty cells would sort among the digits - which is why the
    #: sorting here is done in PYTHON, off the attribute named here, and
    #: never by Qt.
    #:
    #: Round 86 ALSO wrote the value into `Qt.EditRole` so that Qt could
    #: compare it, and then never asked Qt to. That write was not merely
    #: redundant: **a QTableWidgetItem keeps DisplayRole and EditRole in one
    #: slot**, so it silently replaced the formatted text with the raw float
    #: and the column was rendered by Qt rather than by `cells_for`. It went
    #: unnoticed for four rounds because a temperature and a year are whole
    #: numbers and 293.0 happens to render as "293"; a molecular weight of
    #: 106.168 renders as "106.168" next to a neighbour's "106.16", which is
    #: how it was finally seen.
    NUMERIC_COLUMNS = {}

    #: Where a blank sorts. A missing temperature is not 0 K and a missing
    #: molecular weight is not zero, so unknowns are pinned BELOW everything
    #: either way up rather than being given a number that ranks them.
    UNKNOWN = float("inf")

    #: Which column takes the leftover width.
    STRETCH_COLUMN = 1

    #: What the rule between results and bookmarks says.
    DIVIDER_TEXT = "FAVOURITES"

    #: Multi-select? A crystal search wants it (two polymorphs side by side);
    #: a molecule search does not, because the panel beside it shows ONE
    #: structure and a multi-selection would leave it showing an arbitrary
    #: member of the set.
    MULTI_SELECT = True

    chosen_changed = Signal()
    item_activated = Signal(object)
    favourites_changed = Signal()

    def __init__(self, parent=None, favourites=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection
                              if self.MULTI_SELECT
                              else QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        #: The ranked results. Sorting reorders only the VIEW.
        self.results = []
        #: Bookmarks, `{key: item}`.
        self.favourites = dict(favourites or {})
        #: The rows AS DRAWN, mapping a row back to what it draws. `None`
        #: marks the divider.
        self._shown = []
        self._divider_rows = set()
        self._sort_column = None
        self._sort_desc = False
        self._loading_stars = False
        # Sorting is driven by hand rather than by `setSortingEnabled(True)`,
        # because the rows have a MEANINGFUL default order - the ranking is
        # the one thing the search itself is for - and Qt's built-in sorting
        # has no way back to it.
        head = self.horizontalHeader()
        head.setSectionsClickable(True)
        head.sectionClicked.connect(self._sort_by)
        head.setToolTip("Click to sort; click again to reverse, and a third "
                        "time to go back to the search ranking")
        self.itemChanged.connect(self._star_toggled)
        self.itemSelectionChanged.connect(self.chosen_changed)
        self.doubleClicked.connect(self._activate)

    # -------------------------------------------------------- for subclasses
    def cells_for(self, item):
        # type: (object) -> tuple
        """One string per column. The star column's entry is ignored."""
        raise NotImplementedError

    def key_for(self, item):
        # type: (object) -> str
        """Identity, for favourites and for de-duplication."""
        raise NotImplementedError

    def sort_value(self, item, column):
        """What a row is compared BY in one column.

        Text folds case, or `Quartz` and `quartz` end up in different halves.
        The first element of the pair is 0 for a known value and 1 for an
        unknown, which is what keeps blanks at the bottom in both directions.
        """
        field = self.NUMERIC_COLUMNS.get(column)
        if field is not None:
            try:
                return (0, float(getattr(item, field, None)))
            except (TypeError, ValueError):
                return (1, self.UNKNOWN)
        return (0, self.cells_for(item)[column].lower())

    def decorate(self, item, widget_item, column):
        """Hook for per-cell colouring and tooltips. Does nothing here."""

    def star_tooltip(self):
        return "Keep this in the list"

    # -------------------------------------------------------------- filling
    def set_results(self, results):
        self.results = list(results or [])
        self.refill()

    def append_results(self, items):
        """Add rows WITHOUT touching the ones already drawn.

        This is what makes an incrementally filled list honest: a provider
        landing second may add rows, never move them. See
        `molsearch.merge_batch`, and round 78 for why anything recomputed
        under the user's hand is a bug rather than a refresh.
        """
        if not items:
            return
        self.results.extend(items)
        self.refill()

    def _sort_by(self, column):
        """Cycle: ascending, descending, then back to the ranking."""
        if column == self.STAR:
            return                      # a control, not a column of data
        if column != self._sort_column:
            self._sort_column, self._sort_desc = column, False
        elif not self._sort_desc:
            self._sort_desc = True
        else:
            self._sort_column, self._sort_desc = None, False
        self.refill()

    def ordered_results(self):
        if self._sort_column is None:
            return list(self.results)           # the search ranking
        column = self._sort_column
        rows = sorted(self.results,
                      key=lambda h: self.sort_value(h, column),
                      reverse=self._sort_desc)
        if self._sort_desc:
            # `reverse` would also flip the unknowns to the TOP, which is the
            # one thing they must never do. They are lifted out and
            # re-appended instead.
            known = [h for h in rows if self.sort_value(h, column)[0] == 0]
            unknown = [h for h in self.results
                       if self.sort_value(h, column)[0] != 0]
            rows = known + unknown
        return rows

    def favourites_below(self, shown):
        """Favourites that are not already among the results.

        One the search FOUND stays in the results with its star ticked -
        showing it twice would make one compound look like two, and the copy
        in the results is the one carrying its rank.
        """
        seen = {self.key_for(h) for h in shown}
        return [h for k, h in sorted(self.favourites.items()) if k not in seen]

    def refill(self):
        results = self.ordered_results()
        extra = self.favourites_below(results)
        self._divider_rows = set()
        self._shown = list(results)
        divider_at = None
        if extra:
            if results:
                divider_at = len(self._shown)
                self._shown.append(None)          # placeholder for the rule
            self._shown.extend(extra)
        self._loading_stars = True
        self.setRowCount(len(self._shown))
        if divider_at is not None:
            self._add_divider(divider_at)
        for row, entry in enumerate(self._shown):
            if entry is None:
                continue
            self._fill_row(row, entry)
        self._loading_stars = False
        self.resizeColumnsToContents()
        if 0 <= self.STRETCH_COLUMN < len(self.COLUMNS):
            self.horizontalHeader().setSectionResizeMode(
                self.STRETCH_COLUMN, QHeaderView.Stretch)
        self.setColumnWidth(self.STAR, 26)

    def _fill_row(self, row, entry):
        cells = self.cells_for(entry)
        for column, value in enumerate(cells):
            widget_item = QTableWidgetItem(str(value))
            if column == self.STAR:
                widget_item.setFlags((widget_item.flags()
                                      | Qt.ItemIsUserCheckable)
                                     & ~Qt.ItemIsEditable)
                widget_item.setCheckState(
                    Qt.Checked if self.key_for(entry) in self.favourites
                    else Qt.Unchecked)
                widget_item.setToolTip(self.star_tooltip())
                self.setItem(row, column, widget_item)
                continue
            # No EditRole write: see NUMERIC_COLUMNS. The cell shows exactly
            # what `cells_for` formatted, and `sort_value` does the comparing.
            self.decorate(entry, widget_item, column)
            self.setItem(row, column, widget_item)

    def _add_divider(self, row):
        """A full-width rule, drawn the way the F3 palette draws one: a long
        list needs to say where one kind of entry stops and another starts,
        and a heading that cannot be selected is what does it."""
        item = QTableWidgetItem("──  {}  ".format(self.DIVIDER_TEXT)
                                + "─" * 40)
        item.setFlags(Qt.NoItemFlags)               # a divider, not a choice
        item.setForeground(QColor(130, 165, 205))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.setItem(row, 0, item)
        self.setSpan(row, 0, 1, len(self.COLUMNS))
        self._divider_rows.add(row)

    # ----------------------------------------------------------- favourites
    def _star_toggled(self, widget_item):
        """A star ticked or unticked. Persistence is the window's job."""
        if self._loading_stars or widget_item.column() != self.STAR:
            return
        row = widget_item.row()
        if row >= len(self._shown) or self._shown[row] is None:
            return
        entry = self._shown[row]
        if widget_item.checkState() == Qt.Checked:
            self.favourites[self.key_for(entry)] = entry
        else:
            self.favourites.pop(self.key_for(entry), None)
        self.favourites_changed.emit()

    # ------------------------------------------------------------- choosing
    def selected_rows(self):
        """Rows that are a RESULT. The divider is furniture, and a favourite
        below it is still importable, so the rule is the only exclusion."""
        return sorted({i.row() for i in self.selectedIndexes()
                       if i.row() not in self._divider_rows})

    def chosen(self):
        return [self._shown[r] for r in self.selected_rows()
                if 0 <= r < len(self._shown) and self._shown[r] is not None]

    def current_item(self):
        """The single row a preview panel should describe, or None."""
        picked = self.chosen()
        return picked[0] if len(picked) == 1 else None

    def _activate(self, index):
        row = index.row()
        if 0 <= row < len(self._shown) and self._shown[row] is not None:
            self.item_activated.emit(self._shown[row])
