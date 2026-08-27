"""Find a MOLECULE by name, as a list of candidates rather than one answer.

`core/resolve.py` turns a name into ONE structure and is right to: it is a
CASCADE, the first tier that answers wins, and that is what Ctrl+Shift+N has
always needed. This module answers the other question - "which compound did
you mean?" - and it is a different shape for a measured reason.

**Measured 2026-08-26.** PubChem's exact-name endpoint returns exactly one CID
for a clean name (benzoic acid, ferrocene, aspirin, glucose: 1 each), so the
crystal-search analogy is imperfect. A crystal name has many right answers
(polymorphs, redeterminations, temperatures); a molecule name has ONE right
structure and many candidate COMPOUNDS. So this is a disambiguation list, and
the columns exist to tell two candidates apart.

**And two perfectly ordinary names 404 outright**: the exact-name endpoint
fails for both "xylene" and "cresol", because neither is registered as a
synonym of any single compound. That is a property of PubChem's NAME INDEX,
not of its data - o-xylene is CID 7237 with a full record. Which gives the
architecture:

  **the join key between services is the STRUCTURE, not the name.**

Specifically it is the InChIKey, not the SMILES and not the CID. SMILES is not
canonical across toolkits (RDKit and OpenBabel disagree for the same
molecule), so it cannot join two databases; a CID is PubChem-local, and is
what you get AFTER the join. An InChIKey is a hash designed for exactly this,
every major service indexes on it, and RDKit computes it offline. Verified end
to end: OPSIN's answer for "xylene" hashes to CTQNGGLPUBDAKN-UHFFFAOYSA-N,
which PubChem resolves to CID 7237 immediately.

That is also why a cascade answering first is NOT a problem for the properties
tab: enrichment is keyed on the structure, so it does not care which tier
found it.

**What NOT to use.** A word-type name search returns 1064 CIDs for xylene and
3371 for glucose, in database order, and ignores MaxRecords - asking for their
properties is a 414 Request-URI Too Long. Truncating an unranked list is round
85's mistake (COD returns rows in file-id order). PubChem's AUTOCOMPLETE is the
ranked source: for "xylene" it returns M-XYLENE, P-XYLENE, O-XYLENE at the top
in about a second, which is the list a chemist wants.

**A silent disambiguation is reported.** OPSIN and CACTUS both answer "xylene"
with o-xylene and "cresol" with o-cresol, with no warning of any kind - you
type an ambiguous parent name and get the ortho isomer as though it were the
answer. `_interpretation_note` says so on the row.

UI-free and offline-testable: every provider takes an injectable `fetch` with
the same `(status, body)` contract `core/resolve.py` uses, so the tests here
never touch the network.
"""

import json
import re
import threading
import urllib.error
import urllib.parse
from typing import Callable, Dict, List, Optional, Sequence

from . import resolve as resolve_mod

SOURCE_PUBCHEM = "pubchem"
SOURCE_OPSIN = "opsin"
SOURCE_CACTUS = "cactus"
#: A structure the user pasted in, rather than a name anybody looked up.
SOURCE_INPUT = "input"
SOURCES = (SOURCE_INPUT, SOURCE_PUBCHEM, SOURCE_OPSIN, SOURCE_CACTUS)

PUBCHEM = resolve_mod.PUBCHEM
AUTOCOMPLETE = ("https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound"
                "/{}/json?limit={}")

#: How many autocomplete suggestions to turn into rows. Twelve is what the
#: resolver's did-you-mean already uses, it is one screen of a table, and each
#: one costs a name-to-CID request - measured at 1.18 s for ten, concurrently.
AUTOCOMPLETE_LIMIT = 12

#: Properties asked for in the ONE bulk call that fills the list. Deliberately
#: short: this is what a row is chosen BY, and everything else is the
#: properties tab's job, on the row that was actually picked.
#: `SMILES` is asked for by that name and comes back under that key. PubChem
#: renamed these in 2025 (IsomericSMILES -> SMILES), and the old spelling is
#: still accepted but answers under the NEW key - so reading the key you asked
#: for is what breaks. `_smiles_of` checks all three.
LIST_PROPERTIES = ("Title", "MolecularFormula", "MolecularWeight",
                   "IUPACName", "InChIKey", "SMILES")

TIMEOUT_S = 12.0

#: PubChem's documented ceiling, and it is enforced. MEASURED 2026-08-26: a
#: burst of twelve name lookups through an 8-worker pool completes in 0.64 s
#: and the last two come back **503, "too many requests per second"** - after
#: which the bulk property call that fills the list is the request that gets
#: refused. The failure is SILENT and looks nothing like throttling: the rows
#: appear with no name, no formula and no weight, i.e. exactly as though
#: enrichment were broken. Worse, it depends on how many suggestions came
#: back, so "xylene" and "aspirin" failed while "cresol" worked.
PUBCHEM_MAX_PER_SECOND = 5

#: A 503 is retried rather than dropped - it means "wait", not "no".
PUBCHEM_RETRIES = 3

#: Below this a candidate is not shown at all.
MIN_SCORE = 0.30

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# ------------------------------------------------------------------ helpers
def _norm(text):
    # type: (str) -> str
    """A name reduced to what can be compared.

    Case, spaces, hyphens and brackets all vary between services for the same
    compound ("O-Xylene", "o-xylene", "ortho xylene"), so none of them can be
    part of the comparison.
    """
    return _NON_ALNUM.sub("", str(text or "").lower())


def _rdkit_mol(smiles):
    try:
        from rdkit import Chem
    except Exception:                                   # noqa: BLE001
        return None, None
    try:
        return Chem, Chem.MolFromSmiles(str(smiles or "").strip())
    except Exception:                                   # noqa: BLE001
        return Chem, None


def inchikey_for_smiles(smiles):
    # type: (str) -> str
    """The cross-database join key. Empty string if it cannot be computed.

    This is the most important function in the module: it is what lets a
    structure found by OPSIN be looked up in PubChem, which is what makes the
    whole "different APIs carry different breadths of data" problem go away.
    """
    Chem, mol = _rdkit_mol(smiles)
    if Chem is None or mol is None:
        return ""
    try:
        return str(Chem.MolToInchiKey(mol) or "")
    except Exception:                                   # noqa: BLE001
        return ""


def weight_for_smiles(smiles):
    # type: (str) -> Optional[float]
    """Molecular weight, computed locally.

    Free, offline, and available for EVERY row whatever found it - which is
    what makes it an honest column. A weight that appeared only on PubChem
    rows would be blank exactly where the alternatives are.
    """
    _Chem, mol = _rdkit_mol(smiles)
    if mol is None:
        return None
    try:
        from rdkit.Chem import Descriptors
        return float(Descriptors.MolWt(mol))
    except Exception:                                   # noqa: BLE001
        return None


def formula_for_smiles(smiles):
    # type: (str) -> str
    _Chem, mol = _rdkit_mol(smiles)
    if mol is None:
        return ""
    try:
        from rdkit.Chem.rdMolDescriptors import CalcMolFormula
        return str(CalcMolFormula(mol) or "")
    except Exception:                                   # noqa: BLE001
        return ""


def _interpretation_note(query, title):
    # type: (str, str) -> str
    """Did the resolver quietly read the name as something more specific?

    OPSIN answers "xylene" with o-xylene and says nothing. The test is whether
    the query is a PROPER SUBSTRING of the name that came back: "xylene" is
    inside "O-Xylene" and "cresol" inside "O-Cresol", so a locant was added.

    A bare title MISMATCH would not do - PubChem's preferred name for
    ferrocene is "Bis(eta-cyclopentadienyl) iron", which is a different name
    for the same thing rather than a different compound, and "ferrocene" is
    not a substring of it. An unrelated title therefore makes no claim either
    way, which is the honest answer.
    """
    nq, nt = _norm(query), _norm(title)
    if not nq or not nt or nq == nt:
        return ""
    if nq in nt and len(nt) > len(nq):
        return "read {!r} as {}".format(query, title)
    return ""


# ---------------------------------------------------------------- candidate
class Candidate(object):
    """One compound a name might have meant.

    `smiles` is the structure and is the point of the row; everything else is
    what lets you choose between rows. `inchikey` is IDENTITY - two candidates
    with the same key are the same compound however differently they are
    named, which is what `dedupe` runs on.
    """

    __slots__ = ("source", "ref", "name", "smiles", "formula", "weight",
                 "inchikey", "iupac_name", "note", "score", "rank_hint",
                 "query", "verbatim", "pubchem_cid")

    def __init__(self, source, ref="", name="", smiles="", formula="",
                 weight=None, inchikey="", iupac_name="", note="",
                 score=0.0, rank_hint=999, query="", verbatim=False):
        self.source = str(source)
        self.ref = str(ref or "")           # a CID for PubChem, else the query
        self.name = str(name or "")
        self.smiles = str(smiles or "")
        self.formula = str(formula or "")
        self.weight = weight
        self.inchikey = str(inchikey or "")
        self.iupac_name = str(iupac_name or "")
        self.note = str(note or "")
        self.score = float(score)
        #: Where the provider itself put this one. Autocomplete is already
        #: RANKED, so its order is real information and survives as a
        #: tie-break rather than being thrown away and re-guessed.
        self.rank_hint = int(rank_hint)
        self.query = str(query or "")
        #: A provider parsed the QUERY ITSELF and returned this structure -
        #: OPSIN, CACTUS, or PubChem's exact-name lookup. That is the
        #: strongest evidence there is that this is the compound meant, and
        #: it survives `dedupe` because the row that wins the merge may be
        #: the one that arrived by autocomplete instead.
        self.verbatim = bool(verbatim)
        #: The CID this compound turned out to have, however it was FOUND.
        #: Distinct from `ref`, which records the provider's own reference -
        #: an OPSIN row keeps "opsin" as its source, because that is the
        #: truth about where the structure came from, while still carrying
        #: the CID the InChIKey join gave it. Without this split, the
        #: properties tab could only ever work on rows PubChem itself found,
        #: which is precisely the case that 404s.
        self.pubchem_cid = None

    def key(self):
        # type: () -> str
        """Identity: the structure where there is one, the reference
        otherwise. Never the name, since half the point is that one compound
        has many of them."""
        return self.inchikey or "{}:{}".format(self.source, self.ref)

    def label(self):
        # type: () -> str
        return self.name or self.iupac_name or self.formula or self.smiles

    def cid(self):
        # type: () -> Optional[int]
        """The PubChem CID, from the reference or from the InChIKey join."""
        if self.pubchem_cid is not None:
            return self.pubchem_cid
        if self.source != SOURCE_PUBCHEM:
            return None
        try:
            return int(self.ref)
        except (TypeError, ValueError):
            return None

    def to_dict(self):
        # type: () -> dict
        """A favourite, and the one place this differs from a crystal.

        A CIF favourite stores a REFERENCE and never the file, because the
        file is large and would go stale against COD. A molecule's structure
        IS a short string, so it is stored - which costs nothing and makes a
        favourite importable with no network at all.
        """
        return {"source": self.source, "ref": self.ref, "name": self.name,
                "verbatim": self.verbatim, "pubchem_cid": self.pubchem_cid,
                "smiles": self.smiles, "formula": self.formula,
                "weight": self.weight, "inchikey": self.inchikey,
                "iupac_name": self.iupac_name, "note": self.note}

    def __repr__(self):
        return "<Candidate {} {} {}>".format(self.source, self.ref,
                                             self.label())


def candidate_from_dict(data):
    # type: (dict) -> Optional[Candidate]
    """Rebuild a favourite. Returns None on anything malformed rather than
    raising - a corrupt settings entry must not take the dialog down."""
    if not isinstance(data, dict) or not data.get("source"):
        return None
    try:
        cand = Candidate(
            source=data.get("source", ""), ref=data.get("ref", ""),
            name=data.get("name", ""), smiles=data.get("smiles", ""),
            formula=data.get("formula", ""), weight=data.get("weight"),
            inchikey=data.get("inchikey", ""),
            iupac_name=data.get("iupac_name", ""), note=data.get("note", ""),
            verbatim=bool(data.get("verbatim", False)))
    except Exception:                                   # noqa: BLE001
        return None
    # Not a constructor argument, because it is DERIVED by the join rather
    # than stated - but it IS worth storing on a favourite, so a starred
    # compound still reaches the properties tab without being searched again.
    try:
        cand.pubchem_cid = (int(data["pubchem_cid"])
                            if data.get("pubchem_cid") is not None else None)
    except (TypeError, ValueError):
        cand.pubchem_cid = None
    return cand


# ---------------------------------------------------------------- providers
class _RateLimit(object):
    """At most `per_second` requests, across every thread in the process.

    Process-wide and not per-search on purpose: the limit is PubChem's, and it
    counts the whole client. Three provider threads each politely staying
    under it would still add up to three times the limit.
    """

    def __init__(self, per_second):
        self._gap = 1.0 / float(per_second)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        import time
        with self._lock:
            now = time.monotonic()
            due = max(now, self._next)
            self._next = due + self._gap
        delay = due - now
        if delay > 0:
            time.sleep(delay)


_PUBCHEM_LIMIT = _RateLimit(PUBCHEM_MAX_PER_SECOND)


def _default_fetch(url):
    # type: (str) -> tuple
    """The same getter the resolver uses.

    Shared deliberately rather than reimplemented: it already normalises a
    read TimeoutError and an ssl.SSLError into urllib.error.URLError, which
    was round 37's bug and would otherwise sail straight through every
    `except URLError` below.
    """
    return resolve_mod._http_get(url, timeout=TIMEOUT_S)


def _get_json(fetch, url):
    # type: (Callable, str) -> Optional[dict]
    """A JSON GET that answers None for every kind of miss.

    404 is an ORDINARY answer here, not an error: PubChem returns it for a
    name it does not index, which is exactly the "xylene" case this module
    exists to work around.
    """
    status, body = fetch(url)
    if status != 200 or not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _pubchem_json(fetch, url):
    # type: (Callable, str) -> Optional[dict]
    """Every PubChem request goes through here: throttled, and 503-aware.

    The throttle is skipped for an INJECTED fetch, or an offline test would
    sit in `time.sleep` for the rate limiter's benefit and nobody else's.
    """
    throttled = fetch is _default_fetch
    for attempt in range(PUBCHEM_RETRIES):
        if throttled:
            _PUBCHEM_LIMIT.wait()
        status, body = fetch(url)
        if status == 503 and throttled and attempt + 1 < PUBCHEM_RETRIES:
            import time
            time.sleep(0.5 * (attempt + 1))
            continue
        if status != 200 or not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None
    return None


def _structure_provider(service, url_template, query, fetch, live, trouble,
                        rank_hint):
    # type: (str, str, str, Callable, bool, List[str], int) -> List[Candidate]
    """OPSIN and CACTUS: one name in, one structure out, no metadata at all.

    They are kept as CANDIDATE providers rather than being left to the
    resolver because they answer the name AS TYPED - which for a systematic
    name is the authoritative reading and for an ambiguous one is a silent
    guess. Either way the row belongs in the list, and `enrich` will give it
    a real name through the InChIKey join.
    """
    if resolve_mod._is_down(service):
        trouble.append("{} was down a moment ago".format(service))
        return []
    try:
        status, body = fetch(url_template.format(
            urllib.parse.quote(query, safe="")))
    except urllib.error.URLError as exc:
        trouble.append("{} unreachable ({})".format(
            service, resolve_mod._reason(exc)))
        resolve_mod._mark_down(service, live)
        return []
    if status != 200 or not (body or "").strip():
        return []
    smiles = body.strip().splitlines()[0].strip()
    # CACTUS answers a miss with an HTML page rather than a 404, so the body
    # has to be checked for actually being a SMILES (round 37).
    if not smiles or not resolve_mod._SMILES_CHARS.match(smiles):
        return []
    return [Candidate(source=service, ref=query, name="", smiles=smiles,
                      formula=formula_for_smiles(smiles),
                      weight=weight_for_smiles(smiles),
                      inchikey=inchikey_for_smiles(smiles),
                      rank_hint=rank_hint, query=query, verbatim=True)]


def search_opsin(query, fetch=None, live=None, trouble=None):
    # type: (str, Optional[Callable], Optional[bool], Optional[List[str]]) -> List[Candidate]
    fetch = fetch or _default_fetch
    live = _default_fetch is fetch if live is None else live
    return _structure_provider("opsin", resolve_mod.OPSIN_URL, query, fetch,
                               live, trouble if trouble is not None else [], 0)


def search_cactus(query, fetch=None, live=None, trouble=None):
    # type: (str, Optional[Callable], Optional[bool], Optional[List[str]]) -> List[Candidate]
    fetch = fetch or _default_fetch
    live = _default_fetch is fetch if live is None else live
    return _structure_provider("cactus", resolve_mod.CACTUS_URL, query, fetch,
                               live, trouble if trouble is not None else [], 1)


def _cids_for_name(name, fetch, namespace="name"):
    # type: (str, Callable, str) -> List[int]
    """CIDs for a name, a CAS number or an InChIKey.

    The NAMESPACE matters: PubChem indexes a CAS number as an ordinary
    synonym, so `name` finds it, but an InChIKey has its own namespace and is
    simply not found through `name`.
    """
    try:
        data = _pubchem_json(fetch, "{}/pug/compound/{}/{}/cids/JSON".format(
            PUBCHEM, namespace, urllib.parse.quote(name)))
    except urllib.error.URLError:
        return []
    try:
        return [int(c) for c in data["IdentifierList"]["CID"]]
    except (TypeError, KeyError, ValueError):
        return []


def autocomplete_names(query, fetch=None, limit=AUTOCOMPLETE_LIMIT):
    # type: (str, Optional[Callable], int) -> List[str]
    """PubChem's ranked synonym suggestions.

    THE candidate source. See the module docstring for why the word-type name
    search is not usable for this.
    """
    fetch = fetch or _default_fetch
    try:
        data = _pubchem_json(fetch, AUTOCOMPLETE.format(
            urllib.parse.quote(query), int(limit)))
    except urllib.error.URLError:
        return []
    try:
        return [str(n) for n in data["dictionary_terms"]["compound"]][:limit]
    except (TypeError, KeyError):
        return []


def search_input(query, fetch=None, live=None, trouble=None):
    # type: (str, Optional[Callable], Optional[bool], Optional[List[str]]) -> List[Candidate]
    """A SMILES or an InChI pasted straight in.

    The old single-answer dialog accepted these and this one must too, or a
    perfectly ordinary paste stops working. It needs no network at all - and
    because `enrich` then runs the InChIKey join on it, pasting a SMILES now
    also tells you WHICH COMPOUND it is, which the resolver never did.
    """
    kind = resolve_mod.classify(query)
    if kind not in ("smiles", "inchi"):
        return []
    Chem, mol = (None, None)
    try:
        from rdkit import Chem                          # noqa: F811
        mol = (Chem.MolFromInchi(query) if kind == "inchi"
               else Chem.MolFromSmiles(query))
    except Exception:                                   # noqa: BLE001
        mol = None
    if mol is None:
        return []
    try:
        smiles = Chem.MolToSmiles(mol)
    except Exception:                                   # noqa: BLE001
        return []
    return [Candidate(source=SOURCE_INPUT, ref=query, smiles=smiles,
                      formula=formula_for_smiles(smiles),
                      weight=weight_for_smiles(smiles),
                      inchikey=inchikey_for_smiles(smiles),
                      rank_hint=0, query=query, verbatim=True)]


def search_pubchem(query, fetch=None, live=None, trouble=None,
                   limit=AUTOCOMPLETE_LIMIT):
    # type: (str, Optional[Callable], Optional[bool], Optional[List[str]], int) -> List[Candidate]
    """The tier that carries data: an exact hit plus the ranked alternatives.

    The exact lookup is tried first and is usually the answer (one CID for a
    clean name). Autocomplete then supplies the DISAMBIGUATION - the rows that
    make an ambiguous parent name answerable at all - and its own ordering is
    kept as each candidate's `rank_hint`.

    Name-to-CID runs concurrently because it is one small request per
    suggestion and doing twelve in series would put the whole search behind
    them.
    """
    from concurrent.futures import ThreadPoolExecutor

    fetch = fetch or _default_fetch
    live = _default_fetch is fetch if live is None else live
    trouble = trouble if trouble is not None else []
    if resolve_mod._is_down("pubchem"):
        trouble.append("PubChem was down a moment ago")
        return []
    out = []            # type: List[Candidate]
    seen = set()        # type: set
    namespace = ("inchikey" if resolve_mod.classify(query) == "inchikey"
                 else "name")

    def add(cid, hint, verbatim=False):
        if cid in seen:
            return
        seen.add(cid)
        out.append(Candidate(source=SOURCE_PUBCHEM, ref=str(cid),
                             rank_hint=hint, query=query, verbatim=verbatim))

    try:
        for cid in _cids_for_name(query, fetch, namespace)[:5]:
            add(cid, 0, verbatim=True)
    except urllib.error.URLError as exc:
        trouble.append("PubChem unreachable ({})".format(
            resolve_mod._reason(exc)))
        resolve_mod._mark_down("pubchem", live)
        return out
    names = ([] if resolve_mod.classify(query) in ("smiles", "inchi")
             else autocomplete_names(query, fetch=fetch, limit=limit))
    if names:
        def one(pair):
            index, name = pair
            return index, name, _cids_for_name(name, fetch)[:1]
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                found = list(pool.map(one, list(enumerate(names))))
        except Exception:                               # noqa: BLE001
            found = [one(p) for p in enumerate(names)]
        for index, _name, cids in sorted(found):
            for cid in cids:
                add(cid, index + 1)
    return out


# ----------------------------------------------------------------- enriching
def _smiles_of(row):
    # type: (dict) -> str
    for key in ("SMILES", "IsomericSMILES", "ConnectivitySMILES",
                "CanonicalSMILES"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _local_fill(cand):
    """Everything RDKit can say about a SMILES, for free and offline.

    Run before the network so the list is usable without it, and so a row from
    a provider that carries no metadata still has a formula and a weight.
    """
    if not cand.smiles:
        return
    if not cand.formula:
        cand.formula = formula_for_smiles(cand.smiles)
    if cand.weight is None:
        cand.weight = weight_for_smiles(cand.smiles)
    if not cand.inchikey:
        cand.inchikey = inchikey_for_smiles(cand.smiles)


def cid_for_inchikey(inchikey, fetch=None):
    # type: (str, Optional[Callable]) -> Optional[int]
    """THE JOIN. A structure found anywhere, looked up in PubChem.

    This is what makes a cascade's answer enrichable: OPSIN hands back a
    SMILES and nothing else, RDKit hashes it, and PubChem answers with the
    compound - including for the names its own name index 404s on.
    """
    key = str(inchikey or "").strip()
    if not key:
        return None
    fetch = fetch or _default_fetch
    try:
        data = _pubchem_json(fetch, "{}/pug/compound/inchikey/{}/cids/JSON".format(
            PUBCHEM, urllib.parse.quote(key)))
    except urllib.error.URLError:
        return None
    try:
        return int(data["IdentifierList"]["CID"][0])
    except (TypeError, KeyError, ValueError, IndexError):
        return None


def _properties_for(cids, fetch, chunk=50):
    # type: (Sequence[int], Callable, int) -> Dict[int, dict]
    """One request for the WHOLE list, not one per row.

    Chunked because the endpoint is a GET and a long enough CID list is a 414
    - which is exactly how the word-type name search fails.
    """
    out = {}                                            # type: Dict[int, dict]
    cids = [c for c in cids if c is not None]
    for start in range(0, len(cids), chunk):
        batch = cids[start:start + chunk]
        url = "{}/pug/compound/cid/{}/property/{}/JSON".format(
            PUBCHEM, ",".join(str(c) for c in batch),
            ",".join(LIST_PROPERTIES))
        try:
            data = _pubchem_json(fetch, url)
        except urllib.error.URLError:
            continue
        try:
            rows = data["PropertyTable"]["Properties"]
        except (TypeError, KeyError):
            continue
        for row in rows if isinstance(rows, list) else []:
            try:
                out[int(row["CID"])] = row
            except (TypeError, KeyError, ValueError):
                continue
    return out


def enrich(candidates, fetch=None, join=True):
    # type: (Sequence[Candidate], Optional[Callable], bool) -> List[Candidate]
    """Give every candidate a name, a formula, a weight and a structure.

    Two depths, and this is the CHEAP one: it runs for every row as the search
    lands, because a list whose OPSIN row says "xylene" next to a picture of
    the ortho isomer is actively misleading. The expensive depth - melting
    points and the rest of PubChem's experimental record - is the properties
    add-on's job, on the one row that was actually chosen.

    `join=False` turns off the InChIKey lookup for candidates that have no
    CID, which is what an offline test wants.
    """
    from concurrent.futures import ThreadPoolExecutor

    fetch = fetch or _default_fetch
    cands = list(candidates)
    for cand in cands:
        _local_fill(cand)

    by_cid = {}                                    # type: Dict[int, list]
    needs_join = []                                # type: List[Candidate]
    for cand in cands:
        cid = cand.cid()
        if cid is not None:
            by_cid.setdefault(cid, []).append(cand)
        elif join and cand.inchikey:
            needs_join.append(cand)

    if needs_join:
        def look_up(cand):
            return cand, cid_for_inchikey(cand.inchikey, fetch)
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                joined = list(pool.map(look_up, needs_join))
        except Exception:                               # noqa: BLE001
            joined = [look_up(c) for c in needs_join]
        for cand, cid in joined:
            if cid is not None:
                cand.pubchem_cid = cid
                by_cid.setdefault(cid, []).append(cand)

    if not by_cid:
        return cands
    rows = _properties_for(sorted(by_cid), fetch)
    for cid, row in rows.items():
        for cand in by_cid.get(cid, []):
            cand.pubchem_cid = cid
            title = str(row.get("Title") or "")
            if title and not cand.name:
                cand.name = title
            cand.iupac_name = cand.iupac_name or str(row.get("IUPACName") or "")
            cand.formula = cand.formula or str(row.get("MolecularFormula") or "")
            if cand.weight is None:
                try:
                    cand.weight = float(row.get("MolecularWeight"))
                except (TypeError, ValueError):
                    pass
            cand.inchikey = cand.inchikey or str(row.get("InChIKey") or "")
            if not cand.smiles:
                cand.smiles = _smiles_of(row)
                _local_fill(cand)
            # A structure provider answered the name AS TYPED; if PubChem's
            # own name for what came back is longer and contains it, a locant
            # was added on the way and nobody was told.
            if cand.source in (SOURCE_OPSIN, SOURCE_CACTUS) and not cand.note:
                cand.note = _interpretation_note(cand.query or cand.ref, title)
    return cands


# ------------------------------------------------------------------ ranking
def _merge(keep, other):
    # type: (Candidate, Candidate) -> None
    """Fold `other` into `keep`, IN PLACE.

    In place rather than by swapping, because the caller may already be
    drawing `keep` as a table row - see `merge_batch`. `keep` adopts the
    reference of whichever of the two has a PubChem CID, since a CID is what
    the properties tab needs, but it never moves.
    """
    if keep.pubchem_cid is None:
        keep.pubchem_cid = other.pubchem_cid
    if keep.source != SOURCE_PUBCHEM and other.source == SOURCE_PUBCHEM:
        keep.source, keep.ref = other.source, other.ref
    keep.smiles = keep.smiles or other.smiles
    keep.name = keep.name or other.name
    keep.iupac_name = keep.iupac_name or other.iupac_name
    keep.formula = keep.formula or other.formula
    keep.inchikey = keep.inchikey or other.inchikey
    if keep.weight is None:
        keep.weight = other.weight
    if other.note and other.note not in keep.note:
        # Above all the interpretation note, which is produced by a structure
        # provider and would otherwise be lost on exactly the merge that
        # proves it right.
        keep.note = "; ".join(x for x in (keep.note, other.note) if x)
    keep.verbatim = keep.verbatim or other.verbatim
    keep.rank_hint = min(keep.rank_hint, other.rank_hint)
    keep.score = max(keep.score, other.score)


def dedupe(candidates):
    # type: (Sequence[Candidate]) -> List[Candidate]
    """Collapse candidates that are the same COMPOUND.

    Keyed on the InChIKey, so OPSIN's answer for "xylene" and PubChem's
    O-XYLENE become one row rather than two rows of the same molecule.
    """
    out = []                                        # type: List[Candidate]
    index = {}                                      # type: Dict[str, int]
    for cand in candidates:
        key = cand.key()
        if key in index:
            _merge(out[index[key]], cand)
        else:
            index[key] = len(out)
            out.append(cand)
    return out


def merge_batch(existing, batch):
    # type: (List[Candidate], Sequence[Candidate]) -> tuple
    """Fold a provider's results into the rows already on screen.

    This is what makes an INCREMENTALLY filled list honest. Rows appear as
    each provider lands, and a row that is already drawn is never moved or
    removed - which is round 78's rule (nothing that the user is looking at
    may be recomputed under their hand) applied to a search.

    So a later provider can only do two things: append a compound nobody has
    seen yet, or fill in what an existing row was missing. PubChem arriving
    after OPSIN therefore gives the row that is already there its real name
    and its CID, rather than adding a second row for the same molecule.

    Returns `(added, updated)` - the new candidates, and the indices of the
    existing rows whose contents changed.
    """
    index = {}                                      # type: Dict[str, int]
    for i, cand in enumerate(existing):
        index.setdefault(cand.key(), i)
    added, updated = [], []
    for cand in batch:
        key = cand.key()
        if key in index:
            _merge(existing[index[key]], cand)
            if index[key] not in updated:
                updated.append(index[key])
        else:
            index[key] = len(existing)
            existing.append(cand)
            added.append(cand)
    return added, updated


def score_candidate(query, cand):
    # type: (str, Candidate) -> float
    """How likely is this the compound that was meant?

    Different from `cifsearch.score_hit` in one way that matters: there, a
    canonical FORMULA match is the strongest signal, because a crystal search
    is asked by formula as often as by name. Here the query is a name and the
    formula is an OUTPUT, so it carries no evidence at all - every candidate
    for "xylene" has the formula C8H10, which is precisely why the list needs
    a picture.
    """
    from .cifsearch import fuzzy

    names = [n for n in (cand.name, cand.iupac_name) if n]
    nq = _norm(query)
    if nq and any(_norm(n) == nq for n in names):
        return 1.0
    if cand.verbatim:
        # A provider parsed the name itself. Below an exact match, because an
        # ambiguous parent name gets an arbitrary isomer this way (round 90's
        # xylene case), and above anything merely similar.
        return 0.95
    if not names:
        return 0.60          # a structure and no name yet; enrich will fix it
    return max(fuzzy(query, n) for n in names)


def rank(query, candidates, minimum=MIN_SCORE, limit=None):
    # type: (str, Sequence[Candidate], float, Optional[int]) -> List[Candidate]
    """Score, drop the noise, and order.

    `rank_hint` is the tie-break and it is real information: PubChem's
    autocomplete is already ranked, so M-XYLENE, P-XYLENE, O-XYLENE arrive in
    a sensible order and re-guessing it from string similarity alone would be
    strictly worse.
    """
    scored = []
    for cand in candidates:
        cand.score = score_candidate(query, cand)
        if cand.score >= minimum:
            scored.append(cand)
    scored.sort(key=lambda c: (-c.score, c.rank_hint, _norm(c.label())))
    return scored[:limit] if limit else scored


# ------------------------------------------------------------------ results
class Results(object):
    """What a search produced, including what went wrong."""

    def __init__(self, query, candidates=None, trouble=None, asked=None,
                 ambiguous=""):
        self.query = str(query or "")
        self.candidates = list(candidates or [])
        #: One line per provider that failed, in the user's words rather than
        #: a traceback. A search that finds nothing and says nothing is
        #: indistinguishable from a broken one (round 84).
        self.trouble = list(trouble or [])
        self.asked = list(asked or [])
        #: Set when the NAME itself did not pick out a compound - see
        #: `ambiguity_note`.
        self.ambiguous = str(ambiguous or "")

    def __len__(self):
        return len(self.candidates)

    def summary(self):
        # type: () -> str
        if not self.candidates:
            base = "No compounds found for {!r}".format(self.query)
        else:
            base = "{} compound{} for {!r}".format(
                len(self.candidates),
                "" if len(self.candidates) == 1 else "s", self.query)
        if self.ambiguous:
            base += " - " + self.ambiguous
        if self.trouble:
            base += " - {} source{} did not answer".format(
                len(self.trouble), "" if len(self.trouble) == 1 else "s")
        return base


def ambiguity_note(query, candidates):
    # type: (str, Sequence[Candidate]) -> str
    """Say when a name did not, on its own, name a compound.

    The test is not "several results" - almost every search has several. It is
    that two or more of them are the query WITH SOMETHING ADDED: O-Xylene,
    M-Xylene, P-Xylene are all "xylene" plus a locant, which is what makes
    "xylene" a class rather than a compound. A list of derivatives that merely
    mention the query does not qualify, and neither does one exact match with
    unrelated neighbours.
    """
    nq = _norm(query)
    if not nq:
        return ""
    if any(_norm(c.name) == nq or _norm(c.iupac_name) == nq
           for c in candidates):
        return ""                    # the name DOES pick out a compound
    close = [c for c in candidates
             if nq in _norm(c.name) and len(_norm(c.name)) > len(nq)]
    if len(close) < 2:
        return ""
    return "{!r} names {} or more compounds - pick one".format(query,
                                                               len(close))


def search(query, fetch=None, network=True, limit=None, progress=None,
           join=True, timeout=TIMEOUT_S, autocomplete_limit=AUTOCOMPLETE_LIMIT):
    # type: (str, Optional[Callable], bool, Optional[int], Optional[Callable], bool, float, int) -> Results
    """Ask every provider AT ONCE, enrich each batch, merge, rank.

    Concurrent rather than cascaded - round 84's shape - because the whole
    point is that the providers know different things: OPSIN parses a
    systematic name that no index contains, PubChem holds the alternatives and
    all of the data, CACTUS answers when OPSIN is down.

    **`progress(source, candidates)` is called as each provider lands**, with
    that provider's batch already enriched and ranked, so a dialog can fill
    incrementally. It is called from the provider's own thread. Use
    `merge_batch` to fold a batch into what is already on screen: it is what
    stops a later provider reordering rows the user is reading.

    Nothing here can stall the search - each provider is its own thread with
    its own timeout, a failure is recorded and stepped over, and the result is
    whatever came back.
    """
    query = str(query or "").strip()
    trouble = []            # type: List[str]
    asked = []              # type: List[str]
    if not query:
        return Results(query, trouble=["nothing to search for"])
    fetch = fetch or _default_fetch
    live = fetch is _default_fetch
    if not network:
        return Results(query, trouble=["offline: a name needs a web service"])

    jobs = [
        (SOURCE_INPUT, lambda: search_input(query, fetch=fetch, live=live,
                                            trouble=trouble)),
        (SOURCE_OPSIN, lambda: search_opsin(query, fetch=fetch, live=live,
                                            trouble=trouble)),
        (SOURCE_CACTUS, lambda: search_cactus(query, fetch=fetch, live=live,
                                              trouble=trouble)),
        (SOURCE_PUBCHEM, lambda: search_pubchem(query, fetch=fetch, live=live,
                                                trouble=trouble,
                                                limit=autocomplete_limit)),
    ]
    found = {}              # type: Dict[str, List[Candidate]]

    if resolve_mod.classify(query) in ("smiles", "inchi"):
        # A structure is not a name: OPSIN and CACTUS have nothing to add and
        # autocomplete would search for the SMILES as text.
        jobs = [j for j in jobs if j[0] in (SOURCE_INPUT, SOURCE_PUBCHEM)]

    def run(name, job):
        try:
            batch = rank(query, enrich(job(), fetch=fetch, join=join))
        except Exception as exc:            # noqa: BLE001 - one tier, one failure
            trouble.append("{}: {}".format(name, exc))
            return
        found[name] = batch
        if progress is not None and batch:
            try:
                progress(name, batch)
            except Exception:               # noqa: BLE001
                # A dialog that has since closed must not take the search
                # thread with it.
                pass

    threads = []
    for name, job in jobs:
        asked.append(name)
        thread = threading.Thread(target=run, args=(name, job), daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        # A generous ceiling over the per-request timeout: a thread that
        # somehow outlives it is abandoned rather than waited on, because a
        # search that never returns is worse than an incomplete one.
        thread.join(timeout=timeout * 2.0 + 5.0)

    collected = []          # type: List[Candidate]
    for name in asked:
        collected.extend(found.get(name) or [])
        if name not in found and not any(name in t for t in trouble):
            trouble.append("{}: timed out".format(name))
    merged = rank(query, dedupe(collected), limit=limit)
    return Results(query, candidates=merged, trouble=trouble, asked=asked,
                   ambiguous=ambiguity_note(query, merged))
