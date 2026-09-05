"""Round 102: three standing docket items - N1, N2 and N3.

N1 is the one with teeth. The other two are a projection that should not have
changed and a column that was never there.
"""
import os
import shutil
import tempfile

import numpy as np
import pytest

from molom.core import camera as camera_mod
from molom.core import molsearch

HERE = os.path.dirname(__file__)
CIF = os.path.join(HERE, "data", "cod_1547149_solid_solution.cif")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    return MainWindow()


# --------------------------------------------------- N1: a temp file is not
#                                                      the session's document
def _scratch_copy():
    """What the crystal search does: a real name inside a temp DIRECTORY it
    deletes immediately afterwards (round 84)."""
    folder = tempfile.mkdtemp(prefix="molom_cif_")
    path = os.path.join(folder, "Benzoic_acid.cif")
    shutil.copy(CIF, path)
    return folder, path


def test_a_temporary_import_does_not_claim_the_document(win):
    """Christian: a searched benzoic acid put up the round-trip banner. It
    had claimed `source_path` for a file inside a directory that was deleted
    a moment later - so Ctrl+S, which prefers writing back over opening the
    project dialog, would have tried to write THERE."""
    folder, path = _scratch_copy()
    before = win.scene.n_objects
    try:
        win.open_path(path, temporary=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert win.scene.n_objects > before          # it still imported
    assert win.source_path is None               # ...and claimed nothing


def test_a_temporary_import_does_not_join_the_recent_files(win):
    """Same reason, one menu along: a recent-files entry pointing into a
    deleted temp directory is a promise about a path that is already gone."""
    before = list(win._recent())
    folder, path = _scratch_copy()
    try:
        win.open_path(path, temporary=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert list(win._recent()) == before


def test_an_ORDINARY_import_joins_recent_but_claims_NOTHING(win):
    """Christian's design, and it corrects an inference of mine: opening a
    file is not a round trip. `molom some.xyz` imports it, Ctrl+S saves a
    `.molom` project, and writing the geometry back out is an EXPORT."""
    win.open_path(CIF)
    assert win.source_path is None
    assert any(os.path.abspath(p) == os.path.abspath(CIF)
               for p in win._recent())


def test_the_round_trip_has_to_be_ASKED_for(win):
    """...and when it is asked for, it works exactly as before - that is the
    whole reason `source_path` exists (round 92)."""
    win.open_path(CIF, roundtrip=True)
    assert win.source_path is not None
    assert os.path.basename(win.source_path) == os.path.basename(CIF)


def test_a_launcher_asks_through_the_ENVIRONMENT(tmp_path):
    """A flag on the command line would be passed to whatever program sits in
    OWB's editor slot, and whether Avogadro or molden tolerates an unknown
    argument is not consistent and not something OWB can know. A program that
    does not read an environment variable cannot be affected by one.
    """
    from molom import __main__ as entry
    path = str(tmp_path / "mol.xyz")
    open(path, "w").close()
    env = {entry.ROUNDTRIP_ENV: path}
    assert entry.roundtrip_requested(path, False, env)
    assert entry.roundtrip_requested(path, True, {})          # the flag
    assert not entry.roundtrip_requested(path, False, {})     # neither
    # ...and it names the FILE, so a variable left in a shell cannot arm the
    # write-back for something opened later.
    other = str(tmp_path / "other.xyz")
    open(other, "w").close()
    assert not entry.roundtrip_requested(other, False, env)


def test_the_crystal_search_import_is_marked_temporary():
    """A gesture test would need the network; this pins the call site, which
    is the thing that was wrong. Round 59's lesson is that a mechanism with
    no test on the route to it is a mechanism nobody reaches."""
    import inspect
    from molom.ui import app as app_mod
    source = inspect.getsource(app_mod.MainWindow.import_cif_hits) \
        if hasattr(app_mod.MainWindow, "import_cif_hits") else ""
    if not source:                      # find it by its temp-dir prefix
        source = inspect.getsource(app_mod)
        start = source.index('mkdtemp(prefix="molom_cif_")')
        source = source[start:start + 900]
    assert "temporary=True" in source


# ------------------------------- N2: a stepped rotation keeps the projection
def test_a_stepped_rotation_keeps_an_axis_view_orthographic():
    """A crystal's axis views are orthographic on purpose (the VESTA ribbon),
    so walking round one by a typed number of degrees must not drop into
    perspective on the first click."""
    cam = camera_mod.Camera()
    cam.orthographic = True
    cam.auto_ortho = True
    cam.rotate(40.0, 0.0, keep_axis_view=True)
    assert cam.orthographic
    assert cam.auto_ortho          # still an axis view, still poppable


def test_a_free_drag_still_pops_back_to_perspective():
    """Blender's rule, and round 3's, unchanged: a DRAG stops being an axis
    view the moment the mouse moves."""
    cam = camera_mod.Camera()
    cam.orthographic = True
    cam.auto_ortho = True
    cam.rotate(40.0, 0.0)
    assert not cam.orthographic
    assert not cam.auto_ortho


def test_the_ribbon_handler_asks_to_keep_it(win):
    win.open_path(CIF)
    cam = win.viewport.camera
    cam.orthographic = True
    cam.auto_ortho = True
    win._on_ribbon_rotate(15.0, 0.0)
    assert cam.orthographic, "the ribbon's stepped rotation dropped ortho"


def test_the_rotation_itself_still_happens(win):
    """The projection is held; the camera is not."""
    win.open_path(CIF)
    cam = win.viewport.camera
    cam.orthographic = True
    cam.auto_ortho = True
    before = cam.rotation.copy()
    win._on_ribbon_rotate(25.0, 0.0)
    assert not (abs(cam.rotation - before) < 1e-9).all()


# --------------------------------------------- N3: the CAS number as a column
def test_a_cas_number_is_checked_by_its_CHECK_DIGIT():
    """The shape alone is not enough - a synonym list is full of hyphenated
    numbers. Measured on PubChem: benzoic acid has two CAS-shaped synonyms
    and aspirin three, and the digit accepts exactly the right ones."""
    assert molsearch.valid_cas("65-85-0")       # benzoic acid
    assert molsearch.valid_cas("50-78-2")       # aspirin
    assert molsearch.valid_cas("95-47-6")       # o-xylene
    assert not molsearch.valid_cas("65-85-1")   # right shape, wrong digit
    assert not molsearch.valid_cas("1,2-4-5")
    assert not molsearch.valid_cas("12-34-5")
    assert not molsearch.valid_cas("")
    assert not molsearch.valid_cas(None)


def test_the_first_VALID_synonym_wins():
    """PubChem ranks its synonyms, so the order is real information - the
    compound's own registry number comes before those of its hydrates."""
    assert molsearch.cas_from_synonyms(
        ["benzoic acid", "not-a-cas", "65-85-0", "532-32-1"]) == "65-85-0"
    assert molsearch.cas_from_synonyms(["nothing", "here"]) == ""
    assert molsearch.cas_from_synonyms([]) == ""


def test_a_synonyms_failure_costs_the_CAS_and_not_the_ROW(monkeypatch):
    """Round 37's rule: a dead tier costs a tier, never the answer. A CAS is
    a nicety and a row is the result."""
    import urllib.error
    monkeypatch.setattr(molsearch, "_pubchem_json",
                        lambda *a, **k: (_ for _ in ()).throw(
                            urllib.error.URLError("down")))
    assert molsearch._synonyms_for([243, 2244], fetch=lambda *a, **k: b"") == {}


def test_the_cas_rides_a_favourite():
    """A favourite stores the candidate, so it has to carry the column the
    list is showing - otherwise a starred row loses it on reopening."""
    cand = molsearch.Candidate(source="pubchem", ref="243", name="Benzoic acid",
                               smiles="OC(=O)c1ccccc1", formula="C7H6O2")
    cand.cas = "65-85-0"
    back = molsearch.candidate_from_dict(cand.to_dict())
    assert back is not None
    assert back.cas == "65-85-0"


def test_a_candidate_without_a_cas_round_trips_too():
    cand = molsearch.Candidate(source="opsin", name="something")
    assert molsearch.candidate_from_dict(cand.to_dict()).cas == ""


def test_the_molecule_table_shows_the_cas():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui import dialogs
    table = dialogs._MolResultTable(None, favourites={})
    assert "CAS" in table.COLUMNS
    cand = molsearch.Candidate(source="pubchem", ref="7237", name="O-Xylene",
                               formula="C8H10", weight=106.17)
    cand.cas = "95-47-6"
    assert "95-47-6" in table.cells_for(cand)


def test_BOTH_search_tables_obey_the_same_column_rules():
    """Christian's standing rule: a control that exists in both search
    windows should behave the same in both. They share `ResultTable`, so
    this pins that neither subclass quietly opts out."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QHeaderView
    QApplication.instance() or QApplication([])
    from molom.ui import dialogs
    for cls in (dialogs._CifResultTable, dialogs._MolResultTable):
        table = cls(None, favourites={})
        table.resize(800, 400)
        table.show()                 # a hidden widget gets no resize event
        QApplication.processEvents()
        head = table.horizontalHeader()
        # INTERACTIVE, not Stretch: Qt refuses to let a Stretch section be
        # dragged, which is what made the name column's border dead.
        assert head.sectionResizeMode(table.STRETCH_COLUMN) \
            == QHeaderView.Interactive
        assert table.wordWrap()
        # ...and it still takes exactly the room the others leave, which is
        # what Stretch was there for. The width is the VIEWPORT's, never the
        # longest entry's
        assert sum(table.columnWidth(c)
                   for c in range(table.columnCount())) \
            == table.viewport().width()


# ------------------------------- Christian's test pass on the batch itself
def test_a_stepped_rotation_does_not_RE_LEVEL_either():
    """`keep_projection` held the projection and left the LEVEL - and an axis
    view's up vector is a cell axis, so `level_horizon` flipped b and c on
    the first click. Measured as a 180 degree camera movement for a
    ZERO-degree step, which is what Christian saw as the axes jumping."""
    cam = camera_mod.Camera()
    cam.orthographic = True
    cam.auto_ortho = True
    cam.auto_level = True
    before = cam.rotation.copy()
    cam.rotate(0.0, 0.0, keep_axis_view=True)
    assert (abs(cam.rotation - before) < 1e-12).all()
    assert cam.auto_level and cam.orthographic


def test_a_zero_degree_ribbon_step_moves_nothing(win):
    win.open_path(CIF)
    win._on_ribbon_axis("a")
    cam = win.viewport.camera
    before = cam.rotation.copy()
    win._on_ribbon_rotate(0.0, 0.0)
    assert (abs(cam.rotation - before) < 1e-12).all()


def test_a_free_drag_still_re_levels():
    """The other half of the same pose, and it must still unwind for a DRAG:
    the turntable cannot express a cell axis as up."""
    cam = camera_mod.Camera()
    cam.auto_level = True
    cam.rotate(30.0, 0.0)
    assert not cam.auto_level


def test_the_finished_list_reconciles_with_what_is_on_screen():
    """A row whose key matched nothing incrementally would stay half-filled
    for the session and come good only on reopening - Christian's blank
    m-xylene row. The finished list is merged in rather than discarded."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui import dialogs
    dlg = dialogs.MoleculeSearchDialog(None)
    bare = molsearch.Candidate(source="opsin", ref="q", smiles="Cc1ccccc1C")
    dlg._landed("opsin", [bare])
    assert dlg.table.rowCount() == 1
    full = molsearch.Candidate(source="opsin", ref="q", name="O-Xylene",
                               smiles="Cc1ccccc1C", formula="C8H10")
    full.cas = "95-47-6"

    class _Result(object):
        candidates = [full]
        query = "xylene"
        ambiguous = ""
        trouble = []

        def summary(self):
            return ""

    dlg._finished(_Result())
    assert dlg.table.rowCount() == 1              # nothing was duplicated
    assert dlg.table.results[0].name == "O-Xylene"
    assert dlg.table.results[0].cas == "95-47-6"


def test_a_favourite_starred_before_the_column_existed_gets_filled_in():
    """A favourite is a snapshot, so one saved before the CAS was a column
    has none. Folding in what the live search already knows costs nothing;
    re-fetching every star would be a request apiece."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui import dialogs
    old = molsearch.Candidate(source="pubchem", ref="7237", name="O-Xylene",
                              smiles="Cc1ccccc1C",
                              inchikey="CTQNGGLPUBDAKN-UHFFFAOYSA-N")
    assert old.cas == ""
    dlg = dialogs.MoleculeSearchDialog(None,
                                       favourites={old.key(): old})
    fresh = molsearch.Candidate(source="pubchem", ref="7237", name="O-Xylene",
                                smiles="Cc1ccccc1C", formula="C8H10",
                                inchikey="CTQNGGLPUBDAKN-UHFFFAOYSA-N")
    fresh.cas = "95-47-6"
    dlg.table.set_results([fresh])
    dlg._absorb_favourite_updates()
    assert old.cas == "95-47-6"
    assert old.formula == "C8H10"


def test_the_name_column_can_be_dragged_and_then_stays_put():
    """Christian: "the border between name and Formula cannot even show the
    adjust icon". It was Stretch, which Qt will not let anybody drag."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui import dialogs
    table = dialogs._MolResultTable(None, favourites={})
    table.resize(820, 400)
    table.show()                    # a hidden widget gets no resize event
    QApplication.processEvents()
    head = table.horizontalHeader()
    column = table.STRETCH_COLUMN
    before = table.columnWidth(column)
    table.resize(1100, 400)
    QApplication.processEvents()
    assert table.columnWidth(column) > before, "it should grow with the window"
    # A real drag: the mouse is down on the header while the width changes.
    table._user_dragging = True
    head.resizeSection(column, 200)
    table._user_dragging = False
    assert table._stretch_pinned
    table.resize(1300, 400)
    QApplication.processEvents()
    assert table.columnWidth(column) == 200, "a width set by hand must stand"


# ------------------------ #4: an element change makes the site PURE (r102b)
SOLID = os.path.join(HERE, "data", "cod_1547149_solid_solution.cif")
FERROCENE_OR_SOLID = os.path.join(HERE, "data",
                                  "cod_2101932_ferrocene.cif")


def _asym(win, path):
    from molom.core import cif as cif_mod          # noqa: F401  (import cost)
    win.open_path(path)
    obj = [o for o in win.scene.objects
           if (o.structure.metadata or {}).get("cell")][-1]
    win.active_id = obj.id
    win.on_crystal_view("asym")
    return win.scene.get(obj.id)


def test_changing_the_element_of_a_shared_site_makes_it_PURE(win):
    """Christian: "change should make something purely that element, not just
    change the dominant one." Round 87 re-labelled the majority species and
    kept the rest, which leaves a composition nobody asked for and that
    cannot be read off the picture."""
    from molom.core import edits, occupancy as occ
    obj = _asym(win, SOLID)
    meta = obj.structure.metadata
    assert meta["asym_symbols"] == ["Nb", "Ti", "Ni", "Co", "O"]
    assert occ.composition_of(meta, 0), "atom 0 is the shared site"
    edits.set_element(obj.structure, [0], "I")
    win.sync_asymmetric_unit(obj)
    assert meta["asym_symbols"] == ["I", "O"]
    assert [round(float(v), 3) for v in meta["asym_occupancy"]] == [1.0, 1.0]
    assert meta["asym_rows"] == [[0], [1]]


def test_the_PIE_SPHERE_goes_with_it(win):
    """"the pie chart is still the underlying partial occupancies" - the
    wedges are drawn from `site_occupancy`, keyed by drawn atom, and a
    rebuild would fix it eventually. The picture in front of the user must
    not have to wait for one."""
    from molom.core import edits, occupancy as occ
    obj = _asym(win, SOLID)
    meta = obj.structure.metadata
    edits.set_element(obj.structure, [0], "I")
    win.sync_asymmetric_unit(obj)
    assert not occ.composition_of(meta, 0)


def test_the_full_cell_agrees_after_the_change(win):
    """A rebuild regenerates from the metadata, so the two views must not
    disagree about what the crystal is made of."""
    from collections import Counter
    from molom.core import edits, occupancy as occ
    obj = _asym(win, SOLID)
    edits.set_element(obj.structure, [0], "I")
    win.sync_asymmetric_unit(obj)
    win.on_crystal_view("cell")
    obj = win.scene.get(obj.id)
    counts = Counter(obj.structure.symbols)
    assert counts["I"] and not counts["Nb"] and not counts["Ti"]
    meta = obj.structure.metadata
    assert not any(occ.composition_of(meta, i)
                   for i in range(obj.structure.n_atoms))


def test_a_MIXTURE_is_still_stateable_and_is_a_different_operation(win):
    """Making an element pure is what the periodic table means. Saying a site
    is 80% one thing and 20% another is a separate gesture with its own
    dialog - `F3 > Crystal: set the occupancies of a shared site`."""
    from molom.core import occupancy as occ
    obj = _asym(win, SOLID)
    meta = obj.structure.metadata
    occ.set_composition(meta, [0], [("O", 0.8), ("N", 0.2)],
                        n_atoms=obj.structure.n_atoms)
    assert occ.describe(occ.composition_of(meta, 0)) == "O 0.80 / N 0.20"


def test_an_ordinary_single_row_site_is_untouched_by_the_change(win):
    """Round 43e's bug from the other side: a single-row atom is an ordinary
    site and its element change must reach the metadata exactly as before."""
    from molom.core import edits
    obj = _asym(win, SOLID)
    meta = obj.structure.metadata
    edits.set_element(obj.structure, [1], "S")      # the plain O site
    win.sync_asymmetric_unit(obj)
    assert meta["asym_symbols"] == ["Nb", "Ti", "Ni", "Co", "S"]
    assert [round(float(v), 2) for v in meta["asym_occupancy"]] \
        == [0.5, 0.25, 0.15, 0.1, 1.0]


# ------------------------------- the CCDC key hole (no CCDC in it) (r102b)
def test_a_search_tier_can_be_registered_and_removed():
    """The extension point a CSD provider would use. Core owns the registry
    and the signature; every line that knows what CCDC is belongs in an
    add-on, because `core/` has to stay installable, offline-testable and
    publishable and a licensed database is none of those."""
    from molom.core import cifsearch
    from molom.core.cifsearch import Hit

    def tier(query, formula="", limit=20, timeout=8.0):
        return [Hit(source="csd", ref="BENZAC01", name="benzoic acid",
                    formula="C7H6O2")]

    try:
        cifsearch.register_provider("csd", "CSD", tier)
        assert "csd" in cifsearch.extra_providers()
        result = cifsearch.search("benzoic acid", network=False)
        assert "csd" in result.asked
        assert any(h.source == "csd" for h in result.hits)
    finally:
        cifsearch.unregister_provider("csd")
    assert "csd" not in cifsearch.extra_providers()
    assert "csd" not in cifsearch.search("quartz", network=False).asked


def test_a_registered_tier_that_fails_costs_a_TIER_not_the_search():
    """Round 37's rule, which is the whole reason the tiers are concurrent:
    an unlicensed or unreachable database must not take the search down."""
    from molom.core import cifsearch

    def broken(query, **kw):
        raise RuntimeError("no licence")

    try:
        cifsearch.register_provider("csd", "CSD", broken)
        result = cifsearch.search("benzoic acid", network=False)
        assert any("csd" in t for t in result.trouble)
        assert result.hits is not None
    finally:
        cifsearch.unregister_provider("csd")


def test_registering_rubbish_is_refused():
    from molom.core import cifsearch
    with pytest.raises(ValueError):
        cifsearch.register_provider("", "nameless", lambda **kw: [])
    with pytest.raises(TypeError):
        cifsearch.register_provider("x", "not callable", "nope")
    cifsearch.unregister_provider("never-registered")     # must not raise


def test_core_does_not_import_ccdc_anywhere():
    """The key hole has no key in it, and a test says so rather than a
    comment. `ccdc` is not on PyPI, needs a licence, and can never be a
    dependency of this package."""
    import ast
    import glob
    for path in glob.glob(os.path.join(os.path.dirname(HERE),
                                       "molom", "core", "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.split(".")[0] == "ccdc", \
                    "%s imports ccdc" % os.path.basename(path)


# ------------------------------ M2: a frozen P1 cell can be recovered (r103)
def _demoted(win, path):
    """A crystal in the state round 91's bug left `MF.molom`'s CsF in: the
    atoms intact, the group thrown away, the cell frozen."""
    win.open_path(path)
    obj = [o for o in win.scene.objects
           if (o.structure.metadata or {}).get("cell")][-1]
    win.active_id = obj.id
    win.demote_to_p1(obj)
    assert obj.structure.metadata.get("cell_frozen")
    return obj


def test_a_demotion_leaves_the_ATOMS_alone(win):
    """Which is why it is recoverable at all: `demote_to_p1` replaces the
    asymmetric unit and the operators, not the coordinates."""
    win.open_path(SOLID)
    obj = [o for o in win.scene.objects
           if (o.structure.metadata or {}).get("cell")][-1]
    before = np.array(obj.structure.coords, copy=True)
    win.demote_to_p1(obj)
    assert np.allclose(obj.structure.coords, before)


def test_re_deriving_unfreezes_the_cell(win):
    """The freeze exists because after an arbitrary edit the stored unit and
    operators may not rebuild the cell - the MOF-5 failure where 616 atoms
    came back as 7. `reevaluate_symmetry` REFUSES any group that cannot
    reconstruct it, so a successful re-derivation is proof that the condition
    the freeze guards against no longer holds."""
    obj = _demoted(win, SOLID)
    meta = obj.structure.metadata
    found = win.reevaluate_symmetry(obj, announce=False)
    assert found, "the coordinates still have their symmetry"
    assert not meta.get("cell_frozen")
    assert len(meta["symops"]) > 1


def test_a_refused_re_derivation_leaves_the_freeze_in_place(win, monkeypatch):
    """"Nothing changed" must not un-grey anything: if the coordinates really
    only have P1, the cell is frozen for the reason it was frozen."""
    obj = _demoted(win, SOLID)
    meta = obj.structure.metadata
    monkeypatch.setattr(win, "reevaluate_symmetry",
                        lambda o, announce=True: None)
    from molom.ui import app as app_mod
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win.viewport.set_selection([(obj.id, 0)])
    win._sync_crystal_page()
    win.crystal_page.rederive_btn.click()
    assert meta.get("cell_frozen"), "a refusal must not unfreeze the cell"


def test_the_page_offers_the_way_out_ONLY_when_it_is_needed(win):
    """A greyed control that cannot say what would un-grey it is the thing
    this project keeps finding. On an ordinary crystal the button would be
    offering to change something that is already right."""
    win.open_path(SOLID)
    obj = [o for o in win.scene.objects
           if (o.structure.metadata or {}).get("cell")][-1]
    win.active_id = obj.id
    win.viewport.set_selection([(obj.id, 0)])
    win._sync_crystal_page()
    page = win.crystal_page
    # `isHidden`, not `isVisible`: the latter folds in every ancestor, and
    # this page lives on a QStackedWidget inside a dock that is usually shut
    # (round 34).
    assert page.rederive_btn.isHidden()
    assert page.frozen_note.isHidden()
    win.demote_to_p1(obj)
    win._sync_crystal_page()
    assert not page.rederive_btn.isHidden()
    assert not page.frozen_note.isHidden()
    assert not page.cell_radio.isEnabled()


def test_pressing_it_repairs_the_crystal_and_re_enables_the_switch(
        win, monkeypatch):
    from molom.ui import app as app_mod
    from PySide6.QtWidgets import QMessageBox
    obj = _demoted(win, SOLID)
    meta = obj.structure.metadata
    n_atoms = obj.structure.n_atoms
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win.viewport.set_selection([(obj.id, 0)])
    win._sync_crystal_page()
    win.crystal_page.rederive_btn.click()
    assert not meta.get("cell_frozen")
    assert len(meta["symops"]) > 1
    assert obj.structure.n_atoms == n_atoms, "the atoms are not touched"
    assert win.crystal_page.cell_radio.isEnabled()
    assert win.crystal_page.rederive_btn.isHidden()


def test_cancelling_changes_nothing(win, monkeypatch):
    """It says what it is about to do FIRST - Christian's "if the user is
    explicitly informed they're about to change something"."""
    from molom.ui import app as app_mod
    from PySide6.QtWidgets import QMessageBox
    obj = _demoted(win, SOLID)
    meta = obj.structure.metadata
    before = (meta.get("spacegroup"), len(meta.get("symops") or []),
              meta.get("cell_frozen"))
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Cancel))
    win.viewport.set_selection([(obj.id, 0)])
    win._sync_crystal_page()
    win.crystal_page.rederive_btn.click()
    assert (meta.get("spacegroup"), len(meta.get("symops") or []),
            meta.get("cell_frozen")) == before


def test_the_contents_switch_round_trips_after_the_repair(win, monkeypatch):
    """The point of un-greying it: asym -> cell has to work again, and give
    back the cell it started from."""
    from molom.ui import app as app_mod
    from PySide6.QtWidgets import QMessageBox
    obj = _demoted(win, SOLID)
    n_atoms = obj.structure.n_atoms
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win.viewport.set_selection([(obj.id, 0)])
    win._sync_crystal_page()
    win.crystal_page.rederive_btn.click()
    win.on_crystal_view("asym")
    assert win.scene.get(obj.id).structure.n_atoms < n_atoms
    win.on_crystal_view("cell")
    assert win.scene.get(obj.id).structure.n_atoms == n_atoms


# ----------------------------------- the axis-view flip, and Del (round 103)
def test_the_axis_flip_only_applies_to_a_press_in_DIRECT_succession(win):
    """Christian: "If I press direction once, rotate and then press it again,
    the rotation should start from positive again. Start from negative only
    if pressed twice directly in succession." The memory used to survive
    anything at all."""
    from molom.core.camera import quat_to_mat3
    win.open_path(FERROCENE_OR_SOLID)
    cam = win.viewport.camera

    def apart(a, b):
        return np.degrees(np.arccos(
            np.clip((np.trace(b @ a.T) - 1) / 2.0, -1.0, 1.0)))

    win._on_ribbon_axis("c")
    first = quat_to_mat3(cam.rotation).copy()
    win._on_ribbon_axis("c")
    assert apart(first, quat_to_mat3(cam.rotation)) > 170, \
        "twice in a row IS the other side"

    win._last_axis_view = None
    win._on_ribbon_axis("c")
    first = quat_to_mat3(cam.rotation).copy()
    cam.rotate(40.0, 0.0)                      # the user orbits away
    win._on_ribbon_axis("c")
    assert apart(first, quat_to_mat3(cam.rotation)) < 1e-6, \
        "after rotating, the button is a FIRST press again"


def test_a_pan_or_zoom_does_NOT_reset_the_flip(win):
    """Deliberate: those leave you looking down the same axis, so pressing
    again still means "the other side". Only a rotation takes you off it."""
    from molom.core.camera import quat_to_mat3
    win.open_path(FERROCENE_OR_SOLID)
    cam = win.viewport.camera
    win._on_ribbon_axis("c")
    first = quat_to_mat3(cam.rotation).copy()
    win._on_ribbon_zoom(20.0)
    win._on_ribbon_axis("c")
    ang = np.degrees(np.arccos(np.clip(
        (np.trace(quat_to_mat3(cam.rotation) @ first.T) - 1) / 2.0, -1, 1)))
    assert ang > 170


def test_a_different_axis_button_resets_it_too(win):
    from molom.core.camera import quat_to_mat3
    win.open_path(FERROCENE_OR_SOLID)
    cam = win.viewport.camera
    win._on_ribbon_axis("a")
    first = quat_to_mat3(cam.rotation).copy()
    win._on_ribbon_axis("b")
    win._on_ribbon_axis("a")
    ang = np.degrees(np.arccos(np.clip(
        (np.trace(quat_to_mat3(cam.rotation) @ first.T) - 1) / 2.0, -1, 1)))
    assert ang < 1e-6


def test_DELETE_removes_an_empty_molecule_from_the_outliner(win):
    """Christian: "if there is a molecule entry with no atoms and the
    outliner entry is selected, does pressing Del not delete the entry
    because no atoms can be selected?" Exactly that - the window's Del runs
    the delete OPERATOR, which acts on selected atoms, so the one object you
    could not get rid of was the one there was nothing else to do with."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    obj_id = win.new_empty_molecule()
    assert win.scene.get(obj_id).structure.n_atoms == 0
    win.outliner.highlight(obj_id)
    win.outliner.tree.setCurrentItem(win.outliner.tree.topLevelItem(0))
    assert win.outliner.selected_object_ids() == [obj_id]
    before = win.scene.n_objects
    # THROUGH THE KEY, not through the handler. Round 103b called
    # `outliner.keyPressEvent` directly, which is how it came to pin a fix
    # that no hand could reach: `Del` is a window-level QAction and Qt
    # dispatches it before the focused widget sees the key at all.
    win.run_op("delete_selected")
    assert win.scene.n_objects == before - 1


# ------------------------------------------------- N4: distribute (round 103)
def test_distribute_leaves_an_exact_clearance_and_keeps_the_group_put():
    """The number is the CLEAR SPACE between neighbours, not their centre
    spacing, so it means the same thing whatever sizes are in the selection.
    And the group is recentred on the span it already occupied - spreading
    three molecules must not also slide them off to one side."""
    from molom.core import align
    widths, centres = [4.0, 2.0, 6.0], [0.0, 10.0, 20.0]
    out = align.distribute_offsets(widths, centres, gap=3.0)
    for k in range(2):
        clear = ((out[k + 1] - widths[k + 1] / 2.0)
                 - (out[k] + widths[k] / 2.0))
        assert clear == pytest.approx(3.0)
    assert sum(out) / 3.0 == pytest.approx(sum(centres) / 3.0)


def test_distribute_keeps_the_ORDER_the_objects_already_had():
    """Tidying an arrangement up, not reshuffling it into scene-id order -
    which would move things past each other for no visible reason."""
    from molom.core import align
    out = align.distribute_offsets([2.0, 6.0, 4.0], [10.0, 20.0, 0.0],
                                   gap=3.0)
    assert out[2] < out[0] < out[1]        # the one at x=0 stays leftmost


def test_the_extent_is_measured_along_the_AXIS_not_as_a_radius():
    """A long flat molecule laid along x is nearly its own length wide in x
    and almost nothing in y; a bounding radius would leave a hole."""
    from molom.core import align
    coords = np.array([[-5.0, 0.0, 0.0], [5.0, 0.1, 0.0]])
    cx, wx = align.axis_extent(coords, np.array([1.0, 0.0, 0.0]))
    cy, wy = align.axis_extent(coords, np.array([0.0, 1.0, 0.0]))
    assert wx == pytest.approx(10.0)
    assert wy == pytest.approx(0.1)
    assert cx == pytest.approx(0.0)


def test_the_distribute_modal_previews_commits_and_reverts(win):
    """Same contract as every other modal: move to preview, click to confirm,
    Esc to revert exactly."""
    from molom.core import align, build
    unit = np.array([1.0, 0.0, 0.0])
    ids = []
    for k in range(3):
        obj = win.scene.add(build.cubane())
        obj.structure.frames[0][:] += np.array([k * 1.0, 0.0, 0.0])
        ids.append(obj.id)
    win.viewport.set_selection([(i, 0) for i in ids])

    def gaps():
        v = [align.axis_extent(win.scene.get(i).structure.coords, unit)
             for i in ids]
        return [((v[k + 1][0] - v[k + 1][1] / 2.0)
                 - (v[k][0] + v[k][1] / 2.0)) for k in range(len(v) - 1)]

    start = gaps()
    win.viewport.start_distribute("x")
    assert win.viewport._internal is not None
    win.viewport._internal["state"].add_delta(1.0)      # 2.0 -> 3.0 A
    win.viewport._apply_internal()
    assert all(g == pytest.approx(3.0) for g in gaps())
    win.viewport._finish_internal(True)
    assert all(g == pytest.approx(3.0) for g in gaps())

    win.viewport.set_selection([(i, 0) for i in ids])
    win.viewport.start_distribute("x")
    win.viewport._internal["state"].add_delta(5.0)
    win.viewport._apply_internal()
    win.viewport._finish_internal(False)
    assert gaps() == pytest.approx([3.0, 3.0]), "cancel must revert exactly"
    assert start != pytest.approx(gaps())


def test_distribute_refuses_a_selection_of_one(win):
    """Two is the fewest that can have a gap between them."""
    from molom.core import build
    obj = win.scene.add(build.cubane())
    win.viewport.set_selection([(obj.id, 0)])
    win.viewport.start_distribute("x")
    assert win.viewport._internal is None
