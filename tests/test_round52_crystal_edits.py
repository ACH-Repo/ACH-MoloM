"""Round 52: an edited full cell becomes P1, and a shared site can be stated.

Christian's batch:

* adding atoms in the full cell then switching views "breaks everything" —
  measured on MOF-5: 618 atoms came back as 13;
* "automatically convert a crystal with any edit in full mode to triclinic.
  P1 or P-1?" — P1, and here is the reason in a test;
* "the automatic bond length adjustment when changing atom types in crystal
  mode should not apply";
* the origin handle should belong to the SELECT tool, not to the draw tool;
* "can we not just add an F3 option ... in which any occupancies for a shared
  site can be specified at leisure?"
"""

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from molom.core import cif, edits, occupancy as occ_mod  # noqa: E402
from molom.ui.app import MainWindow  # noqa: E402
from molom.ui.viewport import MODE_EDIT, cell_corners_world  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OXIDE = os.path.join(DATA, "cod_1547149_solid_solution.cif")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


@pytest.fixture
def win():
    QApplication.instance() or QApplication([])
    return MainWindow()


def _edit_mode(window, obj):
    window.viewport.set_mode(MODE_EDIT, obj.id)


# ------------------------------------------------------- an edit means P1
def test_editing_the_full_cell_makes_it_p1(win):
    """**P1, not P-1.** P-1 asserts an inversion centre through the origin,
    and an arbitrary edit preserves no such thing — writing it would make
    every downstream expansion invent a second half of the structure that is
    not there. P1 is the one group true of every arrangement of atoms, so it
    can never be wrong, and it makes the rebuild an identity."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    assert len(obj.structure.metadata["symops"]) == 4
    _edit_mode(win, obj)
    win.viewport.set_selection([(obj.id, 0)])
    win.viewport.apply_element("Ru")
    meta = win.scene.get(obj.id).structure.metadata
    assert meta["spacegroup"] == "P 1"
    assert meta["symops"] == ["x,y,z"]
    assert meta["it_number"] == 1


def test_an_edited_cell_stops_being_regenerated(win):
    """P1 alone is not enough. The drawn atoms are not the canonical cell
    content — `packing.pack` unwraps molecules to keep them whole, so 34 of
    ferrocene's 42 content atoms sit outside [0,1) — and re-packing atoms the
    packing has already relocated does not give the picture back: 210 drawn
    atoms came out as 168, four complete molecules where there were five
    (round 45d's trap, from the other side). So an edited cell is FROZEN: the
    atoms in front of you are the structure, and the contents radio stops
    regenerating them."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    _edit_mode(win, obj)
    win.viewport.set_selection([(obj.id, 0)])
    win.viewport.apply_element("Ru")
    drawn = win.scene.get(obj.id).structure.n_atoms
    assert win.scene.get(obj.id).structure.metadata["cell_frozen"] is True
    page = win.crystal_page
    for radio in (page.asym_radio, page.cell_radio, page.asym_radio,
                  page.cell_radio):
        radio.setChecked(True)
        after = win.scene.get(obj.id).structure
        assert after.n_atoms == drawn
        assert "Ru" in after.symbols


def test_a_frozen_cell_refuses_to_be_packed(win):
    """A supercell has to REGENERATE, and there would then be no way back to
    the single cell — the frozen atoms are the only copy of it. Refused
    rather than offered and then lost."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    _edit_mode(win, obj)
    win.viewport.set_selection([(obj.id, 0)])
    win.viewport.apply_element("Ru")
    drawn = win.scene.get(obj.id).structure.n_atoms
    win.crystal_page.pack_radio.setChecked(True)
    assert win.scene.get(obj.id).structure.n_atoms == drawn
    # ...and the controls say so rather than sitting there live and refusing
    assert not win.crystal_page.pack_radio.isEnabled()
    assert "edited" in win.crystal_page.pack_radio.toolTip()


def test_adding_atoms_dissolves_the_packed_split(win):
    """Added atoms land AFTER the boundary copies, so "the first N are the
    content" stops meaning anything — which is why the two carbons never
    reached the asymmetric unit and the next view switch drew 13 atoms."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    before = obj.structure.n_atoms
    assert obj.structure.metadata["cell_content"] < before   # packed
    _edit_mode(win, obj)
    win.begin_model_edit()
    edits.add_atom(obj.structure, "C", np.array([1.0, 1.0, 1.0]))
    edits.add_atom(obj.structure, "C", np.array([2.5, 1.0, 1.0]))
    win.viewport.edit_committed.emit()
    meta = win.scene.get(obj.id).structure.metadata
    assert meta["cell_content"] == before + 2
    assert meta["packed"] is False
    assert len(meta["asym_symbols"]) == before + 2


def test_the_added_atoms_survive_every_view_switch(win):
    """The measured failure, on the vendored file: 618 -> 13."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    _edit_mode(win, obj)
    win.begin_model_edit()
    edits.add_atom(obj.structure, "Xe", np.array([1.0, 1.0, 1.0]))
    win.viewport.edit_committed.emit()
    n = win.scene.get(obj.id).structure.n_atoms
    page = win.crystal_page
    for radio in (page.asym_radio, page.cell_radio):
        radio.setChecked(True)
        after = win.scene.get(obj.id).structure
        assert after.n_atoms == n
        assert "Xe" in after.symbols


def test_a_plain_element_change_keeps_the_content_split(win):
    """The count did NOT change, so the packed split still means something —
    and `cell_content != n_atoms` proves nothing about that, since they
    differ by design on every packed crystal."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    content = obj.structure.metadata["cell_content"]
    drawn = obj.structure.n_atoms
    assert content != drawn
    _edit_mode(win, obj)
    win.viewport.set_selection([(obj.id, 0)])
    win.viewport.apply_element("Ru")
    meta = win.scene.get(obj.id).structure.metadata
    assert meta["cell_content"] == content
    assert win.scene.get(obj.id).structure.n_atoms == drawn


def test_editing_the_asymmetric_unit_is_untouched_by_all_this(win):
    """The other branch: the operators are an INPUT there and the edit is
    repeated by them. Demotion must never reach it."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    win.crystal_page.asym_radio.setChecked(True)
    o = win.scene.get(obj.id)
    group = o.structure.metadata["spacegroup"]
    _edit_mode(win, o)
    win.viewport.set_selection([(o.id, 0)])
    win.viewport.apply_element("Ta")
    assert win.scene.get(obj.id).structure.metadata["spacegroup"] == group


def test_the_explicit_rederivation_checks_it_can_rebuild_the_cell(win):
    """"spglib found a group" is not "this unit and these operators rebuild
    this cell". They came apart on MOF-5: R3m, 6 operators over 7 orbits, 42
    atoms where the cell holds 424. A group that cannot reconstruct the
    structure is refused rather than stored."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    meta = obj.structure.metadata
    frac = win._crystal_fractional(obj)
    from molom.ui.viewport import cell_of
    n = int(meta["cell_content"])
    assert win._reconstructs(obj, meta, frac, n)
    # a unit that is one atom short cannot rebuild the cell
    broken = dict(meta)
    broken["asym_symbols"] = list(meta["asym_symbols"])[:-1]
    broken["asym_frac"] = list(meta["asym_frac"])[:-1]
    assert not win._reconstructs(obj, broken, frac, n)


# ----------------------------------------- no silent geometry in a crystal
def test_changing_an_element_in_a_crystal_moves_nothing(win):
    """A site in a crystal is not a free atom: its position was refined
    against diffraction data and it usually sits ON a symmetry element.
    Stretching its bond to the new covalent length is what pushed a MOF-5
    hydrogen 0.44 A off its site."""
    win.open_path(FERROCENE)
    obj = win._active_obj()
    before = np.array(obj.structure.coords, dtype=float)
    _edit_mode(win, obj)
    index = [i for i, s in enumerate(obj.structure.symbols) if s == "H"][0]
    win.viewport.set_selection([(obj.id, index)])
    win.viewport.apply_element("F")
    after = np.array(win.scene.get(obj.id).structure.coords, dtype=float)
    assert after.shape == before.shape       # no hydrogens added or removed
    assert np.allclose(after, before, atol=1e-12)


def test_a_molecule_still_gets_its_geometry_adjusted(win):
    """The rule is about CRYSTALS. In a molecule, H -> Zn lengthening the
    bond it hangs off is the whole point of the draw tool."""
    from molom.core import build
    obj = win.scene.add(build.cubane(), name="cubane")
    win.active_id = obj.id
    before = np.array(obj.structure.coords, dtype=float)
    _edit_mode(win, obj)
    index = [i for i, s in enumerate(obj.structure.symbols) if s == "H"][0]
    win.viewport.set_selection([(obj.id, index)])
    win.viewport.apply_element("Zn")
    after = np.array(win.scene.get(obj.id).structure.coords, dtype=float)
    assert not np.allclose(after[index], before[index])


# ------------------------------------------------- the origin handle's tool
def test_the_origin_handle_belongs_to_the_select_tool(win):
    """With the draw tool armed every click is a drawing gesture, so a handle
    in the middle of the molecule is a trap: you reach to draw an atom and
    pick up the origin instead."""
    from molom.core import build
    obj = win.scene.add(build.cubane(), name="cubane")
    win.active_id = obj.id
    vp = win.viewport
    vp.set_mode(MODE_EDIT, obj.id)
    assert vp.select_tool_active
    vp.set_draw_tool(True)
    assert not vp.select_tool_active
    vp.set_draw_tool(False)
    assert vp.select_tool_active
    vp.set_measure_tool(True)
    assert not vp.select_tool_active     # the measure tool owns clicks too
    vp.set_measure_tool(False)
    vp.set_mode("object")
    assert not vp.select_tool_active     # ...and it is an EDIT-mode state


def test_arming_the_draw_tool_puts_the_origin_down(win):
    """Leaving it picked up would mean G and R silently moved the origin
    while the user thought they were drawing."""
    from molom.core import build
    obj = win.scene.add(build.cubane(), name="cubane")
    win.active_id = obj.id
    vp = win.viewport
    vp.set_mode(MODE_EDIT, obj.id)
    vp.set_origin_active(True)
    assert vp._origin_active
    vp.set_draw_tool(True)
    assert not vp._origin_active


def test_alt_o_disarms_whatever_is_holding_clicks(win):
    from molom.core import build
    obj = win.scene.add(build.cubane(), name="cubane")
    win.active_id = obj.id
    vp = win.viewport
    vp.set_mode(MODE_EDIT, obj.id)
    vp.set_draw_tool(True)
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    vp.snap_origin_to_selection()
    assert not vp.draw_tool_active
    assert vp._origin_active and vp.select_tool_active


# ------------------------------------------------------ shared-site editing
def test_the_orbit_is_the_whole_site_not_one_atom(win):
    """A cubic cell draws one site twenty-four times, and nobody would edit
    its composition twenty-four times over. `site_of` makes it a lookup."""
    win.open_path(OXIDE)
    s = win._active_obj().structure
    orbit = occ_mod.orbit_of(s.metadata, 0, s.n_atoms)
    assert len(orbit) > 1
    assert all(s.symbols[i] == s.symbols[0] for i in orbit)
    # with no mapping there is nothing to say the others are the same SITE
    assert occ_mod.orbit_of({}, 0, s.n_atoms) == [0]


def test_a_stated_composition_reaches_the_written_file(win, tmp_path):
    """The gap round 50 had to report as a limit: the co-located species are
    merged away at import before occupancy is consulted, so nothing in the
    coordinates implies the composition and no derivation can recover it.
    Stating it is the only honest answer."""
    win.open_path(OXIDE)
    obj = win._active_obj()
    s = obj.structure
    index = [i for i, x in enumerate(s.symbols) if x == "O"][0]
    orbit = occ_mod.orbit_of(s.metadata, index, s.n_atoms)
    occ_mod.set_composition(s.metadata, orbit, [("O", 0.8), ("N", 0.2)])
    s.metadata["site_occupancy_edited"] = True
    path = str(tmp_path / "stated.cif")
    win.export_visible(path)
    data = cif.parse_cif(open(path, encoding="utf-8").read())
    rows = list(zip(data.symbols, [round(o, 3) for o in data.occupancy]))
    assert ("O", 0.8) in rows and ("N", 0.2) in rows
    # ...and the file's OWN shared site is still there, all four species
    assert ("Nb", 0.5) in rows and ("Co", 0.1) in rows


def test_an_unedited_file_round_trips_its_own_shared_site(win, tmp_path):
    """The verbatim path must NOT expand anything: a file that has a shared
    site already lists each species as its own `_atom_site_` row, so the
    solid solution's unit is [Nb, Ti, Ni, Co, O] — five rows for four species
    on one position. Expanding again writes Ti, Ni and Co twice."""
    win.open_path(OXIDE)
    path = str(tmp_path / "verbatim.cif")
    win.export_visible(path)
    data = cif.parse_cif(open(path, encoding="utf-8").read())
    assert data.n_sites == 5
    assert sorted(data.symbols) == ["Co", "Nb", "Ni", "O", "Ti"]


def test_a_full_single_species_clears_the_entry():
    """An atom put back to ordinary should stop being a pie sphere, and a
    table full of `[("C", 1.0)]` is noise every consumer then has to filter."""
    meta = {"site_occupancy": {"0": [("Nb", 0.5), ("Ti", 0.5)]}}
    occ_mod.set_composition(meta, [0], [("Nb", 1.0)])
    assert "site_occupancy" not in meta


def test_the_total_is_described_not_normalised():
    """A site can be genuinely part-vacant, and silently rescaling to one
    would erase that."""
    parts = occ_mod.normalise([("Nb", 0.5), ("Ti", 0.25)])
    assert occ_mod.total(parts) == pytest.approx(0.75)
    assert "vacant" in occ_mod.total_note(parts)
    assert "more than one atom" in occ_mod.total_note(
        [("Nb", 0.7), ("Ti", 0.7)])
    assert "fully occupied" in occ_mod.total_note([("Nb", 1.0)])


def test_unreadable_symbols_are_dropped_rather_than_stored():
    parts = occ_mod.normalise([("Nb", 0.5), ("zzz", 0.3), ("Ti", 0.0)])
    assert parts == [("Nb", 0.5)]


def test_one_species_at_a_partial_occupancy_is_not_a_shared_site():
    """That is an ordinary partial site and rides in the occupancy column;
    only several SPECIES need a pie sphere and several rows."""
    assert not occ_mod.is_shared([("Nb", 0.5)])
    assert occ_mod.is_shared([("Nb", 0.5), ("Ti", 0.5)])


def test_the_dialog_refuses_more_than_one_atom_on_a_position():
    QApplication.instance() or QApplication([])
    from molom.ui.dialogs import SiteOccupancyDialog
    dlg = SiteOccupancyDialog(None, [("Nb", 0.5), ("Ti", 0.5)], "M", 8)
    assert dlg.parts() == [("Nb", 0.5), ("Ti", 0.5)]
    assert dlg._ok.isEnabled()
    dlg._rows[0][1].setValue(0.9)
    assert not dlg._ok.isEnabled()          # 1.4 on one position
    dlg._rows[0][1].setValue(0.4)
    assert dlg._ok.isEnabled()


def test_the_operator_is_registered_and_clash_free(win):
    op = win.ops.get("crystal_site_occupancy")
    assert op is not None
    assert "occupancy" in op.aliases or "occupancy" in op.label.lower()
    assert not win.ops.duplicate_keys()
