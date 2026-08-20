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
    #: Emitted when the user clicks the Read Aloud button (which lives
    #: here, at the bar's right end — MainWindow owns the voice).
    read_requested = pyqtSignal()

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

        # One-step arrows flanking the slider (same moves as the
        # Alt+Left / Alt+Right keys, for mouse-first hands).
        self._back_btn = QPushButton("◀", self)
        self._back_btn.setFixedWidth(28)
        self._back_btn.setToolTip("Back one revision (Alt+Left)")
        self._back_btn.clicked.connect(lambda: self.step(-1))
        self._fwd_btn = QPushButton("▶", self)
        self._fwd_btn.setFixedWidth(28)
        self._fwd_btn.setToolTip("Forward one revision (Alt+Right)")
        self._fwd_btn.clicked.connect(lambda: self.step(+1))

        # Read Aloud sits at the bar's right end.  NoFocus is essential:
        # a focus-taking button steals the caret from the editor at the
        # very moment the reading position matters (the "jumps to the
        # beginning" lesson, Aug 2026).
        self.read_btn = QPushButton("🔊 Read", self)
        self.read_btn.setToolTip(
            "Read aloud from the cursor (or the selection) in a digital "
            "voice — click again to stop (Ctrl+Shift+R)")
        self.read_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.read_btn.clicked.connect(self.read_requested)

        layout.addWidget(QLabel("History:", self))
        layout.addWidget(self._back_btn)
        layout.addWidget(self._slider, stretch=1)
        layout.addWidget(self._fwd_btn)
        layout.addWidget(self._info)
        layout.addWidget(self._newest_btn)
        layout.addWidget(self._restore_btn)
        layout.addWidget(self.read_btn)

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

    #: The buttons' history-mode dress: while an old version is on
    #: screen these two are the ONLY way back to editing, so they must
    #: be impossible to miss ("no cursor showed up" — the time-travel
    #: trap, Aug 2026).
    _ACCENT = (
        "QPushButton { background: #2f6fce; color: white;"
        "  font-weight: bold; border-radius: 3px; padding: 3px 12px; }"
        "QPushButton:hover { background: #3d80e8; }"
    )

    def set_live(self, live: bool) -> None:
        """Live = viewing (and editing) the newest state.  The buttons only
        make sense while looking at the past — and while the past is on
        screen they light up blue, pointing the way back."""
        self._restore_btn.setEnabled(not live)
        self._newest_btn.setEnabled(not live)
        accent = "" if live else self._ACCENT
        self._restore_btn.setStyleSheet(accent)
        self._newest_btn.setStyleSheet(accent)

    def set_info(self, text: str) -> None:
        """Timestamp/origin caption next to the slider."""
        self._info.setText(text)

    # -- internals ----------------------------------------------------------

    def _on_value_changed(self, value: int) -> None:
        if not self._suppress:
            self.position_changed.emit(value)
