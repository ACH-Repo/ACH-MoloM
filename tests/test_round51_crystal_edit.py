"""Round 51: editing a crystal without destroying it, and ticks that follow
the crystal they describe.

All from Christian, on MOF-5 (`938392.cif`, CCDC — not redistributable, so the
regression cases here are the vendored fixtures and the rule is tested rather
than the file):

* changing one H to an F moved the cell box off the floor and "doubled" the
  atoms in the cell;
* the coordination-polyhedra tick had to be cycled to take effect, "even
  though it is on";
* unticking Symmetry elements left its filters expanded.
"""

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from molom.core import blender_export as bx  # noqa: E402
from molom.ui.app import MainWindow  # noqa: E402
from molom.ui.viewport import MODE_EDIT, cell_corners_world  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OXIDE = os.path.join(DATA, "cod_1547149_solid_solution.cif")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


@pytest.fixture
def win():
    QApplication.instance() or QApplication([])
    return MainWindow()


def _first(symbols, want):
    return [i for i, s in enumerate(symbols) if s == want][0]


def _change_element(window, obj, index, symbol):
    window.viewport.set_mode(MODE_EDIT, obj.id)
    window.viewport.set_selection([(obj.id, index)])
    window.viewport.apply_element(symbol)


# ------------------------------------------------- the pose capture, at last
def test_a_chemistry_edit_captures_the_pose_like_a_geometry_edit_does(win):
    """Round 43e's fix hung off `on_model_edit_begin`, which only the geometry
    modals use. Every CHEMISTRY edit — element change, draw, bond order,
    delete — goes through `on_edit_begin`, and that was wired straight to
    `push_undo`. So `cell_pose` got measured AFTER the atom had moved, read
    the move as a rotation of the whole crystal, and baked it into the cell
    reference.

    Round 75 put a permission gate in front of the chemistry hook (overwrite
    protection for a molecule carrying computed layers), so the two callbacks
    are no longer the same object - `begin_chemistry_edit` asks, then delegates
    to `begin_model_edit`. The pose capture is what this test is about, so it
    is asserted as BEHAVIOUR now rather than as callback identity, which is
    what made it break on a change that did not touch the thing it guards.
    """
    win.open_path(FERROCENE)
    obj = win._active_obj()
    win.viewport.set_mode("edit", obj.id)
    win._pose_before_edit = None
    assert win.viewport.on_edit_begin() is not False       # the chemistry hook
    assert win._pose_before_edit is not None,         "a chemistry edit did not capture the crystal's pose first"
    assert win._pose_before_edit[0] == obj.id
    win._pose_before_edit = None
    win.viewport.on_model_edit_begin()                     # the geometry hook
    assert win._pose_before_edit is not None


def test_changing_an_element_leaves_the_cell_box_where_it_was(win):
    """Christian's "the unit cell boundary no longer sits on the floor of the
    xy plane". The box is carried by a Kabsch fit against a sample of the
    atoms, so an edit measured after the fact comes back as a rotation nobody
    performed — and a rotated box has a bigger axis-aligned extent, which is
    what makes it look like it moved AND grew."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    before = np.asarray(cell_corners_world(obj))
    _change_element(win, obj, _first(obj.structure.symbols, "H"), "F")
    after = np.asarray(cell_corners_world(win.scene.get(obj.id)))
    assert np.allclose(before, after, atol=1e-6)


def test_the_pose_stays_the_identity_through_a_run_of_edits(win):
    """It has to hold over MANY edits, not just one: the error accumulates,
    which is what "a small re-scaling of the unit cell boundary" was."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    base = np.asarray(cell_corners_world(obj))
    for k in range(4):
        o = win.scene.get(obj.id)
        _change_element(win, o, _first(o.structure.symbols, "H"), "F")
        now = np.asarray(cell_corners_world(win.scene.get(obj.id)))
        assert np.abs(now - base).max() < 1e-6, k


# ------------------------------------- the asymmetric unit and the operators
def test_a_rebuild_after_an_edit_does_not_destroy_the_structure(win):
    """A rebuild is `asym_symbols` + `asym_frac` expanded by `symops`, so
    those three describe ONE structure. Re-deriving the operators after an
    edit and leaving the stored unit alone made them describe two, and the
    rebuild believes the metadata rather than the atoms in front of it: on
    MOF-5, 616 drawn atoms came back as 7."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    _change_element(win, obj, _first(obj.structure.symbols, "O"), "N")
    drawn = win.scene.get(obj.id).structure.n_atoms
    page = win.crystal_page
    page.outside_check.setChecked(not page.outside_check.isChecked())
    page.outside_check.setChecked(not page.outside_check.isChecked())
    after = win.scene.get(obj.id).structure
    assert after.n_atoms == drawn
    assert "N" in after.symbols            # ...and the edit is still there


def test_the_re_derived_unit_matches_the_re_derived_operators(win):
    """The invariant behind it: expanding the stored unit by the stored
    operators has to give back the cell content."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    meta = obj.structure.metadata
    n_content = int(meta["cell_content"])
    _change_element(win, obj, _first(obj.structure.symbols, "O"), "N")
    meta = win.scene.get(obj.id).structure.metadata
    n_asym = len(meta["asym_symbols"])
    assert n_asym * len(meta["symops"]) >= n_content
    assert len(meta["asym_frac"]) == n_asym


def test_the_parallel_columns_are_looked_up_not_sliced(win):
    """Occupancies described the OLD sites, so they cannot be sliced — but
    they need not be thrown away either: `packing.pack` records which
    asymmetric-unit site each drawn atom came from, so each new
    representative can be looked up in the old column. Without it, a
    re-exported solid solution silently claims full occupancy."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    before = list(obj.structure.metadata["asym_occupancy"])
    assert any(o < 1.0 for o in before)
    _change_element(win, obj, _first(obj.structure.symbols, "O"), "N")
    meta = win.scene.get(obj.id).structure.metadata
    after = meta["asym_occupancy"]
    assert len(after) == len(meta["asym_symbols"])
    assert any(o < 1.0 for o in after)         # the partial site survived
    assert set(after) <= set(before)           # ...and no value was invented
    # `site_of` described the unit that has just been replaced, so nothing
    # downstream may believe it any more (round 42's renumbering rule).
    assert "site_of" not in meta


def test_a_column_with_no_mapping_is_dropped_not_guessed(win):
    """A silently mis-indexed occupancy is worse than none (round 43e)."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    obj.structure.metadata.pop("site_of")
    _change_element(win, obj, _first(obj.structure.symbols, "O"), "N")
    meta = win.scene.get(obj.id).structure.metadata
    assert "asym_occupancy" not in meta
    assert len(meta["asym_symbols"]) == len(meta["asym_frac"])


def test_editing_the_asymmetric_unit_still_keeps_the_group(win):
    """The other branch must be untouched: with the base reduced to the
    asymmetric unit, the operators are an INPUT and the edit is repeated by
    them (round 43e)."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    page = win.crystal_page
    page.asym_radio.setChecked(True)
    o = win.scene.get(obj.id)
    group = o.structure.metadata["spacegroup"]
    n_ops = len(o.structure.metadata["symops"])
    _change_element(win, o, _first(o.structure.symbols, "O"), "N")
    o = win.scene.get(obj.id)
    assert o.structure.metadata["spacegroup"] == group
    assert len(o.structure.metadata["symops"]) == n_ops
    page.cell_radio.setChecked(True)
    o = win.scene.get(obj.id)
    assert "N" in o.structure.symbols        # the edit survived the rebuild


# --------------------------------------------- ticks that follow the crystal
def test_the_display_ticks_follow_the_active_crystal(win):
    """They are stored PER OBJECT, so leaving them where the last molecule
    left them makes the page describe a structure that is not on screen —
    "Coordination polyhedra" reads ticked over a crystal that has none, and
    the only way to get a picture is to untick and retick it."""
    win.open_path(FERROCENE)
    a = win._active_obj()
    win.open_path(OXIDE)
    b = win._active_obj()
    page = win.crystal_page
    page.poly_check.setChecked(True)
    page.sym_check.setChecked(True)
    assert b.structure.metadata.get("polyhedra") is True

    win.active_id = a.id
    win._sync_crystal_page()
    assert page.poly_check.isChecked() is False
    assert page.sym_check.isChecked() is False
    assert not a.structure.metadata.get("polyhedra")

    win.active_id = b.id
    win._sync_crystal_page()
    assert page.poly_check.isChecked() is True
    assert page.sym_check.isChecked() is True


def test_syncing_the_page_does_not_write_back_to_the_object(win):
    """`toggled` does not care who moved the box, so an unguarded connection
    reads the refresh as the user asking for it and carries one molecule's
    state onto the next — round 30's TimelinePanel bug in a new costume."""
    win.open_path(FERROCENE)
    a = win._active_obj()
    win.open_path(OXIDE)
    b = win._active_obj()
    win.crystal_page.poly_check.setChecked(True)
    win.active_id = a.id
    win._sync_crystal_page()                 # writes poly_check False
    assert not a.structure.metadata.get("polyhedra")
    # ...and B, which is no longer active, must not have been unticked by it
    assert b.structure.metadata.get("polyhedra") is True


def test_the_symmetry_filters_collapse_when_symmetry_is_switched_off(win):
    """Christian: "if symmetry elements is unchecked, should it not auto
    un-expand?" It should — the filters choose between things none of which
    are being drawn."""
    win.open_path(OXIDE)
    page = win.crystal_page
    page.sym_check.setChecked(True)
    assert not page._kind_holder.isHidden()
    page.sym_check.setChecked(False)
    assert page._kind_holder.isHidden()
    assert page.sym_arrow.text() == "▸"
    page.sym_check.setChecked(True)
    assert not page._kind_holder.isHidden()


def test_the_arrow_still_ticks_the_box_on_the_way_open(win):
    """Round 41's behaviour, which the two-way connection must not break."""
    win.open_path(OXIDE)
    page = win.crystal_page
    page.sym_check.setChecked(False)
    page.sym_arrow.click()
    assert page.sym_check.isChecked()
    assert not page._kind_holder.isHidden()


def test_importing_a_crystal_refreshes_the_page_at_all(win):
    """The one that caused it: `_sync_all` refreshed the modifier page and
    the crystal RIBBON and not the ❖ page, though round 34's comment right
    above it names that page. So an import left every tick showing the
    PREVIOUS molecule's state, and the first click was the one that finally
    set the flag on the new one."""
    win.open_path(OXIDE)
    page = win.crystal_page
    assert page._has_cell is True
    assert page.poly_check.isEnabled()
    page.poly_check.setChecked(True)
    # a second import must reset the page to the NEW molecule
    win.open_path(FERROCENE)
    assert page.poly_check.isChecked() is False
    assert not win._active_obj().structure.metadata.get("polyhedra")


def test_the_filters_follow_the_crystal_too(win):
    win.open_path(FERROCENE)
    a = win._active_obj()
    win.open_path(OXIDE)
    win.crystal_page.sym_check.setChecked(True)
    win.active_id = a.id
    win._sync_crystal_page()
    assert win.crystal_page._kind_holder.isHidden()


# ------------------------------------------------- the Blender render defaults
def test_the_render_defaults_do_not_blow_the_highlights_out():
    """Measured on a MOF-5 render: Standard clipped 4.9% of the molecule to
    pure white, which is the "super exposed" half of Christian's report. AgX
    clips nothing — and bare AgX drops contrast from 0.165 to 0.120, which is
    the "milky" half, so a contrast LOOK is part of the default rather than an
    option nobody would find."""
    opts = bx.ExportOptions()
    assert opts.view_transform == "AgX"
    assert opts.look == "High Contrast"
    assert opts.hdri == "studio"
    # AgX first in the list, since the picker takes the head as its default
    assert bx.VIEW_TRANSFORMS[0] == "AgX"
    assert bx.LOOKS[0] == "High Contrast"


def test_the_look_reaches_the_generated_script():
    from molom.core import style as style_mod
    from molom.core.scene import Scene
    data = bx.collect(Scene(), style_mod.BALL_AND_STICK, bx.ExportOptions())
    src = bx.build_script(data, bx.ExportOptions(look="Punchy"))
    assert '"look": "Punchy"' in src
    assert "view_settings.look" in src
    # Blender is strict about the name and it is per view transform, so the
    # script has to try "AgX - Punchy" before the bare word and fall back.
    assert '"{0} - {1}".format' in src


def test_the_look_survives_the_dialog_round_trip():
    QApplication.instance() or QApplication([])
    from molom.ui.dialogs import BlenderExportDialog
    dlg = BlenderExportDialog(None, bx.ExportOptions(look="Punchy",
                                                     view_transform="Filmic"))
    out = dlg.options()
    assert out.look == "Punchy"
    assert out.view_transform == "Filmic"
