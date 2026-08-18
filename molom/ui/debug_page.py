"""Debug page: run the CIF pipeline one stage at a time and LOOK at it.

Christian, 2026-08-06: "I want to try an iterative debugging approach that
necessitates my step by step understanding of how unit cells are drawn."

The contract, and it is the whole point of the page:

* the loaded CIF TEXT is the only thing that persists;
* clicking any stage button runs the pipeline **from scratch** up to that
  stage — never forward from whatever happened to be on screen, so a picture
  can never contain something a later stage would have added;
* the stages are horizontal, in pipeline order, left to right.

The camera is deliberately NOT re-fitted between stages: comparing two stages
means seeing the same view twice, so the view only frames itself when a new
file is loaded.
"""

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLayout, QPlainTextEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core import pipeline

_STAGE_STYLE = """
QPushButton {
    background: rgba(56,56,56,230); color: rgba(228,228,228,230);
    border: 1px solid rgba(0,0,0,90); border-radius: 4px;
    padding: 4px 7px; font-size: 11px;
}
QPushButton:hover   { background: rgba(84,84,84,240); color: #fff; }
QPushButton:checked { background: rgba(70,115,175,240); color: #fff; }
QPushButton:disabled { color: rgba(150,150,150,120); }
"""


from .widgets import FlowLayout            # moved; re-exported here


class PipelinePage(QWidget):
    """Load a CIF as text, then run some pipeline up to any single stage.

    Shared by the 🐞 debug page (the real pipeline) and the 🧪 sandbox (an
    experimental one). Subclasses supply the stage list and the headings; the
    load / text / trace / freshness machinery is all here so the two cannot
    drift apart in behaviour while differing in algorithm.
    """

    #: (stage index, cif text) — the app rebuilds the scene from scratch.
    stage_requested = Signal(int, str)
    #: A new file was loaded, so the view may frame itself once.
    file_loaded = Signal(str)

    #: Subclass hooks.
    title = "CIF pipeline, one stage at a time"
    blurb_text = ("Load a file, then click a stage. Every click rebuilds from "
                  "the text below, so what you see is that stage and nothing "
                  "after it.")

    def __init__(self, stages, parent=None):
        super().__init__(parent)
        self.stages = list(stages)
        self.text = ""
        self._current = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        lay.addWidget(QLabel("<b>{}</b>".format(self.title)))
        blurb = QLabel(self.blurb_text)
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: rgba(200,200,200,170); font-size: 11px;")
        lay.addWidget(blurb)

        row = QHBoxLayout()
        self.load_button = QPushButton("Load .cif...")
        self.load_button.clicked.connect(lambda _c=False: self.load_file())
        row.addWidget(self.load_button)
        self.file_label = QLabel("no file loaded")
        self.file_label.setStyleSheet("color: rgba(200,200,200,170);")
        row.addWidget(self.file_label, 1)
        lay.addLayout(row)

        lay.addWidget(self._rule())
        self.extra_controls(lay)
        lay.addWidget(QLabel("Stages — click one to run up to it:"))
        holder = QWidget()
        self.flow = FlowLayout(holder)
        self.stage_buttons = []
        for index, stage in enumerate(self.stages):
            b = QPushButton("{} {}".format(index + 1, stage.label))
            b.setToolTip(stage.summary)
            b.setCheckable(True)
            b.setEnabled(False)
            b.setStyleSheet(_STAGE_STYLE)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, i=index: self.run_stage(i))
            self.flow.addWidget(b)
            self.stage_buttons.append(b)
        holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(holder)

        lay.addWidget(self._rule())
        self.trace = QPlainTextEdit()
        self.trace.setReadOnly(True)
        self.trace.setMinimumHeight(150)
        self.trace.setStyleSheet("font-family: Consolas, monospace; "
                                 "font-size: 11px;")
        self.trace.setPlaceholderText(
            "The per-stage trace appears here: how many atoms and bonds each "
            "step produced, and what it did.")
        lay.addWidget(self.trace, 1)

        lay.addWidget(QLabel("CIF text (edit and re-click a stage to test a "
                             "change):"))
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(110)
        self.editor.setStyleSheet("font-family: Consolas, monospace; "
                                  "font-size: 11px;")
        self.editor.setPlaceholderText("Load a .cif, or paste one here.")
        self.editor.textChanged.connect(self._on_text_edited)
        lay.addWidget(self.editor, 1)

    # ------------------------------------------------------------ helpers
    def extra_controls(self, lay):
        """Subclass hook: controls above the stage row. Nothing by default."""

    @staticmethod
    def _rule():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(255,255,255,28);")
        return line

    def _on_text_edited(self):
        self.text = self.editor.toPlainText()
        enabled = bool(self.text.strip())
        for b in self.stage_buttons:
            b.setEnabled(enabled)

    # -------------------------------------------------------------- public
    def load_file(self, path=None):
        # type: (str) -> None
        if not path:
            path, _f = QFileDialog.getOpenFileName(
                self, "Load a CIF for the debug pipeline", "",
                "Crystallographic Information File (*.cif *.mmcif);;"
                "All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            self.trace.setPlainText("Could not read that file:\n{}".format(exc))
            return
        self.set_text(text, name=path.replace("\\", "/").rsplit("/", 1)[-1])
        self.file_loaded.emit(path)

    def set_text(self, text, name=""):
        # type: (str, str) -> None
        self.text = text
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._on_text_edited()
        self.file_label.setText(name or "pasted text")
        self.trace.setPlainText(
            "Loaded. Click stage 1 to see the cell box on its own.")

    def run_stage(self, index):
        # type: (int) -> None
        self._current = int(index)
        for k, b in enumerate(self.stage_buttons):
            b.setChecked(k == index)
        self.stage_requested.emit(int(index), self.text)

    def show_result(self, result):
        """Print the trace the app got back from the pipeline."""
        lines = []
        if result.error:
            lines.append("ERROR: {}".format(result.error))
            lines.append("")
        width = max([len(s.label) for s in self.stages] + [5])
        for info in result.trace:
            lines.append("{}  atoms {:>6}   bonds {:>6}".format(
                info.label.ljust(width), info.atoms, info.bonds))
            for note in info.note.splitlines():
                lines.append("{}    {}".format(" " * width, note))
            lines.append("")
        if not result.trace:
            lines.append("Nothing ran.")
        self.trace.setPlainText("\n".join(lines).rstrip())


class DebugPage(PipelinePage):
    """The REAL pipeline, exactly as the app runs it."""

    def __init__(self, parent=None):
        super().__init__(pipeline.STAGES, parent)
