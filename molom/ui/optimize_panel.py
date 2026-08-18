"""Force-field clean-up dock — the "Auto Optimize" panel.

Task / Method / Steps / Start, mirroring the layout Christian pointed at.
Defaults follow ORCA Workbench's coordinate pre-optimisation (and Avogadro):
MMFF94, falling back to UFF when MMFF has no parameters.

The dock only collects settings and emits; the app runs the optimisation in
a worker thread (a few hundred MMFF steps on a big molecule would otherwise
freeze the window) and owns undo.
"""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDockWidget, QFormLayout, QLabel,
                               QProgressBar, QPushButton, QSpinBox, QWidget)

from ..core import forcefield

TASK_ALL = "all"
TASK_SELECTION = "selection"


class OptimizeWorker(QThread):
    """Runs one force-field minimisation off the GUI thread."""

    done = Signal(object, object)      # (coords or None, info-or-error)

    def __init__(self, symbols, coords, bonds, method, steps, fixed,
                 parent=None):
        super().__init__(parent)
        self._args = (symbols, coords, bonds, method, steps, fixed)

    def run(self):
        symbols, coords, bonds, method, steps, fixed = self._args
        try:
            out, info = forcefield.optimize(symbols, coords, bonds,
                                            method=method, steps=steps,
                                            fixed=fixed)
        except forcefield.ForceFieldError as e:
            self.done.emit(None, str(e))
            return
        except Exception as e:          # a backend blew up unexpectedly
            self.done.emit(None, "{}: {}".format(type(e).__name__, e))
            return
        self.done.emit(out, info)


class OptimizeDock(QDockWidget):

    start_requested = Signal(str, str, int)     # task, method, steps
    species_changed = Signal(int, int)          # charge, multiplicity

    def __init__(self, parent=None):
        super().__init__("Optimize", parent)
        self.setObjectName("optimize_panel")
        self._loading = False        # see `show_species`
        w = QWidget(self)
        form = QFormLayout(w)
        form.setContentsMargins(10, 8, 10, 8)

        self.task_combo = QComboBox()
        self.task_combo.addItem("Optimize", TASK_ALL)
        self.task_combo.addItem("Optimize selection (freeze rest)",
                                TASK_SELECTION)
        form.addRow("Task:", self.task_combo)

        self.method_combo = QComboBox()
        self.refresh_methods()
        form.addRow("Method:", self.method_combo)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(10, 20000)
        self.steps_spin.setValue(500)
        self.steps_spin.setSingleStep(100)
        self.steps_spin.setSuffix(" steps")
        form.addRow("Max steps:", self.steps_spin)

        # CHARGE AND SPIN, because a semiempirical method needs them and a
        # force field does not - which is why nothing asked for them until
        # MOPAC arrived. Measured on Christian's own square-planar PtCl4:
        # optimised as neutral it holds 2.170 A, as the real [PtCl4]2- it goes
        # to 2.321 A against an experimental ~2.31. Same geometry, same method,
        # different species - so leaving this to a default of 0 silently
        # optimises something the user did not draw.
        #
        # They belong to the MOLECULE (`Structure.metadata`), not to the
        # panel: they are facts about the compound, they ride undo and
        # savefiles, and the SMILES importer already sets them where a name
        # implies a charge. The panel is only where they are visible at the
        # moment they matter.
        self.charge_spin = QSpinBox()
        self.charge_spin.setRange(-20, 20)
        self.charge_spin.setToolTip(
            "Net charge of the molecule. Used by semiempirical methods "
            "(MOPAC); force fields ignore it.")
        form.addRow("Charge:", self.charge_spin)

        self.mult_spin = QSpinBox()
        self.mult_spin.setRange(1, 11)
        self.mult_spin.setValue(1)
        self.mult_spin.setToolTip(
            "Spin multiplicity: 1 = singlet, 2 = doublet, 3 = triplet. Used "
            "by semiempirical methods; force fields ignore it.")
        form.addRow("Multiplicity:", self.mult_spin)
        self.charge_spin.valueChanged.connect(self._emit_species)
        self.mult_spin.valueChanged.connect(self._emit_species)

        self.start_btn = QPushButton("↓  Start")
        self.start_btn.clicked.connect(self._emit_start)
        form.addRow(self.start_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)        # busy indicator
        self.progress.setVisible(False)
        form.addRow(self.progress)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        form.addRow(self.status)

        have = forcefield.backends_available()
        if not any(have.values()):
            self.start_btn.setEnabled(False)
            self.status.setText(
                "No force-field backend found — install RDKit or OpenBabel.")
        self.setWidget(w)
        self.setFeatures(QDockWidget.DockWidgetClosable
                         | QDockWidget.DockWidgetMovable)

    def _emit_species(self, _value=0):
        if not self._loading:
            self.species_changed.emit(int(self.charge_spin.value()),
                                      int(self.mult_spin.value()))

    def show_species(self, charge, multiplicity):
        """Display the ACTIVE molecule's charge and spin.

        Guarded, because `setValue` emits `valueChanged` whether or not a hand
        moved it - and an unguarded refresh writes one molecule's charge onto
        the next as soon as you click a different row. That is round 30's
        TimelinePanel bug, and it is exactly the shape that keeps recurring.
        """
        self._loading = True
        try:
            self.charge_spin.setValue(int(charge or 0))
            self.mult_spin.setValue(max(1, int(multiplicity or 1)))
        finally:
            self._loading = False

    def refresh_methods(self):
        """Rebuild the Method list from `forcefield.all_methods()`.

        Called at construction and again whenever an ADD-ON registers or
        removes a method, because add-ons are enabled and disabled while the
        window is open (round 46) and a combo filled once at startup would
        either miss a new method or keep offering one that has just gone.
        The current selection is preserved where it survives, so enabling an
        unrelated add-on cannot silently reset the user back to MMFF94.
        """
        keep = self.method_combo.currentData()
        self.method_combo.blockSignals(True)
        self.method_combo.clear()
        for key, label in forcefield.all_methods():
            self.method_combo.addItem(label, key)
        index = self.method_combo.findData(keep)
        self.method_combo.setCurrentIndex(max(index, 0))
        self.method_combo.blockSignals(False)

    def _emit_start(self):
        self.start_requested.emit(self.task_combo.currentData(),
                                  self.method_combo.currentData(),
                                  int(self.steps_spin.value()))

    def set_running(self, running, message=""):
        self.start_btn.setEnabled(not running)
        self.progress.setVisible(running)
        if message:
            self.status.setText(message)
