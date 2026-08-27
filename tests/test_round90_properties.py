"""Round 90: the compound-properties tab, and the caps that keep it small.

Christian: "The info obtained would have to be limited so it doesn't become
too big in the future and it would have to be decided what of it should be
carried over into comments of exported coordinate files such as xyz."

`tests/data/pubchem_pugview_aspirin.json` is a VERBATIM capture of PubChem's
`Experimental Properties` response for CID 2244 (2026-08-26), pruned to the
headings the whitelist keeps - every `Information` block inside it is exactly
as the service returned it. Written from a real response rather than from
memory, which is this project's standing rule for parser fixtures.

`pubchem_pugview_cassipourine_computed.json` is the same for the COMPUTED
section of CID 101821144, which is the compound Christian reported: it has no
experimental section at all, and the first cut of this add-on asked only for
that one and so declared an entry full of data empty.
"""
import json
import os

import pytest

from molom.core import molprops

DATA = os.path.join(os.path.dirname(__file__), "data",
                    "pubchem_pugview_aspirin.json")


@pytest.fixture
def qt_window():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


@pytest.fixture
def payload():
    with open(DATA, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def parsed(payload):
    from molom.addons import mol_properties
    return mol_properties.parse_pugview(payload)


# ------------------------------------------------------------- the parsing
def test_the_real_record_parses(parsed):
    keys = {p.key for p in parsed}
    assert "melting_point" in keys and "density" in keys
    assert len(parsed) >= 10


def test_a_melting_point_is_a_BAG_OF_CITATIONS_not_a_number(parsed):
    """The measurement that shaped the whole design.

    Aspirin's own record carries SEVEN melting points in three unit
    conventions - 275 F, 138-140 with no unit at all, 135 C (rapid heating),
    135 C. Any presentation that prints one confident number is hiding a
    spread that the reader needs to see.
    """
    melting = [p for p in parsed if p.key == "melting_point"][0]
    # ALL SEVEN are kept (round 90c raised the storage cap to 8), because
    # Christian could see there was more and had no way to it: "It is
    # annoying to know there is more info but now you have no straightforward
    # way of getting it." Only three are SHOWN, which is a display choice -
    # the rest expand without a second round trip.
    assert len(melting.values) == 7
    assert melting.extra == 0
    assert molprops.PREVIEW_VALUES == 3
    assert "+4 more" in melting.summary()   # the one-line form still previews


def test_every_value_carries_its_source(parsed):
    melting = [p for p in parsed if p.key == "melting_point"][0]
    assert all(v.source for v in melting.values)
    assert "CAMEO Chemicals" in {v.source for v in melting.values}


def test_the_NUMBER_shape_is_parsed_as_well_as_the_string_one(parsed):
    """PubChem writes LogP as `{"Number": [1.18]}` and everything else as
    `StringWithMarkup`. A parser that handled only the second would silently
    drop logP and look like it was simply missing from the record."""
    logp = [p for p in parsed if p.key == "logp"][0]
    assert "1.18" in logp.summary()


def test_only_whitelisted_headings_are_kept(payload):
    """PubChem's experimental section runs to dozens of headings, most of
    them regulatory or toxicological. `Stability/Shelf Life` and
    `Decomposition` are real headings in this very response and are not
    things a structure viewer should be asserting."""
    from molom.addons import mol_properties
    parsed = mol_properties.parse_pugview(payload)
    assert all(p.key in molprops.FIELD_LABELS for p in parsed)


def test_junk_gives_no_properties_rather_than_an_exception():
    from molom.addons import mol_properties
    assert mol_properties.parse_pugview("not json") == []
    assert mol_properties.parse_pugview({"nothing": 1}) == []
    assert mol_properties.parse_pugview(None) == []


# ---------------------------------------------------------------- the caps
def test_a_full_record_stays_in_the_low_kilobytes(parsed):
    """The whole answer to "it must not become too big".

    Measured against the alternative: the FULL PubChem record for this
    compound is 1.81 MB and its experimental section alone is 75 kB. This is
    what rides every undo snapshot and every savefile, so the cap is
    arithmetic (MAX_PROPERTIES x MAX_VALUES x MAX_CHARS) rather than hope.
    """
    record = molprops.Record(name="Aspirin", formula="C9H8O4", cid=2244,
                             properties=parsed, retrieved="2026-08-26",
                             source="PubChem")
    size = molprops.estimated_bytes(record)
    assert 0 < size < 12000, size


def test_a_long_value_is_clipped_and_flattened():
    """A PUG-View string routinely carries embedded newlines, which would
    otherwise break the one-line xyz comment."""
    value = molprops.Measurement("a" * 500 + "\nsecond line", "src")
    assert len(value.value) == molprops.MAX_CHARS
    assert "\n" not in value.value


def test_more_properties_than_the_cap_are_dropped():
    props = [molprops.Property("melting_point", [("1", "s")])
             for _ in range(molprops.MAX_PROPERTIES + 10)]
    record = molprops.Record(properties=props)
    assert len(record.properties) == molprops.MAX_PROPERTIES


# ------------------------------------------------------------- persistence
def test_a_record_round_trips_through_a_structure(parsed):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0.0, 0.0, 0.0)], name="x")
    record = molprops.Record(name="Aspirin", cid=2244, properties=parsed)
    molprops.store(s, record)
    # In METADATA, so it rides undo snapshots and savefiles for free rather
    # than needing an entry in `Scene.snapshot`'s four-place checklist.
    assert molprops.METADATA_KEY in s.metadata
    back = molprops.read(s)
    assert back.cid == 2244 and len(back) == len(record)
    molprops.clear(s)
    assert molprops.read(s) is None


def test_a_future_schema_version_is_ignored_not_guessed_at():
    """Half-understanding a format is how you show somebody a melting point
    that is really a flash point."""
    assert molprops.Record.from_dict(
        {"version": molprops.SCHEMA_VERSION + 1}) is None
    assert molprops.Record.from_dict("nonsense") is None


# ---------------------------------------------------- what reaches an .xyz
def test_only_PROVENANCE_goes_into_an_xyz_comment(parsed):
    """An xyz comment is ONE line that every other program reads.

    So what belongs there is "what is this and where did it come from", not a
    few hundred characters of melting points - which is how you break
    somebody else's parser. The rest lives in the .molom savefile, where
    there is room.
    """
    record = molprops.Record(name="Aspirin", formula="C9H8O4", cid=2244,
                             inchikey="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                             properties=parsed, retrieved="2026-08-26")
    line = record.provenance()
    assert "\n" not in line
    assert "Aspirin" in line and "C9H8O4" in line and "2244" in line
    # ...and NOT the measured values.
    assert "135" not in line and "mmHg" not in line
    assert len(line) < 200


def test_an_import_by_name_writes_that_comment(tmp_path):
    """End to end through the real writer: round 76 puts
    `metadata["comment"]` on the .xyz comment line, so provenance survives
    into the one place every other program already looks."""
    from molom.core import io as io_mod
    from molom.core.structure import Structure
    record = molprops.Record(name="Aspirin", formula="C9H8O4", cid=2244)
    s = Structure.from_atoms([("C", 0.0, 0.0, 0.0)], name="aspirin",
                             metadata={"comment": record.provenance()})
    path = str(tmp_path / "aspirin.xyz")
    io_mod.write_xyz(path, list(zip(s.symbols, *s.coords.T)),
                     comment=s.metadata["comment"])
    lines = open(path, encoding="utf-8").read().splitlines()
    assert "Aspirin" in lines[1] and "CID 2244" in lines[1]


# ------------------------------------------------------------- the add-on
def test_it_loads_through_the_REAL_add_on_manager(qt_window):
    """Round 73's lesson: the MOPAC add-on shipped unloadable with all 34 of
    its tests passing, because every one of them imported the module the
    normal way while `core/addons.py` loads it BY PATH under a synthetic
    name. Testing the module is not testing the loading path.
    """
    from molom.core import addons as addon_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    ok, problem = manager.enable("mol_properties", qt_window)
    assert ok, problem
    assert "compound_properties" in qt_window.properties.buttons
    assert len(qt_window.page_sync_hooks) == 1
    ok, _ = manager.disable("mol_properties", qt_window)
    assert ok
    assert "compound_properties" not in qt_window.properties.buttons
    # The hook goes with it, or a disabled add-on keeps being called on every
    # scene sync for the rest of the session.
    assert qt_window.page_sync_hooks == []


def test_the_page_says_what_is_missing_rather_than_going_blank(qt_window):
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    page.sync(obj)
    # A molecule drawn by hand CAN now be looked up - its graph is its
    # identity - so the page invites the lookup instead of refusing it.
    assert "Not looked up yet" in page.body.text()
    assert page.fetch_btn.isEnabled()
    molprops.store(obj.structure,
                   molprops.Record(name="Cubane", formula="C8H8", cid=136721))
    page.sync(obj)
    assert "Cubane" in page.body.text()
    assert page.fetch_btn.isEnabled()


def test_properties_do_NOT_lock_the_object():
    """Round 90d removed the attachment, and Christian's instinct was right
    for a better reason than convenience.

    An overwrite lock protects something expensive and irreplaceable - round
    75's twenty-minute frequency job. A property record is a web lookup keyed
    on the structure, so the honest answer to an edit is to NOTICE it and
    offer to fetch again, not to refuse the edit. `Record.describes` does the
    noticing, and it catches an edit made by ANY route rather than only one
    that went through the edit path.
    """
    from molom.core import attachments as attach_mod
    from molom.core import build as build_mod
    from molom.core.scene import Scene
    scene = Scene()
    obj = scene.add(build_mod.cubane())
    molprops.store(obj.structure, molprops.Record(name="Cubane", cid=136090))
    assert not attach_mod.is_locked(obj)
    assert not attach_mod.needs_protection(obj)


# ------------------------------------------- measured vs computed (round 90b)
COMPUTED_DATA = os.path.join(os.path.dirname(__file__), "data",
                             "pubchem_pugview_cassipourine_computed.json")


@pytest.fixture
def computed_payload():
    with open(COMPUTED_DATA, encoding="utf-8") as fh:
        return json.load(fh)


def test_a_compound_can_have_COMPUTED_properties_and_no_measured_ones(
        computed_payload):
    """Christian's report, and the bug it exposed.

    Cassipourine (CID 101821144) answers `PUGVIEW.NotFound` for Experimental
    Properties and returns a full Computed Properties section. Asking only
    for the experimental heading therefore declared an entry that is full of
    data to be empty - and a natural product with little literature behind it
    is the ordinary case, not an exotic one.
    """
    from molom.addons import mol_properties
    props = mol_properties.parse_pugview(computed_payload)
    assert len(props) >= 10
    assert all(p.kind == molprops.KIND_COMPUTED for p in props)
    keys = {p.key for p in props}
    assert {"molecular_weight", "xlogp3", "tpsa", "hbond_donors"} <= keys


def test_BOTH_sections_are_requested(computed_payload):
    """Offline reproduction of the exact failure: the experimental heading
    404s and the computed one answers."""
    from molom.addons import mol_properties
    asked = []

    def fetch(url):
        asked.append(url)
        if "Experimental" in url:
            # PubChem's real reply for a compound with no measurements.
            return 404, '{"Fault": {"Code": "PUGVIEW.NotFound"}}'
        return 200, json.dumps(computed_payload)

    props = mol_properties.fetch_properties(101821144, fetch=fetch)
    assert len(asked) == 2
    assert any("Experimental" in u for u in asked)
    assert any("Computed" in u for u in asked)
    assert props, "a missing experimental section must not lose the computed one"


def test_the_two_kinds_are_kept_apart(payload, computed_payload):
    """A computed logP and a measured melting point are different CLAIMS.

    They are stored with their kind and the page heads them separately, so
    nothing on screen can be read as a measurement that is not one.
    """
    from molom.addons import mol_properties
    props = (mol_properties.parse_pugview(payload)
             + mol_properties.parse_pugview(computed_payload))
    record = molprops.Record(name="mixed", properties=props)
    measured = record.of_kind(molprops.KIND_MEASURED)
    computed = record.of_kind(molprops.KIND_COMPUTED)
    assert measured and computed
    assert len(measured) + len(computed) == len(record)
    # MEASURED first, because it is the half that is harder to come by.
    assert record.properties[0].kind == molprops.KIND_MEASURED
    assert record.properties[-1].kind == molprops.KIND_COMPUTED


def test_a_unit_on_a_STRING_value_is_not_dropped(computed_payload):
    """PubChem writes Molecular Weight as the string "346.6" with a separate
    `Unit: g/mol`. Reading only the string prints a bare number and calls it
    a weight."""
    from molom.addons import mol_properties
    props = mol_properties.parse_pugview(computed_payload)
    weight = [p for p in props if p.key == "molecular_weight"][0]
    assert "g/mol" in weight.summary()
    exact = [p for p in props if p.key == "exact_mass"][0]
    assert "Da" in exact.summary()


def test_a_computed_value_cites_the_program_that_produced_it(computed_payload):
    """"Computed by XLogP3 3.0" is the citation, and it matters more here
    than for a measurement: it says which model produced the number."""
    from molom.addons import mol_properties
    props = mol_properties.parse_pugview(computed_payload)
    xlogp = [p for p in props if p.key == "xlogp3"][0]
    assert "Computed by" in xlogp.values[0].source


def test_a_version_1_record_reads_as_MEASURED():
    """Everything in a version-1 record was experimental, so that is what an
    absent kind means. Reading it any other way would relabel somebody's
    stored melting points as computed."""
    old = {"version": 1, "name": "Aspirin",
           "properties": [{"key": "melting_point", "extra": 0,
                           "values": [{"value": "135 C", "source": "Merck"}]}]}
    record = molprops.Record.from_dict(old)
    assert record is not None
    assert record.properties[0].kind == molprops.KIND_MEASURED


def test_both_halves_together_still_fit_the_cap(payload, computed_payload):
    from molom.addons import mol_properties
    props = (mol_properties.parse_pugview(payload)
             + mol_properties.parse_pugview(computed_payload))
    record = molprops.Record(name="Aspirin", formula="C9H8O4", cid=2244,
                             properties=props, retrieved="2026-08-26",
                             source="PubChem")
    assert len(record.properties) <= molprops.MAX_PROPERTIES
    # MEASURED: aspirin's complete record - both halves, all eight values per
    # heading, and the source table - is 7.9 kB against the 1.81 MB it came
    # from. The bound has headroom because the cap is what guarantees the
    # size, not this number.
    size = molprops.estimated_bytes(record)
    assert 0 < size < 12000, size


def test_the_page_heads_the_two_kinds_separately(qt_window, computed_payload):
    from molom.addons import mol_properties
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    molprops.store(obj.structure, molprops.Record(
        name="Cassipourine", formula="C14H22N2S4", cid=101821144,
        properties=mol_properties.parse_pugview(computed_payload)))
    page.sync(obj)
    texts = []
    for i in range(page.rows.count()):
        widget = page.rows.itemAt(i).widget()
        if widget is not None:
            texts.extend(child.text() for child in widget.findChildren(
                type(page.title)))
    joined = " ".join(texts)
    assert "COMPUTED" in joined
    # ...and it does not claim measurements it does not have.
    assert "MEASURED" not in joined


# ------------------------------------------- presentation and reach (round 90c)
def test_all_the_values_are_STORED_so_expanding_needs_no_second_fetch(parsed):
    """Christian on the "+N further values not stored" line: "should be
    expandable/addable on click ... It is annoying to know there is more info
    but now you have no straightforward way of getting it."

    Keeping them beats being able to re-fetch them: it works offline, it
    costs no round trip, and the whole spread is what the citations are FOR.
    """
    melting = [p for p in parsed if p.key == "melting_point"][0]
    assert len(melting.values) > molprops.PREVIEW_VALUES
    assert melting.extra == 0, "nothing was dropped, so nothing to re-fetch"


def test_every_source_carries_a_link_where_PubChem_gives_one(payload):
    """Every PubChem reference has a real URL - the CAMEO datasheet, the HMDB
    entry. A citation you can follow beats one you have to go and find."""
    from molom.addons import mol_properties
    urls = mol_properties.parse_urls(payload)
    assert len(urls) >= 8
    assert all(u.startswith("http") for u in urls.values())
    record = molprops.Record(name="Aspirin", sources=urls)
    assert record.url_for("CAMEO Chemicals").startswith("https://")
    assert record.url_for("nobody said this") == ""


def test_only_http_links_are_kept():
    """These strings come from a web service and end up in a clickable link,
    so anything that is not http(s) is dropped rather than handed to the
    user's browser."""
    record = molprops.Record(sources={
        "good": "https://example.org/x", "bad": "javascript:alert(1)",
        "alsobad": "file:///etc/passwd"})
    assert record.url_for("good")
    assert record.url_for("bad") == ""
    assert record.url_for("alsobad") == ""


def test_the_source_table_is_stored_once_not_per_value(parsed, payload):
    """One compound cites a dozen sources across fifty values; repeating a
    60-character URL on each would cost more than the values do."""
    from molom.addons import mol_properties
    record = molprops.Record(name="Aspirin", properties=parsed,
                             sources=mol_properties.parse_urls(payload))
    blob = json.dumps(record.to_dict())
    for url in record.sources.values():
        assert blob.count(url) == 1


def test_computed_values_group_by_the_program_that_made_them(computed_payload):
    """Christian: "If everything is basically calculated by cactvs 3... then
    there should be a table that just says something like: Simple Computed
    Properties (Cactvs v. ...) and then list all of them." """
    from molom.addons import mol_properties
    props = mol_properties.parse_pugview(computed_payload)
    groups = dict(mol_properties.CompoundPropertiesPage._by_producer(props))
    assert "" not in groups, "every computed value has exactly one source"
    assert len(groups) >= 3
    cactvs = [k for k in groups if "Cactvs" in k]
    assert cactvs and len(groups[cactvs[0]]) >= 4


def test_a_property_whose_values_DISAGREE_has_no_single_producer(parsed):
    """Which is why the grouping cannot be assumed: a measured melting point
    has three different sources and must keep its per-value citations."""
    melting = [p for p in parsed if p.key == "melting_point"][0]
    assert melting.producer() == ""


def test_the_page_expands_a_property_in_place(qt_window, payload):
    from molom.addons import mol_properties
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    molprops.store(obj.structure, molprops.Record(
        name="Aspirin", cid=2244,
        properties=mol_properties.parse_pugview(payload),
        sources=mol_properties.parse_urls(payload)))
    page.sync(obj)
    # Matched on TEXT, not on the widget class: `core/addons.py` imports an
    # add-on BY PATH under a synthetic module name, so the class the loaded
    # page builds is a different object from the one this test imported
    # (round 46's module-identity trap).
    from PySide6.QtWidgets import QLabel
    labels = lambda: [w.text() for w in page.findChildren(QLabel)]
    assert any("Show all 7 values" in t for t in labels())
    page._expand("melting_point")
    assert any("Show fewer" in t for t in labels())
    page._collapse("melting_point")
    assert any("Show all 7 values" in t for t in labels())


def test_the_properties_page_follows_the_ACTIVE_molecule(qt_window):
    """The bug Christian reported as "fetched data is not persistent".

    It was persistent - it rode the structure's metadata and the savefile all
    along. What did not follow was the PAGE: `page_sync_hooks` ran only from
    `_sync_all`, so clicking a different molecule left the page describing
    the previous one and its Fetch button acting on the previous one. Round
    51's bug, in the hook built to prevent round 51's bug.
    """
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    a = qt_window.scene.add(build_mod.cubane())
    a.name = "A"
    b = qt_window.scene.add(build_mod.cubane())
    b.name = "B"
    molprops.store(a.structure, molprops.Record(name="Aspirin", cid=2244))
    qt_window._on_obj_activated(a.id)
    assert page._obj is a
    assert "Aspirin" in page.body.text()
    qt_window._on_obj_activated(b.id)
    assert page._obj is b, "the page must follow an outliner click"
    assert "Not looked up yet" in page.body.text()
    qt_window._on_obj_activated(a.id)
    assert "Aspirin" in page.body.text(), "and it must come back"


def test_a_viewport_pick_also_moves_the_page(qt_window):
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    a = qt_window.scene.add(build_mod.cubane())
    b = qt_window.scene.add(build_mod.cubane())
    qt_window._on_obj_activated(a.id)
    qt_window._on_selection_changed([(b.id, 0)])
    assert page._obj is b


def test_a_record_survives_a_savefile_round_trip(tmp_path, parsed, payload):
    """The other half of the report - and this half was already true. Worth
    pinning so it stays that way: metadata rides `.molom` for free, which is
    exactly why the record lives there (round 43's pattern)."""
    from molom.addons import mol_properties
    from molom.core import build as build_mod
    from molom.core import project
    from molom.core.scene import Scene
    scene = Scene()
    obj = scene.add(build_mod.cubane())
    obj.name = "A"
    molprops.store(obj.structure, molprops.Record(
        name="Aspirin", cid=2244, properties=parsed,
        sources=mol_properties.parse_urls(payload)))
    path = str(tmp_path / "t.molom")
    project.save_project(path, scene)
    back = Scene()
    back.from_dict(project.load_project(path)["scene"])
    record = molprops.read([o for o in back.objects if o.name == "A"][0]
                           .structure)
    assert record is not None and record.cid == 2244
    assert len(record.get("melting_point").values) == 7
    assert record.url_for("CAMEO Chemicals").startswith("https://")


# ------------------------------- identity from the structure (round 90d)
def test_a_DRAWN_molecule_can_be_identified_from_its_graph():
    """Christian: "I would like to be able to search for properties even on
    drawn/edited molecules ... Shouldn't it be possible to just use that as an
    identifier for queries? maybe even obtain the inchikey?"

    Yes, and it is exact rather than a guess: `io.structure_to_smiles` reads
    the drawn graph, and the hash of that is the same join key a searched
    compound gets. MEASURED: the app's own default cubane comes back as
    PubChem CID 136090 by this route.
    """
    from molom.addons import mol_properties
    from molom.core import build as build_mod
    smiles, key, problem = mol_properties.identify(build_mod.cubane())
    assert not problem
    assert smiles and key == "TXWRERCHRDBNLG-UHFFFAOYSA-N"


def test_a_crystal_is_refused_rather_than_mis_identified():
    """A packed cell is not a compound - its "molecule" is the cell contents,
    and a SMILES of that means nothing."""
    from molom.addons import mol_properties
    from molom.core import build as build_mod
    s = build_mod.cubane()
    s.metadata["cell"] = {"a": 10.0, "b": 10.0, "c": 10.0}
    _smiles, key, problem = mol_properties.identify(s)
    assert not key and "crystal" in problem


def test_something_enormous_is_refused_rather_than_stalling_the_page():
    from molom.addons import mol_properties
    from molom.core.structure import Structure
    big = Structure.from_atoms(
        [("C", i * 1.5, 0.0, 0.0)
         for i in range(mol_properties.MAX_IDENTIFY_ATOMS + 1)], name="big")
    _smiles, key, problem = mol_properties.identify(big)
    assert not key and "too large" in problem


def test_an_edit_is_NOTICED_by_comparing_the_structure(qt_window):
    """The replacement for the stale flag, and strictly better: it is asked
    of the structure rather than remembered from an edit event, so it is
    right however the molecule came to be what it is."""
    from molom.addons import mol_properties
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    from molom.core import edits
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    _s, key, _p = mol_properties.identify(obj.structure)
    molprops.store(obj.structure, molprops.Record(
        name="Cubane", cid=136090, inchikey=key,
        properties=[molprops.Property("melting_point", [("130 C", "x")])]))
    page.sync(obj)
    assert page.stale.isHidden(), "unedited: no warning"
    edits.set_element_adjusted(obj.structure, [0], "N")
    page.sync(obj)
    # isHidden, not isVisible: `isVisible` folds in every ancestor and the
    # dock is closed in a test (round 34's trap).
    assert not page.stale.isHidden()
    assert "different compound" in page.stale.text()
    assert page.fetch_btn.isEnabled(), "and nothing is locked"


def test_an_unreadable_edit_says_so_instead_of_going_quiet(qt_window):
    """An over-valent atom cannot be hashed at all, so there is nothing to
    compare - and a page of confident numbers about a structure nobody can
    identify is the wrong answer."""
    from molom.addons import mol_properties
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    from molom.core import edits
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    _s, key, _p = mol_properties.identify(obj.structure)
    molprops.store(obj.structure, molprops.Record(name="Cubane", cid=136090,
                                                  inchikey=key))
    edits.set_element(obj.structure, [0], "N")     # 4 bonds on nitrogen
    page.sync(obj)
    assert not page.stale.isHidden()
    assert "can no longer be identified" in page.stale.text()


def test_the_identity_is_cached_against_the_graph(qt_window):
    """`sync` runs on every selection change and identification is 13 ms at
    300 atoms, so it is cached - and invalidated when the graph changes."""
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    from molom.core import edits
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    first, _p = page.identity_of(obj)
    assert page.identity_of(obj)[0] == first
    edits.set_element_adjusted(obj.structure, [0], "N")
    assert page.identity_of(obj)[0] != first, "the cache must follow the graph"


# ------------------------------------------- presentation (round 90d)
def test_a_long_source_is_shortened_to_what_it_calls_itself():
    """Christian: "Allow for line wrapping on long sources, or abbreviate
    them with an acronym if possible. otherwise the side pane needs to be
    expanded very wide." Most of them carry their own acronym; the ones that
    do not introduce themselves before a comma."""
    short = molprops.abbreviate_source
    assert short("Hazardous Substances Data Bank (HSDB)") == "HSDB"
    assert short("ILO-WHO International Chemical Safety Cards (ICSCs)") == "ICSCs"
    assert short("Haz-Map, Information on Hazardous Chemicals and "
                 "Occupational Diseases") == "Haz-Map"
    # ...and a name that is already short is left exactly alone.
    assert short("CAMEO Chemicals") == "CAMEO Chemicals"
    assert short("DrugBank") == "DrugBank"


def test_alternative_names_are_kept_but_capped():
    """PubChem lists 264 synonyms for benzoic acid and 698 for aspirin. The
    first handful are the recognisable ones; the tail is registry noise."""
    record = molprops.Record(synonyms=["aspirin", "ASPIRIN", "50-78-2"]
                             + ["x%d" % i for i in range(50)])
    assert len(record.synonyms) == molprops.MAX_SYNONYMS
    assert record.synonyms[:2] == ["aspirin", "50-78-2"], "case-folded dedupe"


def test_the_card_background_does_not_bleed_onto_its_children(qt_window):
    """A stylesheet set on a widget applies to its CHILDREN too, which is why
    every row had its own little box. The `#propcard` selector confines it."""
    from molom.addons import mol_properties
    assert "QFrame#propcard" in mol_properties._CARD_CSS


def test_every_value_and_key_can_be_selected_and_says_so(qt_window):
    """Christian: "It is also not possible to mark the key names in the
    computed section... Even worse: You can, but there is no highlighting
    informing you that you can." The I-beam cursor is the affordance."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    from molom.addons import mol_properties
    from molom.core import addons as addon_mod
    from molom.core import build as build_mod
    manager = addon_mod.AddOnManager()
    manager.refresh()
    manager.enable("mol_properties", qt_window)
    page = qt_window._compound_properties_page
    obj = qt_window.scene.add(build_mod.cubane())
    with open(COMPUTED_DATA, encoding="utf-8") as fh:
        payload = json.load(fh)
    molprops.store(obj.structure, molprops.Record(
        name="Cassipourine", cid=101821144,
        properties=mol_properties.parse_pugview(payload)))
    page.sync(obj)
    keys = [w for w in page.findChildren(QLabel)
            if w.text() == "Topological polar surface area"]
    assert keys, "the computed key should be on the page"
    assert keys[0].textInteractionFlags() & Qt.TextSelectableByMouse
    assert keys[0].cursor().shape() == Qt.IBeamCursor
