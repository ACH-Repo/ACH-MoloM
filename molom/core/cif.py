"""CIF reader that KEEPS the crystallography (UI-free, no dependencies).

OpenBabel already parses .cif, but it hands back a bag of Cartesian atoms —
the cell and the space group are gone, so packing, the asymmetric unit and a
cell box can never be drawn. This module reads the parts that matter:

- the CELL (a, b, c, alpha, beta, gamma) and its fractional->Cartesian matrix,
- the SYMMETRY OPERATIONS as written in the file ("-x+1/2, y, -z"),
- the ASYMMETRIC UNIT (the `_atom_site_*` loop, in fractional coordinates).

`expand()` then applies the operations to get the full cell contents. Keeping
the three separable is the point: the asymmetric unit is what a chemist edits,
the expansion is what they look at, and the cell is what both hang off.

Deliberately hand-rolled: the CIF subset real structures use is small, and a
parser here means no new runtime dependency and offline tests.
"""

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


class CifError(ValueError):
    """Raised when a file is not usable CIF (no cell, no sites, ...)."""


# --------------------------------------------------------------------- cell
class Cell(object):
    """A unit cell. Lengths in Angstrom, angles in DEGREES."""

    def __init__(self, a, b, c, alpha=90.0, beta=90.0, gamma=90.0):
        self.a = float(a)
        self.b = float(b)
        self.c = float(c)
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.gamma = float(gamma)

    def __repr__(self):
        return ("Cell(a={:.4f}, b={:.4f}, c={:.4f}, alpha={:.3f}, "
                "beta={:.3f}, gamma={:.3f})".format(
                    self.a, self.b, self.c, self.alpha, self.beta, self.gamma))

    def to_dict(self):
        return {"a": self.a, "b": self.b, "c": self.c, "alpha": self.alpha,
                "beta": self.beta, "gamma": self.gamma}

    @classmethod
    def from_dict(cls, d):
        # type: (dict) -> Cell
        return cls(d["a"], d["b"], d["c"],
                   d.get("alpha", 90.0), d.get("beta", 90.0),
                   d.get("gamma", 90.0))

    def matrix(self):
        # type: () -> np.ndarray
        """3x3 whose ROWS are the a, b, c vectors in Cartesian space.

        The standard crystallographic setting: **a** along x, **b** in the
        xy plane. `frac @ matrix()` therefore converts a fractional row
        vector to Cartesian.
        """
        al = math.radians(self.alpha)
        be = math.radians(self.beta)
        ga = math.radians(self.gamma)
        cos_al, cos_be, cos_ga = math.cos(al), math.cos(be), math.cos(ga)
        sin_ga = math.sin(ga)
        if abs(sin_ga) < 1e-12:
            raise CifError("degenerate cell: gamma = {}".format(self.gamma))
        cx = self.c * cos_be
        cy = self.c * (cos_al - cos_be * cos_ga) / sin_ga
        cz_sq = self.c * self.c - cx * cx - cy * cy
        if cz_sq <= 0.0:
            raise CifError("cell angles are geometrically impossible: "
                           "{}".format(self))
        return np.array([
            [self.a, 0.0, 0.0],
            [self.b * cos_ga, self.b * sin_ga, 0.0],
            [cx, cy, math.sqrt(cz_sq)],
        ])

    def volume(self):
        # type: () -> float
        return float(abs(np.linalg.det(self.matrix())))

    def to_cartesian(self, frac):
        # type: (np.ndarray) -> np.ndarray
        return np.asarray(frac, dtype=float) @ self.matrix()

    def to_fractional(self, cart):
        # type: (np.ndarray) -> np.ndarray
        return np.asarray(cart, dtype=float) @ np.linalg.inv(self.matrix())

    def corners(self):
        # type: () -> np.ndarray
        """The 8 cell corners in Cartesian space, origin first."""
        f = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
                      [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]],
                     dtype=float)
        return self.to_cartesian(f)

    def edges(self):
        # type: () -> List[Tuple[int, int]]
        """The 12 box edges as index pairs into `corners()`."""
        return [(0, 1), (0, 2), (0, 3), (1, 4), (1, 5), (2, 4),
                (2, 6), (3, 5), (3, 6), (4, 7), (5, 7), (6, 7)]


# ---------------------------------------------------------- symmetry operators
_FRACTION = re.compile(r"^([+-]?\d*\.?\d+)\s*/\s*(\d*\.?\d+)$")


def _term_value(text):
    # type: (str) -> float
    """Numeric factor of one symmetry-operator term: "", "2", "1/2", "/2"."""
    s = text.strip().lstrip("*")
    if not s:
        return 1.0
    if s.startswith("/"):                      # "x/2" -> factor 1/2
        return 1.0 / float(s[1:])
    m = _FRACTION.match(s)
    if m:
        return float(m.group(1)) / float(m.group(2))
    return float(s)


def parse_symop_component(text):
    # type: (str) -> Tuple[float, float, float, float]
    """One component of a symmetry operator -> (cx, cy, cz, constant).

    Handles the spellings that occur in the wild: "x", "-x", "1/2-x",
    "-x+1/2", "0.5+y", "2x", "x/2", "-z".
    """
    s = str(text).strip().lower().replace(" ", "")
    if not s:
        raise CifError("empty symmetry component")
    coef = [0.0, 0.0, 0.0]
    const = 0.0
    for term in re.findall(r"[+-]?[^+-]+", s):
        sign = -1.0 if term.startswith("-") else 1.0
        body = term.lstrip("+-")
        if not body:
            continue
        axis = None
        for i, var in enumerate("xyz"):
            if var in body:
                axis = i
                body = body.replace(var, "", 1)
                break
        if axis is None:
            const += sign * _term_value(body)
        else:
            coef[axis] += sign * _term_value(body)
    return coef[0], coef[1], coef[2], const


class SymOp(object):
    """A crystallographic symmetry operation: frac -> R @ frac + t."""

    def __init__(self, rotation, translation, text=""):
        self.rotation = np.asarray(rotation, dtype=float).reshape(3, 3)
        self.translation = np.asarray(translation, dtype=float).reshape(3)
        self.text = text

    def __repr__(self):
        return "SymOp({!r})".format(self.text or self.as_xyz())

    @classmethod
    def from_xyz(cls, text):
        # type: (str) -> SymOp
        parts = str(text).strip().strip("'\"").split(",")
        if len(parts) != 3:
            raise CifError("symmetry op needs 3 components: {!r}".format(text))
        rot = np.zeros((3, 3))
        trans = np.zeros(3)
        for row, part in enumerate(parts):
            cx, cy, cz, const = parse_symop_component(part)
            rot[row] = (cx, cy, cz)
            trans[row] = const
        return cls(rot, trans, str(text).strip())

    def as_xyz(self):
        # type: () -> str
        out = []
        for row in range(3):
            terms = []
            for col, var in enumerate("xyz"):
                v = self.rotation[row, col]
                if abs(v) < 1e-9:
                    continue
                sign = "-" if v < 0 else ("+" if terms else "")
                mag = "" if abs(abs(v) - 1.0) < 1e-9 else "{:g}".format(abs(v))
                terms.append("{}{}{}".format(sign, mag, var))
            t = self.translation[row]
            if abs(t) > 1e-9:
                terms.append("{}{:g}".format("+" if t > 0 and terms else "", t))
            out.append("".join(terms) or "0")
        return ",".join(out)

    def apply(self, frac):
        # type: (np.ndarray) -> np.ndarray
        f = np.asarray(frac, dtype=float)
        return f @ self.rotation.T + self.translation


IDENTITY = SymOp(np.eye(3), np.zeros(3), "x,y,z")


# ----------------------------------------------------------------- CIF parsing
class CifData(object):
    """What a CIF told us: a cell, the symmetry ops, the asymmetric unit."""

    def __init__(self, cell, symops, symbols, frac, name="",
                 spacegroup="", labels=None, occupancy=None,
                 disorder_groups=None, disorder_assemblies=None):
        self.cell = cell
        self.symops = list(symops)
        self.symbols = list(symbols)
        self.frac = np.asarray(frac, dtype=float).reshape(-1, 3)
        self.name = name
        self.spacegroup = spacegroup
        self.labels = list(labels or symbols)
        #: Site occupancies, 1.0 where the file said nothing. READ and now
        #: also USED (round 38): a disordered structure lists every
        #: alternative, and drawing them all at once superimposes atoms that
        #: are never present together — which then perceives bonds that cannot
        #: exist and makes the whole cell read as a framework.
        self.occupancy = ([float(o) for o in occupancy] if occupancy
                          is not None else [1.0] * len(self.symbols))
        #: `_atom_site_disorder_group` / `_atom_site_disorder_assembly`: the
        #: crystallographer's OWN statement of which alternatives go together.
        #: Believe it when it is there; fall back on geometry when it is not.
        self.disorder_groups = list(disorder_groups
                                    or [""] * len(self.symbols))
        self.disorder_assemblies = list(disorder_assemblies
                                        or [""] * len(self.symbols))

    @property
    def is_disordered(self):
        # type: () -> bool
        return (any(o < 1.0 - 1e-6 for o in self.occupancy)
                or any(g for g in self.disorder_groups))

    @property
    def n_sites(self):
        return len(self.symbols)

    def __repr__(self):
        return "CifData({!r}, {} sites, {} symops, {!r})".format(
            self.name, self.n_sites, len(self.symops), self.spacegroup)


def _strip_esd(value):
    # type: (str) -> float
    """CIF numbers carry a standard uncertainty: "5.4321(12)" -> 5.4321."""
    s = str(value).strip().strip("'\"")
    s = re.sub(r"\(\d+\)$", "", s)
    if s in ("", ".", "?"):
        raise CifError("missing numeric value")
    return float(s)


def _tag_value(value):
    # type: (str) -> str
    """A CIF text field, with the two "no value" markers folded to empty."""
    s = str(value).strip().strip("'\"")
    return "" if s in (".", "?") else s


def _element_from_label(label, type_symbol=None):
    # type: (str, Optional[str]) -> str
    """"C12A" / "Fe1" -> "C" / "Fe". `_atom_site_type_symbol` wins when given,
    minus any charge suffix ("Fe3+")."""
    from . import elements
    for candidate in (type_symbol, label):
        if not candidate:
            continue
        text = str(candidate).strip().strip("'\"")
        text = re.sub(r"[0-9+\-].*$", "", text)     # "Fe3+" / "C12A" -> "Fe"/"C"
        if len(text) >= 2 and elements.atomic_number(text[:2]) > 0:
            return elements.symbol(elements.atomic_number(text[:2]))
        if text and elements.atomic_number(text[:1]) > 0:
            return elements.symbol(elements.atomic_number(text[:1]))
    return ""


def _tokenize_loop_values(lines, start):
    # type: (List[str], int) -> Tuple[List[str], int]
    """Values of a loop body, honouring quotes; stops at the next tag/loop."""
    values = []
    i = start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        low = stripped.lower()
        if stripped.startswith("_") or low.startswith("loop_") \
                or low.startswith("data_"):
            break
        if stripped.startswith(";"):        # multi-line text field
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(";"):
                i += 1
            i += 1
            values.append("")
            continue
        values.extend(re.findall(r"'[^']*'|\"[^\"]*\"|\S+", stripped))
        i += 1
    return values, i


_CELL_TAGS = {
    "_cell_length_a": "a", "_cell_length_b": "b", "_cell_length_c": "c",
    "_cell_angle_alpha": "alpha", "_cell_angle_beta": "beta",
    "_cell_angle_gamma": "gamma",
}
_SYMOP_TAGS = ("_symmetry_equiv_pos_as_xyz",
               "_space_group_symop_operation_xyz",
               "_symmetry_equiv_pos_as_xyz_")
_SPACEGROUP_TAGS = ("_symmetry_space_group_name_h-m",
                    "_space_group_name_h-m_alt",
                    "_symmetry_space_group_name_hall")


def parse_cif(text):
    # type: (str) -> CifData
    """Parse the first data block of a CIF. Raises CifError if unusable."""
    lines = str(text).splitlines()
    cell_vals = {}          # type: Dict[str, float]
    symop_texts = []        # type: List[str]
    spacegroup = ""
    name = ""
    site_cols = {}          # type: Dict[str, List[str]]

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        low = stripped.lower()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if low.startswith("data_") and not name:
            name = stripped[5:].strip()
            i += 1
            continue
        if low.startswith("loop_"):
            tags = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith("_"):
                tags.append(lines[i].strip().split()[0].lower())
                i += 1
            values, i = _tokenize_loop_values(lines, i)
            if not tags:
                continue
            ncol = len(tags)
            rows = len(values) // ncol
            columns = {t: [] for t in tags}
            for r in range(rows):
                for c, tag in enumerate(tags):
                    columns[tag].append(values[r * ncol + c])
            for tag in _SYMOP_TAGS:
                if tag in columns:
                    symop_texts.extend(columns[tag])
            if any(t.startswith("_atom_site") for t in tags):
                for tag, col in columns.items():
                    site_cols.setdefault(tag, col)
            continue
        # plain "_tag value" line
        parts = re.findall(r"'[^']*'|\"[^\"]*\"|\S+", stripped)
        tag = parts[0].lower()
        value = parts[1] if len(parts) > 1 else ""
        if tag in _CELL_TAGS:
            try:
                cell_vals[_CELL_TAGS[tag]] = _strip_esd(value)
            except (CifError, ValueError):
                pass
        elif tag in _SPACEGROUP_TAGS and not spacegroup:
            spacegroup = value.strip("'\"")
        elif tag in _SYMOP_TAGS and value:
            symop_texts.append(value)
        i += 1

    missing = [k for k in ("a", "b", "c") if k not in cell_vals]
    if missing:
        raise CifError(
            "no unit cell in this CIF (missing {})".format(", ".join(missing)))
    cell = Cell(cell_vals["a"], cell_vals["b"], cell_vals["c"],
                cell_vals.get("alpha", 90.0), cell_vals.get("beta", 90.0),
                cell_vals.get("gamma", 90.0))

    fx = site_cols.get("_atom_site_fract_x")
    fy = site_cols.get("_atom_site_fract_y")
    fz = site_cols.get("_atom_site_fract_z")
    if not (fx and fy and fz):
        raise CifError("no fractional atom sites (_atom_site_fract_x/y/z)")
    labels = site_cols.get("_atom_site_label", [""] * len(fx))
    types = site_cols.get("_atom_site_type_symbol", [None] * len(fx))
    occ_col = site_cols.get("_atom_site_occupancy", [])
    group_col = site_cols.get("_atom_site_disorder_group", [])
    assembly_col = site_cols.get("_atom_site_disorder_assembly", [])

    symbols, frac, kept_labels = [], [], []
    occupancy, groups, assemblies = [], [], []
    for k in range(min(len(fx), len(fy), len(fz))):
        try:
            xyz = (_strip_esd(fx[k]), _strip_esd(fy[k]), _strip_esd(fz[k]))
        except (CifError, ValueError):
            continue
        sym = _element_from_label(labels[k] if k < len(labels) else "",
                                  types[k] if k < len(types) else None)
        if not sym:
            continue
        symbols.append(sym)
        frac.append(xyz)
        kept_labels.append(labels[k] if k < len(labels) else sym)
        try:
            occupancy.append(_strip_esd(occ_col[k]) if k < len(occ_col)
                             else 1.0)
        except (CifError, ValueError):
            occupancy.append(1.0)          # "." / "?" means "assume full"
        groups.append(_tag_value(group_col[k]) if k < len(group_col) else "")
        assemblies.append(_tag_value(assembly_col[k])
                          if k < len(assembly_col) else "")
    if not symbols:
        raise CifError("no usable atom sites in this CIF")

    symops = []
    for t in symop_texts:
        t = t.strip().strip("'\"")
        if not t:
            continue
        try:
            symops.append(SymOp.from_xyz(t))
        except (CifError, ValueError):
            continue
    if not symops:
        # No symmetry listed = P1: the file already holds every atom.
        symops = [IDENTITY]
    return CifData(cell, symops, symbols, np.array(frac), name=name,
                   spacegroup=spacegroup, labels=kept_labels,
                   occupancy=occupancy, disorder_groups=groups,
                   disorder_assemblies=assemblies)


# -------------------------------------------------------------------- disorder
#: Draw every alternative at once (what MoloM did until round 38).
POLICY_ALL = "all"
#: Resolve OVERLAPS only: where alternatives sit on top of each other, keep
#: the most occupied one. Everything else is left alone, so a partially
#: occupied guest that overlaps nothing still shows.
POLICY_DOMINANT = "dominant"
#: Dominant, plus drop anything below `MAJOR_THRESHOLD` — "show me the ordered
#: structure", which for a MOF usually means the framework without its
#: disordered guest.
POLICY_MAJOR = "major"
DISORDER_POLICIES = (POLICY_DOMINANT, POLICY_MAJOR, POLICY_ALL)

#: Two atoms closer than this are not both really there. Chosen below every
#: real interatomic distance — the shortest bonds in chemistry are H-F at
#: 0.92 A and an X-ray riding C-H at 0.93 — and above the 0.1 A tolerance the
#: symmetry de-duplication already uses. Alternatives further apart than this
#: are the crystallographer's business to tag, which is what the disorder
#: GROUP columns are for.
DISORDER_RADIUS = 0.8
MAJOR_THRESHOLD = 0.5


def resolve_disorder(symbols, frac, cell, occupancy, groups=None,
                     assemblies=None, policy=POLICY_DOMINANT,
                     radius=DISORDER_RADIUS, threshold=MAJOR_THRESHOLD):
    # type: (list, np.ndarray, Cell, Sequence, Optional[Sequence], Optional[Sequence], str, float, float) -> Tuple[np.ndarray, dict]
    """Which atoms of a DISORDERED structure to actually draw.

    Returns `(keep_mask, report)`. A disordered CIF lists every alternative
    position, so drawing them all superimposes atoms that are never present
    together: `MIL-53-lp.cif` comes out with carbons carrying NINE neighbours
    at 0.11 A, which then perceives bonds that cannot exist and makes the
    whole cell read as one percolating framework. This is the third leg of
    round 38 — bond kinds say where a molecule ENDS, valence sanity says which
    bonds cannot BE, and this says which atoms are not simultaneously there.

    Two mechanisms, deliberately both:

    * the **disorder GROUP** columns, which is the crystallographer's own
      statement of which alternatives belong together — believed when present,
      per assembly, keeping the group carrying the most occupancy;
    * **geometric overlap**, for the (very common) files that carry occupancies
      and no grouping at all. Only a site that overlaps another one is ever
      dropped: a lone partially-occupied site is a real partial site, and a
      half-occupied atom sitting ON a symmetry element is a special position,
      not an alternative.
    """
    n = len(symbols)
    occ = np.asarray([float(o) for o in occupancy], dtype=float) \
        if occupancy is not None else np.ones(n)
    if occ.size != n:
        occ = np.ones(n)
    keep = np.ones(n, dtype=bool)
    report = {"policy": policy, "sites": n, "by_group": 0, "by_overlap": 0,
              "by_threshold": 0, "dropped": 0}
    if policy == POLICY_ALL or n == 0:
        return keep, report
    groups = list(groups or [""] * n)
    assemblies = list(assemblies or [""] * n)

    # 1) the file's own grouping, per assembly
    tagged = [i for i in range(n) if groups[i]]
    if tagged:
        by_assembly = {}
        for i in tagged:
            by_assembly.setdefault(assemblies[i], []).append(i)
        for members in by_assembly.values():
            totals = {}
            for i in members:
                totals[groups[i]] = totals.get(groups[i], 0.0) + occ[i]
            best = max(sorted(totals), key=lambda g: totals[g])
            for i in members:
                if groups[i] != best:
                    keep[i] = False
                    report["by_group"] += 1

    # 2) below the threshold, if asked
    if policy == POLICY_MAJOR:
        low = keep & (occ < float(threshold) - 1e-9)
        report["by_threshold"] = int(low.sum())
        keep &= ~low

    # 3) whatever still overlaps. Highest occupancy first, so the winner of
    # each cluster is picked before it can be dropped by a weaker neighbour.
    if float(radius) > 0 and np.any(occ < 1.0 - 1e-6):
        m = cell.matrix()
        frac = np.asarray(frac, dtype=float).reshape(-1, 3)
        for i in np.argsort(-occ, kind="stable"):
            if not keep[i]:
                continue
            d = frac - frac[i]
            d = d - np.round(d)                     # minimum image
            dist = np.linalg.norm(d @ m, axis=1)
            close = (dist < float(radius)) & keep
            close[i] = False
            # A fully occupied atom is never an "alternative" — if two of
            # those overlap the file is broken in a way this cannot fix, and
            # valence sanity will report it instead.
            close &= occ < 1.0 - 1e-6
            if np.any(close):
                keep &= ~close
                report["by_overlap"] += int(close.sum())
    report["dropped"] = int((~keep).sum())
    report["kept"] = int(keep.sum())
    return keep, report


# -------------------------------------------------------------------- expansion
def expand(data, tol=0.1, wrap=True, whole_molecules=True, boundary=True,
           exterior=0, disorder=POLICY_DOMINANT, report=None):
    # type: (CifData, float, bool, bool, bool, int) -> Tuple[List[str], np.ndarray]
    """Apply every symmetry op to every site -> (symbols, CARTESIAN coords).

    Copies that land on an existing atom (within `tol` Angstrom, measured
    with the minimum-image convention so 0.999 and 0.001 count as touching)
    are dropped — special positions on a symmetry element would otherwise
    produce a pile of duplicate atoms.

    `whole_molecules` then reassembles fragments split by the wrap, so the
    cell shows complete molecules rather than atoms stranded on a far face.

    `boundary` repeats the atoms that lie exactly ON the cell boundary onto
    every equivalent corner, edge and face — see `boundary_images`. It is on
    by default because it is what every crystallography viewer draws, and
    without it rock salt shows a single sodium instead of eight corners.

    `exterior` additionally carries out VESTA's boundary SEARCH for that many
    shells — atoms beyond the box that are bonded to atoms inside it, so a
    chain or a framework runs on instead of ending at the wall. Off by
    default (Christian's call): it changes what an import looks like, and
    nothing that counts cell content should ever see these atoms.

    `disorder` decides what to do with partially occupied sites — see
    `resolve_disorder`. It runs on the EXPANDED atoms, not on the sites,
    because the alternatives are routinely symmetry images of one another
    rather than separate rows in the file. Pass a dict as `report` to be told
    what it did.
    """
    if data.n_sites == 0:
        return [], np.zeros((0, 3))
    matrix = data.cell.matrix()
    symbols = []            # type: List[str]
    fracs = []              # type: List[np.ndarray]
    sites = []              # type: List[int]
    for site in range(data.n_sites):
        base = data.frac[site]
        for op in data.symops:
            f = op.apply(base)
            if wrap:
                f = f - np.floor(f)          # into [0, 1)
            if not _is_new(f, fracs, matrix, tol, wrap):
                continue
            fracs.append(f)
            symbols.append(data.symbols[site])
            sites.append(site)
    if not fracs:
        return [], np.zeros((0, 3))
    out = np.asarray(fracs)
    if disorder != POLICY_ALL and data.is_disordered:
        keep, info = resolve_disorder(
            symbols, out, data.cell,
            [data.occupancy[s] for s in sites],
            [data.disorder_groups[s] for s in sites],
            [data.disorder_assemblies[s] for s in sites],
            policy=disorder)
        if report is not None:
            report["disorder"] = info
        if not keep.all():
            symbols = [s for s, k in zip(symbols, keep) if k]
            out = out[keep]
            sites = [s for s, k in zip(sites, keep) if k]
        if not symbols:
            return [], np.zeros((0, 3))
    if wrap and whole_molecules:
        out = unwrap_molecules(symbols, out, data.cell)
    # The boundary search runs on the CELL CONTENT, so capture it before the
    # boundary copies go on the end — those are duplicates of atoms already
    # present and would only have it search the same faces twice.
    content_symbols, content_frac = list(symbols), out
    if wrap and boundary:
        groups = (fragment_info(symbols, out, data.cell) if whole_molecules
                  else None)
        extra_symbols, extra_frac = boundary_images(symbols, out, groups)
        if extra_symbols:
            symbols = list(symbols) + extra_symbols
            out = np.vstack([out, extra_frac])
    if wrap and int(exterior) > 0:
        ext_symbols, ext_frac = bonded_exterior(
            content_symbols, content_frac, data.cell, depth=int(exterior))
        if ext_symbols:
            symbols = list(symbols) + ext_symbols
            out = np.vstack([out, ext_frac])
    return symbols, out @ matrix


def _is_new(f, fracs, matrix, tol, wrap):
    # type: (np.ndarray, List[np.ndarray], np.ndarray, float, bool) -> bool
    if not fracs:
        return True
    d = np.asarray(fracs) - f[None, :]
    if wrap:
        d = d - np.round(d)                  # minimum image
    return bool(np.min(np.linalg.norm(d @ matrix, axis=1)) > tol)


def periodic_pairs(symbols, frac, cell, slack=0.45, sanity=True, report=None):
    # type: (list, np.ndarray, Cell, float, bool, Optional[dict]) -> Tuple[List[tuple], np.ndarray]
    """Bonded pairs under the MINIMUM IMAGE convention, plus their distances.

    Ordinary bond perception measures straight-line distances, so a molecule
    straddling a cell face comes out cut in half. Here the shortest periodic
    image of each pair is used instead, with Avogadro's covalent criterion —
    and then the same VALENCE SANITY the molecular path applies, because a
    crystal is where impossible contacts actually turn up (a superimposed
    disorder alternative, a badly refined hydrogen, a file with a 0.75 A
    clash). Without it one bad contact fuses four molecules into a chain that
    percolates, and the whole cell then reads as a framework.
    """
    from . import bonding, elements
    n = len(symbols)
    if n == 0:
        return [], np.zeros(0)
    m = cell.matrix()
    radii = np.array([elements.radius_covalent(elements.atomic_number(s))
                      for s in symbols])
    radii[radii <= 0] = 2.0
    pairs, dists = [], []
    for i in range(n):
        d = frac[i + 1:] - frac[i]
        d = d - np.round(d)                        # minimum image
        dist = np.linalg.norm(d @ m, axis=1)
        limit = radii[i + 1:] + radii[i] + slack
        for off in np.nonzero((dist > 0.32) & (dist < limit))[0]:
            pairs.append((i, i + 1 + int(off)))
            dists.append(float(dist[off]))
    dists = np.asarray(dists, dtype=float)
    if sanity and pairs:
        keep, dropped = bonding.prune_pairs(symbols, pairs, dists)
        if report is not None:
            report.setdefault("dropped_bonds", []).extend(dropped)
        pairs = [pairs[k] for k in keep]
        dists = dists[keep] if len(keep) else np.zeros(0)
    return pairs, dists


def periodic_neighbours(symbols, frac, cell, slack=0.45, covalent_only=False,
                        sanity=True):
    # type: (list, np.ndarray, Cell, float, bool, bool) -> List[List[int]]
    """`periodic_pairs` as adjacency lists.

    `covalent_only` drops the metal-ligand bonds, which is how an infinite
    framework becomes a set of finite molecules — see `bonding.bond_kind`.
    Use it for the question "what is a molecule here"; use the full graph for
    "what should be drawn joined", which is not the same question.
    """
    from . import bonding
    n = len(symbols)
    adj = [[] for _ in range(n)]
    pairs, _dists = periodic_pairs(symbols, frac, cell, slack, sanity=sanity)
    for i, j in pairs:
        if covalent_only and bonding.bond_kind(symbols[i],
                                               symbols[j]) != bonding.COVALENT:
            continue
        adj[i].append(j)
        adj[j].append(i)
    return adj


def unwrap_molecules(symbols, frac, cell, tol=1e-3):
    # type: (list, np.ndarray, Cell, float) -> np.ndarray
    """Make every bonded fragment CONTIGUOUS across the cell boundary —
    unless that fragment is a PERIODIC NETWORK, which cannot be.

    Wrapping each atom into [0, 1) on its own strands hydrogens on the far
    face, so a molecular crystal wants its fragments walked back together
    (what CCDC/Mercury show). A FRAMEWORK is the opposite case: its bonded
    component percolates through the boundary and is infinite, so walking it
    marches the structure out across cells forever — MOF-5 came out sprawled
    over 4x2x2 cells instead of filling one.

    The two are told apart while walking: if a bond leads back to an atom
    already placed but demands a DIFFERENT periodic image than the one it
    already has, the component closes on itself through the boundary and is
    therefore periodic. Such a fragment is left plainly wrapped.
    """
    n = len(symbols)
    if n == 0:
        return frac
    adj = periodic_neighbours(symbols, frac, cell)
    wrapped = np.array(frac, dtype=float)
    out = np.array(frac, dtype=float)
    seen = np.zeros(n, dtype=bool)
    for seed in range(n):
        if seen[seed]:
            continue
        seen[seed] = True
        fragment = [seed]
        stack = [seed]
        periodic = False
        while stack:
            i = stack.pop()
            for j in adj[i]:
                d = wrapped[j] - wrapped[i]
                target = out[i] + (d - np.round(d))    # nearest image of j
                if not seen[j]:
                    seen[j] = True
                    out[j] = target
                    fragment.append(j)
                    stack.append(j)
                elif np.any(np.abs(out[j] - target) > tol):
                    # Two different routes to the same atom disagree by a
                    # lattice vector: this component wraps onto itself.
                    periodic = True
        if periodic:
            out[fragment] = wrapped[fragment]          # leave it wrapped
            continue
        # Bring the fragment back so its CENTROID is in [0, 1). The nudge
        # matters: a molecule sitting exactly on a cell face (urea's, by
        # symmetry) has a centroid of exactly 1.0, and whether floor() sees
        # 1.0 or 0.99999 then decides between drawing it inside the box and
        # dumping it outside — which is what made urea's asymmetric unit
        # look like it had been left out of its own unit cell.
        shift = np.floor(out[fragment].mean(axis=0) + 1e-6)
        if np.any(shift):
            out[fragment] -= shift
    return out


def _walk_components(indices, adj, frac, matrix, radii, shifts, tol):
    # type: (Sequence, list, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float) -> List[tuple]
    """[(group, is_periodic), ...] for the components of `indices` under
    `adj`. Shared by the full-connectivity pass and the covalent-only one."""
    wanted = set(int(i) for i in indices)
    placed = np.array(frac, dtype=float)
    seen = set()
    out = []
    for seed in sorted(wanted):
        if seed in seen:
            continue
        seen.add(seed)
        group, stack, periodic = [seed], [seed], False
        while stack:
            i = stack.pop()
            for j in adj[i]:
                if j not in wanted:
                    continue
                d = frac[j] - frac[i]
                target = placed[i] + (d - np.round(d))
                if j not in seen:
                    seen.add(j)
                    placed[j] = target
                    group.append(j)
                    stack.append(j)
                elif np.any(np.abs(placed[j] - target) > tol):
                    periodic = True
        group = sorted(group)
        if not periodic:
            periodic = _touches_own_image(placed[group], radii[group],
                                          matrix, shifts)
        out.append((group, periodic))
    return out


def fragment_info(symbols, frac, cell, tol=1e-3, split_coordination=True):
    # type: (list, np.ndarray, Cell, float, bool) -> List[tuple]
    """[(indices, is_periodic), ...] for each bonded component.

    **A periodic component is then cut at its COORDINATION bonds** (round 38,
    Christian's diagnosis). Mercury knows to stop after the carboxylate
    because a Zn-O bond is coordinative and that is the logical place to cut;
    doing the same here turns MIL-53's one 152-atom infinite component into 8
    linkers, 8 hydroxide bridges, 8 waters and 8 aluminium centres — every one
    finite, and therefore completable at the cell boundary. Rock salt cuts the
    same way into single ions, which is exactly the per-atom completion the
    boundary already wanted.

    The cut is applied ONLY to components that came back periodic. A finite
    metal complex — ferrocene, a paddlewheel with its ligands — is already a
    molecule, and dissecting it would strand the ligands from their metal at
    the boundary. Cut where it is infinite, nowhere else: that is the whole
    hierarchy.

    `is_periodic` marks a component that is INFINITE — a framework, or an
    ionic lattice like rock salt where Na and Cl fall inside the covalent
    criterion. Such a component cannot be "completed" into a molecule; a
    finite one can, and must be, or the cell shows half molecules.

    Two independent tests, because either alone gets a real case wrong:

    * a walk that reaches the same atom by two routes disagreeing by a
      lattice vector (what `unwrap_molecules` uses) — catches MOF-5;
    * whether the component BONDS TO ITS OWN LATTICE IMAGE. Rock salt has
      only two atoms in the cell, so there is no second route to find and
      the walk says "finite" — but Na(0,0,0) is 2.48 A from the Cl of the
      cell next door, which is exactly what makes it a lattice rather than
      an NaCl molecule. Urea's molecule, by contrast, is 2.7 A clear of its
      own image at the nearest approach and only H-bonded to it, which is
      beyond the covalent criterion.
    """
    from . import elements
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    n = len(symbols)
    if n == 0:
        return []
    matrix = cell.matrix()
    radii = np.array([elements.radius_covalent(elements.atomic_number(s))
                      or 2.0 for s in symbols])
    shifts = np.array([[a, b, c] for a in (-1, 0, 1) for b in (-1, 0, 1)
                       for c in (-1, 0, 1)
                       if (a, b, c) != (0, 0, 0)], dtype=float)
    adj = periodic_neighbours(symbols, frac, cell)
    whole = _walk_components(range(n), adj, frac, matrix, radii, shifts, tol)
    if not split_coordination or not any(p for _g, p in whole):
        return whole
    cov_adj = periodic_neighbours(symbols, frac, cell, covalent_only=True)
    out = []
    for group, periodic in whole:
        if not periodic:
            out.append((group, periodic))
            continue
        out.extend(_walk_components(group, cov_adj, frac, matrix, radii,
                                    shifts, tol))
    return out


def _touches_own_image(block, radii, matrix, shifts):
    # type: (np.ndarray, np.ndarray, np.ndarray, np.ndarray) -> bool
    """Does this component bond to a lattice translation of itself?"""
    cart = block @ matrix
    limit = radii[:, None] + radii[None, :] + 0.45
    for shift in shifts:
        other = cart + (shift @ matrix)[None, :]
        d = np.linalg.norm(cart[:, None, :] - other[None, :, :], axis=2)
        if np.any((d > 0.32) & (d < limit)):
            return True
    return False


def fragments(symbols, frac, cell):
    # type: (list, np.ndarray, Cell) -> List[List[int]]
    """Bonded groups of atom indices, using the minimum image."""
    adj = periodic_neighbours(symbols, frac, cell)
    n = len(symbols)
    seen = [False] * n
    out = []
    for seed in range(n):
        if seen[seed]:
            continue
        seen[seed] = True
        group, stack = [seed], [seed]
        while stack:
            i = stack.pop()
            for j in adj[i]:
                if not seen[j]:
                    seen[j] = True
                    group.append(j)
                    stack.append(j)
        out.append(sorted(group))
    return out


def direct_pairs(symbols, frac, cell, pairs, slack=0.45):
    # type: (list, np.ndarray, Cell, Sequence, float) -> List[tuple]
    """Which of `pairs` are adjacent AT THESE COORDINATES, no minimum image.

    The companion to `periodic_neighbours`: that one answers "are these two
    bonded in the crystal", this one answers "may I draw a straight line
    between them right here". They differ for exactly the pairs that meet
    only across a cell face, and drawing those is what put lines clean across
    the box in the symmetry ghosts. `unwrap_molecules` removes the problem for
    any FINITE fragment; a periodic one cannot be unwrapped at all (see
    `fragment_info`), so the drawing side still needs to be able to ask.
    """
    from . import elements
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    pairs = [(int(i), int(j)) for i, j in pairs]
    if not pairs:
        return []
    cart = frac @ cell.matrix()
    radii = np.array([elements.radius_covalent(elements.atomic_number(s))
                      for s in symbols], dtype=float)
    radii[radii <= 0] = 2.0
    out = []
    for i, j in pairs:
        if not (0 <= i < len(cart) and 0 <= j < len(cart)):
            continue
        d = float(np.linalg.norm(cart[i] - cart[j]))
        if 0.32 < d < radii[i] + radii[j] + slack:
            out.append((i, j))
    return out


def boundary_images(symbols, frac, groups=None, tol=1e-4):
    # type: (list, np.ndarray, Optional[list], float) -> Tuple[List[str], np.ndarray]
    """Complete the closed cell [0,1]^3 by repeating what lies ON it.

    A site at a corner, edge or face belongs to every equivalent position of
    the closed box, and that is how crystallography is drawn everywhere
    (Mercury, VESTA, Diamond): rock salt is **eight** sodiums at the corners
    around one chlorine in the middle, not one sodium at one corner. The
    content of the cell is unchanged — Z is still Z — these are the same
    atoms seen from the neighbouring cells, and drawing them is what makes
    the picture read as a repeating structure instead of a lone fragment.

    Whether the ATOM is on the boundary decides IF a copy is made; what gets
    copied is the atom's whole MOLECULE, so the copy is a molecule rather
    than a stray carbon and oxygen floating at the far face with nothing
    attached — which is what urea looked like, its C and O sitting on the x
    face with their NH2 groups left behind on the other side. Both reference
    viewers do this: VESTA draws atoms outside the boundary that are bonded
    to atoms inside it, and Mercury includes a whole molecule when any of its
    atoms falls in the cell.

    A PERIODIC component (a framework, or an ionic lattice like rock salt
    where Na and Cl fall inside the covalent criterion) is infinite and
    cannot be completed, so only the atom itself is copied. That is what
    keeps NaCl at eight corner sodiums instead of sprouting a slab.

    `groups` is `[(indices, is_periodic), ...]` from `fragment_info`; without
    it every atom is treated as its own periodic component, i.e. per-atom.

    Returns the ADDED atoms.
    """
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    if groups is None:
        groups = [([i], True) for i in range(len(frac))]
    member = {}
    for group, periodic in groups:
        for index in group:
            member[index] = (group, periodic)
    out_symbols = []
    out_frac = []
    seen = set()
    for index in range(len(frac)):
        f = frac[index]
        options = []
        for axis in range(3):
            shifts = [0.0]
            if abs(f[axis]) <= tol:
                shifts.append(1.0)
            elif abs(f[axis] - 1.0) <= tol:
                shifts.append(-1.0)
            options.append(shifts)
        group, periodic = member.get(index, ([index], True))
        carried = [index] if periodic else group
        for da in options[0]:
            for db in options[1]:
                for dc in options[2]:
                    if da == 0.0 and db == 0.0 and dc == 0.0:
                        continue
                    delta = np.array([da, db, dc])
                    for k in carried:
                        point = frac[k] + delta
                        key = (k, da, db, dc)
                        if key in seen:
                            continue
                        seen.add(key)
                        out_symbols.append(symbols[k])
                        out_frac.append(point)
    if not out_frac:
        return [], np.zeros((0, 3))
    return out_symbols, np.asarray(out_frac)


def bonded_exterior(symbols, frac, cell, depth=1, slack=0.45, tol=1e-3,
                    dup_tol=0.1, covalent_only=False,
                    finite_only=False):
    # type: (list, np.ndarray, Cell, int, float, float) -> Tuple[List[str], np.ndarray]
    """Atoms OUTSIDE the cell that are bonded to atoms inside it.

    This is VESTA's "search atoms bonded to atoms in the boundary", and it is
    a different operation from `boundary_images`: that one repeats sites lying
    exactly ON a face onto their equivalent faces, which completes the closed
    box but adds nothing beyond it. A chain or a framework does not stop at
    the face — it carries on into the next cell — so with the box alone the
    picture is a set of stubs cut off at the boundary, with the bonds that
    would explain them missing. Christian's side-by-side against VESTA is
    exactly that: MoloM's chains ended at the wall, VESTA's ran on.

    Each shell follows every bond that leaves the current set and materialises
    the periodic image at the far end. `depth` shells are taken; one is enough
    to close every bond that crosses a face, which is what makes the structure
    read as continuous. Deeper is available because a framework's node can sit
    a couple of bonds beyond the wall.

    Returns the ADDED atoms, in fractional coordinates that deliberately lie
    outside [0, 1) — that is the whole point of them. The cell CONTENT is
    untouched, so anything counting Z must keep using `expand(boundary=False)`.

    `covalent_only` and `finite_only` default OFF here, which keeps this the
    round-35 operation: an explicit "show me one more shell", valid on a chain
    or a framework that runs on forever. `BoundaryModifier` turns both ON,
    because an AUTOMATIC closure has a narrower job — completing a molecule
    that a cell face happened to cut — and drawing endless shells of a lattice
    nobody asked about is not that.
    """
    from . import bonding, elements
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    n = len(symbols)
    if n == 0 or int(depth) < 1:
        return [], np.zeros((0, 3))
    m = cell.matrix()
    radii = np.array([elements.radius_covalent(elements.atomic_number(s))
                      for s in symbols])
    radii[radii <= 0] = 2.0
    # The 27 neighbouring images; a bond can only ever reach an adjacent cell
    # for any physical covalent radius against any physical cell edge.
    shifts = np.array([[a, b, c] for a in (-1.0, 0.0, 1.0)
                       for b in (-1.0, 0.0, 1.0) for c in (-1.0, 0.0, 1.0)])
    # Keyed by (base site, integer image) so a copy reached from two different
    # directions is added once. The base atoms are image (0,0,0) by
    # construction — `frac` here is already the unwrapped cell content.
    seen = set((i, 0, 0, 0) for i in range(n))
    start = range(n)
    if finite_only:
        # Only a FINITE fragment can be completed. A periodic component is
        # infinite by definition — a metal lattice, an intermetallic, graphite
        # — so following it outward just draws one more shell of something
        # that never ends, and every shell looks as unfinished as the last.
        # The severed-linker problem is a MOLECULE cut by a face, and this is
        # the same "molecule, unless that is impossible" hierarchy round 38
        # uses everywhere else.
        infinite = set()
        for group, periodic in fragment_info(symbols, frac, cell):
            if periodic:
                infinite.update(group)
        start = [i for i in range(n) if i not in infinite]
        if not start:
            return [], np.zeros((0, 3))
    frontier = [(i, np.zeros(3)) for i in start]
    out_symbols = []          # type: List[str]
    out_frac = []             # type: List[np.ndarray]
    # Positions that already exist, to dedupe against. The (site, image) key
    # above is NOT enough: it assumes every input atom is the (0,0,0) image of
    # its site, which is false the moment the input carries BOUNDARY COPIES —
    # `expand(boundary=True)` puts atoms outside [0,1) by design. Without this
    # a structure with 777 boundary copies grew to 6389 atoms, each copy
    # sprouting its own duplicate shell.
    placed = np.array(frac, dtype=float)
    for _ in range(int(depth)):
        nxt = []
        for site, image in frontier:
            here = frac[site] + image
            # Every image of every base site, vectorised: (n, 27, 3).
            deltas = (frac[:, None, :] + shifts[None, :, :]) - here[None, None, :]
            dist = np.linalg.norm(deltas @ m, axis=2)
            limit = (radii[:, None] + radii[site]) + slack
            hits = np.argwhere((dist > 0.32) & (dist < limit))
            for other, si in hits:
                other = int(other)
                if covalent_only and bonding.bond_kind(
                        symbols[site], symbols[other]) != bonding.COVALENT:
                    # A MOLECULE cut by a cell face is the thing that needs
                    # closing; a coordination bond is where a framework is
                    # SUPPOSED to be cut (round 38). Following those too turns
                    # rock salt's 9-atom cell into 59 and an intermetallic
                    # into a solid shell, for no gain: measured on the real
                    # files, every one of MOF-5's 24 cross-face bonds is a
                    # covalent C-C inside a linker, and every one of NaCl's is
                    # ionic.
                    continue
                new_image = image + shifts[si]
                key = (other, int(round(new_image[0])),
                       int(round(new_image[1])), int(round(new_image[2])))
                if key in seen:
                    continue
                seen.add(key)
                point = frac[other] + new_image
                # Only atoms that actually left the box are "exterior"; an
                # image landing back inside is a duplicate of something the
                # cell already contains.
                if np.all(point > -tol) and np.all(point < 1.0 + tol):
                    continue
                if float(np.min(np.linalg.norm(
                        (placed - point) @ m, axis=1))) < dup_tol:
                    continue          # something is already drawn right here
                placed = np.vstack([placed, point])
                out_symbols.append(symbols[other])
                out_frac.append(point)
                nxt.append((other, new_image))
        frontier = nxt
        if not frontier:
            break
    if not out_frac:
        return [], np.zeros((0, 3))
    return out_symbols, np.asarray(out_frac)


def _contiguous(frac, adj, group, seed):
    # type: (np.ndarray, list, Sequence, int) -> dict
    """{atom: position} for one fragment, walked out from `seed` by the
    minimum image so the piece is whole wherever the cell faces fall."""
    members = set(int(k) for k in group)
    pos = {int(seed): np.array(frac[int(seed)], dtype=float)}
    stack = [int(seed)]
    while stack:
        i = stack.pop()
        for j in adj[i]:
            if j in pos or j not in members:
                continue
            d = frac[j] - frac[i]
            pos[j] = pos[i] + (d - np.round(d))
            stack.append(j)
    return pos


def crossing_fragments(symbols, frac, cell, slack=0.45, dup_tol=0.1):
    # type: (list, np.ndarray, Cell, float, float) -> Tuple[List[str], np.ndarray]
    """Whole MOLECULES on the far side of every bond that crosses a face.

    The shell walk in `bonded_exterior` closes each cut bond with a single
    atom, which leaves a ZIF's imidazolate hanging off the face as three atoms
    of a five-ring — better than a severed stub, still not a molecule. Round
    33 settled this for the boundary copies and the same answer applies here:
    a copy carries its whole fragment, because half a ring is not a thing that
    exists.

    Only FINITE covalent fragments travel (see `fragment_info`): a lattice or
    a covalently infinite chain has no "whole molecule" to bring, and trying
    would just draw another shell of something endless.
    """
    from . import bonding
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    n = len(symbols)
    if n == 0:
        return [], np.zeros((0, 3))
    m = cell.matrix()
    owner = {}
    for group, periodic in fragment_info(symbols, frac, cell):
        if not periodic:
            for i in group:
                owner[i] = group
    if not owner:
        return [], np.zeros((0, 3))
    adj = periodic_neighbours(symbols, frac, cell, slack=slack,
                              covalent_only=True)
    placed = np.array(frac, dtype=float)
    out_symbols, out_frac = [], []
    for i in sorted(owner):
        for j in adj[i]:
            if j not in owner:
                continue
            d = frac[j] - frac[i]
            shift = -np.round(d)
            if not np.any(shift):
                continue              # same cell: this bond is already drawn
            # ASSEMBLE THE FRAGMENT AROUND j FIRST. A fragment that itself
            # straddles the face is stored in pieces — it could not be
            # unwrapped, because the component it belongs to percolates — so
            # translating it rigidly keeps it in pieces and throws the far
            # half TWO cells out, where it hangs in space bonded to nothing.
            local = _contiguous(frac, adj, owner[j], j)
            offset = (frac[j] + shift) - local[j]
            for k, point in local.items():
                point = point + offset
                if float(np.min(np.linalg.norm(
                        (placed - point) @ m, axis=1))) < dup_tol:
                    continue
                placed = np.vstack([placed, point])
                out_symbols.append(symbols[k])
                out_frac.append(point)
    if not out_frac:
        return [], np.zeros((0, 3))
    return out_symbols, np.asarray(out_frac)


def rigid_from_reference(ref, cur):
    # type: (np.ndarray, np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]
    """Kabsch fit: the rotation+translation carrying `ref` onto `cur`.

    This is how the cell box FOLLOWS its molecule. The alternative — hooking
    every transform path (grab, rotate, tumble, align, apply, undo) to move
    the cell too — was rejected: a plain grab moves atom coordinates without
    touching the object's origin, so there is no single frame to hang the
    cell off. Re-deriving the rigid motion from a handful of reference atoms
    each frame is exact for any rigid transform, costs a 3x3 SVD, and updates
    LIVE during a drag because it is computed while painting.

    Returns (R, t) with world = ref @ R.T + t, or None if it cannot be fit.
    """
    ref = np.asarray(ref, dtype=float)
    cur = np.asarray(cur, dtype=float)
    if ref.ndim != 2 or ref.shape != cur.shape or ref.shape[0] < 3:
        return None
    c_ref = ref.mean(axis=0)
    c_cur = cur.mean(axis=0)
    h = (ref - c_ref).T @ (cur - c_cur)
    try:
        u, _s, vt = np.linalg.svd(h)
    except np.linalg.LinAlgError:
        return None
    d = 1.0 if np.linalg.det(vt.T @ u.T) > 0 else -1.0
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return rot, c_cur - rot @ c_ref


def reference_sample(coords, limit=24):
    # type: (np.ndarray, int) -> List[int]
    """Indices of a spread-out sample of atoms to pin the cell frame to.

    Evenly spaced rather than the first N: three atoms of one benzene ring
    are nearly coplanar, and a degenerate reference makes the recovered
    rotation unstable.
    """
    n = len(coords)
    if n <= limit:
        return list(range(n))
    step = n / float(limit)
    return sorted({int(k * step) for k in range(limit)})


def build_view(cell, asym_symbols, asym_frac, symops, mode="cell",
               na=1, nb=1, nc=1, tol=0.1, exterior=0, occupancy=None,
               disorder=POLICY_DOMINANT, report=None):
    # type: (Cell, list, list, list, str, int, int, int, float, int, Optional[Sequence], str, Optional[dict]) -> Tuple[List[str], np.ndarray]
    """The atoms for one crystal display mode, in CARTESIAN coordinates.

    - "asym"     the asymmetric unit exactly as the file lists it
    - "cell"     one full unit cell (every symmetry operator applied)
    - "packing"  an na x nb x nc block of full cells

    `exterior` shells of VESTA-style bonded-outside-the-box atoms are added
    to the cell and packing modes (never to "asym", which is by definition
    the listed sites and nothing else).
    """
    data = CifData(cell, symops, asym_symbols, np.asarray(asym_frac, float),
                   occupancy=occupancy)
    if mode == "asym":
        # The asymmetric unit is BY DEFINITION the listed sites, so no
        # disorder resolution here — but say so, since "asym" is also the mode
        # someone switches to when the cell looks wrong.
        return list(data.symbols), data.frac @ cell.matrix()
    symbols, coords = expand(data, tol=tol, exterior=exterior,
                             disorder=disorder, report=report)
    if mode != "packing":
        return symbols, coords
    offsets = supercell_offsets(cell, na, nb, nc)
    out_syms = []
    blocks = []
    for off in offsets:
        out_syms.extend(symbols)
        blocks.append(coords + off[None, :])
    return out_syms, (np.vstack(blocks) if blocks
                      else np.zeros((0, 3)))


def supercell_offsets(cell, na=1, nb=1, nc=1):
    # type: (Cell, int, int, int) -> np.ndarray
    """Cartesian translations for an na x nb x nc block of cells."""
    m = cell.matrix()
    out = []
    for ia in range(int(max(na, 1))):
        for ib in range(int(max(nb, 1))):
            for ic in range(int(max(nc, 1))):
                out.append(np.array([ia, ib, ic], dtype=float) @ m)
    return np.asarray(out)
