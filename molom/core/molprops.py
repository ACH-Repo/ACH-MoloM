"""Measured properties of a COMPOUND, stored in a bounded, cited form.

A molecule downloaded by name has a literature behind it - a melting point, a
boiling point, a density, a solubility - and none of it is derivable from the
coordinates. This module says what MoloM is willing to keep of that, and in
what shape. It holds no network code and no Qt: the fetching and the page live
in the `mol_properties` add-on, and this is the FORMAT they agree on.

**The format is in core deliberately, and the reason is not tidiness.** If the
add-on owned the storage layout, disabling it would make saved files
unreadable and no second add-on could ever cooperate with the first. A key and
a schema version cost nothing to keep here and are what make the data outlive
whatever fetched it.

**Why a hard cap, and how big "too big" turned out to be.** Measured against
PubChem, 2026-08-26:

===========================================  ==========
  the full record for aspirin (CID 2244)      1.81 MB
  its "Experimental Properties" section       75 kB
  its "Melting Point" section alone           11 kB
===========================================  ==========

and that last one contains **seven melting points in three unit conventions**
from different sources - `275 F (NTP, 1992)`, `138-140` with no unit at all,
`135 C (rapid heating)`, `135 C`. So there is no such thing as "the melting
point": there is a bag of citations, and any honest presentation of it has to
show more than one value and say where each came from. Hence `Measurement`,
hence `MAX_VALUES`, and hence the fact that a `Property` never carries a bare
number.

The caps are chosen so the worst case is arithmetic rather than hope:
`MAX_PROPERTIES` x `MAX_VALUES` x `MAX_CHARS` is a few kilobytes, which is the
right order for something that rides every undo snapshot and every savefile.
`estimated_bytes` measures a real record and a test pins it.

**What an edit does to it** is not decided here: a property block is attached
through `core/attachments.py` as `POLICY_FRAGILE`, so the existing machinery
locks the object, marks the block stale on a chemistry edit and refuses to let
an export ship it silently. That is the right policy rather than VOLATILE for
Christian's own round-75 reason - you may change an element for a comparison
figure and still want to see where the data came from - and it is exactly
right here for a second reason: these numbers describe a COMPOUND IDENTITY,
not a conformer, so moving the molecule cannot invalidate them and changing an
element makes them describe something else entirely.
"""

import json
import re
from typing import Any, Dict, List, Optional

#: Where a record lives. `Structure.metadata`, so it rides undo snapshots and
#: `.molom` savefiles for free and needs no entry in `Scene.snapshot`'s
#: four-place checklist (round 43's pattern).
METADATA_KEY = "compound_properties"

#: The attachment key, so the lock and the stale marking find it.
ATTACHMENT_KEY = "compound_properties"

#: Bumped when the stored shape changes in a way a reader must notice. A
#: record from a future version is IGNORED rather than guessed at.
#:
#: 2 (round 90b): a property carries its KIND. Version 1 records still read -
#: everything in one was experimental, which is what `KIND_MEASURED` means.
SCHEMA_VERSION = 2

#: **A measured value and a computed one are different claims**, and mixing
#: them is the one thing this page must not do. PubChem keeps them in two
#: separate sections for the same reason, and a compound can easily have one
#: and not the other: Cassipourine (CID 101821144) has a full Computed
#: Properties section and NO experimental one at all.
KIND_MEASURED = "measured"
KIND_COMPUTED = "computed"
KINDS = (KIND_MEASURED, KIND_COMPUTED)

#: Hard caps. See the module docstring - these are the whole answer to "it
#: would have to be limited so it doesn't become too big in the future".
MAX_PROPERTIES = 32

#: How many values are STORED per heading. Raised from 3 in round 90c:
#: Christian, on the "+N further values not stored" line, "It is annoying to
#: know there is more info but now you have no straightforward way of getting
#: it." Keeping them is better than being able to re-fetch them - it works
#: offline, it needs no second round trip, and the whole spread is what the
#: citations are FOR. Aspirin's worst heading has seven.
MAX_VALUES = 8

#: How many are shown before the reader asks for the rest. A display concern,
#: not a storage one - the others are already there, so "show all" expands
#: rather than fetching.
PREVIEW_VALUES = 3

MAX_CHARS = 120

#: Source name -> URL, stored ONCE per record rather than on every value.
#: PubChem's own payload is built that way and for the same reason: one
#: compound cites a dozen sources across fifty values, and repeating a 60
#: character URL on each of them would cost more than the values do.
MAX_SOURCES = 24

#: How many alternative names to keep. PubChem lists **264 synonyms for
#: benzoic acid and 698 for aspirin** (6.6 kB and 16.5 kB), so "show the
#: synonyms" is not an option - the first handful are the ones anybody
#: recognises (the common name, the CAS number, one or two trade names) and
#: the tail is registry noise.
MAX_SYNONYMS = 8

_ACRONYM = re.compile(r"\(([A-Za-z][A-Za-z0-9./-]{1,9}s?)\)\s*$")


def abbreviate_source(name):
    # type: (str) -> str
    """A citation short enough to sit on one line.

    Most of PubChem's long source names CARRY their own acronym - "Hazardous
    Substances Data Bank (HSDB)", "Occupational Safety and Health
    Administration (OSHA)", "ILO-WHO International Chemical Safety Cards
    (ICSCs)" - so there is nothing to invent: take what the source calls
    itself. A name with no parenthesised acronym is returned unchanged rather
    than truncated, because a clipped name is worse than a long one.
    """
    text = " ".join(str(name or "").split())
    match = _ACRONYM.search(text)
    if match and len(match.group(1)) < len(text) - 2:
        return match.group(1)
    # No acronym: a source that introduces itself and then explains itself
    # keeps the introduction. "Haz-Map, Information on Hazardous Chemicals
    # and Occupational Diseases" is Haz-Map; everything past the comma is the
    # subtitle, and it is what pushes the panel wider than the dock.
    head = text.split(",", 1)[0].strip()
    if head and len(head) < len(text):
        return head
    return text

#: The MEASURED headings worth keeping, in the order a page should show them.
#: A whitelist rather than "whatever came back": PubChem's experimental
#: section runs to dozens of headings, most of which are regulatory or
#: toxicological and none of which belong on a structure viewer's properties
#: page.
MEASURED_FIELDS = (
    ("physical_description", "Appearance"),
    ("melting_point", "Melting point"),
    ("boiling_point", "Boiling point"),
    ("density", "Density"),
    ("solubility", "Solubility"),
    ("vapor_pressure", "Vapour pressure"),
    ("logp", "logP"),
    ("vapor_density", "Vapour density"),
    ("refractive_index", "Refractive index"),
    ("flash_point", "Flash point"),
    ("autoignition_temperature", "Autoignition"),
    ("dissociation_constants", "pKa"),
    ("odor", "Odour"),
    ("color", "Colour"),
)

#: The COMPUTED ones. Several of these RDKit could work out locally, and that
#: is not the point: these are PubChem's own values for this CID, each
#: carrying the program that produced it ("Computed by XLogP3 3.0"), which is
#: the same citation discipline the measured half is built on.
COMPUTED_FIELDS = (
    ("molecular_weight", "Molecular weight"),
    ("exact_mass", "Exact mass"),
    ("monoisotopic_mass", "Monoisotopic mass"),
    ("xlogp3", "XLogP3"),
    ("tpsa", "Topological polar surface area"),
    ("hbond_donors", "H-bond donors"),
    ("hbond_acceptors", "H-bond acceptors"),
    ("rotatable_bonds", "Rotatable bonds"),
    ("heavy_atoms", "Heavy atoms"),
    ("formal_charge", "Formal charge"),
    ("stereocentres", "Defined stereocentres"),
    ("complexity", "Complexity"),
)

FIELDS = MEASURED_FIELDS + COMPUTED_FIELDS

FIELD_LABELS = dict(FIELDS)
FIELD_ORDER = [key for key, _label in FIELDS]

#: Which half a key belongs to, so a stored record can be grouped without the
#: producer having to be asked again.
FIELD_KIND = dict(
    [(key, KIND_MEASURED) for key, _l in MEASURED_FIELDS]
    + [(key, KIND_COMPUTED) for key, _l in COMPUTED_FIELDS])


def _clip(text):
    # type: (Any) -> str
    """One value, bounded. Whitespace is collapsed as well as truncated,
    because a PUG-View string routinely carries embedded newlines and would
    otherwise break the one-line xyz comment."""
    flat = " ".join(str(text or "").split())
    return flat[:MAX_CHARS]


class Measurement(object):
    """One reported value AND where it was reported.

    The source is not optional and has no default. Christian asked for a tab
    that "always cites the source of the info for every item", and with seven
    melting points to choose between it is also the only thing that lets a
    reader judge which to believe.
    """

    __slots__ = ("value", "source")

    def __init__(self, value, source=""):
        self.value = _clip(value)
        self.source = _clip(source)

    def to_dict(self):
        return {"value": self.value, "source": self.source}

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        return cls(data.get("value", ""), data.get("source", ""))

    def __repr__(self):
        return "<Measurement {!r} ({})>".format(self.value, self.source or "?")


class Property(object):
    """One heading and the values reported under it.

    `extra` is how many were dropped by `MAX_VALUES`, and it is SHOWN rather
    than silently swallowed - "3 of 7 values" tells a reader that the spread
    is wider than what is on screen, which is the very thing a single
    confidently-printed number would hide.
    """

    __slots__ = ("key", "values", "extra", "kind")

    def __init__(self, key, values=(), extra=0, kind=None):
        self.key = str(key)
        #: Measured or computed. Defaults to whatever the whitelist says the
        #: key is, so a version-1 record (all experimental) reads correctly
        #: and a caller cannot accidentally file a melting point as computed.
        self.kind = str(kind or FIELD_KIND.get(self.key, KIND_MEASURED))
        vals = [v if isinstance(v, Measurement) else Measurement(*v)
                for v in (values or [])]
        self.values = vals[:MAX_VALUES]
        self.extra = max(int(extra or 0), len(vals) - MAX_VALUES)

    @property
    def label(self):
        return FIELD_LABELS.get(self.key, self.key.replace("_", " ").title())

    def summary(self, limit=None):
        # type: (Optional[int]) -> str
        """The first few values on one line, without their sources.

        For a tooltip and for the xyz comment; the page shows the citations
        in full. `limit` defaults to `PREVIEW_VALUES` because a summary that
        printed eight melting points would not be one.
        """
        limit = PREVIEW_VALUES if limit is None else limit
        shown = [v.value for v in self.values[:limit] if v.value]
        text = "; ".join(shown)
        hidden = max(0, len(self.values) - len(shown)) + self.extra
        if hidden:
            text += " (+{} more)".format(hidden)
        return text

    def producer(self):
        # type: () -> str
        """The one source behind this property, or "" where they differ.

        Computed values come in families - everything Cactvs works out,
        everything PubChem's own code does - and a page that repeats the same
        citation on each of eight rows is harder to read than one that states
        it once. A measured property routinely has three different sources
        and correctly answers "".
        """
        names = {v.source for v in self.values if v.source}
        return names.pop() if len(names) == 1 else ""

    def to_dict(self):
        return {"key": self.key, "extra": int(self.extra), "kind": self.kind,
                "values": [v.to_dict() for v in self.values]}

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        return cls(data.get("key", ""),
                   [Measurement.from_dict(v) for v in (data.get("values") or [])],
                   extra=data.get("extra", 0), kind=data.get("kind"))

    def __repr__(self):
        return "<Property {} {}>".format(self.key, self.summary()[:40])


class Record(object):
    """What is known about one compound, bounded and cited.

    The identity half (name, formula, InChIKey, CID) is as important as the
    property half: it is what says WHICH compound these numbers describe, and
    it is what makes the block checkable against the structure it is attached
    to after somebody has edited an atom.
    """

    __slots__ = ("name", "formula", "inchikey", "cid", "smiles", "iupac_name",
                 "properties", "retrieved", "source", "note", "sources",
                 "synonyms")

    def __init__(self, name="", formula="", inchikey="", cid=None, smiles="",
                 iupac_name="", properties=(), retrieved="", source="",
                 note="", sources=None, synonyms=()):
        self.name = _clip(name)
        self.formula = _clip(formula)
        self.inchikey = _clip(inchikey)
        self.cid = cid
        self.smiles = _clip(smiles)
        self.iupac_name = _clip(iupac_name)
        props = [p if isinstance(p, Property) else Property(*p)
                 for p in (properties or [])]
        # MEASURED first, then computed, and within each the whitelist's own
        # order rather than the order they arrived in - so the page reads the
        # same way whichever headings a given compound happens to have, and
        # the more valuable half is at the top.
        props.sort(key=lambda p: (KINDS.index(p.kind) if p.kind in KINDS else 9,
                                  FIELD_ORDER.index(p.key)
                                  if p.key in FIELD_ORDER else 999, p.key))
        self.properties = props[:MAX_PROPERTIES]
        self.retrieved = _clip(retrieved)
        self.source = _clip(source)
        self.note = _clip(note)
        #: `{source name: URL}`. Every PubChem reference carries a real link
        #: to the record it came from, and a citation you can follow is worth
        #: more than one you have to search for.
        table = {}
        for key, url in list((sources or {}).items())[:MAX_SOURCES]:
            name_, link = _clip(key), _clip(url)
            # http(s) ONLY. These strings come from a web service and end up
            # in a clickable link, so anything else - `javascript:`, `file:` -
            # is dropped rather than handed to the user's browser.
            if name_ and link.lower().startswith(("http://", "https://")):
                table[name_] = link
        self.sources = table
        #: Alternative names, most recognisable first. Capped hard - see
        #: `MAX_SYNONYMS`.
        seen, names = set(), []
        for entry in synonyms or []:
            text = _clip(entry)
            low = text.lower()
            if text and low not in seen:
                seen.add(low)
                names.append(text)
            if len(names) >= MAX_SYNONYMS:
                break
        self.synonyms = names

    def __len__(self):
        return len(self.properties)

    def of_kind(self, kind):
        # type: (str) -> list
        """The half of the record that is measured, or the half that is
        computed. The page shows them under separate headings because they
        are different claims."""
        return [p for p in self.properties if p.kind == kind]

    def describes(self, inchikey):
        # type: (str) -> bool
        """Does this record still describe the structure in front of us?

        The honest replacement for a stale FLAG. Round 90 attached the record
        through `core/attachments.py` so that a chemistry edit would MARK it -
        which works, is one more thing to remember, and only catches edits
        that go through the edit path. Once the identity can be re-derived
        from the structure itself (`molsearch.inchikey_for_smiles` on the
        drawn graph), the question can simply be ASKED, and the answer is
        right however the molecule came to be what it is.
        """
        stored = (self.inchikey or "").strip().upper()
        current = str(inchikey or "").strip().upper()
        if not stored or not current:
            return True             # nothing to compare: make no claim
        return stored == current

    def url_for(self, source):
        # type: (str) -> str
        """The link behind a citation, or "" when there is none. Computed
        values have no URL of their own - "Computed by Cactvs 3.4.8.18" is a
        program, not a document."""
        return self.sources.get(_clip(source), "")

    def get(self, key):
        # type: (str) -> Optional[Property]
        for prop in self.properties:
            if prop.key == key:
                return prop
        return None

    def identity_line(self):
        # type: () -> str
        """Who this is, on one line."""
        bits = [b for b in (self.name, self.formula) if b]
        if self.cid is not None:
            bits.append("PubChem CID {}".format(self.cid))
        elif self.inchikey:
            bits.append(self.inchikey)
        return ", ".join(bits)

    def provenance(self):
        # type: () -> str
        """The line that goes into an exported .xyz comment.

        **Provenance only, and that is a deliberate limit rather than
        laziness.** An xyz comment is ONE line, which every other program will
        read; a few hundred characters of melting points in it is how you
        break somebody else's parser. What belongs there is the answer to
        "what is this and where did it come from" - the rest lives in the
        `.molom` savefile, where there is room for it.
        """
        bits = [b for b in (self.name or self.iupac_name, self.formula) if b]
        if self.cid is not None:
            bits.append("PubChem CID {}".format(self.cid))
        if self.inchikey:
            bits.append("InChIKey {}".format(self.inchikey))
        if self.retrieved:
            bits.append("retrieved {}".format(self.retrieved))
        return "; ".join(bits)

    def to_dict(self):
        return {"version": SCHEMA_VERSION, "name": self.name,
                "formula": self.formula, "inchikey": self.inchikey,
                "cid": self.cid, "smiles": self.smiles,
                "iupac_name": self.iupac_name, "retrieved": self.retrieved,
                "source": self.source, "note": self.note,
                "sources": dict(self.sources),
                "synonyms": list(self.synonyms),
                "properties": [p.to_dict() for p in self.properties]}

    @classmethod
    def from_dict(cls, data):
        # type: (Any) -> Optional[Record]
        """Rebuild, or None.

        A record written by a LATER schema version is ignored rather than
        read optimistically: half-understanding a format is how you end up
        showing somebody a melting point that is really a flash point.
        """
        if not isinstance(data, dict):
            return None
        try:
            version = int(data.get("version", 0))
        except (TypeError, ValueError):
            return None
        if version > SCHEMA_VERSION:
            return None
        cid = data.get("cid")
        try:
            cid = int(cid) if cid is not None else None
        except (TypeError, ValueError):
            cid = None
        return cls(name=data.get("name", ""), formula=data.get("formula", ""),
                   inchikey=data.get("inchikey", ""), cid=cid,
                   smiles=data.get("smiles", ""),
                   iupac_name=data.get("iupac_name", ""),
                   properties=[Property.from_dict(p)
                               for p in (data.get("properties") or [])],
                   retrieved=data.get("retrieved", ""),
                   source=data.get("source", ""), note=data.get("note", ""),
                   sources=data.get("sources") or {},
                   synonyms=data.get("synonyms") or ())

    def __repr__(self):
        return "<Record {} {} properties>".format(self.identity_line(),
                                                  len(self.properties))


def estimated_bytes(record):
    # type: (Record) -> int
    """How much a record costs where it is stored.

    Exists so the cap is a MEASUREMENT rather than a claim - see the test that
    pins a real PubChem record against it.
    """
    if record is None:
        return 0
    return len(json.dumps(record.to_dict(), separators=(",", ":")))


# ------------------------------------------------------------------ storage
def read(structure):
    # type: (Any) -> Optional[Record]
    """The record on a structure, or None."""
    meta = getattr(structure, "metadata", None) or {}
    return Record.from_dict(meta.get(METADATA_KEY))


def store(structure, record):
    # type: (Any, Optional[Record]) -> None
    """Attach a record, or remove it with None."""
    meta = getattr(structure, "metadata", None)
    if meta is None:
        meta = {}
        structure.metadata = meta
    if record is None:
        meta.pop(METADATA_KEY, None)
    else:
        meta[METADATA_KEY] = record.to_dict()


def clear(structure):
    # type: (Any) -> None
    store(structure, None)
