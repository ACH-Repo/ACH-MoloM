"""Measured properties of the compound a molecule IS, on a properties page.

Christian, 2026-08-26: "A properties tab for a regular mol object. An isolated
molecule has properties that can be viewed in a tab analogous to the one for
cifs. When a mol is downloaded through an API search we could fill this tab
with meaningful data about the mol (such as melting point etc.)... I think for
now we should consider making this an add-on."

An add-on for the reason the MOPAC one is (round 73): every line that knows
what PubChem is lives here, and `core/` never learns. What core DOES own is
the storage format (`core/molprops.py`) - if this file owned that, disabling
the add-on would make saved files unreadable and no second add-on could ever
cooperate with the first.

**Melting point is not a number, and finding that out changed the design.**
Measured 2026-08-26: aspirin's full PubChem record is 1.81 MB, its
"Experimental Properties" section 75 kB, and its "Melting Point" section alone
11 kB **containing seven melting points in three unit conventions** - `275 F
(NTP, 1992)`, `138-140` with no unit at all, `135 C (rapid heating)`, `135 C`.
So this page cannot print "the melting point"; it shows up to three values,
each with its source, and says how many more there were. Christian asked for
data that "always cites the source of the info for every item", and with a
spread like that the citation is not decoration - it is the only way to judge
which value to believe.

**A COMPOUND CAN HAVE COMPUTED PROPERTIES AND NO MEASURED ONES**, and the
first cut of this add-on did not know it. Cassipourine (CID 101821144)
answers `PUGVIEW.NotFound` for Experimental Properties and returns a full
16 kB Computed Properties section, so the page reported "no properties" about
an entry that is full of them. Both sections are fetched now, and they are
shown under separate headings because a computed logP and a measured melting
point are different kinds of claim.

**What is NOT stored**: the payload. Only the whitelisted headings, clipped
and capped by `core/molprops.py`, which is what keeps a record in the low
kilobytes where it can ride every undo snapshot and every savefile.

**What an edit does to it**: the record is attached through
`core/attachments.py` as POLICY_FRAGILE, so the existing machinery locks the
object, marks the block stale on a chemistry edit and stops an export
shipping it silently. Fragile rather than volatile because these numbers
describe a COMPOUND IDENTITY rather than a conformer - moving the molecule
cannot invalidate them, and changing an element makes them describe something
else, which is worth SAYING rather than silently discarding.
"""

# Absolute imports, because `core/addons.py` loads an add-on BY PATH under a
# synthetic module name and a relative import cannot resolve without package
# context - round 73 shipped exactly that bug, with all 34 tests passing
# because they imported the module the normal way.
import json
import urllib.error
import urllib.parse

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLayout, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from molom.core import io as io_mod
from molom.core import molprops
from molom.core import molsearch

ADDON = {
    "id": "mol_properties",
    "name": "Compound properties (PubChem)",
    "description": ("Adds a properties page showing what is known about the "
                    "compound a molecule IS - measured values like melting "
                    "point and density, and PubChem's computed ones - "
                    "fetched on demand and stored in a small, fully cited "
                    "form that keeps the two apart."),
    "version": (1, 0),
    "author": "MoloM",
    "api": 1,
}

PAGE_KEY = "compound_properties"
PAGE_GLYPH = "⚗"           # alembic: measured, rather than computed
OP_ID = "compound_properties_fetch"

PUG_VIEW = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/"
            "{}/JSON?heading={}")

#: **BOTH sections are asked for, and this is the round-90b fix.** The first
#: cut asked only for the experimental one, on the reasonable assumption that
#: a compound with a PubChem page has measurements. It does not: Cassipourine
#: (CID 101821144) answers `PUGVIEW.NotFound` for Experimental Properties and
#: returns a full 16 kB Computed Properties section - so the page reported
#: "no properties" about a compound whose PubChem entry is full of them. A
#: natural product with little literature behind it is the ordinary case
#: here, not a corner one.
SECTIONS = ("Experimental+Properties", "Computed+Properties")

SYNONYMS_URL = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
                "{}/synonyms/JSON")

#: PubChem's own heading -> `(our schema key, kind)`. A WHITELIST, not
#: "whatever came back": the two sections run to dozens of headings between
#: them, most of them regulatory, toxicological or bookkeeping, and none of
#: those belong on a structure viewer's properties page.
#:
#: The KIND rides here rather than being inferred from which request the
#: heading arrived in, so a heading is filed correctly however it was found.
HEADINGS = {
    # measured
    "Physical Description": ("physical_description", molprops.KIND_MEASURED),
    "Color/Form": ("color", molprops.KIND_MEASURED),
    "Odor": ("odor", molprops.KIND_MEASURED),
    "Melting Point": ("melting_point", molprops.KIND_MEASURED),
    "Boiling Point": ("boiling_point", molprops.KIND_MEASURED),
    "Flash Point": ("flash_point", molprops.KIND_MEASURED),
    "Density": ("density", molprops.KIND_MEASURED),
    "Solubility": ("solubility", molprops.KIND_MEASURED),
    "Vapor Pressure": ("vapor_pressure", molprops.KIND_MEASURED),
    "Vapor Density": ("vapor_density", molprops.KIND_MEASURED),
    "LogP": ("logp", molprops.KIND_MEASURED),
    "Refractive Index": ("refractive_index", molprops.KIND_MEASURED),
    "Autoignition Temperature": ("autoignition_temperature",
                                 molprops.KIND_MEASURED),
    "Dissociation Constants": ("dissociation_constants",
                               molprops.KIND_MEASURED),
    # computed
    "Molecular Weight": ("molecular_weight", molprops.KIND_COMPUTED),
    "Exact Mass": ("exact_mass", molprops.KIND_COMPUTED),
    "Monoisotopic Mass": ("monoisotopic_mass", molprops.KIND_COMPUTED),
    "XLogP3": ("xlogp3", molprops.KIND_COMPUTED),
    "XLogP3-AA": ("xlogp3", molprops.KIND_COMPUTED),
    "Topological Polar Surface Area": ("tpsa", molprops.KIND_COMPUTED),
    "Hydrogen Bond Donor Count": ("hbond_donors", molprops.KIND_COMPUTED),
    "Hydrogen Bond Acceptor Count": ("hbond_acceptors",
                                     molprops.KIND_COMPUTED),
    "Rotatable Bond Count": ("rotatable_bonds", molprops.KIND_COMPUTED),
    "Heavy Atom Count": ("heavy_atoms", molprops.KIND_COMPUTED),
    "Formal Charge": ("formal_charge", molprops.KIND_COMPUTED),
    "Defined Atom Stereocenter Count": ("stereocentres",
                                        molprops.KIND_COMPUTED),
    "Complexity": ("complexity", molprops.KIND_COMPUTED),
}


# ------------------------------------------------------------------ parsing
def _value_strings(value):
    """The text of one Information block's Value.

    Two shapes in the wild and both are real: `StringWithMarkup` (a list of
    `{"String": ...}`) and `Number` (a list of floats, with an optional
    `Unit`). A parser that handled only the first would silently drop LogP.
    """
    if not isinstance(value, dict):
        return []
    out = []
    # The UNIT is a sibling of the value, not part of it, and it is carried on
    # BOTH shapes: PubChem writes Molecular Weight as the STRING "346.6" with
    # `Unit: g/mol`, so dropping it here prints a bare number and calls it a
    # weight. Experimental values rarely carry one, so this is a no-op there.
    unit = str(value.get("Unit") or "").strip()
    suffix = (" " + unit) if unit else ""
    for entry in value.get("StringWithMarkup") or []:
        text = (entry or {}).get("String")
        if text:
            out.append("{}{}".format(text, suffix))
    for number in value.get("Number") or []:
        out.append("{}{}".format(number, suffix))
    return out


def _sources(payload):
    """`{ReferenceNumber: (SourceName, URL)}` from the record's own table.

    Every PubChem reference carries a real `URL` pointing at the record the
    value came from - the CAMEO datasheet, the HMDB entry, the NIOSH pocket
    guide. A citation you can follow is worth a great deal more than one you
    have to go and search for, so the link is kept and the page makes the
    source name clickable.
    """
    table = {}
    try:
        refs = payload["Record"].get("Reference") or []
    except (KeyError, TypeError, AttributeError):
        return table
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        number, name = ref.get("ReferenceNumber"), ref.get("SourceName")
        if number is not None and name:
            table[number] = (str(name), str(ref.get("URL") or ""))
    return table


def source_urls(payload):
    # type: (dict) -> dict
    """`{source name: URL}` for a whole payload, for `Record.sources`."""
    out = {}
    for name, url in _sources(payload).values():
        if name and url and name not in out:
            out[name] = url
    return out


def _source_for(info, table, kind=molprops.KIND_MEASURED):
    """Who said it - and for a computed value, WHAT said it.

    The two kinds want opposite preferences, which is why this takes the
    kind. A MEASURED value is best cited by the reference table's
    `SourceName`, which is short and consistent ("CAMEO Chemicals", "NIOSH");
    its free-text `Reference` is a whole Merck Index line and only earns its
    place when there is no table entry.

    A COMPUTED value is the other way round. Its table entry says
    **"PubChem"**, which is true and useless - every computed value on the
    page would carry it. The Information block's own citation says
    **"Computed by XLogP3 3.0 (PubChem release 2025.04.14)"**, i.e. WHICH
    MODEL produced the number, and for a value nobody measured that is the
    whole of what a citation is for.

    Found by photographing the page rather than by a test: the first fixture
    for this was captured without its reference table, so the test passed on
    a payload the service does not actually send.
    """
    citation = ""
    for entry in info.get("Reference") or []:
        if entry:
            citation = str(entry)
            break
    name = (table.get(info.get("ReferenceNumber")) or ("", ""))[0]
    if kind == molprops.KIND_COMPUTED:
        return citation or name
    return name or citation


def parse_urls(payload):
    # type: (object) -> dict
    """Just the source table, for callers that also want `parse_pugview`."""
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    return source_urls(payload) if isinstance(payload, dict) else {}


def parse_pugview(payload):
    """PUG-View JSON -> a list of `molprops.Property`.

    Pure: no network, no Qt, and every rule in it is exercised against a
    VERBATIM capture in `tests/data/pubchem_pugview_aspirin.json` rather than
    against a payload written from memory.
    """
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if not isinstance(payload, dict):
        return []
    table = _sources(payload)
    collected = {}          # (key, kind) -> list of Measurement

    def walk(sections):
        for section in sections or []:
            if not isinstance(section, dict):
                continue
            entry = HEADINGS.get(section.get("TOCHeading"))
            if entry:
                for info in section.get("Information") or []:
                    if not isinstance(info, dict):
                        continue
                    source = _source_for(info, table, entry[1])
                    for text in _value_strings(info.get("Value")):
                        collected.setdefault(entry, []).append(
                            molprops.Measurement(text, source))
            walk(section.get("Section"))

    try:
        walk(payload["Record"].get("Section"))
    except (KeyError, TypeError, AttributeError):
        return []
    return [molprops.Property(key, values, kind=kind, extra=max(
        0, len(values) - molprops.MAX_VALUES))
        for (key, kind), values in collected.items()]


# ----------------------------------------------------------------- fetching
#: Above this, deriving a SMILES from the graph stops being cheap (13 ms at
#: 300 atoms, and it grows), and stops being MEANINGFUL long before that - a
#: packed crystal is not a compound with a PubChem entry.
MAX_IDENTIFY_ATOMS = 300


def fetch_properties(cid, fetch=None):
    """PubChem's measured AND computed properties for one CID.

    Returns `(properties, {source name: URL})`.

    Only ever these two HEADINGS, never the whole record: 75 kB and 16 kB
    against 1.81 MB, and the rest of it is not what anybody opened this page
    for.

    **A missing section is an ordinary answer, not a failure.** PubChem
    returns `PUGVIEW.NotFound` with a 404 for a compound that has one section
    and not the other, and that is common rather than exotic - a natural
    product typically has the computed half and nothing measured at all.
    """
    if cid is None:
        return [], {}
    fetch = fetch or molsearch._default_fetch
    found, urls = [], {}
    for heading in SECTIONS:
        try:
            status, body = fetch(PUG_VIEW.format(int(cid), heading))
        except (urllib.error.URLError, TypeError, ValueError):
            continue
        if status != 200 or not body:
            continue
        found.extend(parse_pugview(body))
        urls.update(parse_urls(body))
    return found, urls


def identify(structure):
    # type: (object) -> tuple
    """`(smiles, inchikey, problem)` for a molecule as it is RIGHT NOW.

    **This is what lets the page work on a drawn or edited molecule**, which
    was Christian's ask: "We already have a way to derive the SMILES from a
    structure. Shouldn't it be possible to just use that as an identifier for
    queries? maybe even obtain the inchikey and then do it the most reliable
    way?" - and yes, exactly that. `io.structure_to_smiles` reads the drawn
    GRAPH (atoms, bonds, orders), so it is exact rather than a guess, and
    hashing it gives the same join key a searched compound gets. The app's
    default cubane resolves to CID 136090 this way.

    It also makes the stored record CHECKABLE rather than merely flagged: a
    record whose InChIKey no longer matches the structure is describing a
    different compound, and that can be ASKED instead of remembered.
    """
    if structure is None:
        return "", "", "no molecule"
    if (getattr(structure, "metadata", None) or {}).get("cell"):
        # A crystal is not a compound: its "molecule" is the cell contents,
        # and a SMILES of that means nothing.
        return "", "", "a crystal structure has no single compound identity"
    n = len(getattr(structure, "symbols", ()) or ())
    if not n:
        return "", "", "no atoms"
    if n > MAX_IDENTIFY_ATOMS:
        return "", "", "too large to identify ({} atoms)".format(n)
    smiles, problem = io_mod.structure_to_smiles(
        structure.symbols, structure.bonds,
        int(getattr(structure, "charge", 0) or 0))
    if not smiles:
        return "", "", problem or "could not read this structure"
    key = molsearch.inchikey_for_smiles(smiles)
    if not key:
        return smiles, "", "could not hash this structure"
    return smiles, key, ""


def fetch_synonyms(cid, fetch=None):
    # type: (object, object) -> list
    """A few alternative names.

    Capped hard: PubChem lists 264 synonyms for benzoic acid and 698 for
    aspirin. The first handful are the ones anybody recognises - the common
    name, the CAS number, a trade name or two - and the tail is registry
    noise, so `molprops.MAX_SYNONYMS` takes the top of the list as PubChem
    ranks it.
    """
    if cid is None:
        return []
    fetch = fetch or molsearch._default_fetch
    try:
        data = molsearch._pubchem_json(fetch, SYNONYMS_URL.format(int(cid)))
    except (urllib.error.URLError, TypeError, ValueError):
        return []
    try:
        names = data["InformationList"]["Information"][0]["Synonym"]
    except (TypeError, KeyError, IndexError):
        return []
    return [str(n) for n in names[:molprops.MAX_SYNONYMS]]


def fetch_identity(cid, fetch=None):
    # type: (object, object) -> dict
    """Name, formula and IUPAC name for a CID - one cheap property call."""
    if cid is None:
        return {}
    fetch = fetch or molsearch._default_fetch
    rows = molsearch._properties_for([int(cid)], fetch)
    return rows.get(int(cid), {})


def record_for(structure, fetch=None):
    """Build (or refresh) the record for a structure, from the structure.

    The identity is re-derived every time rather than trusted from the last
    search, so an edited molecule is looked up as what it NOW is. A stored
    CID is reused only while it still describes the structure in front of us.
    """
    smiles, inchikey, problem = identify(structure)
    if problem:
        return None, problem
    stored = molprops.read(structure)
    cid = None
    if stored is not None and stored.cid is not None \
            and stored.describes(inchikey):
        cid = stored.cid
    if cid is None:
        cid = molsearch.cid_for_inchikey(inchikey, fetch=fetch)
    if cid is None:
        return None, "PubChem has no entry for this structure"
    props, urls = fetch_properties(cid, fetch=fetch)
    identity = fetch_identity(cid, fetch=fetch)
    synonyms = fetch_synonyms(cid, fetch=fetch)
    if not props and not identity:
        return None, ("PubChem lists no measured or computed properties for "
                      "CID {}".format(cid))
    import datetime
    filled = molprops.Record(
        name=identity.get("Title") or (stored.name if stored else ""),
        formula=identity.get("MolecularFormula")
        or (stored.formula if stored else ""),
        inchikey=inchikey, cid=cid, smiles=smiles,
        iupac_name=identity.get("IUPACName")
        or (stored.iupac_name if stored else ""),
        properties=props, retrieved=datetime.date.today().isoformat(),
        source="PubChem", sources=urls, synonyms=synonyms)
    return filled, ""


class _PropertiesWorker(QThread):
    """One fetch, off the GUI thread. Unparented and held in
    `dialogs._LIVE_WORKERS` - round 86's crash was a worker QThread parented
    to the widget that started it, destroyed mid-run when the widget went."""

    done = Signal(object, str)

    def __init__(self, structure):
        super().__init__(None)
        self._structure = structure

    def run(self):
        try:
            record, problem = record_for(self._structure)
        except Exception as exc:                        # noqa: BLE001
            record, problem = None, "fetch failed: {}".format(exc)
        self.done.emit(record, problem)


# --------------------------------------------------------------------- page
#: **SCOPED BY OBJECT NAME, and that is not a detail.** A stylesheet set on a
#: widget applies to its CHILDREN too, so `setStyleSheet("background: ...")`
#: on a card painted every label inside it as its own little box - Christian:
#: "Especially having frames for both key and val is overkill." The `#name`
#: selector confines it to the card itself.
_CARD_CSS = ("QFrame#propcard { background: rgba(255, 255, 255, 14); "
             "border-radius: 4px; }")
_SOURCE_CSS = "color: #8fa6c0; font-size: 10px;"
_HINT_CSS = "color: #8fa6c0; font-size: 10px;"
_MORE_CSS = "color: #8fa6c0; font-size: 10px;"
_MORE_HOVER_CSS = "color: #d8e4f0; font-size: 10px; text-decoration: underline;"
#: A hairline between one value-and-source pair and the next, instead of
#: boxing each of them.
_RULE_CSS = "background: rgba(255, 255, 255, 46);"


def _wrapped(label):
    """A label that fills the panel's width and no more.

    A word-wrapped QLabel reports a minimum width based on its content, so a
    long value made the card wider than the dock and the text was clipped
    rather than wrapped. `setMinimumWidth(1)` lets the layout shrink it to the
    space there is; `Minimum` vertical keeps the height it then needs.
    """
    label.setWordWrap(True)
    label.setMinimumWidth(1)
    label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return label


def _selectable(label):
    """Make a label's text selectable AND SAY SO.

    Christian: "I do not like programs that do not allow me to copy paste the
    text that is shown in them. Even worse: You can, but there is no
    highlighting informing you that you can." The affordance is the I-beam
    cursor - it is what every other selectable text in every other program
    uses, and it costs nothing.
    """
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    label.setCursor(Qt.IBeamCursor)
    return label


class _Card(QFrame):
    """A group, boxed once. Christian: "readability would greatly improve from
    more visually distinct segments" - but one frame per GROUP, not per row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("propcard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_CARD_CSS)
        self.setFrameShape(QFrame.NoFrame)
        # A wrapped QLabel's height depends on its width, and a QFrame does
        # not propagate `heightForWidth`, so a card full of wrapped labels can
        # be handed less height than its contents need and draws them on top
        # of one another.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)


class _ClickableLabel(QLabel):
    """Text that behaves like a control: it lights up under the pointer and
    fires on release."""

    clicked = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(_MORE_CSS)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        self.setStyleSheet(_MORE_HOVER_CSS)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(_MORE_CSS)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        # On RELEASE and inside the widget, so a drag away cancels.
        if self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _rule():
    """The separator BETWEEN one value-and-source pair and the next.

    Christian asked for "vertical dashes for separation in between them" -
    read as: stop boxing every value, and mark where one reading ends and the
    next begins. A hairline does that without adding another rectangle to a
    panel that already has one per property.
    """
    line = QFrame()
    line.setFixedHeight(1)
    line.setContentsMargins(0, 0, 0, 0)
    line.setStyleSheet(_RULE_CSS)
    return line


class CompoundPropertiesPage(QWidget):
    """Read-only, cited, and honest about what it does not know."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._obj = None
        self._worker = None
        #: Property keys the reader has asked to see in full. Per page rather
        #: than per molecule: it is a viewing choice, not data.
        self._expanded = set()
        #: `{obj id: (signature, inchikey, problem)}` - see `identity_of`.
        self._identity = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.title)
        self.stale = QLabel("")
        self.stale.setWordWrap(True)
        self.stale.setStyleSheet("color: #e6b478;")
        self.stale.setVisible(False)
        lay.addWidget(self.stale)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.body.setAlignment(Qt.AlignTop)
        lay.addWidget(self.body)
        self.rows = QVBoxLayout()
        lay.addLayout(self.rows)
        row = QHBoxLayout()
        self.fetch_btn = QPushButton("Fetch from PubChem")
        self.fetch_btn.clicked.connect(self.fetch)
        row.addWidget(self.fetch_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.sync(None)

    # ------------------------------------------------------------- refresh
    def _clear_rows(self):
        """Take the old rows out of the hierarchy, then free them.

        `setParent(None)` is not redundant with `deleteLater()`: a deferred
        delete is dispatched on a later pass of the event loop (and NOT by
        `processEvents` at all - round 86), so until then the old widgets are
        still children of this page and still paint, at their old geometry,
        over the new ones. Expanding a property rebuilt the list and left a
        ghost of the previous layout on top of it.
        """
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def identity_of(self, obj):
        """The current structure's InChIKey, cached per object.

        0.93 ms for cubane and 13 ms at 300 atoms, and `sync` runs on every
        selection change - so it is cached against a cheap signature of the
        graph (symbols and bonds) rather than recomputed each time. The cache
        lives on the PAGE, not in metadata: it is derived data, and a savefile
        should not carry it.
        """
        if obj is None:
            return "", "no molecule"
        st = obj.structure
        signature = (len(st.symbols), hash(tuple(st.symbols)),
                     hash(tuple(map(tuple, st.bonds))))
        cached = self._identity.get(obj.id)
        if cached is not None and cached[0] == signature:
            return cached[1], cached[2]
        _smiles, key, problem = identify(st)
        self._identity[obj.id] = (signature, key, problem)
        return key, problem

    def sync(self, obj):
        """Describe the ACTIVE molecule."""
        self._obj = obj
        self._clear_rows()
        self.stale.setVisible(False)
        if obj is None:
            self.title.setText("No molecule selected")
            self.body.setText("Select a molecule to see what is known "
                              "about the compound it is.")
            self.fetch_btn.setEnabled(False)
            return
        record = molprops.read(obj.structure)
        inchikey, problem = self.identity_of(obj)
        self.title.setText(obj.name)
        # THE STRUCTURE decides whether it can be looked up, not whether a
        # search happened to put an identity on it. A molecule drawn by hand
        # or edited beyond recognition is still a molecular graph, and that
        # is all PubChem needs.
        self.fetch_btn.setEnabled(not problem)
        self.fetch_btn.setText("Fetch from PubChem" if record is None
                               else "Fetch again")
        head = []
        if record is not None:
            head.append(record.identity_line())
            if record.iupac_name and record.iupac_name != record.name:
                head.append(record.iupac_name)
            if record.synonyms:
                head.append("Also known as: " + ", ".join(record.synonyms))
            if record.retrieved and record.properties:
                head.append("Retrieved {} from {}".format(
                    record.retrieved, record.source or "PubChem"))
        elif problem:
            head.append("This structure cannot be looked up: {}.".format(
                problem))
        else:
            head.append("Not looked up yet. Press Fetch to ask PubChem what "
                        "this structure is.")
        self.body.setText("\n".join(head))
        if record is not None and problem:
            # The molecule can no longer be read as a compound at all (an
            # over-valent atom, say). The stored values still describe
            # something, and it is not this - which is worth saying, because
            # the alternative is a page of confident numbers about a
            # structure nobody can identify.
            self.stale.setText(
                "These describe {}. This molecule can no longer be "
                "identified: {}.".format(record.name or "another compound",
                                         problem))
            self.stale.setVisible(True)
        elif record is not None and not record.describes(inchikey):
            # ASKED, not remembered. The record carries the InChIKey it was
            # fetched for, so an edit of any kind - through the edit path or
            # not - is caught by comparing it with the structure in front of
            # us. That is why this add-on no longer locks the object or hangs
            # an attachment on it: there is nothing to protect that cannot be
            # re-derived in a second.
            self.stale.setText(
                "These describe {}. This molecule has been edited since and "
                "is now a different compound - press Fetch again.".format(
                    record.name or "another compound"))
            self.stale.setVisible(True)
        if record is None or not record.properties:
            return
        measured = record.of_kind(molprops.KIND_MEASURED)
        if measured:
            self.rows.addWidget(self._heading(
                "Measured", "reported values, each with its source"))
            for prop in measured:
                self.rows.addWidget(self._row(prop, record))
        computed = record.of_kind(molprops.KIND_COMPUTED)
        if computed:
            self.rows.addWidget(self._heading(
                "Computed", "derived from the structure, not measured"))
        for producer, group in self._by_producer(computed):
            if producer:
                # Christian: "If everything is basically calculated by cactvs
                # 3... then there should be a table that just says something
                # like: Simple Computed Properties (Cactvs v. ...) and then
                # list all of them." One card for the group, and the citation
                # BELOW it - "Have the sources also below the groups of
                # keyvals not above."
                self.rows.addWidget(self._compact(group))
                self.rows.addWidget(self._producer_line(producer))
            else:
                for prop in group:
                    self.rows.addWidget(self._row(prop, record))

    @staticmethod
    def _by_producer(properties):
        """Computed properties grouped by the program that produced them.

        A property whose values disagree about their source falls into the ""
        group and keeps per-value citations, which is what every measured
        property does.
        """
        groups = {}
        for prop in properties:
            groups.setdefault(prop.producer(), []).append(prop)
        return sorted(groups.items(), key=lambda kv: kv[0] == "")

    @staticmethod
    def _producer_line(producer):
        """Which program produced the table ABOVE it."""
        label = _selectable(QLabel(producer))
        label.setStyleSheet(_HINT_CSS + " margin-bottom: 6px;")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _heading(title, note):
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 12, 0, 2)
        box.setSpacing(0)
        label = QLabel(title.upper())
        label.setStyleSheet("font-weight: bold; color: #8fa6c0;")
        box.addWidget(label)
        hint = QLabel("<i>{}</i>".format(note))
        hint.setStyleSheet(_HINT_CSS)
        hint.setWordWrap(True)
        box.addWidget(hint)
        return frame

    def _compact(self, properties):
        """A producer's values as one table in ONE frame.

        No box per row and none around the values - the card is the segment,
        and the rows inside it are just rows.
        """
        card = _Card()
        grid = QGridLayout(card)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(0, 1)
        for row, prop in enumerate(properties):
            name = _wrapped(_selectable(QLabel(prop.label)))
            grid.addWidget(name, row, 0)
            value = _selectable(QLabel(prop.summary(limit=1)))
            value.setStyleSheet("font-weight: bold;")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(value, row, 1)
        return card

    def _row(self, prop, record):
        """One measured property in ONE frame: its label, then each value with
        its citation under it, pairs separated by a hairline rather than by a
        box apiece."""
        card = _Card()
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(1)
        label = _selectable(QLabel(prop.label))
        label.setStyleSheet("font-weight: bold;")
        box.addWidget(label)

        expanded = prop.key in self._expanded
        limit = len(prop.values) if expanded else molprops.PREVIEW_VALUES
        shown = prop.values[:limit]
        for index, value in enumerate(shown):
            if index:
                box.addWidget(_rule())
            item = _wrapped(_selectable(QLabel(value.value)))
            box.addWidget(item)
            if value.source:
                box.addWidget(self._citation(value.source, record))

        hidden = max(0, len(prop.values) - limit)
        if hidden:
            more = _ClickableLabel("Show all {} values".format(
                len(prop.values)))
            more.clicked.connect(lambda k=prop.key: self._expand(k))
            box.addWidget(more)
        elif expanded and len(prop.values) > molprops.PREVIEW_VALUES:
            less = _ClickableLabel("Show fewer")
            less.clicked.connect(lambda k=prop.key: self._collapse(k))
            box.addWidget(less)
        if prop.extra:
            note = QLabel("<i>+{} further value{} not stored</i>".format(
                prop.extra, "" if prop.extra == 1 else "s"))
            note.setStyleSheet(_SOURCE_CSS)
            box.addWidget(note)
        return card

    @staticmethod
    def _citation(source, record):
        """The source, on its own line, small, and SHORT.

        Christian: "Allow for line wrapping on long sources, or abbreviate
        them with an acronym if possible. otherwise the side pane needs to be
        expanded very wide to be nicely legible." Most of PubChem's long names
        carry their own acronym - "Hazardous Substances Data Bank (HSDB)" -
        so `molprops.abbreviate_source` takes what the source calls itself and
        the full name goes in the tooltip. One with no acronym wraps instead
        of being truncated.
        """
        url = record.url_for(source)
        short = molprops.abbreviate_source(source)
        label = QLabel('<a style="color:#7fa8d8;" href="{}">{}</a>'.format(
            url, short) if url else short)
        label.setStyleSheet(_SOURCE_CSS)
        _wrapped(label)
        label.setToolTip("{}\n{}".format(source, url) if url else source)
        label.setOpenExternalLinks(bool(url))
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        return label

    def _expand(self, key):
        self._expanded.add(key)
        self.sync(self._obj)

    def _collapse(self, key):
        self._expanded.discard(key)
        self.sync(self._obj)

    # --------------------------------------------------------------- fetch
    def fetch(self):
        if self._obj is None or self._worker is not None:
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")
        from molom.ui import dialogs
        self._worker = dialogs._own_worker(
            _PropertiesWorker(self._obj.structure))
        self._worker.done.connect(self._fetched)
        self._worker.start()

    def _fetched(self, record, problem):
        self._worker = None
        obj = self._obj
        if obj is None:
            return
        if record is None:
            self.fetch_btn.setEnabled(True)
            self.fetch_btn.setText("Fetch from PubChem")
            self.body.setText(problem or "Nothing came back")
            return
        molprops.store(obj.structure, record)
        # NO ATTACHMENT AND NO LOCK any more. Round 90 hung the record off
        # `core/attachments.py` as POLICY_FRAGILE so a chemistry edit would
        # mark it stale, which works and is one more thing to remember.
        # Christian, once the identity could be re-derived: "no need anymore
        # to guard against edits (i think?)" - right, and for a better reason
        # than convenience. An overwrite lock exists to protect something
        # expensive and irreplaceable (round 75's twenty-minute frequency
        # job); this is a web lookup keyed on the structure, so the honest
        # answer to an edit is to NOTICE it (`Record.describes`) and offer to
        # fetch again, not to refuse the edit.
        window = self._window
        if window is not None:
            window.statusBar().showMessage(
                "{} propert{} stored ({} bytes)".format(
                    len(record), "y" if len(record) == 1 else "ies",
                    molprops.estimated_bytes(record)), 8000)
            if hasattr(window, "outliner"):
                window.outliner.sync(window.scene, window.active_id)
        self.sync(obj)


# ----------------------------------------------------------------- add-on
def register(window):
    page = CompoundPropertiesPage(window)
    window.properties.add_page(PAGE_KEY, PAGE_GLYPH,
                               "Compound properties", page)
    window._compound_properties_page = page
    hook = lambda obj: page.sync(obj)
    page._sync_hook = hook
    window.page_sync_hooks.append(hook)
    ops = getattr(window, "ops", None)
    if ops is not None and ops.get(OP_ID) is None:
        ops.register(
            OP_ID, "Compound: fetch properties from PubChem",
            lambda: page.fetch(),
            enabled=lambda ctx: window._active_obj() is not None,
            category="Compute",
            aliases=("melting point", "boiling point", "density",
                     "solubility", "physical properties"))
    page.sync(window._active_obj())


def unregister(window):
    page = getattr(window, "_compound_properties_page", None)
    if page is not None:
        hook = getattr(page, "_sync_hook", None)
        if hook is not None and hook in window.page_sync_hooks:
            window.page_sync_hooks.remove(hook)
        window._compound_properties_page = None
    window.properties.remove_page(PAGE_KEY)
    ops = getattr(window, "ops", None)
    if ops is not None:
        ops.unregister(OP_ID)
