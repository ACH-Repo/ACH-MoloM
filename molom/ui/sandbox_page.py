"""Sandbox page: the same first stages, then a different completion rule.

Christian, 2026-08-06 — a place to try an alternative crystal algorithm and
look at it stage by stage. Nothing the app draws for real goes through here;
the shipping pipeline is the 🐞 page next door.

Cell / Sites / Operators / Wrap / Dedupe are literally `core.pipeline`'s own
stages (the sandbox calls it), so the part not under experiment cannot drift.
The divergence starts at **Bonds**, which takes connectivity from the periodic
graph rather than from the wrapped coordinates, and at **Molecules**, which
completes every fragment reaching into the cell instead of relocating it.
"""

from PySide6.QtWidgets import QCheckBox

from .debug_page import PipelinePage
from ..core import sandbox


class SandboxPage(PipelinePage):
    """Wrap, then complete outwards — Mercury's packing rule."""

    title = "Sandbox — an alternative algorithm"
    blurb_text = (
        "Cell / Sites / Operators / Wrap / Dedupe are the debug page's own. "
        "Then it diverges: bonds come from the periodic graph, and every "
        "fragment reaching into the cell is drawn WHOLE rather than moved "
        "bodily inside it.")

    def __init__(self, parent=None):
        super().__init__(sandbox.STAGES, parent)

    def extra_controls(self, lay):
        self.outside = QCheckBox("Draw atoms outside the cell boundary")
        self.outside.setChecked(True)
        self.outside.setToolTip(
            "On: a molecule with any atom in the cell is completed outwards, "
            "so a fullerene split across four corners becomes four whole "
            "fullerenes.\n"
            "Off: the same connectivity, but only the atoms inside the box "
            "are drawn.")
        self.outside.toggled.connect(self._rerun)
        lay.addWidget(self.outside)

        self.grow_copies = QCheckBox("Complete the boundary copies too")
        self.grow_copies.setToolTip(
            "Off: only the atoms the wrap placed complete their coordination "
            "outwards. On: every boundary copy does too, so an atom drawn at "
            "eight corners is completed eight times.\n\n"
            "This is a real trade-off, measured. On makes a dense oxide look "
            "fuller (1547149: 21 -> 51 atoms) and makes the magnesium "
            "pyrophosphates balloon (60 -> 351 instead of 189). The ZIFs are "
            "unaffected either way.")
        self.grow_copies.toggled.connect(self._rerun)
        lay.addWidget(self.grow_copies)

    def options(self):
        # type: () -> dict
        """Everything `sandbox.run` needs, so the app does not have to know."""
        return {"outside": self.outside.isChecked(),
                "grow_from_copies": self.grow_copies.isChecked()}

    def _rerun(self, _checked=False):
        if self._current >= 0 and self.text.strip():
            self.run_stage(self._current)
