"""Resolve a chemical identifier (name / SMILES / InChI / CAS / InChIKey) to a
SMILES string over public web services — MoloM's "Import by name"
(Ctrl+Shift+N). Vendored from ORCA Workbench (orca_workbench/core/resolve.py,
MIT, same author); keep diffable with upstream.

Web-only and OPTIONAL by design: with no internet, only offline SMILES/InChI
parsing works and everything else returns a graceful error — the feature
degrades, it never crashes. Stdlib urllib + optional RDKit; no extra deps.

Tier order:
  pasted SMILES / InChI   -> RDKit (offline)
  IUPAC name              -> OPSIN web service   (handles novel names PubChem lacks)
  trade/common name, CAS  -> PubChem PUG-REST
  still nothing           -> NIH CACTUS resolver (a different index again)
  miss                    -> PubChem autocomplete ("did you mean ...")

**A dead tier costs you a tier, not the answer.** Every hop is wrapped so an
unreachable service falls through to the next one and is reported as a NOTE on
whatever does answer. That is the whole point of a cascade, and it was broken
for OPSIN until round 37: `opsin.ch.cam.ac.uk` going quiet made every
import-by-name fail outright, even for names PubChem knows perfectly well.

Every web result records provenance (source + retrieval date). The SMILES is
RDKit-sanitised and salt-stripped to one fragment (QM wants a single molecule,
not `drug.HCl`). The HTTP getter is injectable so the whole thing is unit-tested
with no network.
"""

from __future__ import annotations

import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

OPSIN_URL = "https://opsin.ch.cam.ac.uk/opsin/{}.smi"
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest"
#: NIH's Chemical Identifier Resolver. A third INDEPENDENT index — it knows
#: trade names, CAS numbers and systematic names, and it is neither Cambridge
#: nor NCBI, so it is unlikely to be down at the same time as either.
CACTUS_URL = "https://cactus.nci.nih.gov/chemical/structure/{}/smiles"
TIMEOUT = 12
#: OPSIN is tier ONE for a name and it is a small academic service that is
#: sometimes slow or down. Waiting the full timeout before even trying PubChem
#: makes a working lookup feel broken, so its own attempt is kept short.
OPSIN_TIMEOUT = 6

_INCHI = re.compile(r"^InChI=", re.I)
_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_SMILES_CHARS = re.compile(r"^[A-Za-z0-9@+\-\[\]()=#$:/\\.%*]+$")


@dataclass
class Resolution:
    query: str
    smiles: Optional[str] = None        # sanitised, salt-stripped
    raw_smiles: Optional[str] = None    # exactly as the source returned it
    source: Optional[str] = None        # provenance, e.g. "PubChem CID 3672"
    formula: Optional[str] = None
    charge: Optional[int] = None
    retrieved: Optional[str] = None     # ISO date for web sources
    candidates: List[str] = field(default_factory=list)  # did-you-mean / ambiguity
    fragments: List[dict] = field(default_factory=list)  # per-fragment breakdown when
                                      # the resolved structure had >1 component, so the
                                      # UI can offer "which fragment to keep" (e.g. keep
                                      # the metal complex cation, not the counter-ion).
    note: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self):
        return bool(self.smiles) and not self.error

    def provenance(self):
        """One-line provenance string, suitable for Molecule.comment."""
        bits = ["resolved from {!r}".format(self.query)]
        if self.source:
            bits.append("via " + self.source)
        if self.retrieved:
            bits.append("on " + self.retrieved)
        if self.note:
            bits.append("[" + self.note + "]")
        return " ".join(bits)


# ---------------------------------------------------------------- HTTP
def _http_get(url, timeout=TIMEOUT):
    """Return (status_code, body_text). Raises urllib.error.URLError with no network.
    HTTP errors (404 etc.) are returned as (code, body), not raised, so callers
    can branch on them.

    Every other failure is re-raised AS `URLError` on purpose. A read that
    times out raises a bare `TimeoutError` (socket.timeout) rather than a
    URLError, and an SSL failure raises `ssl.SSLError` — both are `OSError`
    subclasses that sail straight through `except urllib.error.URLError` and
    out of the resolver, where every caller in this module is written to
    expect one exception type. One place to normalise beats five places to
    remember.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "molom-resolver/1.0",
                      "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return e.code, ""
    except urllib.error.URLError:
        raise
    except OSError as e:                      # TimeoutError, SSLError, ...
        raise urllib.error.URLError(
            "timed out after {}s".format(timeout)
            if isinstance(e, TimeoutError) else e)


def _reason(e):
    return getattr(e, "reason", e)


# ------------------------------------------------------- circuit breaker
#: A service that just timed out will almost certainly time out again, and
#: paying `OPSIN_TIMEOUT` seconds per lookup to re-learn that makes the whole
#: feature feel broken even though it works. So a failure is remembered and
#: that tier is SKIPPED for a while — the first lookup after an outage starts
#: is slow, the rest are not, and it heals by itself.
DOWN_FOR = 600.0            # seconds
_DOWN = {}                  # service -> monotonic time of the failure


def reset_service_state():
    """Forget every recorded outage (tests, and 'try again now')."""
    _DOWN.clear()


def _is_down(service):
    when = _DOWN.get(service)
    if when is None:
        return False
    import time as _time
    if _time.monotonic() - when > DOWN_FOR:
        _DOWN.pop(service, None)
        return False
    return True


def _mark_down(service, live):
    """Only a REAL network failure trips the breaker. An injected getter is a
    test's business and must not leave state behind for the next test."""
    if live:
        import time as _time
        _DOWN[service] = _time.monotonic()


# ---------------------------------------------------------------- RDKit (optional)
def _rdkit():
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolDescriptors
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")   # quiet the parse-failure spam
        return Chem, rdMolDescriptors
    except ImportError:
        return None, None


# Metal / metalloid symbols, used only to FLAG coordination-complex fragments in
# the fragment chooser (so the user keeps the complex, not the counter-ion). It is
# deliberately NOT used to pick a default — "largest fragment" stays the default,
# because a metal can equally be a spectator counter-ion (e.g. Na+ in an acetate).
_METAL_SYMBOLS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe",
    "Co", "Ni", "Cu", "Zn", "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru",
    "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W",
    "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
}


def sanitize(smiles):
    """RDKit-sanitise + salt-strip to the largest fragment. Returns
    (clean_smiles, formula, charge, n_fragments), or (None, None, None, 0) if
    invalid. Passes the SMILES through unverified if RDKit is unavailable."""
    Chem, desc = _rdkit()
    if Chem is None:
        return smiles, None, None, 1
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, None, None, 0
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    n = len(frags)
    if n > 1:
        mol = max(frags, key=lambda m: m.GetNumHeavyAtoms())
    return (Chem.MolToSmiles(mol), desc.CalcMolFormula(mol),
            Chem.GetFormalCharge(mol), n)


def fragments_of(smiles):
    """Per-fragment breakdown of a (possibly multi-component) SMILES, largest
    heavy-atom count first. Returns [] if RDKit is unavailable or the SMILES won't
    parse. Each item: {smiles, formula, charge, n_heavy, has_metal}. Lets the UI
    offer a 'which fragment to keep' choice instead of silently dropping all but
    the largest — important for coordination complexes where the largest fragment
    can be the counter-ion, not the metal complex."""
    Chem, desc = _rdkit()
    if Chem is None:
        return []
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return []
    out = []
    for f in Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False):
        out.append({
            "smiles": Chem.MolToSmiles(f),
            "formula": desc.CalcMolFormula(f),
            "charge": Chem.GetFormalCharge(f),
            "n_heavy": f.GetNumHeavyAtoms(),
            "has_metal": any(a.GetSymbol() in _METAL_SYMBOLS for a in f.GetAtoms()),
        })
    out.sort(key=lambda d: d["n_heavy"], reverse=True)
    return out


def classify(text):
    """Classify an identifier: 'inchi' | 'inchikey' | 'cas' | 'smiles' | 'name'."""
    t = (text or "").strip()
    if _INCHI.match(t):
        return "inchi"
    if _INCHIKEY.match(t):
        return "inchikey"
    if _CAS.match(t):
        return "cas"
    if t and " " not in t and _SMILES_CHARS.match(t):
        Chem, _ = _rdkit()
        if Chem is not None:
            return "smiles" if Chem.MolFromSmiles(t) is not None else "name"
        return "smiles"   # no RDKit: looks SMILES-ish with no spaces -> assume SMILES
    return "name"


# ---------------------------------------------------------------- resolve
def resolve(query, allow_network=True, get=None, cache=None):
    """Resolve `query` to a SMILES. `get(url)->(status, body)` is injectable for
    tests; `cache` is an optional dict reused across calls."""
    q = (query or "").strip()
    if not q:
        return Resolution(query=query or "", error="empty query")
    if cache is not None and q in cache:
        return cache[q]
    res = _resolve_inner(q, allow_network, get or _http_get)
    if cache is not None and res.ok:
        cache[q] = res
    return res


def _finish(res, raw):
    clean, formula, charge, n = sanitize(raw)
    if clean is None:
        res.error = "got a structure but it failed RDKit parsing: {!r}".format(raw)
        return res
    res.raw_smiles, res.smiles = raw, clean
    res.formula, res.charge = formula, charge
    if n > 1:
        res.fragments = fragments_of(raw)
        res.note = "stripped {} extra fragment(s) (salt/solvent); kept the largest".format(n - 1)
    return res


def _resolve_inner(q, allow_network, get):
    kind = classify(q)

    if kind in ("smiles", "inchi"):
        Chem, _ = _rdkit()
        if kind == "inchi":
            if Chem is None:
                return Resolution(query=q, error="InChI input needs RDKit, which isn't installed")
            mol = Chem.MolFromInchi(q)
            if mol is None:
                return Resolution(query=q, error="RDKit could not parse that InChI")
            return _finish(Resolution(query=q, source="input (InChI)"), Chem.MolToSmiles(mol))
        return _finish(Resolution(query=q, source="input (SMILES)"), q)

    if not allow_network:
        return Resolution(query=q, error="offline: only SMILES/InChI resolve without internet")

    today = datetime.date.today().isoformat()
    trouble = []          # tiers that were unreachable, for the final message
    live = get is _http_get

    # 1) OPSIN for systematic names (offline-resolver power, over HTTP)
    if kind == "name" and not _is_down("opsin"):
        # Only the REAL getter gets the short timeout; an injected one keeps
        # the plain `get(url)` contract the tests are written against.
        opsin_get = get
        if live:
            opsin_get = lambda url: _http_get(url, timeout=OPSIN_TIMEOUT)
        try:
            status, body = opsin_get(OPSIN_URL.format(urllib.parse.quote(q)))
        except urllib.error.URLError as e:
            # FALL THROUGH to PubChem. This used to return, which made a tier
            # ONE outage look like total failure — the whole point of a
            # cascade is that a dead service costs you a tier, not the answer.
            trouble.append("OPSIN unreachable ({})".format(_reason(e)))
            _mark_down("opsin", live)
            status, body = 0, ""
        smi = body.strip()
        if status == 200 and smi and "\n" not in smi:
            return _finish(Resolution(query=q, source="OPSIN web service", retrieved=today), smi)

    # 2) PubChem by name / CAS / InChIKey
    namespace = "inchikey" if kind == "inchikey" else "name"
    try:
        status, body = get("{}/pug/compound/{}/{}/cids/JSON".format(
            PUBCHEM, namespace, urllib.parse.quote(q)))
    except urllib.error.URLError as e:
        trouble.append("PubChem unreachable ({})".format(_reason(e)))
        _mark_down("pubchem", live)
        status, body = 0, ""
    cids = []
    if status == 200:
        try:
            cids = json.loads(body)["IdentifierList"]["CID"]
        except (ValueError, KeyError):
            cids = []
    if cids:
        cid = cids[0]
        smi = _pubchem_smiles(cid, get)
        if smi:
            res = Resolution(query=q, source="PubChem CID {}".format(cid), retrieved=today)
            notes = list(trouble)
            if len(cids) > 1:
                notes.append("{} PubChem hits; used first (CID {}). Others: {}".format(
                    len(cids), cid, ", ".join(str(c) for c in cids[1:6])))
            if notes:
                # A tier that fell over is worth SAYING even when the answer
                # arrived: it explains the pause, and it is the only warning
                # that a systematic name was matched by search rather than
                # parsed.
                res.note = "; ".join(notes)
            return _finish(res, smi)

    # 3) NIH CACTUS — a different index, and the tier that saves a SYSTEMATIC
    # name when OPSIN is down and PubChem's search does not know it.
    try:
        if _is_down("cactus"):
            raise urllib.error.URLError("skipped: it was down a moment ago")
        status, body = get(CACTUS_URL.format(urllib.parse.quote(q, safe="")))
    except urllib.error.URLError as e:
        trouble.append("CACTUS unreachable ({})".format(_reason(e)))
        _mark_down("cactus", live)
        status, body = 0, ""
    if status == 200:
        smi = (body or "").strip().splitlines()[0].strip() if body.strip() \
            else ""
        # It answers a miss with an HTML page, not a 404, so the body has to
        # be checked for actually being a SMILES.
        if smi and _SMILES_CHARS.match(smi):
            res = Resolution(query=q, source="NIH CACTUS resolver",
                             retrieved=today)
            if trouble:
                res.note = "; ".join(trouble)
            return _finish(res, smi)

    # 4) no match -> autocomplete suggestions
    sugg = _autocomplete(q, get)
    msg = "no match for {!r}".format(q)
    if sugg:
        msg += " - did you mean: " + ", ".join(sugg[:5]) + "?"
    if trouble:
        msg += " (" + "; ".join(trouble) + ")"
    return Resolution(query=q, error=msg, candidates=sugg)


def _pubchem_smiles(cid, get):
    """Fetch a stereo-bearing SMILES for a CID. PubChem renamed these properties
    in 2025 (IsomericSMILES -> SMILES; CanonicalSMILES -> ConnectivitySMILES),
    so we try the stereo names in order and take the first that returns a value."""
    for prop in ("IsomericSMILES", "SMILES", "CanonicalSMILES"):
        try:
            status, body = get("{}/pug/compound/cid/{}/property/{}/JSON".format(PUBCHEM, cid, prop))
        except urllib.error.URLError:
            return None
        if status == 200:
            try:
                props = json.loads(body)["PropertyTable"]["Properties"][0]
            except (ValueError, KeyError, IndexError):
                continue
            val = props.get(prop) or props.get("SMILES") or props.get("IsomericSMILES")
            if val:
                return val
    return None


def name_for_smiles(smiles, get=None):
    # type: (str, Optional[callable]) -> Optional[str]
    """Reverse lookup: ask PubChem what a structure is CALLED. Returns a
    common synonym (preferred — "aspirin" beats the IUPAC mouthful) or the
    IUPAC name, or None. Used by "name molecule from its structure", where
    the SMILES came from the drawn graph."""
    get = get or _http_get
    if not (smiles or "").strip():
        return None
    quoted = urllib.parse.quote(smiles, safe="")
    try:
        status, body = get("{}/pug/compound/smiles/{}/synonyms/JSON".format(
            PUBCHEM, quoted))
        if status == 200:
            names = json.loads(body)["InformationList"]["Information"][0] \
                .get("Synonym") or []
            for n in names:                     # skip registry-number noise
                if n and not _CAS.match(n) and not n.isdigit():
                    return n
    except (urllib.error.URLError, ValueError, KeyError, IndexError):
        pass
    try:
        status, body = get(
            "{}/pug/compound/smiles/{}/property/IUPACName/JSON".format(
                PUBCHEM, quoted))
        if status == 200:
            return json.loads(body)["PropertyTable"]["Properties"][0] \
                .get("IUPACName")
    except (urllib.error.URLError, ValueError, KeyError, IndexError):
        pass
    return None


def check_services(get=None):
    """Quick reachability probe for the resolver's web services + RDKit. Returns
    a list of (label, ok, detail) for a 'can Add-by-name work here?' diagnostic.
    Uses a short timeout so a firewalled host fails fast rather than hanging."""
    if get is None:
        def get(url):
            return _http_get(url, timeout=6)
    out = []
    for label, url in (("OPSIN web service", OPSIN_URL.format("benzene")),
                       ("PubChem PUG-REST", "{}/pug/compound/name/water/cids/JSON".format(PUBCHEM)),
                       ("NIH CACTUS resolver", CACTUS_URL.format("benzene"))):
        try:
            status, body = get(url)
            ok = status == 200 and bool((body or "").strip())
            out.append((label, ok, "HTTP {}".format(status)))
        except urllib.error.URLError as e:
            out.append((label, False, "unreachable ({})".format(_reason(e))))
        except Exception as e:
            out.append((label, False, "error: {}".format(e)))
    Chem, _ = _rdkit()
    out.append(("RDKit (2D depiction)", Chem is not None,
                "available" if Chem is not None else "not installed"))
    return out


def _autocomplete(q, get):
    try:
        status, body = get("{}/autocomplete/compound/{}/json?limit=8".format(
            PUBCHEM, urllib.parse.quote(q)))
    except urllib.error.URLError:
        return []
    if status != 200:
        return []
    try:
        return json.loads(body).get("dictionary_terms", {}).get("compound", []) or []
    except ValueError:
        return []
