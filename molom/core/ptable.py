"""Periodic-table geometry: where each element sits in the 18-column chart.

Data only, no Qt — the panel in `ui/periodic_table.py` just draws what this
describes, and the layout can be checked offline (every element placed exactly
once, nothing overlapping, the f-block detached the way every printed table
does it).

Rows are 1-7 for the main body; the lanthanides and actinides go on rows 9
and 10, leaving row 8 empty as the visual gap.
"""

from . import elements

COLUMNS = 18
MAIN_ROWS = 7
LANTHANIDE_ROW = 9
ACTINIDE_ROW = 10
ROWS = ACTINIDE_ROW

# Where the f-block is lifted out of, drawn as a placeholder cell.
LANTHANIDE_GAP = (6, 3)
ACTINIDE_GAP = (7, 3)


def layout():
    # type: () -> list
    """[(z, row, col), ...] 1-based, for Z = 1..118."""
    cells = [(1, 1, 1), (2, 1, 18)]
    for k, z in enumerate(range(3, 5)):            # Li Be
        cells.append((z, 2, 1 + k))
    for k, z in enumerate(range(5, 11)):           # B .. Ne
        cells.append((z, 2, 13 + k))
    for k, z in enumerate(range(11, 13)):          # Na Mg
        cells.append((z, 3, 1 + k))
    for k, z in enumerate(range(13, 19)):          # Al .. Ar
        cells.append((z, 3, 13 + k))
    for k, z in enumerate(range(19, 37)):          # K .. Kr
        cells.append((z, 4, 1 + k))
    for k, z in enumerate(range(37, 55)):          # Rb .. Xe
        cells.append((z, 5, 1 + k))
    cells.extend([(55, 6, 1), (56, 6, 2)])
    for k, z in enumerate(range(72, 87)):          # Hf .. Rn
        cells.append((z, 6, 4 + k))
    cells.extend([(87, 7, 1), (88, 7, 2)])
    for k, z in enumerate(range(104, 119)):        # Rf .. Og
        cells.append((z, 7, 4 + k))
    for k, z in enumerate(range(57, 72)):          # La .. Lu
        cells.append((z, LANTHANIDE_ROW, 3 + k))
    for k, z in enumerate(range(89, 104)):         # Ac .. Lr
        cells.append((z, ACTINIDE_ROW, 3 + k))
    return cells


def text_is_dark(z):
    # type: (int) -> bool
    """True when a cell painted in this element's colour wants BLACK text.

    Rec. 601 luma: the Jmol palette runs from near-white (H) to dark blue
    (F, Cs), so a fixed foreground is unreadable at one end or the other.
    """
    r, g, b = elements.color(z)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 140.0
