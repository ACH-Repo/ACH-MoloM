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

    def __init__(self, parent=None):
        super().__init__("Optimize", parent)
        self.setObjectName("optimize_panel")
        w = QWidget(self)
        form = QFormLayout(w)
        form.setContentsMargins(10, 8, 10, 8)

        self.task_combo = QComboBox()
        self.task_combo.addItem("Optimize", TASK_ALL)
        self.task_combo.addItem("Optimize selection (freeze rest)",
                                TASK_SELECTION)
        form.addRow("Task:", self.task_combo)

        self.method_combo = QComboBox()
        for key, label in forcefield.METHODS:
            self.method_combo.addItem(label, key)
        self.method_combo.setCurrentIndex(0)
        form.addRow("Method:", self.method_combo)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(10, 20000)
        self.steps_spin.setValue(500)
        self.steps_spin.setSingleStep(100)
        self.steps_spin.setSuffix(" steps")
        form.addRow("Max steps:", self.steps_spin)

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

    def _emit_start(self):
        self.start_requested.emit(self.task_combo.currentData(),
                                  self.method_combo.currentData(),
                                  int(self.steps_spin.value()))

    def set_running(self, running, message=""):
        self.start_btn.setEnabled(not running)
        self.progress.setVisible(running)
        if message:
            self.status.setText(message)
