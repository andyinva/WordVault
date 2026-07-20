"""
timeline.py — TimelineBar: the time-travel control (roadmap stage 3).

A slim bar that sits under the editor pane:

    History: [====|=========]  2026-07-19 14:03:22 · typing  [Newest] [Restore]

The slider has one position per revision (oldest on the left, newest on
the right).  The bar is deliberately "dumb": it knows nothing about the
database or the walker — it only reports positions and button clicks via
signals.  All time-travel logic lives in MainWindow, which owns the
DocumentStore (same layering rule as everywhere else in the editor).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


class TimelineBar(QWidget):
    """Slider + info label + Newest/Restore buttons for one document."""

    #: Emitted when the user moves to a revision index (0 = oldest).
    position_changed = pyqtSignal(int)
    #: Emitted when the user clicks "Restore this version".
    restore_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setTracking(True)  # update the view while dragging
        self._slider.valueChanged.connect(self._on_value_changed)

        # Shows the timestamp/origin of the revision being viewed.
        self._info = QLabel("", self)

        # Jump back to the newest revision (leave history mode).
        self._newest_btn = QPushButton("Newest", self)
        self._newest_btn.clicked.connect(self.go_newest)

        # Bring the viewed old state back as a NEW revision (append-only —
        # DESIGN.md section 5: history is never rewritten).
        self._restore_btn = QPushButton("Restore this version", self)
        self._restore_btn.clicked.connect(self.restore_requested)

        layout.addWidget(QLabel("History:", self))
        layout.addWidget(self._slider, stretch=1)
        layout.addWidget(self._info)
        layout.addWidget(self._newest_btn)
        layout.addWidget(self._restore_btn)

        # While set_range() adjusts the slider programmatically we must not
        # re-broadcast the change as if the user dragged it.
        self._suppress = False
        self.set_live(True)

    # -- API used by MainWindow ---------------------------------------------

    def set_range(self, revision_count: int, position: int) -> None:
        """Resize the slider to `revision_count` stops and park it at
        `position`, WITHOUT emitting position_changed."""
        self._suppress = True
        try:
            self._slider.setMaximum(max(revision_count - 1, 0))
            self._slider.setValue(position)
        finally:
            self._suppress = False
        self.setEnabled(revision_count > 0)

    def position(self) -> int:
        return self._slider.value()

    def step(self, delta: int) -> None:
        """Move one stop back (-1) or forward (+1) — the Alt+arrow keys.
        Emits position_changed exactly like a manual drag."""
        self._slider.setValue(self._slider.value() + delta)

    def go_newest(self) -> None:
        """Jump the slider to the newest revision."""
        self._slider.setValue(self._slider.maximum())

    def set_live(self, live: bool) -> None:
        """Live = viewing (and editing) the newest state.  The buttons only
        make sense while looking at the past."""
        self._restore_btn.setEnabled(not live)
        self._newest_btn.setEnabled(not live)

    def set_info(self, text: str) -> None:
        """Timestamp/origin caption next to the slider."""
        self._info.setText(text)

    # -- internals ----------------------------------------------------------

    def _on_value_changed(self, value: int) -> None:
        if not self._suppress:
            self.position_changed.emit(value)
