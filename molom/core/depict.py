"""The 2D skeletal picture of a molecule, as PNG bytes.

A search result list can show a formula and a molecular weight and still not
answer the question the user is asking. o-, m- and p-xylene share a formula
(C8H10), share a weight (106.16) and have names that differ by one character,
so the row that tells them apart is the PICTURE. That is the whole reason this
module exists.

**It draws from a SMILES, never from a Structure**, and that is deliberate
rather than incidental. Laying out a 2D depiction means running
`Compute2DCoords`, which WRITES a conformer - and handing it a molecule that
carries the 3D coordinates about to be imported is how you flatten the thing
you were trying to look at. Taking a string makes that mistake unrepresentable.

**PNG rather than SVG**, for round 62's reason: Qt's svg imageformat plugin is
a deployment detail we do not control, and the failure mode is a silently
missing picture. RDKit's Cairo backend hands back PNG bytes that
`QImage.loadFromData` reads with nothing extra installed.

UI-free and GL-free: this returns bytes, and whoever called it decides what to
do with them.
"""

from typing import Optional

#: Drawn at this size unless the caller says otherwise. Big enough that a
#: substituted ring is legible in a side panel, small enough to render in a
#: few milliseconds while somebody arrows down a list.
DEFAULT_SIZE = (300, 230)

#: Atom colours for a dark window. RDKit's default palette is tuned for black
#: ink on white paper, so carbon comes out black and vanishes against a dark
#: background - the bonds disappear and the heteroatoms float unconnected.
#: Values are 0-1 RGB, which is what `setAtomPalette` wants.
_DARK_PALETTE = {
    -1: (0.85, 0.85, 0.85),      # the default, i.e. carbon and anything unlisted
    0: (0.85, 0.85, 0.85),
    1: (0.85, 0.85, 0.85),       # H
    6: (0.85, 0.85, 0.85),       # C
    7: (0.45, 0.60, 1.00),       # N
    8: (1.00, 0.45, 0.45),       # O
    9: (0.55, 0.95, 0.55),       # F
    15: (1.00, 0.65, 0.35),      # P
    16: (1.00, 0.85, 0.35),      # S
    17: (0.45, 0.95, 0.45),      # Cl
    35: (0.85, 0.55, 0.35),      # Br
    53: (0.75, 0.55, 0.95),      # I
}


def available():
    # type: () -> bool
    """Can a picture be drawn at all?

    RDKit is a base dependency (round 86), but its Cairo backend is a build
    option rather than a guarantee, so the caller still has to be able to ask.
    """
    try:
        from rdkit.Chem.Draw import rdMolDraw2D
    except Exception:                                   # noqa: BLE001
        return False
    return hasattr(rdMolDraw2D, "MolDraw2DCairo")


def depict(smiles, size=DEFAULT_SIZE, dark=True, highlight_query=""):
    # type: (str, tuple, bool, str) -> Optional[bytes]
    """`smiles` as a skeletal formula, PNG bytes, or None.

    Returns None rather than raising for every failure - no RDKit, no Cairo,
    an unparseable SMILES, a structure with no atoms. A missing picture is a
    blank panel; an exception here would take down the list it sits beside.

    The background is TRANSPARENT so the panel keeps the dialog's own colour
    in either theme, and `dark` swaps the ink rather than the background:
    black-on-transparent is invisible on a dark window, which is the same
    failure as no picture at all but harder to diagnose.
    """
    text = (smiles or "").strip()
    if not text:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from rdkit.Chem.Draw import rdMolDraw2D
    except Exception:                                   # noqa: BLE001
        return None
    if not hasattr(rdMolDraw2D, "MolDraw2DCairo"):
        return None
    try:
        mol = Chem.MolFromSmiles(text)
        if mol is None or mol.GetNumAtoms() == 0:
            return None
        # A fresh molecule from a string, so there is no 3D conformer here to
        # destroy - see the module docstring for why that matters.
        AllChem.Compute2DCoords(mol)
        width, height = int(size[0]), int(size[1])
        drawer = rdMolDraw2D.MolDraw2DCairo(width, height)
        opts = drawer.drawOptions()
        opts.clearBackground = False        # transparent, not white
        opts.bondLineWidth = 2
        if dark:
            opts.setAtomPalette(_DARK_PALETTE)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
        drawer.FinishDrawing()
        data = drawer.GetDrawingText()
    except Exception:                                   # noqa: BLE001
        return None
    if isinstance(data, str):
        # Belt and braces: the Cairo backend returns bytes, the SVG one a str.
        data = data.encode("latin-1", "replace")
    return data or None
