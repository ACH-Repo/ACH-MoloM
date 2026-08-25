"""Finding a crystal structure by name, formula or mineral - and importing it.

Christian, 2026-08-24: "Searching the COD by hand is a pain. I want to know if
we can make searching and importing cifs easier."

**A crystal search is not a name resolution, and that is the whole design.**
`core/resolve.py` turns a molecule's name into ONE structure, so its tiers are
a cascade: the first that answers wins and the rest are never asked. A crystal
name maps to MANY structures - polymorphs, temperatures, pressures,
redeterminations, a dozen redeterminations of quartz - so the question is not
"which service knows this?" but "show me the candidates and let me choose".

Three consequences follow, and they are the reason this is its own module:

* **every tier is asked, and they are asked AT THE SAME TIME.** A cascade
  would hide the local copy of a structure behind a slow remote one. Results
  are merged and ranked instead.
* **a dead tier costs a TIER, never the answer** (round 37's lesson, which
  cost a whole feature when `resolve` returned on a tier-1 network error). A
  provider that times out, refuses or returns nonsense is recorded in
  `trouble` and the search carries on. A search that found nothing is a
  result; a search that STALLED is a bug.
* **ranking is done here, not by the providers.** They disagree about what
  matching means, and half of them do not do fuzzy matching at all, so the
  scoring is applied to whatever comes back - which also makes it testable
  with no network.

UI-free and network-injectable: every provider takes a `fetch` callable, so
the whole module is exercised offline.
"""

import difflib
import json
import os
import re
from typing import Callable, Dict, List, Optional, Sequence

#: Where a hit came from. Shown in the results, because "this one is already
#: on your disk" is the single most useful thing the list can say.
SOURCE_LOCAL = "local"
SOURCE_OPTIMADE = "optimade"
SOURCE_COD = "cod"
SOURCES = (SOURCE_LOCAL, SOURCE_OPTIMADE, SOURCE_COD)

#: Per-provider network budget. Deliberately short: with the tiers running
#: concurrently the slowest one sets the wait, and a search that takes ten
#: seconds is one nobody uses twice.
TIMEOUT_S = 8.0

#: How many hits a single provider may contribute AFTER ranking. A formula
#: search on COD can return thousands, and a list nobody can read is not a
#: result.
PER_SOURCE_LIMIT = 60

#: How many rows to PARSE before ranking. The distinction matters: the whole
#: response arrives in one request, so parsing more costs no network at all -
#: and truncating first threw away the best matches, because COD returns its
#: rows in file-id order, which has nothing to do with the query. A search for
#: SiO2 downloads 247 rows; ranking 60 of them by arbitrary id was picking the
#: shortlist at random.
PARSE_CEILING = 500


class Hit(object):
    """One candidate structure, from whichever provider found it.

    Deliberately flat and mostly optional: the three sources agree on almost
    nothing, and a field nobody filled must read as "not known" rather than
    as a wrong answer. `ref` is whatever that provider needs to fetch the
    file - a COD id, an OPTIMADE entry url, a path on disk.
    """

    __slots__ = ("source", "ref", "formula", "name", "mineral", "spacegroup",
                 "cell", "temperature", "year", "doi", "note", "score",
                 "computed")

    def __init__(self, source, ref, formula="", name="", mineral="",
                 spacegroup="", cell=None, temperature=None, year=None,
                 doi="", note="", computed=False):
        self.source = str(source)
        self.ref = ref
        # Cleaned for READING. COD writes "- O2 Si -" and a CIF often quotes
        # its formula; `formula_key` copes with both, but the dashes have no
        # business in a list a person is choosing from.
        self.formula = str(formula or "").strip().strip("-").strip("'\"")
        self.formula = " ".join(self.formula.split())
        self.name = str(name or "")
        self.mineral = str(mineral or "")
        self.spacegroup = str(spacegroup or "")
        self.cell = tuple(cell) if cell else None
        self.temperature = temperature
        self.year = year
        self.doi = str(doi or "")
        self.note = str(note or "")
        #: A DFT-relaxed structure rather than a measurement. Not a detail: a
        #: computed cell can be a percent or two off an experimental one, and
        #: which kind you are looking at has to be visible rather than
        #: inferred from the provider's name.
        self.computed = bool(computed)
        self.score = 0.0

    def label(self):
        # type: () -> str
        """One line for a person to choose by."""
        bits = [self.formula or "?"]
        for extra in (self.mineral, self.name):
            if extra and extra.lower() not in bits[0].lower():
                bits.append(extra)
                break
        if self.spacegroup:
            bits.append(self.spacegroup)
        if self.temperature:
            bits.append("{:g} K".format(float(self.temperature)))
        if self.year:
            bits.append(str(self.year))
        if self.computed:
            bits.append("(computed)")
        return "  ".join(bits)

    def filename(self):
        # type: () -> str
        """A file stem worth seeing in the outliner.

        The import names an object after the FILE it came from, so a
        downloaded structure landing in a temp file is called `molom_d2dtna96`
        - which tells you nothing and is indistinguishable from the next one.
        """
        bits = [self.mineral or self.name or self.formula or "structure"]
        if self.source != SOURCE_LOCAL and self.ref:
            bits.append(str(self.ref).rsplit("/", 1)[-1])
        stem = "_".join(bits)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
        return (stem or "structure")[:60]

    def key(self):
        # type: () -> tuple
        """What makes two hits the SAME structure, for favourites and dedupe.

        The provider plus its own reference - a COD id, an OPTIMADE entry url,
        a path on disk. Never the formula or the name: a dozen determinations
        of quartz share both, and COD leaves most entries unnamed anyway
        (round 85).
        """
        return (str(self.source), str(self.ref))

    def to_dict(self):
        # type: () -> dict
        """Everything needed to SHOW this hit again and to fetch it later.

        Deliberately not the CIF itself. A favourite is a bookmark, and
        keeping the file would mean holding a private copy that silently goes
        stale when COD supersedes the entry - the same argument round 84 makes
        for downloading through a temp file rather than caching.
        """
        return {"source": self.source, "ref": self.ref,
                "formula": self.formula, "name": self.name,
                "mineral": self.mineral, "spacegroup": self.spacegroup,
                "cell": list(self.cell) if self.cell else None,
                "temperature": self.temperature, "year": self.year,
                "doi": self.doi, "note": self.note,
                "computed": bool(self.computed)}

    def __repr__(self):
        return "Hit({}, {!r}, {:.2f})".format(self.source, self.ref,
                                              self.score)


def hit_from_dict(data):
    # type: (dict) -> Optional[Hit]
    """Rebuild a saved favourite. Returns None for anything unusable, because
    a stored preference outlives the code that wrote it and a favourites list
    that raises on load is worse than one that has lost an entry."""
    if not isinstance(data, dict) or not data.get("source"):
        return None
    try:
        return Hit(data["source"], data.get("ref"),
                   formula=data.get("formula") or "",
                   name=data.get("name") or "",
                   mineral=data.get("mineral") or "",
                   spacegroup=data.get("spacegroup") or "",
                   cell=data.get("cell") or None,
                   temperature=data.get("temperature"),
                   year=data.get("year"),
                   doi=data.get("doi") or "",
                   note=data.get("note") or "",
                   computed=bool(data.get("computed")))
    except (KeyError, TypeError, ValueError):
        return None


# ------------------------------------------------------------------ ranking
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")


def formula_key(text):
    # type: (str) -> str
    """A formula in a canonical form, so "TiO2" and "O2Ti" are one key.

    Element symbols sorted alphabetically with their counts, which is what
    lets a formula typed in any order match a provider that alphabetises (COD)
    and one that does not (a filename on disk). Counts are kept because TiO2
    and Ti2O3 are different compounds; a missing count means 1, as in every
    chemical formula ever written.

    Anything unparseable returns "", which simply means "do not match on the
    formula" rather than raising - the text may well be a mineral name.
    """
    # COD writes its formulae wrapped in dashes - "- O2 Si -" - and a CIF's
    # `_chemical_formula_sum` is often quoted. Caught by calling the real
    # service: the leading "-" made `formula_key` bail, so every COD hit
    # scored as a name rather than as the exact chemical identity it is.
    text = str(text or "").strip().strip("-").strip().strip("'\"").strip()
    if not text or not text[0].isupper():
        return ""
    from . import elements
    parts = {}
    consumed = 0
    for symbol, count in _FORMULA_TOKEN.findall(text):
        if not symbol:
            continue
        # EVERY token must be a real element, or an acronym parses as one.
        # "DMSO" splits into D, M, S, O - all of which look like symbols, two
        # of which are not - so it was read as a formula, the name resolver
        # was never consulted, and COD was asked for a compound of D and M.
        # That is why "DMSO" found nothing at all while "dimethylsulfoxide"
        # found co-crystals.
        if elements.atomic_number(symbol) <= 0:
            return ""
        consumed += len(symbol) + len(count)
        try:
            parts[symbol] = parts.get(symbol, 0.0) + (float(count)
                                                      if count else 1.0)
        except ValueError:
            return ""
    # If most of the string was not element tokens it is prose, not a formula.
    if not parts or consumed < 0.6 * len(re.sub(r"[\s()\[\]]", "", text)):
        return ""
    return " ".join("{}{:g}".format(k, parts[k]) for k in sorted(parts))


def _tokens(text):
    return [t for t in re.split(r"[^A-Za-z0-9]+", str(text or "").lower()) if t]


def fuzzy(query, candidate):
    # type: (str, str) -> float
    """0..1 similarity, case- and punctuation-insensitive.

    **A WHOLE WORD is what separates a hit from a coincidence**, and that is
    not a refinement - the first real search made it obvious. "ferrocene"
    against a file called `cod_2101932_ferrocene` and against
    "Ferrocenecarboxylic anhydride" both contained the query, so a plain
    substring test scored them identically and the derivative sorted level
    with the thing actually being looked for. The query IS a word of the
    first and only a prefix of the second.

    Coverage - how much of the candidate the query accounts for - is the
    tie-breaker below that, so a short name beats a long one containing it.
    """
    a = " ".join(_tokens(query))
    b = " ".join(_tokens(candidate))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    words = _tokens(candidate)
    query_words = _tokens(query)
    if query_words and all(w in words for w in query_words):
        # Every word of the query is a whole word of the candidate.
        return 0.90 * (len(a) / float(len(b))) ** 0.25
    flat_a, flat_b = a.replace(" ", ""), b.replace(" ", "")
    if flat_a in flat_b:
        return max(0.45, 0.80 * (len(flat_a) / float(len(flat_b))))
    return difflib.SequenceMatcher(None, flat_a, flat_b).ratio()


#: What each field is worth. A formula that canonicalises to the same key is
#: as strong a signal as this search has - it is an exact chemical identity,
#: not a spelling - so it outranks any amount of name similarity.
_EXACT_FORMULA = 1.0
_WEIGHTS = (("mineral", 0.85), ("name", 0.70), ("formula", 0.55))
#: Below this a hit is noise. difflib rates almost any two short words at
#: 0.3-0.4, so anything under a half is a coincidence rather than a match.
MIN_SCORE = 0.50

#: Name similarity at which a name is EVIDENCE rather than a coincidence.
#: Below it a name breaks no ties - see `score_hit`.
_NAME_IS_A_MATCH = 0.70


def score_hit(query, hit, formula=""):
    # type: (str, Hit, str) -> float
    """How well one candidate answers the query, 0..1.

    `formula` is the query RESOLVED to a chemical formula where it was a name
    ("benzoic acid" -> C7H6O2). A formula match is a chemical identity rather
    than a spelling, so it outranks any amount of name similarity - but the
    NAME still breaks ties within it, which matters more than it sounds:
    C8H6O4 is terephthalic acid and also four other isomers, and without the
    name they all score identically.
    """
    key = formula_key(query) or formula_key(formula)
    if key and formula_key(hit.formula) == key:
        # 0.90 floor so any formula match outranks any pure name match (0.85
        # at best), and the remaining 0.10 is a matching NAME breaking the
        # tie between isomers.
        #
        # **Only a GOOD name counts**, and this is not a refinement. COD
        # frequently has no name at all - 5 of its 7 C6H5NO2 entries are
        # unnamed, and one of those is almost certainly the nicotinic acid
        # being looked for. Rewarding weak similarity put a wrongly-named
        # isomer ("2-pyridinecarboxylic acid", fuzzy 0.5) ABOVE an unnamed
        # entry, which is exactly backwards: at equal formula, a name that
        # does not match is no evidence either way, while an absent one is
        # certainly not evidence against.
        named = False
        best_name = 0.0
        for field in ("mineral", "name"):
            value = getattr(hit, field, "")
            if value:
                named = True
                best_name = max(best_name, fuzzy(query, value))
        if best_name >= _NAME_IS_A_MATCH:
            return 0.90 + 0.10 * best_name          # names agree
        if not named:
            # NO name is not evidence against: COD leaves 5 of its 7 C6H5NO2
            # entries unnamed and one of them is the nicotinic acid being
            # looked for. A name that is present and clearly denotes
            # something else IS evidence against, so it sits below this.
            return 0.95
        return 0.90
    best = 0.0
    for field, weight in _WEIGHTS:
        value = getattr(hit, field, "")
        if value:
            best = max(best, weight * fuzzy(query, value))
    return best


def rank(query, hits, minimum=MIN_SCORE, limit=None, formula=""):
    # type: (str, Sequence[Hit], float, Optional[int], str) -> List[Hit]
    """Score, drop the noise, and put the best first.

    Ties break towards a LOCAL hit, because a file already on the machine
    needs no network and is the one the user most likely meant; and then
    towards the newer determination, which is usually the better one.
    """
    scored = []
    for hit in hits:
        hit.score = score_hit(query, hit, formula=formula)
        if hit.score >= minimum:
            scored.append(hit)
    scored.sort(key=lambda h: (-h.score,
                               0 if h.source == SOURCE_LOCAL else 1,
                               -(h.year or 0),
                               h.label()))
    return scored[:limit] if limit else scored


def dedupe(hits):
    """Collapse ONE structure found by more than one provider.

    OPTIMADE serves COD among others, so the same entry arriving twice is the
    common case rather than an edge one, and two rows for one structure is
    confusing rather than reassuring.

    The identity is formula + space group + **the cell, rounded**, because
    that is what actually separates the two cases: one entry served twice has
    the same cell to every decimal, while two redeterminations of quartz have
    the same formula and space group and cells differing in the third - and a
    redetermination is a different structure that must survive as its own row.
    Where a cell is unknown the year and DOI stand in for it, which is weaker
    but is all a provider that omits the cell has given us.

    A LOCAL copy wins any tie: it needs no network, and a file already on the
    machine is very likely the one that was meant.
    """
    out = []
    seen = {}
    for hit in hits:
        cell = ("|".join("{:.3f}".format(float(v)) for v in hit.cell)
                if hit.cell else "{}|{}".format(hit.year or "", hit.doi))
        key = (formula_key(hit.formula) or hit.formula.lower(),
               hit.spacegroup.replace(" ", "").lower(), cell)
        if key not in seen:
            seen[key] = len(out)
            out.append(hit)
        elif (hit.source == SOURCE_LOCAL
              and out[seen[key]].source != SOURCE_LOCAL):
            out[seen[key]] = hit
    return out


# -------------------------------------------------------------- local files
#: How much of a CIF to read when indexing a folder. The tags worth matching
#: on all sit in the header, and a framework CIF runs to megabytes of atom
#: sites nobody is searching by - so reading the whole file would make the
#: one tier that needs no network the slowest of the three.
_LOCAL_HEAD_BYTES = 8192

_TAGS = {
    "_chemical_formula_sum": "formula",
    "_chemical_formula_structural": "formula",
    "_chemical_name_mineral": "mineral",
    "_chemical_name_systematic": "name",
    "_chemical_name_common": "name",
    "_symmetry_space_group_name_h-m": "spacegroup",
    "_space_group_name_h-m_alt": "spacegroup",
}
_CELL_TAGS = ("_cell_length_a", "_cell_length_b", "_cell_length_c",
              "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma")


def _unquote(value):
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    # CIFs write an unknown value as ? and an inapplicable one as . - neither
    # is a name, and showing either in the results would be worse than blank.
    return "" if value in ("?", ".") else value.strip()


def _number(value):
    """A CIF number, with its standard uncertainty dropped: 4.913(2)."""
    text = re.sub(r"\(.*?\)", "", str(value or "")).strip()
    try:
        return float(text)
    except ValueError:
        return None


def index_cif(path, head=None):
    # type: (str, Optional[str]) -> Optional[Hit]
    """One local file as a searchable hit, from its header alone."""
    try:
        if head is None:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(_LOCAL_HEAD_BYTES)
    except OSError:
        return None
    if "_cell_length_a" not in head and "_atom_site" not in head:
        return None                      # not a CIF, whatever it is called
    fields = {}
    cell = {}
    for line in head.splitlines():
        line = line.strip()
        if not line.startswith("_"):
            continue
        parts = line.split(None, 1)
        tag = parts[0].lower()
        value = _unquote(parts[1]) if len(parts) > 1 else ""
        if tag in _TAGS and value and not fields.get(_TAGS[tag]):
            fields[_TAGS[tag]] = value
        elif tag in _CELL_TAGS:
            cell[tag] = _number(value)
    lengths = [cell.get(t) for t in _CELL_TAGS]
    # The FILENAME is searched too, and it is not a fallback: people name
    # their downloads after what they went looking for, so it is often the
    # best label in the file.
    stem = os.path.splitext(os.path.basename(path))[0]
    return Hit(SOURCE_LOCAL, path, formula=fields.get("formula", ""),
               name=fields.get("name", "") or stem.replace("_", " "),
               mineral=fields.get("mineral", ""),
               spacegroup=fields.get("spacegroup", ""),
               cell=tuple(lengths) if all(v is not None for v in lengths)
               else None,
               note=os.path.basename(path))


def search_local(roots, query, limit=PER_SOURCE_LIMIT):
    # type: (Sequence[str], str, int) -> List[Hit]
    """Every .cif under these folders that matches, ranked.

    Walks rather than globs, because a CIF collection is filed in folders by
    project or by paper and a flat listing would miss most of it.
    """
    hits = []
    for root in roots or ():
        if not root or not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            for name in files:
                if not name.lower().endswith((".cif", ".mmcif")):
                    continue
                hit = index_cif(os.path.join(base, name))
                if hit is not None:
                    hits.append(hit)
    return rank(query, hits, limit=limit)


# ------------------------------------------------------------------ network
def http_get(url, timeout=TIMEOUT_S):
    # type: (str, float) -> tuple
    """(status, body). Imported lazily and normalised like the resolver's.

    `resolve._http_get` already does the round-37 work of turning a read
    timeout (a bare `TimeoutError`) and an SSL failure into the one exception
    type callers are written for, and importing it here keeps that in one
    place. The import is INSIDE the function on purpose: `core.resolve` pulls
    in urllib, http.client and email.parser, which round 65 measured at
    ~130 ms of startup for a lookup most sessions never make.
    """
    from . import resolve
    return resolve._http_get(url, timeout=timeout)


def _json(fetch, url, timeout=TIMEOUT_S):
    """Fetch and parse, or raise ValueError with something readable."""
    status, body = (fetch or http_get)(url, timeout)
    if int(status) != 200:
        raise ValueError("HTTP {}".format(status))
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        raise ValueError("not JSON")


# ---------------------------------------------------------------------- COD
COD_BASE = "https://www.crystallography.net/cod"


def cod_cif_url(cod_id):
    # type: (object) -> str
    return "{}/{}.cif".format(COD_BASE, int(cod_id))


def resolve_formula(query, timeout=TIMEOUT_S):
    # type: (str, float) -> str
    """A chemical NAME turned into a formula, or "" if it is not one.

    **This is what makes a search for "benzoic acid" find benzoic acid**, and
    the reason it is needed is that COD's names cannot be trusted to. Measured
    on the live service: a text search for "benzoic acid" returns 2617 rows,
    of which exactly ONE has `chemname` equal to "benzoic acid" - and the pure
    compound's own entries are spelled "benzioc acid", with `chemname` null.
    So every hit was a derivative or a co-crystal whose name happened to
    contain the phrase, which is precisely what Christian reported.

    A formula is not a spelling, so it cannot be mistyped into invisibility.
    `core.resolve` already turns a name into one through OPSIN, PubChem and
    CACTUS - the same cascade Ctrl+Shift+N uses - so this is a use of
    machinery that is already here rather than a fourth service.
    """
    if formula_key(query):
        return ""                     # already a formula
    try:
        from . import resolve
        result = resolve.resolve(query)
    except Exception:                 # noqa: BLE001 - a name we cannot resolve
        return ""
    return str(getattr(result, "formula", "") or "") if getattr(
        result, "ok", False) else ""


def search_cod(query, fetch=None, limit=PER_SOURCE_LIMIT, timeout=TIMEOUT_S,
               formula=""):
    # type: (str, Optional[Callable], int, float, str) -> List[Hit]
    """The Crystallography Open Database, by formula or by text.

    COD's `result.php` takes either a formula or free text and returns JSON
    with `format=json`. A formula is asked for as a formula when the query
    canonicalises as one, because COD matches those exactly and that is a far
    better answer than a text search over the same string; anything else goes
    to the text index, which covers mineral and chemical names.
    """
    # BOTH searches where the query is a name we could resolve, because they
    # answer different questions: the formula finds the pure compound, and
    # the text index finds the mineral names and the co-crystals a formula
    # cannot express. Merged, then ranked against both.
    urls = []
    key = formula_key(query) or formula_key(formula)
    if key:
        # COD writes a formula alphabetically with spaces, which is exactly
        # what `formula_key` produces - minus our explicit "1".
        spaced = " ".join(t[:-1] if t.endswith("1") and not t[-2].isdigit()
                          else t for t in key.split())
        urls.append("{}/result.php?formula={}&format=json".format(
            COD_BASE, _quote(spaced)))
    if not formula_key(query):
        urls.append("{}/result.php?text={}&format=json".format(
            COD_BASE, _quote(query)))
    rows = []
    trouble = None
    for url in urls:
        try:
            payload = _json(fetch, url, timeout)
        except Exception as exc:      # noqa: BLE001 - one query, one failure
            trouble = exc
            continue
        if isinstance(payload, dict):
            payload = payload.get("results") or payload.get("data") or []
        rows.extend(payload or [])
    if not rows and trouble is not None:
        raise trouble
    hits = []
    for row in list(rows)[:PARSE_CEILING]:
        if not isinstance(row, dict):
            continue
        cell = [_number(row.get(k)) for k in ("a", "b", "c",
                                              "alpha", "beta", "gamma")]
        hits.append(Hit(
            SOURCE_COD, row.get("file") or row.get("id"),
            formula=_unquote(row.get("formula")),
            name=_unquote(row.get("commonname") or row.get("chemname")),
            mineral=_unquote(row.get("mineral")),
            spacegroup=_unquote(row.get("sg")),
            cell=tuple(cell) if all(v is not None for v in cell) else None,
            temperature=_number(row.get("celltemp")),
            year=int(_number(row.get("year")))
            if _number(row.get("year")) else None,
            doi=_unquote(row.get("doi")),
            note="COD {}".format(row.get("file") or row.get("id"))))
    # Ranked HERE, so the shortlist this provider contributes is its best and
    # not its first. See `PARSE_CEILING`.
    # NOT deduped here: `search` does it across all providers, and
    # doing it inside one provider collapsed rows that merely share a
    # cell - which within COD can be two different compounds, and cost
    # the correctly-named one.
    return rank(query, hits, limit=limit, formula=formula)


def _quote(text):
    import urllib.parse
    return urllib.parse.quote(str(text or "").strip())


# ----------------------------------------------------------------- OPTIMADE
#: OPTIMADE is a QUERY STANDARD, not a database: many providers implement the
#: same endpoint and filter grammar, so one client reaches all of them.
#:
#: **What calling them showed, and it changes the division of labour.** COD's
#: own OPTIMADE endpoint answers `501 Not Implemented` for a formula filter,
#: so it is NOT listed here - leaving it in would have put a guaranteed
#: failure line in `trouble` on every single search. COD is reached through
#: its own `result.php` instead, which works and also has the text index
#: OPTIMADE has no equivalent of.
#:
#: So in practice this tier is the COMPUTED databases and the COD tier is the
#: EXPERIMENTAL one. That is worth knowing rather than hiding: a DFT-relaxed
#: cell is not a measurement, and a crystallographer must be able to tell at a
#: glance which they are looking at (see `Hit.computed`).
#:
#: Base URLs rather than the provider registry, deliberately:
#: `providers.optimade.org` is one more service that can be down, and being
#: down there would take out the whole tier rather than one member of it -
#: precisely the failure round 37 is about.
OPTIMADE_PROVIDERS = (
    ("Materials Project", "https://optimade.materialsproject.org"),
    ("OQMD", "https://oqmd.org/optimade"),
)

#: OPTIMADE describes STRUCTURES, not literature: there is no mineral name
#: and no common name in the specification, so a text query has nothing to
#: match against and only a formula can be asked for. COD's text index covers
#: the other half, which is the division of labour between the two tiers.
def optimade_filter(query):
    # type: (str) -> str
    """The OPTIMADE filter for this query, or "" if it cannot express it."""
    key = formula_key(query)
    if not key:
        return ""
    # `chemical_formula_reduced` is the spec's canonical form: element symbols
    # in alphabetical order with integer counts, and 1 omitted. Fractional
    # occupancies have no reduced formula, so a solid solution is asked for by
    # its ELEMENTS instead - which is the honest query for one anyway.
    parts = []
    for token in key.split():
        symbol = re.match(r"[A-Za-z]+", token).group(0)
        count = float(token[len(symbol):])
        if abs(count - round(count)) > 1e-9:
            elements = ",".join('"{}"'.format(
                re.match(r"[A-Za-z]+", t).group(0)) for t in key.split())
            return "elements HAS ALL {}".format(elements)
        parts.append("{}{}".format(symbol,
                                   "" if round(count) == 1 else int(count)))
    return 'chemical_formula_reduced="{}"'.format("".join(parts))


def search_optimade(query, fetch=None, providers=OPTIMADE_PROVIDERS,
                    limit=PER_SOURCE_LIMIT, timeout=TIMEOUT_S, trouble=None):
    # type: (str, Optional[Callable], Sequence, int, float, Optional[list]) -> List[Hit]
    """Ask every OPTIMADE provider, and let the ones that answer answer.

    A provider is its own tier for failure purposes: one being down, slow or
    speaking a slightly different dialect must cost that provider and nothing
    else. What went wrong is recorded in `trouble` so the UI can say
    "Materials Project did not answer" instead of silently returning less.
    """
    query_filter = optimade_filter(query)
    if not query_filter:
        return []
    hits = []
    for name, base in providers:
        url = "{}/v1/structures?filter={}&page_limit={}".format(
            base.rstrip("/"), _quote(query_filter), min(int(limit), 50))
        try:
            payload = _json(fetch, url, timeout)
            for entry in (payload.get("data") or [])[:limit]:
                hit = _optimade_hit(name, base, entry)
                if hit is not None:
                    hits.append(hit)
        except Exception as exc:          # noqa: BLE001 - one tier, one failure
            if trouble is not None:
                trouble.append("OPTIMADE/{}: {}".format(name, exc))
    return hits


def _optimade_hit(provider, base, entry):
    if not isinstance(entry, dict):
        return None
    attrs = entry.get("attributes") or {}
    lengths = attrs.get("lattice_vectors")
    cell = None
    if lengths:
        try:
            import numpy as np
            vectors = np.asarray(lengths, dtype=float).reshape(3, 3)
            a, b, c = (float(np.linalg.norm(v)) for v in vectors)
            ang = []
            for i, j in ((1, 2), (0, 2), (0, 1)):
                cosine = (float(np.dot(vectors[i], vectors[j]))
                          / (float(np.linalg.norm(vectors[i]))
                             * float(np.linalg.norm(vectors[j]))))
                ang.append(float(np.degrees(np.arccos(max(-1.0,
                                                          min(1.0, cosine))))))
            cell = (a, b, c, ang[0], ang[1], ang[2])
        except Exception:                 # noqa: BLE001 - a cell is optional
            cell = None
    return Hit(SOURCE_OPTIMADE,
               "{}/v1/structures/{}".format(base.rstrip("/"), entry.get("id")),
               # REDUCED, not descriptive. Materials Project's descriptive
               # formula is the whole cell's - "O96Si48" for a silica - so it
               # never canonicalises to the query and every MP hit scored as
               # a name match on its own id and fell below MIN_SCORE. The
               # first real search returned nothing from MP for "SiO2" and
               # said nothing about why.
               formula=attrs.get("chemical_formula_reduced")
               or attrs.get("chemical_formula_descriptive") or "",
               name=str(entry.get("id") or ""),
               # The SPEC's field, which both providers fill; Hall is the
               # fallback and is what my first draft used alone, so every
               # OPTIMADE hit would have shown a Hall symbol where a
               # crystallographer expects Hermann-Mauguin.
               spacegroup=str(
                   attrs.get("space_group_symbol_hermann_mauguin")
                   or attrs.get("space_group_symbol_hall") or ""),
               cell=cell,
               computed=True,
               note="{} {}".format(provider, entry.get("id")))


# ------------------------------------------------------------- the search
class Results(object):
    """What a search produced, including what went wrong."""

    def __init__(self, query, hits=None, trouble=None, asked=None,
                 formula=""):
        self.query = str(query or "")
        #: The query resolved to a formula, where it was a name. Shown,
        #: because "searched as C7H6O2" explains the results.
        self.formula = str(formula or "")
        self.hits = list(hits or [])
        #: One line per provider that failed, in the user's words rather than
        #: a traceback. A search that finds nothing and says nothing is
        #: indistinguishable from a broken one.
        self.trouble = list(trouble or [])
        self.asked = list(asked or [])

    def __len__(self):
        return len(self.hits)

    def summary(self):
        # type: () -> str
        counts = {}
        for hit in self.hits:
            counts[hit.source] = counts.get(hit.source, 0) + 1
        if not self.hits:
            base = "No structures found for {!r}".format(self.query)
        else:
            base = "{} structure{} for {!r} ({})".format(
                len(self.hits), "" if len(self.hits) == 1 else "s", self.query,
                ", ".join("{} {}".format(counts[k], k)
                          for k in SOURCES if k in counts))
        if self.formula:
            base += ", searched as {}".format(self.formula)
        if self.trouble:
            base += " - {} source{} did not answer".format(
                len(self.trouble), "" if len(self.trouble) == 1 else "s")
        return base


def search(query, roots=(), fetch=None, network=True, limit=None,
           timeout=TIMEOUT_S, providers=OPTIMADE_PROVIDERS):
    # type: (str, Sequence[str], Optional[Callable], bool, Optional[int], float, Sequence) -> Results
    """Ask every tier AT ONCE, merge, dedupe and rank.

    Concurrent rather than cascaded, which is the difference between this and
    `core/resolve.py`: a cascade takes the first answer, and here every tier
    may hold part of the answer - the local copy, COD's mineral names, and
    whatever OPTIMADE's other providers know. Asking them in turn would also
    hide the instant local hit behind a slow remote one.

    **Nothing here can stall the search.** Each tier runs in its own thread
    with its own timeout, a failure is recorded and stepped over, and the
    result is whatever came back - which may be nothing, said out loud.
    """
    query = str(query or "").strip()
    trouble = []      # type: List[str]
    asked = []        # type: List[str]
    collected = []    # type: List[Hit]
    if not query:
        return Results(query, trouble=["nothing to search for"])

    # FIRST, because both remote tiers want it: a chemical name turned into a
    # formula. It is one call to a resolver with its own circuit breaker, and
    # without it a search for "benzoic acid" cannot find benzoic acid (see
    # `resolve_formula`) and OPTIMADE is not asked at all - which is the whole
    # of "I never get other sources than COD".
    formula = resolve_formula(query, timeout=timeout) if network else ""
    search_terms = query if formula_key(query) else (formula or query)

    jobs = [(SOURCE_LOCAL, lambda: search_local(roots, query))]
    if network:
        jobs.append((SOURCE_OPTIMADE,
                     lambda: search_optimade(search_terms, fetch=fetch,
                                             providers=providers,
                                             timeout=timeout,
                                             trouble=trouble)))
        jobs.append((SOURCE_COD,
                     lambda: search_cod(query, fetch=fetch, timeout=timeout,
                                        formula=formula)))

    import threading
    found = {}

    def run(name, job):
        try:
            found[name] = job()
        except Exception as exc:          # noqa: BLE001 - one tier, one failure
            trouble.append("{}: {}".format(name, exc))

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
    for name in asked:
        collected.extend(found.get(name) or [])
        if name not in found and not any(t.startswith(name) for t in trouble):
            trouble.append("{}: timed out".format(name))

    return Results(query,
                   hits=rank(query, dedupe(collected), limit=limit,
                             formula=formula),
                   trouble=trouble, asked=asked, formula=formula)


# --------------------------------------------------------------- fetching
def optimade_cif(entry):
    # type: (dict) -> str
    """An OPTIMADE structure as CIF text.

    **OPTIMADE does not serve CIF** - it serves the structure as JSON, with
    lattice vectors and Cartesian sites - so without this the computed tier
    could be searched and not imported, which is half a feature. Writing a
    minimal P1 CIF instead of building a `Structure` directly means all three
    tiers hand MoloM the same thing and there is one import path, not two.

    P1 with every site listed explicitly, which is what the data IS: OPTIMADE
    gives the full cell contents, not an asymmetric unit, so claiming any
    other space group would be inventing symmetry (round 52's rule - P1 is
    true of every arrangement of atoms).
    """
    import numpy as np
    attrs = (entry or {}).get("attributes") or {}
    vectors = np.asarray(attrs.get("lattice_vectors") or [],
                         dtype=float).reshape(3, 3)
    sites = np.asarray(attrs.get("cartesian_site_positions") or [],
                       dtype=float).reshape(-1, 3)
    species = list(attrs.get("species_at_sites") or [])
    if not len(vectors) or not len(sites) or len(species) != len(sites):
        raise ValueError("incomplete OPTIMADE structure")
    lengths = [float(np.linalg.norm(v)) for v in vectors]
    angles = []
    for i, j in ((1, 2), (0, 2), (0, 1)):
        cosine = (float(np.dot(vectors[i], vectors[j]))
                  / (lengths[i] * lengths[j]))
        angles.append(float(np.degrees(np.arccos(max(-1.0,
                                                     min(1.0, cosine))))))
    frac = sites @ np.linalg.inv(vectors)
    # An OPTIMADE species name can be an alias for a mixed site; the element
    # is on `species`, so it is looked up rather than assumed to be a symbol.
    symbol_of = {}
    for spec in (attrs.get("species") or []):
        chemicals = spec.get("chemical_symbols") or []
        if chemicals:
            symbol_of[spec.get("name")] = str(chemicals[0])
    lines = [
        "data_optimade_{}".format(str(entry.get("id") or "structure")),
        "_cell_length_a    {:.6f}".format(lengths[0]),
        "_cell_length_b    {:.6f}".format(lengths[1]),
        "_cell_length_c    {:.6f}".format(lengths[2]),
        "_cell_angle_alpha {:.4f}".format(angles[0]),
        "_cell_angle_beta  {:.4f}".format(angles[1]),
        "_cell_angle_gamma {:.4f}".format(angles[2]),
        "_symmetry_space_group_name_H-M 'P 1'",
        "loop_",
        "_symmetry_equiv_pos_as_xyz",
        "x,y,z",
        "loop_",
        "_atom_site_label",
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
    ]
    for k, (name, row) in enumerate(zip(species, frac)):
        symbol = symbol_of.get(name, str(name))
        lines.append("{}{} {} {:.6f} {:.6f} {:.6f}".format(
            symbol, k + 1, symbol, row[0], row[1], row[2]))
    return "\n".join(lines) + "\n"


def fetch_cif(hit, fetch=None, timeout=TIMEOUT_S):
    # type: (Hit, Optional[Callable], float) -> str
    """The CIF text behind one hit, whichever tier it came from."""
    if hit.source == SOURCE_LOCAL:
        with open(hit.ref, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if hit.source == SOURCE_COD:
        status, body = (fetch or http_get)(cod_cif_url(hit.ref), timeout)
        if int(status) != 200 or "_cell_length_a" not in body:
            raise ValueError("COD returned no CIF (HTTP {})".format(status))
        return body
    payload = _json(fetch, str(hit.ref), timeout)
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise ValueError("no structure at {}".format(hit.ref))
    return optimade_cif(data)
