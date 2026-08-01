"""Snapshot undo/redo (the OWB pattern): whole-scene deep snapshots, capped.

The app pushes a snapshot BEFORE each mutating operation; Ctrl+Z swaps the
current state for the last snapshot (and parks the current one on the redo
pile). Molecule scenes are small, so full copies beat command objects on
simplicity and correctness."""

from typing import List, Optional


class UndoStack:

    def __init__(self, limit=30):
        # type: (int) -> None
        self.limit = max(1, int(limit))
        self._undo = []     # type: List[object]
        self._redo = []     # type: List[object]

    def set_limit(self, limit):
        # type: (int) -> None
        """Change the depth (Settings). Oldest entries are trimmed at once so
        the new cap takes effect immediately rather than after N more edits."""
        self.limit = max(1, int(limit))
        while len(self._undo) > self.limit:
            self._undo.pop(0)
        while len(self._redo) > self.limit:
            self._redo.pop(0)

    def push(self, snapshot):
        # type: (object) -> None
        """Record pre-mutation state; any redo history is invalidated."""
        self._undo.append(snapshot)
        self._redo = []
        if len(self._undo) > self.limit:
            self._undo.pop(0)

    def discard_last(self):
        """Drop the most recent push (a mutation that was cancelled)."""
        if self._undo:
            self._undo.pop()

    def undo(self, current):
        # type: (object) -> Optional[object]
        """Trade `current` state for the last snapshot (None if empty)."""
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current):
        # type: (object) -> Optional[object]
        if not self._redo:
            return None
        self._undo.append(current)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        return self._redo.pop()

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def clear(self):
        self._undo = []
        self._redo = []
