"""Round 17: atom-label sizing.

Needs a QApplication (font metrics), but no display — the offscreen platform
is enough and no GL context is ever created, since the widget is never shown.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Function-scoped: `conftest._delete_widgets_after_each_test` destroys every
# top-level widget a test created, so a widget built once for a whole module
# is invalid from the second test on. A bare MolViewport is cheap - it makes
# no GL context until it is shown.
@pytest.fixture
def viewport():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.viewport import MolViewport
    app = QApplication.instance() or QApplication([])
    assert app is not None
    return MolViewport()


def test_labels_of_different_length_share_a_size(viewport):
    """The bug: sizing fitted each string to a fixed WIDTH, so on identical
    atoms "C" came out 18 px and "C12" 6 px. Same atom = same height."""
    viewport.label_scale = 1.0
    sizes = {t: viewport._label_font(t, 20.0).pixelSize()
             for t in ("C", "H", "12", "Fe")}
    assert len(set(sizes.values())) == 1, sizes


def test_a_very_long_label_is_squeezed_but_not_shattered(viewport):
    viewport.label_scale = 1.0
    plain = viewport._label_font("C", 20.0).pixelSize()
    long_label = viewport._label_font("C123", 20.0).pixelSize()
    assert long_label <= plain          # squeezed to fit the sphere
    assert long_label > plain * 0.5     # ...but still in the same league


def test_labels_are_not_bold_and_use_a_wide_sans(viewport):
    f = viewport._label_font("C", 20.0)
    assert not f.bold()
    assert f.families()[0] == "Verdana"


def test_label_scale_multiplies_the_size(viewport):
    viewport.label_scale = 1.0
    base = viewport._label_font("C", 20.0).pixelSize()
    viewport.label_scale = 2.0
    assert viewport._label_font("C", 20.0).pixelSize() == pytest.approx(
        base * 2, abs=1)
    viewport.label_scale = 0.5
    assert viewport._label_font("C", 20.0).pixelSize() == pytest.approx(
        base * 0.5, abs=1)
    viewport.label_scale = 1.0


def test_labels_default_smaller_than_the_old_bold_fit(viewport):
    """Regression guard for "the labels are too large": at scale 1.0 the text
    must sit INSIDE the sphere, not span it."""
    viewport.label_scale = 1.0
    assert viewport._label_font("C", 20.0).pixelSize() < 20.0


def test_tiny_atoms_get_no_label_at_all(viewport):
    viewport.label_scale = 1.0
    assert viewport._label_font("C", 2.0) is None
