"""Round 35: the Settings dialog scrolls and filters.

It outgrew the screen once the Flight section arrived, and a page you have to
scroll needs a way to reach a control without scrolling.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def dlg():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.dialogs import SettingsDialog
    QApplication.instance() or QApplication([])
    return SettingsDialog(None, rotate_speed=1.0, start_maximized=True)


def _visible(dlg):
    from PySide6.QtWidgets import QFormLayout
    form = dlg._form
    out = []
    for row in range(form.rowCount()):
        if not form.isRowVisible(row):
            continue
        item = form.itemAt(row, QFormLayout.LabelRole)
        if item is not None and item.widget() is not None \
                and item.widget().text():
            out.append(item.widget().text())
    return out


def test_the_page_scrolls(dlg):
    from PySide6.QtWidgets import QScrollArea
    assert isinstance(dlg._scroll, QScrollArea)
    assert dlg._scroll.widgetResizable()


def test_ok_and_cancel_are_outside_the_scroll_area(dlg):
    """Buttons you have to scroll to find are buttons people report missing."""
    from PySide6.QtWidgets import QDialogButtonBox
    boxes = dlg.findChildren(QDialogButtonBox)
    assert boxes
    inner = dlg._scroll.widget()
    for box in boxes:
        assert not inner.isAncestorOf(box)


def test_filtering_narrows_to_the_matching_rows(dlg):
    dlg.filter_edit.setText("brake")
    assert _visible(dlg) == ["Auto-brake:"]


def test_filtering_matches_tooltips_not_just_labels(dlg):
    """The real explanation lives in the tooltip for most of these."""
    dlg.filter_edit.setText("creep")
    assert _visible(dlg)


def test_filter_terms_match_at_word_boundaries(dlg):
    """A plain substring search has "roll" dragging in the pointing-device
    row, whose description mentions scrolling."""
    dlg.filter_edit.setText("roll")
    shown = _visible(dlg)
    assert "Roll rate:" in shown
    assert "Pointing device:" not in shown


def test_a_prefix_still_matches(dlg):
    dlg.filter_edit.setText("acce")
    assert "Acceleration:" in _visible(dlg)


def test_matching_a_section_name_reveals_the_whole_section(dlg):
    dlg.filter_edit.setText("flight")
    shown = _visible(dlg)
    for row in ("Acceleration:", "Drag:", "Auto-brake:", "Roll rate:",
                "Auto-bank:", "Turn rate:"):
        assert row in shown
    assert "Undo history:" not in shown


def test_clearing_the_filter_restores_every_row(dlg):
    everything = _visible(dlg)
    dlg.filter_edit.setText("brake")
    assert len(_visible(dlg)) < len(everything)
    dlg.filter_edit.setText("")
    assert _visible(dlg) == everything


def test_a_filter_that_matches_nothing_hides_everything(dlg):
    dlg.filter_edit.setText("zzzznotasetting")
    assert _visible(dlg) == []


def test_the_flight_tuning_round_trips_every_key(dlg):
    from molom.core import flight
    tuning = dlg.flight_tuning()
    # `shuttle_factor` joined in round 69: shuttle mode is deliberately slower
    # than camera flight, and how much slower is a setting.
    assert set(tuning) == {"accel", "damping", "brake_factor",
                           "strafe_factor", "roll_rate", "bank_angle",
                           "aim_expo", "turn_rate", "hold_ms",
                           "shuttle_factor"}
    assert tuning["accel"] == pytest.approx(flight.DEFAULT_ACCEL)
    assert tuning["bank_angle"] == pytest.approx(flight.DEFAULT_BANK_ANGLE)
    assert tuning["hold_ms"] == pytest.approx(flight.DEFAULT_HOLD_MS)


def test_hidden_rows_still_report_their_values(dlg):
    """Filtering is a VIEW. A control scrolled or filtered out of sight must
    still be saved on OK, or the dialog silently discards settings."""
    dlg.filter_edit.setText("brake")
    assert dlg.undo_limit() == 30
    assert dlg.flight_tuning()["roll_rate"] > 0.0
