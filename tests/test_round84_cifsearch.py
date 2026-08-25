"""Round 84: finding a crystal structure without leaving MoloM.

Christian: "Searching the COD by hand is a pain... a tiered search algorithm
that doesn't die or stall if a single tier doesn't work right away and that
allows for fuzzy string matching and selection of multiple options found."

Every test here is OFFLINE - the providers take an injectable `fetch` - but
the payloads are REAL, captured from the live services while building this
(the CLAUDE.md rule: never write a parser fixture from memory). Calling them
for real is also what found four bugs no amount of reading would have:

  * COD writes its formulae as "- O2 Si -", and the leading dash made
    `formula_key` bail, so every COD hit scored as a NAME match;
  * Materials Project's `chemical_formula_descriptive` is the whole cell's
    ("O96Si48"), so it never canonicalised to the query and every MP hit fell
    below MIN_SCORE - silently;
  * COD's own OPTIMADE endpoint answers 501, so listing it as a provider put
    a guaranteed failure line in every search;
  * a plain substring test scored "Ferrocenecarboxylic anhydride" exactly as
    highly as a file called ferrocene.
"""

import json
import os

import pytest

from molom.core import cifsearch as cs

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

#: One row of COD's `result.php?format=json`, verbatim.
COD_ROW = {
    "file": "1011172", "a": "4.913", "b": "4.913", "c": "5.405",
    "alpha": "90", "beta": "90", "gamma": "120", "celltemp": None,
    "formula": "- O2 Si -", "sg": "P 31 2 1", "mineral": "Quartz low",
    "chemname": "Silicon oxide", "commonname": None, "year": "1939",
    "doi": None,
}

#: One OPTIMADE entry from Materials Project, trimmed to the fields read.
MP_ENTRY = {
    "id": "mp-683953",
    "attributes": {
        "chemical_formula_descriptive": "O96Si48",
        "chemical_formula_reduced": "O2Si",
        "space_group_symbol_hermann_mauguin": "P4_132",
        "space_group_symbol_hall": "P 4bd 2ab 3",
        "lattice_vectors": [[-8.324448, 8.324448, 8.324448],
                            [8.324448, -8.324448, 8.324448],
                            [8.324448, 8.324448, -8.324448]],
    },
}


# ------------------------------------------------------------------ formula
def test_a_formula_canonicalises_whatever_order_it_is_written_in():
    assert cs.formula_key("TiO2") == cs.formula_key("O2Ti") == "O2 Ti1"
    assert cs.formula_key("SiO2") == "O2 Si1"


def test_the_wrappers_real_sources_put_round_a_formula():
    """COD's dashes and a CIF's quotes. Found by calling COD."""
    assert cs.formula_key("- O2 Si -") == "O2 Si1"
    assert cs.formula_key("'O2 Si'") == "O2 Si1"


def test_prose_is_not_a_formula():
    for text in ("quartz", "a bad string", "", "high cristobalite"):
        assert cs.formula_key(text) == ""


def test_fractional_occupancies_canonicalise_too():
    assert cs.formula_key("Nb0.5Ti0.25Ni0.15Co0.1O2") == (
        "Co0.1 Nb0.5 Ni0.15 O2 Ti0.25")


# -------------------------------------------------------------------- fuzzy
def test_a_whole_word_beats_a_prefix():
    """The discriminator, and the reason a substring test is not enough:
    both of these CONTAIN the query."""
    exact = cs.fuzzy("ferrocene", "cod 2101932 ferrocene")
    derivative = cs.fuzzy("ferrocene", "Ferrocenecarboxylic anhydride")
    assert exact > derivative
    assert derivative < cs.MIN_SCORE / 0.70     # below the name-weighted bar


def test_an_exact_name_scores_one():
    assert cs.fuzzy("quartz", "Quartz") == 1.0
    assert cs.fuzzy("quartz", "Quartz low") > cs.fuzzy("quartz",
                                                       "cristobalite")


def test_an_unrelated_name_is_noise():
    assert cs.fuzzy("quartz", "cristobalite") < 0.3


# ---------------------------------------------------------- ranking, dedupe
def test_an_exact_formula_outranks_any_name_similarity():
    """A canonical formula match is a chemical identity, not a spelling."""
    by_formula = cs.Hit(cs.SOURCE_COD, 1, formula="O2 Si")
    by_name = cs.Hit(cs.SOURCE_COD, 2, formula="TiO2", mineral="Sio2ish")
    assert cs.score_hit("SiO2", by_formula) >= 0.90
    assert cs.score_hit("SiO2", by_formula) > cs.score_hit("SiO2", by_name)


def test_noise_is_dropped():
    hits = [cs.Hit(cs.SOURCE_COD, 1, formula="TiO2", mineral="Rutile")]
    assert cs.rank("quartz", hits) == []


def test_one_entry_served_twice_collapses_and_local_wins():
    cell = (4.913, 4.913, 5.405, 90.0, 90.0, 120.0)
    common = dict(formula="SiO2", mineral="Quartz", spacegroup="P3221",
                  cell=cell, year=2001)
    hits = [cs.Hit(cs.SOURCE_COD, 2, **common),
            cs.Hit(cs.SOURCE_OPTIMADE, "cod/2", **common),
            cs.Hit(cs.SOURCE_LOCAL, "q.cif", **common)]
    out = cs.dedupe(hits)
    assert len(out) == 1
    assert out[0].source == cs.SOURCE_LOCAL


def test_a_REDETERMINATION_survives_as_its_own_row():
    """Same formula, same space group, a cell differing in the third decimal
    - a different measurement, and the thing a user is choosing between."""
    common = dict(formula="SiO2", mineral="Quartz", spacegroup="P3221")
    hits = [cs.Hit(cs.SOURCE_COD, 2, cell=(4.913, 4.913, 5.405, 90, 90, 120),
                   year=2001, **common),
            cs.Hit(cs.SOURCE_COD, 9, cell=(4.916, 4.916, 5.410, 90, 90, 120),
                   year=1980, **common)]
    assert len(cs.dedupe(hits)) == 2


# ----------------------------------------------------------------- the COD
def _fetch(payload, status=200):
    return lambda url, timeout: (status, json.dumps(payload))


def test_a_real_COD_row_is_read_correctly():
    hits = cs.search_cod("SiO2", fetch=_fetch([COD_ROW]))
    assert len(hits) == 1
    hit = hits[0]
    assert hit.ref == "1011172"
    assert hit.formula == "O2 Si"              # cleaned for reading
    assert cs.formula_key(hit.formula) == "O2 Si1"      # and still matches
    assert hit.mineral == "Quartz low"
    assert hit.spacegroup == "P 31 2 1"
    assert hit.year == 1939
    assert hit.cell == pytest.approx((4.913, 4.913, 5.405, 90.0, 90.0, 120.0))
    assert not hit.computed
    assert cs.cod_cif_url(hit.ref).endswith("/1011172.cif")


def test_a_standard_uncertainty_is_dropped_from_a_number():
    row = dict(COD_ROW, a="4.9134(2)")
    assert cs.search_cod("SiO2", fetch=_fetch([row]))[0].cell[0] == \
        pytest.approx(4.9134)


def test_the_best_rows_survive_the_shortlist_not_the_first_ones():
    """COD returns rows in file-id order, which has nothing to do with the
    query, so truncating before ranking picked the shortlist at random."""
    rows = [dict(COD_ROW, file=str(i), mineral="Cristobalite", formula="- O2 Si -")
            for i in range(80)]
    rows.append(dict(COD_ROW, file="999", mineral="Quartz"))
    hits = cs.search_cod("quartz", fetch=_fetch(rows), limit=3)
    assert hits[0].ref == "999"


# ------------------------------------------------------------- OPTIMADE
def test_the_filter_uses_the_reduced_formula():
    assert cs.optimade_filter("SiO2") == 'chemical_formula_reduced="O2Si"'
    assert cs.optimade_filter("TiO2") == 'chemical_formula_reduced="O2Ti"'


def test_a_solid_solution_is_asked_for_by_ELEMENTS():
    """A fractional occupancy has no reduced formula, and asking by elements
    is the honest query for one anyway."""
    assert cs.optimade_filter("Nb0.5Ti0.25Ni0.15Co0.1O2") == (
        'elements HAS ALL "Co","Nb","Ni","O","Ti"')


def test_a_name_cannot_be_asked_of_OPTIMADE_at_all():
    """The spec describes STRUCTURES: there is no mineral name and no common
    name in it, which is exactly the half COD's text index covers."""
    assert cs.optimade_filter("quartz") == ""
    assert cs.search_optimade("quartz", fetch=_fetch({})) == []


def test_a_real_MP_entry_uses_the_reduced_formula_and_HM_symbol():
    hits = cs.search_optimade("SiO2", fetch=_fetch({"data": [MP_ENTRY]}),
                              providers=(("Materials Project", "http://x"),))
    assert len(hits) == 1
    hit = hits[0]
    # DESCRIPTIVE is the whole cell ("O96Si48") and never matches the query.
    assert hit.formula == "O2Si"
    assert cs.score_hit("SiO2", hit) >= 0.90        # a formula match
    # Hermann-Mauguin, not the Hall symbol a crystallographer does not read.
    assert hit.spacegroup == "P4_132"
    assert hit.computed
    assert "computed" in hit.label()
    assert hit.cell is not None and len(hit.cell) == 6


def test_one_provider_failing_costs_that_provider_and_nothing_else():
    def half(url, timeout):
        if "dead" in url:
            raise OSError("down")
        return 200, json.dumps({"data": [MP_ENTRY]})
    trouble = []
    hits = cs.search_optimade("SiO2", fetch=half, trouble=trouble,
                              providers=(("dead one", "http://dead"),
                                         ("live one", "http://live")))
    assert len(hits) == 1
    assert len(trouble) == 1 and "dead one" in trouble[0]


# -------------------------------------------------------------- the search
def test_a_search_with_no_network_still_uses_the_disk():
    result = cs.search("ferrocene", roots=[DATA], network=False)
    assert len(result) == 1
    assert result.hits[0].source == cs.SOURCE_LOCAL
    assert result.hits[0].ref.endswith("cod_2101932_ferrocene.cif")


def test_A_DEAD_NETWORK_DOES_NOT_STALL_OR_KILL_THE_SEARCH():
    """The headline, and round 37's lesson: a dead tier costs a TIER, not the
    answer. `resolve._resolve_inner` returned on a tier-1 network error and
    took the whole cascade with it, which is a feature nobody can reach."""
    def dead(url, timeout):
        raise OSError("no network here")
    result = cs.search("ferrocene", roots=[DATA], fetch=dead, timeout=0.5)
    assert len(result) == 1                    # the local hit still arrived
    assert result.trouble                      # and it SAYS what failed
    assert "did not answer" in result.summary()


def test_a_search_that_finds_nothing_says_so():
    result = cs.search("unobtainium", roots=[DATA], network=False)
    assert len(result) == 0
    assert "No structures found" in result.summary()
    assert cs.search("", roots=[DATA], network=False).trouble


def test_the_local_index_reads_a_real_cif_header():
    hit = cs.index_cif(os.path.join(DATA, "cod_1547149_solid_solution.cif"))
    assert hit.source == cs.SOURCE_LOCAL
    assert cs.formula_key(hit.formula) == cs.formula_key(
        "Nb0.5Ti0.25Ni0.15Co0.1O2")
    assert hit.spacegroup == "P 42/m n m"
    assert hit.cell == pytest.approx((4.69859, 4.69859, 3.02607,
                                      90.0, 90.0, 90.0))


def test_a_file_that_is_not_a_cif_is_not_indexed(tmp_path):
    path = tmp_path / "notes.cif"
    path.write_text("just some prose\n", encoding="utf-8")
    assert cs.index_cif(str(path)) is None


# --------------------------------------------------------------- fetching
def test_a_local_hit_is_just_read():
    hit = cs.index_cif(os.path.join(DATA, "cod_2101932_ferrocene.cif"))
    assert "_cell_length_a" in cs.fetch_cif(hit)


def test_a_cod_hit_that_returns_no_cif_is_refused_not_returned():
    hit = cs.Hit(cs.SOURCE_COD, 1011172)
    with pytest.raises(ValueError):
        cs.fetch_cif(hit, fetch=lambda url, timeout: (404, "<html>gone"))


def test_an_optimade_structure_becomes_a_cif_MoloM_can_read():
    """OPTIMADE serves JSON, not CIF, so without this the computed tier could
    be searched and not imported - half a feature. Converting to CIF rather
    than building a Structure keeps ONE import path for all three tiers."""
    from molom.core import cif as cif_mod
    entry = {
        "id": "mp-1",
        "attributes": {
            "lattice_vectors": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0],
                                [0.0, 0.0, 4.0]],
            "cartesian_site_positions": [[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]],
            "species_at_sites": ["Na", "Cl"],
            "species": [{"name": "Na", "chemical_symbols": ["Na"]},
                        {"name": "Cl", "chemical_symbols": ["Cl"]}],
        },
    }
    text = cs.optimade_cif(entry)
    data = cif_mod.parse_cif(text)
    assert list(data.symbols) == ["Na", "Cl"]
    assert data.cell.a == pytest.approx(4.0)
    assert data.cell.alpha == pytest.approx(90.0)
    # P1 and nothing else: OPTIMADE gives the whole cell, so claiming any
    # other group would be inventing symmetry (round 52).
    assert len(data.symops) == 1


def test_an_incomplete_optimade_structure_is_refused():
    with pytest.raises(ValueError):
        cs.optimade_cif({"id": "x", "attributes": {"lattice_vectors": []}})


def test_a_downloaded_structure_gets_a_name_worth_reading():
    """The import names an object after its FILE, so a temp name would put
    `molom_d2dtna96` in the outliner."""
    hit = cs.Hit(cs.SOURCE_COD, "9013321", formula="O2 Si", mineral="Quartz")
    assert hit.filename() == "Quartz_9013321"
    assert cs.Hit(cs.SOURCE_COD, "1", formula="O2 Si").filename() == "O2_Si_1"
    messy = cs.Hit(cs.SOURCE_COD, "2", mineral="Quartz low/high (α)")
    assert "/" not in messy.filename() and " " not in messy.filename()


# ------------------------------------------------------------------ the app
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def test_the_hotkey_is_bound(win):
    op = next(o for o in win.ops.all() if o.id == "search_cif")
    assert op.key == "Ctrl+Shift+Alt+N"


def test_the_local_folder_starts_blank_and_is_settable(win):
    """No sensible default exists for somebody else's file collection, and a
    wrong one would silently search the wrong tree."""
    assert win.cif_search_roots() == []
    win.settings.setValue("cif_search_root", DATA)
    assert win.cif_search_roots() == [DATA]


def test_the_folder_is_settable_from_settings_too(win):
    win.on_settings()
    dlg = win._settings_dlg
    assert dlg.cif_search_root() == ""
    dlg.cif_root_edit.setText(DATA)
    dlg.accept()
    assert win.cif_search_roots() == [DATA]


def test_the_dialog_lists_hits_and_multi_selects(win):
    from molom.ui.dialogs import CifSearchDialog
    dlg = CifSearchDialog(win)
    dlg._finished(cs.Results("quartz", hits=[
        cs.Hit(cs.SOURCE_COD, 1, formula="O2 Si", mineral="Quartz",
               spacegroup="P3221", year=2008),
        cs.Hit(cs.SOURCE_OPTIMADE, "mp/1", formula="O2Si", spacegroup="P4_132",
               computed=True)]))
    assert dlg.table.rowCount() == 2
    assert dlg.table.item(0, dlg.COL_NAME).text() == "Quartz"
    assert "calc" in dlg.table.item(1, dlg.COL_SOURCE).text()
    dlg.table.selectAll()
    assert len(dlg.chosen) == 2


def test_the_dialog_names_the_source_that_failed(win):
    """"Materials Project did not answer" is something a user can act on;
    "1 source failed" is not."""
    from molom.ui.dialogs import CifSearchDialog
    dlg = CifSearchDialog(win)
    dlg._finished(cs.Results("quartz", trouble=["OPTIMADE/OQMD: timed out"]))
    assert "OQMD" in dlg.info.text()
    assert not dlg.ok_btn.isEnabled()


# ------------------------------------- round 85: finding the PURE compound
def test_an_acronym_is_not_a_formula():
    """"DMSO" splits into D, M, S, O - all of which LOOK like element
    symbols, two of which are not. It parsed as a formula, so the name
    resolver was never consulted and COD was asked for a compound of D and M:
    "DMSO" found nothing at all while "dimethylsulfoxide" found co-crystals.
    """
    assert cs.formula_key("DMSO") == ""
    assert cs.formula_key("CoNi") == "Co1 Ni1"      # a real one still works
    assert cs.formula_key("Xx2") == ""


def test_a_name_is_resolved_to_a_formula(monkeypatch):
    """The fix for "never a hit for the pure chemical". COD's names cannot be
    trusted to find it: a text search for "benzoic acid" returns 2617 rows,
    exactly ONE of which is named "benzoic acid", and the pure compound's own
    entries are spelled "benzioc acid" with no chemname at all."""
    class FakeResolution:
        ok, formula, smiles = True, "C7H6O2", "O=C(O)c1ccccc1"
    from molom.core import resolve
    monkeypatch.setattr(resolve, "resolve", lambda *a, **k: FakeResolution())
    assert cs.resolve_formula("benzoic acid") == "C7H6O2"
    # A query that is already a formula is left alone - no network needed.
    assert cs.resolve_formula("SiO2") == ""


def test_a_formula_match_beats_any_name_match():
    formula_hit = cs.Hit(cs.SOURCE_COD, 1, formula="C7 H6 O2")
    name_hit = cs.Hit(cs.SOURCE_COD, 2, formula="C9 H9 N O3",
                      mineral="benzoic acid derivative")
    assert (cs.score_hit("benzoic acid", formula_hit, formula="C7H6O2")
            > cs.score_hit("benzoic acid", name_hit, formula="C7H6O2"))


def test_a_matching_name_breaks_the_tie_between_isomers():
    """C8H6O4 is terephthalic acid and also five other things."""
    right = cs.Hit(cs.SOURCE_COD, 1, formula="C8 H6 O4",
                   mineral="Terephthalic acid")
    other = cs.Hit(cs.SOURCE_COD, 2, formula="C8 H6 O4",
                   mineral="endo-7-oxabicyclo-2,3-dicarboxylic anhydride")
    assert (cs.score_hit("terephthalic acid", right, formula="C8H6O4")
            > cs.score_hit("terephthalic acid", other, formula="C8H6O4"))


def test_NO_name_outranks_a_name_that_says_something_else():
    """The one that made terephthalic and nicotinic acid unfindable. COD
    leaves 5 of its 7 C6H5NO2 entries unnamed, and one of them IS the
    nicotinic acid - while a differently-named isomer was scoring above them
    on weak similarity. An absent name is not evidence against; a name that
    clearly denotes something else is."""
    unnamed = cs.Hit(cs.SOURCE_COD, 1, formula="C6 H5 N O2")
    other = cs.Hit(cs.SOURCE_COD, 2, formula="C6 H5 N O2",
                   mineral="2-pyridinecarboxylic acid")
    assert (cs.score_hit("nicotinic acid", unnamed, formula="C6H5NO2")
            > cs.score_hit("nicotinic acid", other, formula="C6H5NO2"))


def test_the_summary_says_what_it_actually_searched_for():
    result = cs.Results("benzoic acid", hits=[cs.Hit(cs.SOURCE_COD, 1)],
                        formula="C7H6O2")
    assert "searched as C7H6O2" in result.summary()


def test_cod_is_asked_by_formula_AND_by_text():
    """They answer different questions: the formula finds the pure compound,
    the text index finds the mineral names and co-crystals a formula cannot
    express."""
    asked = []

    def fetch(url, timeout):
        asked.append(url)
        return 200, json.dumps([])
    cs.search_cod("benzoic acid", fetch=fetch, formula="C7H6O2")
    assert any("formula=" in u for u in asked)
    assert any("text=" in u for u in asked)
