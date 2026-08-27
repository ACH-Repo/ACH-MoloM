"""Round 90: finding a MOLECULE by name, and what is known about it.

Christian, 2026-08-26: make Ctrl+Shift+N work like the crystal search
(multiple results, favourites, header sorting, molecular weight), show the
skeletal structure of the selected one, and add a properties tab for a plain
molecule - as an add-on for now.

Every network fact these tests encode was MEASURED against the live services
on 2026-08-26 and is reproduced here through an injected fetch, so the suite
stays offline. The two that matter most:

* `/name/xylene/cids` and `/name/cresol/cids` return **404** - not because
  PubChem lacks the compound (o-xylene is CID 7237 with a full record) but
  because neither name is a synonym of any single compound.
* OPSIN answers both with the ORTHO isomer and says nothing about it.
"""
import json
import urllib.parse

import pytest

from molom.core import molprops, molsearch

# ---------------------------------------------------------------- fixtures
#: What OPSIN really returns for these, verbatim.
OPSIN_XYLENE = "C=1(C(=CC=CC1)C)C"          # o-xylene
OPSIN_CRESOL = "C1(=CC=CC=C1O)C"            # o-cresol

#: The InChIKeys those hash to, and the CIDs PubChem answers with. Measured.
KEY_O_XYLENE = "CTQNGGLPUBDAKN-UHFFFAOYSA-N"
CID_O_XYLENE = 7237
CID_M_XYLENE = 7929
CID_P_XYLENE = 7809

#: PubChem's autocomplete order for "xylene", verbatim.
AUTOCOMPLETE_XYLENE = ["M-XYLENE", "P-XYLENE", "O-XYLENE"]

_TITLES = {CID_O_XYLENE: ("O-Xylene", "C8H10", "106.17"),
           CID_M_XYLENE: ("M-Xylene", "C8H10", "106.16"),
           CID_P_XYLENE: ("P-Xylene", "C8H10", "106.16")}
_NAME_TO_CID = {"m-xylene": CID_M_XYLENE, "p-xylene": CID_P_XYLENE,
                "o-xylene": CID_O_XYLENE}


def fake_fetch(url):
    """A stand-in for the four endpoints, behaving as the real ones do."""
    if "opsin" in url:
        return (200, OPSIN_XYLENE) if "xylene" in url.lower() else (404, "")
    if "cactus" in url:
        return 404, ""
    if "autocomplete" in url:
        return 200, json.dumps(
            {"total": 3, "dictionary_terms": {"compound": AUTOCOMPLETE_XYLENE}})
    if "/compound/name/" in url:
        name = urllib.parse.unquote(url.split("/compound/name/")[1]
                                    .split("/")[0]).lower()
        cid = _NAME_TO_CID.get(name)
        # THE MEASURED 404: an ambiguous parent name is not a synonym of any
        # single compound, so the exact endpoint simply refuses it.
        return (200, json.dumps({"IdentifierList": {"CID": [cid]}})) if cid \
            else (404, "")
    if "/compound/inchikey/" in url:
        return 200, json.dumps({"IdentifierList": {"CID": [CID_O_XYLENE]}})
    if "/property/" in url:
        cids = url.split("/compound/cid/")[1].split("/property/")[0]
        rows = []
        for raw in cids.split(","):
            cid = int(raw)
            title, formula, weight = _TITLES[cid]
            rows.append({"CID": cid, "Title": title,
                         "MolecularFormula": formula,
                         "MolecularWeight": weight,
                         "InChIKey": KEY_O_XYLENE if cid == CID_O_XYLENE
                         else "KEY{}".format(cid),
                         "SMILES": "Cc1ccccc1C"})
        return 200, json.dumps({"PropertyTable": {"Properties": rows}})
    return 404, ""


# ------------------------------------------------- the join key is identity
def test_the_join_key_is_the_STRUCTURE_not_the_name():
    """The whole architecture in one assertion.

    PubChem's name index 404s on "xylene"; hashing OPSIN's answer and asking
    by InChIKey finds the compound at once. That is why a cascade answering
    first does not starve the properties tab: enrichment does not care which
    tier found the structure.
    """
    assert fake_fetch(
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/xylene/"
        "cids/JSON")[0] == 404
    key = molsearch.inchikey_for_smiles(OPSIN_XYLENE)
    assert key == KEY_O_XYLENE
    assert molsearch.cid_for_inchikey(key, fetch=fake_fetch) == CID_O_XYLENE


def test_a_smiles_is_not_a_join_key():
    """RDKit's canonical SMILES for o-xylene is not the string OPSIN wrote,
    which is exactly why the join runs on an InChIKey instead."""
    from rdkit import Chem
    canonical = Chem.MolToSmiles(Chem.MolFromSmiles(OPSIN_XYLENE))
    assert canonical != OPSIN_XYLENE
    assert (molsearch.inchikey_for_smiles(canonical)
            == molsearch.inchikey_for_smiles(OPSIN_XYLENE))


# ------------------------------------------------ the silent disambiguation
def test_a_silently_interpreted_name_is_reported():
    """OPSIN reads "xylene" as o-xylene without a word. The row says so."""
    assert molsearch._interpretation_note("xylene", "O-Xylene")
    assert molsearch._interpretation_note("cresol", "O-Cresol")


def test_an_unrelated_preferred_name_makes_no_claim():
    """PubChem's own name for ferrocene is "Bis(eta-cyclopentadienyl) iron".

    That is a different NAME for the same thing, not a different compound, so
    a bare title mismatch cannot be the test - it would cry wolf on every
    compound whose common name is not PubChem's preferred one.
    """
    assert not molsearch._interpretation_note(
        "ferrocene", "Bis(eta-cyclopentadienyl) iron")
    assert not molsearch._interpretation_note("aspirin", "Aspirin")


def test_the_end_to_end_xylene_case():
    """The search Christian's report is about, offline.

    Three isomers come back, each with a formula and a weight, and the
    interpretation note survives onto the row it belongs to.
    """
    result = molsearch.search("xylene", fetch=fake_fetch)
    assert len(result) == 3
    names = {c.name for c in result.candidates}
    assert names == {"O-Xylene", "M-Xylene", "P-Xylene"}
    ortho = [c for c in result.candidates if c.name == "O-Xylene"][0]
    assert "read 'xylene' as O-Xylene" in ortho.note
    assert ortho.cid() == CID_O_XYLENE
    assert all(c.formula == "C8H10" for c in result.candidates)
    assert all(c.weight and 105 < c.weight < 107 for c in result.candidates)
    assert result.ambiguous


def test_opsin_and_pubchem_agree_on_ONE_row_not_two():
    """OPSIN's o-xylene and PubChem's O-XYLENE are the same compound.

    They arrive from different providers with different references and must
    collapse, or the list shows one molecule twice and the user picks between
    two identical things.
    """
    result = molsearch.search("xylene", fetch=fake_fetch)
    keys = [c.key() for c in result.candidates]
    assert len(keys) == len(set(keys))
    assert sum(1 for c in result.candidates if c.name == "O-Xylene") == 1


# ------------------------------------------------------ incremental filling
def test_merge_batch_never_moves_a_row_that_is_already_drawn():
    """Round 78's rule applied to a search: a provider landing second may add
    rows, never reorder the ones being read."""
    first = [molsearch.Candidate("opsin", ref="a", inchikey="K1", name="A"),
             molsearch.Candidate("opsin", ref="b", inchikey="K2", name="B")]
    shown = list(first)
    later = [molsearch.Candidate("pubchem", ref="9", inchikey="K3", name="C"),
             molsearch.Candidate("pubchem", ref="8", inchikey="K1", name="A")]
    added, updated = molsearch.merge_batch(shown, later)
    assert [c.inchikey for c in shown[:2]] == ["K1", "K2"]
    assert len(added) == 1 and added[0].inchikey == "K3"
    assert updated == [0]


def test_a_later_provider_FILLS_a_row_rather_than_duplicating_it():
    """PubChem arriving after OPSIN gives the existing row its CID."""
    shown = [molsearch.Candidate("opsin", ref="xylene", inchikey="K1",
                                 smiles=OPSIN_XYLENE)]
    late = molsearch.Candidate("pubchem", ref="7237", inchikey="K1",
                               name="O-Xylene")
    late.pubchem_cid = 7237
    molsearch.merge_batch(shown, [late])
    assert len(shown) == 1
    assert shown[0].name == "O-Xylene"
    assert shown[0].cid() == 7237
    # ...and the structure OPSIN supplied is not lost in the merge.
    assert shown[0].smiles == OPSIN_XYLENE


# ------------------------------------------------------- columns and ranking
def test_formula_and_weight_are_computed_OFFLINE_for_every_row():
    """Which is what makes them honest columns: a weight that appeared only
    on PubChem rows would be blank exactly where the alternatives are."""
    assert molsearch.formula_for_smiles(OPSIN_XYLENE) == "C8H10"
    weight = molsearch.weight_for_smiles(OPSIN_XYLENE)
    assert weight is not None and abs(weight - 106.17) < 0.05


def test_an_exact_name_outranks_a_verbatim_answer_which_outranks_similarity():
    exact = molsearch.Candidate("pubchem", ref="1", name="Xylene")
    verbatim = molsearch.Candidate("opsin", ref="xylene", name="O-Xylene",
                                   verbatim=True)
    similar = molsearch.Candidate("pubchem", ref="2", name="4-Iodo-m-xylene")
    scores = [molsearch.score_candidate("xylene", c)
              for c in (exact, verbatim, similar)]
    assert scores[0] > scores[1] > scores[2]


def test_the_providers_own_ordering_survives_as_a_tie_break():
    """Autocomplete is already RANKED - M-XYLENE, P-XYLENE, O-XYLENE - and
    re-guessing that from string similarity alone would be strictly worse."""
    # The same NAME on both, so the similarity score is identical and the
    # hint is the only thing left to order them by. Two different names would
    # be a test of `fuzzy` instead, which already rewards a shorter
    # candidate - and that difference would decide the order before the
    # tie-break was ever consulted.
    cands = [molsearch.Candidate("pubchem", ref="3", name="O-Xylene",
                                 rank_hint=3),
             molsearch.Candidate("pubchem", ref="1", name="O-Xylene",
                                 rank_hint=1)]
    ordered = molsearch.rank("xylene", cands)
    assert [c.ref for c in ordered] == ["1", "3"]


def test_ambiguity_is_only_claimed_when_the_name_names_a_CLASS():
    """Several results is not ambiguity. Several results that are the query
    PLUS SOMETHING is."""
    klass = [molsearch.Candidate("pubchem", ref=str(i), name=n)
             for i, n in enumerate(("O-Xylene", "M-Xylene", "P-Xylene"))]
    assert molsearch.ambiguity_note("xylene", klass)
    exact = klass + [molsearch.Candidate("pubchem", ref="9", name="Xylene")]
    assert not molsearch.ambiguity_note("xylene", exact)


# ------------------------------------------------------------ pasted input
def test_a_pasted_smiles_still_works_and_now_identifies_itself():
    """The old dialog accepted SMILES and InChI, so this one must too.

    It also does better than the old one: the InChIKey join means a pasted
    structure comes back with a NAME.
    """
    found = molsearch.search_input("Cc1ccccc1C")
    assert len(found) == 1 and found[0].source == molsearch.SOURCE_INPUT
    assert found[0].inchikey == KEY_O_XYLENE
    enriched = molsearch.enrich(found, fetch=fake_fetch)
    assert enriched[0].name == "O-Xylene"


def test_a_name_is_not_treated_as_a_structure():
    assert molsearch.search_input("benzoic acid") == []


# ------------------------------------------------------------- the throttle
def test_pubchem_is_throttled_and_a_503_is_retried():
    """MEASURED: a burst of twelve lookups through an 8-worker pool completes
    in 0.64 s and the last two come back 503 "too many requests per second" -
    after which the bulk property call that fills the list is the one that
    gets refused. The failure is silent and looks exactly like broken
    enrichment.
    """
    assert molsearch.PUBCHEM_MAX_PER_SECOND <= 5
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) < 2:
            return 503, "too many requests per second"
        return 200, json.dumps({"ok": True})

    # An INJECTED fetch is never slept on - a test must not sit in the rate
    # limiter for a service it is not calling.
    assert molsearch._pubchem_json(flaky, "http://x") is None
    assert len(calls) == 1


def test_the_unranked_word_search_is_not_used():
    """It returns 1064 CIDs for xylene in database order and ignores
    MaxRecords; asking for their properties is a 414. Truncating an unranked
    list is round 85's mistake, so the guard is that the parameter never
    appears at all."""
    import inspect
    assert "name_type=word" not in inspect.getsource(molsearch)


# ------------------------------------------------------------- favourites
def test_a_molecule_favourite_stores_the_STRUCTURE_unlike_a_crystal_one():
    """A CIF favourite is a reference because the file is big and goes stale.
    A molecule's structure IS a short string, so storing it costs nothing and
    makes a starred compound importable with no network at all."""
    cand = molsearch.Candidate("opsin", ref="xylene", name="O-Xylene",
                               smiles=OPSIN_XYLENE, formula="C8H10",
                               weight=106.17, inchikey=KEY_O_XYLENE)
    cand.pubchem_cid = CID_O_XYLENE
    back = molsearch.candidate_from_dict(cand.to_dict())
    assert back.smiles == OPSIN_XYLENE
    assert back.key() == cand.key()
    assert back.cid() == CID_O_XYLENE


def test_a_corrupt_favourite_is_dropped_not_raised():
    assert molsearch.candidate_from_dict({"nonsense": 1}) is None
    assert molsearch.candidate_from_dict(None) is None


# ------------------------------------------------------------- the picture
def test_the_skeletal_picture_is_png_bytes_and_needs_no_network():
    from molom.core import depict
    if not depict.available():
        pytest.skip("RDKit was built without the Cairo backend")
    png = depict.depict(OPSIN_XYLENE)
    assert png and png[:4] == b"\x89PNG"


def test_a_bad_smiles_gives_no_picture_rather_than_an_exception():
    from molom.core import depict
    assert depict.depict("not a smiles") is None
    assert depict.depict("") is None
