"""The central data model: a molecule (or trajectory of frames) with bonds.

UI-free and GL-free. Coordinates are numpy (N, 3) float64 in Angstrom; atoms
are identified by 0-based index everywhere (the same convention as ORCA
Workbench's geomspec/transform modules).
"""

from typing import List, Optional, Tuple

import numpy as np

from . import elements

# (i, j, order) with i < j; order 1..3. Stored sorted for stable lookups.
Bond = Tuple[int, int, int]


class Structure:
    """Atoms + coordinates (1..n frames) + bonds + bookkeeping.

    `coords` always aliases the CURRENT frame's array; mutate through the
    provided methods so frame bookkeeping stays consistent.
    """

    def __init__(self, symbols=None, coords=None, name="", metadata=None):
        # type: (Optional[List[str]], Optional[np.ndarray], str, Optional[dict]) -> None
        self.symbols = list(symbols or [])            # type: List[str]
        n = len(self.symbols)
        arr = (np.asarray(coords, dtype=float).reshape(n, 3)
               if coords is not None else np.zeros((n, 3)))
        self.frames = [arr]                           # type: List[np.ndarray]
        self.current_frame = 0
        self.bonds = []                               # type: List[Bond]
        self.name = name or ""
        self.metadata = dict(metadata or {})
        self.charge = int(self.metadata.get("charge", 0) or 0)
        self.multiplicity = int(self.metadata.get("multiplicity", 1) or 1)

    # ------------------------------------------------------------- factories
    @classmethod
    def from_atoms(cls, atoms, name="", metadata=None):
        # type: (List[Tuple[str, float, float, float]], str, Optional[dict]) -> Structure
        """Build from a list of (symbol, x, y, z) tuples (the IO lingua franca)."""
        symbols = [a[0] for a in atoms]
        coords = np.array([[a[1], a[2], a[3]] for a in atoms], dtype=float) \
            if atoms else np.zeros((0, 3))
        meta = dict(metadata or {})
        if not name:
            name = str(meta.get("name", "") or "")
        return cls(symbols, coords, name=name, metadata=meta)

    @classmethod
    def from_frames(cls, frame_list, name="", metadata=None):
        # type: (List[Tuple[List, Optional[dict]]], str, Optional[dict]) -> Structure
        """Build a trajectory from [(atoms, meta), ...] frames sharing one atom
        list. Frames whose symbols differ from the first frame's are rejected
        by the caller (see io.frames_are_trajectory)."""
        first_atoms, first_meta = frame_list[0]
        s = cls.from_atoms(first_atoms, name=name,
                           metadata=metadata if metadata is not None else first_meta)
        for atoms, _m in frame_list[1:]:
            s.frames.append(np.array([[a[1], a[2], a[3]] for a in atoms],
                                     dtype=float))
        return s

    # ------------------------------------------------------------ properties
    @property
    def n_atoms(self):
        # type: () -> int
        return len(self.symbols)

    @property
    def n_frames(self):
        # type: () -> int
        return len(self.frames)

    @property
    def coords(self):
        # type: () -> np.ndarray
        return self.frames[self.current_frame]

    @coords.setter
    def coords(self, value):
        self.frames[self.current_frame] = \
            np.asarray(value, dtype=float).reshape(len(self.symbols), 3)

    @property
    def atomic_numbers(self):
        # type: () -> np.ndarray
        return np.array([elements.atomic_number(s) for s in self.symbols],
                        dtype=int)

    def atoms(self):
        # type: () -> List[Tuple[str, float, float, float]]
        """Current frame as (symbol, x, y, z) tuples (for IO writers)."""
        c = self.coords
        return [(self.symbols[i], float(c[i, 0]), float(c[i, 1]), float(c[i, 2]))
                for i in range(self.n_atoms)]

    # ---------------------------------------------------------------- frames
    def set_frame(self, i):
        # type: (int) -> int
        """Clamp + switch the current frame; returns the frame actually set."""
        i = max(0, min(int(i), self.n_frames - 1))
        self.current_frame = i
        return i

    # ------------------------------------------------------------- geometry
    def centroid(self):
        # type: () -> np.ndarray
        if self.n_atoms == 0:
            return np.zeros(3)
        return self.coords.mean(axis=0)

    def bounding_radius(self):
        # type: () -> float
        """Radius (from the centroid) that encloses every atom's VdW sphere —
        what the camera 'fit' frames."""
        if self.n_atoms == 0:
            return 1.0
        d = np.linalg.norm(self.coords - self.centroid(), axis=1)
        vdw = np.array([elements.radius_vdw(z) for z in self.atomic_numbers])
        return float((d + vdw).max())

    # ---------------------------------------------------------------- bonds
    def connected_component(self, seeds):
        # type: (list) -> set
        """Every atom reachable by bonds from `seeds` (the seeds included).

        Edit mode uses this to keep an operation on the fragment you are
        actually working on: a molecule object can hold several disconnected
        pieces (a metal centre and a ligand you have not bonded yet), and
        aligning or dropping "the selection" should not drag an unrelated
        piece along with it.
        """
        adjacency = {}
        for bond in self.bonds:
            a, b = int(bond[0]), int(bond[1])
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)
        seen = set()
        stack = [int(s) for s in seeds]
        while stack:
            i = stack.pop()
            if i in seen or not (0 <= i < self.n_atoms):
                continue
            seen.add(i)
            stack.extend(adjacency.get(i, ()))
        return seen

    def fragments(self):
        # type: () -> list
        """All disconnected pieces, each a sorted list of atom indices."""
        remaining = set(range(self.n_atoms))
        out = []
        while remaining:
            seed = min(remaining)
            piece = self.connected_component([seed])
            out.append(sorted(piece))
            remaining -= piece
        return out

    def bonded_neighbors(self, i):
        # type: (int) -> List[int]
        out = []
        for a, b, _o in self.bonds:
            if a == i:
                out.append(b)
            elif b == i:
                out.append(a)
        return out

    def find_bond(self, i, j):
        # type: (int, int) -> Optional[int]
        """Index into self.bonds of the (i, j) bond, or None."""
        a, b = (i, j) if i < j else (j, i)
        for k, (x, y, _o) in enumerate(self.bonds):
            if x == a and y == b:
                return k
        return None
