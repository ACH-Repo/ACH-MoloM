"""Blender N-panel, docked along the BOTTOM of the window so it pops in and
out like the outliner without stealing viewport width.

Shows the active molecule's transform (origin location + local-frame rotation
as Euler XYZ degrees) — or, when the edit-mode origin handle is picked up,
the ORIGIN's own transform, so the handle can be typed into as well as
dragged. No scale/dimensions: molecules don't scale.

The dock only displays and emits; the app applies the transforms and owns
undo."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDockWidget, QHBoxLayout, QLabel, QSizePolicy,
                               QWidget)

from .widgets import DragValueEdit

_AXIS = "XYZ"


class TransformDock(QDockWidget):

    drag_started = Signal()                       # one undo snapshot per scrub
    location_changed = Signal(int, float, bool)   # axis, value, final
    rotation_changed = Signal(int, float, bool)   # axis, degrees, final

    def __init__(self, parent=None):
        super().__init__("Transform", parent)
        self.setObjectName("transform_panel")
        self._obj_id = None                     # type: Optional[int]
        self.origin_mode = False
        w = QWidget(self)
        row = QHBoxLayout(w)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(6)
        self._title = QLabel("(no molecule)")
        self._title.setMinimumWidth(140)
        row.addWidget(self._title)

        self._loc = self._add_group(row, "Location:", step=0.02, decimals=3,
                                    signal=self.location_changed,
                                    tip="{} (A) — drag to scrub, click to "
                                        "type; arithmetic OK")
        row.addSpacing(12)
        self._rot = self._add_group(row, "Rotation:", step=0.4, decimals=1,
                                    signal=self.rotation_changed,
                                    tip="{} (deg, Euler XYZ)")
        row.addStretch(1)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setWidget(w)
        self.setFeatures(QDockWidget.DockWidgetClosable
                         | QDockWidget.DockWidgetMovable)
        self.setMaximumHeight(78)

    def _add_group(self, row, label, step, decimals, signal, tip):
        row.addWidget(QLabel(label))
        fields = []
        for axis in range(3):
            e = DragValueEdit(0.0, step=step, decimals=decimals)
            e.setToolTip(tip.format(_AXIS[axis]))
            e.setMaximumWidth(90)
            e.drag_started.connect(self.drag_started)
            e.value_changed.connect(
                lambda v, a=axis, s=signal: s.emit(a, v, False))
            e.value_committed.connect(
                lambda v, a=axis, s=signal: s.emit(a, v, True))
            fields.append(e)
            row.addWidget(e)
        return fields

    @property
    def obj_id(self):
        return self._obj_id

    def sync(self, obj, euler_deg, origin_mode=False):
        # type: (Optional[object], Optional[tuple], bool) -> None
        """Refresh from the active object (None = disable). `origin_mode`
        labels the fields as the origin's own transform."""
        self.origin_mode = bool(origin_mode)
        if obj is None:
            self._obj_id = None
            self._title.setText("(no molecule)")
            for e in self._loc + self._rot:
                e.set_value(0.0)
                e.setEnabled(False)
            return
        self._obj_id = obj.id
        self._title.setText("{}{}".format(
            obj.name, "  —  ORIGIN" if self.origin_mode else ""))
        for k in range(3):
            self._loc[k].setEnabled(True)
            self._rot[k].setEnabled(True)
            self._loc[k].set_value(float(obj.origin[k]))
            self._rot[k].set_value(float(euler_deg[k]))
