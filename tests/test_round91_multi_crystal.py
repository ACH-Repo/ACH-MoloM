"""Round 91b: a ❖ tick acts on every SELECTED crystal, not just the active one.

Christian, with five isostructural alkali fluorides open: "I wanted to change a
tick box in the cif props pane for all of them simultaneously => Select all,
untick draw atoms outside boundary. I think it basically just selected the last
in the list CsF."

It did. Every control on that page took one `obj_id` and that was the ACTIVE
object, so one crystal changed and the rest silently did not.
"""
import pytest


def _crystal(win, name, a=4.0):
    from molom.core.structure import Structure
    coords, symbols = [], []
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                coords.append([i * a, j * a, k * a])
                symbols.append("Na")
    coords.append([a / 2.0, a / 2.0, a / 2.0])
    symbols.append("F")
    s = Structure.from_atoms(
        [(sym, c[0], c[1], c[2]) for sym, c in zip(symbols, coords)],
        name=name)
    s.metadata.update({
        "cell": {"a": a, "b": a, "c": a,
                 "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
        "spacegroup": "F m -3 m", "symops": ["x,y,z"],
        "asym_symbols": ["Na", "F"],
        "asym_frac": [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    })
    return win.scene.add(s)


@pytest.fixture
def bench():
    """Four crystals and one plain molecule, as his scene had."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.core import build as build_mod
    from molom.ui.app import MainWindow

    win = MainWindow()
    crystals = [_crystal(win, "LiF"), _crystal(win, "NaF"),
                _crystal(win, "KF"), _crystal(win, "CsF")]
    molecule = win.scene.add(build_mod.cubane())
    molecule.name = "cubane"
    win.active_id = crystals[-1].id
    return win, crystals, molecule


def _select_everything(win):
    """Ctrl+A, then make a CRYSTAL active - `set_selection` moves the active
    object to the last thing picked, which here is the plain molecule."""
    win.viewport.set_selection(
        [(o.id, i) for o in win.scene.objects
         for i in range(o.structure.n_atoms)])
    win.active_id = [o for o in win.scene.objects
                     if (o.structure.metadata or {}).get("cell")][-1].id


def test_select_all_then_untick_reaches_every_crystal(bench):
    """The report, as an assertion."""
    win, crystals, _mol = bench
    _select_everything(win)
    win._on_packing_option(win.active_id, "outside", False)
    assert all(c.structure.metadata.get("pack_outside") is False
               for c in crystals)


def test_a_display_flag_reaches_them_too(bench):
    win, crystals, _mol = bench
    _select_everything(win)
    win._set_obj_flag("polyhedra", True)
    assert all(c.structure.metadata.get("polyhedra") for c in crystals)
    win._set_obj_flag("polyhedra", False)
    assert not any(c.structure.metadata.get("polyhedra") for c in crystals)


def test_a_plain_MOLECULE_caught_in_a_select_all_is_passed_over(bench):
    """The ❖ page is the crystal page and its ticks are crystallographic, so
    a molecule swept up by Ctrl+A is not given `show_symmetry` it can do
    nothing with."""
    win, _crystals, molecule = bench
    _select_everything(win)
    win._set_obj_flag("show_symmetry", True)
    assert "show_symmetry" not in (molecule.structure.metadata or {})


def test_with_nothing_selected_it_is_the_active_one_alone(bench):
    """Which is exactly the old behaviour, and the common case."""
    win, crystals, _mol = bench
    win.viewport.set_selection([])
    win._set_obj_flag("polyhedra", True)
    assert crystals[-1].structure.metadata.get("polyhedra")
    assert not any(c.structure.metadata.get("polyhedra")
                   for c in crystals[:-1])


def test_the_active_crystal_is_included_even_when_not_selected(bench):
    """The tick the user just clicked shows the ACTIVE object's state, so it
    would be strange for that one to be the one left behind."""
    win, crystals, _mol = bench
    win.viewport.set_selection([(crystals[0].id, 0)])
    win.active_id = crystals[-1].id      # picking moved it; put it back
    assert {o.name for o in win._crystal_targets()} == {"LiF", "CsF"}


def test_a_SECOND_tick_still_reaches_all_of_them(bench):
    """A packing change rebuilds the view, which regenerates the atom list and
    drops a selection that names atoms by index. Without putting it back the
    first tick would reach five crystals and the second would quietly reach
    one - the very surprise this change removes."""
    win, crystals, _mol = bench
    _select_everything(win)
    win._on_packing_option(win.active_id, "outside", True)
    win._on_packing_option(win.active_id, "copies", True)
    assert all(c.structure.metadata.get("pack_copies") for c in crystals)


def test_the_active_object_is_not_moved_by_a_tick(bench):
    """`on_crystal_view` rebuilds the ACTIVE crystal, so each target takes its
    turn at being active - and it has to be put back, or clicking a tick would
    quietly change which molecule the rest of the UI is describing."""
    win, crystals, _mol = bench
    _select_everything(win)
    before = win.active_id
    win._on_packing_option(win.active_id, "outside", True)
    assert win.active_id == before


def test_the_status_line_says_how_many_were_reached(bench):
    """A control that quietly acts on four objects needs to say so as much as
    one that acts on an object the user was not looking at."""
    win, crystals, _mol = bench
    _select_everything(win)
    win._set_obj_flag("polyhedra", True)
    assert "4 crystals" in win.statusBar().currentMessage()
    win.viewport.set_selection([])
    win._set_obj_flag("polyhedra", False)
    assert "CsF" in win.statusBar().currentMessage()


def test_the_message_names_the_flag_in_english(bench):
    win, _crystals, _mol = bench
    win.viewport.set_selection([])
    win._set_obj_flag("show_refused_bonds", True)
    message = win.statusBar().currentMessage()
    assert "refused bonds" in message and "show_refused_bonds" not in message


def test_an_outliner_row_control_still_acts_on_its_OWN_object(bench):
    """The per-crystal row in the outliner names one object explicitly, and
    that must not broadcast to whatever happens to be selected."""
    win, crystals, _mol = bench
    _select_everything(win)
    win._on_packing_option(crystals[0].id, "outside", True)
    assert crystals[0].structure.metadata.get("pack_outside") is True
    assert all(c.structure.metadata.get("pack_outside") is not True
               for c in crystals[1:])


# ------------------------------------------------- round 93: the rest of it
def test_the_page_stays_live_when_a_MOLECULE_is_active(bench):
    """Christian: "Having benzene in the selection greys out all controls of
    crystal properties tab."

    Picking atoms makes the last one ACTIVE, so sweeping up a solvent killed
    the page - while its controls would have worked perfectly well, since
    `_crystal_targets` filters non-crystals out anyway.
    """
    win, crystals, molecule = bench
    _select_everything(win)
    win.active_id = molecule.id          # the molecule was picked last
    assert win._crystal_subject() in crystals
    win._sync_crystal_page()
    assert win.crystal_page._has_cell, "the controls must stay usable"


def test_with_no_crystal_anywhere_the_page_still_greys(bench):
    win, crystals, molecule = bench
    for c in crystals:
        win.scene.remove(c.id)
    win.active_id = molecule.id
    win.viewport.set_selection([(molecule.id, 0)])
    win._sync_crystal_page()
    assert not win.crystal_page._has_cell


def test_the_view_radio_reaches_every_selected_crystal(bench):
    """Christian: "Switch to asymmetric unit view only works on the active
    crystal when all except CsF are selected." Round 91b made the TICKS act on
    the selection and left the radio behind."""
    win, crystals, _mol = bench
    _select_everything(win)
    win._on_crystal_view_chosen("asym")
    assert all(c.structure.metadata.get("cell_view") == "asym"
               for c in crystals)


def test_the_view_radio_puts_the_active_object_back(bench):
    win, crystals, _mol = bench
    _select_everything(win)
    before = win.active_id
    win._on_crystal_view_chosen("asym")
    assert win.active_id == before


def test_the_cell_box_tick_is_PER_CRYSTAL(bench):
    """Christian: "Show unit cell box is applied to every crystal structure,
    even not selected ones... Is it not a crystal's own internal coordinate
    system that should be displayable?" """
    from molom.ui.viewport import cell_shown
    win, crystals, _mol = bench
    win.viewport.set_selection([(crystals[0].id, 0)])
    win.active_id = crystals[0].id
    win._on_cell_box_toggled(False)
    assert not cell_shown(crystals[0])
    assert all(cell_shown(c) for c in crystals[1:]), "the others keep theirs"


def test_a_crystal_with_no_flag_still_shows_its_box(bench):
    """Absent means SHOWN, so every file imported before this draws as it
    always did."""
    from molom.ui.viewport import cell_shown
    _win, crystals, _mol = bench
    assert "show_cell" not in (crystals[0].structure.metadata or {})
    assert cell_shown(crystals[0])


def test_switching_view_drops_a_stale_packed_bond_list(bench):
    """A PRE-EXISTING crash, found while testing the above: `packed_bonds` is
    keyed by DRAWN atom index, an asymmetric unit produces none, and the old
    FULL CELL list was left in metadata for `_perceive_fresh` to apply to two
    atoms - an IndexError. It only bit a crystal that had actually been
    packed, which is why four of Christian's five fluorides switched happily
    and the fifth threw."""
    win, crystals, _mol = bench
    obj = crystals[0]
    win.viewport.set_selection([])
    win.active_id = obj.id
    obj.structure.metadata["packed_bonds"] = [[0, 26, 1]]   # a full-cell list
    obj.structure.metadata["packed"] = True
    win.on_crystal_view("asym")            # must not raise
    assert "packed_bonds" not in obj.structure.metadata
