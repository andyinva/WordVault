"""
help_dialog.py — the Help window (toolbar button / F1).

Renders docs/help.md — a plain-language guide in two parts: the concept
(what WordVault is and why), then the use (how to do things).  The
document is ordinary Markdown in the repository, so contributors can
improve the help without touching any code.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout

#: repo_root/docs/help.md  (this file is wordvault/editor/help_dialog.py)
_HELP_FILE = Path(__file__).resolve().parents[2] / "docs" / "help.md"

_FALLBACK = (
    "# WordVault Help\n\nThe help document (docs/help.md) was not found "
    "next to the program.\n\nIn short: WordVault records a revision every "
    "time you pause typing; the History bar under the editor moves through "
    "them; Ctrl+Shift+F searches the whole library; Ctrl+M marks passages "
    "to gather into new documents; and the Settings button can encrypt "
    "your library."
)


class HelpDialog(QDialog):
    """A read-only viewer for the help document."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WordVault Help")
        self.resize(700, 640)

        viewer = QTextBrowser(self)
        viewer.setOpenExternalLinks(True)
        try:
            viewer.setMarkdown(_HELP_FILE.read_text(encoding="utf-8"))
        except OSError:
            viewer.setMarkdown(_FALLBACK)

        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(viewer)
        layout.addWidget(close_btn)
