"""Preferences > Add-ons — Blender's add-on list, with tick boxes.

Lists everything found in the bundled folder and in `~/.molom/addons/`, with
its description, version, author and where it came from. Ticking one loads and
registers it immediately; unticking marks it off for the next launch, because
a live teardown is only as good as the add-on's own `unregister()` and MoloM
cannot enforce that.
"""
import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..core import addons as addons_mod


class AddOnsDialog(QDialog):
    """Enable and disable add-ons. Modeless, like Settings."""

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle("Add-ons")
        self.resize(560, 480)
        lay = QVBoxLayout(self)

        blurb = QLabel(
            "Add-ons extend MoloM. They run with the same access the "
            "application has, so only enable ones you trust — or wrote.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: rgba(200,200,200,180);")
        lay.addWidget(blurb)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        self._holder = QWidget()
        self._list = QVBoxLayout(self._holder)
        self._list.setSpacing(10)
        area.setWidget(self._holder)
        lay.addWidget(area, 1)

        row = QHBoxLayout()
        folder = QPushButton("Open user add-ons folder")
        folder.clicked.connect(lambda _c=False: self._open_folder())
        row.addWidget(folder)
        rescan = QPushButton("Rescan")
        rescan.clicked.connect(lambda _c=False: self.rebuild())
        row.addWidget(rescan)
        row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        lay.addWidget(buttons)
        self.rebuild()

    # ---------------------------------------------------------------- build
    def rebuild(self):
        while self._list.count():
            item = self._list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        manager = self.window.addons
        manager.refresh()
        if not manager.available:
            empty = QLabel("No add-ons found.\n\nDrop a .py file or a folder "
                           "with an __init__.py into the user add-ons folder "
                           "and press Rescan.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: rgba(200,200,200,140);")
            self._list.addWidget(empty)
        for info in manager.available:
            self._list.addWidget(self._card(info))
        self._list.addStretch(1)

    def _card(self, info):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        head = QHBoxLayout()
        tick = QCheckBox(info.name)
        tick.setChecked(self.window.addons.is_enabled(info.id))
        tick.setEnabled(not info.error)
        tick.setStyleSheet("font-weight: bold;")
        tick.toggled.connect(lambda on, i=info.id: self._toggle(i, on))
        head.addWidget(tick)
        head.addStretch(1)
        tag = QLabel("bundled" if info.bundled else "user")
        tag.setStyleSheet("color: rgba(200,200,200,120); font-size: 10px;")
        head.addWidget(tag)
        lay.addLayout(head)

        if info.description:
            text = QLabel(info.description)
            text.setWordWrap(True)
            text.setStyleSheet("color: rgba(210,210,210,180); font-size: 11px;")
            lay.addWidget(text)

        bits = []
        if info.version:
            bits.append("v" + ".".join(str(v) for v in info.version))
        if info.author:
            bits.append(info.author)
        bits.append(info.path)
        meta = QLabel("  ·  ".join(bits))
        meta.setWordWrap(True)
        meta.setStyleSheet("color: rgba(180,180,180,110); font-size: 10px;")
        lay.addWidget(meta)

        problem = info.error or self.window.addons.errors.get(info.id, "")
        if problem:
            bad = QLabel(problem.strip().splitlines()[-1]
                         if problem.strip() else "")
            bad.setWordWrap(True)
            bad.setStyleSheet("color: rgb(230,120,110); font-size: 10px;")
            bad.setToolTip(problem)
            lay.addWidget(bad)

        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(255,255,255,20);")
        lay.addWidget(line)
        return box

    # --------------------------------------------------------------- action
    def _toggle(self, addon_id, on):
        window = self.window
        if on:
            ok, message = window.addons.enable(addon_id, window)
            if not ok:
                window.statusBar().showMessage(
                    "Add-on '{}' failed to load — see Add-ons".format(
                        addon_id), 8000)
            else:
                window.statusBar().showMessage(
                    "Enabled add-on '{}'".format(addon_id), 5000)
        else:
            window.addons.disable(addon_id, window)
            window.statusBar().showMessage(
                "Disabled add-on '{}' (restart to remove it fully)".format(
                    addon_id), 6000)
        window.save_enabled_addons()
        self.rebuild()

    def _open_folder(self):
        path = addons_mod.user_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            return
        if sys.platform.startswith("win"):
            os.startfile(path)                       # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])         # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", path])     # noqa: S603,S607
