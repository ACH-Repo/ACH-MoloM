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
from typing import Dict, List, Optional, Tuple

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
                 spacegroup="", labels=None):
        self.cell = cell
        self.symops = list(symops)
        self.symbols = list(symbols)
        self.frac = np.asarray(frac, dtype=float).reshape(-1, 3)
        self.name = name
        self.spacegroup = spacegroup
        self.labels = list(labels or symbols)

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

    symbols, frac, kept_labels = [], [], []
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
                   spacegroup=spacegroup, labels=kept_labels)


# -------------------------------------------------------------------- expansion
def expand(data, tol=0.1, wrap=True, whole_molecules=True):
    # type: (CifData, float, bool, bool) -> Tuple[List[str], np.ndarray]
    """Apply every symmetry op to every site -> (symbols, CARTESIAN coords).

    Copies that land on an existing atom (within `tol` Angstrom, measured
    with the minimum-image convention so 0.999 and 0.001 count as touching)
    are dropped — special positions on a symmetry element would otherwise
    produce a pile of duplicate atoms.

    `whole_molecules` then reassembles fragments split by the wrap, so the
    cell shows complete molecules rather than atoms stranded on a far face.
    """
    if data.n_sites == 0:
        return [], np.zeros((0, 3))
    matrix = data.cell.matrix()
    symbols = []            # type: List[str]
    fracs = []              # type: List[np.ndarray]
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
    if not fracs:
        return [], np.zeros((0, 3))
    out = np.asarray(fracs)
    if wrap and whole_molecules:
        out = unwrap_molecules(symbols, out, data.cell)
    return symbols, out @ matrix


def _is_new(f, fracs, matrix, tol, wrap):
    # type: (np.ndarray, List[np.ndarray], np.ndarray, float, bool) -> bool
    if not fracs:
        return True
    d = np.asarray(fracs) - f[None, :]
    if wrap:
        d = d - np.round(d)                  # minimum image
    return bool(np.min(np.linalg.norm(d @ matrix, axis=1)) > tol)


def periodic_neighbours(symbols, frac, cell, slack=0.45):
    # type: (list, np.ndarray, Cell, float) -> List[List[int]]
    """Adjacency using the MINIMUM IMAGE convention.

    Ordinary bond perception measures straight-line distances, so a molecule
    straddling a cell face comes out cut in half. Here the shortest periodic
    image of each pair is used instead, with Avogadro's covalent criterion.
    """
    from . import elements
    n = len(symbols)
    if n == 0:
        return []
    m = cell.matrix()
    radii = np.array([elements.radius_covalent(elements.atomic_number(s))
                      for s in symbols])
    radii[radii <= 0] = 2.0
    adj = [[] for _ in range(n)]
    for i in range(n):
        d = frac[i + 1:] - frac[i]
        d = d - np.round(d)                        # minimum image
        dist = np.linalg.norm(d @ m, axis=1)
        limit = radii[i + 1:] + radii[i] + slack
        for off in np.nonzero((dist > 0.32) & (dist < limit))[0]:
            j = i + 1 + int(off)
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
        shift = np.floor(out[fragment].mean(axis=0))
        if np.any(shift):
            out[fragment] -= shift
    return out


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
               na=1, nb=1, nc=1, tol=0.1):
    # type: (Cell, list, list, list, str, int, int, int, float) -> Tuple[List[str], np.ndarray]
    """The atoms for one crystal display mode, in CARTESIAN coordinates.

    - "asym"     the asymmetric unit exactly as the file lists it
    - "cell"     one full unit cell (every symmetry operator applied)
    - "packing"  an na x nb x nc block of full cells
    """
    data = CifData(cell, symops, asym_symbols, np.asarray(asym_frac, float))
    if mode == "asym":
        return list(data.symbols), data.frac @ cell.matrix()
    symbols, coords = expand(data, tol=tol)
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
