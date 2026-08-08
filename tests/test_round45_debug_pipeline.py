"""Round 45: the debug page — the CIF pipeline run one stage at a time.

The contract under test is the one that makes the page trustworthy: a stage is
a PURE FUNCTION of (text, stage index). Clicking around must never leave state
behind, or the picture stops being evidence.
"""
import os

import numpy as np
import pytest

from molom.core import pipeline
from molom.addons._pipeline_host import (
    pipeline_object as _pipeline_object)
from tests.test_round18_cif import NACL_CIF

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    from molom.ui.app import MainWindow
    w = MainWindow()
    w.load_default_scene()
    w.show()
    return w


def test_every_stage_runs_and_is_traced():
    for index in range(len(pipeline.STAGES)):
        result = pipeline.run(NACL_CIF, index)
        assert not result.error
        assert len(result.trace) == index + 1
        assert result.trace[-1].key == pipeline.STAGES[index].key


def test_the_first_stage_is_the_cell_with_no_atoms():
    """The box on its own — what the file says before anything is drawn."""
    result = pipeline.run(NACL_CIF, 0)
    assert result.cell is not None
    assert len(result.symbols) == 0
    assert result.coords.shape == (0, 3)
    assert not result.bonds
    assert "a=" in result.trace[0].note


def test_the_second_stage_is_exactly_what_the_file_lists():
    """No symmetry, no bonds: the raw _atom_site_ rows."""
    from molom.core import cif
    data = cif.parse_cif(NACL_CIF)
    result = pipeline.run(NACL_CIF, 1)
    assert result.symbols == list(data.symbols)
    assert len(result.symbols) == len(data.frac)
    assert not result.bonds
    assert result.coords == pytest.approx(data.frac @ data.cell.matrix())


def test_symmetry_is_what_multiplies_the_atoms():
    sites = pipeline.run(NACL_CIF, 1)
    expanded = pipeline.run(NACL_CIF, pipeline.stage_index("dedupe"))
    assert len(expanded.symbols) > len(sites.symbols)


# ------------------------------------- the operators / wrap / dedupe split
def test_operators_produce_exactly_sites_times_operators():
    """No wrapping and no merging: the raw arithmetic, one atom per (site,
    operator) pair however many of them coincide."""
    from molom.core import cif
    data = cif.parse_cif(NACL_CIF)
    result = pipeline.run(NACL_CIF, pipeline.stage_index("operators"))
    assert len(result.symbols) == data.n_sites * len(data.symops)


def test_the_operators_alone_do_not_put_anything_in_the_box():
    """The wrap is what does that, and telling them apart is the whole point
    of the split (Christian, on SodiumNicotinate.cif: 24 of 25 sites start
    outside)."""
    from molom.core import cif
    data = cif.parse_cif(NACL_CIF)
    ops = pipeline.run(NACL_CIF, pipeline.stage_index("operators"))
    raw = data.cell.to_fractional(ops.coords)
    wrapped = pipeline.run(NACL_CIF, pipeline.stage_index("wrap"))
    inside = data.cell.to_fractional(wrapped.coords)
    assert np.all(inside > -1e-9) and np.all(inside < 1.0 + 1e-9)
    # Same atoms, moved by WHOLE lattice vectors and nothing else. Compared
    # this way rather than against `raw - floor(raw)` because the fractional
    # coordinates here are recovered from Cartesian through a matrix inverse,
    # so a coordinate that was exactly 1.0 comes back a hair under it and
    # floor() then disagrees by a whole cell.
    assert len(ops.symbols) == len(wrapped.symbols)
    shift = inside - raw
    assert np.allclose(shift, np.round(shift), atol=1e-6)


def test_wrapping_creates_and_destroys_nothing():
    a = pipeline.run(NACL_CIF, pipeline.stage_index("operators"))
    b = pipeline.run(NACL_CIF, pipeline.stage_index("wrap"))
    assert a.symbols == b.symbols


def test_dedupe_is_expands_own_answer():
    """Operators and wrap are this module's own arithmetic; the stage below
    them must land exactly on what `cif.expand` really produces, or the page
    would be describing a pipeline the app does not run."""
    from molom.core import cif
    data = cif.parse_cif(NACL_CIF)
    reference, ref_coords = cif.expand(
        data, whole_molecules=False, boundary=False,
        disorder=cif.POLICY_ALL)
    result = pipeline.run(NACL_CIF, pipeline.stage_index("dedupe"))
    assert result.symbols == list(reference)
    assert result.coords == pytest.approx(ref_coords)


def test_dedupe_only_ever_removes():
    wrapped = pipeline.run(NACL_CIF, pipeline.stage_index("wrap"))
    deduped = pipeline.run(NACL_CIF, pipeline.stage_index("dedupe"))
    assert len(deduped.symbols) <= len(wrapped.symbols)
    note = deduped.trace[-1].note
    assert "merged" in note
    assert "general position" in note


def test_no_bonds_before_the_bond_stage():
    """Every stage below `bonds` must draw none — that is the whole point of
    being able to look at them separately."""
    for index in range(pipeline.stage_index("bonds")):
        assert not pipeline.run(NACL_CIF, index).bonds
    assert pipeline.run(NACL_CIF, pipeline.stage_index("bonds")).bonds


def test_a_stage_is_a_pure_function_of_the_text():
    """Running the same stage twice gives the same picture, and running a
    LATER stage first cannot change it — the page rebuilds from scratch."""
    index = pipeline.stage_index("boundary")
    first = pipeline.run(NACL_CIF, index)
    pipeline.run(NACL_CIF, len(pipeline.STAGES) - 1)      # the whole thing
    second = pipeline.run(NACL_CIF, index)
    assert first.symbols == second.symbols
    assert first.coords == pytest.approx(second.coords)
    assert first.bonds == second.bonds


def test_going_back_a_stage_drops_the_later_work():
    late = pipeline.run(NACL_CIF, len(pipeline.STAGES) - 1)
    early = pipeline.run(NACL_CIF, 1)
    assert len(early.symbols) < len(late.symbols)
    assert not early.bonds


def test_the_trace_reports_what_each_stage_did():
    result = pipeline.run(NACL_CIF, len(pipeline.STAGES) - 1)
    labels = [info.label for info in result.trace]
    assert labels == [s.label for s in pipeline.STAGES]
    boundary = [i for i in result.trace if i.key == "boundary"][0]
    assert "CONTENT" in boundary.note        # says where the copies start


def test_the_last_stage_matches_an_ordinary_import():
    """The page must describe the pipeline the app actually runs, or it is
    worse than useless for debugging it."""
    from molom.core import bonding, cif
    from molom.core.modifiers import BoundaryModifier
    from molom.core.structure import Structure

    data = cif.parse_cif(NACL_CIF)
    report = {}
    symbols, coords = cif.expand(data, report=report)
    content = int(report["n_content"])
    s = Structure(list(symbols), coords)
    s.metadata["cell"] = data.cell.to_dict()
    bonding.perceive_structure_bonds(s)
    s.bonds = cif.display_bonds(s.symbols, s.coords, data.cell, content,
                                existing=s.bonds)
    mod = BoundaryModifier(cell=data.cell.to_dict(), shells=1,
                           content=content)
    app_symbols, _xyz, app_bonds = mod.evaluate(s.symbols, s.coords, s.bonds)

    final = pipeline.run(NACL_CIF, len(pipeline.STAGES) - 1)
    assert len(final.symbols) == len(app_symbols)
    assert len(final.bonds) == len(app_bonds)


def test_rubbish_text_is_reported_not_raised():
    result = pipeline.run("this is not a CIF at all", 3)
    assert result.error
    assert not result.symbols
    assert result.cell is None


def test_an_empty_string_is_survivable():
    result = pipeline.run("", 0)
    assert result.error
    assert not result.symbols


# ------------------------------------------------------------------ the page
def test_the_page_offers_a_button_per_stage(qapp):
    from molom.ui.debug_page import DebugPage
    page = DebugPage()
    assert len(page.stage_buttons) == len(pipeline.STAGES)
    # Disabled until there is something to run: a live-looking control that
    # does nothing is the round-43 complaint.
    assert not any(b.isEnabled() for b in page.stage_buttons)
    page.set_text(NACL_CIF, name="nacl.cif")
    assert all(b.isEnabled() for b in page.stage_buttons)


def test_the_page_emits_the_stage_and_the_text(qapp):
    from molom.ui.debug_page import DebugPage
    page = DebugPage()
    page.set_text(NACL_CIF, name="nacl.cif")
    seen = []
    page.stage_requested.connect(lambda i, t: seen.append((i, t)))
    page.stage_buttons[1].click()
    assert seen and seen[0][0] == 1
    assert seen[0][1] == NACL_CIF


def test_the_window_runs_a_stage_and_keeps_the_camera(win):
    """Only the CIF text persists — and the camera, so two stages can be
    compared without the view jumping between them.

    The page is an ADD-ON now, so it has to be enabled first; that it can be
    driven exactly as before afterwards is half the point of this test."""
    ok, message = win.addons.enable("debug_pipeline", win)
    assert ok, message
    win.debug_page.set_text(NACL_CIF, name="nacl.cif")
    win._pipeline_needs_fit = True
    win.debug_page.run_stage(0)
    obj = _pipeline_object(win)
    assert obj is not None
    assert obj.structure.n_atoms == 0            # the cell alone
    assert obj.structure.metadata.get("cell")
    distance = win.viewport.camera.distance
    assert distance > 1.0                        # framed the BOX, not nothing

    win.debug_page.run_stage(1)
    assert _pipeline_object(win).structure.n_atoms == 2
    assert win.viewport.camera.distance == pytest.approx(distance)

    # and exactly one debug object, however many times it is run
    win.debug_page.run_stage(5)
    names = [o.name for o in win.scene.objects if "Debug" in o.name]
    assert len(names) == 1
